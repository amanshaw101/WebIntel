import sqlite3
import os
import json
from datetime import datetime
from typing import List, Dict, Any, Optional

DB_FILE = os.path.join(os.path.dirname(__file__), "assistant.db")

class Database:
    def __init__(self, db_path: str = DB_FILE):
        self.db_path = db_path
        self.init_db()

    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Table for tracking discovered/visited URLs
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS visited_pages (
                    url TEXT PRIMARY KEY,
                    title TEXT,
                    status TEXT, -- 'discovered', 'crawled', 'skipped', 'failed'
                    error_message TEXT,
                    crawled_at TEXT,
                    page_hash TEXT
                )
            """)
            
            # Table for site hierarchy mapping
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sitemap (
                    parent_url TEXT,
                    child_url TEXT,
                    PRIMARY KEY (parent_url, child_url)
                )
            """)

            # Table for logs
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    level TEXT, -- 'INFO', 'WARNING', 'ERROR'
                    message TEXT
                )
            """)

            # Table for state variables
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS app_state (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            
            # Table for storing conversation chat history
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT, -- 'user', 'assistant'
                    content TEXT,
                    timestamp TEXT
                )
            """)
            conn.commit()

    # Visited Pages methods
    def add_discovered_url(self, url: str, title: str = ""):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Only add if it doesn't already exist
            cursor.execute("""
                INSERT OR IGNORE INTO visited_pages (url, title, status)
                VALUES (?, ?, 'discovered')
            """, (url, title))
            conn.commit()

    def update_page_status(self, url: str, status: str, title: Optional[str] = None, error_message: Optional[str] = None, page_hash: Optional[str] = None):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            crawled_at = datetime.now().isoformat() if status in ('crawled', 'failed', 'skipped') else None
            
            if title is not None:
                cursor.execute("""
                    UPDATE visited_pages
                    SET status = ?, title = ?, error_message = ?, crawled_at = ?, page_hash = ?
                    WHERE url = ?
                """, (status, title, error_message, crawled_at, page_hash, url))
            else:
                cursor.execute("""
                    UPDATE visited_pages
                    SET status = ?, error_message = ?, crawled_at = ?, page_hash = ?
                    WHERE url = ?
                """, (status, error_message, crawled_at, page_hash, url))
            conn.commit()

    def get_all_pages(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM visited_pages")
            return [dict(row) for row in cursor.fetchall()]

    def get_pending_urls(self) -> List[str]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT url FROM visited_pages WHERE status = 'discovered'")
            return [row["url"] for row in cursor.fetchall()]

    # Sitemap hierarchy methods
    def add_hierarchy_link(self, parent_url: str, child_url: str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR IGNORE INTO sitemap (parent_url, child_url)
                VALUES (?, ?)
            """, (parent_url, child_url))
            conn.commit()

    def get_sitemap(self) -> List[Dict[str, str]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT parent_url, child_url FROM sitemap")
            return [dict(row) for row in cursor.fetchall()]

    # Logging methods
    def log(self, level: str, message: str):
        print(f"[{level}] {message}")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO logs (timestamp, level, message)
                VALUES (?, ?, ?)
            """, (datetime.now().isoformat(), level, message))
            conn.commit()

    def get_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(row) for row in cursor.fetchall()]

    # App State methods
    def set_state(self, key: str, value: Any):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO app_state (key, value)
                VALUES (?, ?)
            """, (key, json.dumps(value)))
            conn.commit()

    def get_state(self, key: str, default: Any = None) -> Any:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM app_state WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row:
                return json.loads(row["value"])
            return default

    # Chat History
    def add_chat_msg(self, role: str, content: str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO chat_history (role, content, timestamp)
                VALUES (?, ?, ?)
            """, (role, content, datetime.now().isoformat()))
            conn.commit()

    def get_chat_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT role, content, timestamp FROM chat_history ORDER BY id ASC LIMIT ?", (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def clear_chat_history(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM chat_history")
            conn.commit()

    def reset_crawled_data(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM visited_pages")
            cursor.execute("DELETE FROM sitemap")
            cursor.execute("DELETE FROM logs")
            cursor.execute("DELETE FROM app_state")
            conn.commit()
