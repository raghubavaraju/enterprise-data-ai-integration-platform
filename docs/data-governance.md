# Data governance

## 1. Operating model

Governance fails when it is a document. It works when it is a set of objects the
platform enforces. Everything below has a table behind it.

| Role | Held by | Accountable for | Where it shows up |
|---|---|---|---|
| Data Owner | The business VP for the domain | Definition, classification, retention, who may access | `GOVERNANCE.DATA_DICTIONARY.DATA_OWNER` |
| Data Steward | A named person in the domain | Quality rules, exception triage, definition disputes | `DATA_DICTIONARY.DATA_STEWARD`, `DQ_RULE.OWNER` |
| Data Custodian | Platform engineering | Pipelines, storage, controls operating as designed | Pipeline run log |
| Data Consumer | Any application or analyst | Using data within the terms of its contract | OAuth client registration |
| Chief Privacy Officer |, | Consent, subject rights, regulatory posture | Consent history view |

The test of the model: **every column in the dictionary has an owner and a
one-sentence business definition, and CI fails if one does not.** A column whose
definition cannot be written in one sentence usually means the model is wrong,
not that the sentence is hard.

## 2. Data domains

| Domain | Owner | System of record | Owns | Does not own |
|---|---|---|---|---|
| Customer | VP Customer Experience | CRM | Identity, contact, segment, consent | Purchase behaviour |
| Order | VP Commerce | Order Management | Orders, lines, fulfilment | Product master |
| Product | VP Merchandising | PIM | Product master | Pricing at time of sale (the order owns that) |
| Service | VP Customer Service | Support platform | Cases, CSAT, resolutions | Order value |
| Loyalty | VP Loyalty | Loyalty platform | Tier, points, enrolment | Service history |
| Analytics | Data Platform Owner | This platform | Every derived metric | Any source-system fact |
| AI | AI Platform Owner | This platform | Features, scores, generated content | Anything treated as truth |

## 3. Classification

| Class | Definition | Examples | Handling |
|---|---|---|---|
| **RESTRICTED** | Direct identifiers and sensitive free text | e-mail, phone, date of birth, case description | Masked by default; never sent to a model; `pii:read` required to see unmasked |
| **CONFIDENTIAL** | Attributable to an individual, business-sensitive | Name, consent flag, generated insight | Masked by default; restricted roles |
| **INTERNAL** | Not identifying on its own | Segment, order value, engagement score, churn score | Available to entitled applications and analysts |
| **PUBLIC** | Safe to publish | Product catalogue | No restriction |

Two categories deserve their own note:

- **Quasi-identifiers.** Date of birth alone is not a direct identifier, but with
  a postcode it re-identifies most people. It is classified RESTRICTED and
  generalised to the year.
- **Free text.** A support case description is classified RESTRICTED because it
  routinely contains incidental PII the customer typed themselves. It is
  truncated and redacted before it reaches the AI layer.

## 4. Data dictionary

The full dictionary is `GOVERNANCE.DATA_DICTIONARY`, seeded by
`snowflake/09-data-quality/04-data-dictionary-seed.sql` and generated in full at
[data-dictionary.md](data-dictionary.md). A representative slice:

| Table | Column | Definition | Class | PII | Owner | Retention | Masking |
|---|---|---|---|---|---|---:|---|
| `CORE.CUSTOMER` | `CUSTOMER_BK` | CRM-issued business key, stable for the life of the record | INTERNAL | no | VP CX | 84m |: |
| `CORE.CUSTOMER` | `EMAIL` | Primary e-mail; also the strongest identity-resolution key | RESTRICTED | yes | VP CX | 84m | `MP_EMAIL` |
| `CORE.CUSTOMER` | `BIRTH_DATE` | Date of birth. Quasi-identifier; generalised to year | RESTRICTED | yes | VP CX | 84m | `MP_DATE_GENERALISE` |
| `CORE.CUSTOMER` | `MARKETING_OPT_IN` | Marketing consent. Historised, consent state at a point in time is auditable | CONFIDENTIAL | no | CPO | 84m |: |
| `CORE.SALES_ORDER` | `NET_AMOUNT` | Amount less discount, excluding shipping. The revenue figure used everywhere downstream | INTERNAL | no | VP Commerce | 84m |: |
| `CORE.SUPPORT_CASE` | `DESCRIPTION` | Free-text complaint. May contain incidental PII; redacted before any AI call | RESTRICTED | yes | VP CS | 36m | `MP_FREE_TEXT` |
| `ANALYTICS.CUSTOMER_360` | `CUSTOMER_LIFETIME_VALUE` | Realised net revenue to date on recognised orders. **Not** a prediction | INTERNAL | no | VP Commerce | 24m |, |
| `ANALYTICS.CUSTOMER_360` | `PREDICTED_CLV_12M` | Projected 12-month value. Always labelled as predicted | INTERNAL | no | VP Commerce | 24m |, |
| `AI.CUSTOMER_CHURN_SCORE` | `CHURN_PROBABILITY` | Baseline rule-weighted score in [0,1]. Not a calibrated probability from a fitted model | INTERNAL | no | AI Owner | 24m |: |
| `AI.AI_CUSTOMER_INSIGHTS` | `GENERATED_TEXT` | Model-generated narrative. Never a system of record | CONFIDENTIAL | no | AI Owner | 24m |, |
| `AI.AI_CUSTOMER_INSIGHTS` | `GROUNDING_SNAPSHOT` | The exact facts given to the model. The evidence in any later dispute | CONFIDENTIAL | no | AI Owner | 24m |, |

CI asserts two properties of this table: every PII column names a masking policy,
and no column lacks an owner or a definition.

## 5. Data quality

Rules are **data, not code**: rows in `GOVERNANCE.DQ_RULE`. That lets a steward
add a rule without a deployment, lets the scorecard render itself, and lets
severity be tuned per environment. Two executors read the same rows: a Snowflake
stored procedure, and `local_warehouse/dq_runner.py`.

### Dimensions

| Dimension | Question | Example rule |
|---|---|---|
| Completeness | Is it there? | `DQ-C-001` customer business key present |
| Validity | Is it well-formed? | `DQ-O-002` order amount non-negative |
| Uniqueness | Is it one thing? | `DQ-X-002` exactly one current version per customer |
| Consistency | Does it agree with itself? | `DQ-O-006` every order references a known customer |
| Accuracy | Is it right? | `DQ-OI-002` line amount = quantity × unit price |
| Timeliness | Is it current? | `DQ-X-007` Customer 360 rebuilt within 24 hours |

Timeliness is the dimension teams skip, and it produces the most damaging kind of
wrong answer: a number that is internally consistent, passes every other check,
and describes last week.

### Severity, and what each one does

| Severity | Behaviour | When to use it |
|---|---|---|
| **BLOCKING** | Row quarantined in `RAW_REJECTED_RECORDS`, excluded from CORE, the rest of the load succeeds | Loading the row would corrupt a number someone decides on |
| **WARNING** | Row loads, flagged, appears on the steward's scorecard | The row is wrong but usable |
| **INFO** | Measured and trended; gates nothing | Signal, not a defect |

The failure mode to avoid is making everything BLOCKING. A platform that rejects
a day's orders because two of them have a bad postcode does not get trusted with
the next system.

### Quarantine, not deletion

Rejected rows go to `RAW.RAW_REJECTED_RECORDS` with the rule id, the reason, the
original payload and the correlation id. Three properties follow: the bad record
is kept, the reason is recorded, and reprocessing is possible once the source is
fixed. **Silent data loss is the failure mode that destroys trust in a platform**,
and it is usually invisible until someone reconciles counts months later.

### Proving the suite works

`sample-data/` contains eight deliberately planted defects. A data quality suite
that always reports green is indistinguishable from one that is not running, so
the expected outcome is documented in
[`snowflake/09-data-quality/expected-results.md`](../snowflake/09-data-quality/expected-results.md)
and asserted by `tests/data/test_data_quality.py`: **14 PASS, 5 WARN, 3 FAIL**.

### Escalation

| Status | Action | Owner | Target |
|---|---|---|---|
| BLOCKING FAIL | Page the on-call data engineer; halt promotion to CORE for that entity | Custodian | 1 hour |
| WARNING above threshold | Ticket to the domain steward | Steward | 3 business days |
| WARNING trending up | Raised at the monthly governance forum | Owner | Next cycle |
| INFO | Trended only |, |: |

## 6. Lineage

`GOVERNANCE.LINEAGE_EDGE` holds **declared** lineage, 25 edges covering the full
path from source system to the agent's screen, including the two that leave the
warehouse and enter MuleSoft. Snowflake's `ACCESS_HISTORY` gives **observed**
lineage.

Reconciling the two is the control:

| Situation | Meaning | Action |
|---|---|---|
| Observed, not declared | Undocumented coupling: someone is reading something nobody agreed to | Declare it, or stop it |
| Declared, not observed | Dead code | Remove it |
| Both | Healthy |: |

Each edge records whether it **propagates PII**, which makes the question
"where does this customer's e-mail address end up?" answerable by query rather
than by grep.

## 7. Retention

| Data | Retention | Basis |
|---|---:|---|
| Customer profile | 84 months after the last transaction | Commercial + statute of limitations |
| Consent history | 7 years | Evidential |
| Orders and lines | 84 months | Financial reporting |
| Support cases | 36 months | Service quality analysis |
| Interactions | 24 months | Marketing analysis |
| Derived analytics | 24 months | Recomputable from CORE |
| AI generated insights | 24 months | Audit and dispute |
| AI request audit | 24 months | Audit, cost, security |
| DQ results | 30 days hot, 13 months aggregated | Trend |
| RAW landing | 90 days in the stage, 1 day Time Travel | Replay window |
| Quarantined records | 90 days | Remediation window |

## 8. Subject rights

| Right | Mechanism | Target |
|---|---|---|
| Access | `CUSTOMER_BK` reaches every table; one parameterised query assembles the subject's data | 30 days |
| Rectification | Corrected at source; the platform picks it up on the next incremental load and creates a new SCD2 version | Next load |
| Erasure | Profile and contact data deleted; transactional records pseudonymised (`pseudonymise()` in `common/pii.py`) and retained 7 years for financial reporting | 30 days |
| Portability | The subject access extract, as JSON | 30 days |
| Objection to profiling | `MARKETING_OPT_IN = FALSE` suppresses marketing use; churn scoring for service purposes continues under legitimate interest | Immediate |

Erasure on purpose does **not** delete transactional history. It is
pseudonymised: the financial record survives, the person does not.

## 9. Data contracts

A contract is the promise a producer makes to a consumer. In this platform the
consumption views *are* the contracts.

Each carries:

| Element | Example |
|---|---|
| Producer | Data Platform Owner |
| Consumer | Snowflake Data System API |
| Schema | The view's column set and types |
| Freshness | `CUSTOMER_360` rebuilt daily by 05:00 UTC; `AS_OF_TIMESTAMP` published in every response |
| Quality | The DQ rules targeting the underlying tables, and their thresholds |
| Change policy | Additive within a major version; a removal or a type change is a new major version with a deprecation window |
| Escalation | Data Platform on-call |

The change policy makes the layering pay off: a consumer that reads a
view is insulated from a warehouse refactor, and a producer that adds a column
does not need to ask permission.

## 10. Governance forum

Monthly, chaired by the Data Platform Owner:

1. DQ scorecard. New failures, trends, rules whose thresholds need tuning.
2. Definition disputes, two teams computing "active customer" differently is a
   governance problem, not a reporting one.
3. New data contracts and deprecations.
4. Access review, who holds `pii:read`, who holds `ai:invoke`, and whether they
   still need it.
5. AI review queue health. Size, age, and the approve/reject ratio. A queue
   that is always empty and one that is never read fail in the same way.
