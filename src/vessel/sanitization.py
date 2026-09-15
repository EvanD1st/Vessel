"""Client-independent bounded JSON redaction for event and MCP transport."""

from __future__ import annotations

import math
import re
from typing import Any

MAX_TEXT_CHARS = 16384
_SECRET_KEY = re.compile(
    r"(?i)(?:password|passwd|api[_-]?key|(?:^|_)token(?:$|_)|access[_-]?token|refresh[_-]?token|authorization|private[_-]?key|secret|seed[_-]?phrase)"
)
_SECRET_TEXT = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"(?is)-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(?:api[_-]?key|password|access[_-]?token|secret)[\"']?\s*[=:]\s*[\"']?[^\s\"',;}]+"),
)


class EventRejected(ValueError):
    """A bounded reason code; never include incoming text."""


def sanitize(value: Any, gaps: set[str] | None = None, *, depth: int = 0) -> Any:
    """Bound/redact JSON without storing any raw credentials in diagnostics."""
    gaps = gaps if gaps is not None else set()
    if depth > 20:
        gaps.add("nesting_truncated")
        return "[omitted: nesting limit]"
    if isinstance(value, dict):
        output = {}
        if len(value) > 256:
            gaps.add("fields_truncated")
        for key, item in list(value.items())[:256]:
            if not isinstance(key, str):
                raise EventRejected("invalid_object_key")
            if key.startswith("_vessel"):
                continue
            if len(key) > 256:
                gaps.add("key_truncated")
            output[key[:256]] = (
                "[REDACTED]" if _SECRET_KEY.search(key) else sanitize(item, gaps, depth=depth + 1)
            )
        return output
    if isinstance(value, list):
        if len(value) > 1000:
            gaps.add("list_truncated")
        return [sanitize(item, gaps, depth=depth + 1) for item in value[:1000]]
    if isinstance(value, str):
        # Redact before truncation so a PEM/key spanning the cutoff is removed.
        for pattern in _SECRET_TEXT:
            value = pattern.sub("[REDACTED]", value)
        if len(value) > MAX_TEXT_CHARS:
            gaps.add("text_truncated")
            return value[:MAX_TEXT_CHARS] + "\n[omitted: text limit]"
        return value
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise EventRejected("invalid_json_value")
