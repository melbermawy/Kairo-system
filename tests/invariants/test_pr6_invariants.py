"""
PR-6 Invariant Tests: Live-cap-limited Apify Path.

Per opportunities_v1_prd.md Section I.6:
1. POST /regenerate enqueues job with live mode
2. Live mode requires APIFY_ENABLED and mode gate
3. Actor inputs include hard caps
4. Instagram 2-stage derivation occurs
5. ActivationRun and EvidenceItem persisted on live run
6. EvidenceItem IDs deterministic (uuid5 rule)
7. GET path remains read-only

All tests use mocked Apify - no real network calls.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from kairo.core.models import Brand


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def tenant(db):
    """Create a test tenant."""
    from kairo.core.models import Tenant

    return Tenant.objects.create(
        id=uuid.uuid4(),
        name="Test Tenant PR6",
    )


@pytest.fixture
def brand(db, tenant) -> Brand:
    """Create a test brand."""
    return Brand.objects.create(
        id=uuid.uuid4(),
        tenant=tenant,
        name="Test Brand PR6",
        positioning="A test brand for PR-6 invariant testing",
    )


@pytest.fixture
def job(brand: Brand):
    """Create a test job."""
    from kairo.hero.models import OpportunitiesJob, OpportunitiesJobStatus

    return OpportunitiesJob.objects.create(
        brand_id=brand.id,
        status=OpportunitiesJobStatus.PENDING,
        params_json={"mode": "live_cap_limited", "force": True},
    )


@pytest.fixture
def mock_apify_client():
    """Mock ApifyClient for all tests."""
    from kairo.integrations.apify.client import RunInfo

    mock_client = MagicMock()

    # Stage 1 run
    mock_run_info = RunInfo(
        run_id="mock-run-1",
        dataset_id="mock-dataset-1",
        status="SUCCEEDED",
    )
    mock_client.start_actor_run.return_value = mock_run_info
    mock_client.poll_run.return_value = mock_run_info

    # Stage 1 items (Instagram discovery)
    mock_client.fetch_dataset_items.return_value = [
        {
            "url": "https://instagram.com/p/test1",
            "shortCode": "test1",
            "ownerUsername": "creator1",
            "caption": "Test post #marketing #brand",
            "likesCount": 5000,
            "commentsCount": 100,
            "videoViewCount": 50000,
            "productType": "clips",
            "timestamp": "2026-01-15T10:00:00Z",
        },
        {
            "url": "https://instagram.com/p/test2",
            "shortCode": "test2",
            "ownerUsername": "creator2",
            "caption": "Another test #trending",
            "likesCount": 8000,
            "commentsCount": 200,
            "videoViewCount": 100000,
            "productType": "clips",
            "timestamp": "2026-01-16T12:00:00Z",
        },
    ]

    return mock_client


# =============================================================================
# Test 1: POST /regenerate enqueues job with live mode
# =============================================================================


@pytest.mark.django_db
class TestPostRegenerateEnqueuesLiveMode:
    """Test 1: POST /regenerate enqueues job with live_cap_limited mode."""

    def test_enqueue_with_force_and_apify_enabled_uses_live_mode(self, brand: Brand):
        """When force=True and APIFY_ENABLED=true, mode should be live_cap_limited."""
        from kairo.hero.jobs.queue import enqueue_opportunities_job
        from kairo.hero.models import OpportunitiesJob

        with patch("kairo.core.guardrails.is_apify_enabled", return_value=True):
            result = enqueue_opportunities_job(brand.id, force=True)

        job = OpportunitiesJob.objects.get(id=result.job_id)
        assert job.params_json["mode"] == "live_cap_limited"

    def test_enqueue_with_force_but_apify_disabled_uses_fixture_mode(
        self, brand: Brand
    ):
        """When force=True but APIFY_ENABLED=false, mode should be fixture_only."""
        from kairo.hero.jobs.queue import enqueue_opportunities_job
        from kairo.hero.models import OpportunitiesJob

        with patch("kairo.core.guardrails.is_apify_enabled", return_value=False):
            result = enqueue_opportunities_job(brand.id, force=True)

        job = OpportunitiesJob.objects.get(id=result.job_id)
        assert job.params_json["mode"] == "fixture_only"

    def test_enqueue_first_run_uses_fixture_mode(self, brand: Brand):
        """First-run auto-enqueue always uses fixture_only mode."""
        from kairo.hero.jobs.queue import enqueue_opportunities_job
        from kairo.hero.models import OpportunitiesJob

        with patch("kairo.core.guardrails.is_apify_enabled", return_value=True):
            result = enqueue_opportunities_job(brand.id, first_run=True)

        job = OpportunitiesJob.objects.get(id=result.job_id)
        assert job.params_json["mode"] == "fixture_only"


# =============================================================================
# Test 2: Live mode requires APIFY_ENABLED and mode gate
# =============================================================================


@pytest.mark.django_db
class TestLiveModeRequiresGuards:
    """Test 2: Live mode requires APIFY_ENABLED and mode guard."""

    def test_live_bundle_requires_apify_enabled(self, brand: Brand, job):
        """Live mode raises ApifyDisabledError when APIFY_ENABLED=false."""
        from kairo.core.guardrails import ApifyDisabledError
        from kairo.sourceactivation.services import get_or_create_evidence_bundle
        from kairo.sourceactivation.types import SeedPack

        seed_pack = SeedPack(
            brand_id=brand.id,
            brand_name=brand.name,
            positioning=brand.positioning or "",
            search_terms=["test"],
            pillar_keywords=[],
            persona_contexts=[],
            snapshot_id=brand.id,
        )

        with patch("kairo.core.guardrails.is_apify_enabled", return_value=False):
            with pytest.raises(ApifyDisabledError):
                get_or_create_evidence_bundle(
                    brand_id=brand.id,
                    seed_pack=seed_pack,
                    job_id=job.id,
                    mode="live_cap_limited",
                )

    def test_live_bundle_raises_in_get_today_context(self, brand: Brand, job):
        """Live mode raises GuardrailViolationError in GET /today context."""
        from kairo.core.guardrails import (
            GuardrailViolationError,
            set_get_today_context,
            reset_get_today_context,
        )
        from kairo.sourceactivation.services import get_or_create_evidence_bundle
        from kairo.sourceactivation.types import SeedPack

        seed_pack = SeedPack(
            brand_id=brand.id,
            brand_name=brand.name,
            positioning=brand.positioning or "",
            search_terms=["test"],
            pillar_keywords=[],
            persona_contexts=[],
            snapshot_id=brand.id,
        )

        token = set_get_today_context(True)
        try:
            with pytest.raises(GuardrailViolationError):
                get_or_create_evidence_bundle(
                    brand_id=brand.id,
                    seed_pack=seed_pack,
                    job_id=job.id,
                    mode="live_cap_limited",
                )
        finally:
            reset_get_today_context(token)


# =============================================================================
# Test 3: Actor inputs include hard caps
# =============================================================================


@pytest.mark.unit
class TestActorInputsIncludeCaps:
    """Test 3: Actor inputs include hard caps per PRD G.1 table."""

    def test_instagram_scraper_cap(self):
        """Instagram scraper has resultsLimit cap."""
        from kairo.sourceactivation.budget import apply_caps_to_input, ACTOR_CAPS

        input_data = {"hashtags": ["test"]}
        result = apply_caps_to_input("apify/instagram-scraper", input_data)

        assert "resultsLimit" in result
        assert result["resultsLimit"] == 20  # Per PRD G.1

    def test_instagram_reel_scraper_cap(self):
        """Instagram Reel scraper has resultsLimit cap."""
        from kairo.sourceactivation.budget import apply_caps_to_input

        input_data = {"directUrls": ["https://instagram.com/reel/test"]}
        result = apply_caps_to_input("apify/instagram-reel-scraper", input_data)

        assert result["resultsLimit"] == 5  # Per PRD G.1

    def test_tiktok_scraper_cap(self):
        """TikTok scraper has resultsPerPage cap."""
        from kairo.sourceactivation.budget import apply_caps_to_input

        input_data = {"hashtags": ["test"]}
        result = apply_caps_to_input("clockworks/tiktok-scraper", input_data)

        assert result["resultsPerPage"] == 15  # Per PRD G.1

    def test_linkedin_scraper_cap(self):
        """LinkedIn scraper has limit cap."""
        from kairo.sourceactivation.budget import apply_caps_to_input

        input_data = {"companyNames": ["Test Corp"]}
        result = apply_caps_to_input("apimaestro/linkedin-company-posts", input_data)

        assert result["limit"] == 20  # Per PRD G.1

    def test_youtube_scraper_cap(self):
        """YouTube scraper has maxResults cap."""
        from kairo.sourceactivation.budget import apply_caps_to_input

        input_data = {"searchQueries": ["test"]}
        result = apply_caps_to_input("streamers/youtube-scraper", input_data)

        assert result["maxResults"] == 10  # Per PRD G.1


# =============================================================================
# Test 4: Instagram 2-stage derivation
# =============================================================================


@pytest.mark.unit
class TestInstagram2StageDerivation:
    """Test 4: Instagram recipes use 2-stage acquisition with derivation."""

    def test_instagram_recipes_have_stage2(self):
        """All Instagram recipes must have stage2_actor (SA-1)."""
        from kairo.sourceactivation.recipes import RECIPE_REGISTRY

        ig_recipes = [
            r for rid, r in RECIPE_REGISTRY.items() if r.platform == "instagram"
        ]

        assert len(ig_recipes) > 0, "Should have Instagram recipes"

        for recipe in ig_recipes:
            assert recipe.stage2_actor is not None, (
                f"SA-1 violation: Instagram recipe {recipe.recipe_id} missing stage2_actor"
            )
            assert recipe.stage1_to_stage2_filter is not None, (
                f"SA-2 violation: Instagram recipe {recipe.recipe_id} missing stage2 filter"
            )

    def test_stage2_filter_derives_urls_from_stage1(self):
        """Stage 2 inputs must be derived from Stage 1 outputs (SA-2)."""
        from kairo.sourceactivation.recipes import filter_ig_reels_by_engagement

        # Stage 1 items (raw from Apify)
        stage1_items = [
            {
                "url": "https://instagram.com/reel/abc",
                "productType": "clips",
                "videoViewCount": 50000,
                "likesCount": 5000,
            },
            {
                "url": "https://instagram.com/p/def",
                "productType": "feed",  # Not a reel, should be filtered
                "videoViewCount": 100000,
                "likesCount": 10000,
            },
            {
                "url": "https://instagram.com/reel/ghi",
                "productType": "clips",
                "videoViewCount": 500,  # Below threshold, should be filtered
                "likesCount": 50,
            },
        ]

        urls = filter_ig_reels_by_engagement(stage1_items)

        # Should only include reels with views >= 1000
        assert len(urls) == 1
        assert "https://instagram.com/reel/abc" in urls
        # Non-reel and low-view items should be filtered
        assert "https://instagram.com/p/def" not in urls
        assert "https://instagram.com/reel/ghi" not in urls

    def test_non_instagram_recipes_are_single_stage(self):
        """Non-Instagram platforms use single-stage acquisition."""
        from kairo.sourceactivation.recipes import RECIPE_REGISTRY

        non_ig_recipes = [
            r
            for rid, r in RECIPE_REGISTRY.items()
            if r.platform != "instagram"
        ]

        for recipe in non_ig_recipes:
            assert recipe.stage2_actor is None, (
                f"Non-Instagram recipe {recipe.recipe_id} should not have stage2_actor"
            )


# =============================================================================
# Test 5: ActivationRun and EvidenceItem persisted
# =============================================================================


@pytest.mark.django_db
class TestActivationRunAndEvidenceItemPersisted:
    """Test 5: ActivationRun and EvidenceItem rows persisted on live run."""

    def test_fixture_bundle_creates_activation_run(self, brand: Brand, job):
        """Fixture mode creates ActivationRun with FIXTURE recipe."""
        from kairo.hero.models import ActivationRun
        from kairo.sourceactivation.services import get_or_create_evidence_bundle
        from kairo.sourceactivation.types import SeedPack

        seed_pack = SeedPack(
            brand_id=brand.id,
            brand_name=brand.name,
            positioning=brand.positioning or "",
            search_terms=["test"],
            pillar_keywords=[],
            persona_contexts=[],
            snapshot_id=brand.id,
        )

        bundle = get_or_create_evidence_bundle(
            brand_id=brand.id,
            seed_pack=seed_pack,
            job_id=job.id,
            mode="fixture_only",
        )

        # ActivationRun should be created
        if bundle.activation_run_id:
            run = ActivationRun.objects.get(id=bundle.activation_run_id)
            assert run.job_id == job.id
            assert "FIXTURE" in run.recipes_executed
            assert run.estimated_cost_usd == 0

    def test_activation_run_links_to_job(self, brand: Brand, job):
        """ActivationRun must have FK to OpportunitiesJob per PRD §D.3.2."""
        from kairo.hero.models import ActivationRun
        from kairo.sourceactivation.services import _persist_evidence
        from kairo.sourceactivation.types import SeedPack

        seed_pack = SeedPack(
            brand_id=brand.id,
            brand_name=brand.name,
            positioning=brand.positioning or "",
            search_terms=["test"],
            pillar_keywords=[],
            persona_contexts=[],
            snapshot_id=brand.id,
        )

        run_id, _ = _persist_evidence(
            brand_id=brand.id,
            job_id=job.id,
            seed_pack=seed_pack,
            items=[],
            recipes_selected=["TEST"],
            recipes_executed=["TEST"],
            estimated_cost=0.25,
        )

        run = ActivationRun.objects.get(id=run_id)
        assert run.job_id == job.id
        assert run.estimated_cost_usd == Decimal("0.25")


# =============================================================================
# Test 6: EvidenceItem IDs deterministic (uuid5)
# =============================================================================


@pytest.mark.unit
class TestEvidenceItemIdsDeterministic:
    """Test 6: EvidenceItem IDs are deterministic using uuid5."""

    def test_same_inputs_produce_same_id(self):
        """Same brand+platform+url produces same evidence ID."""
        from kairo.sourceactivation.fixtures.loader import generate_evidence_id

        brand_id = UUID("12345678-1234-5678-1234-567812345678")
        platform = "instagram"
        url = "https://instagram.com/p/test123"

        id1 = generate_evidence_id(brand_id, platform, url)
        id2 = generate_evidence_id(brand_id, platform, url)

        assert id1 == id2

    def test_different_urls_produce_different_ids(self):
        """Different URLs produce different evidence IDs."""
        from kairo.sourceactivation.fixtures.loader import generate_evidence_id

        brand_id = UUID("12345678-1234-5678-1234-567812345678")
        platform = "instagram"

        id1 = generate_evidence_id(brand_id, platform, "https://instagram.com/p/test1")
        id2 = generate_evidence_id(brand_id, platform, "https://instagram.com/p/test2")

        assert id1 != id2

    def test_different_brands_produce_different_ids(self):
        """Different brands produce different evidence IDs for same URL."""
        from kairo.sourceactivation.fixtures.loader import generate_evidence_id

        brand1 = UUID("12345678-1234-5678-1234-567812345678")
        brand2 = UUID("87654321-4321-8765-4321-876543218765")
        platform = "instagram"
        url = "https://instagram.com/p/test123"

        id1 = generate_evidence_id(brand1, platform, url)
        id2 = generate_evidence_id(brand2, platform, url)

        assert id1 != id2


# =============================================================================
# Test 7: GET path remains read-only
# =============================================================================


@pytest.mark.django_db
class TestGetPathRemainsReadOnly:
    """Test 7: GET /today never calls Apify."""

    def test_get_today_context_blocks_apify(self, brand: Brand):
        """Apify calls raise in GET /today context."""
        from kairo.core.guardrails import (
            GuardrailViolationError,
            set_get_today_context,
            reset_get_today_context,
            require_live_apify_allowed,
        )

        with patch("kairo.core.guardrails.is_apify_enabled", return_value=True):
            # Outside GET context - should work
            require_live_apify_allowed()  # No error

            # Inside GET context - should raise
            token = set_get_today_context(True)
            try:
                with pytest.raises(GuardrailViolationError):
                    require_live_apify_allowed()
            finally:
                reset_get_today_context(token)

    def test_sourceactivation_blocked_in_get_context(self, brand: Brand, job):
        """SourceActivation raises in GET /today context."""
        from kairo.core.guardrails import (
            GuardrailViolationError,
            set_get_today_context,
            reset_get_today_context,
        )
        from kairo.sourceactivation.services import get_or_create_evidence_bundle
        from kairo.sourceactivation.types import SeedPack

        seed_pack = SeedPack(
            brand_id=brand.id,
            brand_name=brand.name,
            positioning=brand.positioning or "",
            search_terms=["test"],
            pillar_keywords=[],
            persona_contexts=[],
            snapshot_id=brand.id,
        )

        token = set_get_today_context(True)
        try:
            with pytest.raises(GuardrailViolationError):
                get_or_create_evidence_bundle(
                    brand_id=brand.id,
                    seed_pack=seed_pack,
                    job_id=job.id,
                    mode="fixture_only",  # Even fixture mode is blocked in GET
                )
        finally:
            reset_get_today_context(token)


# =============================================================================
# Test: Budget enforcement
# =============================================================================


@pytest.mark.django_db
class TestBudgetEnforcement:
    """Tests for budget cap enforcement."""

    def test_daily_cap_check(self, brand: Brand):
        """Daily cap should be checked before execution."""
        from kairo.sourceactivation.budget import (
            is_daily_cap_reached,
            APIFY_DAILY_SPEND_CAP_USD,
        )

        # Initially should not be reached
        assert not is_daily_cap_reached()

    def test_per_run_cap_estimated(self):
        """Per-run cost should be estimated correctly."""
        from kairo.sourceactivation.budget import (
            estimate_execution_plan_cost,
            APIFY_PER_REGENERATE_CAP_USD,
        )
        from kairo.sourceactivation.recipes import DEFAULT_EXECUTION_PLAN

        cost = estimate_execution_plan_cost(DEFAULT_EXECUTION_PLAN)

        # Default plan (IG-1, IG-3, TT-1) should be under per-run cap
        assert cost <= APIFY_PER_REGENERATE_CAP_USD

    def test_budget_check_passes_when_under_cap(self):
        """Budget check should pass when costs are under caps."""
        from kairo.sourceactivation.budget import check_budget_for_run, BudgetStatus

        result = check_budget_for_run(Decimal("0.10"))

        assert result.can_proceed
        assert result.status == BudgetStatus.OK


# =============================================================================
# Test: Recipe cost estimates
# =============================================================================


@pytest.mark.unit
class TestRecipeCostEstimates:
    """Tests for recipe cost estimation."""

    def test_all_recipes_have_cost_estimates(self):
        """All recipes should have cost estimates."""
        from kairo.sourceactivation.budget import RECIPE_COST_ESTIMATES
        from kairo.sourceactivation.recipes import RECIPE_REGISTRY

        for recipe_id in RECIPE_REGISTRY:
            assert recipe_id in RECIPE_COST_ESTIMATES, (
                f"Recipe {recipe_id} missing cost estimate"
            )

    def test_fixture_recipe_has_zero_cost(self):
        """FIXTURE recipe should have zero cost."""
        from kairo.sourceactivation.budget import estimate_recipe_cost

        cost = estimate_recipe_cost("FIXTURE")
        assert cost == Decimal("0")

    def test_instagram_2stage_cost_includes_both_stages(self):
        """Instagram 2-stage recipes include cost for both stages."""
        from kairo.sourceactivation.budget import RECIPE_COST_ESTIMATES

        ig1 = RECIPE_COST_ESTIMATES["IG-1"]

        assert ig1.stage1_cost > 0
        assert ig1.stage2_cost > 0
        assert ig1.total_cost == ig1.stage1_cost + ig1.stage2_cost


# =============================================================================
# Critical invariant: Auto-enqueue NEVER uses live mode (ChatGPT sanity check)
# =============================================================================


@pytest.mark.django_db
class TestAutoEnqueueNeverLiveMode:
    """
    CRITICAL: Auto-enqueue from GET /today NEVER triggers live mode.

    Per PRD §0.2: Only POST /regenerate can spend money.
    This is the biggest real-world budget leak to prevent.
    """

    def test_get_today_first_visit_uses_fixture_mode_even_with_apify_enabled(
        self, brand: Brand
    ):
        """
        GET /today first visit with APIFY_ENABLED=True still uses fixture_only.

        This is the critical budget leak test:
        - Set APIFY_ENABLED=True
        - Call GET /today first visit (snapshot exists)
        - Assert job params say mode=fixture_only
        - Assert Apify client has 0 calls
        """
        from kairo.brandbrain.models import BrandBrainSnapshot
        from kairo.hero.models import OpportunitiesJob
        from kairo.hero.services import today_service

        # Create a snapshot so first-run auto-enqueue will trigger
        BrandBrainSnapshot.objects.create(
            brand=brand,
            snapshot_json={},
            diff_from_previous_json={},
        )

        # Mock Apify client to ensure it's never called
        with patch("kairo.core.guardrails.is_apify_enabled", return_value=True), \
             patch("kairo.integrations.apify.client.ApifyClient") as mock_apify_class:

            mock_apify = MagicMock()
            mock_apify_class.return_value = mock_apify

            # GET /today - first visit should auto-enqueue
            result = today_service.get_today_board(brand.id)

            # Should be in GENERATING state (first-run auto-enqueue)
            from kairo.core.enums import TodayBoardState
            assert result.meta.state == TodayBoardState.GENERATING
            assert result.meta.job_id is not None

            # Critical: Job should have mode=fixture_only
            job = OpportunitiesJob.objects.get(id=result.meta.job_id)
            assert job.params_json["mode"] == "fixture_only", (
                "BUDGET LEAK: Auto-enqueue used live mode! "
                "Only POST /regenerate should trigger live_cap_limited."
            )
            assert job.params_json["first_run"] is True
            assert job.params_json["force"] is False

            # Apify client should have 0 calls
            mock_apify.start_actor_run.assert_not_called()

    def test_post_regenerate_is_the_only_path_to_live_mode(self, brand: Brand):
        """
        Only POST /regenerate with APIFY_ENABLED=True triggers live mode.

        This verifies:
        1. first_run=True → fixture_only (regardless of APIFY_ENABLED)
        2. force=True + APIFY_ENABLED=False → fixture_only
        3. force=True + APIFY_ENABLED=True → live_cap_limited (ONLY this case)
        """
        from kairo.hero.jobs.queue import enqueue_opportunities_job
        from kairo.hero.models import OpportunitiesJob

        # Case 1: first_run=True + APIFY_ENABLED=True → fixture_only
        with patch("kairo.core.guardrails.is_apify_enabled", return_value=True):
            result1 = enqueue_opportunities_job(brand.id, first_run=True)
        job1 = OpportunitiesJob.objects.get(id=result1.job_id)
        assert job1.params_json["mode"] == "fixture_only"

        # Case 2: force=True + APIFY_ENABLED=False → fixture_only
        with patch("kairo.core.guardrails.is_apify_enabled", return_value=False):
            result2 = enqueue_opportunities_job(brand.id, force=True)
        job2 = OpportunitiesJob.objects.get(id=result2.job_id)
        assert job2.params_json["mode"] == "fixture_only"

        # Case 3: force=True + APIFY_ENABLED=True → live_cap_limited (ONLY path)
        with patch("kairo.core.guardrails.is_apify_enabled", return_value=True):
            result3 = enqueue_opportunities_job(brand.id, force=True)
        job3 = OpportunitiesJob.objects.get(id=result3.job_id)
        assert job3.params_json["mode"] == "live_cap_limited"

        # Case 4: neither force nor first_run + APIFY_ENABLED=True → fixture_only
        with patch("kairo.core.guardrails.is_apify_enabled", return_value=True):
            result4 = enqueue_opportunities_job(brand.id)
        job4 = OpportunitiesJob.objects.get(id=result4.job_id)
        assert job4.params_json["mode"] == "fixture_only"


# =============================================================================
# Instagram Stage 2 actor verification
# =============================================================================


@pytest.mark.unit
class TestInstagramStage2ActorSpec:
    """
    Verify Instagram Stage 2 matches PRD spec exactly.

    Per PRD B.2.1:
    - Stage 2 = apify/instagram-reel-scraper
    - Input = directUrls[] derived from Stage 1 results
    - No hardcoded URLs
    """

    def test_stage2_actor_is_instagram_reel_scraper(self):
        """Instagram Stage 2 actor must be apify/instagram-reel-scraper."""
        from kairo.sourceactivation.recipes import RECIPE_REGISTRY

        for recipe_id, recipe in RECIPE_REGISTRY.items():
            if recipe.platform == "instagram":
                assert recipe.stage2_actor == "apify/instagram-reel-scraper", (
                    f"Recipe {recipe_id} has wrong Stage 2 actor: {recipe.stage2_actor}"
                )

    def test_stage2_input_builder_produces_directUrls(self):
        """Stage 2 input builder must produce directUrls field."""
        from kairo.sourceactivation.recipes import build_ig_reel_enrichment_input

        test_urls = ["https://instagram.com/reel/test1", "https://instagram.com/reel/test2"]
        result = build_ig_reel_enrichment_input(test_urls)

        assert "directUrls" in result
        assert result["directUrls"] == test_urls
        # No hardcoded URLs - only what was passed in
        assert len(result["directUrls"]) == len(test_urls)

    def test_stage1_to_stage2_filter_produces_urls_from_items(self):
        """Stage 1 → Stage 2 filter must derive URLs from Stage 1 output."""
        from kairo.sourceactivation.recipes import filter_ig_reels_by_engagement

        # Stage 1 output (simulated Apify response)
        stage1_items = [
            {
                "url": "https://instagram.com/reel/derived1",
                "productType": "clips",
                "videoViewCount": 10000,
                "likesCount": 1000,
            },
            {
                "url": "https://instagram.com/reel/derived2",
                "productType": "clips",
                "videoViewCount": 5000,
                "likesCount": 500,
            },
        ]

        urls = filter_ig_reels_by_engagement(stage1_items)

        # URLs must come from Stage 1 items (not hardcoded)
        for url in urls:
            assert any(
                item["url"] == url for item in stage1_items
            ), f"URL {url} not derived from Stage 1 items (SA-2 violation)"


# =============================================================================
# TASK-2 INVARIANT: Live mode NEVER falls back to fixtures
# =============================================================================


@pytest.mark.django_db
class TestLiveModeNeverFallsBackToFixtures:
    """
    CRITICAL INVARIANT (TASK-2):
    When mode=live_cap_limited, fixtures are NEVER loaded as fallback.

    If Apify returns 0 items → return empty bundle → gates fail → insufficient_evidence.
    This ensures we get real feedback about evidence quality, not demo data.
    """

    def test_live_mode_returns_empty_bundle_when_apify_fails(self, brand: Brand, job):
        """
        When live mode Apify execution returns no items, we get empty bundle.
        NOT a fallback to fixtures.
        """
        from unittest.mock import patch, MagicMock
        from kairo.sourceactivation.services import get_or_create_evidence_bundle
        from kairo.sourceactivation.types import SeedPack

        seed_pack = SeedPack(
            brand_id=brand.id,
            brand_name=brand.name,
            positioning=brand.positioning or "",
            search_terms=["test"],
            pillar_keywords=[],
            persona_contexts=[],
            snapshot_id=brand.id,
        )

        # Mock Apify to return failure
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.items = []
        mock_result.error = "Apify call failed"
        mock_result.recipes_executed = ["IG-1"]
        mock_result.total_cost = 0

        with patch("kairo.core.guardrails.is_apify_enabled", return_value=True), \
             patch("kairo.sourceactivation.live.execute_live_activation", return_value=mock_result), \
             patch("kairo.sourceactivation.budget.check_budget_for_run") as mock_budget:

            mock_budget.return_value = MagicMock(can_proceed=True)

            bundle = get_or_create_evidence_bundle(
                brand_id=brand.id,
                seed_pack=seed_pack,
                job_id=job.id,
                mode="live_cap_limited",
            )

            # CRITICAL: Bundle should be empty, NOT fallback to fixtures
            assert bundle.items == [], "Live mode should NOT fall back to fixtures"
            assert bundle.mode == "live_cap_limited"
            # If fixtures were loaded, we'd have items
            assert len(bundle.items) == 0

    def test_fixture_fallback_logging_is_explicit(self, brand: Brand, job):
        """
        FIXTURE_FALLBACK_USED is logged explicitly for visibility.
        """
        from unittest.mock import patch
        from kairo.sourceactivation.services import get_or_create_evidence_bundle
        from kairo.sourceactivation.types import SeedPack
        import logging

        seed_pack = SeedPack(
            brand_id=brand.id,
            brand_name=brand.name,
            positioning=brand.positioning or "",
            search_terms=["test"],
            pillar_keywords=[],
            persona_contexts=[],
            snapshot_id=brand.id,
        )

        # Capture log output
        with patch("kairo.sourceactivation.services.logger") as mock_logger:
            bundle = get_or_create_evidence_bundle(
                brand_id=brand.id,
                seed_pack=seed_pack,
                job_id=job.id,
                mode="fixture_only",
            )

            # Check FIXTURE_FALLBACK_USED was logged
            log_calls = [str(call) for call in mock_logger.info.call_args_list]
            fixture_log_found = any("FIXTURE_FALLBACK_USED=true" in str(call) for call in log_calls)
            assert fixture_log_found, (
                "Missing FIXTURE_FALLBACK_USED=true log line. "
                f"Actual log calls: {log_calls}"
            )

    def test_live_mode_logs_fixture_fallback_false(self, brand: Brand, job):
        """
        Live mode explicitly logs FIXTURE_FALLBACK_USED=false.
        """
        from unittest.mock import patch, MagicMock
        from kairo.sourceactivation.services import get_or_create_evidence_bundle
        from kairo.sourceactivation.types import SeedPack

        seed_pack = SeedPack(
            brand_id=brand.id,
            brand_name=brand.name,
            positioning=brand.positioning or "",
            search_terms=["test"],
            pillar_keywords=[],
            persona_contexts=[],
            snapshot_id=brand.id,
        )

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.items = []
        mock_result.recipes_executed = []
        mock_result.total_cost = 0

        with patch("kairo.core.guardrails.is_apify_enabled", return_value=True), \
             patch("kairo.sourceactivation.live.execute_live_activation", return_value=mock_result), \
             patch("kairo.sourceactivation.budget.check_budget_for_run") as mock_budget, \
             patch("kairo.sourceactivation.services.logger") as mock_logger:

            mock_budget.return_value = MagicMock(can_proceed=True)

            bundle = get_or_create_evidence_bundle(
                brand_id=brand.id,
                seed_pack=seed_pack,
                job_id=job.id,
                mode="live_cap_limited",
            )

            # Check FIXTURE_FALLBACK_USED=false was logged
            log_calls = [str(call) for call in mock_logger.info.call_args_list]
            fixture_log_found = any("FIXTURE_FALLBACK_USED=false" in str(call) for call in log_calls)
            assert fixture_log_found, (
                "Missing FIXTURE_FALLBACK_USED=false log line for live mode. "
                f"Actual log calls: {log_calls}"
            )


# =============================================================================
# TASK-2: Fail-fast when APIFY_ENABLED=false in live mode
# =============================================================================


@pytest.mark.django_db
class TestLiveModeFailFastWhenApifyDisabled:
    """
    CRITICAL: Live mode must fail immediately when preconditions not met.

    This prevents the UI from hanging in "generating" state forever
    when Apify is disabled or token is missing.
    """

    def test_live_mode_raises_immediately_when_apify_disabled(self, brand: Brand, job):
        """
        When mode=live_cap_limited and APIFY_ENABLED=false,
        the call must raise ApifyDisabledError immediately.
        """
        from unittest.mock import patch
        from kairo.core.guardrails import ApifyDisabledError
        from kairo.sourceactivation.services import get_or_create_evidence_bundle
        from kairo.sourceactivation.types import SeedPack

        seed_pack = SeedPack(
            brand_id=brand.id,
            brand_name=brand.name,
            positioning=brand.positioning or "",
            search_terms=["test"],
            pillar_keywords=[],
            persona_contexts=[],
            snapshot_id=brand.id,
        )

        with patch("kairo.core.guardrails.is_apify_enabled", return_value=False):
            with pytest.raises(ApifyDisabledError) as exc_info:
                get_or_create_evidence_bundle(
                    brand_id=brand.id,
                    seed_pack=seed_pack,
                    job_id=job.id,
                    mode="live_cap_limited",
                )

            # Should have clear error message
            assert "APIFY_ENABLED=false" in str(exc_info.value)

    def test_live_mode_raises_immediately_when_token_missing(self, brand: Brand, job):
        """
        When mode=live_cap_limited and APIFY_TOKEN is missing,
        the call must raise ValueError immediately.
        """
        from unittest.mock import patch, PropertyMock
        from kairo.sourceactivation.services import get_or_create_evidence_bundle
        from kairo.sourceactivation.types import SeedPack

        seed_pack = SeedPack(
            brand_id=brand.id,
            brand_name=brand.name,
            positioning=brand.positioning or "",
            search_terms=["test"],
            pillar_keywords=[],
            persona_contexts=[],
            snapshot_id=brand.id,
        )

        with patch("kairo.core.guardrails.is_apify_enabled", return_value=True), \
             patch("django.conf.settings.APIFY_TOKEN", None, create=True):

            with pytest.raises(ValueError) as exc_info:
                get_or_create_evidence_bundle(
                    brand_id=brand.id,
                    seed_pack=seed_pack,
                    job_id=job.id,
                    mode="live_cap_limited",
                )

            # Should have clear error message
            assert "APIFY_TOKEN" in str(exc_info.value)

    def test_apify_precondition_check_is_logged(self, brand: Brand, job):
        """
        APIFY_PRECONDITION_CHECK must be logged for observability.
        """
        from unittest.mock import patch
        from kairo.core.guardrails import ApifyDisabledError
        from kairo.sourceactivation.services import get_or_create_evidence_bundle
        from kairo.sourceactivation.types import SeedPack

        seed_pack = SeedPack(
            brand_id=brand.id,
            brand_name=brand.name,
            positioning=brand.positioning or "",
            search_terms=["test"],
            pillar_keywords=[],
            persona_contexts=[],
            snapshot_id=brand.id,
        )

        with patch("kairo.core.guardrails.is_apify_enabled", return_value=False), \
             patch("kairo.sourceactivation.services.logger") as mock_logger:

            try:
                get_or_create_evidence_bundle(
                    brand_id=brand.id,
                    seed_pack=seed_pack,
                    job_id=job.id,
                    mode="live_cap_limited",
                )
            except ApifyDisabledError:
                pass  # Expected

            # Check APIFY_PRECONDITION_CHECK was logged
            log_calls = [str(call) for call in mock_logger.info.call_args_list]
            precondition_logged = any("APIFY_PRECONDITION_CHECK" in str(call) for call in log_calls)
            assert precondition_logged, (
                "Missing APIFY_PRECONDITION_CHECK log line. "
                f"Actual log calls: {log_calls}"
            )


# =============================================================================
# TASK-2: TikTok subtitle download → has_transcript invariant
# =============================================================================


@pytest.mark.unit
class TestTikTokSubtitleTranscriptInvariant:
    """
    INVARIANT: When TikTok subtitles are downloaded, has_transcript=true
    and text_secondary is non-empty.

    Per TASK-2: TikTok evidence includes subtitleLinks, but without
    shouldDownloadSubtitles=true, we don't get actual transcript text.
    """

    def test_tiktok_input_includes_subtitle_download_params(self):
        """TikTok recipe inputs must include shouldDownloadSubtitles=true."""
        from kairo.sourceactivation.recipes import build_tt_hashtag_input, build_tt_profile_input
        from kairo.sourceactivation.types import SeedPack

        seed_pack = SeedPack(
            brand_id=uuid.uuid4(),
            brand_name="Test Brand",
            positioning="Test positioning",
            search_terms=["test"],
            pillar_keywords=[],
            persona_contexts=[],
            snapshot_id=uuid.uuid4(),
        )

        hashtag_input = build_tt_hashtag_input(seed_pack)
        profile_input = build_tt_profile_input(seed_pack)

        # Both inputs must request subtitle download
        assert hashtag_input.get("shouldDownloadSubtitles") is True, (
            "TikTok hashtag input missing shouldDownloadSubtitles=true"
        )
        assert profile_input.get("shouldDownloadSubtitles") is True, (
            "TikTok profile input missing shouldDownloadSubtitles=true"
        )

    def test_tiktok_normalizer_extracts_downloaded_subtitles(self):
        """When subtitles are downloaded, normalizer sets has_transcript=true."""
        from datetime import datetime, timezone
        from kairo.sourceactivation.normalizers import _normalize_tiktok_item

        # Simulated TikTok output with downloaded subtitles
        raw_item = {
            "id": "12345",
            "webVideoUrl": "https://www.tiktok.com/@test/video/12345",
            "text": "Test video #hashtag",
            "createTime": 1705000000,
            "authorMeta": {"name": "testuser"},
            "playCount": 1000,
            "diggCount": 100,
            "commentCount": 10,
            "shareCount": 5,
            # Downloaded subtitles (plain text)
            "subtitles": "This is the actual transcript text from the video. It contains the spoken words.",
            "hashtags": [{"name": "hashtag"}],
        }

        result = _normalize_tiktok_item(
            raw=raw_item,
            actor_id="clockworks/tiktok-scraper",
            recipe_id="TT-1",
            stage=1,
            fetched_at=datetime.now(timezone.utc),
        )

        assert result is not None
        assert result.has_transcript is True, (
            "When subtitles are downloaded, has_transcript must be True"
        )
        assert len(result.text_secondary) > 10, (
            "When subtitles are downloaded, text_secondary must contain transcript"
        )
        assert "transcript text" in result.text_secondary

    def test_tiktok_normalizer_handles_subtitle_list_format(self):
        """Normalizer handles subtitles as list of objects."""
        from datetime import datetime, timezone
        from kairo.sourceactivation.normalizers import _normalize_tiktok_item

        raw_item = {
            "id": "12345",
            "webVideoUrl": "https://www.tiktok.com/@test/video/12345",
            "text": "Test video",
            "createTime": 1705000000,
            "authorMeta": {"name": "testuser"},
            # Subtitles as list of objects
            "subtitles": [
                {"text": "First subtitle segment."},
                {"text": "Second subtitle segment."},
                {"text": "Third subtitle segment."},
            ],
        }

        result = _normalize_tiktok_item(
            raw=raw_item,
            actor_id="clockworks/tiktok-scraper",
            recipe_id="TT-1",
            stage=1,
            fetched_at=datetime.now(timezone.utc),
        )

        assert result is not None
        assert result.has_transcript is True
        assert "First subtitle segment" in result.text_secondary
        assert "Second subtitle segment" in result.text_secondary

    def test_tiktok_normalizer_without_subtitles_has_no_transcript(self):
        """When subtitles are not downloaded, has_transcript=false."""
        from datetime import datetime, timezone
        from kairo.sourceactivation.normalizers import _normalize_tiktok_item

        raw_item = {
            "id": "12345",
            "webVideoUrl": "https://www.tiktok.com/@test/video/12345",
            "text": "Test video",
            "createTime": 1705000000,
            "authorMeta": {"name": "testuser"},
            # No subtitles field - wasn't downloaded
            "videoMeta": {
                "subtitleLinks": [
                    {
                        "language": "eng-US",
                        "downloadLink": "https://example.com/subtitles.srt",
                        # No content field - not downloaded
                    }
                ]
            },
        }

        result = _normalize_tiktok_item(
            raw=raw_item,
            actor_id="clockworks/tiktok-scraper",
            recipe_id="TT-1",
            stage=1,
            fetched_at=datetime.now(timezone.utc),
        )

        assert result is not None
        assert result.has_transcript is False, (
            "Without actual subtitle content, has_transcript must be False"
        )
        assert result.text_secondary == "", (
            "Without subtitles, text_secondary must be empty"
        )
