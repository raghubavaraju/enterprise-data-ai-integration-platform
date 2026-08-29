# ADR-006 / Snowflake SQL API instead of JDBC from Mule

**Status:** Accepted / **Date:** 2026-08 / **Decider:** Integration Architect

## Context

The Snowflake Data System API is the only component permitted to query the
warehouse. Two connection options exist from a Mule application: the Database
connector over the Snowflake JDBC driver, or the Snowflake SQL API over HTTPS.

The deployment target is CloudHub 2.0: ephemeral, horizontally scaled workers
that are replaced on every deployment and scaled on load.

## Problem

How should the System API talk to Snowflake?

## Options considered

### A. JDBC via the Mule Database connector

- **For:** Familiar. First-class `<db:select>` support. Result sets map cleanly.
  Bind parameters are natural.
- **Against:**
  - **Connection pools on ephemeral workers.** Each worker holds a pool. Three
    replicas at ten connections each is thirty Snowflake sessions, most of them
    idle. They keep the warehouse from auto-suspending, so an XSMALL warehouse
    that should be running for seconds a minute runs continuously, a recurring
    bill produced by connections nobody is using.
  - **Opaque to the platform.** A JDBC call is invisible to the HTTP-level retry,
    timeout, circuit-breaker and correlation-id machinery every other dependency
    uses. Resilience has to be re-implemented differently for this one connector.
  - **Blocking threads.** A long query occupies a worker thread for its duration.
  - **Driver management.** The JDBC driver is a dependency to package, patch and
    keep compatible with the runtime.

### B. Snowflake SQL API over HTTPS (chosen)

- **For:**
  - **No persistent sessions.** Each call is a request; the warehouse suspends
    when nothing is running, which is what makes aggressive auto-suspend
    effective rather than theoretical.
  - **The platform's own machinery applies.** Timeouts, `until-successful`
    retry, circuit breaking, correlation-id propagation and API-level monitoring
    all work because it is just another HTTP dependency.
  - **Asynchronous statements.** A statement can be submitted and polled by
    handle, so a long query does not occupy a worker thread, the only sane
    option for an integration platform that might run a multi-minute query.
  - **Key-pair JWT authentication.** No password exists, so there is no password
    to leak or rotate by hand.
  - **`QUERY_TAG` carries the correlation id** into `QUERY_HISTORY`, which is the
    join that makes end-to-end tracing reach into the warehouse.
  - **Testable.** Because the contract is HTTP, local mode can implement the same
    contract over DuckDB, so the flow logic is identical in both modes.
- **Against:** Results arrive as arrays of strings with a separate metadata
  block, so type coercion is the caller's job. More verbose than `<db:select>`.
  Pagination for very large result sets must be handled explicitly. It is a
  less common pattern, so it needs explaining in review.

## Decision

**Option B.** The System API calls the Snowflake SQL API over HTTPS with
key-pair JWT authentication, submits parameterised statements with bind values,
sets `QUERY_TAG` to the correlation id, and polls asynchronously when Snowflake
returns 202.

Type coercion happens once, in `dw/sql-result-to-rows.dwl`, so no flow downstream
knows the wire format. Coercing rather than passing strings through matters:
`"0.3988"` and `0.3988` behave differently the moment a consumer compares, sorts
or sums them, and the bug surfaces far from its cause.

## Consequences

**Positive**

- The warehouse suspends between bursts, which is the single largest lever on
  cost for a bursty API workload.
- One set of resilience patterns for every dependency, so there is one place to
  get retry and circuit breaking right.
- End-to-end tracing reaches into `QUERY_HISTORY`.
- No JDBC driver to package or patch.
- The local implementation of the same HTTP contract makes the whole
  platform runnable without a Snowflake account.

**Negative**

- More code than `<db:select>`: request construction, result mapping, polling.
- Result-set size limits mean actually large extracts need `COPY INTO` a stage
  plus a file transfer, which is the right pattern for a bulk extract anyway,
  and would be a bad thing to do through an API in any case.
- Per-statement HTTP overhead, tens of milliseconds. Irrelevant next to query
  time.

**Neutral**

- Bind parameters are mandatory, which is a constraint the design wanted anyway:
  concatenating a URL path segment into SQL is injection with extra steps, and
  this API's inputs come from a URL.

## Alternatives reconsidered

Option A remains right for a **batch** application on a dedicated, long-lived
worker doing bulk loads, where a persistent pool is an asset rather than a
liability, and the warehouse is meant to stay awake for the duration.

## What would make us revisit this

- A requirement for very large synchronous result sets, which the SQL API is not
  designed for and which would push that specific path to a stage-and-fetch
  pattern.
- Snowflake deprecating or materially changing the SQL API.
- A move to long-lived, dedicated runtimes rather than ephemeral workers, which
  would remove the main argument against a connection pool.
