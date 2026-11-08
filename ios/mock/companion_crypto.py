"""Signing and sealing as docs/COMPANION.md describes them, shared by the mock and the test vectors."""

import base64
import hashlib
import hmac
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def b64url_encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def sign(key: bytes, method: str, path: str, time: str, nonce: str, body: bytes) -> str:
    msg = "\n".join([method, path, time, nonce, hashlib.sha256(body).hexdigest()])
    return hmac.new(key, msg.encode(), hashlib.sha256).hexdigest()


def seal_key(key: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"phoneuse seal").derive(key)


def seal(key: bytes, field: str, plaintext: str, nonce: bytes | None = None) -> str:
    nonce = nonce or os.urandom(12)
    ct = AESGCM(seal_key(key)).encrypt(nonce, plaintext.encode(), field.encode())
    return base64.b64encode(nonce + ct).decode()


def unseal(key: bytes, field: str, sealed: str) -> str:
    raw = base64.b64decode(sealed)
    return AESGCM(seal_key(key)).decrypt(raw[:12], raw[12:], field.encode()).decode()
