import os, socket, time, struct, select
import rendezvous_pb2 as rdv
import message_pb2 as msg
from nacl.public import PrivateKey, Box, PublicKey
from nacl.signing import SigningKey
import hashlib

sk = PrivateKey.generate()
pk = sk.public_key
sign_key = SigningKey.generate()

# Use a stable-looking ID
my_id = str(int.from_bytes(bytes(pk)[:4], "big"))
target_id = "283 760 096"
server = "aws.logany.info"
rdv_port = 21116
relay_port = 21117

print("My ID: " + my_id)

# Step 1: UDP Register
print("\n=== Step 1: UDP Register ===")
udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
udp.settimeout(5)

m = rdv.RendezvousMessage()
m.register_pk.id = my_id
m.register_pk.uuid = os.urandom(16)
m.register_pk.pk = bytes(pk)
udp.sendto(m.SerializeToString(), (server, rdv_port))
r, _ = udp.recvfrom(4096)
rm = rdv.RendezvousMessage()
rm.ParseFromString(r)
print("RegisterPk: result=" + str(rm.register_pk_response.result))

time.sleep(0.3)

# RegisterPeer too
m2 = rdv.RendezvousMessage()
m2.register_peer.id = my_id
m2.register_peer.serial = 0
udp.sendto(m2.SerializeToString(), (server, rdv_port))
r2, _ = udp.recvfrom(4096)
rm2 = rdv.RendezvousMessage()
rm2.ParseFromString(r2)
print("RegisterPeer: " + str(rm2.WhichOneof("union")))

time.sleep(0.3)

# Step 2: PunchHoleRequest via UDP
print("\n=== Step 2: PunchHoleRequest ===")
m3 = rdv.RendezvousMessage()
m3.punch_hole_request.id = target_id
m3.punch_hole_request.conn_type = 0
udp.sendto(m3.SerializeToString(), (server, rdv_port))

# Wait for responses
print("Waiting for UDP responses (10s)...")
end_time = time.time() + 10
relay_server = None
peer_pk_bytes = None

while time.time() < end_time:
    ready = select.select([udp], [], [], 1)
    if ready[0]:
        data, addr = udp.recvfrom(4096)
        rmsg = rdv.RendezvousMessage()
        rmsg.ParseFromString(data)
        f = rmsg.WhichOneof("union")
        print("  UDP got: " + f + " (" + str(len(data)) + "B)")
        
        if f == "punch_hole_response":
            phr = rmsg.punch_hole_response
            print("    failure=" + str(phr.failure))
            if phr.relay_server:
                relay_server = phr.relay_server
                print("    RELAY: " + relay_server)
            if phr.pk:
                peer_pk_bytes = phr.pk
                print("    PK: " + str(len(phr.pk)) + "B")
            if phr.socket_addr:
                print("    Socket: " + phr.socket_addr.hex())
        
        elif f == "punch_hole_sent":
            phs = rmsg.punch_hole_sent
            print("    socket=" + phs.socket_addr.hex())
            print("    id=" + phs.id)
            if phs.relay_server:
                relay_server = phs.relay_server
                print("    relay=" + relay_server)
        
        elif f == "relay_response":
            rr = rmsg.relay_response
            print("    server=" + rr.relay_server)
            print("    uuid=" + (rr.uuid.hex() if rr.uuid else "none"))
            relay_server = rr.relay_server
            if rr.pk:
                peer_pk_bytes = rr.pk

# Step 3: Try RequestRelay via UDP
if not relay_server:
    print("\n=== Step 3: RequestRelay via UDP ===")
    m4 = rdv.RendezvousMessage()
    m4.request_relay.id = target_id
    m4.request_relay.uuid = os.urandom(16).hex()[:32]
    m4.request_relay.relay_server = server
    m4.request_relay.secure = True
    m4.request_relay.conn_type = 0
    udp.sendto(m4.SerializeToString(), (server, rdv_port))
    
    try:
        data, addr = udp.recvfrom(4096)
        rm4 = rdv.RendezvousMessage()
        rm4.ParseFromString(data)
        f4 = rm4.WhichOneof("union")
        print("  Response: " + f4)
        if f4 == "relay_response":
            rr = rm4.relay_response
            print("    server=" + rr.relay_server)
            print("    uuid=" + (rr.uuid.hex() if rr.uuid else "none"))
            print("    socket=" + (rr.socket_addr.hex() if rr.socket_addr else "none"))
            print("    refuse=" + rr.refuse_reason)
            relay_server = rr.relay_server if rr.relay_server else server
            if rr.pk:
                peer_pk_bytes = rr.pk
    except socket.timeout:
        print("  TIMEOUT")

# Step 4: Connect to relay TCP
if relay_server or True:
    print("\n=== Step 4: TCP to relay ===")
    try:
        tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp.settimeout(10)
        tcp.connect((server, relay_port))
        print("Connected to relay TCP!")
        
        # Send SignedId message (message.proto format)
        # First sign our ID
        signed = sign_key.sign(my_id.encode())
        
        sid = msg.SignedId()
        sid.id = signed
        
        data = sid.SerializeToString()
        tcp.sendall(struct.pack("!I", len(data)) + data)
        print("Sent SignedId (" + str(len(data)) + "B)")
        
        # Read response
        raw_len = tcp.recv(4)
        if len(raw_len) >= 4:
            length = struct.unpack("!I", raw_len)[0]
            print("Response length: " + str(length))
            resp = b""
            while len(resp) < min(length, 8192):
                chunk = tcp.recv(min(length - len(resp), 8192))
                if not chunk:
                    break
                resp += chunk
            
            print("Response hex: " + resp.hex()[:200])
            
            # Try parsing as SignedId
            try:
                sid_resp = msg.SignedId()
                sid_resp.ParseFromString(resp)
                print("Parsed as SignedId, id len=" + str(len(sid_resp.id)))
            except:
                pass
            
            # Try as PublicKey
            try:
                pk_resp = msg.PublicKey()
                pk_resp.ParseFromString(resp)
                print("Parsed as PublicKey")
                print("  asymmetric=" + str(len(pk_resp.asymmetric_value)) + "B")
                print("  symmetric=" + str(len(pk_resp.symmetric_value)) + "B")
            except:
                pass
                
        else:
            print("Short response: " + raw_len.hex())
        
        tcp.close()
    except Exception as e:
        print("TCP error: " + repr(e))

udp.close()
print("\nDone.")
