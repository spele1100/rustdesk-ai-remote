# RustDesk Source Analysis for AI Remote Control

## Directory Tree Overview

```
rustdesk/
├── src/
│   ├── client/              # Client (controller/viewer) side
│   │   ├── io_loop.rs       # Main client I/O loop: receives video frames, sends input events
│   │   ├── helper.rs        # Helper utilities
│   │   ├── screenshot.rs    # Screenshot capture from client side
│   │   └── file_trait.rs    # File transfer trait
│   ├── client.rs            # Client struct & connection logic
│   ├── server/              # Server (controlled/target) side
│   │   ├── video_service.rs # Screen capture → encode → send (1419 lines)
│   │   ├── input_service.rs # Receive input events → inject via enigo/rdev (2373 lines)
│   │   ├── connection.rs    # Main server connection handler (5720 lines - biggest file)
│   │   ├── audio_service.rs # Audio capture & streaming
│   │   ├── display_service.rs
│   │   ├── clipboard_service.rs
│   │   ├── port_forward.rs
│   │   ├── terminal_service.rs
│   │   ├── video_qos.rs     # Quality of service / adaptive bitrate
│   │   ├── wayland.rs       # Linux Wayland-specific capture/input
│   │   ├── uinput.rs        # Linux uinput for input injection
│   │   └── rdp_input.rs     # RDP-based input for Wayland
│   ├── server.rs            # Server entry point
│   ├── flutter.rs           # Flutter bridge (2363 lines) - UI callbacks
│   ├── flutter_ffi.rs       # FFI bridge for Flutter
│   ├── ipc.rs               # IPC between service and UI process
│   ├── keyboard.rs          # Keyboard mapping
│   ├── rendezvous_mediator.rs # NAT traversal / signaling
│   ├── lan.rs               # LAN discovery
│   ├── port_forward.rs      # Port forwarding
│   ├── platform/            # Platform-specific code (Linux, Windows, macOS)
│   ├── ui/                  # UI abstraction layer
│   ├── privacy_mode/
│   └── common.rs            # Shared utilities
├── libs/
│   ├── scrap/               # Screen capture library
│   │   └── src/
│   │       ├── common/      # Platform-agnostic codec/encode logic
│   │       │   ├── codec.rs # Video encoder/decoder (VP8/VP9/H264/H265/AV1/AOM)
│   │       │   ├── vpxcodec.rs
│   │       │   ├── aom.rs
│   │       │   └── convert.rs
│   │       ├── x11/         # Linux X11 capture (XCB + SHM)
│   │       │   ├── capturer.rs  # Capturer struct using XCB shared memory
│   │       │   ├── display.rs   # Display enumeration
│   │       │   └── iter.rs      # Frame iterator
│   │       ├── wayland/     # Linux Wayland capture (PipeWire)
│   │       ├── dxgi/        # Windows DXGI Desktop Duplication
│   │       ├── quartz/      # macOS CGWindowListCreateImage
│   │       └── android/     # Android MediaProjection
│   ├── enigo/               # Input simulation library
│   │   └── src/
│   │       ├── lib.rs       # Cross-platform input traits
│   │       ├── linux/       # XTest / uinput
│   │       ├── win/         # SendInput
│   │       └── macos/       # CGEvent
│   ├── hbb_common/          # Shared library (submodule - protocol, config, networking)
│   │   └── protos/
│   │       ├── message.proto    # Main message types (video, input, misc)
│   │       └── rendezvous.proto # Signaling/hole-punch protocol
│   ├── clipboard/           # Clipboard handling
│   ├── virtual_display/     # Virtual display driver
│   └── portable/            # Portable build support
├── flutter/                 # Flutter UI (entirely replaceable for AI agent)
└── Cargo.toml               # Workspace root
```

## Key Files and Their Purposes

### 1. Screen Capture (`libs/scrap/`)

**How it works:**
- Platform-specific `Capturer` structs that produce raw RGB frames
- **Linux X11**: Uses XCB shared memory (shm) for fast frame reads from X server
- **Linux Wayland**: Uses PipeWire (screen cast portal via D-Bus)
- **Windows**: DXGI Desktop Duplication API
- **macOS**: CoreGraphics `CGWindowListCreateImage`
- Frames are encoded by `codec.rs` into VP9/VP8/H264/H265/AV1 via platform encoders

**Key structs:**
- `Capturer` (in platform subdirs) — yields raw pixel buffers
- `Encoder` trait (in `common/codec.rs`) — encodes frames to compressed video
- `CodecFormat` enum — VP8, VP9, H264, H265, AV1, AOM

### 2. Input Injection (`libs/enigo/` + `src/server/input_service.rs`)

**How it works:**
- `enigo` crate provides cross-platform `MouseControllable` and `KeyboardControllable` traits
- **Linux**: XTest extension (X11) or uinput (Wayland)
- **Windows**: `SendInput` Win32 API
- **macOS**: `CGEvent` Quartz Event Services
- `input_service.rs` receives `MouseEvent`, `KeyEvent`, `PointerDeviceEvent` messages and calls enigo
- Also uses `rdev` crate for raw key simulation

**Key functions in `input_service.rs`:**
- `handle_mouse_()` — parses MouseEvent mask (button + state), moves cursor, clicks
- `handle_key_()` — presses/releases keys via enigo KeyboardControllable
- Mouse mask encoding: bit 0 = left, bit 1 = right, bit 2 = middle, higher bits = scroll

### 3. Network Protocol (`libs/hbb_common/protos/`)

**Protocol is protobuf-based.** Key message types from `message.proto`:

#### Video (Server → Client)
- `VideoFrame` — contains `EncodedVideoFrames` (VP9/VP8/H264/H265/AV1) or raw RGB/YUV
- `CursorData` — cursor image
- `CursorPosition` — cursor coordinates

#### Input (Client → Server)  
- `MouseEvent` — `{mask, x, y, modifiers}` — mouse move/click/scroll
- `KeyEvent` — `{down, press, control_key/chr/unicode/seq, modifiers, mode}` — keyboard
- `PointerDeviceEvent` — touch events (scale, pan)

#### Connection
- `LoginRequest` — authentication with optional sub-types (file transfer, port forward, terminal)
- `LoginResponse` — error or `PeerInfo` (displays, platform info)
- `ChatMessage` — text chat

#### Miscellaneous
- `Clipboard` / `MultiClipboards` — clipboard sync
- `OptionMessage` — quality/resolution/audio settings
- `FileEntry`, `FileDirectory`, `ReadDir` — file transfer

### 4. Client/Server Architecture

**Server (target PC):**
- `src/server/connection.rs` — accepts connections, authenticates, spawns service threads
- `src/server/video_service.rs` — captures screen, encodes, sends `VideoFrame` messages
- `src/server/input_service.rs` — receives input messages, injects via enigo
- Each service runs in its own thread with MPSC channels

**Client (viewer/controller):**
- `src/client/io_loop.rs` — main loop: receives video frames, sends input events
- `src/client.rs` — `Client` struct manages connection state
- `Session<T: InvokeUiSession>` — generic over UI backend (Flutter or headless)

### 5. Flutter Bridge (`src/flutter.rs`)

- `InvokeUiSession` trait implementation for Flutter
- Callbacks for: `on_connected`, `on_disconnected`, `on_peer_info`, `on_remote_clipboard`
- Video frame delivery via `on_frame` callback (but actual frame data goes through FFI binary channel)
- **This is entirely replaceable** — we just need a different `InvokeUiSession` implementation

## Recommended Files to Modify/Remove for AI Control

### Keep (Core - Don't Modify)
- `libs/scrap/` — screen capture (use as-is)
- `libs/enigo/` — input injection (use as-is)  
- `libs/hbb_common/` — protocol definitions, networking (use as-is)
- `src/server/` — entire server side runs on target PC unchanged
- `src/keyboard.rs` — key mapping

### Modify
- `src/client/io_loop.rs` — replace Flutter callbacks with WebSocket/HTTP API
- `src/client.rs` — headless client mode (no UI dependency)
- `src/flutter.rs` / `src/flutter_ffi.rs` — **DELETE** (not needed)
- `src/ui/` — **DELETE** (UI layer)
- `src/ui_session_interface.rs` — modify `InvokeUiSession` trait for headless

### Remove Entirely
- `flutter/` — entire Flutter UI project
- `src/ui/` — UI abstraction
- `src/tray.rs` — system tray (optional, not needed for agent)
- `src/privacy_mode/` — optional, can keep
- `src/plugin/` — plugin framework, not needed

## Suggested Minimal Agent Architecture

### Approach: Headless Client (Not a Fork of Server)

The **server side runs unmodified** on the target PC. We only need to build a headless client that:

1. Connects to the RustDesk server (target PC) using existing protocol
2. Receives video frames → decodes → sends screenshots to AI vision API
3. Receives AI commands → translates to `MouseEvent`/`KeyEvent` protobuf messages → sends to server

```
┌─────────────────────┐         Protobuf/TCP          ┌──────────────────┐
│  Target PC           │◄────────────────────────────►│  AI Agent (VPS)   │
│  RustDesk Server     │                               │  (Headless Client)│
│  (unmodified)        │                               │                   │
│  - video_service     │  VideoFrame messages ────────►│  Decode → PNG     │
│  - input_service     │◄───── MouseEvent/KeyEvent ────│  AI Command → Proto│
│  - connection        │                               │                   │
└─────────────────────┘                               └────────┬──────────┘
                                                               │
                                                               ▼
                                                      ┌──────────────────┐
                                                      │  AI Controller   │
                                                      │  Vision API call │
                                                      │  (GLM-4.6V)      │
                                                      └──────────────────┘
```

### Minimal Files Needed for Headless Client

```
ai-agent/
├── Cargo.toml              # Depend on hbb_common, scrap (decoder only)
├── src/
│   ├── main.rs             # Entry: connect to target, start loops
│   ├── client.rs           # Simplified Client (no UI dependency)
│   ├── io_loop.rs          # I/O loop: receive frames, send inputs
│   ├── frame_sink.rs       # Decode video frames → save as PNG/JPEG
│   ├── command_source.rs   # WebSocket/HTTP server for AI commands
│   └── proto_bridge.rs     # AI command JSON → protobuf Message
```

### Alternative: Standalone Agent (No RustDesk Protocol)

If we don't want to deal with RustDesk's protobuf + encryption + NAT traversal, we can extract just the core libraries:

```
minimal-agent/
├── screen_capture.rs   # Use scrap's Capturer directly
├── input_inject.rs     # Use enigo directly  
├── api_server.rs       # HTTP/WebSocket server
└── main.rs             # Tie it together
```

This is simpler but loses: encryption, NAT traversal, multi-platform builds.

## Protocol Message Types Summary

### Client → Server (Input)
| Message | Fields | Purpose |
|---------|--------|---------|
| `MouseEvent` | mask, x, y, modifiers | Mouse move/click/scroll |
| `KeyEvent` | down, press, control_key/chr/unicode, modifiers, mode | Keyboard input |
| `PointerDeviceEvent` | touch_event, modifiers | Touch gestures |

### Server → Client (Video/Audio)
| Message | Fields | Purpose |
|---------|--------|---------|
| `VideoFrame` | vp9s/h264s/h265s/vp8s/av1s/rgb/yuv, display | Encoded screen frame |
| `CursorData` | id, hotx, hoty, width, height, colors | Cursor image |
| `CursorPosition` | x, y | Cursor position |

### Handshake
| Message | Purpose |
|---------|---------|
| `LoginRequest` | Auth + session type (desktop/file/terminal/port forward) |
| `LoginResponse` | Success (with PeerInfo) or error |
| `PeerInfo` | Target platform, displays, capabilities |

### Utility
| Message | Purpose |
|---------|---------|
| `OptionMessage` | Quality/resolution/audio settings |
| `ChatMessage` | Text chat |
| `Clipboard` | Clipboard sync |
| `Hash` | Password challenge |

## Key Insights

1. **Video encoding is complex but decoupled** — the server handles encoding, client just needs to decode. For AI use, we can request RGB frames or decode VP9/H264 to raw pixels.

2. **Input is straightforward** — `enigo` directly calls OS APIs. The `MouseEvent` mask encoding is: bit 0=left, 1=right, 2=middle, bits 3-6=scroll count, bit 7=scroll direction.

3. **Protocol is binary protobuf over TCP** — no REST/WebSocket. For AI integration, we need a translation layer (protobuf ↔ JSON).

4. **The server is already headless** — RustDesk's server (service) runs as a background daemon with no GUI. Only the client has Flutter UI.

5. **`hbb_common` is a git submodule** — it contains the proto definitions and networking code. Must be cloned separately (`git submodule update --init`).

6. **Simplest path forward**: Build a standalone Rust agent using `scrap` + `enigo` + `tokio` with an HTTP/WebSocket API, skipping RustDesk's protocol entirely. This avoids the complexity of protobuf, encryption, and NAT traversal while giving us screen capture + input injection.
