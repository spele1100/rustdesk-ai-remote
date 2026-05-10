import os, socket, time, struct, select
import message_pb2 as msg
from nacl.public import PrivateKey, Box, PublicKey
from nacl.signing import SigningKey

sk = PrivateKey.generate()
pk = sk.public_key
sign_key = SigningKey.generate()
my_id = str(int.from_bytes(bytes(pk)[:4], "big"))

target_ip = "100.76.224.70"
password = "d88ax6"

# Try common RustDesk peer ports
ports = [21118, 21116, 2118, 21119, 0]

for port in ports:
    print("\n=== Trying %s:%s ===" % (target_ip, port if port else "scan"))
    
    if port == 0:
        # Port scan
        print("Scanning common ports...")
        for p in [21118, 21116, 2118, 21119, 5800, 5900, 3389]:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2)
            result = s.connect_ex((target_ip, p))
            if result == 0:
                print("  Port %d OPEN" % p)
            s.close()
        continue
    
    try:
        tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp.settimeout(5)
        tcp.connect((target_ip, port))
        print("Connected!")
        
        # Send SignedId
        signed = sign_key.sign(my_id.encode())
        sid = msg.SignedId()
        sid.id = signed
        data = sid.SerializeToString()
        tcp.sendall(struct.pack("!I", len(data)) + data)
        print("Sent SignedId (" + str(len(data)) + "B)")
        
        # Read response
        tcp.settimeout(5)
        try:
            raw_len = tcp.recv(4)
            if len(raw_len) >= 4:
                length = struct.unpack("!I", raw_len)[0]
                print("Response length: %d" % length)
                resp = b""
                while len(resp) < min(length, 16384):
                    chunk = tcp.recv(min(length - len(resp), 16384))
                    if not chunk:
                        break
                    resp += chunk
                
                print("Hex: " + resp.hex()[:300])
                
                # Try parse as various types
                for name, cls in [("SignedId", msg.SignedId), ("PublicKey", msg.PublicKey), 
                                  ("Hash", msg.Hash), ("LoginResponse", msg.LoginResponse),
                                  ("TestDelay", msg.TestDelay)]:
                    try:
                        parsed = cls()
                        parsed.ParseFromString(resp)
                        fields = [f.name for f in parsed.DESCRIPTOR.fields if parsed.HasField(f.name)]
                        if fields:
                            print("  Parsed as " + name + " fields=" + str(fields))
                            if name == "PublicKey":
                                print("    asymmetric=%dB" % len(parsed.asymmetric_value))
                                print("    symmetric=%dB" % len(parsed.symmetric_value))
                            elif name == "Hash":
                                print("    salt=" + parsed.salt)
                                print("    challenge=" + parsed.challenge)
                            elif name == "SignedId":
                                print("    id len=%d" % len(parsed.id))
                            elif name == "TestDelay":
                                print("    time=%d from_client=%s" % (parsed.time, parsed.from_client))
                            break
                    except:
                        pass
            else:
                print("Short response: " + (raw_len.hex() if raw_len else "empty"))
        except socket.timeout:
            print("Timeout reading response")
        
        tcp.close()
    except Exception as e:
        print("Error: " + repr(e))

print("\nDone.")
