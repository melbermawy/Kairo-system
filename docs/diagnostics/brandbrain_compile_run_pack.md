# BrandBrain Compile Run Diagnostic Pack

**Generated:** 2026-01-15
**Run Type:** Latest SUCCEEDED compile run with real LLM synthesis

---

## 1. Compile Run Metadata

| Field | Value |
|-------|-------|
| compile_run_id | `fb3b8b91-d7bc-4841-8b30-f25d1b49fa46` |
| brand_id | `d8dca5da-6ee2-40a9-bd1d-4a8a065cf556` |
| started_at | 2026-01-15 02:19:53.040907 UTC |
| finished_at | 2026-01-15 02:20:45.720752 UTC |
| **total_duration** | 52.7 seconds |
| status | SUCCEEDED |
| model | gpt-5.2 |
| snapshot_id | `2bac0711-d99b-4a4d-8a8f-ab38705c1893` |

---

## 2. Evidence Decision Summary Per Source

**TTL Configuration:** 24 hours
**Force Refresh:** true (both sources refreshed)

| Source | Decision | Reason | Normalized Items | ApifyRun ID | Has Evidence? |
|--------|----------|--------|------------------|-------------|---------------|
| linkedin.company_posts | REFRESH | force_refresh=True | 0 | `d94568f1-76c2-49dc-bb32-52a579e78866` | NO |
| instagram.reels | REFRESH | force_refresh=True | 6 | `21507181-2da8-4910-850f-b0d31c086b85` | YES |

### Source Diagnostics

```json
{
  "sources_considered": [
    {
      "source": "linkedin.company_posts",
      "enabled": true,
      "freshness_action": "refresh",
      "has_evidence": false,
      "normalized_count": 0,
      "exclusion_reason": "no_normalized_items_from_refresh"
    },
    {
      "source": "instagram.reels",
      "enabled": true,
      "freshness_action": "refresh",
      "has_evidence": true,
      "normalized_count": 6,
      "exclusion_reason": null
    }
  ],
  "sources_with_evidence": ["instagram.reels"],
  "sources_without_evidence": [
    {
      "source": "linkedin.company_posts",
      "reason": "no_normalized_items_from_refresh"
    }
  ]
}
```

**Why LinkedIn has no evidence:** The Apify actor returned an error response `{"message": "No posts found or wrong input", "company_input": "revops-intelligence"}`. The normalization step correctly rejected this as it has no `external_id` for dedupe. This is expected behavior - the LinkedIn company page either has no public posts or the identifier is incorrect.

---

## 3. Evidence Bundle Serialized to LLM Prompt

**Bundle ID:** `c4675491-0881-4936-9252-4d545556072b`
**Total Items:** 6 (all from Instagram)

### Bundle Items (Sanitized, 280 char max)

| # | Platform | Type | Text (truncated) |
|---|----------|------|------------------|
| 1 | instagram | reel | OpenAl's plan to acquire Pinterest is a big move for the start of 2026 #openai #pinterest #acquisition #aisearch #brandstrategy |
| 2 | instagram | reel | ChatGPT's ad leak just called out something we saw coming... #chatgpt #seo #aeo #aisearch #internet |
| 3 | instagram | reel | Let us know in the comments below what your AI predictions for 2025 are #predictions #2026 #ai #aisearch |
| 4 | instagram | reel | The AI healthcare industry is on the rise with ChatGPT and Claude releasing health extensions. Let us know your thoughts #chatgpt #claude #healthcare |
| 5 | instagram | reel | Here's a recap of the biggest AI search moments in 2025 #aisearch #2025recap #google #chatgpt |
| 6 | instagram | reel | Microsoft is begging their users to stop calling them "Microslop" But do you think all AI is created equal? |

**Note:** LinkedIn evidence was NOT included because the source returned 0 normalized items (actor error response).

---

## 4. LLM Prompts

### System Prompt

```
You are a brand strategist AI. Given a company's onboarding answers and evidence
from their social media presence, synthesize a BrandBrain snapshot.

Output valid JSON with this exact structure:
{
  "positioning": {
    "what_we_do": {"value": "string", "confidence": 0.0-1.0},
    "who_for": {"value": "string", "confidence": 0.0-1.0},
    "differentiators": [{"value": "string", "confidence": 0.0-1.0}, ...]
  },
  "voice": {
    "tone_tags": ["tag1", "tag2", ...],
    "cta_policy": {"value": "soft|moderate|aggressive", "confidence": 0.0-1.0},
    "taboos": ["thing to avoid 1", "thing to avoid 2", ...],
    "risk_boundaries": ["boundary 1", "boundary 2", ...]
  },
  "content": {
    "content_pillars": [{"name": "string", "description": "string"}, ...],
    "proof_types": ["case_study", "testimonial", "data", ...]
  },
  "meta": {
    "content_goal": {"value": "string", "confidence": 0.0-1.0}
  }
}

Guidelines:
- differentiators: 3-5 unique selling points based on evidence
- tone_tags: 3-5 adjectives describing brand voice
- taboos: 2-3 things the brand should never say/do
- risk_boundaries: 2-3 limits on controversial topics
- content_pillars: 3-5 main content themes with descriptions
- proof_types: types of social proof that work for this brand
- confidence: 0.9 for strong evidence, 0.7 for inferred, 0.5 for assumed
```

### User Prompt

```
## Onboarding Answers

**What we do:** this brand is a product that provides clients with AEO growth.
**Who for:** consumer brands. digital marketing
**Primary goal:** engagement
**CTA posture:** soft

## Evidence from Social Media (6 items)

1. [instagram/reel] OpenAl's plan to acquire Pinterest is a big move for the start of 2026
#openai #pinterest #acquisition #aisearch #brandstrategy...

2. [instagram/reel] ChatGPT's ad leak just called out something we saw coming…
#chatgpt #seo #aeo #aisearch #internet...

3. [instagram/reel] Let us know in the comments below what your AI predictions for 2025 are
#predictions #2026 #ai #aisearch...

4. [instagram/reel] The AI healthcare industry is on the rise with ChatGPT and Claude
releasing health extensions. Let us know your thoughts
#chatgpt #claude #healthcare #aitech #aisearch...

5. [instagram/reel] Here's a recap of the biggest AI search moments in 2025
#aisearch #2025recap #google #chatgpt...

6. [instagram/reel] Microsoft is begging their users to stop calling them "Microslop"
But do you think all AI is created equal?...

Synthesize a BrandBrain snapshot based on this information. Output only valid JSON.
```

---

## 5. Raw LLM JSON Response (Sanitized)

```json
{
  "positioning": {
    "what_we_do": {
      "value": "A product that helps consumer brands grow through AEO (Answer Engine Optimization) and AI search visibility.",
      "confidence": 0.7
    },
    "who_for": {
      "value": "Consumer brands and their digital marketing teams looking to win visibility in AI search (ChatGPT, Google AI, etc.).",
      "confidence": 0.7
    },
    "differentiators": [
      {
        "value": "AEO-first growth focus (built specifically for AI search/answer engines rather than traditional SEO alone).",
        "confidence": 0.7
      },
      {
        "value": "Fast, trend-driven insights on major AI platforms and search shifts (OpenAI, ChatGPT, Google, Microsoft).",
        "confidence": 0.9
      },
      {
        "value": "Community-led engagement approach that invites predictions, opinions, and comments to spark conversation.",
        "confidence": 0.9
      },
      {
        "value": "Clear, punchy commentary that translates AI news into brand/marketing implications.",
        "confidence": 0.7
      }
    ]
  },
  "voice": {
    "tone_tags": ["insightful", "punchy", "conversational", "trend-savvy", "slightly provocative"],
    "cta_policy": {"value": "soft", "confidence": 0.9},
    "taboos": [
      "Overpromising guaranteed rankings/visibility or implying control over AI platform outcomes",
      "Using fearmongering or doom narratives about AI replacing marketers/brands",
      "Attacking individuals or using derogatory language beyond light, contextual commentary"
    ],
    "risk_boundaries": [
      "Avoid medical/health advice or claims when discussing healthcare AI; keep it to industry commentary",
      "Avoid political partisanship and culture-war framing when covering big tech news",
      "Avoid defamation or unverified allegations about companies; stick to sourced news and clearly labeled opinions"
    ]
  },
  "content": {
    "content_pillars": [
      {"name": "AI Search News & Platform Moves", "description": "Timely takes on major announcements, leaks, acquisitions, and product changes across OpenAI, Google, Microsoft, and others—framed for marketers."},
      {"name": "AEO Strategy & Implications", "description": "What AI search changes mean for consumer brand visibility, content strategy, and digital marketing priorities (AEO vs. SEO)."},
      {"name": "Predictions & Community Debate", "description": "Prompts, polls, and comment-driven posts that ask the audience to share forecasts and hot takes to drive engagement."},
      {"name": "Year-in-Review & Trend Recaps", "description": "Recaps of the biggest AI search moments and lessons learned, packaged as quick, shareable summaries."}
    ],
    "proof_types": ["data", "case_study", "before_after", "expert_quote", "product_demo"]
  },
  "meta": {
    "content_goal": {
      "value": "Drive engagement and conversation while positioning the brand as a go-to source for AI search/AEO insights for consumer brands.",
      "confidence": 0.9
    }
  }
}
```

---

## 6. Final snapshot_json (Sanitized)

```json
{
  "_stub": false,
  "_note": "LLM synthesized",
  "_llm_meta": {
    "provider": "openai",
    "model": "gpt-5.2",
    "used": true,
    "tokens_in": 733,
    "tokens_out": 740,
    "error": null
  },
  "positioning": {
    "what_we_do": {
      "value": "A product that helps consumer brands grow through AEO (Answer Engine Optimization) and AI search visibility.",
      "confidence": 0.7,
      "sources": [{"type": "llm", "id": "tier0.what_we_do"}],
      "locked": false,
      "override_value": null
    },
    "who_for": {
      "value": "Consumer brands and their digital marketing teams looking to win visibility in AI search.",
      "confidence": 0.7,
      "sources": [{"type": "llm", "id": "tier0.who_for"}],
      "locked": false,
      "override_value": null
    },
    "differentiators": [
      {"value": "AEO-first growth focus (built for AI search/answer engines).", "confidence": 0.7},
      {"value": "Fast, trend-driven insights on major AI platforms.", "confidence": 0.9},
      {"value": "Community-led engagement approach.", "confidence": 0.9},
      {"value": "Clear, punchy commentary on AI news.", "confidence": 0.7}
    ]
  },
  "voice": {
    "cta_policy": {
      "value": "soft",
      "confidence": 0.9,
      "sources": [{"type": "llm", "id": "tier0.cta_posture"}],
      "locked": false,
      "override_value": null
    },
    "tone_tags": ["insightful", "punchy", "conversational", "trend-savvy", "slightly provocative"],
    "taboos": [
      "Overpromising guaranteed rankings",
      "Using fearmongering about AI",
      "Attacking individuals"
    ],
    "risk_boundaries": [
      "Avoid medical/health claims",
      "Avoid political partisanship",
      "Avoid defamation"
    ]
  },
  "content": {
    "content_pillars": [
      {"name": "AI Search News & Platform Moves", "description": "Timely takes on announcements..."},
      {"name": "AEO Strategy & Implications", "description": "What AI search changes mean..."},
      {"name": "Predictions & Community Debate", "description": "Prompts, polls, comment-driven..."},
      {"name": "Year-in-Review & Trend Recaps", "description": "Recaps of biggest AI moments..."}
    ],
    "proof_types": ["data", "case_study", "before_after", "expert_quote", "product_demo"]
  },
  "meta": {
    "content_goal": {
      "value": "Drive engagement while positioning the brand as a go-to source for AI search/AEO insights.",
      "confidence": 0.9,
      "sources": [{"type": "llm", "id": "tier0.primary_goal"}],
      "locked": false,
      "override_value": null
    },
    "evidence_summary": {
      "bundle_id": "c4675491-0881-4936-9252-4d545556072b",
      "item_count": 6
    },
    "feature_report_id": "468f443c-3d47-4554-b133-bb9bc536bbb1"
  }
}
```

---

## 7. Field Provenance Table

| Path | Value Source | Evidence-derived? | Notes |
|------|--------------|-------------------|-------|
| `positioning.what_we_do` | **LLM** | Yes | Enhanced from tier0 answer + evidence |
| `positioning.who_for` | **LLM** | Yes | Enhanced from tier0 answer + evidence |
| `positioning.differentiators` | **LLM** | Yes | 4 items generated from evidence patterns |
| `voice.cta_policy` | **LLM** | Yes | Confirmed from tier0 answer |
| `voice.tone_tags` | **LLM** | Yes | 5 tags: insightful, punchy, conversational, trend-savvy, slightly provocative |
| `voice.taboos` | **LLM** | Yes | 3 items generated |
| `voice.risk_boundaries` | **LLM** | Yes | 3 items generated |
| `content.content_pillars` | **LLM** | Yes | 4 pillars with descriptions |
| `content.proof_types` | **LLM** | Yes | 5 types generated |
| `meta.content_goal` | **LLM** | Yes | Enhanced from tier0 answer |
| `meta.evidence_summary` | Deterministic | Yes | Bundle ID + item count |
| `meta.feature_report_id` | Deterministic | Yes | FeatureReport UUID |

### Provenance Legend

| Source Type | Description |
|-------------|-------------|
| **LLM** | Generated by LLM synthesis using onboarding answers + evidence |
| **Deterministic** | Computed from evidence bundle without LLM |
| **Override** | User-provided override value (none in this run) |

---

## 8. LLM Metadata (_llm_meta)

| Field | Value |
|-------|-------|
| provider | `openai` |
| model | `gpt-5.2` |
| **used** | `true` |
| **tokens_in** | 733 |
| **tokens_out** | 740 |
| error | `null` |
| latency_ms | 14,159 ms (~14.2 seconds) |

---

## 9. Stage Timings

| Stage | Duration (ms) | Notes |
|-------|---------------|-------|
| **Total** | 52,679 | ~52.7 seconds |
| Gating | 215 | Check tier0 fields + enabled sources |
| Ingestion Total | 36,906 | Both sources refreshed |
| → linkedin.company_posts | 6,727 | Actor returned error (no posts found) |
| → instagram.reels | 30,088 | 6 items fetched + normalized |
| Bundling | 931 | Select top items from evidence |
| Feature Report | 222 | Compute deterministic stats |
| **LLM Synthesis** | 14,159 | OpenAI API call |
| Snapshot Insert | 131 | DB write |

### Timing Breakdown

```
[Gating: 215ms]──>[Ingestion: 36.9s]──>[Bundling: 931ms]──>[LLM: 14.2s]──>[Save: 131ms]
                       ↓
              linkedin: 6.7s (error)
              instagram: 30.1s (6 items)
```

---

## 10. LLM Configuration at Compile Time

```json
{
  "llm_disabled": false,
  "openai_key_present": true,
  "provider": "openai",
  "heavy_model": "gpt-5.2",
  "fast_model": "gpt-5.2"
}
```

**Log line at compile start:**
```
LLM_CONFIG [compile_run=fb3b8b91-d7bc-4841-8b30-f25d1b49fa46] | llm_disabled=False | openai_key_present=True | provider=openai | heavy_model=gpt-5.2
```

---

## Pass Criteria Checklist

| Criterion | Status | Evidence |
|-----------|--------|----------|
| `_llm_meta.used == true` | **PASS** | `"used": true` in Section 8 |
| `tokens_in > 0` | **PASS** | `tokens_in: 733` |
| `tokens_out > 0` | **PASS** | `tokens_out: 740` |
| `differentiators` exists | **PASS** | 4 items in Section 6 |
| `tone_tags` exists | **PASS** | 5 items in Section 6 |
| `taboos` exists | **PASS** | 3 items in Section 6 |
| `risk_boundaries` exists | **PASS** | 3 items in Section 6 |
| `content_pillars` exists | **PASS** | 4 items in Section 6 |
| `proof_types` exists | **PASS** | 5 items in Section 6 |
| Bundle includes all eligible sources | **PASS** | Instagram included; LinkedIn excluded with explicit reason |
| Exclusion reasons documented | **PASS** | `"no_normalized_items_from_refresh"` in Section 2 |

---

## Appendix: Why LinkedIn Evidence is Missing

The LinkedIn source (`linkedin.company_posts`) is **enabled** and was **refreshed**, but produced 0 normalized items because:

1. **Apify actor returned error response:**
   ```json
   {"message": "No posts found or wrong input", "company_input": "revops-intelligence"}
   ```

2. **Normalization correctly rejected it:**
   - The error response has no `external_id` (required for dedupe)
   - The normalizer raised: `ValueError: Non-web item (platform=linkedin) must have external_id for dedupe`

3. **Root cause:** Either:
   - The LinkedIn company page `revops-intelligence` has no public posts
   - The company slug is incorrect

**This is expected behavior** - the system correctly tracked the source, attempted ingestion, and documented why no evidence was available. The bundler only includes sources with normalized items.

To fix: Verify the LinkedIn company identifier is correct (should be the slug from the company URL, e.g., `company/revops-intelligence`).
