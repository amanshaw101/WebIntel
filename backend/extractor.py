from bs4 import BeautifulSoup, Tag
import hashlib
from typing import List, Dict, Any, Tuple
import re

class ContentExtractor:
    @staticmethod
    def clean_html(html_content: str) -> BeautifulSoup:
        soup = BeautifulSoup(html_content, "html.parser")
        
        # Remove interactive/non-content elements
        for element in soup(["script", "style", "noscript", "iframe", "svg", "header", "footer", "nav"]):
            element.decompose()
            
        # Remove elements with class/id containing navbar, sidebar, footer, menu, ad, etc.
        for element in soup.find_all(True):
            if not getattr(element, "attrs", None):
                continue
            attrs_str = " ".join([str(v) for v in element.attrs.values() if v is not None])
            if re.search(r"(sidebar|navbar|footer|menu|nav-links|header|ad-container|cookie)", attrs_str, re.I):
                # But don't decompose the main content block if it happens to match a keyword
                if element.name not in ("main", "article"):
                    element.decompose()
                    
        return soup

    @staticmethod
    def find_main_content(soup: BeautifulSoup) -> Tag:
        """
        Locates the main documentation article or body, skipping global chrome.
        """
        # Common semantic tags first
        for tag in ["article", "main", "[role='main']"]:
            found = soup.select_one(tag)
            if found:
                return found
                
        # Common layout classes/ids
        selectors = [
            "#content", ".content", "#main-content", ".main-content", 
            ".documentation", ".docs-content", ".markdown-body",
            "#doc-content", ".doc-content", "article", "main"
        ]
        for sel in selectors:
            found = soup.select_one(sel)
            if found:
                return found
                
        # Fallback to body
        return soup.body if soup.body else soup

    @classmethod
    def extract(cls, html_content: str, url: str) -> Tuple[str, List[Dict[str, Any]], str]:
        """
        Extracts structured page content: title, structured blocks, and page content hash.
        Returns: (title, list of blocks, hash_string)
        """
        soup = cls.clean_html(html_content)
        main_content = cls.find_main_content(soup)
        
        # Get Page Title
        title_tag = soup.find("title")
        title = title_tag.get_text().strip() if title_tag else "Untitled Documentation"
        
        # Clean title (remove suffixes like " | Node.js v20.0.0")
        if " | " in title:
            title = title.split(" | ")[0]
        elif " - " in title:
            title = title.split(" - ")[0]
            
        blocks: List[Dict[str, Any]] = []
        current_heading = ""
        
        # Traverse elements inside the main content container
        for element in main_content.find_all(["h1", "h2", "h3", "h4", "p", "pre", "table", "ul", "ol"]):
            # Ignore nested items that were already processed inside a parent structure (like ul/table)
            # if we check parents and find we've already processed it, we can skip. But BeautifulSoup
            # find_all returns flat list. To handle nested elements, we can check if it is within another pre, table, etc.
            if element.find_parent(["pre", "table"]):
                continue
                
            tag_name = element.name
            
            # 1. Headings
            if tag_name in ["h1", "h2", "h3", "h4"]:
                text = element.get_text().strip()
                if text:
                    current_heading = text
                    blocks.append({
                        "type": "heading",
                        "level": int(tag_name[1]),
                        "content": text,
                        "heading": current_heading
                    })
                    
            # 2. Code blocks
            elif tag_name == "pre":
                # Find code tags inside pre
                code_tag = element.find("code")
                code_text = code_tag.get_text() if code_tag else element.get_text()
                # Remove trailing whitespace/newlines
                code_text = code_text.strip()
                
                # Check for language class if available
                lang = ""
                if code_tag and code_tag.has_attr("class"):
                    classes = code_tag["class"]
                    for c in classes:
                        if c.startswith("language-"):
                            lang = c.replace("language-", "")
                            break
                            
                if code_text:
                    blocks.append({
                        "type": "code",
                        "language": lang,
                        "content": f"``` {lang}\n{code_text}\n```",
                        "heading": current_heading
                    })
                    
            # 3. Tables
            elif tag_name == "table":
                # Render table into markdown table or structured text
                headers = [th.get_text().strip() for th in element.find_all("th")]
                rows = []
                for tr in element.find_all("tr"):
                    cells = [td.get_text().strip() for td in tr.find_all("td")]
                    if cells:
                        rows.append(cells)
                
                if headers or rows:
                    # Construct markdown representation
                    md_table = ""
                    if headers:
                        md_table += "| " + " | ".join(headers) + " |\n"
                        md_table += "| " + " | ".join(["---"] * len(headers)) + " |\n"
                    for row in rows:
                        # Make row match column counts
                        if headers and len(row) < len(headers):
                            row += [""] * (len(headers) - len(row))
                        md_table += "| " + " | ".join(row) + " |\n"
                        
                    blocks.append({
                        "type": "table",
                        "content": md_table.strip(),
                        "heading": current_heading
                    })
                    
            # 4. Lists
            elif tag_name in ["ul", "ol"]:
                list_items = []
                for li in element.find_all("li", recursive=False):
                    item_text = li.get_text().strip()
                    if item_text:
                        list_items.append(f"- {item_text}")
                if list_items:
                    blocks.append({
                        "type": "list",
                        "content": "\n".join(list_items),
                        "heading": current_heading
                    })
                    
            # 5. Paragraphs
            elif tag_name == "p":
                # Skip paragraphs that are child of lists or blockquotes to avoid double extraction
                if element.find_parent(["li", "blockquote"]):
                    continue
                text = element.get_text().strip()
                # Skip tiny/empty strings or common UI noise
                if len(text) > 10:
                    blocks.append({
                        "type": "text",
                        "content": text,
                        "heading": current_heading
                    })
                    
        # Construct flat text representation to compute content hash
        all_text = "\n".join([b["content"] for b in blocks])
        content_hash = hashlib.sha256(all_text.encode("utf-8")).hexdigest()
        
        return title, blocks, content_hash
