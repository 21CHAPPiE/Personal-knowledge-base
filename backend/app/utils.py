"""Small shared helpers (time, tags, file naming)."""

import re
import unicodedata
from datetime import datetime, timezone


def utcnow_iso() -> str:
    """UTC timestamp, second precision, e.g. 2026-08-24T10:00:00Z."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_tags(raw) -> list:
    """Normalize a tag list / comma string into a clean, deduplicated list."""
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = raw.split(",")
    else:
        parts = list(raw)
    seen = set()
    result = []
    for p in parts:
        t = str(p).strip().strip(",").strip()
        if not t:
            continue
        t = re.sub(r"\s+", " ", t)[:40]
        key = t.casefold()
        if key not in seen:
            seen.add(key)
            result.append(t)
    return result


def sanitize_original_name(filename: str, max_len: int = 80) -> str:
    """Clean a user-supplied filename for display/metadata (control chars, length)."""
    name = unicodedata.normalize("NFC", str(filename or ""))
    name = re.sub(r"[\x00-\x1f\x7f]", "_", name)
    name = name.replace("\\", "/")
    return name[-max_len:] if len(name) > max_len else name
