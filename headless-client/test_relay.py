import os, socket, time, struct
import rendezvous_pb2 as rdv
from nacl.public import PrivateKey

sk = PrivateKey.generate()
pk = sk.public_key
my_id = str(int.from_bytes(bytes(pk)[:4], "big"))

# UDP Register
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.settimeout(5)
m1 = rdv.RendezvousMessage()
m1.register_pk.id = my_id
m1.register_pk.uuid = os.urandom(16)
m1.register_pk.pk = bytes(pk)
sock.sendto(m1.SerializeToString(), ("aws.logany.info", 21116))
sock.recvfrom(4096)
print("Registered OK")
sock.close()
time.sleep(0.3)

# TCP to relay
print("Connecting to relay TCP 21117...")
peer = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
peer.settimeout(10)
peer.connect(("aws.logany.info", 21117))
print("TCP connected!")

# Send RequestRelay
req = rdv.RendezvousMessage()
req.request_relay.id = "283 760 096"
req.request_relay.uuid = os.urandom(16).hex()[:32]
req.request_relay.relay_server = "aws.logany.info"
req.request_relay.secure = True
req.request_relay.conn_type = 0
data = req.SerializeToString()
peer.sendall(struct.pack("!I", len(data)) + data)
print("Sent RequestRelay (%dB)" % len(data))

# Read response
try:
    raw_len = peer.recv(4)
    if len(raw_len) < 4:
        print("Short read: " + raw_len.hex())
    else:
        length = struct.unpack("!I", raw_len)[0]
        print("Response length: %d" % length)
        resp = b""
        while len(resp) < min(length, 4096):
            chunk = peer.recv(min(length - len(resp), 4096))
            if not chunk:
                break
            resp += chunk
        rm = rdv.RendezvousMessage()
        rm.ParseFromString(resp)
        f = rm.WhichOneof("union")
        print("Response field: " + str(f))
        print("Hex: " + resp.hex()[:200])
        if f == "relay_response":
            rr = rm.relay_response
            print("  server=" + rr.relay_server)
            print("  uuid=" + (rr.uuid.hex() if rr.uuid else "none"))
            print("  refuse=" + rr.refuse_reason)
            print("  socket=" + (rr.socket_addr.hex() if rr.socket_addr else "none"))
            print("  pk=%dB" % len(rr.pk))
        elif f:
            print("  Full hex: " + resp.hex()[:300])
except Exception as e:
    print("Error: " + repr(e))
    peer.settimeout(2)
    try:
        raw = peer.recv(4096)
        print("Raw: " + raw.hex()[:200])
    except:
        pass

peer.close()
