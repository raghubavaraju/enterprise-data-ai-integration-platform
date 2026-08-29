# Contributing

## Getting a green build locally

```bash
make setup      # install python dependencies
make build      # build the local warehouse from sample data
make test       # 245 tests: unit, data, API, AI evaluation
make lint       # ruff, SQL conventions, API governance
make run        # start the platform
make smoke      # end-to-end demonstration
```

Nothing above needs a Snowflake account, an Anypoint licence, an LLM API key or
a credit card.  That is deliberate: a repository that cannot be run cannot be
reviewed.

## The rules this repository actually enforces

These are checked by CI, not by convention:

| Rule | Enforced by |
|---|---|
| No credential, key or account identifier anywhere in the tree | `security-scan` job, gitleaks + a repository-wide pattern check |
| Every API has a specification that conforms to `docs/api-governance.md` | `scripts/validate_api_specs.py` |
| No `SELECT *` in a consumption view; no unqualified object in a portable script; no read of an SCD2 table without `IS_CURRENT` | `scripts/lint_sql.py` |
| The sample dataset is reproducible | CI regenerates it and fails on a diff |
| Generated AI output stays grounded, safe and consistent | `tests/ai`, thresholds in `services/ai_service/evaluation.py` |
| The data quality suite still finds all eight planted defects | `tests/data/test_data_quality.py` |

## Architectural rules that are not automatable

Reviewers check these by hand:

1. **An experience API does not orchestrate.** If a change adds a second
   outbound call to an experience API, it belongs in a process API.
2. **A system API does not join two sources.** The moment it does, it has become
   a process API with the wrong name and the wrong blast radius.
3. **Nothing but the Snowflake System API queries Snowflake.**
4. **The AI layer reads the AI-safe view, never a source system and never a
   table with direct identifiers in it.**
5. **A new BLOCKING data quality rule needs a justification.** Blocking is for
   defects that would corrupt a number someone decides on. Over-using it is how
   a platform becomes famous for rejecting the business's data.

## Adding a data quality rule

Rules are data, not code.  Add a row to
`snowflake/09-data-quality/01-rule-catalog.sql`, give it an owner and a
dimension, and choose the severity on purpose.  Both executors - the Snowflake
stored procedure and `local_warehouse/dq_runner.py` - pick it up with no code
change.

## Changing a prompt

Prompts are versioned artefacts.  Bump the `version` on the template in
`services/ai_service/prompts.py`, and expect the AI evaluation gate to tell you
whether the change helped.  Every stored insight records the prompt version that
produced it, so a regression is attributable.

## Commit style

Conventional commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`),
scoped to a layer where it helps: `feat(process): degrade instead of failing when
the loyalty platform is down`.
