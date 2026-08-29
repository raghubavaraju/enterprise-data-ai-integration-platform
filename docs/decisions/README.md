# Architecture decision records

One record per decision that was really contested, where a competent
architect could have chosen otherwise, and where reversing the choice later
would be expensive.

Decisions that were obvious are not recorded. An ADR for "we used HTTPS" is
noise that makes the real ones harder to find.

| ADR | Decision | Status |
|---|---|---|
| [001](ADR-001-api-led-connectivity.md) | API-led connectivity with three layers | Accepted |
| [002](ADR-002-snowflake-data-platform.md) | Snowflake as the analytical data platform | Accepted |
| [003](ADR-003-customer-360-materialised.md) | Customer 360 materialised, not a view | Accepted |
| [004](ADR-004-ai-separated-from-integration.md) | AI as a separate service, with no source-system access | Accepted |
| [005](ADR-005-apis-versus-events.md) | APIs now, events designed but not built | Accepted |
| [006](ADR-006-snowflake-sql-api-over-jdbc.md) | Snowflake SQL API rather than JDBC from Mule | Accepted |
| [007](ADR-007-transparent-churn-baseline.md) | A transparent rule-weighted churn baseline, not a fitted model | Accepted |
| [008](ADR-008-local-runnable-platform.md) | A locally runnable platform executing the real SQL | Accepted |

## Format

Context / Problem / Options considered / Decision / Consequences / Alternatives
reconsidered. Every record states what would make us revisit it, because an ADR
without a reversal condition is a justification instead of a decision.
