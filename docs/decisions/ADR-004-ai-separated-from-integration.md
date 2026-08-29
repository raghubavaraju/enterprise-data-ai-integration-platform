# ADR-004 / AI as a separate service, with no source-system access

**Status:** Accepted / **Date:** 2026-08 / **Decider:** Data & AI Architect

## Context

The platform must produce customer summaries, churn explanations, next-best
actions, sentiment and grounded answers. MuleSoft has AI connectors; Snowflake
has Cortex; the AI capability could plausibly live in either, or in its own
service.

Underneath the placement question is a more consequential one: **what may the
model read?**

## Problem

Where does generative AI live, and what data access does it get?

## Options considered

### A. AI inside the Mule flows

A Mule flow calls an LLM connector directly and shapes the response.

- **For:** No new deployable. Reuses existing patterns and monitoring.
- **Against:** A generative call has a completely different profile from an
  integration call: 5–20 seconds instead of 200 ms, a per-call cost, and a
  failure mode where the service is up and the output is still unusable. Sharing
  a runtime means a model slowdown consumes worker threads that customer lookups
  need. Prompt versioning, evaluation and grounding logic in DataWeave is the
  wrong tool for the job. And AI governance becomes indistinguishable from
  integration monitoring.

### B. AI entirely inside Snowflake (Cortex, called from SQL)

- **For:** Data never leaves the account. No new service. Simple.
- **Against:** Prompt engineering, retrieval orchestration, guardrails and
  evaluation in SQL and stored procedures are hard to test and harder to change.
  It also couples the AI capability to Snowflake permanently, which forecloses
  the provider swap that is certain to be asked for.

### C. An LLM with tools/function-calling over the source systems

The agentic approach: give the model a set of tools and let it decide what to
query.

- **For:** Flexible. Handles questions nobody anticipated.
- **Against:** This is the option to argue against most carefully, because it is
  the fashionable one.
  - **Blast radius.** A prompt-injection bug becomes a data exfiltration path.
    The attacker is not a hacker with credentials; it is a customer typing into a
    support form.
  - **No point-in-time correctness.** An explanation generated against live data
    cannot be reproduced tomorrow, so it cannot be audited or disputed.
  - **Unbounded PII exposure.** Whatever the model can query, it can put in an
    answer, and answers are displayed and stored.
  - **Operational coupling.** Generative traffic on an OLTP system competes with
    the transactions that system exists to serve.
  - **Unbounded cost.** A model that decides how many calls to make decides how
    much to spend.

### D. A separate AI service reading a curated, PII-free, point-in-time view (chosen)

- **For:** Independent scaling, deployment, rate limiting and failure isolation.
  Prompts, guardrails and evaluation in code that can be unit-tested. A thin
  provider interface, so Cortex, OpenAI or Bedrock is a configuration change.
  Data access is narrow and named. Everything is auditable.
- **Against:** Another deployable. A network hop. Bounded by what the curated
  view exposes, so a really novel question needs a schema change rather than
  the model figuring it out.

## Decision

**Option D.** A separate AI service that reads `AI.V_CUSTOMER_AI_CONTEXT` and
`AI.V_CUSTOMER_SUPPORT_CONTEXT` **through the data platform's API**, and has no
path to any source system.

Three specifics that matter more than the placement:

1. **The AI-safe view has no direct identifiers in it.** Not filtered, absent.
   No code path can leak a name or an e-mail by omitting a filter, because there
   is no filter to omit.
2. **The service cannot execute arbitrary SQL.** It reads named views and invokes
   three named, parameterised write operations. A service that can run arbitrary
   SQL is one prompt-injection bug away from being an exfiltration tool.
3. **Generated content is never a system of record**, and is never fed back as
   model input without human approval. Otherwise a hallucination becomes a fact
   by citation.

## Consequences

**Positive**

- A model outage degrades the AI endpoints and nothing else. Analytics and churn
  scores are deterministic and unaffected.
- Generative spend is attributable per client and hard-capped by a resource
  monitor on its own warehouse.
- Prompts, guardrails and evaluation are ordinary code with ordinary tests, and
  the evaluation suite is a CI gate.
- Swapping providers is a configuration change; the pipeline is unchanged.
- Every call is audited. Successes, blocks and errors. Which is what makes the
  post-incident questions answerable.

**Negative**

- Another service to deploy, monitor and secure.
- A network hop on the generative path, which is noise against a multi-second
  model call.
- The model can only answer what the curated view supports. Adding a fact is a
  schema change plus a prompt version bump, which is slower than an agent
  discovering it, and is the intended trade.

**Neutral**

- The service is Python and not Mule. That is a deliberate tool choice for
  prompt and evaluation work, and it is why the AI service is identical in local
  and cloud mode while everything else has a Mule counterpart.

## Alternatives reconsidered

Option C is right for an internal analyst tool over non-sensitive data with a
human in the loop for every query. It is not right for a capability whose output
is shown to customer-facing agents and stored as an audit record.

Option B remains attractive for the *inference* step, and is the recommended
production provider, `AI_PROVIDER=cortex`. The distinction is that Cortex
becomes the model provider behind this service, not a replacement for it. The
orchestration, grounding, guardrails and evaluation stay in code.

## What would make us revisit this

- A strong requirement for open-ended analytical questions over customer data,
  which would justify a constrained agentic tier, with read-only, view-scoped
  tools, per-query cost limits, and a human in the loop.
- Cortex gaining first-class prompt versioning, retrieval orchestration and
  evaluation, which would narrow the gap with Option B enough to reconsider.
