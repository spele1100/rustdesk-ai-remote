# AI Remote Desktop Agent (Python)

Lightweight agent that lets an AI control your desktop via HTTP API.

## Quick Start

### Linux / macOS
```bash
cd agent-python
chmod +x setup.sh
./setup.sh
```

Or manually:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python agent.py
```

### Windows
```powershell
cd agent-python
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python agent.py
```

### Docker
```bash
docker build -t ai-desktop-agent .
docker run -p 5800:5800 --device /dev/input -e DISPLAY=$DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix ai-desktop-agent
```

## API

| Endpoint | Method | Description |
|---|---|---|
| `/screenshot` | GET | Returns current screenshot as PNG |
| `/input` | POST | Execute an input action (JSON body) |
| `/screen/info` | GET | Screen resolution & OS info |
| `/health` | GET | Health check (`{"ok": true}`) |
| `/emergency_stop` | POST | Kill the agent immediately |

### Input Actions

```json
{"action": "click", "x": 500, "y": 300, "button": "left"}
{"action": "double_click", "x": 500, "y": 300}
{"action": "type", "text": "hello world"}
{"action": "key_press", "keys": ["ctrl", "c"]}
{"action": "hotkey", "keys": ["ctrl", "alt", "delete"]}
{"action": "scroll", "x": 500, "y": 300, "delta": -3}
{"action": "drag", "from": [100, 200], "to": [300, 400]}
{"action": "wait", "ms": 1000}
```

## Exposing the Agent

### Tailscale (recommended)
```bash
# On target machine
tailscale up
# Agent binds to 0.0.0.0:5800, accessible via tailscale IP

# On controller
node index.js --agent http://100.x.x.x:5800 --task "Open Chrome"
```

### ngrok
```bash
ngrok http 5800
# Use the ngrok URL as --agent
```

### SSH Tunnel
```bash
ssh -R 5800:localhost:5800 user@controller-host
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `AGENT_HOST` | `0.0.0.0` | Bind address |
| `AGENT_PORT` | `5800` | Bind port |
| `AGENT_RATE_LIMIT` | `10` | Max actions per second |
| `AGENT_ALLOWED_ACTIONS` | (all) | Comma-separated allowed actions |

Example — only allow click and type:
```bash
AGENT_ALLOWED_ACTIONS=click,type python agent.py
```

## Safety

- ⚠️ **This gives full desktop control to an AI. Use with caution.**
- Every action is logged to console (auditable)
- Rate limited to 10 actions/sec by default
- Three kill switches: `POST /emergency_stop`, `Ctrl+C`, mouse-to-corner (FAILSAFE)
- Restrict actions with `AGENT_ALLOWED_ACTIONS`
- **Never expose directly to the internet** — use tailscale, SSH tunnel, or VPN

## Using with the Controller

The Node.js controller in `../controller/` works out of the box:

```bash
# Terminal 1: Start agent on target machine
python agent.py

# Terminal 2: Start controller
node ../controller/index.js --agent http://localhost:5800 --task "Open Chrome and go to google.com"
```
