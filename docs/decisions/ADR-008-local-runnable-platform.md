# ADR-008 / A locally runnable platform that executes the real SQL

**Status:** Accepted / **Date:** 2026-08 / **Decider:** Data & AI Architect

## Context

This platform's components normally require a Snowflake account, an Anypoint
Platform licence and an LLM provider key. That creates three problems:

1. **Reviewability.** An architecture nobody can run is an architecture nobody
   can check. A reader has to take the transformation logic on trust.
2. **CI.** Tests that need a cloud account are slow, flaky, expensive, and
   cannot run on a pull request from a fork.
3. **Onboarding.** A new engineer who needs three accounts before they can see
   anything work will not see anything work for a week.

## Problem

How can the platform be exercised end to end without any paid infrastructure,
without weakening the claim that the code is real?

## Options considered

### A. Mock everything

Stub responses at every boundary.

- **For:** Trivial. Fast tests.
- **Against:** Proves nothing. The SQL is never executed, so a transformation bug
  is invisible until it reaches Snowflake. Mocks encode what the author *believed*
  the dependency returns, and drift silently.

### B. Testcontainers with PostgreSQL

Run a real database, port the SQL to PostgreSQL.

- **For:** Real SQL execution.
- **Against:** Two copies of every transformation, in two dialects. They drift,
  and the drift is invisible because both pass their own tests. This is the
  failure mode that matters: a repository that *looks* like it validates its SQL
  while validating a divergent copy.

### C. A Snowflake trial account in CI

- **For:** The real thing.
- **Against:** Credentials in CI, a shared mutable environment, trial expiry,
  cost, and a fork can never get a green build.

### D. DuckDB executing the real scripts through an explicit dialect shim (chosen)

Run the **same** `.sql` files after a small, documented set of rewrites; skip the
Snowflake-only scripts and say which and why.

- **For:** The transformation logic in the repository is the logic that runs. No
  second copy to drift. Fast, a full build is about five seconds. No
  credentials, no cost, works on a fork. The boundary is explicit: `make build`
  prints every script it skipped and the feature that made it unportable.
- **Against:** DuckDB is not Snowflake. Some constructs cannot be translated, so
  parts of the pipeline are genuinely not exercised locally. The shim is code
  that must itself be maintained and tested.

## Decision

**Option D**, with three rules that keep it honest:

1. **The rewrite list is small, explicit and auditable.** Every rule is a real,
   named difference between the two engines, listed in
   `local_warehouse/dialect.py` and asserted by `tests/unit/test_sql_dialect.py`.
   A half-working general-purpose SQL translator would be worse than an honest
   boundary, because it would produce subtly different results instead of an
   error.
2. **Unportable constructs are skipped loudly, never faked.** `MERGE`, streams,
   tasks, Snowpipe, Cortex, masking policies, row access policies, `COPY INTO`
   and Time Travel are detected and reported with the reason.
3. **The differences are documented.** `local_warehouse/README.md` and
   `docs/deployment.md` §3 both carry the table of what is faithful and what is
   not.

The same principle extends to the rest of the stack: the Snowflake **SQL API**
contract is implemented locally over DuckDB, which is why the Mule flow logic is
identical in both modes; and the AI service ships a deterministic offline
provider so the grounding, guardrail, evaluation and audit pipeline can be tested
without a model.

## Consequences

**Positive**

- `make build && make test` runs 245 tests, including the full transformation
  chain and the data quality suite, in under twenty seconds with no accounts.
- A transformation bug fails on a laptop and not in Snowflake.
- CI proves the SQL parses and produces the expected rows on every commit.
- A reviewer can verify claims instead of believing them.
- The dialect shim doubles as documentation of the Snowflake features the design
  actually depends on, the skip list *is* the list.

**Negative**

- The incremental `MERGE` path, streams, tasks, Snowpipe, masking and row access
  policies are not exercised locally. They are written and reviewable and have
  never been run.
- The shim is maintenance: a new Snowflake construct may need a rule or a skip.
- Two SCD2 implementations exist: full-rebuild (portable) and MERGE-based
  (Snowflake-only). They must be kept equivalent. This is a real cost, partly
  offset by the full-rebuild path also being the recovery path.
- DuckDB may accept SQL Snowflake rejects, or differ in edge-case semantics
  (NULL ordering, decimal rounding). Local green is not a deployment guarantee.

**Neutral**

- The local warehouse has a single owner process because DuckDB permits one
  writer. That constraint pushed the AI service to read through the data
  platform's API and not opening the file, which turned out to be the better
  architecture in cloud mode too, for reasons that have nothing to do with
  DuckDB.

## Alternatives reconsidered

Option C is the right addition, not a replacement: a **nightly** job against a
real Snowflake account, running the full script set including the skipped ones,
gated on repository secrets and therefore skipped on forks. That gives the fast
per-commit signal and the slow high-fidelity one.

## What would make us revisit this

- The skip list growing large enough that most of the pipeline is unexercised
  locally, at which point the local build is reassuring rather than useful.
- A Snowflake-compatible local emulator of sufficient fidelity appearing.
- The two SCD2 implementations diverging in behaviour, which would mean paying
  for the nightly real-account job immediately.
