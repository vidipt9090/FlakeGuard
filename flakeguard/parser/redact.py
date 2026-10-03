"""
flakeguard.parser.redact
~~~~~~~~~~~~~~~~~~~~~~~~
Mask sensitive patterns (emails, phone numbers, tokens) from text
before any log is stored.

This runs before storage — never after.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Patterns to redact
# ---------------------------------------------------------------------------

_PATTERNS: list[tuple[str, str]] = [
    # Email addresses
    (r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", "[REDACTED_EMAIL]"),
    # Phone-number-like strings: +91-XXXXXXXXXX, (XXX) XXX-XXXX, XXX-XXX-XXXX, etc.
    (r"(\+?\d[\d\s\-().]{7,}\d)", "[REDACTED_PHONE]"),
    # Long token-like strings: 20+ consecutive non-space alphanumeric/special chars
    # Covers API keys, JWT segments, base64 blobs, hex hashes, etc.
    (r"[A-Za-z0-9+/=_\-]{20,}", "[REDACTED_TOKEN]"),
]

_COMPILED: list[tuple[re.Pattern[str], str]] = [
    (re.compile(pat), repl) for pat, repl in _PATTERNS
]


def redact(text: str) -> str:
    """Return *text* with all sensitive patterns replaced by placeholders.

    Patterns are applied in order: email → phone → token.
    This function must be called before any log or test-id is stored.
    """
    for pattern, replacement in _COMPILED:
        text = pattern.sub(replacement, text)
    return text
