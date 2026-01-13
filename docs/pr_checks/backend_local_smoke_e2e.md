# Backend Local Smoke E2E Test

Copy-paste runnable sequence for testing the full frontend flow locally.

---

## Prerequisites

```bash
# Terminal 1: Ensure virtualenv and migrations
source .venv/bin/activate
python manage.py migrate
```

---

## Start Backend Services

```bash
# Terminal 1: Django dev server
python manage.py runserver 0.0.0.0:8000

# Terminal 2: BrandBrain worker (required for compile jobs)
source .venv/bin/activate
python manage.py brandbrain_worker --poll-interval=2
```

---

## Smoke Test Sequence

Run these in order. Replace `$BRAND_ID` and other variables as you go.

### 1. Create Brand

```bash
curl -X POST http://localhost:8000/api/brands \
  -H "Content-Type: application/json" \
  -d '{"name": "Test Brand", "website_url": "https://example.com"}'
```

**Expected Response (201)**:
```json
{
  "id": "UUID_HERE",
  "name": "Test Brand",
  "website_url": "https://example.com",
  "created_at": "2025-01-13T..."
}
```

**Capture the ID**:
```bash
export BRAND_ID="<paste-uuid-here>"
```

### 2. Get Brand

```bash
curl http://localhost:8000/api/brands/$BRAND_ID
```

**Expected Response (200)**:
```json
{
  "id": "...",
  "name": "Test Brand",
  "website_url": "https://example.com",
  "created_at": "..."
}
```

### 3. List Brands

```bash
curl http://localhost:8000/api/brands
```

**Expected Response (200)**:
```json
[
  {"id": "...", "name": "Test Brand", "website_url": "https://example.com", "created_at": "..."}
]
```

### 4. Get Onboarding (empty)

```bash
curl http://localhost:8000/api/brands/$BRAND_ID/onboarding
```

**Expected Response (200)**:
```json
{
  "brand_id": "...",
  "tier": 0,
  "answers_json": {},
  "updated_at": null
}
```

### 5. Put Onboarding (tier 0 answers)

```bash
curl -X PUT http://localhost:8000/api/brands/$BRAND_ID/onboarding \
  -H "Content-Type: application/json" \
  -d '{
    "tier": 0,
    "answers_json": {
      "brand_name": "Test Brand",
      "what_you_do": "We help people do things",
      "target_audience": "Everyone"
    }
  }'
```

**Expected Response (200)**:
```json
{
  "brand_id": "...",
  "tier": 0,
  "answers_json": {
    "brand_name": "Test Brand",
    "what_you_do": "We help people do things",
    "target_audience": "Everyone"
  },
  "updated_at": "2025-01-13T..."
}
```

### 6. Create Source Connection (Instagram Posts)

```bash
curl -X POST http://localhost:8000/api/brands/$BRAND_ID/sources \
  -H "Content-Type: application/json" \
  -d '{
    "platform": "instagram",
    "capability": "posts",
    "identifier": "testbrand",
    "is_enabled": true
  }'
```

**Expected Response (201)**:
```json
{
  "id": "SOURCE_UUID_HERE",
  "brand_id": "...",
  "platform": "instagram",
  "capability": "posts",
  "identifier": "testbrand",
  "is_enabled": true,
  "settings_json": null,
  "created_at": "..."
}
```

**Capture source ID**:
```bash
export SOURCE_ID="<paste-source-uuid-here>"
```

### 7. List Sources

```bash
curl http://localhost:8000/api/brands/$BRAND_ID/sources
```

**Expected Response (200)**:
```json
[
  {
    "id": "...",
    "brand_id": "...",
    "platform": "instagram",
    "capability": "posts",
    "identifier": "testbrand",
    "is_enabled": true,
    "settings_json": null,
    "created_at": "..."
  }
]
```

### 8. Kick Off BrandBrain Compile

```bash
curl -X POST http://localhost:8000/api/brands/$BRAND_ID/brandbrain/compile \
  -H "Content-Type: application/json" \
  -d '{"force_refresh": false}'
```

**Expected Response (202 Accepted)**:
```json
{
  "compile_run_id": "COMPILE_RUN_UUID",
  "status": "PENDING",
  "poll_url": "/api/brands/.../brandbrain/compile/.../status"
}
```

**Capture compile_run_id**:
```bash
export COMPILE_RUN_ID="<paste-compile-run-uuid-here>"
```

### 9. Poll Status Until Terminal

```bash
# Poll loop (run manually or script)
while true; do
  STATUS=$(curl -s http://localhost:8000/api/brands/$BRAND_ID/brandbrain/compile/$COMPILE_RUN_ID/status)
  echo "$STATUS" | python -c "import sys,json; d=json.load(sys.stdin); print(d['status'])"

  # Check if terminal
  STAT=$(echo "$STATUS" | python -c "import sys,json; print(json.load(sys.stdin)['status'])")
  if [ "$STAT" = "SUCCEEDED" ] || [ "$STAT" = "FAILED" ]; then
    echo "Final status: $STAT"
    echo "$STATUS" | python -m json.tool
    break
  fi

  sleep 2
done
```

**Expected Terminal Response (SUCCEEDED)**:
```json
{
  "compile_run_id": "...",
  "status": "SUCCEEDED",
  "evidence_status": {...},
  "snapshot": {
    "snapshot_id": "...",
    "created_at": "...",
    "snapshot_json": {...}
  }
}
```

### 10. Fetch Latest Snapshot

```bash
curl "http://localhost:8000/api/brands/$BRAND_ID/brandbrain/latest?include=full"
```

**Expected Response (200)**:
```json
{
  "snapshot_id": "...",
  "brand_id": "...",
  "snapshot_json": {...},
  "created_at": "...",
  "compile_run_id": "...",
  "evidence_status": {...},
  "qa_report": {...},
  "bundle_summary": {...}
}
```

### 11. Fetch Overrides (empty)

```bash
curl http://localhost:8000/api/brands/$BRAND_ID/brandbrain/overrides
```

**Expected Response (200)**:
```json
{
  "brand_id": "...",
  "overrides_json": {},
  "pinned_paths": [],
  "updated_at": null
}
```

### 12. Patch Overrides

```bash
curl -X PATCH http://localhost:8000/api/brands/$BRAND_ID/brandbrain/overrides \
  -H "Content-Type: application/json" \
  -d '{
    "overrides_json": {"positioning.tagline": "Custom tagline"},
    "pinned_paths": ["positioning.tagline"]
  }'
```

**Expected Response (200)**:
```json
{
  "brand_id": "...",
  "overrides_json": {"positioning.tagline": "Custom tagline"},
  "pinned_paths": ["positioning.tagline"],
  "updated_at": "..."
}
```

### 13. Patch Source (update identifier)

```bash
curl -X PATCH http://localhost:8000/api/sources/$SOURCE_ID \
  -H "Content-Type: application/json" \
  -d '{"identifier": "newhandle"}'
```

**Expected Response (200)**:
```json
{
  "id": "...",
  "brand_id": "...",
  "platform": "instagram",
  "capability": "posts",
  "identifier": "newhandle",
  "is_enabled": true,
  "settings_json": null,
  "created_at": "..."
}
```

### 14. Delete Source

```bash
curl -X DELETE http://localhost:8000/api/sources/$SOURCE_ID
```

**Expected Response (204)**: Empty body.

---

## Quick One-Liner Test Script

```bash
#!/bin/bash
set -e

echo "=== Creating brand ==="
BRAND=$(curl -s -X POST http://localhost:8000/api/brands \
  -H "Content-Type: application/json" \
  -d '{"name": "Smoke Test Brand", "website_url": "https://smoke.test"}')
echo "$BRAND"
BRAND_ID=$(echo "$BRAND" | python -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "BRAND_ID=$BRAND_ID"

echo "=== Setting onboarding ==="
curl -s -X PUT http://localhost:8000/api/brands/$BRAND_ID/onboarding \
  -H "Content-Type: application/json" \
  -d '{"tier": 0, "answers_json": {"brand_name": "Smoke Test"}}' | python -m json.tool

echo "=== Creating source ==="
SOURCE=$(curl -s -X POST http://localhost:8000/api/brands/$BRAND_ID/sources \
  -H "Content-Type: application/json" \
  -d '{"platform": "instagram", "capability": "posts", "identifier": "smoketest"}')
echo "$SOURCE"
SOURCE_ID=$(echo "$SOURCE" | python -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "SOURCE_ID=$SOURCE_ID"

echo "=== Kicking off compile ==="
COMPILE=$(curl -s -X POST http://localhost:8000/api/brands/$BRAND_ID/brandbrain/compile \
  -H "Content-Type: application/json" \
  -d '{"force_refresh": false}')
echo "$COMPILE"

echo "=== SMOKE TEST PASSED ==="
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Connection refused | Start `python manage.py runserver` |
| Compile stuck in PENDING | Start worker: `python manage.py brandbrain_worker --poll-interval=2` |
| CORS errors from frontend | Ensure `CORS_ALLOWED_ORIGINS` includes frontend URL |
| 404 on /api/brands | Run `python manage.py migrate` |
