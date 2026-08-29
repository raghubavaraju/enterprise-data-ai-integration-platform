# ADR-007 / A transparent rule-weighted churn baseline, not a fitted model

**Status:** Accepted / **Date:** 2026-08 / **Decider:** Data & AI Architect

## Context

The platform needs a churn probability per customer. It drives a retention
workflow, appears on the service-desk screen, and grounds an AI-generated
explanation shown to an agent.

The available data has one decisive property: **there is no labelled churn
outcome.** Acme has no field that says "this customer churned on this date", and
in a retail context churn is not an event, it is the absence of one, which
requires a definition ("no order in 12 months") that nobody has agreed.

## Problem

How should the churn probability be produced?

## Options considered

### A. Train a classifier on a synthesised label

Define churn as "no order in the last 365 days", label the history, fit gradient
boosting, report AUC.

- **For:** Looks like machine learning. Produces a model artefact and a metric.
- **Against:** The label is a definition, not an observation, so the model learns
  to predict the definition. `F_RECENCY_DAYS` would dominate and the AUC would be
  near 1.0: an impressive number that means "recency predicts recency". Worse, a
  reported AUC invites the business to trust the score more than it deserves, and
  the honest conversation about what the model does not know never happens.

### B. Buy or import a generic churn model

- **For:** Someone else's problem.
- **Against:** Trained on someone else's customers and someone else's business
  model, uncalibrated for Acme, and unexplainable, which fails the requirement
  that the drivers be defensible to a business user.

### C. An unsupervised approach (clustering, anomaly detection)

- **For:** No label needed.
- **Against:** Produces cohorts, not a probability. Harder to explain, not
  easier. Does not answer the question the retention workflow asks.

### D. A transparent, rule-weighted baseline (chosen)

Seven bounded contributions, weights summing to 1, drivers computed and stored.

- **For:** Fully explainable: every component is a business signal with a stated
  weight, and the top three contributions are stored alongside the score. Honest:
  it claims to be a heuristic and is labelled `SCORING_METHOD = 'RULE_BASED'`.
  Debuggable: an unexpected score decomposes into seven numbers. It is a real
  baseline that a future model must beat.
- **Against:** Not learned from data, so the weights are opinion, informed
  opinion, agreed with the business, but opinion. Will not capture interactions
  between features. Not calibrated, so `0.62` is an ordering, not a frequency.

## Decision

**Option D**, with the weights documented in
[ai-architecture.md](../ai-architecture.md) §5 and the honesty carried into the
schema:

- `SCORING_METHOD = 'RULE_BASED'`: a column, so the method is queryable.
- `MODEL_VERSION` and `FEATURE_SET_VERSION`, so a score is attributable.
- `TOP_DRIVER_1..3` and their contributions, **stored**, not recomputed on read.
- The data dictionary says in words: *"Baseline rule-weighted churn score in
  [0,1]. Not a calibrated probability from a fitted model."*

The contract with the AI layer matters more than the arithmetic. The model
**explains stored drivers**; it does not decide why a customer might churn and it
does not re-score them. That boundary is where hallucination would otherwise
enter.

## Consequences

**Positive**

- Every score is defensible. "Why is this customer HIGH?" has a three-line
  answer with numbers in it.
- The AI explanation is grounded in stored values, so it is reproducible months
  later.
- The feature store, the score table and the API contract are already the right
  shape for a real model. Replacing the scorer is a change to one script.
- No fabricated accuracy metric exists to be quoted out of context.

**Negative**

- Weights are opinion and will drift from reality without periodic review.
- No interaction effects: a customer who is both recently complaining *and*
  slowing down is scored additively, when the combination is probably worse than
  the sum.
- `0.62` is not a 62% chance of churning. It is an ordering. That is stated in
  the dictionary and must be repeated whenever someone starts treating it as a
  frequency.

**Neutral**

- The bands (LOW/MEDIUM/HIGH/CRITICAL) do most of the operational work anyway.
  Retention acts on bands, not on decimals.

## Alternatives reconsidered

Option A becomes correct the moment a real outcome exists, a cancelled
subscription, a closed account, or twelve months of observed silence *after* the
business agrees that definition. The path is on purpose short: keep
`AI.CUSTOMER_FEATURES` as the training set, fit the model, register it, write to
the same score table with `SCORING_METHOD = 'ML'`, and run both until the model
demonstrably beats the baseline on a held-out period.

## What would make us revisit this

- A labelled outcome becoming available.
- Business feedback that the ordering is wrong, which is measurable: track the
  retention outcome of the customers the score put in the HIGH band.
- Drift in a driver's distribution large enough that a fixed weight no longer
  represents the same signal.
