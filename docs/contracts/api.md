# Kairo Hero Loop API Contracts

PR-2: DTOs + Validation Layer + API Contracts

This document defines the HTTP API contracts for the Kairo Hero Loop.
All endpoints return JSON and validate responses against Pydantic DTOs defined in `kairo/hero/dto.py`.

## Base URL

All endpoints are prefixed with `/hero/api/`.

## Authentication

Authentication is planned for future PRs. Currently, all endpoints are open.

---

## Versioning & Path Scoping

**Current Design Choices (PRD-1):**

1. **Unversioned URLs**: URLs do not include a version prefix (e.g., no `/v1/`).
   - Rationale: PRD-1 is internal-only; we'll add versioning when external API is exposed.

2. **Package/Variant endpoints are not brand-scoped in path**:
   - `GET /api/packages/{package_id}/` — not `/api/brands/{brand_id}/packages/{package_id}/`
   - `PATCH /api/variants/{variant_id}/` — not brand-scoped in URL
   - **Rationale**: Packages and variants have FKs to brand in the DB, so scoping is enforced at the data layer. URL brevity is preferred for internal use.
   - **Note**: This may change when we expose these externally or add multi-tenant isolation at the API layer.

3. **Today Board and Package Creation are brand-scoped**:
   - `GET /api/brands/{brand_id}/today/` — brand context is required
   - `POST /api/brands/{brand_id}/opportunities/{opportunity_id}/packages/` — brand provides context

This design is documented in [kairo/hero/urls.py](../../kairo/hero/urls.py).

---

## Endpoints

### Today Board

#### GET /hero/api/brands/{brand_id}/today/

Retrieves the Today board for a brand, containing prioritized opportunities.

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| brand_id | UUID | Brand identifier |

**Response DTO:** `TodayBoardDTO`

**Response Fields:**
| Field | Type | Description |
|-------|------|-------------|
| brand_id | UUID | Brand identifier |
| snapshot | BrandSnapshotDTO | Point-in-time brand context |
| opportunities | list[OpportunityDTO] | Prioritized opportunities |
| meta | TodayBoardMetaDTO | Generation metadata |

**Example Response:**
```json
{
  "brand_id": "550e8400-e29b-41d4-a716-446655440000",
  "snapshot": {
    "brand_id": "550e8400-e29b-41d4-a716-446655440000",
    "brand_name": "Test Brand",
    "positioning": "The leading AI platform",
    "pillars": [],
    "personas": [],
    "voice_tone_tags": ["professional", "innovative"],
    "taboos": []
  },
  "opportunities": [
    {
      "id": "...",
      "brand_id": "550e8400-e29b-41d4-a716-446655440000",
      "title": "AI Trends 2025",
      "angle": "Industry perspective on emerging AI capabilities",
      "type": "trend",
      "primary_channel": "linkedin",
      "score": 85.0,
      "score_explanation": "High relevance to brand positioning",
      "source": "industry_analysis",
      "source_url": null,
      "persona_id": null,
      "pillar_id": null,
      "suggested_channels": ["linkedin", "x"],
      "is_pinned": false,
      "is_snoozed": false,
      "snoozed_until": null,
      "created_via": "ai_suggested",
      "created_at": "2025-01-15T10:00:00Z",
      "updated_at": "2025-01-15T10:00:00Z"
    }
  ],
  "meta": {
    "generated_at": "2025-01-15T10:00:00Z",
    "source": "hero_f1",
    "degraded": false,
    "notes": [],
    "opportunity_count": 1,
    "dominant_pillar": null,
    "dominant_persona": null,
    "channel_mix": {"linkedin": 1}
  }
}
```

---

#### POST /hero/api/brands/{brand_id}/today/regenerate/

Regenerates the Today board, fetching fresh opportunities.

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| brand_id | UUID | Brand identifier |

**Request Body:** None required

**Response DTO:** `RegenerateResponseDTO`

**Response Fields:**
| Field | Type | Description |
|-------|------|-------------|
| status | string | "regenerated" |
| today_board | TodayBoardDTO | The regenerated board |

---

### Packages

#### POST /hero/api/brands/{brand_id}/opportunities/{opportunity_id}/packages/

Creates a content package from an opportunity.

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| brand_id | UUID | Brand identifier |
| opportunity_id | UUID | Opportunity identifier |

**Request Body:** None required (opportunity provides context)

**Response DTO:** `CreatePackageResponseDTO`

**Response Fields:**
| Field | Type | Description |
|-------|------|-------------|
| status | string | "created" |
| package | ContentPackageDTO | The created package |

---

#### GET /hero/api/packages/{package_id}/

Retrieves a content package by ID.

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| package_id | UUID | Package identifier |

**Response DTO:** `ContentPackageDTO`

**Response Fields:**
| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Package identifier |
| brand_id | UUID | Brand identifier |
| title | string | Package title |
| status | PackageStatus | draft, in_review, scheduled, published, archived |
| origin_opportunity_id | UUID | null | Source opportunity |
| persona_id | UUID | null | Target persona |
| pillar_id | UUID | null | Content pillar |
| channels | list[Channel] | Target channels |
| planned_publish_start | datetime | null | Planned start |
| planned_publish_end | datetime | null | Planned end |
| owner_user_id | UUID | null | Owner |
| notes | string | null | Notes |
| created_via | CreatedVia | manual, ai_suggested, imported |
| created_at | datetime | Creation timestamp |
| updated_at | datetime | Last update timestamp |

---

### Variants

#### POST /hero/api/packages/{package_id}/variants/generate/

Generates content variants for a package across its target channels.

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| package_id | UUID | Package identifier |

**Request Body:** None required

**Response DTO:** `GenerateVariantsResponseDTO`

**Response Fields:**
| Field | Type | Description |
|-------|------|-------------|
| status | string | "generated" |
| package_id | UUID | Package identifier |
| variants | list[VariantDTO] | Generated variants |
| count | int | Number of variants |

---

#### GET /hero/api/packages/{package_id}/variants/

Lists all variants for a package.

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| package_id | UUID | Package identifier |

**Response DTO:** `VariantListDTO`

**Response Fields:**
| Field | Type | Description |
|-------|------|-------------|
| package_id | UUID | Package identifier |
| variants | list[VariantDTO] | Variants for this package |
| count | int | Number of variants |

---

#### PATCH /hero/api/variants/{variant_id}/

Updates a variant's content or status.

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| variant_id | UUID | Variant identifier |

**Request DTO:** `VariantUpdateDTO`

**Request Fields (all optional):**
| Field | Type | Description |
|-------|------|-------------|
| body | string | null | Updated body text |
| call_to_action | string | null | Updated CTA |
| status | VariantStatus | null | New status |

**Response DTO:** `VariantDTO`

---

### Decisions

#### POST /hero/api/opportunities/{opportunity_id}/decision/

Records a user decision on an opportunity (pin, snooze, ignore).

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| opportunity_id | UUID | Opportunity identifier |

**Request DTO:** `DecisionRequestDTO`

**Request Fields:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| decision_type | DecisionType | Yes | Type of decision |
| reason | string | null | No | User-provided reason |
| metadata | dict | No | Additional context |

**Valid Decision Types for Opportunities:**
- `opportunity_pinned`
- `opportunity_snoozed`
- `opportunity_ignored`

**Response DTO:** `DecisionResponseDTO`

**Response Fields:**
| Field | Type | Description |
|-------|------|-------------|
| status | string | "accepted" |
| decision_type | DecisionType | Recorded decision |
| object_type | string | "opportunity" |
| object_id | UUID | Opportunity ID |
| recorded_at | datetime | When recorded |

---

#### POST /hero/api/packages/{package_id}/decision/

Records a user decision on a package.

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| package_id | UUID | Package identifier |

**Request DTO:** `DecisionRequestDTO`

**Valid Decision Types for Packages:**
- `package_created`
- `package_approved`

**Response DTO:** `DecisionResponseDTO` (object_type: "package")

---

#### POST /hero/api/variants/{variant_id}/decision/

Records a user decision on a variant.

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| variant_id | UUID | Variant identifier |

**Request DTO:** `DecisionRequestDTO`

**Valid Decision Types for Variants:**
- `variant_edited`
- `variant_approved`
- `variant_rejected`

**Response DTO:** `DecisionResponseDTO` (object_type: "variant")

---

## Enums

### Channel
Content distribution channels.
- `linkedin`
- `x`
- `youtube`
- `instagram`
- `tiktok`
- `newsletter`

### OpportunityType
Types of content opportunities.
- `trend` - Trending topic
- `evergreen` - Timeless content
- `competitive` - Competitor-inspired
- `campaign` - Campaign-driven

### PackageStatus
Content package lifecycle states.
- `draft`
- `in_review`
- `scheduled`
- `published`
- `archived`

### VariantStatus
Content variant states.
- `draft`
- `edited`
- `approved`
- `scheduled`
- `published`
- `rejected`

### DecisionType
User interaction types.
- `opportunity_pinned`
- `opportunity_snoozed`
- `opportunity_ignored`
- `package_created`
- `package_approved`
- `variant_edited`
- `variant_approved`
- `variant_rejected`

### CreatedVia
Entity creation source.
- `manual`
- `ai_suggested`
- `imported`

---

## Error Responses

All hero API endpoints return errors in a standardized envelope format:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Human-readable summary of what went wrong",
    "details": { "field": "brand_id", "value": "not-a-uuid" }
  }
}
```

### Error Envelope Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| code | string | Yes | Machine-readable error code |
| message | string | Yes | Human-readable error description |
| details | object | No | Optional context (field names, values, etc.) |

### Error Codes

| Code | Description |
|------|-------------|
| `invalid_uuid` | Path parameter is not a valid UUID format |
| `invalid_json` | Request body is not valid JSON |
| `validation_error` | Request body failed DTO validation |

### Example Error Responses

**Invalid UUID:**
```json
{
  "error": {
    "code": "invalid_uuid",
    "message": "Invalid brand_id format",
    "details": { "field": "brand_id", "value": "not-a-uuid" }
  }
}
```

**Invalid JSON:**
```json
{
  "error": {
    "code": "invalid_json",
    "message": "Request body is not valid JSON"
  }
}
```

**Validation Error:**
```json
{
  "error": {
    "code": "validation_error",
    "message": "Request body validation failed",
    "details": { "error": "1 validation error for DecisionRequestDTO..." }
  }
}
```

### HTTP Status Codes

| Code | Description |
|------|-------------|
| 200 | Success |
| 201 | Created (for POST that creates resources) |
| 400 | Bad Request (validation error, invalid JSON, invalid UUID) |
| 404 | Not Found (resource doesn't exist) |
| 405 | Method Not Allowed |
| 500 | Internal Server Error |

---

## DTO Reference

All DTOs are defined in `kairo/hero/dto.py`. Key DTOs:

| DTO | Purpose |
|-----|---------|
| `TodayBoardDTO` | Today board response |
| `BrandSnapshotDTO` | Brand context for LLM prompts |
| `OpportunityDTO` | Persisted opportunity |
| `ContentPackageDTO` | Content package |
| `VariantDTO` | Content variant |
| `VariantUpdateDTO` | Variant patch request |
| `VariantListDTO` | Variant list response |
| `DecisionRequestDTO` | Decision request body |
| `DecisionResponseDTO` | Decision response |
| `RegenerateResponseDTO` | Regenerate response |
| `CreatePackageResponseDTO` | Package creation response |
| `GenerateVariantsResponseDTO` | Variant generation response |

---

## Contract Guarantees

1. **Field Stability**: Once a DTO field is published, it cannot be renamed or removed without a migration plan.
2. **Type Safety**: All responses are validated against Pydantic DTOs before returning.
3. **Enum Values**: Enum values are stable and additive-only (new values may be added, existing values won't change).
4. **UUID Format**: All IDs are UUIDs in standard string format.
5. **Datetime Format**: All datetimes are ISO 8601 format in UTC.

---

## Testing

Contract tests are in `tests/test_http_contracts.py`. These tests verify:
- Response shapes match DTOs
- Required fields are present
- Enum values are valid
- Error responses are properly formatted

Run tests with:
```bash
pytest tests/test_http_contracts.py -v
```
