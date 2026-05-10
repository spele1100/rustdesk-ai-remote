# RustDesk AI Remote Control

## Vision
Fork RustDesk to create an AI-controlled remote desktop system. Replace the human-facing GUI viewer with an AI-facing API — vision model sees the screen, decides actions, sends inputs.

## Architecture

```
[Target PC] ↔ RustDesk Agent (modified) ↔ Frame/Command API ↔ [AI Controller on VPS]
```

### Components
1. **Modified RustDesk Agent** (runs on target PC)
   - Keep existing: screen capture, input injection, NAT traversal, encryption
   - Replace: Flutter viewer → HTTP/WebSocket API for frame streaming + command receiving

2. **AI Controller** (runs on VPS)
   - Receives frames → analyzes with vision model
   - Decides actions (click, type, scroll, drag)
   - Sends commands back to agent
   - Maintains context (what's open, cursor position, current task)

3. **Command Protocol**
   ```json
   {"action": "click", "x": 500, "y": 300, "button": "left"}
   {"action": "double_click", "x": 500, "y": 300}
   {"action": "type", "text": "hello world"}
   {"action": "key_press", "keys": ["ctrl", "c"]}
   {"action": "scroll", "x": 500, "y": 300, "delta": -3}
   {"action": "drag", "from": [100, 200], "to": [300, 400]}
   {"action": "screenshot"}  // request current frame
   {"action": "wait", "ms": 1000}
   ```

## Key Challenges
- **Frame rate vs cost**: Need smart change detection, not every frame to vision model
- **Latency**: Vision model (1-3s) + network + action = 2-5s per step
- **Context tracking**: Window state, cursor, task progress
- **Safety**: Confirm destructive actions, rate limits, kill switch

## Tech Stack
- **Agent**: Rust (forked from RustDesk)
- **Controller**: Node.js/Python API server
- **Vision**: GLM-4.6V or similar (already available)
- **Transport**: WebSocket with TLS (RustDesk's existing encrypted channel)

## Development Phases

### Phase 1: Proof of Concept
- [ ] Analyze RustDesk source architecture
- [ ] Identify key files: screen capture, input injection, network transport
- [ ] Build minimal agent that streams screenshots via HTTP
- [ ] Build minimal controller that takes screenshot → vision → command
- [ ] End-to-end demo: AI clicks a button on target PC

### Phase 2: Usability
- [ ] Smart frame differencing (only send changed regions)
- [ ] OCR/text extraction for faster reading (skip vision for text)
- [ ] Action recording and replay
- [ ] Task scripting language ("open Chrome, go to X, click Y")
- [ ] Safety: confirmation prompts for risky actions

### Phase 3: Integration
- [ ] Chi integration (I can remote control via chat command)
- [ ] Multi-monitor support
- [ ] Mobile target support (Android/iOS)
- [ ] Session recording and audit log

## RustDesk Source Analysis (DONE ✅)
- **Full analysis:** [SOURCE_ANALYSIS.md](./SOURCE_ANALYSIS.md)
- **Source cloned to:** `source/` (shallow clone)
- **Key finding:** Server side already headless (daemon). Client has Flutter UI.
- **Protocol:** Binary protobuf over TCP. Messages: VideoFrame, MouseEvent, KeyEvent, LoginRequest/Response.
- **Screen capture:** `libs/scrap/` — platform-specific Capturer (X11 SHM, DXGI, CoreGraphics)
- **Input injection:** `libs/enigo/` + `src/server/input_service.rs` — uses XTest/uinput/SendInput/CGEvent

## Protocol Specification (DONE ✅)
- **Full spec:** [PROTOCOL_SPEC.md](./PROTOCOL_SPEC.md)
- **Connection flow:** PunchHoleRequest → PunchHoleResponse → direct/relay TCP → KeyExchange (NaCl) → LoginRequest → VideoFrame/Input
- **Encryption:** XSalsa20-Poly1305 (NaCl secretbox) with sequential nonce counters
- **Key exchange:** NaCl box (Curve25519 + XSalsa20) to exchange a symmetric session key
- **Auth:** SHA256 challenge-response (salt + challenge from server)
- **Video:** VP9/VP8/H264/H265/AV1 encoded frames in EncodedVideoFrames protobuf
- **Input:** MouseEvent (mask + x,y + modifiers) and KeyEvent (control_key/chr/unicode/seq + modifiers)
- **No existing headless client found** — must build from scratch
- **Estimated effort:** ~10 days for minimal Rust client

## Architecture Decision: Hybrid Approach

```
┌──────────────────────┐         RustDesk Protocol          ┌──────────────────┐
│  Target PC            │◄──────────────────────────────────►│  VPS (AI Agent)   │
│  RustDesk Server      │   TCP/WS + Protobuf + NaCl        │  Headless Client  │
│  (UNMODIFIED)         │                                    │  (Rust)           │
│  - video_service      │  ◄──── VideoFrame (VP9) ──────────│  decode → PNG     │
│  - input_service      │  ───── MouseEvent/KeyEvent ──────►│  AI cmd → proto   │
│  - connection         │                                    │  HTTP API ────────│──► AI Controller
└──────────────────────┘                                    └──────────────────┘    (Vision API)
```

**Why this approach:**
- Target runs standard RustDesk — no custom build needed
- NAT traversal + encryption built-in
- Only need to build the controller-side headless client
- AI controller talks to headless client via simple HTTP API

### Headless Client Components
```
ai-remote-client/
├── protos/              # message.proto + rendezvous.proto (from hbb_common)
├── src/
│   ├── main.rs          # Entry: connect to target via RustDesk server
│   ├── connection.rs    # Full flow: punch/relay → key exchange → login
│   ├── encryption.rs    # NaCl box + secretbox (XSalsa20-Poly1305)
│   ├── video_sink.rs    # Receive VideoFrame → decode VP9 → PNG
│   ├── input.rs         # Build MouseEvent/KeyEvent protobufs
│   ├── api.rs           # HTTP/WebSocket server for AI controller
│   └── config.rs        # Server addr, peer ID, password
└── Cargo.toml
```

## Competitive Landscape Insights
- **No competitor does remote control of existing machines** — all use sandboxed VMs or local-only
- **UI-TARS** is the best vision model for GUI tasks — consider as default vision backbone
- **CUA (trycua)** has the best sandbox API design — their screenshot/mouse/keyboard abstraction is clean
- **Open Computer Use** has good multi-agent architecture patterns
- **Astropad Workbench** validates the market need (launched Apr 2026 for AI agent monitoring)
- See [COMPETITIVE_RESEARCH.md](./COMPETITIVE_RESEARCH.md) for full analysis

## Notes
- RustDesk is GPL-3.0, so fork must also be GPL-3.0
- Could potentially be an OpenClaw skill/plugin
- Alternative approach: skip RustDesk entirely, build lightweight agent from scratch using system APIs
- UI-TARS action parser (`pip install ui-tars`) could be used for action parsing
- Consider supporting UI-TARS-2 (7B) as local vision option for low-latency scenarios
