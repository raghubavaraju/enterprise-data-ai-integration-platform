# Local warehouse (DuckDB stand-in for Snowflake)

This package lets the whole platform run on a laptop with no Snowflake account.
It is **not** a Snowflake emulator and does not pretend to be one.  What it does:

1. Executes the **portable** scripts in `snowflake/` verbatim, after a small,
   explicit dialect rewrite (`dialect.py`).  The transformation logic in this
   repository is therefore the logic that actually runs in the demo - there is
   no second, quietly divergent copy of the SQL.
2. Skips the **Snowflake-only** scripts and says so, loudly, listing which
   feature made each one unportable.
3. Serves results to the rest of the platform through a mock of the
   **Snowflake SQL API** (`services/data_api`), which is the same HTTP contract
   the MuleSoft System API calls in cloud mode.  Switching `PLATFORM_MODE` from
   `local` to `cloud` changes a base URL and a credential, not a line of flow
   logic.

## What is faithful, and what is not

| Aspect | Local (DuckDB) | Snowflake |
|---|---|---|
| Transformation SQL | same scripts | same scripts |
| SCD2 load | full-rebuild script | `MERGE` over a stream |
| Ingestion | Python loader from `sample-data/` | Snowpipe / external stage / Mule bulk |
| Vector search | numpy cosine over stored arrays | `VECTOR_COSINE_SIMILARITY` on `VECTOR(FLOAT, 768)` |
| Embeddings / LLM | deterministic local implementation | Cortex `EMBED_TEXT_768` / `AI_COMPLETE` |
| Masking, row access policies | not enforced | enforced by policy objects |
| Time Travel, cloning, failover | absent | native |
| Cost model | none | credits |

Anything in the right-hand column that is absent on the left is called out in
`docs/deployment.md` under "what changes when you move to a real account".
