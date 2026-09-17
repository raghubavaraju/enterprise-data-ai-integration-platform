# API specifications

Contract-first.  Every API in this repository has a published specification, and
the specification is the deliverable a consumer integrates against - not the
implementation, and not a Postman collection someone exported.

| Layer | API | Specification |
|---|---|---|
| Experience | Customer Experience API | `oas/customer-experience-api.v1.yaml`, `raml/customer-experience-api/` |
| Experience | AI Insights API | `oas/ai-insights-api.v1.yaml` |
| Experience | Store Associate API (second consumer, same process API) | `oas/store-associate-experience-api.v1.yaml`, `raml/store-associate-experience-api/` |
| Process | Customer 360 Process API | `oas/customer-360-process-api.v1.yaml` |
| Process | Customer Intelligence Process API | `oas/customer-intelligence-process-api.v1.yaml` |
| System | Snowflake Data System API | `oas/snowflake-data-system-api.v1.yaml` |
| System | CRM System API | `oas/crm-system-api.v1.yaml` |

Shared fragments live in `fragments/` and are referenced by `$ref` so that the
error model, pagination shape and correlation-id header are defined once.  In
Anypoint these are published as **API fragments in Exchange**; the RAML tree
under `raml/` shows the same decomposition in RAML 1.0, which is what Anypoint
Design Center produces.

## Why both RAML and OAS

RAML is what Anypoint's tooling generates flows and policies from, and its
libraries and resource types express reuse more directly.  OAS is what the rest
of the world's tooling reads, and it is what the CI spec-validation and contract
tests use.  Publishing both is normal in a MuleSoft estate; keeping them
consistent is a CI job (`scripts/validate_api_specs.py`), not a convention.

## Governance rules these specs are checked against

See `docs/api-governance.md`.  In summary: plural nouns, no verbs in paths,
major version in the URI, `x-correlation-id` on every request and response, the
canonical error object on every non-2xx, cursorless offset pagination with an
explicit `hasMore`, and no unbounded collection endpoints.
