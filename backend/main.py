import uvicorn
import webbrowser
import threading
import time
import os
import sys

def open_browser():
    # Wait a couple of seconds for uvicorn server to bind and start accepting connections
    time.sleep(1.5)
    url = "http://localhost:8000"
    print(f"[Server] Automatically opening default browser to {url}...")
    webbrowser.open(url)

if __name__ == "__main__":
    # Ensure current directory is in sys.path so we can import modules
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    # Launch browser-opening helper in a separate thread
    threading.Thread(target=open_browser, daemon=True).start()
    
    # Start the FastAPI server
    print("[Server] Launching FastAPI Backend on http://localhost:8000...")
    uvicorn.run("backend.app:app", host="localhost", port=8000, log_level="info")
