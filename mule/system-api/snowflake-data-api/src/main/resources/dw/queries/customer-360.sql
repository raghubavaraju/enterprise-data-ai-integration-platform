-- Statement executed by GET /customers/{customerId}/360.
--
-- Held as a resource instead of built in DataWeave for three reasons:
--   * it is reviewable as SQL by a data engineer who does not read DataWeave;
--   * it cannot accidentally acquire string concatenation;
--   * it can be linted by the same tooling as everything in snowflake/.
--
-- Reads a view, never a base table: the view is the contract, so a warehouse
-- refactor is not an API change.
SELECT *
FROM ACME_EDP.ANALYTICS.V_CUSTOMER_360_API
WHERE CUSTOMER_ID = ?
