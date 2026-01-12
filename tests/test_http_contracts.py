"""
HTTP contract tests for PR-2 / PR-3 (updated for PR-9).

Tests verify:
- All hero loop endpoints exist at the correct paths
- All endpoints return valid JSON
- All responses validate against the appropriate DTOs
- Request/response contracts are enforced

PR-3 update: Today board endpoints now require a real Brand in the database
since the opportunities_engine looks up the brand.

PR-9 update: Package and variant creation tests now mock the graph functions
to avoid real LLM calls.
"""

import json
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from django.test import Client

from kairo.core.enums import (
    Channel,
    CreatedVia,
    OpportunityType,
    PackageStatus,
    VariantStatus,
)
from kairo.core.models import Brand, ContentPackage, Opportunity, Tenant, Variant
from kairo.hero.dto import (
    ContentPackageDTO,
    ContentPackageDraftDTO,
    CreatePackageResponseDTO,
    DecisionResponseDTO,
    GenerateVariantsResponseDTO,
    RegenerateResponseDTO,
    TodayBoardDTO,
    VariantDTO,
    VariantDraftDTO,
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
def tenant(db):
    """Create a test tenant."""
    return Tenant.objects.create(
        name="HTTP Contract Test Tenant",
        slug="http-contract-test",
    )


@pytest.fixture
def brand(db, tenant):
    """Create a test brand for Today board tests."""
    return Brand.objects.create(
        id=UUID("12345678-1234-5678-1234-567812345678"),
        tenant=tenant,
        name="HTTP Contract Test Brand",
        positioning="Testing HTTP contracts",
    )


@pytest.fixture
def sample_brand_id(brand) -> str:
    """A sample brand ID for testing (from real brand)."""
    return str(brand.id)


@pytest.fixture
def opportunity(db, brand):
    """Create a real opportunity for decision tests."""
    return Opportunity.objects.create(
        brand=brand,
        type=OpportunityType.TREND,
        title="Test Opportunity",
        angle="Test angle",
        score=0.75,
        primary_channel=Channel.LINKEDIN,
        created_via=CreatedVia.AI_SUGGESTED,
        metadata={},
    )


@pytest.fixture
def sample_opportunity_id(opportunity) -> str:
    """A sample opportunity ID for testing (from real opportunity)."""
    return str(opportunity.id)


@pytest.fixture
def package(db, brand, opportunity):
    """Create a real package for decision tests."""
    return ContentPackage.objects.create(
        brand=brand,
        title="Test Package",
        status=PackageStatus.DRAFT,
        origin_opportunity=opportunity,
        metrics_snapshot={},
    )


@pytest.fixture
def sample_package_id(package) -> str:
    """A sample package ID for testing (from real package)."""
    return str(package.id)


@pytest.fixture
def variant(db, brand, package):
    """Create a real variant for decision tests."""
    return Variant.objects.create(
        brand=brand,
        package=package,
        channel=Channel.LINKEDIN,
        status=VariantStatus.DRAFT,
        draft_text="Test draft",
    )


@pytest.fixture
def sample_variant_id(variant) -> str:
    """A sample variant ID for testing (from real variant)."""
    return str(variant.id)


@pytest.fixture
def mock_package_draft():
    """Mock package draft for HTTP contract testing."""
    return ContentPackageDraftDTO(
        title="HTTP Contract Test Package",
        thesis="A comprehensive test thesis about marketing strategies and best practices for testing.",
        summary="This package covers various marketing topics with practical examples.",
        primary_channel=Channel.LINKEDIN,
        channels=[Channel.LINKEDIN, Channel.X],
        cta="Learn more",
        is_valid=True,
        rejection_reasons=[],
        package_score=12.0,
        quality_band="board_ready",
    )


@pytest.fixture
def mock_variant_drafts():
    """Mock variant drafts for HTTP contract testing."""
    return [
        VariantDraftDTO(
            channel=Channel.LINKEDIN,
            body="Test content for LinkedIn with multiple paragraphs and insights for HTTP contract testing.",
            call_to_action="Share your thoughts",
            is_valid=True,
            rejection_reasons=[],
            variant_score=10.0,
            quality_band="publish_ready",
        ),
        VariantDraftDTO(
            channel=Channel.X,
            body="Concise X post about marketing strategies. Thread below.",
            call_to_action="Follow for more",
            is_valid=True,
            rejection_reasons=[],
            variant_score=9.0,
            quality_band="publish_ready",
        ),
    ]


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

    def test_get_today_board_missing_brand_returns_404(self, client: Client, db):
        """GET /api/brands/{valid-but-missing}/today returns 404 with error envelope."""
        missing_id = "99999999-9999-9999-9999-999999999999"
        response = client.get(f"/api/brands/{missing_id}/today/")
        assert response.status_code == 404
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == "not_found"
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

    def test_regenerate_today_board_missing_brand_returns_404(self, client: Client, db):
        """POST /api/brands/{valid-but-missing}/today/regenerate returns 404."""
        missing_id = "99999999-9999-9999-9999-999999999999"
        response = client.post(f"/api/brands/{missing_id}/today/regenerate/")
        assert response.status_code == 404
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == "not_found"


# =============================================================================
# PACKAGE ENDPOINT TESTS
# =============================================================================


@pytest.mark.django_db
class TestPackageEndpoints:
    """Tests for package endpoints."""

    def test_create_package_returns_201(
        self, client: Client, sample_brand_id: str, sample_opportunity_id: str, mock_package_draft
    ):
        """POST /api/brands/{brand_id}/opportunities/{opp_id}/packages returns 201."""
        with patch("kairo.hero.engines.content_engine.graph_hero_package_from_opportunity") as mock_graph:
            mock_graph.return_value = mock_package_draft

            response = client.post(
                f"/api/brands/{sample_brand_id}/opportunities/{sample_opportunity_id}/packages/"
            )
            assert response.status_code == 201

    def test_create_package_validates_against_dto(
        self, client: Client, sample_brand_id: str, sample_opportunity_id: str, mock_package_draft
    ):
        """POST create package response validates against CreatePackageResponseDTO."""
        with patch("kairo.hero.engines.content_engine.graph_hero_package_from_opportunity") as mock_graph:
            mock_graph.return_value = mock_package_draft

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

    def test_generate_variants_returns_201(self, client: Client, sample_package_id: str, mock_variant_drafts):
        """POST /api/packages/{package_id}/variants/generate returns 201."""
        with patch("kairo.hero.engines.content_engine.graph_hero_variants_from_package") as mock_graph:
            mock_graph.return_value = mock_variant_drafts

            response = client.post(f"/api/packages/{sample_package_id}/variants/generate/")
            assert response.status_code == 201

    def test_generate_variants_validates_against_dto(self, client: Client, sample_package_id: str, mock_variant_drafts):
        """POST generate variants response validates against GenerateVariantsResponseDTO."""
        with patch("kairo.hero.engines.content_engine.graph_hero_variants_from_package") as mock_graph:
            mock_graph.return_value = mock_variant_drafts

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
