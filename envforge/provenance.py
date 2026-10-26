"""Content identity of the installed environment implementation."""

from functools import lru_cache
from pathlib import Path

from envforge.protocol.integrity import digest


@lru_cache(maxsize=1)
def implementation_digest() -> str:
    root = Path(__file__).parent
    return digest(
        {
            str(path.relative_to(root)): digest(path.read_text())
            for path in sorted(root.rglob("*.py"))
        }
    )
