# Apify Field Observations

**Status:** PENDING - Populate after first local run
**Goal:** Document observed fields from Apify actor runs for BrandBrain exploration.
**Source:** `brandbrain_spec_skeleton.md` §10

---

## Runs Executed

| Actor ID | Apify Run ID | Dataset ID | Item Count | Timestamp |
|----------|--------------|------------|------------|-----------|
| PENDING: populate after first run | - | - | - | - |

---

## Observed Fields

PENDING: populate after first local run.

After running the exploration command, document the JSON structure returned by each actor:

### Instagram Scraper (`apify/instagram-scraper`)

**PENDING:** Run the command and document actual fields.

Expected fields (verify after run):
- `$.id` or `$.shortCode` - Post identifier
- `$.caption` - Caption text (if present)
- `$.likesCount` or `$.likeCount` - Likes
- `$.commentsCount` or `$.commentCount` - Comments
- `$.playCount` or `$.viewCount` - Views
- `$.timestamp` or `$.takenAt` - Post date
- `$.ownerUsername` - Author handle
- `$.videoUrl` or `$.displayUrl` - Media URL

### TikTok Profile Scraper

**PENDING:** Run the command and document actual fields.

### LinkedIn Profile Scraper

**PENDING:** Run the command and document actual fields.

---

## Missing/Unstable Fields

PENDING: populate after first local run.

Document any fields that:
- Are sometimes missing
- Have inconsistent types
- Are null more than 50% of the time

---

## Recommended Minimal Normalized Post Shape

**Note:** This is a suggestion based on `brandbrain_spec_skeleton.md` §8. DO NOT implement normalization yet.

- `platform`: `instagram` | `tiktok` | `linkedin` | `x` | `web` | `unknown`
- `post_url`: string (nullable)
- `created_at`: ISO datetime (nullable)
- `text`: string (caption or transcript)
- `format`: supported format enum
- `metrics.views`: number (nullable)
- `metrics.likes`: number (nullable)
- `metrics.comments`: number (nullable)
- `metrics.shares`: number (nullable)
- `media.thumbnail_url`: string (nullable)
- `media.video_url`: string (nullable)
- `signals.hashtags`: string[]
- `signals.mentions`: string[]
- `raw_ref.run_id`: string
- `raw_ref.item_index`: number
- `raw_ref.json_pointer`: string

---

## How to Run with Free-Tier Cap

Per `brandbrain_spec_skeleton.md` §10:

- **Max items per run:** 20 (use `--limit 20`)
- **Max runs during exploration:** 1 per platform
- **Cost target:** Stay under $5 total for all exploration

---

## Mode 1: Start a New Run

Use this when you want to start a fresh Apify actor run. **This spends Apify budget.**

### Ready-to-Run Example: Wendy's Instagram

**Input JSON:**
```json
{
  "username": ["wendys"],
  "resultsLimit": 20
}
```

**Command:**
```bash
# Ensure APIFY_TOKEN is set in .env
python manage.py brandbrain_apify_explore \
    --actor-id "apify~instagram-scraper" \
    --input-json '{"username": ["wendys"], "resultsLimit": 20}' \
    --limit 20 \
    --save-samples 3
```

**Alternative with input file:**
```bash
# Create input file
echo '{"username": ["wendys"], "resultsLimit": 20}' > var/apify_input_wendys.json

python manage.py brandbrain_apify_explore \
    --actor-id "apify~instagram-scraper" \
    --input-file var/apify_input_wendys.json \
    --limit 20 \
    --save-samples 3
```

**Expected outputs:**
- `ApifyRun` row in database with `apify_run_id`, `dataset_id`, `item_count`
- `RawApifyItem` rows (up to 20) with full raw JSON
- Sample files: `var/apify_samples/apify_instagram-scraper/<run_uuid>/item_0.json`, etc.

---

## Mode 2: Resume an Existing Run (Budget-Safe)

Use this when:
- A previous run started but the DB write failed
- You want to re-fetch items from an existing dataset
- You have a run ID from the Apify console

**This does NOT start a new Apify run. No budget is spent.**

### Resume with polling (run may still be in progress):
```bash
python manage.py brandbrain_apify_explore \
    --existing-run-id "abc123xyz" \
    --actor-id "apify~instagram-scraper" \
    --limit 20 \
    --save-samples 3
```

### Resume with known dataset ID (skip polling entirely):
```bash
python manage.py brandbrain_apify_explore \
    --existing-run-id "abc123xyz" \
    --dataset-id "def456uvw" \
    --actor-id "apify~instagram-scraper" \
    --limit 20 \
    --save-samples 3
```

**Notes:**
- `--actor-id` is optional in resume mode (will store empty string if not provided)
- `--input-file` and `--input-json` are NOT allowed in resume mode
- Running the command multiple times with the same `--existing-run-id` is safe (idempotent):
  - `ApifyRun` is upserted (updated if exists)
  - `RawApifyItem` rows are only created if missing (no duplicates)
  - Sample files are overwritten deterministically

---

## Next Steps After Exploration

1. Run the command above for Wendy's Instagram
2. Examine `var/apify_samples/` for actual field structure
3. Update this document with observed fields
4. Update "Missing/Unstable Fields" section
5. Proceed to normalization design (separate task)
