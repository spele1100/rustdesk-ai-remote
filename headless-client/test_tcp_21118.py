import os, socket, time, struct, select
import rendezvous_pb2 as rdv
import message_pb2 as msg
from nacl.public import PrivateKey
from nacl.signing import SigningKey

sk = PrivateKey.generate()
pk = sk.public_key
sign_key = SigningKey.generate()
my_id = str(int.from_bytes(bytes(pk)[:4], "big"))
target_id = "283 760 096"
server = "aws.logany.info"

print("My ID: " + my_id)

# UDP Register
udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
udp.settimeout(5)
m = rdv.RendezvousMessage()
m.register_pk.id = my_id
m.register_pk.uuid = os.urandom(16)
m.register_pk.pk = bytes(pk)
udp.sendto(m.SerializeToString(), (server, 21116))
udp.recvfrom(4096)
print("Registered")

# RegisterPeer
m2 = rdv.RendezvousMessage()
m2.register_peer.id = my_id
m2.register_peer.serial = 0
udp.sendto(m2.SerializeToString(), (server, 21116))
udp.recvfrom(4096)
time.sleep(0.3)

# PunchHole
m3 = rdv.RendezvousMessage()
m3.punch_hole_request.id = target_id
m3.punch_hole_request.conn_type = 0
udp.sendto(m3.SerializeToString(), (server, 21116))
r3, _ = udp.recvfrom(4096)
rm3 = rdv.RendezvousMessage()
rm3.ParseFromString(r3)
print("PunchHole: failure=" + str(rm3.punch_hole_response.failure))
udp.close()

# Now try TCP 21118 (hole punch helper)
print("\nTrying TCP 21118 (hole punch)...")
try:
    tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp.settimeout(10)
    tcp.connect((server, 21118))
    print("Connected!")
    
    # Send SignedId
    signed = sign_key.sign(my_id.encode())
    sid = msg.SignedId()
    sid.id = signed
    data = sid.SerializeToString()
    tcp.sendall(struct.pack("!I", len(data)) + data)
    print("Sent SignedId (" + str(len(data)) + "B)")
    
    # Wait for response
    tcp.settimeout(5)
    try:
        raw_len = tcp.recv(4)
        if len(raw_len) >= 4:
            length = struct.unpack("!I", raw_len)[0]
            resp = b""
            while len(resp) < min(length, 8192):
                chunk = tcp.recv(min(length - len(resp), 8192))
                if not chunk:
                    break
                resp += chunk
            print("Response (" + str(length) + "B): " + resp.hex()[:200])
            
            # Try parse as different message types
            for name, cls in [("SignedId", msg.SignedId), ("PublicKey", msg.PublicKey), 
                              ("Hash", msg.Hash), ("LoginResponse", msg.LoginResponse)]:
                try:
                    parsed = cls()
                    parsed.ParseFromString(resp)
                    fields = [f.name for f in parsed.DESCRIPTOR.fields if parsed.HasField(f.name)]
                    if fields or len(resp) > 0:
                        print("  Parsed as " + name + " fields=" + str(fields))
                        if name == "PublicKey":
                            print("    asymmetric=" + str(len(parsed.asymmetric_value)) + "B")
                            print("    symmetric=" + str(len(parsed.symmetric_value)) + "B")
                        elif name == "Hash":
                            print("    salt=" + parsed.salt)
                            print("    challenge=" + parsed.challenge)
                        elif name == "SignedId":
                            print("    id len=" + str(len(parsed.id)))
                        elif name == "LoginResponse":
                            print("    error=" + parsed.error if parsed.error else "    peer_info present")
                except:
                    pass
        else:
            print("Short: " + raw_len.hex())
    except socket.timeout:
        print("Timeout reading response")
    
    tcp.close()
except Exception as e:
    print("Error: " + repr(e))

# Also try TCP 21116 (rendezvous TCP)
print("\nTrying TCP 21116...")
try:
    tcp2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp2.settimeout(10)
    tcp2.connect((server, 21116))
    print("Connected!")
    
    # Send RegisterPk via TCP
    req = rdv.RendezvousMessage()
    req.register_pk.id = my_id
    req.register_pk.uuid = os.urandom(16)
    req.register_pk.pk = bytes(pk)
    data = req.SerializeToString()
    tcp2.sendall(struct.pack("!I", len(data)) + data)
    print("Sent RegisterPk via TCP (" + str(len(data)) + "B)")
    
    tcp2.settimeout(5)
    try:
        raw_len = tcp2.recv(4)
        if len(raw_len) >= 4:
            length = struct.unpack("!I", raw_len)[0]
            resp = b""
            while len(resp) < min(length, 8192):
                chunk = tcp2.recv(min(length - len(resp), 8192))
                if not chunk:
                    break
                resp += chunk
            print("Response (" + str(length) + "B): " + resp.hex()[:200])
            rm = rdv.RendezvousMessage()
            rm.ParseFromString(resp)
            print("  Field: " + str(rm.WhichOneof("union")))
        else:
            print("Short: " + (raw_len.hex() if raw_len else "empty"))
    except socket.timeout:
        print("Timeout")
    
    tcp2.close()
except Exception as e:
    print("Error: " + repr(e))

print("\nDone.")
