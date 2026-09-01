"""Input and output guardrails for generative calls.

Three checks, in this order, because each is cheaper than the next and each
removes work from the one after it:

  1. INPUT   redact direct identifiers before anything leaves the boundary.
  2. INPUT   detect instruction-like content inside the data (prompt injection
             via a support-case description is the realistic attack here - the
             attacker is a customer typing into a web form, not a hacker).
  3. OUTPUT  validate the generated text: no leaked PII, no invented numbers,
             no promises, correct shape.

The output check is what turns "the model usually behaves" into a system
property.  A response that fails it is never returned as if it succeeded; the
caller gets a degraded, deterministic answer and the failure is audited.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from common.pii import EMAIL_RE, PHONE_RE, redact_for_ai

INJECTION_PATTERNS = [
    r"ignore (all |any |the )?(previous|prior|above) instructions",
    r"disregard (the |your )?(system|previous|above)",
    r"you are now\b", r"\bnew instructions?\b", r"</?(system|assistant|user)>",
    r"reveal (your |the )?(system )?prompt", r"print (your|the) instructions",
    r"\bDAN\b", r"jailbreak", r"act as (an? )?(unrestricted|uncensored)",
]

# Things the model must never commit Acme to.
PROMISE_PATTERNS = [
    r"\bwe (will|shall) (refund|credit|compensate|reimburse)\b",
    r"\byou (will|shall) receive\b", r"\bguarantee(d)?\b",
    r"\bwe promise\b", r"\bwill be delivered (on|by)\b",
]


@dataclass
class GuardrailReport:
    passed: bool = True
    input_redacted: bool = False
    injection_detected: bool = False
    findings: list[str] = field(default_factory=list)

    def fail(self, finding: str) -> GuardrailReport:
        self.passed = False
        self.findings.append(finding)
        return self


def sanitise_input(text: str) -> tuple[str, bool, bool]:
    """Returns (clean_text, was_redacted, injection_detected)."""
    if not text:
        return "", False, False
    injected = any(re.search(p, text, re.IGNORECASE) for p in INJECTION_PATTERNS)
    clean = redact_for_ai(text)
    if injected:
        # Neutralise rather than drop: the analyst still needs to know a case
        # exists, and silently discarding customer text loses information.
        clean = "[CONTENT WITHHELD: this record contains instruction-like text]"
    return clean, clean != text, injected


# A standalone numeric token: not part of an identifier.  The lookarounds are
# what stop "RETENTION_OFFER_15_PCT", "KB-009" and "CRM-100005" from being read
# as the claims "15", "009" and "100005" - false positives that would make the
# groundedness check cry wolf on every recommendation and citation.
_NUMBER_RE = re.compile(r"(?<![\w.\-])-?\d[\d,]*(?:\.\d+)?(?![\w.])")


def numbers_in(text: str) -> set[str]:
    """Standalone numeric tokens, normalised so 1,234.50 and 1234.5 compare equal."""
    out = set()
    for raw in _NUMBER_RE.findall(text or ""):
        cleaned = raw.replace(",", "").rstrip(".")
        if not cleaned or cleaned in {"-"}:
            continue
        try:
            value = float(cleaned)
        except ValueError:
            continue
        out.add(f"{value:g}")
    return out


def check_output(generated: str, grounding_text: str,
                 allow_numbers: set[str] | None = None) -> GuardrailReport:
    report = GuardrailReport()
    if not generated or not generated.strip():
        return report.fail("empty generation")

    if EMAIL_RE.search(generated):
        report.fail("output contains an e-mail address")
    if PHONE_RE.search(generated):
        report.fail("output contains a telephone number")

    for pattern in PROMISE_PATTERNS:
        if re.search(pattern, generated, re.IGNORECASE):
            report.fail(f"output makes a commitment on Acme's behalf: /{pattern}/")

    # Every number stated must be traceable to the grounding block.  This is the
    # cheapest and most effective hallucination check available, because the
    # hallucinations that cause damage are almost always numeric.
    permitted = numbers_in(grounding_text) | (allow_numbers or set())
    # Small integers are structural ("one open case", "3 drivers") and are not
    # evidence of fabrication.
    unsupported = {n for n in numbers_in(generated)
                   if n not in permitted and abs(float(n)) > 10}
    if unsupported:
        report.fail(f"output states numbers absent from the grounding data: "
                    f"{sorted(unsupported)}")
    return report
