# ADR-002 / Snowflake as the analytical data platform

**Status:** Accepted / **Date:** 2026-08 / **Decider:** Data Architect

## Context

The platform needs somewhere to hold integrated customer data. The workload is
genuinely mixed, and that mix is what decides the answer:

| Workload | Pattern | Frequency |
|---|---|---|
| Batch transformation | Heavy, minutes, once or twice a day | Scheduled |
| Interactive API reads | Single-row lookups, sub-second, bursty | Continuous |
| Analyst exploration | Unpredictable, occasionally very large | Working hours |
| AI feature and embedding generation | Vectorised, occasional | Scheduled + on demand |

Two constraints matter: PII must be governed inside the platform, and the
organisation is small enough that a data platform nobody can operate is worse
than a less capable one that they can.

## Problem

Which analytical platform, given that the same data must serve a 200 ms API
lookup and a multi-minute transformation without either paying for the other?

## Options considered

### A. PostgreSQL (or another OLTP database)

- **For:** Everyone knows it. Cheap. Excellent for the single-row API lookup.
- **Against:** Analytical scans on a row store at 40 million orders a year are
  slow and get slower. Scaling is vertical. Concurrency between a batch
  transformation and interactive reads means one starves the other. It is the
  right answer at a tenth of this scale and the wrong one here.

### B. A data lake (S3 + Spark/Databricks)

- **For:** Cheapest storage. Best for very large volumes and ML at scale.
  Databricks is already used elsewhere in the organisation as an integration
  consumer.
- **Against:** Sub-second single-row lookups need an extra serving layer, so the
  architecture grows a component. Governance. Masking, row access, lineage: is
  bolted on instead of native. Operating Spark is a skill the data team would
  have to acquire and keep.

### C. A warehouse appliance (Redshift, Synapse, BigQuery)

- **For:** Mature. Strong analytical performance.
- **Against:** Redshift and Synapse couple storage and compute, so an
  interactive workload and a batch workload share a cluster and interfere.
  BigQuery separates them well but ties the estate to one cloud, which is a
  larger commitment than the platform needs to make.

### D. Snowflake (chosen)

- **For:** Storage and compute separated, so an XSMALL warehouse can serve API
  reads while a SMALL one runs the batch, on the same data, with no
  interference and no copy. Zero-copy cloning makes non-production environments
  effectively free and makes point-in-time recovery a clone instead of a
  restore. Governance is native: dynamic masking, row access policies,
  `ACCESS_HISTORY`, object tagging. Cortex keeps AI inference inside the account,
  which removes the hardest question in the AI data protection assessment.
  Time Travel gives a recovery mechanism with no operational cost.
- **Against:** Consumption pricing punishes carelessness, an unattended
  warehouse is a recurring bill. Vendor lock-in, particularly around Snowpark,
  Cortex and the vector type. Not the cheapest per terabyte.

## Decision

**Option D, Snowflake**, with three separate warehouses:

| Warehouse | Size | Auto-suspend | Serves |
|---|---|---:|---|
| `ACME_INTEGRATION_WH` | XSMALL, multi-cluster to 3 | 60 s | Synchronous API reads |
| `ACME_TRANSFORM_WH` | SMALL | 120 s | Batch transformation |
| `ACME_AI_WH` | SMALL | 60 s | Cortex inference and embeddings |

The warehouse separation is the decision inside the decision. Mixing them means
an interactive API call pays for a batch-sized warehouse, and AI spend becomes
unattributable. Three warehouses cost nothing extra when suspended and make cost
attributable by workload: which makes a resource monitor on the AI
warehouse a meaningful control rather than a shared cap.

## Consequences

**Positive**

- One copy of the data serves both workloads.
- Non-production refresh is a clone: minutes, no storage cost, masking policies
  still applied.
- Recovery from a bad load is a clone-and-diff rather than a restore.
- The governance controls the architecture depends on, masking, row access,
  access history: are platform features, not custom code.
- With Cortex, grounding data never leaves the account.

**Negative**

- Cost discipline is a design obligation, not an afterthought: hence the
  aggressive auto-suspend, the statement timeouts, the resource monitors, and
  the materialised Customer 360 that keeps API reads off the join path.
- Lock-in. Standard SQL and the layered model would port; Cortex, Snowpark,
  streams, tasks and the vector type would not.
- The local development story needed solving, which is what
  [ADR-008](ADR-008-local-runnable-platform.md) is about.

**Neutral**

- The `MERGE`-based incremental loads are Snowflake-only in this repository, so
  the local build uses a full-rebuild path that produces the same end state.

## Alternatives reconsidered

Option B has the strongest case if the interaction volume (500 million events a
year) became the dominant workload rather than an aggregated feed. The
architecture anticipates that: interactions are aggregated on ingest, and if that
stopped being adequate, a lakehouse layer under CORE would be the change, not a
replatform.

## What would make us revisit this

- Consumption cost exceeding the modelled budget by more than 50% after the
  obvious optimisations, which would mean the workload mix is not what was
  assumed.
- Interaction-level analytics becoming a first-class requirement at raw fidelity.
- Salesforce Data 360 absorbing enough of the unified-profile workload that
  Snowflake became a feeder instead of the platform.
