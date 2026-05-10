# RustDesk Protocol Specification

Reverse-engineered from RustDesk source code (v1.3.x+), protos, and tcp.rs.

---

## 1. Connection Flow

### Full Sequence Diagram

```
Client (Controller)          hbbs (Rendezvous)          Target (Controlled)
      │                            │                            │
      │  ── RegisterPk ──────────► │                            │
      │  ◄── RegisterPkResponse ── │                            │
      │                            │                            │
      │  ── TestNatRequest ──────► │                            │
      │  ◄── TestNatResponse ───── │                            │
      │                            │                            │
      │══════════════════════════════════════════════════════════│
      │                  PHASE 1: CONNECT TO hbbs               │
      │══════════════════════════════════════════════════════════│
      │                            │                            │
      │  TCP connect to hbbs:21116 │                            │
      │  (or WS to hbbs:21118)     │                            │
      │                            │                            │
      │  ── secure_tcp ──────────► │  (KeyExchange via NaCl)    │
      │  ◄── KeyExchange ───────── │  (if key+token present)    │
      │  ── KeyExchange ─────────► │                            │
      │                            │                            │
      │══════════════════════════════════════════════════════════│
      │                  PHASE 2: PUNCH HOLE                    │
      │══════════════════════════════════════════════════════════│
      │                            │                            │
      │  ── PunchHoleRequest ────► │                            │
      │    {id, nat_type, token,   │                            │
      │     licence_key, version}  │                            │
      │                            │  ── PunchHole ────────────►│
      │                            │    {socket_addr, relay_srv,│
      │                            │     nat_type}              │
      │                            │                            │
      │  ◄── PunchHoleResponse ── │                             │
      │    {socket_addr=peer_addr, │                             │
      │     pk=signed_id_pk,       │                             │
      │     relay_server,          │                             │
      │     is_local, feedback}    │                             │
      │                            │                             │
      │═══════════════════════════════════════════════════════════│
      │        PHASE 2b: FALLBACK TO RELAY (if punch fails)     │
      │═══════════════════════════════════════════════════════════│
      │                            │                             │
      │  ── RequestRelay ────────► │                             │
      │  ◄── RelayResponse ────── │  {uuid, relay_server,       │
      │                            │   socket_addr, pk}          │
      │                            │                             │
      │  TCP connect to hbbr:21117 │                             │
      │  ── KeyExchange ───────────────────────────────────────►│
      │  ◄── KeyExchange ────────────────────────────────────────│
      │                            │                             │
      │═══════════════════════════════════════════════════════════│
      │         PHASE 3: PEER-TO-PEER KEY EXCHANGE               │
      │═══════════════════════════════════════════════════════════│
      │                            │                             │
      │  (direct or relayed TCP)   │                             │
      │                            │                             │
      │  ◄── SignedId ──────────────────────────────────────────│
      │      {id=signed(peer_id||peer_pk)}                      │
      │                            │                             │
      │  Client verifies signature using rs_pk (server's sign key)│
      │  Extracts peer's NaCl box PublicKey (32 bytes)           │
      │                            │                             │
      │  Generates:                                               │
      │    - ephemeral box::keypair (our_pk, our_sk)             │
      │    - random secretbox::Key (symmetric session key)       │
      │    - box::seal(symm_key, nonce=[0;24], peer_pk, our_sk) │
      │                            │                             │
      │  ── PublicKey ──────────────────────────────────────────►│
      │      {asymmetric_value=our_pk,                            │
      │       symmetric_value=sealed_symm_key}                   │
      │                            │                             │
      │  Both sides now share the same secretbox::Key            │
      │  All further messages encrypted with XSalsa20-Poly1305   │
      │                            │                             │
      │═══════════════════════════════════════════════════════════│
      │         PHASE 4: AUTHENTICATION (LoginRequest)           │
      │═══════════════════════════════════════════════════════════│
      │                            │                             │
      │  ◄── Misc(Hash) ────────────────────────────────────────│
      │      {salt, challenge}                                    │
      │                            │                             │
      │  Client computes:                                         │
      │    hash1 = SHA256(password + salt)                        │
      │    hash2 = SHA256(hash1 + challenge)                      │
      │                            │                             │
      │  ── LoginRequest ───────────────────────────────────────►│
      │      {username=peer_id,                                   │
      │       password=hash2,                                     │
      │       my_id, my_name, my_platform,                        │
      │       option: OptionMessage,                              │
      │       session_id, version, ...}                           │
      │                            │                             │
      │  ◄── LoginResponse ─────────────────────────────────────│
      │      {peer_info: {username, hostname, platform,          │
      │       displays, current_display, version, ...}}          │
      │                            │                             │
      │═══════════════════════════════════════════════════════════│
      │         PHASE 5: SESSION (video + input)                 │
      │═══════════════════════════════════════════════════════════│
      │                            │                             │
      │  ◄── VideoFrame(vp9s/h264s/...) ────────────────────────│
      │  ◄── VideoFrame(...) ───────────────────────────────────│
      │  ── MouseEvent ────────────────────────────────────────►│
      │  ── KeyEvent ──────────────────────────────────────────►│
      │  ◄── Misc(SwitchDisplay) ───────────────────────────────│
      │  ◄── Misc(PermissionInfo) ──────────────────────────────│
      │  ◄── CursorData / CursorPosition ───────────────────────│
      │  ...                                                      │
```

---

## 2. Transport Layer

### 2.1 TCP Framing

Messages are framed using a **length-prefix** codec (`BytesCodec`):
- 4 bytes (u32 big-endian): message length
- N bytes: protobuf-encoded message

### 2.2 WebSocket Alternative

If `use_ws()` is true, the client connects via WebSocket to port 21118 (hbbs) / 21119 (hbbr).
WSS provides TLS, so the `secure_tcp` KeyExchange with hbbs is **skipped** (but peer-to-peer key exchange still happens).

### 2.3 Encryption (Data Stream)

After key exchange, **all messages** are encrypted with:

- **Algorithm:** XSalsa20-Poly1305 (NaCl `secretbox`)
- **Key:** 32-byte random symmetric key generated by the client
- **Nonce:** 24 bytes, constructed as:
  ```
  nonce[0..8] = send_counter (u64, little-endian)
  nonce[8..24] = 0x00
  ```
- **Counter:** Each side maintains independent send (`.1`) and receive (`.2`) counters, incrementing by 1 per message

The `Encrypt` struct in `tcp.rs`:
```rust
pub struct Encrypt(pub Key, pub u64, pub u64);
//                        key   send_seq  recv_seq
```

`enc()`: `secretbox::seal(data, nonce(send_seq), key)` → prefixed with MAC (16 bytes)
`dec()`: `secretbox::open(data, nonce(recv_seq), key)` → strips MAC, returns plaintext

### 2.4 Key Exchange Details

**Step 1 — Server key exchange (with hbbs):**
- Server sends `KeyExchange { keys: [signed_pk] }` — signed with the server's ed25519 signing key
- Client verifies with `RS_PUB_KEY` (hardcoded or configured)
- Same pattern: generate box keypair, encrypt symmetric key, send back

**Step 2 — Peer key exchange (with target):**
- Target sends `SignedId { id: sign(peer_id || peer_pk) }` — signed with its ed25519 key
- Client verifies using the signing public key received via PunchHoleResponse.pk (which was signed by hbbs)
- Client generates:
  ```
  (our_pk, our_sk) = box_::gen_keypair()
  symm_key = secretbox::gen_key()       // 32 random bytes
  nonce = [0u8; 24]                     // zero nonce for key exchange only
  sealed = box_::seal(symm_key, nonce, peer_pk, our_sk)
  ```
- Sends `PublicKey { asymmetric_value: our_pk, symmetric_value: sealed }`
- Target decrypts: `symm_key = box_::open(sealed, nonce, our_pk, target_sk)`
- Both sides now share `symm_key` for XSalsa20-Poly1305

---

## 3. Protobuf Message Types

### 3.1 Rendezvous Messages (`rendezvous.proto` → `RendezvousMessage`)

Used for signaling via hbbs/hbbr.

| Field # | Message | Direction | Purpose |
|---------|---------|-----------|---------|
| 6 | RegisterPeer | Server→hbbs | Periodic registration |
| 7 | RegisterPeerResponse | hbbs→Server | Registration ack |
| 8 | PunchHoleRequest | Client→hbbs | Request to connect to peer |
| 9 | PunchHole | hbbs→Server | Forward punch request |
| 10 | PunchHoleSent | Server→hbbs | Acknowledge punch sent |
| 11 | PunchHoleResponse | hbbs→Client | Punch result (peer addr or failure) |
| 12 | FetchLocalAddr | Server→hbbs | Get local address |
| 13 | LocalAddr | hbbs→Server | Local address response |
| 15 | RegisterPk | Server→hbbs | Register public key |
| 16 | RegisterPkResponse | hbbs→Server | PK registration result |
| 18 | RequestRelay | Client→hbbs | Request relay connection |
| 19 | RelayResponse | hbbs→Client | Relay server address |
| 20 | TestNatRequest | Any→hbbs | NAT type detection |
| 21 | TestNatResponse | hbbs→Any | NAT test result |
| 25 | KeyExchange | Both | Encryption key exchange |
| 26 | HealthCheck | Client→hbbs | Keep-alive |

### 3.2 Data Messages (`message.proto` → `Message`)

The main `Message` oneof (used after connection is established):

```protobuf
message Message {
  oneof union {
    LoginRequest login_request = 3;
    LoginResponse login_response = 4;
    Hash hash = 6;                    // Password challenge
    MouseEvent mouse_event = 7;
    KeyEvent key_event = 8;
    VideoFrame video_frame = 9;       // Encoded screen frame
    ChatMessage chat_message = 10;
    CursorData cursor_data = 11;
    CursorPosition cursor_position = 12;
    AudioFormat audio_format = 13;
    AudioFrame audio_frame = 14;
    Misc misc = 20;                   // Catch-all for many sub-messages
    Cliprdr cliprdr = 21;            // Clipboard
    MultiClipboards multi_clipboards = 22;
    PointerDeviceEvent pointer_device_event = 23;
    VoiceCallRequest voice_call_request = 24;
    VoiceCallResponse voice_call_response = 25;
    Auth2FA auth_2fa = 26;
    ScreenshotRequest screenshot_request = 27;
    ScreenshotResponse screenshot_response = 28;
    PublicKey public_key = 29;        // Key exchange (peer-to-peer)
    SignedId signed_id = 30;          // Identity exchange
    TerminalAction terminal_action = 31;
    TerminalOpened terminal_opened = 32;
    TerminalData terminal_data = 33;
  }
}
```

---

## 4. Authentication

### 4.1 Password Hash Challenge-Response

The target sends a `Hash` message containing `salt` and `challenge` (random strings).

Client computes:
```
hash1 = SHA256(raw_password || salt)
hash2 = SHA256(hash1 || challenge)
```

The `hash2` is sent as `LoginRequest.password` (bytes field).

Server side verifies by computing the same with its stored password hash.

### 4.2 No-Password / Token Auth

If no password is set, the `LoginRequest.password` is empty. The target may accept or require interactive confirmation.

### 4.3 OS Login

`LoginRequest.os_login` can carry OS-level credentials (`{username, password}`) for UAC/elevation on Windows.

### 4.4 2FA

If enabled, server responds with `Auth2FA` requirement. Client must send back `Auth2FA { code, hwid }`.

---

## 5. Video Frames

### 5.1 VideoFrame Structure

```protobuf
message VideoFrame {
  oneof union {
    EncodedVideoFrames vp9s = 6;
    RGB rgb = 7;
    YUV yuv = 8;
    EncodedVideoFrames h264s = 10;
    EncodedVideoFrames h265s = 11;
    EncodedVideoFrames vp8s = 12;
    EncodedVideoFrames av1s = 13;
  }
  int32 display = 14;   // Display index (multi-monitor)
}

message EncodedVideoFrames {
  repeated EncodedVideoFrame frames = 1;
}

message EncodedVideoFrame {
  bytes data = 1;     // Raw encoded bitstream (VP9/H264/etc.)
  bool key = 2;       // Is this a keyframe?
  int64 pts = 3;      // Presentation timestamp
}
```

### 5.2 Codec Negotiation

Client sends `Misc(OptionMessage)` with `supported_decoding`:
```protobuf
message SupportedDecoding {
  int32 ability_vp9 = 1;
  int32 ability_h264 = 2;
  int32 ability_h265 = 3;
  PreferCodec prefer = 4;    // Auto/VP9/H264/H265/VP8/AV1
  int32 ability_vp8 = 5;
  int32 ability_av1 = 6;
  CodecAbility i444 = 7;
  Chroma prefer_chroma = 8;  // I420 or I444
}
```

Server selects the best mutually-supported codec.

### 5.3 For AI Use

For an AI client, **VP9 is recommended** — widely supported, good quality. Alternatively, request RGB/YUV if bandwidth permits (no decoder needed, just raw pixels).

Each `EncodedVideoFrame.data` is a raw codec bitstream chunk. For VP9, these are complete frames (key or delta). For H264/H265, may be NAL units.

---

## 6. Input Events

### 6.1 MouseEvent

```protobuf
message MouseEvent {
  int32 mask = 1;                    // Button + action flags
  sint32 x = 2;                      // X coordinate (signed, can be negative)
  sint32 y = 3;                      // Y coordinate (signed)
  repeated ControlKey modifiers = 4; // Alt, Shift, Control, Meta
}
```

**Mask encoding:**
| Bit(s) | Meaning |
|--------|---------|
| 0 | Left button down |
| 1 | Right button down |
| 2 | Middle button down |
| 3-6 | Scroll count (absolute value) |
| 7 | Scroll direction (0=vertical, 1=horizontal) |

Mouse move: `mask=0, x, y` (just coordinates, no buttons)

**Constants from source:**
```rust
MOUSE_BUTTON_LEFT = 1;   // bit 0
MOUSE_BUTTON_RIGHT = 2;  // bit 1  
MOUSE_BUTTON_MIDDLE = 4; // bit 2
MOUSE_TYPE_DOWN = 0;     // press event
MOUSE_TYPE_UP = 0;       // release event (same, inferred from previous state)
MOUSE_TYPE_TRACKPAD = 8; // special trackpad scroll flag
```

Actually, for click: send `mask=1` (left down) then `mask=0` (release all).
For right click: `mask=2` then `mask=0`.

### 6.2 KeyEvent

```protobuf
message KeyEvent {
  bool down = 1;                     // true=press, false=release
  bool press = 2;                    // true=click (down+up combined)
  oneof union {
    ControlKey control_key = 3;      // Named key (Alt, Return, F1, etc.)
    uint32 chr = 4;                  // Position key code (scancode)
    uint32 unicode = 5;              // Unicode codepoint
    string seq = 6;                  // Character sequence (text input)
    uint32 win2win_hotkey = 7;       // Win-specific hotkey
  }
  repeated ControlKey modifiers = 8; // Active modifiers
  KeyboardMode mode = 9;            // Legacy/Map/Translate/Auto
}
```

**KeyboardMode:**
- `Legacy (0)`: Use `control_key` enum values
- `Map (1)`: Use `chr` with platform scancodes
- `Translate (2)`: Use `chr` with local layout mapping
- `Auto (3)`: Client auto-selects

**For AI use, simplest is:**
- `mode = Auto`
- For typing text: `seq = "hello"` with `press = true`
- For special keys: `control_key = Return` with `press = true`
- For combos: set `modifiers = [Control]` and `control_key = A`

### 6.3 ControlKey Enum (Key Names)

Full list (67+ keys) includes: `Alt, Backspace, CapsLock, Control, Delete, DownArrow, End, Escape, F1-F12, Home, LeftArrow, Meta, PageDown, PageUp, Return, RightArrow, Shift, Space, Tab, UpArrow, CtrlAltDel, LockScreen, Numpad0-9`, etc.

---

## 7. Important Misc Sub-Messages

The `Misc` message is a catch-all:

| Sub-message | Purpose |
|---|---|
| `Hash` | Password challenge (salt + challenge) |
| `OptionMessage` | Quality/resolution/codec settings |
| `SwitchDisplay` | Display change notification |
| `PermissionInfo` | Keyboard/clipboard/file permissions |
| `AudioFormat` | Audio sample rate + channels |
| `close_reason` | Session disconnect reason |
| `refresh_video` | Request video keyframe refresh |
| `TestDelay` | Latency measurement |
| `CaptureDisplays` | Select active displays |

---

## 8. Ports

| Port | Service | Protocol |
|------|---------|----------|
| 21115 | hbbs | NAT test (TCP) |
| 21116 | hbbs | Rendezvous (TCP + WebSocket) |
| 21117 | hbbr | Relay (TCP) |
| 21118 | hbbs | WebSocket relay |
| 21119 | hbbr | WebSocket relay |

---

## 9. Existing Implementations & Reusable Projects

### 9.1 RustDesk Official Web Client
- **URL:** https://rustdesk.com/web/
- **Status:** Available, communicates via WebSocket using same protobuf protocol
- **Source:** Not fully open-sourced as standalone, but DeepWiki documents the architecture
- **Key insight:** Proves a browser-based client using the protobuf protocol over WebSocket works

### 9.2 UNITRONIX/Rustdesk-FreeConsole
- **URL:** https://github.com/UNITRONIX/Rustdesk-FreeConsole
- **Purpose:** Free web console for RustDesk (device management)
- **Had web client plan** but the plan doc was removed (404)
- **Useful for:** API server reference, device management patterns

### 9.3 palmstamp/rustdesk-client
- **URL:** https://github.com/palmstamp/rustdesk-client
- **Purpose:** Pre-built RustDesk client packages

### 9.4 DeepWiki Protocol Documentation
- **URL:** https://deepwiki.com/rustdesk/rustdesk/2.3-client-server-communication
- **Content:** Comprehensive protocol documentation auto-generated from source
- **Note:** JS-rendered, not easily fetchable, but good for reference

### 9.5 No Known Headless/Python Client
No existing implementation of a standalone RustDesk client in Python or other non-Rust language was found. The protocol is complex enough that all existing implementations use the Rust codebase directly.

---

## 10. Minimum Viable Client Implementation Plan

### Architecture Decision: Two Approaches

#### Approach A: Rust Headless Client (Recommended)

**Pros:** Reuse RustDesk's networking + encryption + protobuf directly
**Cons:** Requires Rust toolchain, complex build

```
ai-remote-client/ (Rust crate)
├── Cargo.toml
├── protos/ → symlink to hbb_common protos
├── src/
│   ├── main.rs              # Entry point: parse config, connect
│   ├── connection.rs        # Full connection flow (punch/relay/key exchange/login)
│   ├── video_sink.rs        # Receive VideoFrame → decode → PNG/JPEG
│   ├── input.rs             # Accept commands → MouseEvent/KeyEvent
│   ├── api.rs               # HTTP/WebSocket server for AI controller
│   └── config.rs            # Connection config (server, peer ID, password)
└── build.rs                 # Compile protos
```

**Dependencies:**
- `hbb_common` (or extract protos + tcp.rs)
- `protobuf` / `prost` for message serialization
- `sodiumoxide` or `libsodium` for NaCl crypto
- `tokio` for async runtime
- `vp9` / `ffmpeg` for video decoding

**Implementation steps:**
1. Extract protobuf definitions, compile to Rust structs
2. Implement TCP framing (length-prefix codec)
3. Implement NaCl key exchange (box + secretbox)
4. Implement connection flow: PunchHoleRequest → PunchHoleResponse → direct/relay
5. Implement peer key exchange: SignedId → PublicKey
6. Implement login: receive Hash → compute response → send LoginRequest
7. Implement video frame reception and decoding
8. Implement input event sending (MouseEvent, KeyEvent)
9. Add HTTP/WebSocket API layer for AI controller

#### Approach B: Standalone Agent (Skip RustDesk Protocol)

**Pros:** Much simpler, no RustDesk dependency
**Cons:** No NAT traversal, no encryption, no multi-platform builds

```
ai-agent/ (Python or Rust)
├── screen_capture.rs   # Use scrap's Capturer directly on target
├── input_inject.rs     # Use enigo directly on target
├── api_server.rs       # HTTP/WebSocket server
└── main.rs
```

This runs ON the target machine — no remote protocol needed.

### Recommended: Hybrid Approach

1. **On the target machine:** Run RustDesk server (unmodified, standard install)
2. **On the VPS/controller:** Build a minimal Rust client that speaks the RustDesk protocol
3. **Wrap it** with an HTTP API that the AI controller calls

This gives us NAT traversal + encryption for free, while keeping the AI control logic simple.

### Estimated Effort

| Component | Effort | Notes |
|-----------|--------|-------|
| Protobuf compilation | 0.5 day | Just run protoc on existing .proto files |
| TCP framing + encryption | 1 day | Copy from hbb_common/src/tcp.rs |
| Connection flow (punch/relay) | 2-3 days | Complex, many edge cases |
| Key exchange | 1 day | NaCl box + secretbox, well-documented |
| Login auth | 0.5 day | SHA256 challenge-response |
| Video frame reception | 1 day | Decode VP9 with libvpx/ffmpeg |
| Input event sending | 0.5 day | Simple protobuf construction |
| HTTP API layer | 1 day | Axum/Actix for REST+WS |
| Testing & debugging | 2-3 days | NAT traversal edge cases |
| **Total** | **~10 days** | |

### Supported Server Versions

The protocol is stable across RustDesk 1.2.x and 1.3.x. The proto definitions are backward-compatible (proto3). A client built against current protos should work with:
- RustDesk Server (hbbs/hbbr) 1.1.x+
- RustDesk Server Pro
- Self-hosted community server

---

## 11. Key Source References

| File | Purpose |
|------|---------|
| `src/client.rs:400-560` | Connection: PunchHoleRequest, peer key exchange |
| `src/client.rs:760-820` | Peer-to-peer key exchange (SignedId → PublicKey) |
| `src/client.rs:2680-2760` | LoginRequest construction |
| `src/client.rs:3550-3590` | Password hashing (SHA256 challenge-response) |
| `src/client.rs:3110-3160` | send_mouse() — MouseEvent construction |
| `src/client/io_loop.rs:1280-1310` | VideoFrame reception in main loop |
| `src/common.rs:1939-1990` | secure_tcp — server KeyExchange |
| `src/common.rs:2005-2030` | create_symmetric_key_msg — NaCl key generation |
| `libs/hbb_common/src/tcp.rs` | FramedStream + Encrypt (XSalsa20-Poly1305) |
| `libs/hbb_common/protos/message.proto` | All data message definitions |
| `libs/hbb_common/protos/rendezvous.proto` | All signaling message definitions |
