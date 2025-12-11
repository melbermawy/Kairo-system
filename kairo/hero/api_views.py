"""
Hero Loop API Views.

PR-2: DTOs + Validation Layer + API Contracts.

These views return stubbed data validated against DTOs.
No business logic, no DB writes, no engines, no LLM calls.

Stub only – real implementation comes in PR-3.

All responses must validate against the appropriate DTO before returning.
"""

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from .dto import (
    BrandSnapshotDTO,
    Channel,
    ContentPackageDTO,
    CreatePackageResponseDTO,
    CreatedVia,
    DecisionRequestDTO,
    DecisionResponseDTO,
    DecisionType,
    GenerateVariantsResponseDTO,
    OpportunityDTO,
    OpportunityType,
    PackageStatus,
    PersonaDTO,
    PillarDTO,
    RegenerateResponseDTO,
    TodayBoardDTO,
    TodayBoardMetaDTO,
    VariantDTO,
    VariantListDTO,
    VariantStatus,
    VariantUpdateDTO,
)


# =============================================================================
# ERROR ENVELOPE HELPER
# =============================================================================


def error_response(
    code: str,
    message: str,
    status: int = 400,
    details: dict[str, Any] | None = None,
) -> JsonResponse:
    """
    Create a standardized error response envelope.

    All hero API errors use this format:
    {
        "error": {
            "code": "validation_error",
            "message": "Human-readable summary",
            "details": { ...optional extra fields... }
        }
    }

    Args:
        code: Machine-readable error code (e.g., "validation_error", "invalid_uuid")
        message: Human-readable error message
        status: HTTP status code (default 400)
        details: Optional dict with additional error context

    Returns:
        JsonResponse with error envelope
    """
    envelope: dict[str, Any] = {
        "error": {
            "code": code,
            "message": message,
        }
    }
    if details:
        envelope["error"]["details"] = details

    return JsonResponse(envelope, status=status)


# =============================================================================
# STUB DATA GENERATORS
# =============================================================================


def _stub_brand_id() -> UUID:
    """Return a consistent stub brand ID for testing."""
    return UUID("12345678-1234-5678-1234-567812345678")


def _stub_persona() -> PersonaDTO:
    """Generate a stub persona."""
    return PersonaDTO(
        id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        name="RevOps Director",
        role="Director of Revenue Operations",
        summary="Senior revenue operations leader at mid-market B2B SaaS companies",
        priorities=["pipeline accuracy", "sales efficiency", "data hygiene"],
        pains=["tool sprawl", "attribution confusion", "forecast misses"],
        success_metrics=["pipeline velocity", "forecast accuracy", "rep productivity"],
        channel_biases={"linkedin": "professional, no memes"},
    )


def _stub_pillar() -> PillarDTO:
    """Generate a stub pillar."""
    return PillarDTO(
        id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        name="Attribution Reality",
        category="authority",
        description="Content about the messy truth of B2B attribution",
        priority_rank=1,
        is_active=True,
    )


def _stub_brand_snapshot(brand_id: UUID) -> BrandSnapshotDTO:
    """Generate a stub brand snapshot."""
    return BrandSnapshotDTO(
        brand_id=brand_id,
        brand_name="Acme Analytics",
        positioning="The attribution platform that tells you the truth, even when it hurts",
        pillars=[_stub_pillar()],
        personas=[_stub_persona()],
        voice_tone_tags=["direct", "data-driven", "slightly irreverent"],
        taboos=["never bash competitors by name", "no FUD marketing"],
    )


def _stub_opportunity(brand_id: UUID, index: int = 0) -> OpportunityDTO:
    """Generate a stub opportunity."""
    now = datetime.now(timezone.utc)
    titles = [
        "LinkedIn attribution debate is heating up",
        "New Gartner report on RevOps tech stack",
        "Confessional: Our biggest attribution mistake",
        "Behind the scenes: How we fixed our pipeline",
        "Hot take: Multi-touch is dead",
        "Customer story: Acme helped us 3x pipeline",
    ]
    return OpportunityDTO(
        id=UUID(f"cccccccc-cccc-cccc-cccc-{index:012d}"),
        brand_id=brand_id,
        title=titles[index % len(titles)],
        angle="There's a viral thread about attribution models that perfectly aligns with our positioning. Great moment to share our contrarian take.",
        type=OpportunityType.TREND if index % 2 == 0 else OpportunityType.EVERGREEN,
        primary_channel=Channel.LINKEDIN,
        score=85 - (index * 5),
        score_explanation="High relevance to core persona, trending topic, aligns with pillar",
        source="LinkedIn trending",
        source_url="https://linkedin.com/posts/example",
        persona_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        pillar_id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        suggested_channels=[Channel.LINKEDIN, Channel.X],
        is_pinned=index == 0,
        is_snoozed=False,
        snoozed_until=None,
        created_via=CreatedVia.AI_SUGGESTED,
        created_at=now,
        updated_at=now,
    )


def _stub_today_board(brand_id: UUID) -> TodayBoardDTO:
    """Generate a stub Today board."""
    now = datetime.now(timezone.utc)
    opportunities = [_stub_opportunity(brand_id, i) for i in range(6)]

    return TodayBoardDTO(
        brand_id=brand_id,
        snapshot=_stub_brand_snapshot(brand_id),
        opportunities=opportunities,
        meta=TodayBoardMetaDTO(
            generated_at=now,
            source="hero_f1",
            degraded=False,
            notes=["Stub data for PR-2 contract testing"],
            opportunity_count=len(opportunities),
            dominant_pillar="Attribution Reality",
            dominant_persona="RevOps Director",
            channel_mix={"linkedin": 5, "x": 1},
        ),
    )


def _stub_package(brand_id: UUID, opportunity_id: UUID) -> ContentPackageDTO:
    """Generate a stub content package."""
    now = datetime.now(timezone.utc)
    return ContentPackageDTO(
        id=UUID("dddddddd-dddd-dddd-dddd-dddddddddddd"),
        brand_id=brand_id,
        title="Attribution Reality Check",
        status=PackageStatus.DRAFT,
        origin_opportunity_id=opportunity_id,
        persona_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        pillar_id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        channels=[Channel.LINKEDIN, Channel.X],
        planned_publish_start=None,
        planned_publish_end=None,
        owner_user_id=None,
        notes=None,
        created_via=CreatedVia.AI_SUGGESTED,
        created_at=now,
        updated_at=now,
    )


def _stub_variant(package_id: UUID, brand_id: UUID, channel: Channel, index: int = 0) -> VariantDTO:
    """Generate a stub variant."""
    now = datetime.now(timezone.utc)

    bodies = {
        Channel.LINKEDIN: "Let's talk about the elephant in the room: your attribution model is probably lying to you.\n\nI've spent 10 years in RevOps, and here's what I've learned:\n\n• First-touch attribution? Overstates top-of-funnel.\n• Last-touch? Gives all credit to the closer.\n• Multi-touch? Still just guessing, but with more math.\n\nThe truth is messier. The best teams I've worked with don't obsess over perfect attribution. They focus on directional signals and iterate fast.\n\nWhat's your take? Drop your attribution horror stories below. 👇",
        Channel.X: "Hot take: Your attribution model is lying to you.\n\nFirst-touch overstates TOF.\nLast-touch credits the closer.\nMulti-touch? Educated guessing.\n\nThe best RevOps teams focus on directional signals, not perfect measurement.\n\nWhat's your attribution horror story? 🧵",
    }

    return VariantDTO(
        id=UUID(f"eeeeeeee-eeee-eeee-eeee-{index:012d}"),
        package_id=package_id,
        brand_id=brand_id,
        channel=channel,
        status=VariantStatus.DRAFT,
        pattern_template_id=UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
        body=bodies.get(channel, "Stub variant body"),
        call_to_action="Share your story in the comments",
        generated_by_model="gpt-4",
        proposed_at=now,
        scheduled_publish_at=None,
        published_at=None,
        eval_score=None,
        eval_notes=None,
        created_at=now,
        updated_at=now,
    )


# =============================================================================
# TODAY BOARD ENDPOINTS
# =============================================================================


@require_GET
def get_today_board(request: HttpRequest, brand_id: str) -> JsonResponse:
    """
    GET /api/brands/{brand_id}/today

    Returns the Today board for a brand.
    Stub only – real implementation comes in PR-3.
    """
    try:
        brand_uuid = UUID(brand_id)
    except ValueError:
        return error_response(
            code="invalid_uuid",
            message="Invalid brand_id format",
            details={"field": "brand_id", "value": brand_id},
        )

    dto = _stub_today_board(brand_uuid)
    return JsonResponse(dto.model_dump(mode="json"))


@csrf_exempt
@require_http_methods(["POST"])
def regenerate_today_board(request: HttpRequest, brand_id: str) -> JsonResponse:
    """
    POST /api/brands/{brand_id}/today/regenerate

    Triggers regeneration of the Today board.
    Stub only – real implementation comes in PR-3.
    """
    try:
        brand_uuid = UUID(brand_id)
    except ValueError:
        return error_response(
            code="invalid_uuid",
            message="Invalid brand_id format",
            details={"field": "brand_id", "value": brand_id},
        )

    today_board = _stub_today_board(brand_uuid)
    dto = RegenerateResponseDTO(
        status="regenerated",
        today_board=today_board,
    )
    return JsonResponse(dto.model_dump(mode="json"))


# =============================================================================
# PACKAGE ENDPOINTS
# =============================================================================


@csrf_exempt
@require_http_methods(["POST"])
def create_package_from_opportunity(
    request: HttpRequest, brand_id: str, opportunity_id: str
) -> JsonResponse:
    """
    POST /api/brands/{brand_id}/opportunities/{opportunity_id}/packages

    Creates a content package from an opportunity.
    Stub only – real implementation comes in PR-3.
    """
    try:
        brand_uuid = UUID(brand_id)
    except ValueError:
        return error_response(
            code="invalid_uuid",
            message="Invalid brand_id format",
            details={"field": "brand_id", "value": brand_id},
        )
    try:
        opportunity_uuid = UUID(opportunity_id)
    except ValueError:
        return error_response(
            code="invalid_uuid",
            message="Invalid opportunity_id format",
            details={"field": "opportunity_id", "value": opportunity_id},
        )

    package = _stub_package(brand_uuid, opportunity_uuid)
    dto = CreatePackageResponseDTO(
        status="created",
        package=package,
    )
    return JsonResponse(dto.model_dump(mode="json"), status=201)


@require_GET
def get_package(request: HttpRequest, package_id: str) -> JsonResponse:
    """
    GET /api/packages/{package_id}

    Returns a content package by ID.
    Stub only – real implementation comes in PR-3.
    """
    try:
        package_uuid = UUID(package_id)
    except ValueError:
        return error_response(
            code="invalid_uuid",
            message="Invalid package_id format",
            details={"field": "package_id", "value": package_id},
        )

    # Stub: use consistent brand and opportunity IDs
    brand_id = _stub_brand_id()
    opportunity_id = UUID("cccccccc-cccc-cccc-cccc-000000000000")

    package = _stub_package(brand_id, opportunity_id)
    # Override the ID to match the request
    package_dict = package.model_dump(mode="json")
    package_dict["id"] = str(package_uuid)

    return JsonResponse(package_dict)


# =============================================================================
# VARIANT ENDPOINTS
# =============================================================================


@csrf_exempt
@require_http_methods(["POST"])
def generate_variants(request: HttpRequest, package_id: str) -> JsonResponse:
    """
    POST /api/packages/{package_id}/variants/generate

    Generates variants for a package.
    Stub only – real implementation comes in PR-3.
    """
    try:
        package_uuid = UUID(package_id)
    except ValueError:
        return error_response(
            code="invalid_uuid",
            message="Invalid package_id format",
            details={"field": "package_id", "value": package_id},
        )

    brand_id = _stub_brand_id()
    variants = [
        _stub_variant(package_uuid, brand_id, Channel.LINKEDIN, 0),
        _stub_variant(package_uuid, brand_id, Channel.X, 1),
    ]

    dto = GenerateVariantsResponseDTO(
        status="generated",
        package_id=package_uuid,
        variants=variants,
        count=len(variants),
    )
    return JsonResponse(dto.model_dump(mode="json"), status=201)


@require_GET
def get_variants(request: HttpRequest, package_id: str) -> JsonResponse:
    """
    GET /api/packages/{package_id}/variants

    Returns all variants for a package.
    Stub only – real implementation comes in PR-3.
    """
    try:
        package_uuid = UUID(package_id)
    except ValueError:
        return error_response(
            code="invalid_uuid",
            message="Invalid package_id format",
            details={"field": "package_id", "value": package_id},
        )

    brand_id = _stub_brand_id()
    variants = [
        _stub_variant(package_uuid, brand_id, Channel.LINKEDIN, 0),
        _stub_variant(package_uuid, brand_id, Channel.X, 1),
    ]

    dto = VariantListDTO(
        package_id=package_uuid,
        variants=variants,
        count=len(variants),
    )
    return JsonResponse(dto.model_dump(mode="json"))


@csrf_exempt
@require_http_methods(["PATCH"])
def update_variant(request: HttpRequest, variant_id: str) -> JsonResponse:
    """
    PATCH /api/variants/{variant_id}

    Updates a variant (body, status, etc.).
    Stub only – real implementation comes in PR-3.
    """
    try:
        variant_uuid = UUID(variant_id)
    except ValueError:
        return error_response(
            code="invalid_uuid",
            message="Invalid variant_id format",
            details={"field": "variant_id", "value": variant_id},
        )

    # Parse request body
    try:
        body_data = json.loads(request.body) if request.body else {}
        update_dto = VariantUpdateDTO.model_validate(body_data)
    except json.JSONDecodeError:
        return error_response(
            code="invalid_json",
            message="Request body is not valid JSON",
        )
    except Exception as e:
        return error_response(
            code="validation_error",
            message="Request body validation failed",
            details={"error": str(e)},
        )

    # Generate stub variant and apply updates
    package_id = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
    brand_id = _stub_brand_id()
    variant = _stub_variant(package_id, brand_id, Channel.LINKEDIN, 0)

    # Apply partial updates
    variant_dict = variant.model_dump(mode="json")
    variant_dict["id"] = str(variant_uuid)
    if update_dto.body is not None:
        variant_dict["body"] = update_dto.body
    if update_dto.call_to_action is not None:
        variant_dict["call_to_action"] = update_dto.call_to_action
    if update_dto.status is not None:
        variant_dict["status"] = update_dto.status.value
    variant_dict["updated_at"] = datetime.now(timezone.utc).isoformat()

    return JsonResponse(variant_dict)


# =============================================================================
# DECISION ENDPOINTS
# =============================================================================


@csrf_exempt
@require_http_methods(["POST"])
def record_opportunity_decision(request: HttpRequest, opportunity_id: str) -> JsonResponse:
    """
    POST /api/opportunities/{opportunity_id}/decision

    Records a user decision on an opportunity.
    Stub only – real implementation comes in PR-3.
    """
    try:
        opportunity_uuid = UUID(opportunity_id)
    except ValueError:
        return error_response(
            code="invalid_uuid",
            message="Invalid opportunity_id format",
            details={"field": "opportunity_id", "value": opportunity_id},
        )

    # Parse and validate request
    try:
        body_data = json.loads(request.body) if request.body else {}
        decision_request = DecisionRequestDTO.model_validate(body_data)
    except json.JSONDecodeError:
        return error_response(
            code="invalid_json",
            message="Request body is not valid JSON",
        )
    except Exception as e:
        return error_response(
            code="validation_error",
            message="Request body validation failed",
            details={"error": str(e)},
        )

    dto = DecisionResponseDTO(
        status="accepted",
        decision_type=decision_request.decision_type,
        object_type="opportunity",
        object_id=opportunity_uuid,
        recorded_at=datetime.now(timezone.utc),
    )
    return JsonResponse(dto.model_dump(mode="json"))


@csrf_exempt
@require_http_methods(["POST"])
def record_package_decision(request: HttpRequest, package_id: str) -> JsonResponse:
    """
    POST /api/packages/{package_id}/decision

    Records a user decision on a package.
    Stub only – real implementation comes in PR-3.
    """
    try:
        package_uuid = UUID(package_id)
    except ValueError:
        return error_response(
            code="invalid_uuid",
            message="Invalid package_id format",
            details={"field": "package_id", "value": package_id},
        )

    # Parse and validate request
    try:
        body_data = json.loads(request.body) if request.body else {}
        decision_request = DecisionRequestDTO.model_validate(body_data)
    except json.JSONDecodeError:
        return error_response(
            code="invalid_json",
            message="Request body is not valid JSON",
        )
    except Exception as e:
        return error_response(
            code="validation_error",
            message="Request body validation failed",
            details={"error": str(e)},
        )

    dto = DecisionResponseDTO(
        status="accepted",
        decision_type=decision_request.decision_type,
        object_type="package",
        object_id=package_uuid,
        recorded_at=datetime.now(timezone.utc),
    )
    return JsonResponse(dto.model_dump(mode="json"))


@csrf_exempt
@require_http_methods(["POST"])
def record_variant_decision(request: HttpRequest, variant_id: str) -> JsonResponse:
    """
    POST /api/variants/{variant_id}/decision

    Records a user decision on a variant.
    Stub only – real implementation comes in PR-3.
    """
    try:
        variant_uuid = UUID(variant_id)
    except ValueError:
        return error_response(
            code="invalid_uuid",
            message="Invalid variant_id format",
            details={"field": "variant_id", "value": variant_id},
        )

    # Parse and validate request
    try:
        body_data = json.loads(request.body) if request.body else {}
        decision_request = DecisionRequestDTO.model_validate(body_data)
    except json.JSONDecodeError:
        return error_response(
            code="invalid_json",
            message="Request body is not valid JSON",
        )
    except Exception as e:
        return error_response(
            code="validation_error",
            message="Request body validation failed",
            details={"error": str(e)},
        )

    dto = DecisionResponseDTO(
        status="accepted",
        decision_type=decision_request.decision_type,
        object_type="variant",
        object_id=variant_uuid,
        recorded_at=datetime.now(timezone.utc),
    )
    return JsonResponse(dto.model_dump(mode="json"))
