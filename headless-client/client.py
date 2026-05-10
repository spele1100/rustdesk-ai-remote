"""
Headless RustDesk client — connects via RustDesk protocol, decodes video,
and exposes an HTTP API for AI control.

Usage:
    python3 client.py --server host:21116 --target 123456789 --password secret
"""

import asyncio
import struct
import os
import sys
import json
import time
import subprocess
import logging
import argparse
from io import BytesIO

import message_pb2 as msg_pb2
import rendezvous_pb2 as rdv_pb2
from google.protobuf import message as _pb_msg
from nacl.public import PrivateKey, PublicKey, Box
from nacl.bindings import crypto_sign_keypair, crypto_sign

from config import Config
from crypto import generate_keypair, generate_sign_keypair, sign_id, encrypt, decrypt

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("headless")


# ── Wire helpers ────────────────────────────────────────────────────

async def read_exact(reader: asyncio.StreamReader, n: int) -> bytes:
    """Read exactly n bytes."""
    buf = b""
    while len(buf) < n:
        chunk = await reader.read(n - len(buf))
        if not chunk:
            raise ConnectionError("Connection closed")
        buf += chunk
    return buf


async def read_message(reader: asyncio.StreamReader) -> bytes:
    """Read a length-prefixed protobuf message."""
    raw_len = await read_exact(reader, 4)
    length = struct.unpack(">I", raw_len)[0]
    if length > 10_000_000:  # 10MB sanity check
        raise ValueError(f"Message too large: {length}")
    return await read_exact(reader, length)


async def write_message(writer: asyncio.StreamWriter, data: bytes):
    """Write a length-prefixed protobuf message."""
    writer.write(struct.pack(">I", len(data)) + data)
    await writer.drain()


# ── VP9/H264 decoding via ffmpeg ───────────────────────────────────

class VideoDecoder:
    """Decodes VP9/H264 frames to PNG using ffmpeg subprocess."""

    def __init__(self):
        self._process = None
        self._codec = None

    def _ensure_process(self, codec: str):
        """Start ffmpeg decoder process for the given codec."""
        if self._process is not None and self._codec == codec:
            return
        self.close()
        # Use raw video input with the appropriate codec
        fmt_map = {
            "vp9": "webm",
            "vp8": "webm",
            "h264": "h264",
            "h265": "hevc",
            "av1": "av1",
        }
        input_fmt = fmt_map.get(codec, codec)
        self._process = subprocess.Popen(
            [
                "ffmpeg", "-f", input_fmt, "-i", "-",
                "-f", "image2pipe", "-vcodec", "png", "-",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self._codec = codec

    def decode_frame(self, data: bytes, codec: str) -> bytes | None:
        """Decode a single video frame to PNG bytes. Returns None on failure."""
        self._ensure_process(codec)
        try:
            self._process.stdin.write(data)
            self._process.stdin.flush()
        except BrokenPipeError:
            # Restart
            self._codec = None
            self._ensure_process(codec)
            try:
                self._process.stdin.write(data)
                self._process.stdin.flush()
            except Exception:
                return None

        # Non-blocking read with timeout — ffmpeg needs enough data to produce output
        # For keyframes this should work, for deltas it may not produce output
        import select
        png_data = b""
        try:
            # Give ffmpeg a moment to produce output
            ready, _, _ = select.select([self._process.stdout], [], [], 0.1)
            if ready:
                # Read PNG — look for PNG signature and read until IEND
                chunk = self._process.stdout.read1(1024 * 1024)
                if chunk:
                    png_data = chunk
                    # Try to find IEND
                    while b"IEND" not in png_data and len(png_data) < 10_000_000:
                        ready, _, _ = select.select([self._process.stdout], [], [], 0.05)
                        if not ready:
                            break
                        more = self._process.stdout.read1(256 * 1024)
                        if not more:
                            break
                        png_data += more
        except Exception:
            pass

        if png_data and png_data[:4] == b"\x89PNG":
            return png_data
        return None

    def close(self):
        if self._process:
            try:
                self._process.stdin.close()
                self._process.terminate()
                self._process.wait(timeout=2)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None
            self._codec = None


# ── UDP Protocol for Rendezvous ────────────────────────────────────

class _RdvProtocol(asyncio.DatagramProtocol):
    """Simple asyncio datagram protocol for rendezvous server UDP."""
    def __init__(self):
        self.queue: asyncio.Queue[bytes] = asyncio.Queue()

    def datagram_received(self, data: bytes, addr):
        self.queue.put_nowait(data)

    def error_received(self, exc):
        log.warning(f"Rendezvous UDP error: {exc}")


# ── Main Client ─────────────────────────────────────────────────────

class HeadlessClient:
    def __init__(self, config: Config):
        self.config = config
        self.state = "disconnected"  # disconnected, registering, connecting, connected, authenticated
        self.my_id = ""
        self.target_id = config.target_id

        # NaCl keys
        self.private_key, self.public_key = generate_keypair()
        self.sign_sk, self.sign_pk = generate_sign_keypair()
        self.box: Box | None = None
        self.peer_pk: PublicKey | None = None

        # Server connection
        self._rdv_transport: asyncio.DatagramTransport | None = None
        self._rdv_protocol: _RdvProtocol | None = None
        self._peer_reader: asyncio.StreamReader | None = None
        self._peer_writer: asyncio.StreamWriter | None = None

        # Session nonce counter for NaCl
        self._send_nonce = 0
        self._recv_nonce = 0

        # Video
        self._decoder = VideoDecoder()
        self._latest_frame: bytes | None = None  # PNG bytes
        self._frame_count = 0
        self._display_info = {}

        # Peer info
        self.peer_info: dict = {}

        # Tasks
        self._tasks: list[asyncio.Task] = []
        self._running = False

        # Session ID
        self.session_id = int(time.time() * 1000)

    # ── Rendezvous server connection (UDP) ─────────────────────────

    async def connect_to_server(self):
        """Connect to the RustDesk rendezvous server via UDP."""
        host = self.config.server_host
        port = self.config.server_port
        log.info(f"Connecting to rendezvous server {host}:{port} (UDP)")

        loop = asyncio.get_event_loop()
        self._rdv_protocol = _RdvProtocol()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: self._rdv_protocol,
            remote_addr=(host, port),
        )
        self._rdv_transport = transport
        self.state = "registering"
        log.info("UDP transport to rendezvous server ready")

    async def _rdv_send(self, data: bytes):
        """Send raw protobuf via UDP to rendezvous server."""
        self._rdv_transport.sendto(data)

    async def _rdv_recv(self, timeout: float = 10) -> bytes:
        """Receive one UDP datagram from rendezvous server."""
        return await asyncio.wait_for(self._rdv_protocol.queue.get(), timeout=timeout)

    async def register(self):
        """Register our public key with the server."""
        reg = rdv_pb2.RendezvousMessage()
        reg.register_pk.id = ""
        reg.register_pk.uuid = os.urandom(16)
        reg.register_pk.pk = bytes(self.public_key)

        await self._rdv_send(reg.SerializeToString())
        log.info("Sent RegisterPk (UDP)")

        # Read response with timeout
        try:
            data = await self._rdv_recv(timeout=10)
        except asyncio.TimeoutError:
            log.error("Timeout waiting for RegisterPk response")
            raise ConnectionError("Server did not respond to RegisterPk")
        except Exception as e:
            log.error(f"Error reading RegisterPk response: {e}")
            raise
        log.info(f"RegisterPk response: {len(data)} bytes, hex: {data[:40].hex()}")
        resp = rdv_pb2.RendezvousMessage()
        resp.ParseFromString(data)
        field = resp.WhichOneof('union')
        log.info(f"RegisterPk response field: {field}")

        if field == "register_pk_response":
            rpr = resp.register_pk_response
            if rpr.result == rdv_pb2.RegisterPkResponse.OK:
                log.info("Registered OK")
            elif rpr.result == rdv_pb2.RegisterPkResponse.ID_EXISTS:
                log.info("ID already registered")
            elif rpr.result == rdv_pb2.RegisterPkResponse.UUID_MISMATCH:
                log.warning("UUID mismatch — may need new UUID")
            else:
                log.warning(f"Registration result: {rpr.result}")

            if rpr.keep_alive:
                log.info(f"Keep-alive interval: {rpr.keep_alive}s")
        else:
            log.warning(f"Unexpected rendezvous response: {resp.WhichOneof('union')}")

        # Generate our ID from public key hash
        self.my_id = str(int.from_bytes(bytes(self.public_key)[:4], "big"))
        log.info(f"Our ID: {self.my_id}")

    # ── Punch hole / relay ──────────────────────────────────────────

    async def request_connection(self, target_id: str):
        """Request connection to a target peer."""
        self.target_id = target_id
        self.state = "connecting"
        log.info(f"Requesting connection to {target_id}")

        phr = rdv_pb2.RendezvousMessage()
        phr.punch_hole_request.id = target_id
        phr.punch_hole_request.conn_type = rdv_pb2.DEFAULT_CONN
        phr.punch_hole_request.version = self.config.version

        await self._rdv_send(phr.SerializeToString())

        # Read punch hole response
        data = await self._rdv_recv()
        resp = rdv_pb2.RendezvousMessage()
        resp.ParseFromString(data)

        field = resp.WhichOneof("union")
        log.info(f"Server response: {field}")

        if field == "punch_hole_response":
            ph_resp = resp.punch_hole_response
            if ph_resp.failure != 0:
                failure_names = {0: "NONE", 2: "OFFLINE", 3: "LICENSE_MISMATCH", 4: "LICENSE_OVERUSE"}
                fail = failure_names.get(ph_resp.failure, str(ph_resp.failure))
                other = ph_resp.other_failure
                raise ConnectionError(f"PunchHole failed: {fail} {other}")

            # Get peer's public key
            if ph_resp.pk:
                self.peer_pk = PublicKey(ph_resp.pk)
                log.info(f"Got peer public key ({len(ph_resp.pk)} bytes)")
            else:
                raise ConnectionError("No peer public key in PunchHoleResponse")

            # Determine connection type: direct or relay
            if ph_resp.relay_server:
                log.info(f"Using relay: {ph_resp.relay_server}")
                await self._connect_relay(ph_resp.relay_server)
            elif ph_resp.socket_addr:
                log.info("Attempting direct connection")
                await self._connect_direct(ph_resp.socket_addr)
            elif ph_resp.HasField("is_local") and ph_resp.is_local:
                log.info("Local connection indicated, trying relay fallback")
                # Try relay
                await self._request_relay(target_id)
            else:
                raise ConnectionError("No connection method in PunchHoleResponse")

        elif field == "punch_hole_sent":
            # Server forwarded our request, peer will connect to us
            log.info("PunchHoleSent — waiting for peer to connect...")
            # In practice, we'd need to handle incoming connections
            # For now, try relay as fallback
            await self._request_relay(target_id)
        else:
            raise ConnectionError(f"Unexpected response: {field}")

    async def _request_relay(self, target_id: str):
        """Request a relay connection."""
        rr = rdv_pb2.RendezvousMessage()
        rr.request_relay.id = target_id
        rr.request_relay.uuid = os.urandom(16).hex()
        rr.request_relay.relay_server = ""
        rr.request_relay.conn_type = rdv_pb2.DEFAULT_CONN

        await self._rdv_send(rr.SerializeToString())

        data = await self._rdv_recv()
        resp = rdv_pb2.RendezvousMessage()
        resp.ParseFromString(data)

        if resp.WhichOneof("union") == "relay_response":
            relay_resp = resp.relay_response
            relay_server = relay_resp.relay_server
            if not relay_server:
                raise ConnectionError("Empty relay server in response")
            log.info(f"Relay server: {relay_server}")
            await self._connect_relay(relay_server)
        else:
            raise ConnectionError(f"Expected RelayResponse, got {resp.WhichOneof('union')}")

    async def _connect_relay(self, relay_server: str):
        """Connect to relay server."""
        host = self.config.server_host
        port = self.config.relay_port

        # relay_server might be "host:port" or just a hostname
        if ":" in relay_server:
            parts = relay_server.rsplit(":", 1)
            host = parts[0]
            port = int(parts[1])
        elif relay_server:
            host = relay_server

        log.info(f"Connecting to relay {host}:{port}")
        self._peer_reader, self._peer_writer = await asyncio.open_connection(host, port)

        # Send relay request
        # First message to relay is: 4-byte len + RequestRelay (from rendezvous)
        rr = rdv_pb2.RendezvousMessage()
        rr.request_relay.id = self.target_id
        rr.request_relay.uuid = os.urandom(16).hex()
        rr.request_relay.conn_type = rdv_pb2.DEFAULT_CONN
        await write_message(self._peer_writer, rr.SerializeToString())

        log.info("Connected to relay")

    async def _connect_direct(self, socket_addr: bytes):
        """Connect directly to peer at the given socket address."""
        import socket
        if len(socket_addr) == 16:  # IPv4 sockaddr_in
            # Parse sockaddr: family(2) + port(2) + addr(4) + padding(8)
            port = struct.unpack("!H", socket_addr[2:4])[0]
            ip = socket.inet_ntoa(socket_addr[4:8])
        elif len(socket_addr) == 28:  # IPv6
            port = struct.unpack("!H", socket_addr[2:4])[0]
            import socket as _s
            ip = _s.inet_ntop(_s.AF_INET6, socket_addr[8:24])
        else:
            raise ConnectionError(f"Unknown socket addr format ({len(socket_addr)} bytes)")

        log.info(f"Direct connect to {ip}:{port}")
        self._peer_reader, self._peer_writer = await asyncio.open_connection(ip, port)

    # ── Key exchange & authentication ───────────────────────────────

    async def do_key_exchange(self):
        """Exchange keys and authenticate with the remote peer."""
        if not self._peer_writer:
            raise ConnectionError("No peer connection")

        # 1. Send SignedId
        signed = msg_pb2.Message()
        signed_id_bytes = sign_id(self.my_id, self.sign_sk)
        signed.signed_id.id = signed_id_bytes
        await write_message(self._peer_writer, signed.SerializeToString())
        log.info("Sent SignedId")

        # 2. Receive peer's SignedId
        data = await read_message(self._peer_reader)
        peer_msg = msg_pb2.Message()
        peer_msg.ParseFromString(data)
        log.info(f"Received from peer: {peer_msg.WhichOneof('union')}")

        # 3. Send PublicKey (key exchange)
        # asymmetric_value = our ephemeral public key
        # symmetric_value = encrypted with peer's pk
        pk_msg = msg_pb2.Message()
        pk_msg.public_key.asymmetric_value = bytes(self.public_key)
        # symmetric_value can be empty for basic key exchange
        pk_msg.public_key.symmetric_value = b""
        await write_message(self._peer_writer, pk_msg.SerializeToString())
        log.info("Sent PublicKey")

        # 4. Receive peer's PublicKey
        data = await read_message(self._peer_reader)
        peer_msg = msg_pb2.Message()
        peer_msg.ParseFromString(data)

        if peer_msg.WhichOneof("union") == "public_key":
            peer_asym = peer_msg.public_key.asymmetric_value
            if not self.peer_pk and peer_asym:
                self.peer_pk = PublicKey(peer_asym)
            log.info(f"Received peer PublicKey ({len(peer_asym)} bytes)")
        else:
            log.warning(f"Expected PublicKey, got {peer_msg.WhichOneof('union')}")

        # Create Box for encryption
        if self.peer_pk:
            self.box = Box(self.private_key, self.peer_pk)
            log.info("NaCl Box established")
        else:
            raise ConnectionError("No peer public key for encryption")

        # 5. Receive Hash (challenge)
        data = await self._read_encrypted()
        hash_msg = msg_pb2.Message()
        hash_msg.ParseFromString(data)

        if hash_msg.WhichOneof("union") == "hash":
            salt = hash_msg.hash.salt
            challenge = hash_msg.hash.challenge
            log.info(f"Received Hash challenge (salt={salt[:16]}...)")
        else:
            log.warning(f"Expected Hash, got {hash_msg.WhichOneof('union')}")
            salt = ""
            challenge = ""

        # 6. Send LoginRequest with encrypted password
        login = msg_pb2.Message()
        login.login_request.username = ""
        # Encrypt password: RustDesk encrypts with the shared secret
        if self.config.password and self.box:
            pwd_bytes = self.config.password.encode()
            # Use the box to encrypt the password
            nonce, enc_pwd = encrypt(self.box, pwd_bytes)
            login.login_request.password = nonce + enc_pwd
        else:
            login.login_request.password = b""
        login.login_request.my_id = self.my_id
        login.login_request.my_name = self.config.my_name
        login.login_request.session_id = self.session_id
        login.login_request.version = self.config.version
        login.login_request.my_platform = "Linux"

        # Set video codec preference
        codec_map = {
            "VP9": msg_pb2.SupportedDecoding.VP9,
            "H264": msg_pb2.SupportedDecoding.H264,
            "H265": msg_pb2.SupportedDecoding.H265,
            "VP8": msg_pb2.SupportedDecoding.VP8,
            "AV1": msg_pb2.SupportedDecoding.AV1,
            "Auto": msg_pb2.SupportedDecoding.Auto,
        }
        prefer = codec_map.get(self.config.preferred_codec, msg_pb2.SupportedDecoding.VP9)
        login.login_request.option.supported_decoding.prefer = prefer
        login.login_request.option.supported_decoding.ability_vp9 = 1
        login.login_request.option.supported_decoding.ability_h264 = 1
        login.login_request.option.supported_decoding.ability_h265 = 1
        login.login_request.option.image_quality = msg_pb2.Balanced
        login.login_request.option.show_remote_cursor = msg_pb2.OptionMessage.Yes
        login.login_request.video_ack_required = False

        await self._write_encrypted(login.SerializeToString())
        log.info("Sent LoginRequest")

        # 7. Receive LoginResponse
        data = await self._read_encrypted()
        resp_msg = msg_pb2.Message()
        resp_msg.ParseFromString(data)

        field = resp_msg.WhichOneof("union")
        if field == "login_response":
            lr = resp_msg.login_response
            if lr.HasField("error") and lr.error:
                raise ConnectionError(f"Login failed: {lr.error}")
            if lr.HasField("peer_info"):
                pi = lr.peer_info
                self.peer_info = {
                    "username": pi.username,
                    "hostname": pi.hostname,
                    "platform": pi.platform,
                    "current_display": pi.current_display,
                    "version": pi.version,
                    "displays": [],
                }
                for d in pi.displays:
                    disp = {
                        "x": d.x, "y": d.y,
                        "width": d.width, "height": d.height,
                        "name": d.name,
                        "online": d.online,
                    }
                    self.peer_info["displays"].append(disp)
                    self._display_info[d.width] = disp
                log.info(f"Authenticated! Peer: {pi.username}@{pi.hostname} ({pi.platform})")
                log.info(f"Displays: {self.peer_info['displays']}")
                self.state = "authenticated"
            elif field == "peer_info":
                # Sometimes peer_info comes directly
                pi = resp_msg.peer_info
                self.peer_info = {
                    "username": pi.username,
                    "hostname": pi.hostname,
                    "platform": pi.platform,
                    "displays": [{"width": d.width, "height": d.height, "name": d.name} for d in pi.displays],
                }
                log.info(f"Authenticated! Peer: {pi.username}@{pi.hostname}")
                self.state = "authenticated"
            else:
                log.warning(f"LoginResponse field: {field}")
        elif field == "peer_info":
            pi = resp_msg.peer_info
            self.peer_info = {
                "username": pi.username,
                "hostname": pi.hostname,
                "platform": pi.platform,
                "displays": [{"width": d.width, "height": d.height, "name": d.name} for d in pi.displays],
            }
            self.state = "authenticated"
            log.info(f"Authenticated via PeerInfo!")
        else:
            log.warning(f"Expected LoginResponse, got {field}")

        if self.state != "authenticated":
            raise ConnectionError(f"Authentication did not complete (state={self.state}, field={field})")

    # ── Encrypted message I/O ───────────────────────────────────────

    async def _write_encrypted(self, plaintext: bytes):
        """Encrypt and send a message to the peer."""
        if not self.box:
            raise ConnectionError("No encryption box")
        nonce = self._send_nonce.to_bytes(24, "little").ljust(24, b"\0")[:24]
        self._send_nonce += 1
        ciphertext = self.box.encrypt(plaintext, nonce)
        # NaCl Box.encrypt prepends nonce (24 bytes) to ciphertext
        await write_message(self._peer_writer, ciphertext)

    async def _read_encrypted(self) -> bytes:
        """Read and decrypt a message from the peer."""
        if not self.box:
            raise ConnectionError("No encryption box")
        data = await read_message(self._peer_reader)
        # First 24 bytes are the nonce
        nonce = data[:24]
        ciphertext = data[24:]
        return self.box.decrypt(ciphertext, nonce)

    # ── Message sending helpers ─────────────────────────────────────

    async def send_mouse(self, x: int, y: int, mask: int = 0, modifiers: list = None):
        """Send a mouse event."""
        msg = msg_pb2.Message()
        msg.mouse_event.x = x
        msg.mouse_event.y = y
        msg.mouse_event.mask = mask
        if modifiers:
            for m in modifiers:
                msg.mouse_event.modifiers.append(m)
        await self._write_encrypted(msg.SerializeToString())

    async def send_key(self, down: bool, press: bool = False,
                       control_key=None, chr_val: int = 0,
                       unicode_val: int = 0, modifiers: list = None,
                       mode=None):
        """Send a key event."""
        msg = msg_pb2.Message()
        msg.key_event.down = down
        msg.key_event.press = press
        if control_key is not None:
            msg.key_event.control_key = control_key
        elif chr_val:
            msg.key_event.chr = chr_val
        elif unicode_val:
            msg.key_event.unicode = unicode_val
        if modifiers:
            for m in modifiers:
                msg.key_event.modifiers.append(m)
        if mode is not None:
            msg.key_event.mode = mode
        await self._write_encrypted(msg.SerializeToString())

    # ── Main message loop ───────────────────────────────────────────

    async def _message_loop(self):
        """Main loop receiving messages from peer."""
        while self._running:
            try:
                data = await self._read_encrypted()
                msg = msg_pb2.Message()
                msg.ParseFromString(data)

                field = msg.WhichOneof("union")
                if field == "video_frame":
                    await self._handle_video_frame(msg.video_frame)
                elif field == "cursor_position":
                    pass  # cursor position, ignore
                elif field == "cursor_data":
                    pass  # cursor image, ignore
                elif field == "misc":
                    await self._handle_misc(msg.misc)
                elif field == "test_delay":
                    pass  # latency test
                elif field == "login_response":
                    pass  # already handled
                elif field == "message_box":
                    log.info(f"MessageBox: {msg.message_box.title} - {msg.message_box.text}")
                else:
                    log.debug(f"Received: {field}")

            except ConnectionError:
                log.error("Peer connection lost")
                self.state = "disconnected"
                break
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"Message loop error: {e}")
                import traceback
                traceback.print_exc()

    async def _handle_video_frame(self, vf):
        """Decode and store a video frame."""
        codec = None
        frames_data = []

        if vf.HasField("vp9s"):
            codec = "vp9"
            for f in vf.vp9s.frames:
                frames_data.append((f.data, f.key))
        elif vf.HasField("h264s"):
            codec = "h264"
            for f in vf.h264s.frames:
                frames_data.append((f.data, f.key))
        elif vf.HasField("h265s"):
            codec = "h265"
            for f in vf.h265s.frames:
                frames_data.append((f.data, f.key))
        elif vf.HasField("vp8s"):
            codec = "vp8"
            for f in vf.vp8s.frames:
                frames_data.append((f.data, f.key))
        elif vf.HasField("av1s"):
            codec = "av1"
            for f in vf.av1s.frames:
                frames_data.append((f.data, f.key))

        for data, is_key in frames_data:
            self._frame_count += 1
            if is_key:
                png = self._decoder.decode_frame(data, codec)
                if png:
                    self._latest_frame = png
            else:
                # Delta frames — still try to decode
                self._decoder.decode_frame(data, codec)

    async def _handle_misc(self, misc):
        field = misc.WhichOneof("union")
        if field == "switch_display":
            sd = misc.switch_display
            log.info(f"SwitchDisplay: {sd.width}x{sd.height}")
        elif field == "close_reason":
            log.info(f"Close reason: {misc.close_reason}")
            self.state = "disconnected"
            self._running = False
        elif field == "audio_format":
            pass  # ignore audio

    # ── Keep-alive ──────────────────────────────────────────────────

    async def _keep_alive(self):
        """Send periodic keep-alive to rendezvous server (UDP)."""
        while self._running:
            await asyncio.sleep(15)
            if self._rdv_transport and not self._rdv_transport.is_closing():
                try:
                    ka = rdv_pb2.RendezvousMessage()
                    ka.register_peer.id = self.my_id
                    await self._rdv_send(ka.SerializeToString())
                except Exception:
                    pass

    # ── Lifecycle ───────────────────────────────────────────────────

    async def connect(self, target_id: str = None, password: str = None):
        """Full connection sequence."""
        if target_id:
            self.target_id = target_id
        if password:
            self.config.password = password

        if not self.target_id:
            raise ValueError("No target ID specified")

        self._running = True

        await self.connect_to_server()
        await self.register()
        await self.request_connection(self.target_id)
        await self.do_key_exchange()

        # Start message loop
        self._tasks.append(asyncio.create_task(self._message_loop()))
        self._tasks.append(asyncio.create_task(self._keep_alive()))

        self.state = "connected"
        log.info("Connected! Starting message loop...")

    async def disconnect(self):
        """Disconnect from peer and server."""
        self._running = False
        for t in self._tasks:
            t.cancel()
        self._tasks.clear()
        self._decoder.close()

        if self._peer_writer and not self._peer_writer.is_closing():
            try:
                self._peer_writer.close()
                await self._peer_writer.wait_closed()
            except Exception:
                pass
        if self._rdv_transport and not self._rdv_transport.is_closing():
            self._rdv_transport.close()

        self._peer_reader = self._peer_writer = None
        self._rdv_transport = None
        self._rdv_protocol = None
        self.state = "disconnected"
        log.info("Disconnected")

    def get_frame(self) -> bytes | None:
        """Get latest decoded frame as PNG bytes."""
        return self._latest_frame

    def get_status(self) -> dict:
        """Get current connection status."""
        return {
            "state": self.state,
            "my_id": self.my_id,
            "target_id": self.target_id,
            "peer_info": self.peer_info,
            "frame_count": self._frame_count,
            "has_frame": self._latest_frame is not None,
        }


# ── HTTP API ────────────────────────────────────────────────────────

from aiohttp import web


async def handle_status(req: web.Request) -> web.Response:
    client: HeadlessClient = req.app["client"]
    return web.json_response(client.get_status())


async def handle_frame(req: web.Request) -> web.Response:
    client: HeadlessClient = req.app["client"]
    frame = client.get_frame()
    if frame:
        return web.Response(body=frame, content_type="image/png")
    return web.Response(status=404, text="No frame available")


async def handle_connect(req: web.Request) -> web.Response:
    client: HeadlessClient = req.app["client"]
    body = await req.json()
    target_id = body.get("target_id", "")
    password = body.get("password", "")

    if not target_id:
        return web.json_response({"error": "target_id required"}, status=400)

    if client.state != "disconnected":
        await client.disconnect()
        await asyncio.sleep(0.5)

    try:
        await client.connect(target_id, password)
        return web.json_response({"status": "connected", "peer_info": client.peer_info})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_disconnect(req: web.Request) -> web.Response:
    client: HeadlessClient = req.app["client"]
    await client.disconnect()
    return web.json_response({"status": "disconnected"})


async def handle_mouse(req: web.Request) -> web.Response:
    client: HeadlessClient = req.app["client"]
    if client.state not in ("connected", "authenticated"):
        return web.json_response({"error": "Not connected"}, status=400)

    body = await req.json()
    x = body.get("x", 0)
    y = body.get("y", 0)
    mask = body.get("mask", 0)
    modifiers = body.get("modifiers", [])

    try:
        await client.send_mouse(x, y, mask, modifiers)
        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_key(req: web.Request) -> web.Response:
    client: HeadlessClient = req.app["client"]
    if client.state not in ("connected", "authenticated"):
        return web.json_response({"error": "Not connected"}, status=400)

    body = await req.json()
    down = body.get("down", True)
    press = body.get("press", False)
    control_key = body.get("control_key", None)
    chr_val = body.get("chr", 0)
    unicode_val = body.get("unicode", 0)
    modifiers = body.get("modifiers", [])
    mode = body.get("mode", None)

    try:
        await client.send_key(
            down=down, press=press,
            control_key=control_key,
            chr_val=chr_val,
            unicode_val=unicode_val,
            modifiers=modifiers,
            mode=mode,
        )
        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_click(req: web.Request) -> web.Response:
    """Convenience: click at (x, y). Sends down + up mouse events."""
    client: HeadlessClient = req.app["client"]
    if client.state not in ("connected", "authenticated"):
        return web.json_response({"error": "Not connected"}, status=400)

    body = await req.json()
    x = body.get("x", 0)
    y = body.get("y", 0)
    button = body.get("button", "left")  # left, right, middle
    double = body.get("double", False)
    modifiers = body.get("modifiers", [])

    mask_map = {"left": 1, "right": 2, "middle": 4}
    mask = mask_map.get(button, 1)

    try:
        count = 2 if double else 1
        for _ in range(count):
            await client.send_mouse(x, y, mask, modifiers)
            await asyncio.sleep(0.02)
            await client.send_mouse(x, y, 0, modifiers)
            await asyncio.sleep(0.05)
        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_type_text(req: web.Request) -> web.Response:
    """Convenience: type a string by sending unicode key events."""
    client: HeadlessClient = req.app["client"]
    if client.state not in ("connected", "authenticated"):
        return web.json_response({"error": "Not connected"}, status=400)

    body = await req.json()
    text = body.get("text", "")
    modifiers = body.get("modifiers", [])

    try:
        for ch in text:
            code = ord(ch)
            await client.send_key(down=True, unicode_val=code, modifiers=modifiers)
            await asyncio.sleep(0.01)
            await client.send_key(down=False, unicode_val=code, modifiers=modifiers)
            await asyncio.sleep(0.01)
        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_key_combo(req: web.Request) -> web.Response:
    """Convenience: press a key combo like Ctrl+C."""
    client: HeadlessClient = req.app["client"]
    if client.state not in ("connected", "authenticated"):
        return web.json_response({"error": "Not connected"}, status=400)

    body = await req.json()
    keys = body.get("keys", [])  # e.g. ["ctrl", "c"]
    modifier_map = {
        "ctrl": msg_pb2.Control, "alt": msg_pb2.Alt,
        "shift": msg_pb2.Shift, "meta": msg_pb2.Meta,
        "win": msg_pb2.Meta, "cmd": msg_pb2.Meta,
    }
    named_keys = {
        "enter": msg_pb2.Return, "return": msg_pb2.Return,
        "escape": msg_pb2.Escape, "esc": msg_pb2.Escape,
        "tab": msg_pb2.Tab, "space": msg_pb2.Space,
        "backspace": msg_pb2.Backspace, "delete": msg_pb2.Delete,
        "up": msg_pb2.UpArrow, "down": msg_pb2.DownArrow,
        "left": msg_pb2.LeftArrow, "right": msg_pb2.RightArrow,
        "home": msg_pb2.Home, "end": msg_pb2.End,
        "pageup": msg_pb2.PageUp, "pagedown": msg_pb2.PageDown,
        "f1": msg_pb2.F1, "f2": msg_pb2.F2, "f3": msg_pb2.F3,
        "f4": msg_pb2.F4, "f5": msg_pb2.F5, "f6": msg_pb2.F6,
        "f7": msg_pb2.F7, "f8": msg_pb2.F8, "f9": msg_pb2.F9,
        "f10": msg_pb2.F10, "f11": msg_pb2.F11, "f12": msg_pb2.F12,
        "insert": msg_pb2.Insert, "printscreen": msg_pb2.Snapshot,
    }

    try:
        mods = []
        main_key = None
        main_chr = 0

        for k in keys:
            kl = k.lower()
            if kl in modifier_map:
                mods.append(modifier_map[kl])
            elif kl in named_keys:
                main_key = named_keys[kl]
            elif len(k) == 1:
                main_chr = ord(k.upper())
            else:
                # Try ControlKey enum by name
                try:
                    main_key = msg_pb2.ControlKey.Value(kl.upper())
                except ValueError:
                    main_chr = ord(k[0])

        # Press modifiers
        # Send key down for main key
        if main_key:
            await client.send_key(down=True, control_key=main_key, modifiers=mods)
            await asyncio.sleep(0.02)
            await client.send_key(down=False, control_key=main_key, modifiers=mods)
        elif main_chr:
            await client.send_key(down=True, chr_val=main_chr, modifiers=mods)
            await asyncio.sleep(0.02)
            await client.send_key(down=False, chr_val=main_chr, modifiers=mods)

        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_scroll(req: web.Request) -> web.Response:
    """Convenience: scroll at position."""
    client: HeadlessClient = req.app["client"]
    if client.state not in ("connected", "authenticated"):
        return web.json_response({"error": "Not connected"}, status=400)

    body = await req.json()
    x = body.get("x", 0)
    y = body.get("y", 0)
    delta = body.get("delta", -3)  # negative = scroll down

    # RustDesk scroll: mouse events with mask bit 6 (up) or 7 (down)
    try:
        for _ in range(abs(delta)):
            mask = 0x80 if delta < 0 else 0x40  # 0x80=scroll down, 0x40=scroll up
            await client.send_mouse(x, y, mask)
            await asyncio.sleep(0.02)
        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


def create_app(client: HeadlessClient) -> web.Application:
    app = web.Application()
    app["client"] = client

    app.router.add_get("/status", handle_status)
    app.router.add_get("/frame", handle_frame)
    app.router.add_post("/connect", handle_connect)
    app.router.add_post("/disconnect", handle_disconnect)
    app.router.add_post("/mouse", handle_mouse)
    app.router.add_post("/key", handle_key)
    app.router.add_post("/click", handle_click)
    app.router.add_post("/type", handle_type_text)
    app.router.add_post("/key_combo", handle_key_combo)
    app.router.add_post("/scroll", handle_scroll)

    return app


# ── Main ────────────────────────────────────────────────────────────

async def main_async():
    parser = argparse.ArgumentParser(description="Headless RustDesk Client")
    parser.add_argument("--server", default="", help="RustDesk server host[:port]")
    parser.add_argument("--target", default="", help="Target RustDesk ID")
    parser.add_argument("--password", default="", help="Remote password")
    parser.add_argument("--codec", default="VP9", help="Preferred codec (VP9, H264, etc.)")
    parser.add_argument("--api-port", type=int, default=8080, help="Local API port")
    parser.add_argument("--api-host", default="0.0.0.0", help="Local API bind host")
    parser.add_argument("--config", default="", help="Config JSON file path")
    parser.add_argument("--auto-connect", action="store_true", help="Auto-connect on startup")
    args = parser.parse_args()

    if args.config:
        config = Config.from_file(args.config)
    else:
        kw = {}
        if args.server:
            if ":" in args.server:
                h, p = args.server.rsplit(":", 1)
                kw["server_host"] = h
                kw["server_port"] = int(p)
            else:
                kw["server_host"] = args.server
        if args.target:
            kw["target_id"] = args.target
        if args.password:
            kw["password"] = args.password
        if args.codec:
            kw["preferred_codec"] = args.codec
        if args.api_port:
            kw["api_port"] = args.api_port
        if args.api_host:
            kw["api_host"] = args.api_host
        config = Config(**kw)

    client = HeadlessClient(config)

    # Auto-connect if target specified
    if args.auto_connect and config.target_id:
        try:
            await client.connect()
        except Exception as e:
            log.error(f"Auto-connect failed: {e}")

    app = create_app(client)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, config.api_host, config.api_port)
    await site.start()
    log.info(f"HTTP API listening on {config.api_host}:{config.api_port}")

    # Keep running
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        await client.disconnect()
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main_async())
