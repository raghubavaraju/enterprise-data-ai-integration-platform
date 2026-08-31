# Data quality: expected results

The sample dataset in `sample-data/` contains **eight deliberately planted
defects**.  They exist so that the rule catalogue can be seen to work rather
than merely to exist - a data quality suite that always reports green is
indistinguishable from one that is not running.

Regenerating the dataset (`python scripts/generate_sample_data.py`) is
deterministic, so these numbers are stable and are asserted by
`tests/data/test_data_quality.py`.

## Expected outcome of `make dq` on a fresh build

| Rule | Severity | Failing rows | Status | Planted defect |
|---|---|---:|---|---|
| `DQ-C-001` | BLOCKING | 1 | **FAIL** | A customer record with a null `customerId` |
| `DQ-O-002` | BLOCKING | 1 | **FAIL** | `ORD-999001` has an order amount of `-42.50` |
| `DQ-O-003` | BLOCKING | 1 | **FAIL** | `ORD-999002` is dated 120 days in the future |
| `DQ-C-002` | WARNING  | 2 | WARN | Two malformed e-mail addresses (missing TLD, missing `@`) |
| `DQ-C-005` | WARNING  | 1 | WARN | `CRM-900001` is the same person as an existing customer, different id and casing |
| `DQ-L-003` | WARNING  | 1 | WARN | One loyalty account has redeemed more points than it ever earned |
| `DQ-O-006` | WARNING  | 1 | WARN | `ORD-999003` references customer `CRM-404404`, who does not exist |
| `DQ-OI-003`| WARNING  | 1 | WARN | `ORD-999003-1` references product `PRD-9999`, which does not exist |
| `DQ-X-007` | BLOCKING | 0 | PASS | Timeliness: Customer 360 rebuilt within 24h |
| `DQ-X-008` | WARNING  | 0 | PASS | Timeliness: churn scores refreshed today |
| all others | -        | 0 | PASS | - |

Summary: **14 PASS, 5 WARN, 3 FAIL, 0 ERROR.**

## What happens to each defect

| Defect | Fate |
|---|---|
| Null business key | Never enters STAGING (it cannot be keyed).  Quarantined in `RAW.RAW_REJECTED_RECORDS` with rule `DQ-C-001`. |
| Negative amount, future date | Loaded to STAGING, stamped `DQ_STATUS = 'FAIL'`, excluded from CORE, quarantined. |
| Malformed e-mail | Loaded and flagged.  `EMAIL_IS_VALID = FALSE` means the row is excluded from e-mail-based identity matching but is otherwise usable. |
| Exact duplicate | Collapsed silently by the stage-1 dedupe.  A source replay is not a defect. |
| Fuzzy duplicate | Suppressed by survivorship, recorded in `RAW_REJECTED_RECORDS` as WARNING for steward review. |
| Orphan order / orphan line | Loaded (the transaction really happened) but reported.  The line is dropped from `CORE.SALES_ORDER_ITEM` so revenue aggregates stay correct. |
| Loyalty inconsistency | Loaded and flagged; the loyalty team owns the correction upstream. |

## The design point

Three severities, three different behaviours:

- **BLOCKING** - loading the row would corrupt a number someone decides on.
  Quarantine it, and let the rest of the load succeed.
- **WARNING** - the row is usable but wrong.  Load it, flag it, put it on the
  steward's scorecard.
- **INFO** - measured and trended, never gates anything.

The failure mode to avoid is making everything BLOCKING.  A platform that
rejects a day's orders because two of them have a bad postcode does not get
trusted with the next system.
