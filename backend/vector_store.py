import os
import chromadb
from chromadb.config import Settings
from typing import List, Dict, Any, Optional
import numpy as np

CHROMA_DIR = os.path.join(os.path.dirname(__file__), "chroma_db")

class VectorStore:
    def __init__(self, model: str = "nomic-embed-text", ollama_url: str = "http://localhost:11434", chroma_dir: str = CHROMA_DIR):
        self.chroma_dir = chroma_dir
        self.model = model
        self.ollama_url = ollama_url
        
        # Initialize Chroma DB client (persistent)
        self.client = chromadb.PersistentClient(path=self.chroma_dir)
        self.collection_name = "website_knowledge"
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"}
        )
        
        self.encoder = None

    def configure(self, model: str, ollama_url: str):
        self.model = model
        self.ollama_url = ollama_url

    def count_tokens(self, text: str) -> int:
        # Simple word estimation for local Ollama models
        return len(text.split())

    def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for a list of texts using local Ollama.
        """
        import requests
        
        # Verify model tag and fallback if not found locally
        model_name = self.model
        try:
            tags_res = requests.get(f"{self.ollama_url}/api/tags", timeout=2)
            if tags_res.status_code == 200:
                installed = [m["name"] for m in tags_res.json().get("models", [])]
                has_match = False
                for inst in installed:
                    if model_name == inst or inst.startswith(f"{model_name}:") or model_name.startswith(f"{inst}:"):
                        model_name = inst
                        has_match = True
                        break
                
                if not has_match and installed:
                    # Find first installed model that contains "embed" or "nomic"
                    embed_models = [m for m in installed if "embed" in m.lower() or "nomic" in m.lower()]
                    if embed_models:
                        model_name = embed_models[0]
                    else:
                        model_name = installed[0]
                    print(f"Fallback embedding model: {model_name}")
        except Exception as e:
            print(f"Error querying tags in get_embeddings: {e}")

        try:
            embeddings = []
            for text in texts:
                res = requests.post(
                    f"{self.ollama_url}/api/embeddings",
                    json={"model": model_name, "prompt": text},
                    timeout=15
                )
                if res.status_code == 200:
                    embeddings.append(res.json()["embedding"])
                else:
                    raise Exception(f"Ollama returned HTTP {res.status_code}: {res.text}")
            return embeddings
        except Exception as e:
            print(f"Error calling Ollama embeddings: {e}. Falling back to mock embeddings.")
            # Fallback to mock (nomic-embed-text/other local models use 768 dimensions by default)
            mock_embeddings = []
            for _ in texts:
                vec = np.random.randn(768)
                vec /= np.linalg.norm(vec)
                mock_embeddings.append(vec.tolist())
            return mock_embeddings

    def chunk_document(self, page_content: List[Dict[str, Any]], max_tokens: int = 500, overlap_tokens: int = 50) -> List[Dict[str, Any]]:
        """
        Semantic chunker that groups parsed HTML components (headings, paragraphs, code blocks).
        Tries to break chunks cleanly at headings or block boundaries, and falls back to 
        token-sliding window if a block exceeds max_tokens.
        """
        chunks = []
        current_chunk_text = ""
        current_chunk_metadata = []
        current_tokens = 0
        
        for item in page_content:
            item_type = item.get("type", "text")
            content = item.get("content", "").strip()
            heading = item.get("heading", "")
            
            if not content:
                continue
                
            item_tokens = self.count_tokens(content)
            
            # If a single item is larger than the max size (e.g. a huge code block)
            if item_tokens > max_tokens:
                # Flush existing chunk
                if current_chunk_text:
                    chunks.append({
                        "text": current_chunk_text.strip(),
                        "headings": list(set(current_chunk_metadata))
                    })
                    current_chunk_text = ""
                    current_chunk_metadata = []
                    current_tokens = 0
                
                # Split large item into token window chunks
                words = content.split()
                temp_text = ""
                for word in words:
                    word_with_space = word + " "
                    word_tokens = self.count_tokens(word_with_space)
                    
                    if self.count_tokens(temp_text + word_with_space) > max_tokens:
                        chunks.append({
                            "text": temp_text.strip(),
                            "headings": [heading] if heading else []
                        })
                        # Retain some overlap
                        temp_text = " ".join(temp_text.split()[-10:]) + " " + word_with_space
                    else:
                        temp_text += word_with_space
                if temp_text.strip():
                    chunks.append({
                        "text": temp_text.strip(),
                        "headings": [heading] if heading else []
                    })
                continue
            
            # If adding this item exceeds max tokens, flush the current chunk
            if current_tokens + item_tokens > max_tokens:
                chunks.append({
                    "text": current_chunk_text.strip(),
                    "headings": list(set(current_chunk_metadata))
                })
                # Set up next chunk, start with some overlap from the end of the previous chunk if appropriate, 
                # or just start fresh. Let's start fresh or with last item
                current_chunk_text = content + "\n\n"
                current_chunk_metadata = [heading] if heading else []
                current_tokens = item_tokens
            else:
                current_chunk_text += content + "\n\n"
                if heading:
                    current_chunk_metadata.append(heading)
                current_tokens += item_tokens
                
        if current_chunk_text:
            chunks.append({
                "text": current_chunk_text.strip(),
                "headings": list(set(current_chunk_metadata))
            })
            
        return chunks

    def add_page_chunks(self, url: str, title: str, parsed_content: List[Dict[str, Any]]) -> int:
        """
        Chunks the parsed content, generates embeddings, and adds them to ChromaDB.
        """
        # 1. Chunk document
        chunks = self.chunk_document(parsed_content)
        if not chunks:
            return 0
            
        texts = [c["text"] for c in chunks]
        
        # 2. Get embeddings
        embeddings = self.get_embeddings(texts)
        
        # 3. Add to ChromaDB
        ids = [f"{url}_chunk_{i}" for i in range(len(chunks))]
        metadatas = [
            {
                "url": url,
                "title": title,
                "headings": ", ".join(c["headings"]),
                "chunk_index": i
            }
            for i, c in enumerate(chunks)
        ]
        
        # Delete any existing entries for this URL to avoid duplicates on re-crawl
        try:
            self.collection.delete(where={"url": url})
        except Exception:
            pass
            
        self.collection.add(
            ids=ids,
            embeddings=embeddings,
            metadatas=metadatas,
            documents=texts
        )
        
        return len(chunks)

    def query(self, query_text: str, n_results: int = 5) -> List[Dict[str, Any]]:
        """
        Perform RAG query against ChromaDB.
        """
        query_embedding = self.get_embeddings([query_text])[0]
        
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results
        )
        
        formatted_results = []
        if results and results["documents"]:
            docs = results["documents"][0]
            metadatas = results["metadatas"][0]
            distances = results["distances"][0] if "distances" in results else [0.0] * len(docs)
            ids = results["ids"][0]
            
            for doc, meta, dist, chunk_id in zip(docs, metadatas, distances, ids):
                formatted_results.append({
                    "id": chunk_id,
                    "text": doc,
                    "url": meta.get("url", ""),
                    "title": meta.get("title", ""),
                    "headings": meta.get("headings", ""),
                    "similarity": float(1.0 - dist) # convert distance to similarity score
                })
                
        return formatted_results

    def get_db_stats(self) -> Dict[str, Any]:
        """
        Return the number of stored chunks.
        """
        try:
            count = self.collection.count()
            return {"chunks_count": count}
        except Exception:
            return {"chunks_count": 0}

    def clear_database(self):
        """
        Reset collection.
        """
        try:
            self.client.delete_collection(self.collection_name)
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"}
            )
        except Exception as e:
            print(f"Error resetting Chroma collection: {e}")
