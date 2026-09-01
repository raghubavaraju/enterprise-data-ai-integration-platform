## What changed

<!-- One paragraph. What does this change do, and why is it the right change? -->

## Architecture impact

- [ ] No layer boundary was crossed (an experience API still does not orchestrate;
      a system API still does not join two sources)
- [ ] No new component gained direct access to Snowflake or to a source system
- [ ] Any new API surface has a specification, and `make lint-spec` passes
- [ ] Any change to a derived metric is documented in `docs/data-architecture.md`
- [ ] An ADR was added or amended if a significant decision changed

## Data and AI

- [ ] No PII was added to a view the AI layer reads
- [ ] Data quality rules were added or updated for any new field that matters
- [ ] `make test` passes, including the AI evaluation gate
- [ ] Prompt changes carry a version bump

## Security

- [ ] No credential, key or account identifier is in the diff
- [ ] New configuration goes to `*.yaml` and its secret half to `*-secure.yaml.example`
- [ ] Scope requirements on new endpoints are least-privilege

## How this was verified

<!-- Commands run, and what you observed. "CI is green" is not a verification. -->
