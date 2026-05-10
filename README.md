# AI Remote Desktop Control — Proof of Concept

AI-controlled remote desktop: a vision model sees the screen, decides actions, sends inputs. Like a human using remote desktop, but the "human" is an AI.

## Architecture

```
[Target PC]                               [VPS / Control Machine]
 Agent (Rust)                             Controller (Node.js)
┌──────────────┐    HTTP/WebSocket       ┌──────────────────────┐
│ xcap screen  │◄───────────────────────►│ Screenshot → Vision  │
│ capture      │                          │ API (GLM-4.6V)       │
│              │                          │                      │
│ enigo input  │◄─── JSON commands ──────│ Action decision loop │
│ injection    │                          │                      │
│              │──── PNG screenshots ────►│                      │
│ axum HTTP/WS │                          └──────────────────────┘
└──────────────┘
```

## Quick Start

### 1. Run the Agent (on target PC)

```bash
cd agent
cargo build --release
./target/release/ai-remote-agent
```

The agent starts on port 5800 and exposes:
- `GET /screenshot` — returns current screenshot as PNG
- `POST /input` — accepts JSON input commands
- `WS /stream` — WebSocket for bidirectional commands + screenshots
- `GET /health` — health check

### 2. Run the Controller (on VPS)

```bash
cd controller
npm install

# Set your vision API key
export ZAI_API_KEY="your-api-key-here"

# Run with a task
node index.js --task "Open a text editor and type Hello World"

# Or point to a remote agent
node index.js --agent http://192.168.1.100:5800 --task "Open Chrome and go to github.com"
```

### CLI Options

```
--task <prompt>      Task description for the AI to execute
--agent <url>        Agent URL (default: http://localhost:5800)
--steps <n>          Max steps before stopping (default: 30)
--delay <ms>         Delay between steps in ms (default: 1000)
--model <name>       Vision model name (default: glm-4.6v)
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_URL` | `http://localhost:5800` | Agent endpoint |
| `VISION_API_URL` | `https://api.z.ai/api/coding/paas/v4/chat/completions` | Vision API endpoint |
| `ZAI_API_KEY` | — | API key for vision model |
| `VISION_MODEL` | `glm-4.6v` | Vision model to use |
| `MAX_STEPS` | `30` | Maximum action steps |
| `SCREENSHOT_DELAY` | `1000` | ms between steps |
| `DEBUG_DIR` | `./debug-screenshots` | Where to save debug screenshots |

## Action Protocol

Commands are JSON:

```json
{"action": "click", "x": 500, "y": 300, "button": "left"}
{"action": "double_click", "x": 500, "y": 300}
{"action": "type", "text": "hello world"}
{"action": "key_press", "keys": ["ctrl", "c"]}
{"action": "scroll", "x": 500, "y": 300, "delta": -3}
{"action": "drag", "from": [100, 200], "to": [300, 400]}
{"action": "wait", "ms": 1000}
{"action": "done", "reason": "Task completed"}
```

## How It Works

1. **Controller** requests a screenshot from the **Agent**
2. **Screenshot** (PNG, base64) is sent to the **Vision Model** (GLM-4.6V)
3. Vision model analyzes the screen and returns a **JSON action**
4. Controller sends the action to the Agent
5. Agent executes the action via **enigo** (OS-level input injection)
6. Loop until the model says `done` or max steps reached

## Safety Warnings

⚠️ **This is a Proof of Concept. Not production ready.**

- **No authentication** — anyone who can reach the agent can control the PC
- **No encryption** — screenshots and commands are sent in plaintext
- **No sandbox** — the AI can do anything a human at the keyboard could do
- **Kill switch** — `Ctrl+C` on the controller stops the loop. The agent responds to `emergency_stop` action.
- **Rate limiting** — there's a delay between steps, but no action validation
- **The AI can make mistakes** — it might click the wrong thing, delete files, or cause damage
- **Never run on production machines** — use a VM or test environment

## Project Structure

```
rustdesk-ai-remote/
├── agent/                  # Rust agent (runs on target PC)
│   ├── Cargo.toml
│   └── src/
│       └── main.rs         # HTTP server + screen capture + input injection
├── controller/             # Node.js controller (runs on VPS)
│   ├── package.json
│   └── index.js            # Vision loop + action execution
├── PROJECT.md              # Project vision & roadmap
├── SOURCE_ANALYSIS.md      # RustDesk source code analysis
├── COMPETITIVE_RESEARCH.md # Competitive landscape
└── README.md               # This file
```

## Next Steps (Phase 2)

- [ ] Add TLS encryption to agent
- [ ] Add token-based authentication
- [ ] Smart frame differencing (only send changed regions)
- [ ] OCR pre-processing (skip vision for text-heavy screens)
- [ ] Action recording and replay
- [ ] Multi-monitor support
- [ ] Chi integration (control via chat)
- [ ] UI-TARS as alternative vision backbone

## License

GPL-3.0 (derivative of RustDesk concepts)
