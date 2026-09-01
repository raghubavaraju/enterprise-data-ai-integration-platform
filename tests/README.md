# Tests

| Suite | What it proves | Needs a running stack |
|---|---|---|
| `tests/unit/` | Pure logic: masking, guardrails, resilience primitives, the SQL dialect rules | no |
| `tests/data/` | The warehouse builds correctly, the model holds its invariants, the DQ rules find the planted defects | no |
| `tests/api/` | API contracts, auth, error shapes, pagination, entitlement masking - in-process | no |
| `tests/ai/` | Groundedness, relevance, safety, consistency, PII leakage, prompt-injection resistance | no |
| `tests/integration/` | Real cross-process behaviour through the full API-led chain | yes - skipped automatically if not |

Run everything with `make test`.  CI runs the same command.

## Why the API tests run in-process

`TestClient` starts the ASGI app in the test process.  No ports, no docker, no
sleep-and-retry, and a failing test points at code rather than at the
environment.  The actually cross-process concerns - correlation-id propagation
across four services, circuit breaking, real HTTP status translation - are what
`tests/integration/` is for, and those are skipped rather than failed when the
stack is not running, so a developer without docker still gets a green suite
that means something.

## AI tests without a model

The suite runs against the local deterministic provider.  That is a feature, not
a limitation: the evaluation harness is testing *the pipeline* - grounding,
redaction, guardrails, scoring, audit - and a non-deterministic model would make
those assertions flaky for reasons that have nothing to do with the code under
test.  When a real provider is configured, the same suite runs against it and
the thresholds in `services/ai_service/evaluation.py` become a genuine model
quality gate.
