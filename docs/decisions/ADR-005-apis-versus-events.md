# ADR-005 / APIs now, events designed but not built

**Status:** Accepted / **Date:** 2026-08 / **Decider:** Integration Architect

## Context

Two integration paradigms are available, and both have legitimate uses here:

- **Request/response**, a consumer needs an answer now about a specific record.
- **Event-driven**, something happened and an unknown set of consumers may care.

The platform's dominant use case is a service-desk agent opening a customer
record: synchronous, specific, and needing an answer within a second. But there
are real propagation needs too: a consent change must reach marketing quickly,
and a nightly Customer 360 rebuild means "has an open case" can be a day stale.

## Problem

Which paradigm, for which interactions, and how much do we build now?

## Options considered

### A. APIs only, permanently

- **For:** One paradigm to operate, monitor and reason about. Strong consistency.
  Simple failure semantics.
- **Against:** Propagation via API means either N consumers polling, or the
  publisher hard-coded to call N consumers. The second is the point-to-point
  coupling this platform exists to remove, re-created one layer up.

### B. Event-driven first, APIs as a thin layer

- **For:** Loose coupling. Natural fan-out. Replay. Good fit for a
  high-throughput, eventually-consistent estate.
- **Against:** The dominant use case is a synchronous read. Serving it from an
  event-sourced projection adds eventual consistency to an interaction that does
  not tolerate it: an agent refreshing because the customer's order "hasn't
  appeared yet" is a worse experience, not a better one. It also doubles the
  operational surface: a bus, consumer groups, dead-letter triage, schema
  registry and replay tooling, all before the synchronous platform is trusted.

### C. Both, built together

- **For:** The right tool for each interaction from day one.
- **Against:** Two paradigms to prove simultaneously. Twice the operational
  learning curve at exactly the moment the platform has the least credibility.

### D. APIs now; events designed, specified and deferred (chosen)

- **For:** Delivers the dominant use case first. The event design exists, event
  catalogue, envelope, topology, delivery guarantees, failure handling, so it is
  a build, not a discovery. Decisions that are expensive to retrofit (partition
  key in the envelope, idempotent consumers, canonical vocabulary published by
  the system layer) are made now at no cost.
- **Against:** Freshness stays at the batch cadence until it is built. Some
  design work is done that is not yet exercised, and unexercised design ages.

## Decision

**Option D.** APIs are implemented; the event architecture is fully specified in
[event-driven-architecture.md](../event-driven-architecture.md) and is not built.

The distinction that governs future work:

| Use an API | Use an event |
|---|---|
| The caller needs an answer now | Nobody is waiting |
| The caller needs a specific record | Something happened others may care about |
| The caller must know it succeeded | The publisher should not care who listens |
| Strong consistency is required | Eventual consistency is acceptable |

**Recommended bus when it is built: Anypoint MQ, designed for Kafka.** The
volumes that justify Kafka are in the interaction domain, which is an aggregated
analytical feed instead of an operational event. Operational events here are
thousands per day. Designing for Kafka: a partition key in the envelope, no
reliance on queue semantics Kafka lacks, idempotent consumers: costs nothing now
and is expensive to retrofit.

## Consequences

**Positive**

- The team proves one paradigm before adding a second.
- The event design informs the API design today: system APIs would publish, so
  canonical vocabulary is already enforced at that boundary, and the correlation
  id is already the join across both paradigms.
- The four preconditions for building it are written down, so "when do we do
  events?" has an answer.

**Negative**

- `CUSTOMER_360` is up to 24 hours stale. Published as `AS_OF_TIMESTAMP` and
  enforced by a timeliness rule, so it is visible rather than surprising.
- Consent propagation is batch, which is the weakest point of the current design
  and the first thing events would fix.
- A written-but-unbuilt design decays. It needs revisiting when it is picked up
  and not being treated as a finished specification.

**Neutral**

- Some SCD2 machinery, the tracked-attribute hash, the stale-update rejection,
  is exactly what an idempotent event consumer needs. That is not a coincidence:
  an event consumer writing to an SCD2 table is the batch loader with a different
  trigger.

## Alternatives reconsidered

Option B is right for an estate whose dominant interactions are asynchronous,
order processing, fulfilment, settlement. Acme's are, for this platform, a person
looking at a screen.

## What would make us revisit this

Build it when **all four** are true:

1. The synchronous platform is in production and trusted.
2. A named consumer has a real sub-hour freshness requirement.
3. Dead-letter triage is staffed with an agreed response time.
4. Idempotency and deduplication are proven in the consumers.

The first candidate events are `ConsentChanged` (regulatory latency),
`SupportCaseCreated` and `OrderCompleted` (the two fields agents notice are
stale).
