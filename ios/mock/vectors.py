#!/usr/bin/env python3
"""Prints the fixed-input signature and seal that ios/Tests/CompanionCryptoTests.swift checks."""

from companion_crypto import b64url_encode, seal, seal_key, sign

KEY = bytes(range(32))
print("key (base64url):", b64url_encode(KEY))
print("sig GET /v1/state:", sign(KEY, "GET", "/v1/state", "1794153854", "00112233445566778899aabbccddeeff", b""))
print("sig POST /v1/awake:", sign(KEY, "POST", "/v1/awake?x=1", "1794153854", "ffeeddccbbaa99887766554433221100",
                                  b'{"on":true}'))
print("seal key:", seal_key(KEY).hex())
print("seal passcode 123456:", seal(KEY, "passcode", "123456", nonce=bytes(range(12))))
