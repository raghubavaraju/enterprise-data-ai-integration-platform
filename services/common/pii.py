"""PII detection, masking and tokenisation.

Two distinct jobs, on purpose kept separate:

1. ``mask_*``   - what an API returns to a client that lacks the ``pii:read``
                  entitlement.  Irreversible, presentation-level.
2. ``redact_for_ai`` - what leaves the trust boundary towards a model provider.
                  Direct identifiers are replaced by stable pseudonyms so the
                  model can still refer to "the customer" coherently, and the
                  mapping never leaves the platform.

``docs/data-governance.md`` holds the classification table this implements.
"""
from __future__ import annotations

import hashlib
import re

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"\+?\d[\d\s().-]{7,}\d")
CARD_RE = re.compile(r"\b(?:\d[ -]*?){13,16}\b")

SALT = "acme-edp-pseudonymisation-salt"          # cloud mode: from secrets manager


def pseudonymise(value: str, prefix: str = "CUST") -> str:
    digest = hashlib.sha256(f"{SALT}:{value}".encode()).hexdigest()[:12].upper()
    return f"{prefix}_{digest}"


def mask_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return email
    local, _, domain = email.partition("@")
    keep = local[0] if local else ""
    return f"{keep}{'*' * max(3, len(local) - 1)}@{domain}"


def mask_phone(phone: str | None) -> str | None:
    if not phone:
        return phone
    digits = re.sub(r"\D", "", phone)
    return f"***-***-{digits[-4:]}" if len(digits) >= 4 else "***"


def mask_name(name: str | None) -> str | None:
    if not name:
        return name
    return f"{name[0]}{'*' * max(2, len(name) - 1)}"


def mask_birth_date(value: str | None) -> str | None:
    """Generalise to year - date of birth is a quasi-identifier."""
    return f"{value[:4]}-**-**" if value and len(value) >= 4 else value


def redact_for_ai(text: str) -> str:
    """Strip direct identifiers from free text before it leaves the boundary."""
    text = EMAIL_RE.sub("[EMAIL_REDACTED]", text)
    text = CARD_RE.sub("[CARD_REDACTED]", text)
    text = PHONE_RE.sub("[PHONE_REDACTED]", text)
    return text


MASKERS = {
    "email": mask_email,
    "phone": mask_phone,
    "birthDate": mask_birth_date,
    "fullName": lambda v: mask_full_name(v),
    "firstName": mask_name,
    "lastName": mask_name,
}


def mask_full_name(name: str | None) -> str | None:
    """Keep the given name, mask the family name.

    An agent needs to address the customer; they do not need the surname on a
    screen that may be shared or screenshotted.  Masking the whole name makes
    the record unusable, which is how masking gets switched off in practice.
    """
    if not name:
        return name
    parts = name.split()
    if len(parts) == 1:
        return parts[0]
    return " ".join([parts[0]] + [mask_name(p) for p in parts[1:]])


def apply_profile_masking(profile: dict, allowed: bool) -> dict:
    """Return the profile as the caller is entitled to see it.

    Only fields that are present are masked - inventing a masked value for a
    field the response never contained would tell the client the field exists,
    which is itself a small disclosure.
    """
    if allowed:
        return profile
    out = dict(profile)
    for field, masker in MASKERS.items():
        if field in out and out[field] is not None:
            out[field] = masker(out[field])
    out["_masked"] = True
    out["_maskedFields"] = sorted(f for f in MASKERS if f in profile)
    return out
