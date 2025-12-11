"""
HTTP contract tests for PR-2.

Tests verify:
- All hero loop endpoints exist at the correct paths
- All endpoints return valid JSON
- All responses validate against the appropriate DTOs
- Request/response contracts are enforced
"""

import json
from uuid import uuid4

import pytest
from django.test import Client

from kairo.hero.dto import (
    ContentPackageDTO,
    CreatePackageResponseDTO,
    DecisionResponseDTO,
    GenerateVariantsResponseDTO,
    RegenerateResponseDTO,
    TodayBoardDTO,
    VariantDTO,
    VariantListDTO,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def client() -> Client:
    """Django test client."""
    return Client()


@pytest.fixture
def sample_brand_id() -> str:
    """A sample brand ID for testing."""
    return "12345678-1234-5678-1234-567812345678"


@pytest.fixture
def sample_opportunity_id() -> str:
    """A sample opportunity ID for testing."""
    return "cccccccc-cccc-cccc-cccc-000000000000"


@pytest.fixture
def sample_package_id() -> str:
    """A sample package ID for testing."""
    return "dddddddd-dddd-dddd-dddd-dddddddddddd"


@pytest.fixture
def sample_variant_id() -> str:
    """A sample variant ID for testing."""
    return "eeeeeeee-eeee-eeee-eeee-000000000000"


# =============================================================================
# TODAY BOARD ENDPOINT TESTS
# =============================================================================


@pytest.mark.django_db
class TestTodayBoardEndpoints:
    """Tests for Today board endpoints."""

    def test_get_today_board_returns_200(self, client: Client, sample_brand_id: str):
        """GET /api/brands/{brand_id}/today returns 200."""
        response = client.get(f"/api/brands/{sample_brand_id}/today/")
        assert response.status_code == 200

    def test_get_today_board_returns_valid_json(self, client: Client, sample_brand_id: str):
        """GET /api/brands/{brand_id}/today returns valid JSON."""
        response = client.get(f"/api/brands/{sample_brand_id}/today/")
        data = response.json()
        assert "brand_id" in data
        assert "snapshot" in data
        assert "opportunities" in data
        assert "meta" in data

    def test_get_today_board_validates_against_dto(self, client: Client, sample_brand_id: str):
        """GET /api/brands/{brand_id}/today response validates against TodayBoardDTO."""
        response = client.get(f"/api/brands/{sample_brand_id}/today/")
        data = response.json()

        # This should not raise
        dto = TodayBoardDTO.model_validate(data)

        assert str(dto.brand_id) == sample_brand_id
        assert dto.snapshot is not None
        assert isinstance(dto.opportunities, list)
        assert dto.meta is not None

    def test_get_today_board_has_opportunities(self, client: Client, sample_brand_id: str):
        """Today board returns stub opportunities."""
        response = client.get(f"/api/brands/{sample_brand_id}/today/")
        data = response.json()

        assert len(data["opportunities"]) > 0
        assert data["meta"]["opportunity_count"] == len(data["opportunities"])

    def test_get_today_board_invalid_uuid_returns_400(self, client: Client):
        """GET /api/brands/{invalid}/today returns 400 with error envelope."""
        response = client.get("/api/brands/not-a-uuid/today/")
        assert response.status_code == 400
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == "invalid_uuid"
        assert "message" in data["error"]

    def test_regenerate_today_board_returns_200(self, client: Client, sample_brand_id: str):
        """POST /api/brands/{brand_id}/today/regenerate returns 200."""
        response = client.post(f"/api/brands/{sample_brand_id}/today/regenerate/")
        assert response.status_code == 200

    def test_regenerate_today_board_validates_against_dto(
        self, client: Client, sample_brand_id: str
    ):
        """POST /api/brands/{brand_id}/today/regenerate validates against RegenerateResponseDTO."""
        response = client.post(f"/api/brands/{sample_brand_id}/today/regenerate/")
        data = response.json()

        # This should not raise
        dto = RegenerateResponseDTO.model_validate(data)

        assert dto.status == "regenerated"
        assert dto.today_board is not None
        assert str(dto.today_board.brand_id) == sample_brand_id


# =============================================================================
# PACKAGE ENDPOINT TESTS
# =============================================================================


@pytest.mark.django_db
class TestPackageEndpoints:
    """Tests for package endpoints."""

    def test_create_package_returns_201(
        self, client: Client, sample_brand_id: str, sample_opportunity_id: str
    ):
        """POST /api/brands/{brand_id}/opportunities/{opp_id}/packages returns 201."""
        response = client.post(
            f"/api/brands/{sample_brand_id}/opportunities/{sample_opportunity_id}/packages/"
        )
        assert response.status_code == 201

    def test_create_package_validates_against_dto(
        self, client: Client, sample_brand_id: str, sample_opportunity_id: str
    ):
        """POST create package response validates against CreatePackageResponseDTO."""
        response = client.post(
            f"/api/brands/{sample_brand_id}/opportunities/{sample_opportunity_id}/packages/"
        )
        data = response.json()

        # This should not raise
        dto = CreatePackageResponseDTO.model_validate(data)

        assert dto.status == "created"
        assert dto.package is not None
        assert str(dto.package.brand_id) == sample_brand_id

    def test_get_package_returns_200(self, client: Client, sample_package_id: str):
        """GET /api/packages/{package_id} returns 200."""
        response = client.get(f"/api/packages/{sample_package_id}/")
        assert response.status_code == 200

    def test_get_package_validates_against_dto(self, client: Client, sample_package_id: str):
        """GET /api/packages/{package_id} validates against ContentPackageDTO."""
        response = client.get(f"/api/packages/{sample_package_id}/")
        data = response.json()

        # This should not raise
        dto = ContentPackageDTO.model_validate(data)

        assert dto.id is not None
        assert dto.title is not None
        assert dto.status is not None

    def test_get_package_invalid_uuid_returns_400(self, client: Client):
        """GET /api/packages/{invalid} returns 400 with error envelope."""
        response = client.get("/api/packages/not-a-uuid/")
        assert response.status_code == 400
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == "invalid_uuid"
        assert "message" in data["error"]


# =============================================================================
# VARIANT ENDPOINT TESTS
# =============================================================================


@pytest.mark.django_db
class TestVariantEndpoints:
    """Tests for variant endpoints."""

    def test_generate_variants_returns_201(self, client: Client, sample_package_id: str):
        """POST /api/packages/{package_id}/variants/generate returns 201."""
        response = client.post(f"/api/packages/{sample_package_id}/variants/generate/")
        assert response.status_code == 201

    def test_generate_variants_validates_against_dto(self, client: Client, sample_package_id: str):
        """POST generate variants response validates against GenerateVariantsResponseDTO."""
        response = client.post(f"/api/packages/{sample_package_id}/variants/generate/")
        data = response.json()

        # This should not raise
        dto = GenerateVariantsResponseDTO.model_validate(data)

        assert dto.status == "generated"
        assert str(dto.package_id) == sample_package_id
        assert len(dto.variants) > 0
        assert dto.count == len(dto.variants)

    def test_get_variants_returns_200(self, client: Client, sample_package_id: str):
        """GET /api/packages/{package_id}/variants returns 200."""
        response = client.get(f"/api/packages/{sample_package_id}/variants/")
        assert response.status_code == 200

    def test_get_variants_validates_against_dto(self, client: Client, sample_package_id: str):
        """GET /api/packages/{package_id}/variants validates against VariantListDTO."""
        response = client.get(f"/api/packages/{sample_package_id}/variants/")
        data = response.json()

        # This should not raise
        dto = VariantListDTO.model_validate(data)

        assert str(dto.package_id) == sample_package_id
        assert isinstance(dto.variants, list)
        assert dto.count == len(dto.variants)

    def test_update_variant_returns_200(self, client: Client, sample_variant_id: str):
        """PATCH /api/variants/{variant_id} returns 200."""
        response = client.patch(
            f"/api/variants/{sample_variant_id}/",
            data=json.dumps({"body": "Updated body text"}),
            content_type="application/json",
        )
        assert response.status_code == 200

    def test_update_variant_validates_against_dto(self, client: Client, sample_variant_id: str):
        """PATCH /api/variants/{variant_id} response validates against VariantDTO."""
        response = client.patch(
            f"/api/variants/{sample_variant_id}/",
            data=json.dumps({"body": "Updated body text", "status": "edited"}),
            content_type="application/json",
        )
        data = response.json()

        # This should not raise
        dto = VariantDTO.model_validate(data)

        assert dto.body == "Updated body text"
        assert dto.status.value == "edited"

    def test_update_variant_partial_update(self, client: Client, sample_variant_id: str):
        """PATCH allows partial updates."""
        # Only update body
        response = client.patch(
            f"/api/variants/{sample_variant_id}/",
            data=json.dumps({"body": "New body only"}),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["body"] == "New body only"

    def test_update_variant_invalid_uuid_returns_400(self, client: Client):
        """PATCH /api/variants/{invalid} returns 400 with error envelope."""
        response = client.patch(
            "/api/variants/not-a-uuid/",
            data=json.dumps({"body": "Test"}),
            content_type="application/json",
        )
        assert response.status_code == 400
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == "invalid_uuid"
        assert "message" in data["error"]


# =============================================================================
# DECISION ENDPOINT TESTS
# =============================================================================


@pytest.mark.django_db
class TestDecisionEndpoints:
    """Tests for decision endpoints."""

    def test_opportunity_decision_returns_200(
        self, client: Client, sample_opportunity_id: str
    ):
        """POST /api/opportunities/{opportunity_id}/decision returns 200."""
        response = client.post(
            f"/api/opportunities/{sample_opportunity_id}/decision/",
            data=json.dumps({
                "decision_type": "opportunity_pinned",
                "reason": "High priority",
            }),
            content_type="application/json",
        )
        assert response.status_code == 200

    def test_opportunity_decision_validates_against_dto(
        self, client: Client, sample_opportunity_id: str
    ):
        """POST opportunity decision validates against DecisionResponseDTO."""
        response = client.post(
            f"/api/opportunities/{sample_opportunity_id}/decision/",
            data=json.dumps({
                "decision_type": "opportunity_pinned",
                "reason": "High priority",
            }),
            content_type="application/json",
        )
        data = response.json()

        # This should not raise
        dto = DecisionResponseDTO.model_validate(data)

        assert dto.status == "accepted"
        assert dto.decision_type.value == "opportunity_pinned"
        assert dto.object_type == "opportunity"
        assert str(dto.object_id) == sample_opportunity_id

    def test_package_decision_returns_200(self, client: Client, sample_package_id: str):
        """POST /api/packages/{package_id}/decision returns 200."""
        response = client.post(
            f"/api/packages/{sample_package_id}/decision/",
            data=json.dumps({
                "decision_type": "package_approved",
                "reason": "Ready for publish",
            }),
            content_type="application/json",
        )
        assert response.status_code == 200

    def test_package_decision_validates_against_dto(self, client: Client, sample_package_id: str):
        """POST package decision validates against DecisionResponseDTO."""
        response = client.post(
            f"/api/packages/{sample_package_id}/decision/",
            data=json.dumps({
                "decision_type": "package_approved",
            }),
            content_type="application/json",
        )
        data = response.json()

        # This should not raise
        dto = DecisionResponseDTO.model_validate(data)

        assert dto.object_type == "package"
        assert str(dto.object_id) == sample_package_id

    def test_variant_decision_returns_200(self, client: Client, sample_variant_id: str):
        """POST /api/variants/{variant_id}/decision returns 200."""
        response = client.post(
            f"/api/variants/{sample_variant_id}/decision/",
            data=json.dumps({
                "decision_type": "variant_approved",
            }),
            content_type="application/json",
        )
        assert response.status_code == 200

    def test_variant_decision_validates_against_dto(self, client: Client, sample_variant_id: str):
        """POST variant decision validates against DecisionResponseDTO."""
        response = client.post(
            f"/api/variants/{sample_variant_id}/decision/",
            data=json.dumps({
                "decision_type": "variant_edited",
                "reason": "Minor tweaks",
                "metadata": {"field": "body"},
            }),
            content_type="application/json",
        )
        data = response.json()

        # This should not raise
        dto = DecisionResponseDTO.model_validate(data)

        assert dto.object_type == "variant"
        assert dto.decision_type.value == "variant_edited"

    def test_decision_invalid_type_returns_400(self, client: Client, sample_opportunity_id: str):
        """Decision with invalid decision_type returns 400 with error envelope."""
        response = client.post(
            f"/api/opportunities/{sample_opportunity_id}/decision/",
            data=json.dumps({
                "decision_type": "invalid_decision",
            }),
            content_type="application/json",
        )
        assert response.status_code == 400
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == "validation_error"
        assert "message" in data["error"]

    def test_decision_missing_type_returns_400(self, client: Client, sample_opportunity_id: str):
        """Decision without decision_type returns 400 with error envelope."""
        response = client.post(
            f"/api/opportunities/{sample_opportunity_id}/decision/",
            data=json.dumps({
                "reason": "No type provided",
            }),
            content_type="application/json",
        )
        assert response.status_code == 400
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == "validation_error"
        assert "message" in data["error"]

    def test_decision_invalid_json_returns_400(self, client: Client, sample_opportunity_id: str):
        """Decision with invalid JSON returns 400 with error envelope."""
        response = client.post(
            f"/api/opportunities/{sample_opportunity_id}/decision/",
            data="not valid json",
            content_type="application/json",
        )
        assert response.status_code == 400
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == "invalid_json"
        assert "message" in data["error"]


# =============================================================================
# CONTRACT STABILITY TESTS
# =============================================================================


@pytest.mark.django_db
class TestContractStability:
    """Tests to ensure API contracts remain stable."""

    def test_today_board_required_fields(self, client: Client, sample_brand_id: str):
        """Today board response has all required fields per contract."""
        response = client.get(f"/api/brands/{sample_brand_id}/today/")
        data = response.json()

        # Required top-level fields
        assert "brand_id" in data
        assert "snapshot" in data
        assert "opportunities" in data
        assert "meta" in data

        # Required snapshot fields
        assert "brand_id" in data["snapshot"]
        assert "brand_name" in data["snapshot"]
        assert "pillars" in data["snapshot"]
        assert "personas" in data["snapshot"]

        # Required meta fields
        assert "generated_at" in data["meta"]
        assert "source" in data["meta"]
        assert "degraded" in data["meta"]

    def test_opportunity_required_fields(self, client: Client, sample_brand_id: str):
        """Opportunity objects have all required fields per contract."""
        response = client.get(f"/api/brands/{sample_brand_id}/today/")
        data = response.json()

        for opp in data["opportunities"]:
            # Required opportunity fields
            assert "id" in opp
            assert "brand_id" in opp
            assert "title" in opp
            assert "angle" in opp
            assert "type" in opp
            assert "primary_channel" in opp
            assert "score" in opp
            assert "is_pinned" in opp
            assert "is_snoozed" in opp
            assert "created_at" in opp
            assert "updated_at" in opp

    def test_package_required_fields(self, client: Client, sample_package_id: str):
        """Package objects have all required fields per contract."""
        response = client.get(f"/api/packages/{sample_package_id}/")
        data = response.json()

        # Required package fields
        assert "id" in data
        assert "brand_id" in data
        assert "title" in data
        assert "status" in data
        assert "channels" in data
        assert "created_at" in data
        assert "updated_at" in data

    def test_variant_required_fields(self, client: Client, sample_package_id: str):
        """Variant objects have all required fields per contract."""
        response = client.get(f"/api/packages/{sample_package_id}/variants/")
        data = response.json()

        for variant in data["variants"]:
            # Required variant fields
            assert "id" in variant
            assert "package_id" in variant
            assert "brand_id" in variant
            assert "channel" in variant
            assert "status" in variant
            assert "body" in variant
            assert "created_at" in variant
            assert "updated_at" in variant

    def test_decision_response_required_fields(
        self, client: Client, sample_opportunity_id: str
    ):
        """Decision response has all required fields per contract."""
        response = client.post(
            f"/api/opportunities/{sample_opportunity_id}/decision/",
            data=json.dumps({"decision_type": "opportunity_pinned"}),
            content_type="application/json",
        )
        data = response.json()

        # Required decision response fields
        assert "status" in data
        assert "decision_type" in data
        assert "object_type" in data
        assert "object_id" in data
        assert "recorded_at" in data


# =============================================================================
# ERROR ENVELOPE TESTS
# =============================================================================


@pytest.mark.django_db
class TestErrorEnvelope:
    """Tests for standardized error envelope format."""

    def test_error_envelope_structure(self, client: Client):
        """Error responses follow the envelope structure."""
        response = client.get("/api/brands/not-a-uuid/today/")
        assert response.status_code == 400
        data = response.json()

        # Must have "error" key
        assert "error" in data

        # Error must have code and message
        error = data["error"]
        assert "code" in error
        assert "message" in error
        assert isinstance(error["code"], str)
        assert isinstance(error["message"], str)

    def test_error_envelope_with_details(self, client: Client):
        """Error responses can include optional details."""
        response = client.get("/api/packages/bad-uuid/")
        assert response.status_code == 400
        data = response.json()

        error = data["error"]
        assert error["code"] == "invalid_uuid"
        # Details should include field information
        if "details" in error:
            assert "field" in error["details"]

    def test_validation_error_envelope(self, client: Client, sample_opportunity_id: str):
        """Validation errors use the validation_error code."""
        response = client.post(
            f"/api/opportunities/{sample_opportunity_id}/decision/",
            data=json.dumps({"decision_type": "not_a_real_type"}),
            content_type="application/json",
        )
        assert response.status_code == 400
        data = response.json()

        assert data["error"]["code"] == "validation_error"
        assert "message" in data["error"]

    def test_invalid_json_error_envelope(self, client: Client, sample_opportunity_id: str):
        """Invalid JSON uses the invalid_json code."""
        response = client.post(
            f"/api/opportunities/{sample_opportunity_id}/decision/",
            data="{this is not json",
            content_type="application/json",
        )
        assert response.status_code == 400
        data = response.json()

        assert data["error"]["code"] == "invalid_json"
        assert "message" in data["error"]
