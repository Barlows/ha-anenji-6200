"""EyeBond's shared signature codec; callers own endpoint and action policy."""

from __future__ import annotations

import hashlib


def password_signature(salt: str, password: str, action: str) -> str:
    """Sign the caller's exact login suffix without choosing an auth profile."""

    password_hash = hashlib.sha1(password.encode("utf-8")).hexdigest()
    return hashlib.sha1((salt + password_hash + action).encode("utf-8")).hexdigest()


def session_signature(salt: str, secret: str, token: str, action: str) -> str:
    """Sign an exact suffix, including the caller's source/client metadata."""

    return hashlib.sha1((salt + secret + token + action).encode("utf-8")).hexdigest()
