# ADR-001 / API-led connectivity with three layers

**Status:** Accepted / **Date:** 2026-08 / **Decider:** Integration Architect

## Context

Acme Retail has seven systems holding parts of the customer picture and roughly
twelve consumers that need some combination of them. The current estate is
point-to-point: the service desk built an extract from the CRM, marketing built
another, finance built a third, and each of them independently learned that the
CRM calls the business key `CustomerNumber`.

The arithmetic is the problem. Seven sources and twelve consumers is up to
eighty-four connections, each one a place a schema change can break something,
and each one a place an entitlement decision is made differently.

A new requirement, a unified customer view feeding an AI capability. Would add
several more.

## Problem

How should integration be structured so that adding a consumer is cheap, and
replacing a source system is a bounded change and not a programme?

## Options considered

### A. Point-to-point, continued

Each consumer integrates directly with each source.

- **For:** No new infrastructure. Fastest for the first consumer.
- **Against:** O(n×m) connections. Every consumer re-learns every source's
  quirks. A source replacement touches every consumer. Entitlement and masking
  are implemented n times, differently. This is the status quo, and it is the
  reason the unified view does not exist.

### B. A single canonical "customer service"

One API in front of everything.

- **For:** Simple to describe. One thing to call.
- **Against:** It becomes the bottleneck and the single point of change. Every
  consumer's requirements accumulate in one contract, so it either grows query
  parameters until it is unreadable, or it forces every consumer to accept one
  shape. There is no boundary at which a source system's change stops.

### C. A plain API gateway over the sources

Kong, Apigee or similar, exposing each source through a managed endpoint.

- **For:** Policy enforcement, rate limiting, a developer portal. Lighter than a
  full integration platform.
- **Against:** A gateway routes and polices; it does not orchestrate, transform
  or aggregate. Assembling a Customer 360 from five sources still has to happen
  somewhere, and with a bare gateway that somewhere is each consumer. It solves
  the security problem and leaves the coupling problem.

### D. API-led connectivity: system, process, experience (chosen)

Three layers, each with one reason to change.

- **For:** Source quirks absorbed once. Orchestration in one place. Consumer
  contracts stable across source and process change. Reuse is structural rather
  than aspirational.
- **Against:** More applications to deploy and monitor. An extra network hop
  (15–30 ms). It needs discipline: without review, an experience API grows
  orchestration and the layering stops being real.

## Decision

**Option D.** Three layers, with explicit rules about what each may contain:

| Layer | Changes when | Must not contain |
|---|---|---|
| Experience | A consumer's needs change | Orchestration, source knowledge |
| Process | The business process changes | Source field names, connection details |
| System | A source system changes | Business logic, cross-source joins |

The claim being made is narrow and checkable: **when the CRM is replaced,
exactly one application changes.** That is the test, and it is what separates
API-led connectivity from a diagram with three boxes in it.

## Consequences

**Positive**

- Adding a consumer means writing an experience API over process APIs that
  already exist, days, not a project.
- The CRM's `CustomerNumber` vocabulary exists in exactly one file
  (`mule/system-api/crm-system-api/src/main/resources/dw/crm-customer-to-canonical.dwl`).
- The loyalty platform's habit of returning 404 for an unenrolled customer is
  translated once into an unambiguous `enrolled: false`.
- Entitlement and masking are enforced at one point, from the token.
- Degradation is possible: because orchestration is in one layer, that layer can
  decide what to do when a source is down. Point-to-point consumers cannot.

**Negative**

- Four applications instead of one. More to deploy, monitor and reason about.
- An extra hop. Mitigated by concurrent orchestration and a materialised
  Customer 360; the p95 budget is 800 ms and the layering costs tens of
  milliseconds of it.
- The layering degrades without enforcement. Two rules are checked in review
  because no linter can express them: an experience API making a second outbound
  call belongs in the process layer, and a system API joining two sources has
  become a process API with the wrong name.

**Neutral**

- Ties the estate to MuleSoft's conventions. The pattern is portable; the
  tooling investment is not.

## Alternatives reconsidered

Option C keeps coming back, usually phrased as "we already have a gateway".
The answer: the gateway solves policy, and this platform needs policy *and*
orchestration *and* source normalisation. A gateway plus a service mesh plus
per-consumer aggregation code is Option A with better observability.

## What would make us revisit this

- If the number of consumers stayed at two or three, the layering would be
  overhead. It is justified by fan-out, and fan-out is the assumption to test.
- If Salesforce Data 360 subsumed enough source connectivity that the system
  layer became mostly empty, the process layer would sit directly on Data Cloud
  and the system layer would shrink to the systems Data Cloud does not reach.
  See [deployment.md](../deployment.md) §7.
