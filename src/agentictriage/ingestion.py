from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Ticket

_INJECTION_PATTERNS = (
    re.compile(r"\bignore\s+(all\s+)?previous\s+instructions\b", re.IGNORECASE),
    re.compile(r"\b(system|developer)\s+prompt\b", re.IGNORECASE),
    re.compile(
        r"\b(reveal|print|dump)\s+(your\s+)?(prompt|secrets?|credentials?)\b", re.IGNORECASE
    ),
)
_PII_PATTERNS = (
    (re.compile(r"(?<![\w.])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.])"), "[EMAIL]"),
    (re.compile(r"\b(?:\+?\d[\d .()-]{7,}\d)\b"), "[PHONE]"),
    (re.compile(r"\b(?:\d[ -]*?){13,19}\b"), "[PAYMENT_CARD]"),
)


@dataclass(frozen=True, slots=True)
class GuardResult:
    ticket: Ticket
    injection_detected: bool
    redactions: int


def inspect_and_redact(ticket: Ticket) -> GuardResult:
    combined = f"{ticket.subject}\n{ticket.body}"
    injection = any(pattern.search(combined) for pattern in _INJECTION_PATTERNS)
    subject, subject_count = _redact(ticket.subject)
    body, body_count = _redact(ticket.body)
    return GuardResult(
        ticket=ticket.model_copy(update={"subject": subject, "body": body}),
        injection_detected=injection,
        redactions=subject_count + body_count,
    )


def _redact(value: str) -> tuple[str, int]:
    count = 0
    for pattern, replacement in _PII_PATTERNS:
        value, matches = pattern.subn(replacement, value)
        count += matches
    return value, count
