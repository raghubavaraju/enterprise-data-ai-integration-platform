# Architecture diagrams

All diagrams are **Mermaid**, so they render directly in GitHub and diff as text.
A `.drawio` file cannot be reviewed in a pull request; a diagram that cannot be
reviewed drifts from the system it describes.

| Diagram | What it shows |
|---|---|
| [01, Enterprise context](01-context.md) | Who uses the platform and what it depends on |
| [02, API-led architecture](02-api-led-architecture.md) | The three MuleSoft layers and every application |
| [03, Snowflake data architecture](03-data-architecture.md) | Layers, objects and the transformation DAG |
| [04, Customer 360 data flow](04-customer-360-flow.md) | Source record to agent screen |
| [05, AI architecture](05-ai-architecture.md) | Grounding, guardrails, RAG, evaluation, audit |
| [06, Security architecture](06-security-architecture.md) | Trust boundaries, controls and identities |
| [07, CI/CD](07-cicd.md) | Commit to deployment |
| [08, Disaster recovery](08-disaster-recovery.md) | Failure modes and recovery paths |
| [09, Deployment topology](09-deployment-topology.md) | Where everything runs, in both modes |
| [10, Event-driven extension](10-event-driven.md) | The designed, unbuilt asynchronous path |

## Conventions

- Solid arrows are synchronous calls; dashed arrows are batch or asynchronous.
- A red-outlined boundary is a trust boundary.
- Anything drawn with a dotted "designed, not built" note is that.
