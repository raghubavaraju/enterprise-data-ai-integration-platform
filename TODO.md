# TODO

Running list. Not a roadmap, just what I keep meaning to get back to.

## Next

- [ ] Chunk overlap in the RAG corpus. A policy rule and its exception can end up
      in different chunks (see the note in `services/ai_service/rag.py`).
- [ ] Run `snowflake/05-pipelines` and `10-security` against a real trial account.
      Everything in those two folders is written and reviewed but never executed,
      and until it runs I can only say that much.
- [ ] The `CUSTOMER_360` rebuild is full-refresh. Fine at this size, wrong at a
      real one. Incremental refresh keyed on the changed-customer set.
- [ ] MUnit coverage for the experience layer error paths is thinner than the
      process layer's. Not hard, just not done.
- [ ] Decide whether `ENGAGEMENT_SCORE` belongs in ANALYTICS or in the feature
      store. It is currently defined in `07-customer-360/02` and read by both,
      which works but reads like a compromise because it is one.

## Maybe

- [ ] LLM-as-judge evaluation alongside the deterministic metrics. Useful, but it
      makes the CI gate non-deterministic, which is the property I like most
      about it today.
- [ ] Swap the lexical embedder for a real one behind the same interface. The
      interface is already there; it is a config change and a re-embed.
- [ ] A steward review queue for the probabilistic identity-resolution tier that
      does not exist yet.

## Done

- [x] Data dictionary generated from the warehouse instead of hand-maintained.
      Hand-maintained lasted about a week.
- [x] Diagram rendering in CI. Two diagrams were already broken when I added it.
