import socket, struct, time
import message_pb2 as msg
from nacl.public import PrivateKey
from nacl.signing import SigningKey

sk = PrivateKey.generate()
pk = sk.public_key
sign_key = SigningKey.generate()
my_id = str(int.from_bytes(bytes(pk)[:4], "big"))

target = ("100.76.224.70", 21118)

# Try different approaches
approaches = [
    ("raw protobuf SignedId (no length prefix)", False),
    ("4-byte LE length + protobuf", False, "<"),
    ("4-byte BE length + protobuf", True),
]

for desc, use_prefix, fmt in [("4-byte BE length + SignedId", True, "!"), 
                               ("raw protobuf no prefix", False, None),
                               ("4-byte LE length + SignedId", True, "<")]:
    print("\n=== " + desc + " ===")
    try:
        tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp.settimeout(5)
        tcp.connect(target)
        print("Connected!")
        
        signed = sign_key.sign(my_id.encode())
        sid = msg.SignedId()
        sid.id = signed
        data = sid.SerializeToString()
        
        if use_prefix:
            tcp.sendall(struct.pack(fmt + "I", len(data)) + data)
        else:
            tcp.sendall(data)
        print("Sent %dB" % len(data))
        
        # Read raw bytes
        tcp.settimeout(3)
        try:
            raw = tcp.recv(4096)
            print("Raw response (%dB): %s" % (len(raw), raw.hex()[:200]))
            
            # If it looks like length-prefixed, try reading more
            if len(raw) >= 4:
                for fmt2 in ["!", "<"]:
                    try:
                        length = struct.unpack(fmt2 + "I", raw[:4])[0]
                        if 1 < length < 100000:
                            print("  Possible %s length: %d" % (fmt2, length))
                            resp_data = raw[4:]
                            if len(resp_data) < length:
                                tcp.settimeout(2)
                                try:
                                    more = tcp.recv(length)
                                    resp_data += more
                                except:
                                    pass
                            
                            # Try parse
                            for name, cls in [("SignedId", msg.SignedId), ("PublicKey", msg.PublicKey), 
                                              ("Hash", msg.Hash), ("TestDelay", msg.TestDelay)]:
                                try:
                                    parsed = cls()
                                    parsed.ParseFromString(resp_data[:length])
                                    fields = [f.name for f in parsed.DESCRIPTOR.fields if parsed.HasField(f.name)]
                                    if fields:
                                        print("  PARSED as %s: %s" % (name, str(fields)))
                                        if name == "Hash":
                                            print("    salt=" + parsed.salt)
                                            print("    challenge=" + parsed.challenge)
                                        elif name == "PublicKey":
                                            print("    asymmetric=%dB symmetric=%dB" % (len(parsed.asymmetric_value), len(parsed.symmetric_value)))
                                        elif name == "TestDelay":
                                            print("    time=%d" % parsed.time)
                                        break
                                except:
                                    pass
                    except:
                        pass
        except socket.timeout:
            print("Timeout - no response")
        
        tcp.close()
    except Exception as e:
        print("Error: " + repr(e))

print("\nDone.")
