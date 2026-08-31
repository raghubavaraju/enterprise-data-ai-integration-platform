# MuleSoft applications

Four Mule 4 applications, one per API-led layer responsibility:

| Application | Layer | Responsibility |
|---|---|---|
| `experience-api/` | Experience | Client-shaped payload, entitlement masking, client SLA |
| `process-api/` | Process | Orchestration, degradation policy, business rules, idempotency |
| `system-api/snowflake-data-api/` | System | The only component that queries Snowflake |
| `system-api/crm-system-api/` | System | The only component that knows how the CRM talks |

## Running these

These are real Mule 4 projects: `pom.xml`, `mule-artifact.json`, flows under
`src/main/mule/`, DataWeave in `src/main/resources/dw/`, MUnit under
`src/test/munit/`, and per-environment properties under
`src/main/resources/config/`.  Building them needs a Mule runtime and Anypoint
credentials (`mvn -Pdev clean package` with the Anypoint Exchange repository
configured), which this repository cannot assume a reader has.

So that the architecture is still runnable and testable, `services/gateway/`
implements the same three layers, the same contracts, the same policies and the
same error semantics in Python, as three separate processes.  Every module there
names the Mule file it mirrors.  **Where the two differ, the Mule application is
the authoritative statement of the design.**

## Conventions used across all four

| Concern | Approach |
|---|---|
| Configuration | `configuration-properties` per environment, `secure-properties` for anything sensitive; nothing sensitive is ever in a file, only its key |
| Secrets | Runtime Manager secure properties / Anypoint Secrets Manager, injected as `${secure::...}` |
| Correlation | `correlationId` accepted from the inbound header, otherwise Mule's own; propagated on every outbound call and every log line |
| Errors | One global error handler per application, imported from `common/global-error-handler.xml`; one canonical error payload |
| Retry | `until-successful` on transient errors only, with exponential backoff |
| Timeouts | Explicit `responseTimeout` on every connector - the default is never left in place |
| Logging | `logger` at flow boundaries only, structured, never the full payload (PII) |
| API discovery | `api-gateway:autodiscovery` so API Manager policies apply to the deployed app |
| Testing | MUnit with mocked connectors; coverage gate in CI |
