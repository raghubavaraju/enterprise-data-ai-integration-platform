# Snowflake data platform

Execution order (each script is idempotent and safe to re-run):

```
00-database/      warehouse, database, resource monitor
01-schemas/       RAW / STAGING / CORE / ANALYTICS / AI / GOVERNANCE
02-tables/        DDL, by layer
03-views/         semantic + governed consumption views
04-procedures/    stored procedures (SCD2 load, DQ runner, churn scoring)
05-pipelines/     ingestion: stages, file formats, Snowpipe, streams, tasks   [Snowflake only]
06-transformations/  RAW -> STAGING -> CORE                                    [portable]
07-customer-360/  ANALYTICS.CUSTOMER_360 and its feeding aggregates            [portable]
08-ai/            feature store, churn scoring, Cortex, RAG corpus             [mixed]
09-data-quality/  rule definitions, checks, expected results                   [portable]
10-security/      roles, grants, masking policies, row access policies         [Snowflake only]
```

## Portability

Scripts marked **portable** are executed verbatim (after a small, documented
dialect rewrite) by the local DuckDB warehouse in `local_warehouse/`,
so the transformation logic in this repository is the logic that actually runs
in the demo - not a parallel copy that can silently drift.

Scripts marked **Snowflake only** use features with no local equivalent
(Snowpipe, streams, tasks, `MERGE`, Cortex functions, masking policies,
row access policies).  They are complete and runnable against a real account;
`local_warehouse/dialect.py` lists exactly which constructs are skipped
and why.

## Conventions

| Convention | Rule |
|---|---|
| Naming | `SCREAMING_SNAKE_CASE`; layer prefix only in RAW (`RAW_`) and STAGING (`STG_`) |
| Business key | The source system's natural key, kept verbatim, never re-used as a join key |
| Surrogate key | `<ENTITY>_SK`, `MD5` of business key (+ effective date for SCD2) |
| Audit columns | `_SRC_SYSTEM`, `_SRC_FILE`, `_INGESTED_AT`, `_BATCH_ID`, `_CORRELATION_ID`, `_ROW_HASH` |
| Reserved words | `ORDER` is reserved, so the order entity is `SALES_ORDER` |
| Time | All timestamps stored `TIMESTAMP_NTZ` in UTC; no local time anywhere |
| Money | `NUMBER(18,2)` with an explicit `CURRENCY_CODE` column - never a bare float |
