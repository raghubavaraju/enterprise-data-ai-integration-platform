#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# End-to-end demonstration of the platform.  Every call below traverses
#   client -> experience API -> process API -> system API -> Snowflake SQL API
# and, where relevant, the AI service.
#
# Run ./scripts/run_local.sh (or make up) first.
# -----------------------------------------------------------------------------
set -uo pipefail
BASE="${EXPERIENCE_API:-http://127.0.0.1:8080}"
CUSTOMER="${CUSTOMER_ID:-CRM-100005}"
AT_RISK="${AT_RISK_ID:-CRM-100046}"
PASS=0; FAIL=0

hr() { printf '\n\033[1m%s\033[0m\n' "$1"; }
check() { # description expected_status actual_status
  if [ "$2" = "$3" ]; then printf '  \033[32mPASS\033[0m %-52s (%s)\n' "$1" "$3"; PASS=$((PASS+1));
  else printf '  \033[31mFAIL\033[0m %-52s (expected %s, got %s)\n' "$1" "$2" "$3"; FAIL=$((FAIL+1)); fi
}
status() { curl -s -o /dev/null -w '%{http_code}' "$@"; }

hr "1. OAuth 2.0 client credentials"
TOKEN=$(curl -s -X POST "$BASE/oauth/token" \
  -d "grant_type=client_credentials&client_id=acme-portal-client&client_secret=${OAUTH_CLIENT_SECRET:-change-me-local-only}&scope=customer:read insights:read ai:invoke" \
  | python3 -c "import sys,json;print(json.load(sys.stdin).get('access_token',''))")
[ -n "$TOKEN" ] && { echo "  token acquired (${#TOKEN} chars)"; PASS=$((PASS+1)); } \
                || { echo "  could not acquire a token - is the stack running?"; exit 1; }

READONLY=$(curl -s -X POST "$BASE/oauth/token" \
  -d "grant_type=client_credentials&client_id=acme-readonly-client&client_secret=${OAUTH_CLIENT_SECRET:-change-me-local-only}" \
  | python3 -c "import sys,json;print(json.load(sys.stdin).get('access_token',''))")

AUTH=(-H "Authorization: Bearer $TOKEN")
CID="smoke-$(date +%s)"

hr "2. Customer 360 through the full API-led chain"
curl -s "${AUTH[@]}" -H "x-correlation-id: $CID" \
  "$BASE/api/v1/customers/$CUSTOMER/360?orderLimit=3" |
  python3 -c "
import json,sys
d=json.load(sys.stdin)
p,a,m=d['profile'],d['analytics'],d['meta']
print(f\"  customer         {d['customerId']}  ({p['segment']}, {p['status']})\")
print(f\"  name / e-mail    {p['fullName']} / {p['email']}   <- masked: no pii:read scope\")
print(f\"  orders           {a['totalOrders']} orders, revenue {a['totalNetRevenue']}, AOV {a['avgOrderValue']}\")
print(f\"  service          {a['totalCases']} cases ({a['openCases']} open), CSAT {a['avgCsat']}\")
print(f\"  loyalty          {d['loyalty']['tier']} / {d['loyalty']['pointsBalance']} points\")
print(f\"  engagement/CLV   {a['engagementScore']} / {a['customerLifetimeValue']} (predicted 12m {a['predictedClv12m']})\")
print(f\"  churn            {d['churnRisk']['riskBand']} p={d['churnRisk']['churnProbability']} \"
      f\"top driver {d['churnRisk']['drivers'][0]['driver']}\")
print(f\"  sources          {','.join(m['contributingSources'])} completeness {m['dataCompletenessScore']}%\")
print(f\"  correlation id   {m['correlationId']}  ({m['elapsedMs']} ms)\")
"

hr "3. Correlation id propagates end to end"
ECHOED=$(curl -s -D- -o /dev/null "${AUTH[@]}" -H "x-correlation-id: $CID" \
  "$BASE/api/v1/customers/$CUSTOMER/churn-risk" | tr -d '\r' | awk -F': ' '/^x-correlation-id/{print $2}')
check "the id we sent comes back" "$CID" "$ECHOED"

hr "4. Grounded AI insights"
curl -s "${AUTH[@]}" "$BASE/api/v1/customers/$AT_RISK/insights?types=SUMMARY,CHURN_EXPLANATION,NEXT_BEST_ACTION" |
  python3 -c "
import json,sys,textwrap
d=json.load(sys.stdin)
for i in d['insights']['generated']:
    print(f\"  [{i['type']}] confidence={i['confidence']} review={i['reviewStatus']} sources={i['sources']}\")
    print(textwrap.fill(i['text'], 92, initial_indent='      ', subsequent_indent='      '))
"

hr "5. Least privilege - a read-only client cannot invoke the AI"
check "403 for a client without ai:invoke" 403 \
  "$(status -X POST -H "Authorization: Bearer $READONLY" -H 'content-type: application/json' \
      --data-binary '{"capability":"SUMMARY"}' "$BASE/api/v1/customers/$CUSTOMER/ai-analysis")"
check "403 for a client without insights:read" 403 \
  "$(status -H "Authorization: Bearer $READONLY" "$BASE/api/v1/customers/$CUSTOMER/insights")"
check "401 with no token at all" 401 "$(status "$BASE/api/v1/customers/$CUSTOMER/360")"
check "401 with a malformed token" 401 \
  "$(status -H 'Authorization: Bearer not-a-real-token' "$BASE/api/v1/customers/$CUSTOMER/360")"

hr "6. Error contract"
check "404 for an unknown customer" 404 \
  "$(status "${AUTH[@]}" "$BASE/api/v1/customers/CRM-000000/360")"
curl -s "${AUTH[@]}" "$BASE/api/v1/customers/CRM-000000/360" |
  python3 -c "import json,sys;d=json.load(sys.stdin);print(f\"  errorCode={d['errorCode']} retryable={d['retryable']} correlationId={d['correlationId'][:24]}...\")"

hr "7. Idempotency - a replayed AI call is not charged twice"
KEY="smoke-idem-$(date +%s)"
for i in 1 2; do
  curl -s -X POST "${AUTH[@]}" -H 'content-type: application/json' -H "Idempotency-Key: $KEY" \
    -d '{"capability":"NEXT_BEST_ACTION","forceRefresh":true}' \
    "$BASE/api/v1/customers/$AT_RISK/ai-analysis" |
    python3 -c "import json,sys;d=json.load(sys.stdin);print(f\"  call $i -> replay={d['meta']['idempotentReplay']} action={(d.get('structured') or {}).get('action')}\")"
done

hr "8. Data quality scorecard (planted defects are expected to appear)"
curl -s "${AUTH[@]}" "$BASE/api/v1/governance/data-quality" |
  python3 -c "
import json,sys,collections
rows=json.load(sys.stdin)['data']
c=collections.Counter(r['status'] for r in rows)
print(f\"  {len(rows)} rules -> {dict(c)}\")
for r in rows:
    if r['status'] != 'PASS':
        print(f\"    {r['status']:4s} {r['ruleId']:<11s} {r['ruleName'][:52]:<52s} failed={r['rowsFailed']}\")
"

hr "9. High-risk cohort ordered by customer value"
curl -s "${AUTH[@]}" "$BASE/api/v1/cohorts/high-risk?limit=5" |
  python3 -c "
import json,sys
for r in json.load(sys.stdin)['data']:
    print(f\"  {r['customerId']:<12s} p={r['churnProbability']:<7} {r['churnRiskBand']:<8s} \"
          f\"CLV={r['customerLifetimeValue']:<9} tier={r['loyaltyTier']}\")
"

hr "Result"
printf '  %d passed, %d failed\n\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
