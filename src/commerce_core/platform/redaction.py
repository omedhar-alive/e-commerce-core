"""One redaction policy for logs and error reports (A12, X13a, X15).

Values under a sensitive key are replaced whole. Free text is scrubbed for
the shapes that identify people or open accounts: email addresses, phone
numbers, bearer and JWT-like tokens, card-like digit runs. Names and
addresses cannot be recognised in free text, so they must only ever be
logged under a named key, which is then replaced.
"""

import re
from collections.abc import Mapping
from typing import Any

REDACTED = "[REDACTED]"

SENSITIVE_KEY = re.compile(
    r"(pass(word)?|secret|token|authorization|auth|cookie|session|csrf|api[_-]?key|dsn|"
    r"signature|card|pan|cvv|email|phone|mobile|first_name|last_name|full_name|^name$|"
    r"address|street|city|postcode|postal|recipient|payload|body)",
    re.IGNORECASE,
)

_PATTERNS = [
    re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+"),  # email
    re.compile(r"(?i)bearer\s+[\w\-.~+/=]+"),  # bearer token
    re.compile(r"\beyJ[\w-]+\.[\w-]+\.[\w-]*"),  # JWT
    re.compile(r"\+\d[\d\s-]{6,}\d"),  # international phone
    re.compile(r"\b\d{10,19}\b"),  # local phone or card-like digit run
    re.compile(r"(?i)(otpauth://\S+)"),  # TOTP provisioning URIs
]


def scrub_text(text: str) -> str:
    for pattern in _PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def scrub(value: Any, key: str | None = None, depth: int = 0) -> Any:
    if key is not None and SENSITIVE_KEY.search(str(key)):
        return REDACTED
    if depth > 8:
        return REDACTED
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, Mapping):
        return {k: scrub(v, k, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(scrub(v, None, depth + 1) for v in value)
    return value
