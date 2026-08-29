# ADR-003 / Customer 360 materialised, not a view

**Status:** Accepted / **Date:** 2026-08 / **Decider:** Data Architect

## Context

`ANALYTICS.CUSTOMER_360` unifies CRM, orders, support, loyalty and engagement
into one row per customer with ~45 attributes, several of them windowed
aggregates. It is read by:

- the Customer 360 API, on every service-desk screen load, with an 800 ms p95
  budget;
- the AI feature store, once per day;
- analysts, ad hoc;
- the churn scorer, once per day.

Underneath it are eight tables and a set of window functions.

## Problem

Should the unified view be computed on read (a view) or on write (a table)?

## Options considered

### A. A view

`CREATE VIEW CUSTOMER_360 AS SELECT ... FROM eight tables ...`

- **For:** Always current. No orchestration. No storage. One object to change.
- **Against:** Every API call recomputes an eight-table join with window
  functions. On an XSMALL warehouse at production volumes that is seconds, not
  milliseconds, the latency budget is gone before masking and shaping. Cost
  scales with read volume instead of with data volume. And the number changes
  under the model's feet, so an AI explanation generated at 10:00 cannot be
  reproduced at 10:05.

### B. A materialised view (Snowflake native)

- **For:** Automatic maintenance. Always current.
- **Against:** Snowflake materialised views do not support joins, aggregates over
  multiple tables, window functions or non-deterministic functions. `CUSTOMER_360`
  needs all four. This option is unavailable, not merely unattractive.

### C. A table, rebuilt on a schedule (chosen)

- **For:** Single-row lookup on a clustered table: milliseconds. Computed once
  per load and read many times, so cost tracks data volume rather than traffic.
  Stable: an AI insight and a churn score are grounded on a known snapshot, and
  `AS_OF_TIMESTAMP` makes the snapshot explicit.
- **Against:** Staleness bounded by the load cadence. Orchestration and a
  freshness SLA to own. Storage. Negligible at this row count.

### D. A table plus an event-driven incremental refresh

- **For:** All of C, with near-real-time freshness for the fields that need it.
- **Against:** Requires the event platform, which does not exist yet
  ([ADR-005](ADR-005-apis-versus-events.md)). Complexity now for freshness nobody
  has yet asked for.

## Decision

**Option C.** Rebuilt daily by the transformation task, with the freshness
published as `AS_OF_TIMESTAMP` in every API response and enforced by a timeliness
data quality rule (`DQ-X-007`, BLOCKING at 24 hours).

Publishing the freshness is the part that makes the trade-off honest. A consumer
can see how old the number is and decide for itself; a view would have been
implicitly current and a table without `AS_OF_TIMESTAMP` would be implicitly
trusted.

## Consequences

**Positive**

- The API read path is a primary-key lookup, which is what keeps the p95 budget
  achievable and warehouse concurrency from being the first limit reached.
- Cost is proportional to data volume, not to how many times the service desk
  opens a customer.
- AI grounding is reproducible: the snapshot the model saw is recorded, and the
  underlying row did not move while it was being explained.
- The rebuild is also the recovery path, `CUSTOMER_360` can be reconstructed
  from CORE at any time.

**Negative**

- Up to 24 hours stale. Acceptable for segment, lifetime value and tenure;
  **not** acceptable indefinitely for "has an open case" and "ordered this
  morning", which is the first thing Option D would fix.
- A freshness SLA to own, monitor and alert on.
- A pipeline failure now has a visible customer-facing symptom, which is
  arguably a feature: the DQ rule fires before an agent notices.

**Neutral**

- Full rebuild and not incremental, while it takes minutes on an XSMALL. The
  switch to a stream-driven MERGE is a change to one script, and the trigger will
  be cost, not elegance.

## Alternatives reconsidered

Option A survives for the *supporting* aggregates in development, where the data
is small and the convenience is real. It does not survive contact with the
latency budget.

## What would make us revisit this

- A named consumer with a sub-hour freshness requirement, which moves us to
  Option D for the specific fields that need it, not for the whole table.
- The rebuild exceeding the batch window, which moves us to incremental.
- Snowflake materialised views gaining support for joins and window functions,
  which would make Option B viable and remove the orchestration.
