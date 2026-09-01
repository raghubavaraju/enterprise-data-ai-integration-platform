# Resilience and disaster recovery

> **Every target in this document is an architectural assumption made for this
> proof of concept.** They are not measured, not agreed with a business, and not
> a production SLA. They are here because an architecture without stated targets
> cannot be reviewed, and because the right answer to "what is your RTO?" is a
> number with a justification, not "as fast as possible".

## 1. Failure modes, and what each one does

| Failure | Blast radius | Behaviour | Customer impact |
|---|---|---|---|
| One source system down | Ingestion for that domain | The last good data continues to serve; the next load catches up | Staleness in one section of the 360 |
| Snowflake unavailable | All read APIs | Circuit breaker opens; 503 with `retryable: true` | Customer 360 unavailable; the service desk falls back to the CRM directly |
| AI provider unavailable | Generative endpoints only | Degrades to analytics and the churn score, which are deterministic | No narrative; the score and the drivers still appear |
| One Mule worker fails | None | Load balancer removes it; the remaining workers absorb the traffic | None |
| An entire CloudHub region fails | All APIs in that region | Failover to the secondary region | Outage for the duration of the failover |
| A bad deployment | The deployed application | Automatic rollback on the health check | Brief elevated errors |
| Corrupt data loaded to CORE | Analytics and AI | Rebuild CORE from RAW; DQ rules should have caught it | Wrong numbers until the rebuild completes |
| Accidental table drop | One object | Snowflake `UNDROP` within the Time Travel window | Minutes |
| Credential compromise | Whatever that credential could reach | Revoke, rotate, audit via `ACCESS_HISTORY` and the per-client API audit | Depends on the credential |

The pattern in the "behaviour" column is deliberate: **degrade in the direction
of the deterministic**. The AI narrative can be lost without losing the churn
score; the churn score can be lost without losing the profile.

## 2. Resilience patterns, and where each one lives

### Timeouts, a budget that shrinks inward

| Hop | Budget | Why |
|---|---:|---|
| Client → experience | 10 s | The client's own patience |
| Experience → process | 5 s | Leaves headroom for shaping and masking |
| Process → system | 3.5 s | Leaves headroom for orchestration across three concurrent calls |
| System → Snowflake | 20 s statement, 22 s HTTP | Interactive queries; anything longer is a bug, not a slow query |
| Process → AI | 20 s | Generative calls are slow by nature |

Each budget is **strictly smaller than its caller's**. If an inner timeout were
larger, the caller would give up first and the inner work would be wasted. And,
worse, the caller would report a timeout while the downstream reported success.

The AI budget is intentionally outside the chain: it is only ever reached on an
opt-in path, which is one of the reasons the AI Insights API is a separate
deployment.

### Retry. Transient only, with jitter

Retried: `HTTP:TIMEOUT`, `HTTP:CONNECTIVITY`, `HTTP:SERVICE_UNAVAILABLE`.
Not retried: 400, 404, 409, 422, and **every generative call**.

Retrying a 404 cannot succeed; it only multiplies load and latency. Retrying a
generative call doubles the bill and, on a busy day, helps push the provider over
its own limits.

Backoff is exponential with **full jitter**. A fixed schedule means every worker
retries at the same moment and the recovering downstream is knocked over by the
synchronised wave.

### Circuit breaker

Per dependency. Five failures opens it; 30 seconds later it half-opens and allows
one probe.

The argument for it: when Snowflake or the LLM provider is degraded, hammering it
with retries turns a partial outage into a full one and burns credits. Failing
fast lets the caller fall back to cached or degraded data, which is exactly what
the Customer 360 flow does.

State is exposed on every `/health` endpoint, and any open breaker is a P2 alert.

### Bulkhead

Concurrency towards the AI service is bounded at four, independent of inbound
traffic. Without it, a traffic spike on Customer 360 fans out to a paid provider
and converts a busy morning into an invoice.

### Idempotency

`Idempotency-Key` on every operation with a side effect that costs money,
enforced at the process layer with a **persistent** object store so the guarantee
survives a worker restart. An in-memory idempotency store is not an idempotency
store.

### Graceful degradation

The one that matters most in practice. A Customer 360 assembled from five systems
will, on any given day, have one of them unavailable. Three options:

1. fail the whole request, unacceptable; an agent with a customer on the phone
   gets a blank screen;
2. silently return partial data, worse; the agent cannot tell "no orders" from
   "the order system is down";
3. return what is available, name what is missing, and say why.

The platform does (3), which is why `partial` and `degradedFields` are in the
published contract and not bolted on later.

## 3. Availability targets (assumptions)

| Component | Target | Basis |
|---|---:|---|
| Experience APIs | 99.9% | ~43 minutes/month. Multi-worker, multi-AZ |
| Process APIs | 99.9% | Same |
| System APIs | 99.9% | Same |
| Snowflake | 99.9% | Vendor SLA |
| AI provider | 99.5% | Lower, and treated as optional by design |
| **End-to-end Customer 360** | **99.5%** | Compound, mitigated by degradation |

The end-to-end figure is lower than any single component's, which is the idea of
stating it: the naive assumption that a chain is as available as its parts is how
availability promises get broken.

## 4. RTO and RPO (assumptions)

| Scenario | RTO | RPO | Recovery |
|---|---:|---:|---|
| Single worker failure | 0 | 0 | Load balancer removes it |
| Application failure | 5 min | 0 | Automatic restart or rollback |
| Region failure | 30 min | 0 for APIs | DNS failover to the secondary region |
| Snowflake object dropped | 15 min | 0 | `UNDROP` within Time Travel |
| Corrupt data in CORE | 2 h | 1 h | Rebuild from RAW |
| Corrupt data in RAW | 4 h | 24 h | Re-ingest from the source system |
| Full Snowflake account loss | 4 h | 1 h | Failover to the replicated account |
| Total platform loss | 8 h | 1 h | Rebuild from infrastructure as code + replica |

Two of these are worth reading carefully:

- **The APIs have an RPO of zero because they hold no state.** All state is in
  Snowflake or in a source system. That is a design outcome, not luck: it is why
  the object stores hold only idempotency keys and breaker flags, both of which
  are safe to lose.
- **Corrupt data in CORE has a 2-hour RTO because CORE is rebuildable from RAW.**
  If CORE were the only copy, this row would say "restore from backup" and the
  number would be much larger.

## 5. Backup and replication

| What | Mechanism | Retention |
|---|---|---|
| Snowflake data | Time Travel | 1 day RAW/STAGING, 7 days CORE/ANALYTICS/AI |
| Snowflake data | Fail-safe (Snowflake-managed) | 7 days after Time Travel |
| Snowflake account | Database replication to a secondary region | Continuous |
| Source landing files | Object store with versioning | 90 days |
| Mule applications | Immutable artefacts in Exchange | Indefinite |
| Configuration | Git | Indefinite |
| Secrets | Anypoint Secrets Manager / vault, with its own backup | Per policy |

**Zero-copy cloning is the recovery tool that gets underused.** Cloning
`ACME_EDP` to `ACME_EDP_RECOVERY` at a point in time is effectively free and
instant, which means the standard response to "we think last night's load
corrupted something" is: clone to before the load, compare, decide. Rather than
restore and hope.

## 6. Recovery runbooks

### Corrupt data in CORE

1. Stop the pipeline (suspend the Snowflake tasks).
2. `CREATE DATABASE ACME_EDP_INVESTIGATE CLONE ACME_EDP AT (OFFSET => -3600);`
3. Diff the suspect tables against the clone to establish the blast radius.
4. Fix the transformation, or quarantine the offending source batch.
5. Re-run `06-transformations` and `07-customer-360`, CORE and ANALYTICS are
   rebuildable, so this is a re-run, not a restore.
6. Run the DQ suite and confirm the expected outcome (14 PASS / 5 WARN / 3 FAIL
   on the sample dataset).
7. Resume tasks. Record the incident against the rule that should have caught it,
   and add the rule if none existed.

Step 7 is the one that compounds: every incident either confirms a rule or
creates one.

### Region failover

1. Confirm the primary is really unavailable, not slow, failing over from a
   slow region is usually worse than waiting.
2. Promote the replicated Snowflake database in the secondary region.
3. Repoint the System API configuration at the promoted account.
4. Update DNS to the secondary CloudHub region (TTL 60 s).
5. Verify with the smoke test.
6. Announce degraded state: the replica's RPO is one hour, so the most recent
   loads may be missing.

### AI provider outage

Nothing to do. The circuit breaker opens, generative endpoints return the
degraded message, and analytics and churn scores are unaffected. Confirm the
degradation is visible in `meta.degradedFields` instead of presenting as a 500,
and confirm the review queue is not filling with blocked outputs.

### Credential compromise

1. Revoke at the issuer (IdP for OAuth, Snowflake for the key pair).
2. Rotate and redeploy. The application does not change, because it references
   a property name, not a value.
3. Establish blast radius: `ACCESS_HISTORY` for the warehouse,
   `AI_REQUEST_AUDIT` and the API audit for the platform, both keyed by client id.
4. Follow the incident process.

Step 3 is only fast because every call is attributable to a registered client.

## 7. Testing the plan

A recovery plan that has never been executed is a document, not a plan.

| Exercise | Frequency | Success criterion |
|---|---|---|
| Restore a table from Time Travel | Monthly | Under 15 minutes, data verified |
| Rebuild CORE from RAW in a clone | Monthly | Under 2 hours, DQ suite matches expectations |
| Region failover, non-production | Quarterly | Under 30 minutes, smoke test green |
| Chaos: kill a worker in UAT | Monthly | No client-visible error |
| Chaos: block Snowflake from UAT | Quarterly | 503 with `retryable`, breaker opens, alert fires |
| Chaos: fail the AI provider in UAT | Quarterly | Degradation visible, no 500s |
| Credential rotation rehearsal | Quarterly | No outage |

The fault-injection hooks in the mock services (`?__fault=timeout|error|throttle|flaky`)
exist so the last three can be exercised locally and in CI, not only in UAT. The
integration suite uses them.

## 8. Capacity and scaling

| Dimension | Approach | Limit |
|---|---|---|
| API throughput | Horizontal: more CloudHub replicas, stateless workers | Warehouse concurrency |
| Warehouse concurrency | Multi-cluster `ACME_INTEGRATION_WH`, max 3 | Cost |
| Query performance | Cluster keys on the large tables; the API reads a materialised 360 rather than joining | Data volume |
| Transformation | Larger `ACME_TRANSFORM_WH` for the batch window only | Cost |
| AI throughput | Bulkhead + provider quota | Provider rate limit and budget |

Scaling out the API tier without scaling the warehouse simply moves the queue.
The materialised Customer 360 is what keeps warehouse concurrency from being the
first limit reached, a single-row lookup on a clustered table, and not an
eight-table join per request.

## 9. What is not covered

- No formal business impact analysis, so the RTO and RPO figures have no
  business sign-off behind them.
- Neither the failover nor the recovery runbooks have been executed.
- No load test has been run; the throughput figures are estimates.
- Source system recovery is out of scope. Each source owns its own DR, and this
  platform's plan assumes they have one.
