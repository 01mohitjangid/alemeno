#!/usr/bin/env bash
#
# End-to-end smoke test: uploads a CSV, polls until the job finishes, then prints
# the results summary and the job list.
#
# Usage:
#   ./scripts/smoke_test.sh                 # uses http://localhost:8000
#   BASE_URL=http://localhost:8080 ./scripts/smoke_test.sh
#   ./scripts/smoke_test.sh path/to/other.csv
#
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
CSV="${1:-data/transactions.csv}"

echo "== Base URL: $BASE_URL"
echo "== CSV file: $CSV"

echo ""
echo "== Health check"
curl -fsS "$BASE_URL/health"; echo ""

echo ""
echo "== 1) Upload"
RESP="$(curl -fsS -X POST "$BASE_URL/jobs/upload" -F "file=@${CSV};type=text/csv")"
echo "$RESP" | python3 -m json.tool
JOB_ID="$(echo "$RESP" | python3 -c 'import sys,json; print(json.load(sys.stdin)["job_id"])')"

echo ""
echo "== 2) Poll status (job_id=$JOB_ID)"
for i in $(seq 1 60); do
  ST="$(curl -fsS "$BASE_URL/jobs/$JOB_ID/status")"
  STATUS="$(echo "$ST" | python3 -c 'import sys,json; print(json.load(sys.stdin)["status"])')"
  echo "   poll $i: $STATUS"
  if [ "$STATUS" = "completed" ] || [ "$STATUS" = "failed" ]; then break; fi
  sleep 1
done
echo "$ST" | python3 -m json.tool

echo ""
echo "== 3) Results (transactions/anomalies shown as counts)"
curl -fsS "$BASE_URL/jobs/$JOB_ID/results" | python3 -c '
import sys, json
d = json.load(sys.stdin)
for k in ("transactions", "anomalies"):
    d[k] = f"[{len(d[k])} items]"
print(json.dumps(d, indent=2, default=str))
'

echo ""
echo "== 4) Job list"
curl -fsS "$BASE_URL/jobs" | python3 -m json.tool

echo ""
echo "== Done."
