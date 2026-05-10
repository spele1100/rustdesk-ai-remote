# Headless RustDesk Client

A Python headless client for RustDesk remote desktop — no GUI, just protocol + video decode + input send. Designed to be controlled by an AI agent via a clean HTTP API.

## Setup

```bash
# Install protoc (protobuf compiler)
apt install -y protobuf-compiler

# Compile proto files (already done, but if you need to recompile):
protoc --python_out=. --proto_path=protos protos/message.proto protos/rendezvous.proto

# Install dependencies
pip3 install -r requirements.txt

# Make sure ffmpeg is available (for VP9/H264 decoding)
apt install -y ffmpeg
```

## Quick Start

```bash
# Start with server and target
python3 client.py --server your-rustdesk-server.com --target 123456789 --password secret --auto-connect

# Or just start the API and connect later
python3 client.py --server your-rustdesk-server.com
```

## HTTP API

All endpoints accept/return JSON unless noted.

### `GET /status`
Connection status.
```json
{
  "state": "authenticated",
  "my_id": "123456",
  "target_id": "987654321",
  "peer_info": { "username": "...", "hostname": "...", "displays": [...] },
  "frame_count": 42,
  "has_frame": true
}
```

### `GET /frame`
Latest decoded frame as PNG image. Returns `image/png` or 404.

### `POST /connect`
Connect to a RustDesk peer.
```json
{ "target_id": "123456789", "password": "secret" }
```

### `POST /disconnect`
Disconnect from current peer.

### `POST /mouse`
Send raw mouse event.
```json
{ "x": 500, "y": 300, "mask": 0, "modifiers": [] }
```
Mask bits: 1=left, 2=right, 4=middle.

### `POST /key`
Send raw key event.
```json
{ "down": true, "press": false, "chr": 65, "modifiers": [] }
```

### `POST /click`
Convenience: click at position.
```json
{ "x": 500, "y": 300, "button": "left", "double": false }
```

### `POST /type`
Convenience: type a string.
```json
{ "text": "hello world" }
```

### `POST /key_combo`
Convenience: press key combo.
```json
{ "keys": ["ctrl", "c"] }
```
Supports: ctrl, alt, shift, meta/win/cmd, enter, escape, tab, space, backspace, delete, arrow keys, F1-F12, etc.

### `POST /scroll`
Convenience: scroll.
```json
{ "x": 500, "y": 300, "delta": -3 }
```
Negative = scroll down, positive = scroll up.

## Example: AI Controller Usage

```python
import requests

BASE = "http://localhost:8080"

# Connect
r = requests.post(f"{BASE}/connect", json={"target_id": "123456789", "password": "secret"})
print(r.json())

# Get screenshot
r = requests.get(f"{BASE}/frame")
with open("screenshot.png", "wb") as f:
    f.write(r.content)

# Click
r = requests.post(f"{BASE}/click", json={"x": 500, "y": 300})

# Type text
r = requests.post(f"{BASE}/type", json={"text": "Hello"})

# Ctrl+C
r = requests.post(f"{BASE}/key_combo", json={"keys": ["ctrl", "c"]})

# Scroll down 5 steps
r = requests.post(f"{BASE}/scroll", json={"x": 500, "y": 300, "delta": -5})
```

## Architecture

```
┌─────────────┐    RustDesk     ┌──────────────────┐
│  Target PC  │◄───Protocol────►│  Headless Client │
│  (RustDesk  │   (TCP/NaCl)    │  (Python)        │
│   Server)   │                 │                  │
└─────────────┘                 │  ┌────────────┐  │
                                │  │ HTTP API   │  │
                                │  │ :8080      │  │
                                │  └──────┬─────┘  │
                                │         │        │
                                │  ┌──────▼─────┐  │
                                │  │ VP9/H264   │  │
                                │  │ Decoder    │  │
                                │  │ (ffmpeg)   │  │
                                │  └────────────┘  │
                                └──────────────────┘
                                         ▲
                                         │ HTTP
                                  ┌──────┴─────┐
                                  │ AI Agent   │
                                  │ / Chi      │
                                  └────────────┘
```

## Connection Flow

1. TCP connect to RustDesk rendezvous server (default port 21116)
2. Register our public key → get assigned ID
3. PunchHoleRequest → get peer address or relay server
4. TCP connect to peer (direct or relay)
5. Exchange SignedId messages
6. Exchange PublicKey (NaCl key exchange → encrypted channel)
7. Receive Hash challenge → encrypt password → send LoginRequest
8. Receive LoginResponse with PeerInfo (display info)
9. Video frames arrive → decode via ffmpeg → store latest PNG
10. AI sends mouse/key events via HTTP API

## Config

Environment variables:
- `RUSTDESK_SERVER_HOST` — Server hostname
- `RUSTDESK_SERVER_PORT` — Rendezvous port (default 21116)
- `RUSTDESK_RELAY_PORT` — Relay port (default 21117)
- `RUSTDESK_TARGET_ID` — Target RustDesk ID
- `RUSTDESK_PASSWORD` — Remote password
- `RUSTDESK_CODEC` — Preferred codec (VP9, H264, H265, VP8, AV1)
- `RUSTDESK_API_PORT` — Local API port (default 8080)
- `RUSTDESK_API_HOST` — Local API bind host (default 0.0.0.0)

## Compatibility

- Works with RustDesk Server OSS (open source)
- Works with RustDesk Server Pro
- Handles both direct (P2P) and relay connections
- Supports VP9, H264, H265, VP8, AV1 codecs (auto-fallback)
