"""
Hero Loop API Views.

PR-3: Service Layer + Engines Layer Skeleton.

Views now call services → services call engines.
Still returning stubbed data, but through the proper layer architecture.

All responses must validate against the appropriate DTO before returning.
"""

import json
from typing import Any
from uuid import UUID

from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from kairo.core.models import Brand

from .dto import (
    DecisionRequestDTO,
    RegenerateResponseDTO,
    VariantUpdateDTO,
)
from .services import (
    content_packages_service,
    decisions_service,
    opportunities_service,
    today_service,
    variants_service,
)
from .services.decisions_service import ObjectNotFoundError


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
# TODAY BOARD ENDPOINTS
# =============================================================================


@require_GET
def get_today_board(request: HttpRequest, brand_id: str) -> JsonResponse:
    """
    GET /api/brands/{brand_id}/today

    Returns the Today board for a brand.

    Calls: today_service.get_today_board → opportunities_engine.generate_today_board
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
        dto = today_service.get_today_board(brand_uuid)
    except Brand.DoesNotExist:
        return error_response(
            code="not_found",
            message="Brand not found",
            status=404,
            details={"brand_id": brand_id},
        )

    return JsonResponse(dto.model_dump(mode="json"))


@csrf_exempt
@require_http_methods(["POST"])
def regenerate_today_board(request: HttpRequest, brand_id: str) -> JsonResponse:
    """
    POST /api/brands/{brand_id}/today/regenerate

    Triggers regeneration of the Today board.

    Calls: today_service.regenerate_today_board → opportunities_engine.generate_today_board
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
        today_board = today_service.regenerate_today_board(brand_uuid)
    except Brand.DoesNotExist:
        return error_response(
            code="not_found",
            message="Brand not found",
            status=404,
            details={"brand_id": brand_id},
        )

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

    Calls: opportunities_service.create_package_for_opportunity
           → content_engine.create_package_from_opportunity
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

    dto = opportunities_service.create_package_for_opportunity(
        brand_uuid, opportunity_uuid
    )
    return JsonResponse(dto.model_dump(mode="json"), status=201)


@require_GET
def get_package(request: HttpRequest, package_id: str) -> JsonResponse:
    """
    GET /api/packages/{package_id}

    Returns a content package by ID.

    Calls: content_packages_service.get_package
    """
    try:
        package_uuid = UUID(package_id)
    except ValueError:
        return error_response(
            code="invalid_uuid",
            message="Invalid package_id format",
            details={"field": "package_id", "value": package_id},
        )

    dto = content_packages_service.get_package(package_uuid)
    return JsonResponse(dto.model_dump(mode="json"))


# =============================================================================
# VARIANT ENDPOINTS
# =============================================================================


@csrf_exempt
@require_http_methods(["POST"])
def generate_variants(request: HttpRequest, package_id: str) -> JsonResponse:
    """
    POST /api/packages/{package_id}/variants/generate

    Generates variants for a package.

    Calls: variants_service.generate_variants_for_package
           → content_engine.generate_variants_for_package
    """
    try:
        package_uuid = UUID(package_id)
    except ValueError:
        return error_response(
            code="invalid_uuid",
            message="Invalid package_id format",
            details={"field": "package_id", "value": package_id},
        )

    dto = variants_service.generate_variants_for_package(package_uuid)
    return JsonResponse(dto.model_dump(mode="json"), status=201)


@require_GET
def get_variants(request: HttpRequest, package_id: str) -> JsonResponse:
    """
    GET /api/packages/{package_id}/variants

    Returns all variants for a package.

    Calls: variants_service.list_variants_for_package
    """
    try:
        package_uuid = UUID(package_id)
    except ValueError:
        return error_response(
            code="invalid_uuid",
            message="Invalid package_id format",
            details={"field": "package_id", "value": package_id},
        )

    dto = variants_service.list_variants_for_package(package_uuid)
    return JsonResponse(dto.model_dump(mode="json"))


@csrf_exempt
@require_http_methods(["PATCH"])
def update_variant(request: HttpRequest, variant_id: str) -> JsonResponse:
    """
    PATCH /api/variants/{variant_id}

    Updates a variant (body, status, etc.).

    Calls: variants_service.update_variant
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

    # Convert DTO to dict for service
    payload = {}
    if update_dto.body is not None:
        payload["body"] = update_dto.body
    if update_dto.call_to_action is not None:
        payload["call_to_action"] = update_dto.call_to_action
    if update_dto.status is not None:
        payload["status"] = update_dto.status

    dto = variants_service.update_variant(variant_uuid, payload)
    return JsonResponse(dto.model_dump(mode="json"))


# =============================================================================
# DECISION ENDPOINTS
# =============================================================================


@csrf_exempt
@require_http_methods(["POST"])
def record_opportunity_decision(request: HttpRequest, opportunity_id: str) -> JsonResponse:
    """
    POST /api/opportunities/{opportunity_id}/decision

    Records a user decision on an opportunity.

    Calls: decisions_service.record_opportunity_decision
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

    # Stub brand_id for now (real implementation would extract from context)
    stub_brand_id = UUID("12345678-1234-5678-1234-567812345678")

    try:
        dto = decisions_service.record_opportunity_decision(
            stub_brand_id, opportunity_uuid, decision_request
        )
    except ObjectNotFoundError:
        return error_response(
            code="not_found",
            message="Opportunity not found",
            status=404,
            details={"opportunity_id": opportunity_id},
        )

    return JsonResponse(dto.model_dump(mode="json"))


@csrf_exempt
@require_http_methods(["POST"])
def record_package_decision(request: HttpRequest, package_id: str) -> JsonResponse:
    """
    POST /api/packages/{package_id}/decision

    Records a user decision on a package.

    Calls: decisions_service.record_package_decision
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

    # Stub brand_id for now (real implementation would extract from context)
    stub_brand_id = UUID("12345678-1234-5678-1234-567812345678")

    try:
        dto = decisions_service.record_package_decision(
            stub_brand_id, package_uuid, decision_request
        )
    except ObjectNotFoundError:
        return error_response(
            code="not_found",
            message="Package not found",
            status=404,
            details={"package_id": package_id},
        )

    return JsonResponse(dto.model_dump(mode="json"))


@csrf_exempt
@require_http_methods(["POST"])
def record_variant_decision(request: HttpRequest, variant_id: str) -> JsonResponse:
    """
    POST /api/variants/{variant_id}/decision

    Records a user decision on a variant.

    Calls: decisions_service.record_variant_decision
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

    # Stub brand_id for now (real implementation would extract from context)
    stub_brand_id = UUID("12345678-1234-5678-1234-567812345678")

    try:
        dto = decisions_service.record_variant_decision(
            stub_brand_id, variant_uuid, decision_request
        )
    except ObjectNotFoundError:
        return error_response(
            code="not_found",
            message="Variant not found",
            status=404,
            details={"variant_id": variant_id},
        )

    return JsonResponse(dto.model_dump(mode="json"))
