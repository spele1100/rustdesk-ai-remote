#!/usr/bin/env python3
"""
AI Remote Desktop Agent — lightweight Python agent for AI-controlled remote desktop.

Exposes HTTP API for screenshot capture and input injection.
The AI controller (Node.js) takes screenshots, sends them to a vision model,
and sends back actions via the /input endpoint.

Requirements: pip install flask flask-cors mss Pillow pyautogui
"""

import io
import os
import sys
import time
import signal
import platform
import threading
from collections import deque

from flask import Flask, request, jsonify, Response
from flask_cors import CORS

try:
    import mss
    import mss.tools
except ImportError:
    print("ERROR: mss not installed. Run: pip install mss")
    sys.exit(1)

try:
    from PIL import Image
except ImportError:
    print("ERROR: Pillow not installed. Run: pip install Pillow")
    sys.exit(1)

try:
    import pyautogui
    pyautogui.FAILSAFE = True  # Move mouse to corner to abort
except ImportError:
    print("ERROR: pyautogui not installed. Run: pip install pyautogui")
    sys.exit(1)

# ── Configuration ────────────────────────────────────────────────────

HOST = os.environ.get("AGENT_HOST", "0.0.0.0")
PORT = int(os.environ.get("AGENT_PORT", "5800"))
MAX_ACTIONS_PER_SEC = int(os.environ.get("AGENT_RATE_LIMIT", "10"))

# Allowed actions — set to empty list to allow all, or list specific ones
# Options: click, double_click, type, key_press, scroll, drag, hotkey
ALLOWED_ACTIONS = os.environ.get("AGENT_ALLOWED_ACTIONS", "").split(",") if os.environ.get("AGENT_ALLOWED_ACTIONS") else []

# ── Globals ──────────────────────────────────────────────────────────

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

action_timestamps = deque()
rate_lock = threading.Lock()
alive = True


# ── Helpers ──────────────────────────────────────────────────────────

def check_rate_limit():
    """Return True if action is allowed, False if rate-limited."""
    now = time.time()
    with rate_lock:
        # Prune old entries
        while action_timestamps and action_timestamps[0] < now - 1.0:
            action_timestamps.popleft()
        if len(action_timestamps) >= MAX_ACTIONS_PER_SEC:
            return False
        action_timestamps.append(now)
        return True


def log_action(action_data):
    """Print action for audit trail."""
    ts = time.strftime("%H:%M:%S")
    print(f"  [{ts}] ACTION: {action_data}", flush=True)


def take_screenshot():
    """Capture screenshot using mss, return PNG bytes."""
    with mss.mss() as sct:
        # Use primary monitor (index 1) or all monitors
        monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
        img = sct.grab(monitor)
        # Convert to PNG bytes
        png_bytes = mss.tools.to_png(img.rgb, img.size)
        return png_bytes


def get_screen_info():
    """Get screen resolution and OS info."""
    with mss.mss() as sct:
        monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
        width = monitor["width"]
        height = monitor["height"]
    return {
        "width": width,
        "height": height,
        "os": platform.system(),
        "os_version": platform.version(),
        "platform": platform.platform(),
        "python": platform.python_version(),
    }


# ── Input Execution ──────────────────────────────────────────────────

def execute_action(data):
    """Execute an input action. Returns (success, message)."""
    action = data.get("action", "")
    
    if not action:
        return False, "Missing 'action' field"
    
    # Check allowed actions
    if ALLOWED_ACTIONS and action not in ALLOWED_ACTIONS:
        return False, f"Action '{action}' is not allowed. Allowed: {ALLOWED_ACTIONS}"
    
    # Check rate limit
    if not check_rate_limit():
        return False, "Rate limit exceeded"
    
    log_action(data)
    
    try:
        if action == "click":
            x = data.get("x")
            y = data.get("y")
            button = data.get("button", "left")
            if x is None or y is None:
                return False, "click requires x and y"
            pyautogui.click(x=int(x), y=int(y), button=button)
            return True, f"clicked ({x}, {y}) {button}"
        
        elif action == "double_click":
            x = data.get("x")
            y = data.get("y")
            if x is None or y is None:
                return False, "double_click requires x and y"
            pyautogui.doubleClick(x=int(x), y=int(y))
            return True, f"double_clicked ({x}, {y})"
        
        elif action == "type":
            text = data.get("text", "")
            if not text:
                return False, "type requires 'text'"
            pyautogui.write(str(text), interval=0.02)
            return True, f"typed '{text[:50]}'"
        
        elif action == "key_press":
            keys = data.get("keys", [])
            if not keys:
                return False, "key_press requires 'keys' list"
            if len(keys) == 1:
                pyautogui.press(keys[0])
            else:
                # Hold modifiers, press last key
                modifiers = keys[:-1]
                main_key = keys[-1]
                for m in modifiers:
                    pyautogui.keyDown(m)
                pyautogui.press(main_key)
                for m in reversed(modifiers):
                    pyautogui.keyUp(m)
            return True, f"key_press {keys}"
        
        elif action == "hotkey":
            keys = data.get("keys", [])
            if not keys:
                return False, "hotkey requires 'keys' list"
            pyautogui.hotkey(*keys)
            return True, f"hotkey {keys}"
        
        elif action == "scroll":
            x = data.get("x")
            y = data.get("y")
            delta = data.get("delta", -3)
            if x is not None and y is not None:
                pyautogui.moveTo(int(x), int(y))
            # pyautogui scroll: positive = up, negative = down
            pyautogui.scroll(int(delta))
            return True, f"scrolled delta={delta} at ({x}, {y})"
        
        elif action == "drag":
            from_pos = data.get("from", [])
            to_pos = data.get("to", [])
            if len(from_pos) != 2 or len(to_pos) != 2:
                return False, "drag requires 'from': [x,y] and 'to': [x,y]"
            pyautogui.moveTo(int(from_pos[0]), int(from_pos[1]))
            pyautogui.drag(
                int(to_pos[0]) - int(from_pos[0]),
                int(to_pos[1]) - int(from_pos[1]),
                duration=0.3
            )
            return True, f"dragged from {from_pos} to {to_pos}"
        
        elif action == "wait":
            ms = data.get("ms", 1000)
            time.sleep(ms / 1000.0)
            return True, f"waited {ms}ms"
        
        else:
            return False, f"Unknown action: {action}"
    
    except pyautogui.FailSafeException:
        return False, "FAILSAFE triggered — mouse moved to corner"
    except Exception as e:
        return False, f"Error: {str(e)}"


# ── Routes ───────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "status": "running"})


@app.route("/screenshot", methods=["GET"])
def screenshot():
    try:
        png_bytes = take_screenshot()
        return Response(png_bytes, mimetype="image/png",
                        headers={"X-Screen-Width": str(get_screen_info()["width"]),
                                 "X-Screen-Height": str(get_screen_info()["height"])})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/input", methods=["POST"])
def input_action():
    global alive
    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify({"ok": False, "error": "Invalid JSON"}), 400
    
    success, message = execute_action(data)
    return jsonify({"ok": success, "message": message}), 200 if success else 400


@app.route("/screen/info", methods=["GET"])
def screen_info():
    return jsonify(get_screen_info())


@app.route("/emergency_stop", methods=["POST"])
def emergency_stop():
    global alive
    print("\n🚨 EMERGENCY STOP ACTIVATED! 🚨", flush=True)
    alive = False
    # Give response time to send, then kill
    threading.Thread(target=lambda: (time.sleep(0.5), os.kill(os.getpid(), signal.SIGTERM)), daemon=True).start()
    return jsonify({"ok": True, "message": "EMERGENCY_STOP"})


# ── Main ─────────────────────────────────────────────────────────────

def print_banner():
    info = get_screen_info()
    print("")
    print("╔" + "═" * 58 + "╗")
    print("║" + " " * 58 + "║")
    print("║   ⚠️   AI REMOTE DESKTOP AGENT   ⚠️                  ║")
    print("║" + " " * 58 + "║")
    print("║   This machine is being controlled by an AI.          ║")
    print("║   All inputs are logged to this console.              ║")
    print("║" + " " * 58 + "║")
    print("║   Kill switch:  POST /emergency_stop                  ║")
    print("║   Or press Ctrl+C to stop immediately.                ║")
    print("║   Or move mouse to screen corner (FAILSAFE).          ║")
    print("║" + " " * 58 + "║")
    print("╚" + "═" * 58 + "╝")
    print(f"\n  Screen:  {info['width']}x{info['height']}")
    print(f"  OS:      {info['os']} ({info['os_version']})")
    print(f"  Port:    {PORT}")
    print(f"  Rate:    {MAX_ACTIONS_PER_SEC} actions/sec")
    if ALLOWED_ACTIONS:
        print(f"  Allowed: {ALLOWED_ACTIONS}")
    else:
        print(f"  Allowed: ALL actions")
    print(f"\n  Endpoints:")
    print(f"    GET  /screenshot       — PNG screenshot")
    print(f"    POST /input            — Send input action")
    print(f"    GET  /screen/info      — Screen & OS info")
    print(f"    GET  /health           — Health check")
    print(f"    POST /emergency_stop   — Kill agent")
    print("")


def main():
    print_banner()
    
    # Graceful shutdown
    def shutdown(sig, frame):
        print("\n⏹  Shutting down agent...")
        os._exit(0)
    
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    
    # Use Werkzeug quietly
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.WARNING)
    
    app.run(host=HOST, port=PORT, threaded=True, debug=False)


if __name__ == "__main__":
    main()
