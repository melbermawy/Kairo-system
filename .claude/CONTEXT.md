# Kairo Context File

> **Purpose:** This file exists for Claude to read when context compacts. It contains everything Claude needs to work effectively on Kairo without asking Mohamed to re-explain things.

---

## Mohamed's Working Style

**READ THIS FIRST - these are non-negotiable:**

1. **Mohamed does NOT touch code.** Ever. Don't ask him to create files, edit files, run commands, or navigate the codebase. You do all of that.

2. **Mohamed does NOT navigate files.** Don't ask him to "open X file" or "check Y". You read files, you explore, you figure it out.

3. **Long session mentality.** Mohamed works in intense, focused sessions until things are done. He's a 10x engineer who ships complete features in a day. Match that energy.

4. **Quality bar is high.** Don't half-ass things. Don't say "we could improve this later". Do it right the first time.

5. **Be proactive.** If something needs to be done, do it. Don't ask for permission on obvious next steps.

---

## The Repositories

**CRITICAL: Kairo is a TWO-REPO application. Never forget the frontend.**

### Backend: Kairo-system
- **Location:** `/Users/mohamed/Documents/Kairo-system`
- **Framework:** Django 5.0 (Python)
- **What it does:** API server, background jobs, LLM orchestration, Apify integration

### Frontend: kairo-frontend
- **Location:** `/Users/mohamed/Documents/kairo-frontend`
- **Framework:** Next.js 16 with React 19, Tailwind CSS 4
- **Structure:** The actual Next.js app is in the `ui/` subfolder
- **What it does:** User interface, brand onboarding wizard, Today board, opportunity display

**When working on features, you almost always need to touch BOTH repos.**

---

## Core Application Flow

This is Kairo's main pipeline. Understand this deeply:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           BRAND ONBOARDING                               │
│  User fills out brand info → Stored as OnboardingAnswers                │
│  (name, positioning, pillars, target audience, social URLs)             │
└─────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                           BRAND BRAIN COMPILATION                        │
│  OnboardingAnswers → LLM synthesis → BrandBrainSnapshot                 │
│  Creates: voice profile, content pillars, audience insights             │
│  Location: kairo/brandbrain/                                            │
└─────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                           SOURCE ACTIVATION                              │
│  BrandBrainSnapshot → SeedPack derivation → Apify actor execution       │
│                                                                          │
│  Key components:                                                         │
│  • Query Planner (kairo/sourceactivation/query_planner.py)              │
│    - LLM generates search queries from brand context                     │
│    - Mixes with TREND_BANK for guaranteed viral content discovery       │
│                                                                          │
│  • Recipes (kairo/sourceactivation/recipes.py)                          │
│    - IG-1: Instagram hashtag → reel enrichment (2-stage)                │
│    - IG-3: Instagram search → reel enrichment (2-stage)                 │
│    - TT-1: TikTok search (single-stage)                                 │
│    - YT-1: YouTube search (single-stage)                                │
│    - LI-1: LinkedIn posts (single-stage)                                │
│                                                                          │
│  • Live execution (kairo/sourceactivation/live.py)                      │
│    - Orchestrates recipe execution with budget controls                  │
│    - 2-stage recipes: Stage 1 (discovery) → Stage 2 (enrichment)        │
│                                                                          │
│  Output: EvidenceBundle with normalized EvidenceItemData                │
└─────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                        OPPORTUNITY SYNTHESIS                             │
│  EvidenceBundle + BrandBrainSnapshot → 4-stage LLM pipeline             │
│                                                                          │
│  Stage 1 (Kernels): Extract opportunity seeds from evidence             │
│  Stage 2 (Consolidate): Merge similar kernels                           │
│  Stage 3 (Expand): Full opportunity generation (parallel, bottleneck)   │
│  Stage 4 (Score): Rank opportunities by relevance/impact                │
│                                                                          │
│  Location: kairo/hero/synthesis/                                        │
│  Output: List of Opportunity objects with hooks, angles, evidence       │
└─────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                            TODAY BOARD                                   │
│  Frontend polls /api/brands/{id}/today/ for opportunities               │
│  Displays opportunity cards with hooks, evidence, actions               │
│  "Regenerate" button triggers new SourceActivation + Synthesis          │
│  Location: kairo-frontend/ui/src/app/brands/[brandId]/today/            │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Key Technical Details

### Background Jobs
- **NOT Celery/Redis.** Kairo uses a database-backed job queue.
- Jobs stored in `OpportunitiesJob` table
- Same Django process handles web requests AND job polling
- Location: `kairo/hero/jobs/queue.py`

### 2-Stage Acquisition (Instagram)
- **INVARIANT SA-1:** Instagram MUST use 2-stage acquisition
- Stage 1: Discovery (hashtag/search scraper) → gets post URLs
- Stage 2: Enrichment (reel scraper) → gets full content + transcripts
- **INVARIANT SA-2:** Stage 2 inputs MUST come from Stage 1 outputs (no hardcoding)

### Budget System (currently active, will be removed with BYOK)
- Location: `kairo/sourceactivation/budget.py`
- Per-regeneration cap: $0.25
- Daily cap: $0.50
- Early-exit thresholds for evidence sufficiency

### LLM Integration
- Uses OpenAI models (gpt-4o, gpt-4o-mini)
- Config: `KAIRO_LLM_MODEL_FAST` and `KAIRO_LLM_MODEL_HEAVY`
- Location: `kairo/core/llm/`

### Apify Integration
- Client: `kairo/integrations/apify/client.py`
- Actors used: Instagram scrapers, TikTok scraper, YouTube scraper
- Actor documentation: `docs/apify_actor_samples.md`

---

## Current Work: Deployment Preparation

**Master plan:** `/docs/deployment_prep_plan.md`

The deployment prep has 6 phases:

| Phase | What | Status |
|-------|------|--------|
| 1. Authentication | Supabase Auth, user accounts | Not started |
| 2. BYOK | Users bring own API keys | Not started |
| 3. Speed & Quality | Remove caps, parallel execution, TikTok Trends | Not started |
| 4. Frontend Polish | Onboarding UX, Today board states | Not started |
| 5. Data Migration | Preserve Goodie AI brand | Not started |
| 6. Deployment | Railway + Vercel + Supabase | Not started |

**Supabase credentials (already set up for DB):**
- URL: `https://qtohqspbwroqibnjnbue.supabase.co`
- Service Role Key: In `.env` file
- Need to get: Anon/public key for frontend

---

## File Locations Quick Reference

### Backend (Kairo-system)
```
kairo/
├── core/               # Shared utilities, LLM client, guardrails
├── brandbrain/         # Brand compilation pipeline
├── sourceactivation/   # External trend discovery (Apify)
│   ├── query_planner.py   # LLM query generation
│   ├── recipes.py         # Actor configurations
│   ├── live.py            # Execution orchestration
│   ├── normalizers.py     # Output normalization
│   └── budget.py          # Cost controls
├── hero/               # Opportunity synthesis
│   ├── synthesis/         # 4-stage LLM pipeline
│   └── jobs/              # Background job queue
└── integrations/
    └── apify/             # Apify client wrapper
```

### Frontend (kairo-frontend/ui/)
```
src/
├── app/
│   ├── brands/[brandId]/
│   │   ├── today/         # Today board (opportunities)
│   │   ├── onboarding/    # Brand setup wizard
│   │   └── strategy/      # Brand strategy view
│   └── (auth)/            # Login/signup (to be created)
├── components/
│   ├── onboarding/        # Wizard components
│   └── today/             # Opportunity cards, drawer
└── lib/
    ├── api/               # API client with Zod validation
    └── env.ts             # Environment config
```

---

## Decisions Already Made

These are settled. Don't re-discuss or propose alternatives:

1. **Auth:** Supabase Auth (JWT-based)
2. **Hosting:** Railway (backend) + Vercel (frontend)
3. **Database:** Supabase PostgreSQL (already in use)
4. **BYOK model:** Users must provide their own Apify + OpenAI keys
5. **Demo mode:** Fixture data for users without keys
6. **TikTok Trends:** Adding `clockworks/tiktok-trends-scraper` as TT-TRENDS recipe

---

## When You Resume After Context Compaction

1. **Read this file first** - it has everything you need
2. **Check `/docs/deployment_prep_plan.md`** - for detailed phase requirements
3. **Remember the frontend exists** at `/Users/mohamed/Documents/kairo-frontend`
4. **Never ask Mohamed to touch code or files** - you do all the work
5. **Check STATE.md** (if it exists) for where we left off
