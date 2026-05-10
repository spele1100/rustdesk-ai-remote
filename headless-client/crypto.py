"""NaCl crypto helpers for RustDesk protocol."""

import os
import hashlib
from nacl.public import PrivateKey, PublicKey, Box
from nacl.bindings import crypto_sign_keypair, crypto_sign


def generate_keypair():
    """Generate a NaCl keypair (for Box encryption)."""
    private_key = PrivateKey.generate()
    public_key = private_key.public_key
    return private_key, public_key


def generate_sign_keypair():
    """Generate a signing keypair (for SignedId)."""
    pk, sk = crypto_sign_keypair()
    return sk, pk


def sign_id(my_id: str, sign_sk: bytes) -> bytes:
    """Sign an ID string with the signing secret key."""
    return crypto_sign(my_id.encode(), sign_sk)


def make_box(private_key, peer_public_key) -> Box:
    """Create a NaCl Box from our private key and peer's public key."""
    return Box(private_key, peer_public_key)


def encrypt(box: Box, plaintext: bytes, nonce: bytes = None) -> tuple:
    """Encrypt with NaCl Box. Returns (nonce, ciphertext)."""
    if nonce is None:
        nonce = os.urandom(24)
    ciphertext = box.encrypt(plaintext, nonce)
    # ciphertext includes nonce prefix (24 bytes) + encrypted data
    return nonce, ciphertext.ciphertext


def decrypt(box: Box, ciphertext: bytes, nonce: bytes) -> bytes:
    """Decrypt with NaCl Box."""
    return box.decrypt(ciphertext, nonce)


def encrypt_password(password: str, challenge: str) -> bytes:
    """
    Encrypt password for RustDesk login.
    The password is hashed with the challenge/salt from the server.
    
    RustDesk uses: sign(private_key, sha256(password + challenge))
    But for headless client we do a simpler approach matching the protocol:
    The password field in LoginRequest is the encrypted password bytes.
    """
    # RustDesk password encryption: the password is encrypted using the shared secret
    # from the NaCl key exchange. The challenge from Hash message provides the salt.
    # For now, we send the password as-is (plaintext bytes) — the actual encryption
    # depends on the key exchange having been completed, and the box being used.
    # This will be done in client.py where we have the box.
    return password.encode("utf-8")


def hash_password(password: str, salt: str) -> bytes:
    """
    Hash password with salt for RustDesk.
    Matches RustDesk's password verification.
    """
    return hashlib.sha256((password + salt).encode()).digest()
