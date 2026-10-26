"""Canonical content identities for reproducible, tamper-evident artifacts."""

import hashlib
import json
from typing import Any


def digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()
