"""API key generation/hashing and permission checks.

Keys are high-entropy random tokens (`secrets.token_urlsafe`), so a fast
SHA-256 digest is an appropriate, industry-standard way to store them (unlike
low-entropy user passwords, which need a slow adaptive hash like bcrypt to
resist brute force). Only the digest is ever persisted; the plaintext key is
returned exactly once, at creation time.
"""

from __future__ import annotations

import hashlib
import secrets

_KEY_PREFIX = "sk_sentinel_"


def generate_api_key() -> str:
    return f"{_KEY_PREFIX}{secrets.token_urlsafe(32)}"


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def key_display_prefix(key: str) -> str:
    return key[: len(_KEY_PREFIX) + 6]


ROLE_HIERARCHY = {"read": 0, "write": 1, "admin": 2}


def role_satisfies(role: str, required: str) -> bool:
    return ROLE_HIERARCHY.get(role, -1) >= ROLE_HIERARCHY.get(required, 99)
