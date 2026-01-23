# Session Handoff

> **When to update this:** Before ending a session mid-task, or when context is getting full.
> **Purpose:** Everything the next Claude instance needs to continue seamlessly.

---

## Last Session Summary

**Date:** 2026-01-23

**What we accomplished:**
- Fixed BrandBrain compile stuck in queue (added sync mode for DEBUG)
- Fixed BYOK token decryption (memoryview → bytes conversion)
- Removed all system .env token fallback (BYOK only, per user request)
- Fixed opportunities regeneration stuck in loading (added sync mode for DEBUG)
- Increased frontend compile timeout to 60s
- Updated STATE.md with all changes

**Where we stopped:**
- All sync mode fixes applied
- Mohamed can now test NoGood brand with BYOK tokens
- User confirmed API keys ARE stored in settings UI

---

## Immediate Next Actions

When resuming, do these in order:

1. Read `.claude/STATE.md` for current status
2. Ask Mohamed about the regeneration test results
3. If successful: Begin Phase 5 (Railway deployment) per `/docs/deployment_prep_plan.md`
4. If issues found: Debug and fix before proceeding

---

## Critical Technical Context

### Sync Mode Pattern (DEBUG only)

Both BrandBrain compile and Opportunities generation now execute synchronously when `settings.DEBUG=True`:

**BrandBrain Compile:**
```python
# kairo/brandbrain/api/views.py
use_sync = settings.DEBUG
result = compile_brandbrain(brand_id, sync=use_sync, user_id=user_id)
```

**Opportunities Generation:**
```python
# kairo/hero/services/today_service.py
def _enqueue_generation_job(...):
    # Job is created
    result = enqueue_opportunities_job(...)

    # DEBUG mode: Execute immediately
    if settings.DEBUG:
        _execute_job_sync(result.job_id, brand_id, user_id=user_id)
```

### BYOK Token Flow

1. Auth middleware extracts user from JWT (`supabase_uid` → User record)
2. `user.id` passed to compile/regenerate functions
3. BYOK token retrieved: `get_user_apify_token(user_id)` → decrypts from `UserAPIKeys`
4. **No fallback to .env tokens** - user explicitly requested this

### Key Files Modified This Session

**Backend:**
- `kairo/brandbrain/api/views.py` - sync mode + user_id extraction
- `kairo/brandbrain/compile/service.py` - user_id parameter
- `kairo/brandbrain/compile/worker.py` - user_id parameter
- `kairo/brandbrain/ingestion/service.py` - BYOK only, no fallback
- `kairo/sourceactivation/live.py` - BYOK only, no fallback
- `kairo/users/encryption.py` - memoryview handling
- `kairo/hero/services/today_service.py` - sync execution in DEBUG mode

**Frontend:**
- `ui/src/lib/api/client.ts` - 60s compile timeout

---

## Important Context That Might Get Lost

**The two repos:**
- Backend: `/Users/mohamed/Documents/Kairo-system` (Django)
- Frontend: `/Users/mohamed/Documents/kairo-frontend/ui/` (Next.js 16)

**Mohamed's rules:**
- He does NOT touch code. Ever.
- He does NOT navigate files. You do everything.
- Long sessions until complete. Match his energy.
- **ALWAYS update STATE.md and HANDOFF.md before session ends or compaction**

**User Database Mapping:**
- User `f4bbe287-c6a0-4302-bf52-b3b36c2b43d9` (mohamedabdouelbermawy@gmail.com)
- Has Supabase UID `21e29821-33fc-47a5-b258-3f2e556654d8`
- Has UserAPIKeys with apify_token_last4=`lsvg`

**Environment:**
- `DJANGO_DEBUG=true` in .env for sync mode
- `ENCRYPTION_KEY` required for BYOK decryption

---

## Open Questions / Decisions Needed

1. **Compile UI redirect:** After successful compile, UI may not redirect properly. May need frontend fix.
2. **Production workers:** In production (Railway), will need background workers for async execution. Sync mode is dev-only.

---

## Mental Model to Restore

The big picture: Kairo scrapes social media for trending content, then uses LLMs to synthesize brand-relevant opportunities.

**Pipeline:**
```
Brand Onboarding → BrandBrain Compile → Source Activation → Opportunity Synthesis → Today Board
```

**Critical invariant:** In production, async workers execute jobs. In DEBUG mode, jobs execute synchronously (no worker needed). This was causing the "stuck in queue/loading" issues.

**BYOK invariant:** All external API calls (Apify, OpenAI) must use user's BYOK tokens. No fallback to system .env tokens.

**Deployment plan remaining:**
- Phase 5: Railway (backend)
- Phase 6: Vercel (frontend)
