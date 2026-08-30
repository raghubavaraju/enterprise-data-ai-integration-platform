# API Manager policies

Policies are configured in **API Manager**, not in application code.  The
distinction matters: a policy applied in code ships with the release and can be
removed by a developer; a policy applied at the gateway is owned by the platform
team, is auditable, and applies to every version of the API instance.

The JSON files here are the policy definitions as exported from API Manager, so
that the intended security posture is reviewable in the repository and can be
applied by the pipeline (`.github/workflows/ci.yml` -> `deploy` job).

| Policy | Applied to | Why |
|---|---|---|
| `jwt-validation.json` | Experience APIs | Validates the token signature against the IdP JWKS, checks issuer, audience and expiry, and extracts scopes into a header the flow can read |
| `rate-limiting-sla.json` | Experience APIs | Per-client SLA tiers. Protects the warehouse and the AI provider from a single misbehaving consumer |
| `ip-allowlist.json` | Process and System APIs | These are never reachable from outside the VPC; the allow-list is the second control after network segmentation |
| `client-id-enforcement.json` | All | Every call is attributable to a registered client application |
| `header-removal.json` | Experience APIs | Strips internal headers (`x-query-tag`, `x-mule-*`) before the response leaves the platform |
| `spike-control.json` | AI Insights API | Generative calls are expensive; a spike is throttled rather than passed through |

## Layering

    internet
      -> WAF / API gateway            TLS termination, IP allow-list, WAF rules
      -> Experience API               JWT validation, SLA rate limit, spike control
      -> Process API                  internal only, client id enforcement, mTLS
      -> System API                   internal only, mTLS, read-only credential
      -> Snowflake / AI provider      network policy, key-pair auth, RBAC

Each layer assumes the one outside it may have failed.  That is the whole point
of defence in depth, and it is why the System API's Snowflake role is read-only
even though nothing upstream of it can issue a write.
