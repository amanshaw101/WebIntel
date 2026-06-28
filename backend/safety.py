import ctypes
import ctypes.wintypes
import threading
import time
from typing import Callable

class SafetyMonitor:
    def __init__(self, trigger_callback: Callable[[str], None]):
        """
        trigger_callback: Function to run when emergency stop is triggered.
                          It accepts a reason string.
        """
        self.trigger_callback = trigger_callback
        self.running = False
        self.thread = None

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._monitor_loop, name="SafetyMonitorThread", daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=1.0)
            self.thread = None

    def _monitor_loop(self):
        # Modifier codes
        MOD_ALT = 0x0001
        MOD_CONTROL = 0x0002
        # Virtual key code for 'Q'
        VK_Q = 0x51
        HOTKEY_ID = 1918  # Unique ID for the hotkey

        user32 = ctypes.windll.user32
        
        # Register global hotkey: Ctrl + Alt + Q (0x0001 | 0x0002 = 0x0003)
        success = user32.RegisterHotKey(None, HOTKEY_ID, MOD_ALT | MOD_CONTROL, VK_Q)
        if not success:
            print("[Safety] Warning: Could not register Ctrl+Alt+Q hotkey. (It may be registered by another app)")
        else:
            print("[Safety] Registered global hotkey: Ctrl + Alt + Q")

        # Define structure to hold mouse coordinates
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        msg = ctypes.wintypes.MSG()
        last_mouse_check = 0.0
        
        try:
            while self.running:
                # 1. Non-blocking check for Windows message queue (handles WM_HOTKEY)
                # PM_REMOVE = 0x0001
                if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                    if msg.message == 0x0312 and msg.wParam == HOTKEY_ID:  # WM_HOTKEY
                        print("[Safety] Emergency hotkey Ctrl+Alt+Q pressed!")
                        self.trigger_callback("Ctrl+Alt+Q pressed")
                        break
                    
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))

                # 2. Check mouse position (every 100ms)
                now = time.time()
                if now - last_mouse_check >= 0.10:
                    last_mouse_check = now
                    pt = POINT()
                    if user32.GetCursorPos(ctypes.byref(pt)):
                        if pt.x == 0 and pt.y == 0:
                            print("[Safety] Mouse fail-safe triggered (reached top-left corner 0,0)!")
                            self.trigger_callback("Mouse reached top-left corner (0,0)")
                            break

                time.sleep(0.01)  # Minimal sleep to reduce CPU overhead
        finally:
            # Make sure we clean up and unregister the hotkey
            user32.UnregisterHotKey(None, HOTKEY_ID)
            print("[Safety] Safety monitor stopped.")
