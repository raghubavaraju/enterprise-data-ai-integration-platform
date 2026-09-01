# Interview guide

Every answer below is defensible from something in this repository. Where an
answer would over-claim, it says so, a candidate caught over-claiming loses more
than they gained.

**Before you use this: know what you did and did not do.** Section 12 is the
list of things not to claim. Read it first.

---

## 1. Explaining the project

### "Explain this project in two minutes"

> Acme Retail has seven systems that each hold part of the truth about a
> customer, and twelve consumers that need combinations of them. Point-to-point
> integration means up to eighty-four connections, every consumer re-learning
> every source's quirks, and no way to introduce AI safely because there is no
> governed view for a model to read.
>
> I built three things. A MuleSoft API-led integration layer, system, process,
> experience, so a source system change touches one application instead of
> twelve. A layered Snowflake platform whose top layer is a materialised
> Customer 360 with every derived metric explainable in one sentence. And a
> separate AI service that reads a PII-free, point-in-time view and produces
> grounded, audited, reviewable insight, with no path to any source system.
>
> The whole thing runs on a laptop with no cloud account: 245 tests, including
> an AI evaluation gate and a data quality suite that finds eight deliberately
> planted defects. The Snowflake SQL in the repository is the SQL that runs
> locally, through a documented dialect shim, so the transformation logic can't
> silently diverge from what's tested.
>
> It's a proof of concept. It has never been deployed, and the README says so.

### "Explain it to a CTO"

Lead with cost, risk and time, not architecture.

> Today, adding a consumer of customer data is a project, because each one
> integrates directly with each source. This platform makes it a two-week piece
> of work, because the integration already exists and the new consumer gets an
> API over it.
>
> It also unblocks AI. The reason nobody has shipped AI over customer data is
> that there's nowhere safe to point it. This gives it a governed, PII-free view
> with an audit trail, human review on anything customer-facing, and a hard cap
> on spend. That turns "we can't do that" into a controlled experiment.
>
> The risks I'd want you to know about: Snowflake is consumption-priced, so cost
> discipline is a design obligation and I've built it in, separate warehouses,
> aggressive auto-suspend, resource monitors. And the AI is only as good as the
> governance around it, which is why nothing it produces can trigger a
> customer-facing action without a person approving it.

### "Explain it to a MuleSoft architect"

> Four Mule 4 applications across three layers. Experience shapes and masks;
> process orchestrates and owns the degradation policy; system normalises one
> source each. APIkit routers against RAML pulled from Exchange, so the contract
> is enforced at runtime rather than documented. One global error handler
> imported by all four, so there's one error envelope across the estate.
>
> Two things I'd want you to look at. First, the Snowflake System API uses the
> SQL API over HTTPS rather than JDBC: on ephemeral CloudHub workers a JDBC pool
> per worker keeps the warehouse awake and is invisible to the platform's own
> retry and circuit-breaker machinery. Second, the Customer 360 process flow uses
> `scatter-gather` with per-route `on-error-continue`, so one source being down
> degrades one field instead of failing the request. That's why the contract has
> `partial` and `degradedFields` in it.

### "Explain it to a data architect"

> Six schemas: RAW, STAGING, CORE, ANALYTICS, AI, GOVERNANCE. RAW is immutable
> and permissively typed so a source-side type change can't break ingestion.
> STAGING and ANALYTICS are disposable, rebuildable from RAW: which is what
> makes a cleansing bug a re-run instead of a recovery exercise.
>
> CORE.CUSTOMER is the only Type 2 dimension, because three questions need it:
> what segment were they in when they ordered, did they consent when we mailed
> them, and when did their tier change. Everything else is a transactional fact
> or an attribute nobody has asked the history of. Surrogate keys are
> deterministic hashes, not sequences, so a rebuild produces the same keys.
>
> Revenue is defined once. Engagement score is defined once and read by both
> Customer 360 and the AI feature store. Realised CLV and predicted CLV are
> separate columns and a test asserts they stay separate.

### "Explain it to an AI architect"

> The central decision is that the model has no access to operational systems.
> It reads `AI.V_CUSTOMER_AI_CONTEXT`, which has no name, e-mail, phone or date
> of birth in it: not filtered out, absent, so there's no filter to forget.
>
> The pipeline is: assemble grounding, redact and injection-check free text,
> render a versioned prompt with an explicit facts block, retrieve if the
> capability needs it, call the provider, validate the output, score it, route
> to a human if anything is off, and persist with the grounding snapshot.
>
> The output check I'd point at first: every number in the generated text must
> appear in the grounding block. It's cheap, mechanical, and it catches the
> hallucinations that cost money, because those are almost always numeric.
>
> Churn is a rule-weighted baseline, not a fitted model, because the dataset has
> no labelled churn outcome. Fitting against a synthesised label would produce an
> impressive AUC that means "recency predicts recency". The model *explains
> stored drivers*; it never decides why a customer might churn.

---

## 2. Integration architecture

### 1. Why MuleSoft?

The requirement is not routing, it is orchestration plus source normalisation
plus policy. A plain gateway gives policy and leaves the other two to each
consumer. MuleSoft gives all three, plus Exchange as a reusable asset catalogue
and API Manager for policies applied outside application code.

The honest caveat: the *pattern* is what matters. Everything here would work on
another integration platform. The MuleSoft-specific parts are the tooling and the
governance workflow.

### 2. Why API-led connectivity, rather than just building APIs?

Because each layer gets one reason to change. The experience layer changes when a
consumer's needs change, the process layer when the business process changes, the
system layer when a source changes.

The concrete claim: **replace the CRM, and one application changes.** The CRM's
`CustomerNumber` vocabulary exists in exactly one file
(`crm-customer-to-canonical.dwl`). If it appeared in three consumers, replacing
the CRM would be a co-ordinated release across all of them.

### 3. Isn't three layers over-engineering? It adds a hop.

It does, 15 to 30 milliseconds against an 800 ms budget. What it buys is that a
source change is bounded, orchestration exists in one place, and entitlement is
enforced once.

It *would* be over-engineering with two consumers and two sources. The layering
is justified by fan-out, and I'd say that explicitly rather than defend it as
universally correct.

### 4. Why not let the process API query Snowflake directly?

Then every process API needs a warehouse credential, a connection strategy and
knowledge of the schema, and a table rename becomes a multi-application change.
One system API is one blast radius. It also means there is one place to enforce
"no caller supplies SQL" and one place to hold the read-only credential.

### 5. Why the Snowflake SQL API instead of JDBC?

Four reasons, and the first is the one people miss. CloudHub workers are
ephemeral and horizontally scaled; a JDBC pool per worker means thirty mostly-idle
Snowflake sessions across three replicas, which keeps the warehouse from
auto-suspending, you pay for a warehouse kept warm by connections nobody is
using.

Second, a JDBC call is opaque to the platform's HTTP-level retry, timeout,
circuit-breaker and correlation-id machinery, so resilience has to be
re-implemented for that one connector. Third, statements can be submitted
asynchronously and polled, so a long query doesn't hold a worker thread. Fourth,
because the contract is HTTP, I could implement the same contract locally over
DuckDB, which is why the flow logic is identical in both modes.

The cost: results arrive as arrays of strings with a metadata block, so type
coercion is my job. I do it once, in `sql-result-to-rows.dwl`.

### 6. How do you stop an experience API from becoming a process API?

Review, because no linter can express it. The rule is: **a second outbound call
in an experience API means it belongs in the process layer.** It's in
`CONTRIBUTING.md` and the pull request template.

I'd rather be honest that this one is enforced by discipline than pretend there's
a check for it.

### 7. API or event, when would you use each?

An API when the caller needs an answer now about a specific record, needs to know
it succeeded, and needs strong consistency. An event when something happened and
an unknown set of consumers may care.

Both failure modes are bad. Events used for request/response means a
correlation-id chase every time someone asks a simple question. APIs used for
propagation means N consumers polling, or the publisher hard-coded to call N
consumers, which is the idea-to-point coupling one layer up.

I designed the event architecture and deliberately didn't build it, because the
dominant use case here is an agent opening a screen, and adding an
eventually-consistent path before the synchronous one is trusted doubles the
operational surface. ADR-005 lists the four preconditions for building it.

### 8. How would you version an API?

Major version in the URI, because it's visible in a log, a firewall rule and a
support ticket. Additive changes only within a major version. A breaking change
gets a new major, both run for a six-month deprecation window with `Deprecation`
and `Sunset` headers, and usage is tracked per client in Exchange.

Usage tracking is the part that makes it real. Without it, deprecation is a
request and the old version runs forever.

### 9. How do you handle a source system being down?

Degrade, and say so. The Customer 360 flow fetches concurrently with per-route
`on-error-continue`, so a failed route records itself in `degradedFields` and
returns an empty result and not failing the request. The response is 200 with
`partial: true`.

Three options exist: fail the whole request, silently return partial data, or
return what you have and name what's missing. The first leaves an agent with a
blank screen while a customer is on the phone. The second is worse, because the
agent can't tell "no orders" from "the order system is down".

There's a subtlety: a 404 on the churn score means "not scored yet", which is a
fact about the customer, not an outage, so it's *not* reported as degradation.
Crying outage over an absent record is how the partial flag becomes noise that
operations learns to ignore.

### 10. Retry versus resume versus continue versus propagate?

In Mule terms:

- `on-error-propagate`: the flow failed. The error reaches the caller and any
  transaction rolls back. Everything a client must know about.
- `on-error-continue`, the flow succeeded with a different payload. No rollback.
  Used where absence is legitimate, or where degraded is better than failed.
- `until-successful`: retry, for transient failures only. A 400 or 404 cannot
  succeed on retry; retrying only multiplies load.
- `raise-error`, translate a downstream error into a platform error type at the
  boundary, so error handling upstream is written against our taxonomy rather
  than the CRM's HTTP codes.

The one I'd emphasise: retry classification. Retrying a generative call is a
category error, because it's not idempotent from a cost perspective and a slow
response is usually a slow model, not a lost request.

---

## 3. Data architecture

### 11. Why Snowflake?

The workload is actually mixed: a 200 ms single-row API lookup and a multi-minute
batch transformation on the same data. Separated storage and compute means an
XSMALL warehouse serves the API while a SMALL one runs the batch, with no
interference and no copy.

Then: zero-copy cloning makes non-production effectively free and makes
point-in-time recovery a clone instead of a restore; governance is native rather
than bolted on; and Cortex keeps AI inference inside the account, which removes
the hardest question in the AI data protection assessment.

The trade: consumption pricing punishes carelessness, and there's real lock-in
around Cortex, Snowpark and the vector type.

### 12. Why three warehouses?

Cost attribution and interference. Mixing them means an interactive API call pays
for a batch-sized warehouse, and AI spend becomes unattributable. Separate
warehouses cost nothing when suspended, and they're what make a resource monitor
on the AI warehouse a meaningful control rather than a shared cap.

### 13. How did you design Customer 360?

Bottom-up from what a service-desk agent needs on screen, then checked against
the retention workflow and the AI grounding requirement.

Structurally: CORE holds conformed entities; three aggregate tables compute order,
support and engagement summaries; `CUSTOMER_360` joins them into one row per
customer with about 45 attributes.

The decisions worth defending are the derived metrics. Every one is explainable
in one sentence, because an unexplainable number in a customer-facing context is
a liability. Revenue is defined once. Engagement score is a weighted, capped sum
of six observable signals with documented weights: a business assumption, not a
fitted model, and I'd call it that. Realised CLV and predicted CLV are separate
columns because conflating them is how a forecast ends up quoted as revenue.

### 14. Why materialise it rather than use a view?

Latency, cost and reproducibility. The view version is an eight-table join with
window functions, seconds on an XSMALL at production volumes, and the 800 ms
budget is gone before masking. Cost would scale with read volume instead of data
volume. And an AI explanation generated against a view can't be reproduced,
because the number moves under it.

The trade is staleness, which is why `AS_OF_TIMESTAMP` is in every API response
and a timeliness DQ rule fails at 24 hours. Publishing the freshness makes
the trade-off honest.

Snowflake materialised views aren't an option here, they don't support joins,
multi-table aggregates or window functions, and this needs all three.

### 15. Why is only CUSTOMER a Type 2 dimension?

Because three questions need it and all three get asked: what segment was the
customer in when they placed that order, did they consent at the time we mailed
them, and when did their tier change. Consent history in particular is a
regulatory artefact, not an analytics nicety.

Everything else is either a transactional fact: immutable once complete, or an
attribute nobody has asked the history of. Historising everything "just in case"
produces a warehouse that is both expensive and unqueryable.

### 16. Walk me through your SCD2 implementation.

Change detection is a hash over tracked attributes only; audit columns are
excluded, so re-ingesting an unchanged record doesn't create a version. When the
hash differs, close the open row and insert a new one.

Two details I'd want you to check. `VALID_FROM` is the **source** update
timestamp, not the load timestamp. Using load time makes history depend on when
the pipeline happened to run, which makes every point-in-time answer wrong after
a backfill. And `VALID_TO` for the open row is `9999-12-31`, never NULL, because
a NULL forces every downstream predicate to special-case it and someone always
forgets.

`SALES_ORDER.CUSTOMER_SK` points at the version current at the order date. That
one column is the payoff of the whole design.

Three invariants are tested: one current version per customer, no overlapping
windows, no open row with a past `VALID_TO`.

### 17. Why hash surrogate keys instead of sequences?

A sequence key depends on insert order, so a rebuilt warehouse produces different
keys and every stored reference silently breaks. A hash key is computable
independently in any layer, in any order, after any reload, which is what makes
"STAGING and ANALYTICS are disposable" a true statement and not an aspiration.

### 18. How would you implement CDC?

Debezium or the source vendor's log reader writes change events to an object
store; Snowpipe ingests continuously into a RAW change table; a stream over that
table drives a task that MERGEs into STAGING and then CORE.

The SCD2 MERGE is written in `05-pipelines/03-incremental-scd2-merge.sql`. It's
marked Snowflake-only because DuckDB has no MERGE, so the local build uses the
full-rebuild path, which produces the same end state and doubles as the recovery
path when CORE is corrupted.

Being straight about it: the CDC path is designed and written, not run. What runs
is watermark-based incremental and full-snapshot ingestion.

### 19. Why do watermarks only advance after a commit?

Because a failed run must re-read instead of skip. Advancing the watermark on
read is the single most common cause of silent data loss in an incremental
pipeline, and it's invisible until someone reconciles counts months later.

### 20. How do you handle identity resolution?

Two stages. Exact: collapse replays of the same business key, keeping the latest,
a source replay is not a defect. Fuzzy: group by a match key, which is the
lower-cased e-mail when it's valid and a name-plus-date-of-birth key when it
isn't, then elect a survivor.

Survivorship is earliest-created-wins, because that record is the one other
systems already reference: promoting a newer duplicate breaks external
references to fix an internal one.

The suppressed duplicate is *recorded*, not discarded. Silently collapsing
duplicates is how a duplicate-customer problem becomes invisible rather than
solved.

Production would add a probabilistic tier with a review queue for the uncertain
band. The deterministic tier here is the honest floor.

### 21. How do you handle data quality?

Rules are data, not code. Rows in `GOVERNANCE.DQ_RULE`, so a steward can add one
without a deployment and the scorecard renders itself. Two executors read the same
rows: a Snowflake stored procedure and a local Python runner.

Three severities with three behaviours. BLOCKING quarantines the row and lets the
rest of the load succeed. WARNING loads it, flags it, and puts it on the steward's
scorecard. INFO is trended only.

The failure mode to avoid is making everything BLOCKING. A platform that rejects
a day's orders over two bad postcodes doesn't get trusted with the next system.

Rejected rows go to a quarantine table with the rule, the reason, the payload and
the correlation id, never deleted. Silent data loss is what destroys trust in a
platform.

### 22. How do you know your data quality suite actually works?

Because the sample data contains eight intentionally planted defects and a test
asserts the exact outcome: 14 PASS, 5 WARN, 3 FAIL. A DQ suite that always
reports green is indistinguishable from one that isn't running.

### 23. What about lineage?

`GOVERNANCE.LINEAGE_EDGE` holds declared lineage. 25 edges including the two that
leave the warehouse and enter MuleSoft. Snowflake's `ACCESS_HISTORY` gives observed
lineage. The gap between them is the control: observed-but-not-declared is
undocumented coupling; declared-but-not-observed is dead code.

Most lineage tooling stops at the database boundary, which is where the
interesting question lives, where does this number on the agent's screen come
from?

---

## 4. AI architecture

### 24. Why isn't the AI inside the Mule flows?

Different latency profile. 5 to 20 seconds against 200 ms. Different cost model
, per call. Different failure mode, the service is up and the output is still
unusable. Different governance, every call audited, some outputs needing human
approval.

Sharing a runtime means a model slowdown consumes worker threads that customer
lookups need. And prompt versioning, grounding and evaluation in DataWeave is the
wrong tool for the job.

### 25. Why doesn't the model have tool access to the source systems?

This is the agentic pattern, and I'd argue against it here for four reasons.

Blast radius: a prompt-injection bug becomes a data exfiltration path, and the
attacker isn't a hacker with credentials, it's a customer typing into a support
form. No point-in-time correctness: an explanation generated against live data
can't be reproduced tomorrow, so it can't be audited or disputed. Unbounded PII
exposure: whatever the model can query, it can put in an answer, and answers are
displayed and stored. Unbounded cost: a model that decides how many calls to make
decides how much to spend.

It's the right pattern for an internal analyst tool over non-sensitive data with
a human in the loop for every query. It's not right for output shown to
customer-facing agents and stored as an audit record.

### 26. How do you prevent hallucination?

Ranked by how much they actually help:

Ground on facts, not retrieval alone: most enterprise "hallucination" is the
model filling a gap the pipeline left. Give it nothing to paraphrase, labelled
key/value facts, not prose. Check every number in the output against the
grounding block, which is cheap and catches the failures that cost money. Let
retrieval return nothing, via a similarity floor, so "I don't know" is reachable.
Constrain the output shape. JSON with a closed enum can't express an invented
action. Explain stored values and not re-deriving them. Low temperature plus a
consistency check. And route the uncertain to a human.

One detail worth mentioning: a NULL fact renders as "NOT AVAILABLE", never as
zero or `nan`. A number-shaped token for a missing fact is worse than silence,
because the model repeats it as data. I hit that bug and fixed it; there's a test
for it.

### 27. How do you evaluate AI output?

Five deterministic metrics: groundedness, relevance, safety, consistency and PII
leakage, with thresholds that are the CI gate instead of a report. A change that
makes generation less grounded or less safe fails the build.

The suite runs every capability over a spread of customers chosen to include the
edge cases. The customer with no orders, the one with the worst satisfaction, the
highest-risk cohort, because the edges are where a pipeline produces confident
nonsense.

An LLM-as-judge evaluator is the right addition with a real provider, and
`EVALUATOR = 'LLM_JUDGE'` is already a value in the table. It's not a substitute
for the deterministic checks, because a judge model shares the failure modes of
the model it judges.

### 28. How does your RAG work, and what's the hard part?

Knowledge article to document to chunk to embedding to vector search to context
to grounded answer with citations.

The hard parts are two. **Chunking on paragraph boundaries, not character
counts**, slicing at an offset separates a policy rule from its exception, which
is how a RAG system cites "returns within 30 days" while omitting "except…".
And **the similarity floor**. Without it, top-k always returns k chunks, so a
question the knowledge base doesn't cover still gets three confident-looking
extracts. With it, retrieval can return nothing and the refusal path fires. There's
a test that asks an out-of-scope question and asserts the refusal.

Search runs in the warehouse, so the corpus never leaves it: only the query
vector goes in and the top-k chunks come out.

### 29. How do you handle prompt injection?

The realistic attack arrives through the data: a customer types instructions into
a support form. So detection happens on the way in, on the case text, and the
content is replaced with a withheld marker, but the case id, type and status
still appear, because silently dropping the record would hide a real support case
from the analyst.

Detecting injection also forces human review of whatever is generated, however
clean it looks, because a record carrying instruction-like content is a signal
that something odd is happening to this customer's data.

The prompt also states that text in the facts block is data, not instruction, and
the facts block is key/value pairs rather than prose so there's less surface.

### 30. What's your human-in-the-loop policy?

Mandatory when the guardrails failed, when injection was detected, when the
capability is `NEXT_BEST_ACTION`, or when confidence is below threshold.
Everything else is auto-approved.

That last part is deliberate. **A review queue nobody reads is worse than no
queue**, because it manufactures the appearance of oversight: so the queue is
kept small enough to actually be read, and its depth and age are monitored.

### 31. Why a rule-based churn score rather than a model?

There's no labelled churn outcome in the data. Churn in retail isn't an event,
it's the absence of one, which needs a definition nobody has agreed.

If I synthesised a label like "no order in 365 days" and fitted a classifier,
recency would dominate and I'd report an AUC near 1.0 that means "recency predicts
recency". Worse, a reported AUC invites the business to trust the score more than
it deserves.

So: seven bounded contributions, weights summing to one, fully explainable, with
the top three drivers stored alongside the score. `SCORING_METHOD = 'RULE_BASED'`
is a column, so the method is queryable, and the data dictionary says in words
that it isn't a calibrated probability.

The path to a real model is short: the feature store is the training set, and
`SCORING_METHOD` lets both run side by side until the model beats the baseline.

### 32. What happens if the AI provider is unavailable?

Nothing important. The circuit breaker opens, the generative endpoints return a
deterministic degraded message, and the analytics and churn score are unaffected
because they're computed in the warehouse.

That's the design principle: **degrade in the direction of the deterministic.**
The narrative can be lost without losing the score; the score can be lost without
losing the profile.

### 33. How do you control AI cost?

Generation is opt-in per request, so the common Customer 360 call costs nothing
generative. A 24-hour insight cache. Idempotency keys, so a client retrying on
timeout isn't billed twice. A bulkhead of four concurrent calls. No automatic
retry. A separate warehouse with a resource monitor that hard-stops at quota. And
every call audited with an estimated cost and a client id, so spend is
attributable and chargeable.

---

## 5. Security

### 34. How would you secure MuleSoft?

Policies at the gateway, not in application code, a policy in code ships with the
release and can be removed by a developer; a policy at the gateway is owned by the
platform team and applies to every version.

JWT validation with RS256 against a rotating JWKS, because a shared HMAC secret
would have to be distributed to every validating application, which makes rotation
a coordinated outage. SLA-based rate limiting, so the noisiest consumer can't
degrade everyone else. Spike control on the AI API specifically. Client id
enforcement, so every call is attributable. IP allow-listing on the process and
system layers, which have no public endpoint at all. Header removal on the way
out. mTLS between layers.

And the caller's token is not forwarded inward, the experience layer makes the
entitlement decision and calls downstream with the platform's credential.
Forwarding a client token would mean every internal API re-implementing the same
decision, differently.

### 35. How would you secure Snowflake?

Key-pair JWT authentication: no password exists, so there's nothing to paste into
a support ticket, and rotation is a key swap and not a coordinated change.
A read-only role for the integration identity. A network policy limiting the
account to the CloudHub egress range and the corporate VPN. Dynamic masking on
every PII column, keyed on the executing role, so an analyst querying directly
sees the same masked values as an unentitled API consumer. A row access policy for
regional segregation. Roles granted to roles, never to users.

And defence in depth: the System API refuses mutating SQL even though its role
couldn't execute it, and the role is read-only even though nothing upstream can
issue a write. Either control alone is a single point of failure.

### 36. How do you handle PII?

Three distinct mechanisms, deliberately not conflated.

Masking at the experience layer, decided from the token, e-mail keeps the first
character and domain, phone keeps four digits, the given name is kept and the
family name masked, date of birth generalised to the year. Keeping the given name
is a deliberate compromise: masking that makes the record unusable to an agent is
masking that gets switched off.

Masking policies in Snowflake, so the same rules apply to an analyst querying
directly.

And redaction before the trust boundary, plus an AI-safe view that has no
identifiers in it at all: absent by construction, so there's no filter to forget.

Date of birth is treated as a quasi-identifier, because with a postcode it
re-identifies most people.

### 37. Where do secrets live?

The repository contains the *name* of every secret and the value of none.
Non-sensitive settings in committed YAML; sensitive values in encrypted
`-secure.yaml` files that aren't committed, with a committed `.example` template
so a missing property fails code review rather than a 3 a.m. deployment. The
decryption key is a Runtime Manager secure property injected at deploy.

CI runs gitleaks plus a repository-wide pattern check and fails the build.

### 38. What's your threat model?

Six threats drive the controls: bulk PII exfiltration through an API, arbitrary
SQL reaching the warehouse, prompt injection through customer text, credential
leakage, excess generative spend, and privilege creep.

Each has a primary control and a backstop. For SQL: the System API accepts no SQL
at all, and the role is read-only. For injection: input neutralisation, and output
guardrails plus forced review. For spend: spike control and idempotency, and a
resource monitor with a hard stop.

Designing controls without naming threats produces a checklist.

---

## 6. Operations

### 39. How would you monitor this?

One correlation id, adopted from the caller and propagated on every hop, used as
the Snowflake `QUERY_TAG` and stored in the AI audit table. That's the design
goal: one id finds the API call, three layers of flow logs, the warehouse query
and the AI generation.

The `QUERY_TAG` join is the part most implementations lack. It turns "the API was
slow" into "the query scanned 40 GB because the predicate didn't prune".

Beyond that: structured JSON logs with a fixed field contract, technical and data
and AI and business metrics, health endpoints that expose circuit-breaker state,
and alert routing with severities. Payload logging is off in every environment
including development, because the habit is what matters.

### 40. What are the RTO and RPO, and why?

They're architectural assumptions, not measured or agreed SLAs, and I'd say that
before quoting them.

The APIs have RPO zero because they hold no state, all state is in Snowflake or a
source, and the object stores hold only idempotency keys and breaker flags, both
safe to lose. Corrupt CORE is a 2-hour re-run rather than a restore, because CORE
is rebuildable from RAW; if it were the only copy the number would be much larger.
Region failure is 30 minutes on DNS failover. Full account loss is 4 hours with a
1-hour RPO from the replica.

The end-to-end availability target is 99.5%, *lower* than any single component's
99.9%, because it's compound. Stating that is the point: assuming a chain is as
available as its parts is how availability promises get broken.

### 41. What happens if Snowflake is unavailable?

Circuit breaker opens after five failures, the read APIs return 503 with
`retryable: true` and a `Retry-After`, and the service desk falls back to querying
the CRM directly for basic profile data.

Failing fast matters here: hammering a degraded Snowflake with retries turns a
partial outage into a full one and burns credits.

### 42. How do you control Snowflake cost?

Three warehouses sized for their workload with aggressive auto-suspend, 60
seconds on the integration warehouse, because API traffic is bursty. Statement
timeouts, so a runaway query is bounded. Resource monitors, with a hard stop on
the AI warehouse. A materialised Customer 360, so an API read is a primary-key
lookup instead of an eight-table join per request. Cluster keys for partition
pruning. And the SQL API rather than JDBC, so idle connections don't keep the
warehouse awake.

### 43. How would you take this to production?

Ordered by what blocks what: Snowflake account with roles, masking and network
policy; key pair generated and stored; API instances in API Manager with policies
applied; clients registered with SLA tiers; alerting routed to a real rotation;
DR runbooks executed at least once in UAT; a load test at twice expected peak;
penetration test; data protection assessment, especially for any external AI
provider; data owners named; and the AI review queue staffed with an agreed
response time.

The checklist is in `docs/deployment.md`. The two people usually forget are the
DR rehearsal and staffing the review queue.

### 44. How does this scale to 8 million customers?

Cluster keys on the large tables for partition pruning. Interactions aggregated on
ingest and not stored raw in CORE, because nobody queries individual email
opens. The API reads a materialised row, so warehouse concurrency isn't the first
limit reached. Multi-cluster warehouse for API bursts. And the switch from a full
`CUSTOMER_360` rebuild to a stream-driven incremental MERGE, which is a change to
one script: triggered by cost, not elegance.

Being straight: none of this has been load-tested. It's sizing reasoning, not
measurement.

### 45. How would this evolve toward Salesforce Data 360?

`CORE.CUSTOMER` maps to the Individual DMO; the deterministic match rules map to
an identity resolution ruleset; engagement score, CLV and predicted CLV become
calculated insights; system APIs are replaced by native connectors where they
exist and stay where they don't.

The experience layer never changes, which is the idea of the layering, it makes
the move a project and not a programme.

What wouldn't move: the integration layer for systems Data Cloud doesn't reach,
the DQ rule catalogue and quarantine mechanism, and the AI governance apparatus.
Those are platform-independent and the most expensive parts to rebuild.

---

## 7. Testing and engineering

### 46. What did you test, and why those things?

245 tests in five suites. Unit tests for masking, guardrails, resilience
primitives and the SQL dialect rules. Data tests for the warehouse invariants,
one current version per customer, no overlapping SCD2 windows, revenue consistent
between the summary and the recomputation, engagement score identical in all three
places it appears. API tests for contracts, auth, error shapes and entitlement
masking. AI tests for the evaluation gate and injection resistance. Integration
tests for the cross-process behaviour.

The ones I'd point at: the data quality test that asserts the exact expected
outcome on eight planted defects, and the SQL-injection test on the System API
that asserts the payload appears in the bind parameters and *not* in the statement
text.

### 47. Why can this run without a Snowflake account?

Because a repository nobody can run is a repository nobody can check. The local
warehouse executes the same `.sql` files through a small, documented dialect
rewrite; Snowflake-only constructs are detected and skipped with the reason
printed. There's no second copy of the transformation logic to drift.

The limitation is real and stated: MERGE, streams, tasks, Snowpipe, Cortex,
masking and row access policies aren't exercised locally. The right addition is a
nightly job against a real account running the full script set.

### 48. What would you do differently?

Three things.

I'd have built the local warehouse first. I wrote a lot of SQL before I could run
any of it, and the first build surfaced several bugs at once.

I'd have made the AI service read through the data platform's API from the start.
I got there because DuckDB permits one writer, which forced it: but it's the
better architecture in cloud mode too, and arriving at it by accident is luck, not
design.

And I'd have written the data dictionary generator earlier. Doing it late meant a
gap between what the schema says and what's curated, which the generator now marks
honestly as inferred: but curating as I went would have been better.

---

## 8. Questions to ask them

Interviews go both ways, and these signal that you think about the operating
model rather than just the diagram.

1. Who owns a data definition when two teams disagree, and how is that resolved
   today?
2. What's the actual latency budget for the customer view, and where did that
   number come from?
3. Is there a labelled churn outcome, or would we be defining one?
4. What happens today when a source system is down: what does the agent see?
5. Who reviews AI output, and what's their response time commitment?
6. Is the API estate contract-first, or are specs generated from implementations?
7. What's the cost model, is anyone accountable for the consumption bill?
8. How is a deprecation actually completed, and not announced?

---

## 9. Numbers worth remembering

| Fact | Number |
|---|---|
| Tests | 245, passing, ~13 s |
| Coverage | 81% |
| Data quality rules | 22, across all six dimensions |
| Planted defects found | 8 (3 FAIL, 5 WARN) |
| Mermaid diagrams | 38, all render-validated |
| API specifications | 6 OAS + a full RAML tree |
| Mule applications | 4, across 3 layers |
| Snowflake schemas | 6 |
| Customer 360 attributes | ~45 |
| Churn drivers | 7 weighted, top 3 stored |
| AI capabilities | 5 |
| ADRs | 8 |
| Local build time | ~5 s, no cloud account |

---

## 10. The three hardest questions

### "This is a portfolio project. What's actually hard about it?"

> Three things were really hard.
>
> Making the same SQL run in both Snowflake and DuckDB without a second copy.
> The temptation is to write a general-purpose translator; that's worse, because
> it produces subtly different results instead of an error. The discipline was
> keeping the rewrite list small and skipping loudly.
>
> The degradation policy. It's easy to say "degrade gracefully" and hard to
> decide what "gracefully" means per dependency, and to distinguish "this
> customer has no loyalty account" from "the loyalty platform is down", which
> look identical at the source.
>
> Making the AI honest. Not making it produce text: making it produce text where
> every number is traceable, every claim is checkable, and a missing fact renders
> as "NOT AVAILABLE" instead of a plausible zero.

### "What's the weakest part?"

> The churn score. It's a heuristic with weights I chose, and no amount of
> engineering around it changes that. It's honest about being one, and the
> architecture makes replacing it cheap, but if you asked me which part would not
> survive contact with a real business, it's the weights.
>
> Second: the Mule applications have never been deployed. The XML is real and
> reviewable, and the Python stand-in proves the behaviour, but "it runs on
> CloudHub" is not a claim I can make.

### "How much of this would survive at real scale?"

> The layering, the governance model, the data quality mechanism and the AI
> pipeline would survive unchanged: they're structural.
>
> What breaks: the full `CUSTOMER_360` rebuild becomes incremental. Interactions
> at 500 million a year need a different storage strategy than CORE. The
> deterministic identity resolution needs a probabilistic tier with a review
> queue. And the local warehouse stops being able to represent enough of the
> pipeline to be useful, which is when the nightly real-account job stops being
> optional.

---

## 11. Two-minute whiteboard

Draw this, in this order:

```
1. Consumers        [service desk] [marketing] [BI]
2. Experience              ↓
3. Process           orchestrate + degrade
4. System            one per source ← the reusability claim
5. Snowflake         RAW → STAGING → CORE → ANALYTICS → AI
6. AI service        reads the AI-safe view only  ← the safety claim
7. Correlation id    one arrow through all of it  ← the operability claim
```

Three claims, one per arrow. If you only get three sentences, use them on:
a source change touches one application; the model can't reach a source system;
one id traces everything.

---

## 12. What NOT to claim

Say these before you are asked. Being caught over-claiming costs more than the
claim was worth.

**Do not say:**

- that this ran in production, or served real customers, or was used by a team
- that you deployed the Mule applications to CloudHub, they have never been
  deployed
- that you built this at any employer, or that it reflects any employer's systems
- that the churn model is trained, or quote an accuracy figure
- that the platform handles millions of records, it holds 60 customers and 351
  orders
- that any performance number is measured, none are
- that Cortex, Snowpipe, streams, tasks, masking policies or row access policies
  have been executed, they are written and reviewable, not run
- that the RTO, RPO or availability targets are agreed SLAs

**Do say:**

- "This is an independent architecture and proof of concept."
- "It runs end to end locally; here is the test suite and here is what it proves."
- "The Snowflake-only parts are written and reviewable, and I can show you which
  ones the local build skips and why."
- "These targets are architectural assumptions I made, not measured numbers."
- "My production experience is X; this project is where I worked through Y."

The last one is the important one. A proof of concept that is presented as a
proof of concept, with its limitations volunteered and not extracted, is
worth more in an interview than a production system described vaguely.
