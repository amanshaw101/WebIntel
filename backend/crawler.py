import asyncio
import time
from urllib.parse import urlparse, urljoin
from playwright.async_api import async_playwright
from typing import Callable, Optional, Dict, Any, List, Tuple
import traceback
import psutil
import base64

from .db import Database
from .extractor import ContentExtractor
from .vector_store import VectorStore

class Crawler:
    def __init__(self, db: Database, vector_store: VectorStore, progress_callback: Callable[[Dict[str, Any]], None]):
        self.db = db
        self.vector_store = vector_store
        self.progress_callback = progress_callback
        
        self.status = "idle"  # idle, mapping, crawling, paused, stopped
        self.start_url = ""
        self.allowed_domain = ""
        self.path_prefix = "/"
        self.browser = None
        self.context = None
        self.page = None
        self.playwright = None
        
        self.start_time = 0.0
        self.pages_completed = 0
        self.lock = asyncio.Lock()
        self.last_screenshot = ""

    def set_status(self, new_status: str):
        self.status = new_status
        self.db.set_state("crawler_status", new_status)
        self.push_status()

    def push_status(self, extra: Optional[Dict[str, Any]] = None):
        stats = self.get_stats()
        if extra:
            stats.update(extra)
        self.progress_callback(stats)

    def get_stats(self) -> Dict[str, Any]:
        pages = self.db.get_all_pages()
        completed = len([p for p in pages if p["status"] in ("crawled", "failed", "skipped")])
        discovered = len(pages)
        pending = len([p for p in pages if p["status"] == "discovered"])
        
        # Calculate speed and ETA
        elapsed = time.time() - self.start_time if self.start_time > 0 and self.status == "crawling" else 0.0
        speed = (completed / (elapsed / 60.0)) if elapsed > 0 and completed > 0 else 0.0
        eta = (pending / speed) if speed > 0 else 0.0
        
        # Memory usage
        process = psutil.Process()
        mem_mb = process.memory_info().rss / (1024 * 1024)
        
        db_stats = self.vector_store.get_db_stats()

        return {
            "status": self.status,
            "start_url": self.start_url,
            "pages_completed": completed,
            "pages_discovered": discovered,
            "pages_remaining": pending,
            "speed_ppm": round(speed, 2),
            "eta_mins": round(eta, 2),
            "memory_usage_mb": round(mem_mb, 2),
            "chunks_count": db_stats.get("chunks_count", 0),
            "current_url": self.db.get_state("current_url", ""),
            "current_section": self.db.get_state("current_section", ""),
            "screenshot": self.last_screenshot
        }

    async def _capture_screenshot(self):
        try:
            if self.page:
                # Capture JPEG with compression to keep WebSocket payload size small and fast
                img_bytes = await self.page.screenshot(type="jpeg", quality=40)
                self.last_screenshot = base64.b64encode(img_bytes).decode("utf-8")
        except Exception as e:
            self.db.log("WARNING", f"Failed to capture browser screenshot: {e}")

    async def start(self, start_url: str, cdp_url: Optional[str] = None):
        async with self.lock:
            if self.status in ("mapping", "crawling"):
                self.db.log("WARNING", "Crawler is already running.")
                return

            self.start_url = start_url
            self.allowed_domain = urlparse(start_url).netloc
            
            # Restrict crawling to starting sub-directories/path prefixes
            start_path = urlparse(start_url).path
            if not start_path or start_path == "/":
                self.path_prefix = "/"
            elif start_path.endswith('/'):
                self.path_prefix = start_path
            else:
                parts = start_path.split('/')
                if len(parts) > 1:
                    self.path_prefix = '/'.join(parts[:-1]) + '/'
                else:
                    self.path_prefix = '/'
            
            self.db.reset_crawled_data()
            self.vector_store.clear_database()
            
            self.db.add_discovered_url(start_url, "Home")
            self.db.set_state("start_url", start_url)
            self.db.set_state("current_url", start_url)
            self.db.set_state("current_section", "Initializing")
            
            self.start_time = time.time()
            self.pages_completed = 0
            
            self.set_status("mapping")
            self.db.log("INFO", f"Starting crawler on domain: {self.allowed_domain} (Path restricted to: {self.path_prefix})")
            
            # Start crawler thread/task
            asyncio.create_task(self._run_crawler_loop(cdp_url))

    async def pause(self):
        if self.status in ("mapping", "crawling"):
            self.set_status("paused")
            self.db.log("INFO", "Crawl paused by user.")

    async def resume(self):
        if self.status == "paused":
            self.set_status("crawling")
            self.db.log("INFO", "Crawl resumed by user.")

    async def stop(self, reason: str = "Stopped by user"):
        async with self.lock:
            if self.status == "idle":
                return
            self.set_status("stopped")
            self.db.log("INFO", f"Stopping crawler: {reason}")
            await self._cleanup_browser()

    async def _cleanup_browser(self):
        try:
            if self.page:
                await self.page.close()
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
        except Exception as e:
            self.db.log("ERROR", f"Error cleaning up browser: {e}")
        finally:
            self.page = None
            self.context = None
            self.browser = None
            self.playwright = None

    def _should_keep_link(self, url: str) -> bool:
        """
        Validates if URL is within domain, matches the path prefix, not an anchor fragment, and is an HTML document.
        """
        parsed = urlparse(url)
        if parsed.netloc != self.allowed_domain:
            return False
            
        # Path prefix restriction: ensure link path starts with self.path_prefix
        # (Allows crawling subfolders/articles under starting URL but blocks homepage wandering)
        if not parsed.path.startswith(self.path_prefix):
            return False
            
        # Ignore media/binary files
        path = parsed.path.lower()
        ignored_extensions = [
            ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".tar", ".gz", 
            ".mp4", ".mp3", ".css", ".js", ".svg", ".ico", ".xml", ".json"
        ]
        if any(path.endswith(ext) for ext in ignored_extensions):
            return False
            
        return True

    async def _run_crawler_loop(self, cdp_url: Optional[str] = None):
        try:
            self.playwright = await async_playwright().start()
            
            if cdp_url:
                self.db.log("INFO", f"Connecting to existing browser via CDP: {cdp_url}")
                self.browser = await self.playwright.chromium.connect_over_cdp(cdp_url)
                # CDP usually has contexts already
                if self.browser.contexts:
                    self.context = self.browser.contexts[0]
                else:
                    self.context = await self.browser.new_context()
            else:
                self.db.log("INFO", "Launching new Chromium browser instance")
                self.browser = await self.playwright.chromium.launch(headless=False)
                self.context = await self.browser.new_context(
                    viewport={"width": 1280, "height": 800}
                )
                
            self.page = await self.context.new_page()
            
            # --- PHASE 1: SITE MAPPING ---
            self.db.log("INFO", "Phase 1: Initial page scan and sitemap building...")
            await self.page.goto(self.start_url, wait_until="domcontentloaded")
            await asyncio.sleep(2) # Wait for page load scripts
            await self._capture_screenshot()
            self.push_status()
            
            # Extract links on start page
            start_links = await self._extract_page_links()
            for text, href in start_links:
                if self._should_keep_link(href):
                    self.db.add_discovered_url(href, text)
                    self.db.add_hierarchy_link(self.start_url, href)
                    
            self.set_status("crawling")
            self.db.log("INFO", "Phase 2: Systematic exploration and database ingestion...")
            
            # Reset timer for crawling phase
            self.start_time = time.time()
            
            while self.status in ("crawling", "paused"):
                # Handle paused state
                if self.status == "paused":
                    await asyncio.sleep(0.5)
                    continue
                    
                pending = self.db.get_pending_urls()
                if not pending:
                    self.db.log("INFO", "No more links discovered. Learning complete.")
                    break
                    
                url = pending[0]
                self.db.set_state("current_url", url)
                self.db.log("INFO", f"Navigating to {url}...")
                
                try:
                    self.db.update_page_status(url, "crawling")
                    self.push_status()
                    
                    # Open page and wait
                    response = await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    if not response or response.status >= 400:
                        raise Exception(f"Failed loading page: HTTP {response.status if response else 'No Response'}")
                        
                    await self._capture_screenshot()
                    self.push_status()
                    
                    # Expand collapsible panels (HTML details tags)
                    await self.page.evaluate("document.querySelectorAll('details').forEach(el => el.open = true)")
                    
                    # Smooth Scroll to bottom to trigger lazy loading
                    await self._smooth_scroll()
                    await self._capture_screenshot()
                    self.push_status()
                    
                    # Extract page HTML
                    html_content = await self.page.content()
                    
                    # Parse and Clean
                    title, blocks, content_hash = ContentExtractor.extract(html_content, url)
                    self.db.set_state("current_section", title)
                    
                    # Chunk and generate embeddings
                    chunks_added = self.vector_store.add_page_chunks(url, title, blocks)
                    
                    # Mark page crawled
                    self.db.update_page_status(url, "crawled", title=title, page_hash=content_hash)
                    self.db.log("INFO", f"Successfully ingested {url} - Generated {chunks_added} chunks.")
                    
                    # Discover links on this page to expand mapping
                    new_links = await self._extract_page_links()
                    for text, href in new_links:
                        if self._should_keep_link(href):
                            # Add link to queue
                            self.db.add_discovered_url(href, text)
                            self.db.add_hierarchy_link(url, href)
                            
                except Exception as page_err:
                    self.db.log("ERROR", f"Error crawling {url}: {page_err}")
                    self.db.update_page_status(url, "failed", error_message=str(page_err))
                    
                self.pages_completed += 1
                self.push_status()
                
                # Small human-like browsing delay
                await asyncio.sleep(1.5)
                
            if self.status != "stopped":
                self.set_status("idle")
                self.db.log("INFO", "Crawler finished successfully.")
                
        except Exception as e:
            self.db.log("ERROR", f"Crawler loop encountered fatal error: {e}\n{traceback.format_exc()}")
            self.set_status("stopped")
        finally:
            await self._cleanup_browser()
            self.push_status()

    async def _smooth_scroll(self):
        """
        Scrolls the page incrementally to trigger dynamic assets or lazy-loaded blocks.
        """
        try:
            scroll_height = await self.page.evaluate("document.body.scrollHeight")
            client_height = await self.page.evaluate("window.innerHeight")
            
            # Limit scroll steps to avoid hanging on infinite-scroll pages
            current_position = 0
            step = 300
            max_scrolls = 15
            scroll_count = 0
            
            while current_position < scroll_height and scroll_count < max_scrolls:
                current_position += step
                await self.page.evaluate(f"window.scrollTo(0, {current_position})")
                await asyncio.sleep(0.15)
                # Re-evaluate scroll height in case it grew
                scroll_height = await self.page.evaluate("document.body.scrollHeight")
                scroll_count += 1
                
            # Scroll back to top
            await self.page.evaluate("window.scrollTo(0, 0)")
        except Exception as e:
            self.db.log("WARNING", f"Error during smooth scroll: {e}")

    async def _extract_page_links(self) -> List[Tuple[str, str]]:
        """
        Queries all anchors, resolves relative URLs, and strips fragments/hashes.
        """
        try:
            anchors = await self.page.query_selector_all("a")
            links = []
            
            for anchor in anchors:
                href = await anchor.get_attribute("href")
                if not href:
                    continue
                    
                # Clean links: strip fragments
                href_clean = href.split("#")[0].strip()
                if not href_clean:
                    continue
                    
                text = await anchor.inner_text()
                text_clean = text.strip() if text else ""
                
                # Resolve relative links
                resolved_url = urljoin(self.page.url, href_clean)
                links.append((text_clean, resolved_url))
                
            return links
        except Exception as e:
            self.db.log("WARNING", f"Failed to extract page links: {e}")
            return []
