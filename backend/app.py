from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import os
import asyncio
import json
from typing import List, Dict, Any, Optional

from .db import Database
from .vector_store import VectorStore
from .crawler import Crawler
from .safety import SafetyMonitor

app = FastAPI(title="WebIntel API")

# Enable CORS for frontend development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Database and VectorStore
db = Database()
stored_embedding_model = db.get_state("embedding_model", "nomic-embed-text")
stored_ollama_url = db.get_state("ollama_url", "http://localhost:11434")

vector_store = VectorStore(
    model=stored_embedding_model,
    ollama_url=stored_ollama_url
)

# Global lists for active WebSockets
active_websockets: List[WebSocket] = []

def broadcast_stats(stats: Dict[str, Any]):
    """
    Called by crawler to broadcast progress to all UI clients.
    """
    message = json.dumps({"type": "progress", "data": stats})
    # Run in the active asyncio loop
    loop = asyncio.get_event_loop()
    if loop.is_running():
        for ws in active_websockets:
            loop.create_task(ws.send_text(message))

# Initialize Crawler
crawler = Crawler(db, vector_store, broadcast_stats)

# Safety stop callback
def on_emergency_stop(reason: str):
    db.log("WARNING", f"EMERGENCY INTERRUPT: {reason}")
    # Run stop synchronously/asyncly
    loop = asyncio.get_event_loop()
    if loop.is_running():
        loop.create_task(crawler.stop(reason=f"Emergency: {reason}"))
    else:
        asyncio.run(crawler.stop(reason=f"Emergency: {reason}"))

# Start Safety Monitor
safety_monitor = SafetyMonitor(on_emergency_stop)
safety_monitor.start()

# --- Pydantic Schemas ---
class StartRequest(BaseModel):
    url: str
    cdp_url: Optional[str] = None

class SettingsRequest(BaseModel):
    ollama_url: Optional[str] = "http://localhost:11434"
    llm_model: Optional[str] = "llama3"
    embedding_model: Optional[str] = "nomic-embed-text"

class ChatRequest(BaseModel):
    message: str
    model: Optional[str] = "llama3"

class ControlRequest(BaseModel):
    action: str  # pause, resume, stop, reset

# --- REST Routes ---

@app.get("/api/settings")
def get_settings():
    return {
        "ollama_url": db.get_state("ollama_url", "http://localhost:11434"),
        "llm_model": db.get_state("llm_model", "llama3"),
        "embedding_model": db.get_state("embedding_model", "nomic-embed-text"),
        "start_url": db.get_state("start_url", "")
    }

@app.post("/api/settings")
def save_settings(req: SettingsRequest):
    db.set_state("ollama_url", req.ollama_url)
    db.set_state("llm_model", req.llm_model)
    db.set_state("embedding_model", req.embedding_model)
    
    vector_store.configure(
        model=req.embedding_model,
        ollama_url=req.ollama_url
    )
    db.log("INFO", "Settings updated successfully.")
    return {"status": "success"}

@app.get("/api/ollama/models")
def get_ollama_models():
    ollama_url = db.get_state("ollama_url", "http://localhost:11434")
    try:
        import requests
        res = requests.get(f"{ollama_url}/api/tags", timeout=3)
        if res.status_code == 200:
            models = [m["name"] for m in res.json().get("models", [])]
            return {"models": models}
    except Exception:
        pass
    # Fallback default models list
    return {"models": ["llama3:latest", "mistral:latest", "nomic-embed-text:latest", "all-minilm:latest"]}

@app.get("/api/stats")
def get_stats():
    return crawler.get_stats()

@app.get("/api/logs")
def get_logs(limit: int = 50):
    return db.get_logs(limit=limit)

@app.get("/api/sitemap")
def get_sitemap():
    pages = db.get_all_pages()
    links = db.get_sitemap()
    return {
        "pages": pages,
        "links": links
    }

@app.post("/api/start")
async def start_learning(req: StartRequest):
    # Verify starting URL
    if not req.url.startswith("http://") and not req.url.startswith("https://"):
        raise HTTPException(status_code=400, detail="Invalid URL format. Must start with http:// or https://")
        
    await crawler.start(req.url, cdp_url=req.cdp_url)
    return {"status": "started"}

@app.post("/api/control")
async def control_crawler(req: ControlRequest):
    action = req.action.lower()
    if action == "pause":
        await crawler.pause()
    elif action == "resume":
        await crawler.resume()
    elif action == "stop":
        await crawler.stop()
    elif action == "reset":
        await crawler.stop(reason="Resetting DB")
        db.reset_crawled_data()
        vector_store.clear_database()
        db.log("INFO", "Database reset and cleared.")
    else:
        raise HTTPException(status_code=400, detail=f"Unknown control action: {action}")
    return {"status": "success"}

@app.get("/api/chat/history")
def get_chat_history():
    return db.get_chat_history()

@app.post("/api/chat/clear")
def clear_chat_history():
    db.clear_chat_history()
    db.log("INFO", "Chat history cleared.")
    return {"status": "success"}

@app.post("/api/chat")
def run_chat(req: ChatRequest):
    user_msg = req.message.strip()
    if not user_msg:
        raise HTTPException(status_code=400, detail="Empty query message")
        
    db.add_chat_msg("user", user_msg)
    
    # 1. Retrieve related document chunks
    results = vector_store.query(user_msg, n_results=5)
    
    ollama_url = db.get_state("ollama_url", "http://localhost:11434")
    llm_model = db.get_state("llm_model", "llama3")
    
    # Verify model is installed in local tags; fallback if not found
    try:
        import requests
        tags_res = requests.get(f"{ollama_url}/api/tags", timeout=2)
        if tags_res.status_code == 200:
            installed = [m["name"] for m in tags_res.json().get("models", [])]
            has_match = False
            for inst in installed:
                if llm_model == inst or inst.startswith(f"{llm_model}:") or llm_model.startswith(f"{inst}:"):
                    llm_model = inst
                    has_match = True
                    break
            
            if not has_match and installed:
                # Fallback: find first installed model that is not an embedding model
                chat_models = [m for m in installed if "embed" not in m.lower()]
                if chat_models:
                    old_model = llm_model
                    llm_model = chat_models[0]
                    db.log("WARNING", f"Model '{old_model}' not found in Ollama. Falling back to '{llm_model}'.")
                else:
                    old_model = llm_model
                    llm_model = installed[0]
                    db.log("WARNING", f"Model '{old_model}' not found. Falling back to '{llm_model}'.")
    except Exception as e:
        print(f"Error resolving installed Ollama models: {e}")
    
    # Assemble LLM prompt
    context_str = ""
    for i, res in enumerate(results):
        context_str += f"Source [{i+1}] - Title: {res['title']} | Section: {res['headings']} | URL: {res['url']}\nContent: {res['text']}\n\n"
        
    system_prompt = (
        "You are the AI Website Learning Assistant. Answer the user's question using the retrieved documentation context below.\n"
        "Rules:\n"
        "1. Answer the question thoroughly, drawing information ONLY from the provided context.\n"
        "2. Cite your sources in the text using [Source Name](URL) markdown links.\n"
        "3. If the context does not contain enough information to answer the question, say clearly that you do not have that information in your knowledge base.\n"
        "4. NEVER hallucinate or assume facts that are not written in the context.\n"
    )

    try:
        import requests
        response = requests.post(
            f"{ollama_url}/api/chat",
            json={
                "model": llm_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Retrieved Context:\n{context_str}\n\nQuestion: {user_msg}"}
                ],
                "stream": False
            },
            timeout=30
        )
        if response.status_code == 200:
            assistant_response = response.json()["message"]["content"]
            db.add_chat_msg("assistant", assistant_response)
            return {
                "response": assistant_response,
                "sources": results
            }
        else:
            raise Exception(f"Ollama returned HTTP {response.status_code}: {response.text}")
    except Exception as e:
        error_msg = f"Failed calling local Ollama chat API: {e}"
        db.log("ERROR", error_msg)
        fallback_res = f"An error occurred while communicating with the local Ollama LLM: {e}"
        return {
            "response": fallback_res,
            "sources": results
        }

# --- WebSockets Server ---

@app.websocket("/ws/progress")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_websockets.append(websocket)
    # Send current stats immediately
    await websocket.send_text(json.dumps({
        "type": "progress",
        "data": crawler.get_stats()
    }))
    try:
        while True:
            # Keep connection open, ignore incoming client WS frames for now
            await websocket.receive_text()
    except WebSocketDisconnect:
        active_websockets.remove(websocket)
    except Exception:
        if websocket in active_websockets:
            active_websockets.remove(websocket)

# --- Mount Production Static Files ---
frontend_dist = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "dist"))
if os.path.exists(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="static")
