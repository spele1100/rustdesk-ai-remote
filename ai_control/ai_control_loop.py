#!/usr/bin/env python3
"""
AI Remote Desktop Control Loop
Screenshot → GLM-4.6V analysis → Action → Verify → Repeat

Usage:
  python3 ai_control_loop.py --task "open Google Maps"
  python3 ai_control_loop.py --task "draw a circle in Paint" --max-steps 10
"""

import json, base64, sys, time, argparse, os, re, io
import urllib.request
from PIL import Image
import websocket

# ============ Config ============
API_KEY = "3a4229987df34db39dc6bce283b35113.2iYW6eDaNBBWhsKI"
API_URL = "https://api.z.ai/api/coding/paas/v4/chat/completions"
VISION_MODEL = "glm-4.6v"
WS_URL = "ws://100.86.104.36:8080"
AWS_HOST = "root@claw-build-host-contabo"
AWS_KEY = os.path.expanduser("~/claw-build-host-contabo-key")
REMOTE_SCREENSHOT = "/tmp/headless_screenshot.png"
TEMP_DIR = "/tmp/ai_remote"
MAX_STEPS = 20
IMG_QUALITY = 70
IMG_MAX_W = 960

os.makedirs(TEMP_DIR, exist_ok=True)

SYSTEM_PROMPT = """You are an AI desktop controller. You analyze screenshots of a remote desktop and decide the next action to accomplish a task.

IMPORTANT: Respond with ONLY a JSON object, no markdown, no explanation outside the JSON:
{
  "analysis": "What you see on screen (be specific about UI elements, their positions, and state)",
  "action": {
    "type": "mousemove|click|rightclick|doubleclick|drag|type|hotkey|key|scroll|wait",
    "params": { ... }
  },
  "reasoning": "Why this action helps accomplish the task",
  "done": false
}

Action types and params:
- mousemove: {"x": int, "y": int} — move cursor to position
- click: {"x": int, "y": int, "alt": false, "ctrl": false, "shift": false, "command": false}
- rightclick: {"x": int, "y": int, ...}
- doubleclick: {"x": int, "y": int, ...}
- drag: {"x1": int, "y1": int, "x2": int, "y2": int, "duration_ms": 500}
- type: {"text": "string"} — type text character by character
- hotkey: {"key": "key_name", "modifiers": ["ctrl"]} — e.g. Ctrl+N, Alt+F
  Keys: return, tab, escape, backspace, delete, f1-f12, up/down/left/right, home, end, space, etc.
- key: {"key": "key_name"} — press a single key
- scroll: {"x": int, "y": int, "dy": int} — scroll at position, dy positive=down, negative=up
- wait: {"ms": 1000} — wait then retake screenshot

Rules:
- Coordinates are in the ORIGINAL screen resolution (shown in image info)
- Be precise with coordinates — estimate carefully based on what you see
- Use "wait" after actions that need time (opening apps, loading pages)
- Set done: true ONLY when the task is fully complete
- If something unexpected appears (dialog, error), handle it first
- For menus: click to open, wait briefly, then click the menu item"""


def ws_send(cmd):
    """Send command via WebSocket, return response."""
    ws = websocket.create_connection(WS_URL, timeout=5)
    ws.send(json.dumps(cmd))
    resp = json.loads(ws.recv())
    ws.close()
    return resp


def fetch_screenshot(step):
    """Fetch screenshot from AWS."""
    path = f"{TEMP_DIR}/step_{step:03d}.png"
    ret = os.system(
        f"scp -i {AWS_KEY} -o StrictHostKeyChecking=no "
        f"{AWS_HOST}:{REMOTE_SCREENSHOT} {path} 2>/dev/null"
    )
    if ret == 0 and os.path.exists(path) and os.path.getsize(path) > 1000:
        return path
    return None


def prepare_image(image_path):
    """Resize and encode image for API."""
    img = Image.open(image_path)
    orig_w, orig_h = img.size
    
    # Resize if needed
    scale = min(IMG_MAX_W / orig_w, IMG_MAX_W / orig_h)
    if scale < 1:
        img = img.resize((int(orig_w * scale), int(orig_h * scale)))
    
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=IMG_QUALITY)
    b64 = base64.b64encode(buf.getvalue()).decode()
    
    return b64, orig_w, orig_h


def ask_vision(image_path, prompt):
    """Send image + prompt to GLM-4.6V."""
    b64, orig_w, orig_h = prepare_image(image_path)
    
    full_prompt = (
        f"Screen resolution: {orig_w}x{orig_h}\n"
        f"(Image may be scaled down — use original coordinates above)\n\n"
        f"{prompt}"
    )
    
    payload = {
        "model": VISION_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "text", "text": full_prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
            ]}
        ],
        "max_tokens": 2000,
        "temperature": 0.1
    }
    
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        }
    )
    
    with urllib.request.urlopen(req, timeout=90) as resp:
        result = json.loads(resp.read())
        msg = result["choices"][0]["message"]
        content = msg.get("content", "")
        reasoning = msg.get("reasoning_content", "")
        usage = result.get("usage", {})
        return content, reasoning, usage


def execute_action(action):
    """Execute action on remote desktop."""
    atype = action.get("type", "")
    params = action.get("params", {})
    
    if atype == "wait":
        ms = params.get("ms", 1000)
        time.sleep(ms / 1000)
        return {"type": "waited", "ms": ms}
    
    # Build WS command
    cmd = {"type": atype}
    cmd.update(params)
    
    # Ensure boolean defaults for click commands
    if atype in ("click", "rightclick", "doubleclick"):
        for k in ("alt", "ctrl", "shift", "command"):
            if k not in cmd:
                cmd[k] = False
    
    return ws_send(cmd)


def parse_response(content, reasoning=""):
    """Extract JSON decision from model response."""
    # Try content first
    if content:
        match = re.search(r'\{[^{}]*"action"[^{}]*\}', content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        
        # Try full content as JSON
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass
    
    # Try reasoning
    if reasoning:
        match = re.search(r'\{[^{}]*"action"[^{}]*\}', reasoning, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    
    return None


def run_loop(task, max_steps=MAX_STEPS):
    """Main AI control loop."""
    print(f"🎯 Task: {task}")
    print(f"🔄 Max steps: {max_steps}")
    print()
    
    history = []
    
    for step in range(max_steps):
        print(f"{'='*40}")
        print(f"📍 Step {step + 1}/{max_steps}")
        
        # 1. Screenshot
        print("📸 Taking screenshot...", end=" ", flush=True)
        screenshot = fetch_screenshot(step)
        if not screenshot:
            print("❌ Failed")
            print("   Make sure headless client is running: ./manage.sh start")
            break
        print(f"✅ ({os.path.getsize(screenshot)//1024}KB)")
        
        # 2. Build prompt with history
        hist_lines = []
        for i, (act, res) in enumerate(history[-5:]):
            hist_lines.append(f"  {i+1}. {json.dumps(act)[:80]} → {json.dumps(res)[:40]}")
        history_text = "\n".join(hist_lines) if hist_lines else "  None (first step)"
        
        prompt = f"Task: {task}\n\nRecent actions:\n{history_text}\n\nWhat's the next action?"
        
        # 3. Vision analysis
        print("🧠 Analyzing...", end=" ", flush=True)
        content, reasoning, usage = ask_vision(screenshot, prompt)
        tokens = usage.get("total_tokens", 0)
        print(f"({tokens} tokens)")
        
        # 4. Parse decision
        decision = parse_response(content, reasoning)
        if not decision:
            print(f"❌ Could not parse response")
            print(f"   Content: {(content or '')[:200]}")
            print(f"   Reasoning: {(reasoning or '')[:200]}")
            break
        
        analysis = decision.get("analysis", "")
        action = decision.get("action", {})
        done = decision.get("done", False)
        reasoning_text = decision.get("reasoning", "")
        
        print(f"👁️  {analysis[:120]}...")
        print(f"🎯 Action: {json.dumps(action)[:100]}")
        if reasoning_text:
            print(f"💭 {reasoning_text[:100]}...")
        
        # 5. Check done
        if done:
            print("\n✅ TASK COMPLETE!")
            break
        
        # 6. Execute
        if not action or not action.get("type"):
            print("⚠️  No action, retaking screenshot")
            time.sleep(1)
            continue
        
        print("⚡ Executing...", end=" ", flush=True)
        result = execute_action(action)
        print(f"→ {json.dumps(result)[:60]}")
        
        # 7. Record
        history.append((action, result))
        
        # 8. Delay
        time.sleep(1)
    else:
        print(f"\n⚠️  Reached max steps ({max_steps})")
    
    print(f"\n🏁 Loop finished. {len(history)} actions taken.")
    
    # Summary
    if history:
        print("\n📋 Action history:")
        for i, (act, res) in enumerate(history):
            print(f"  {i+1}. {act.get('type','?')}: {json.dumps(act.get('params',{}))[:60]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Remote Desktop Control Loop")
    parser.add_argument("--task", required=True, help="Task to accomplish")
    parser.add_argument("--ws", default=WS_URL, help="WebSocket URL")
    parser.add_argument("--max-steps", type=int, default=MAX_STEPS)
    args = parser.parse_args()
    
    WS_URL = args.ws
    run_loop(args.task, args.max_steps)
