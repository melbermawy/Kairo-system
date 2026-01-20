# Frontend–Backend Convergence Plan (frontend repo: kairo-frontend)

This plan converges the frontend onto the backend contract defined in opportunities_v1_prd.md.
No backend redesign. No invented fields. No fake semantics.

## North Star

Single source of truth = backend TodayBoardDTO + OpportunityDTO.

The frontend becomes:
- a thin renderer
- plus one real action: regenerate

Everything else that is fake, speculative, or unbacked by backend data is removed or hidden.

The UI keeps its visual quality — but the engine underneath becomes real.

---

## Phase 0 — Decide What Dies (Product Decision, Not Technical)

The current frontend Opportunity contract is fiction. The backend does not (and should not) produce many of these fields yet.

### Keep (maps cleanly to backend)
- Card layout and drawer layout
- Score badge
- Opportunity type badge
- Platform badges
- "Why now" section (single string, not bullets)
- Evidence list UI driven by evidence_preview[]
- Persona / pillar resolution via snapshot data if needed

### Remove or hide (no backend source)
- lifecycle + sparkline
- trend kernel chip
- weekly metrics / targets
- format_target
- signals block
- any "status" enum beyond what the board already encodes

**Rule:**
If the backend does not send it → the UI does not imply it exists.

This is how you ship without lying.

---

## Phase 1 — Replace mockApi With Real Backend API

### Backend endpoints used
- `GET /api/brands/{brand_id}/today/`
- `POST /api/brands/{brand_id}/today/regenerate/`

Nothing else.

### Frontend data model strategy

Stop using the fake `ui/src/contracts/index.ts` for opportunities.

Instead:
- Create `backendContracts.ts` (or similar) containing:
  - TodayBoardDTO
  - OpportunityDTO
  - EvidencePreviewDTO
- These types must match backend DTOs exactly.
- No enrichment. No invented fields.

Optionally add a thin UI adapter layer if you want to rename labels (e.g. `angle` → "Hook"), but do not rename the data field.

### Mapping examples (allowed)
- `angle` → render label "Angle" or "Hook"
- `primary_channel` + `suggested_channels` → platform badges
- `why_now` → drawer paragraph
- `evidence_preview[]` → evidence tiles

### Kill N+1 hydration

Current UI:
- list opportunities
- then hydrate each opportunity individually

New model:
- One GET returns everything needed
- Cards and drawer render from the same object
- No extra fetch on click (initially)

---

## Phase 2 — Make Evidence UI Real (But Modest)

Backend already gives `evidence_preview[]` (PR-5). That's enough.

Each evidence tile uses:
- `platform`
- `canonical_url`
- `author_ref`
- `text_snippet`
- `has_transcript`

What you do not have yet:
- thumbnails
- detailed metrics
- clusters / content taxonomy

So:
- show platform icon + author + snippet + link
- optional "Transcript available" badge

This is the correct MVP evidence experience.

---

## Phase 3 — Regenerate + Async State Handling

Backend already supports:
- async jobs
- caching
- deterministic states

### Frontend behavior:
1. Load Today page → `GET /today`
2. If `state = generating` → poll every N seconds (cheap GET)
3. If `state = ready | insufficient_evidence | failed` → stop polling
4. Regenerate button:
   - calls `POST /today/regenerate`
   - then begins polling

**Hard requirement:** polling must stop deterministically. No runaway loops.

---

## Phase 4 — End-to-End Real Brand Test Loop

This is your final confidence check.

### Steps:
1. Rename your fake brand row to Goodie AI (same brand_id)
2. Ensure a valid BrandBrainSnapshot exists
3. Open Today page
4. First GET:
   - auto-enqueues fixture-only run if none exists
5. Click Regenerate:
   - triggers live-cap-limited run (if enabled)
6. Verify:
   - opportunity cards render
   - drawer opens
   - evidence previews appear
   - no fake UI elements remain

This brand becomes your golden smoke test.
