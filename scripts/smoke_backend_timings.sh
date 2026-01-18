#!/usr/bin/env bash
#
# smoke_backend_timings.sh - Backend E2E latency smoke test
#
# PR-7: Backend debug pack - provides request-level timing proof
# without browser DevTools.
#
# Usage:
#   ./scripts/smoke_backend_timings.sh [BASE_URL]
#
# Arguments:
#   BASE_URL - Backend URL (default: http://localhost:8000)
#
# Environment:
#   BRAND_ID - Existing brand UUID for compile tests (optional)
#
# Output:
#   Request-level timing for key endpoints
#

set -euo pipefail

# Configuration
BASE_URL="${1:-http://localhost:8000}"
BRAND_ID="${BRAND_ID:-}"

echo "======================================"
echo "Backend E2E Latency Smoke Test"
echo "======================================"
echo ""
echo "Base URL: $BASE_URL"
echo "Time: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo ""

# Function to run a timed request
run_test() {
    local method="$1"
    local path="$2"
    local name="$3"
    local data="${4:-}"

    local url="${BASE_URL}${path}"

    if [ "$method" = "POST" ]; then
        if [ -n "$data" ]; then
            result=$(curl -s -o /tmp/curl_body.txt -w "%{http_code} %{time_total}" \
                -X POST -H "Content-Type: application/json" -d "$data" "$url")
        else
            result=$(curl -s -o /tmp/curl_body.txt -w "%{http_code} %{time_total}" \
                -X POST -H "Content-Type: application/json" "$url")
        fi
    else
        result=$(curl -s -o /tmp/curl_body.txt -w "%{http_code} %{time_total}" "$url")
    fi

    # Parse result
    http_code=$(echo "$result" | awk '{print $1}')
    time_total=$(echo "$result" | awk '{print $2}')

    # Convert to ms
    time_ms=$(echo "$time_total * 1000" | bc 2>/dev/null || echo "0")

    printf "%-50s %3s  %8.1f ms\n" "$name" "$http_code" "$time_ms"
}

# ============================================================
# Health Check
# ============================================================
echo "--- Health Check ---"
run_test "GET" "/health/" "GET /health/"
echo ""

# ============================================================
# Brands Endpoints
# ============================================================
echo "--- Brands API ---"
run_test "GET" "/api/brands" "GET /api/brands"

# Try to get a brand ID if not provided
if [ -z "$BRAND_ID" ]; then
    BRAND_ID=$(curl -s "${BASE_URL}/api/brands" 2>/dev/null | \
        python3 -c "import sys,json; d=json.load(sys.stdin); print(d[0]['id'] if d else '')" 2>/dev/null || echo "")
fi

if [ -n "$BRAND_ID" ]; then
    echo "Using brand: $BRAND_ID"
    echo ""

    run_test "GET" "/api/brands/${BRAND_ID}" "GET /api/brands/:id"
    run_test "GET" "/api/brands/${BRAND_ID}/onboarding" "GET /api/brands/:id/onboarding"
    run_test "GET" "/api/brands/${BRAND_ID}/sources" "GET /api/brands/:id/sources"
    echo ""

    # ============================================================
    # BrandBrain Endpoints
    # ============================================================
    echo "--- BrandBrain API ---"
    run_test "GET" "/api/brands/${BRAND_ID}/brandbrain/overrides" "GET overrides (read-path, SLA: <30ms)"
    run_test "GET" "/api/brands/${BRAND_ID}/brandbrain/latest" "GET latest snapshot (SLA: <50ms)"
    run_test "GET" "/api/brands/${BRAND_ID}/brandbrain/history" "GET history (SLA: <100ms)"
    echo ""

    # ============================================================
    # Compile Endpoints
    # ============================================================
    echo "--- Compile API ---"
    run_test "POST" "/api/brands/${BRAND_ID}/brandbrain/compile" "POST compile kickoff (SLA: <200ms)"

    # Check if we got a compile run ID
    COMPILE_RUN_ID=$(cat /tmp/curl_body.txt 2>/dev/null | \
        python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('compile_run_id',''))" 2>/dev/null || echo "")

    if [ -n "$COMPILE_RUN_ID" ] && [ "$COMPILE_RUN_ID" != "None" ]; then
        run_test "GET" "/api/brands/${BRAND_ID}/brandbrain/compile/${COMPILE_RUN_ID}/status" "GET compile status (SLA: <30ms)"
    fi

    echo ""
    echo "--- Compile Response ---"
    cat /tmp/curl_body.txt 2>/dev/null | python3 -m json.tool 2>/dev/null | head -20 || cat /tmp/curl_body.txt
else
    echo ""
    echo "No brand found. Create a brand to test BrandBrain endpoints."
fi

echo ""
echo "======================================"
echo "Test Complete"
echo "======================================"
echo ""
echo "Notes:"
echo "  - SLA times are for local/fast DB. Remote Supabase adds ~700-900ms network overhead."
echo "  - Enable server-side timing with: KAIRO_LOG_DB_TIMING=1"
echo "  - Check Django server logs for query counts and DB time."
echo ""

# Cleanup
rm -f /tmp/curl_body.txt

exit 0
