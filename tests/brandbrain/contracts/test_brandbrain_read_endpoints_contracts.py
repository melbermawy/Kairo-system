"""
Contract tests for BrandBrain read-path endpoints.

PR-0: Skeleton tests that define expected behavior.
PR-5: Compile orchestration endpoints implemented.
PR-7: API Surface completed - all read endpoints implemented.

These tests verify:
1. Response status codes
2. Response payload shapes (matching spec TypeScript interfaces)
3. Payload cap rules (compact vs include=full)
4. Read-path boundary (no side effects)

Per spec Section 1.1 (Performance & Latency Contracts):
- Read-path endpoints: GET /latest, GET /history, GET /status, GET /overrides
- Must be DB reads only, no side effects
- P95 latency budgets enforced

Per spec Section 10 (APIs):
- GET /api/brands/:id/brandbrain/latest -> LatestSnapshotResponse
- GET /api/brands/:id/brandbrain/history -> HistoryResponse (paginated)
- GET /api/brands/:id/brandbrain/compile/:compile_run_id/status -> CompileStatusResponse
- GET/PATCH /api/brands/:id/brandbrain/overrides -> overrides CRUD

Note: Full implementation tests are in test_pr7_api_surface.py.
These contract tests focus on response shape validation.
"""

import pytest


# =============================================================================
# EXPECTED RESPONSE SHAPES (from spec TypeScript interfaces)
# =============================================================================

# Per spec Section 1.1:
# interface LatestSnapshotResponse {
#   snapshot_id: UUID;
#   brand_id: UUID;
#   snapshot_json: BrandBrainSnapshot;
#   created_at: datetime;
#   compile_run_id: UUID;
# }
LATEST_SNAPSHOT_REQUIRED_FIELDS = {
    "snapshot_id",
    "brand_id",
    "snapshot_json",
    "created_at",
    "compile_run_id",
}

# Per spec Section 1.1 (with ?include=full):
# interface LatestSnapshotResponseFull extends LatestSnapshotResponse {
#   evidence_status: EvidenceStatus;
#   qa_report: QAReport;
#   bundle_summary: BundleSummary;
# }
LATEST_SNAPSHOT_FULL_ADDITIONAL_FIELDS = {
    "evidence_status",
    "qa_report",
    "bundle_summary",
}

# Per spec Section 10:
# interface CompileStatusResponse {
#   compile_run_id: UUID;
#   status: "PENDING" | "RUNNING" | "SUCCEEDED" | "FAILED";
#   progress?: {...};
#   snapshot?: BrandBrainSnapshot;
#   evidence_status?: EvidenceStatus;
#   error?: string;
# }
COMPILE_STATUS_REQUIRED_FIELDS = {
    "compile_run_id",
    "status",
}
COMPILE_STATUS_VALID_STATUSES = {"PENDING", "RUNNING", "SUCCEEDED", "FAILED"}


# =============================================================================
# HELPER TO CHECK RESPONSE SHAPE
# =============================================================================


def assert_has_required_fields(data: dict, required_fields: set, context: str = ""):
    """Assert that data dict contains all required fields."""
    missing = required_fields - set(data.keys())
    assert not missing, f"{context}Missing required fields: {missing}"


def assert_excludes_fields(data: dict, excluded_fields: set, context: str = ""):
    """Assert that data dict does NOT contain excluded fields."""
    present = excluded_fields & set(data.keys())
    assert not present, f"{context}Unexpected fields in compact response: {present}"


# =============================================================================
# GET /api/brands/:id/brandbrain/latest
# =============================================================================


@pytest.mark.contract
@pytest.mark.skip(reason="Endpoint not implemented until PR-7")
class TestGetLatestEndpoint:
    """
    Contract tests for GET /api/brands/:id/brandbrain/latest.

    Per spec Section 1.1:
    - P95 target: 50ms
    - Returns compact payload by default
    - ?include=full for verbose mode
    """

    def test_returns_200_for_existing_brand_with_snapshot(self, client):
        """Should return 200 OK when brand has a compiled snapshot."""
        # TODO PR-7: Create brand + snapshot, then GET /latest
        brand_id = "test-brand-id"
        response = client.get(f"/api/brands/{brand_id}/brandbrain/latest")

        assert response.status_code == 200

    def test_returns_404_for_nonexistent_brand(self, client):
        """Should return 404 when brand doesn't exist."""
        response = client.get("/api/brands/nonexistent-uuid/brandbrain/latest")

        assert response.status_code == 404

    def test_returns_404_for_brand_without_snapshot(self, client):
        """Should return 404 when brand exists but has no compiled snapshot."""
        # TODO PR-7: Create brand without snapshot, then GET /latest
        pass

    def test_compact_response_has_required_fields(self, client):
        """Compact response (default) should have required fields."""
        brand_id = "test-brand-id"
        response = client.get(f"/api/brands/{brand_id}/brandbrain/latest")

        data = response.json()
        assert_has_required_fields(
            data,
            LATEST_SNAPSHOT_REQUIRED_FIELDS,
            context="GET /latest compact: ",
        )

    def test_compact_response_excludes_verbose_fields(self, client):
        """Compact response should NOT include verbose fields."""
        brand_id = "test-brand-id"
        response = client.get(f"/api/brands/{brand_id}/brandbrain/latest")

        data = response.json()
        assert_excludes_fields(
            data,
            LATEST_SNAPSHOT_FULL_ADDITIONAL_FIELDS,
            context="GET /latest compact: ",
        )

    def test_full_response_includes_additional_fields(self, client):
        """Response with ?include=full should include additional fields."""
        brand_id = "test-brand-id"
        response = client.get(f"/api/brands/{brand_id}/brandbrain/latest?include=full")

        data = response.json()
        assert_has_required_fields(
            data,
            LATEST_SNAPSHOT_REQUIRED_FIELDS | LATEST_SNAPSHOT_FULL_ADDITIONAL_FIELDS,
            context="GET /latest?include=full: ",
        )

    def test_snapshot_json_excludes_raw_refs_in_compact_mode(self, client):
        """Compact snapshot_json should not include raw_refs arrays."""
        brand_id = "test-brand-id"
        response = client.get(f"/api/brands/{brand_id}/brandbrain/latest")

        data = response.json()
        snapshot_json = data.get("snapshot_json", {})

        # Walk the snapshot to ensure no raw_refs at any level
        # (This is a simplified check - full impl would be recursive)
        examples = snapshot_json.get("examples", {})
        canonical_evidence = examples.get("canonical_evidence", [])
        for evidence in canonical_evidence:
            assert "raw_refs" not in evidence, "raw_refs should be excluded in compact mode"


# =============================================================================
# GET /api/brands/:id/brandbrain/history
# =============================================================================


@pytest.mark.contract
@pytest.mark.skip(reason="Endpoint not implemented until PR-7")
class TestGetHistoryEndpoint:
    """
    Contract tests for GET /api/brands/:id/brandbrain/history.

    Per spec Section 1.1:
    - P95 target: 100ms
    - Paginated: ?page_size=10&cursor=...
    - Default response: list of {id, created_at, diff_summary}
    - Excludes full snapshot_json by default
    """

    def test_returns_200_with_pagination(self, client):
        """Should return 200 OK with paginated list."""
        brand_id = "test-brand-id"
        response = client.get(f"/api/brands/{brand_id}/brandbrain/history")

        assert response.status_code == 200
        data = response.json()

        # Should have pagination structure
        assert "items" in data or isinstance(data, list)

    def test_returns_404_for_nonexistent_brand(self, client):
        """Should return 404 when brand doesn't exist."""
        response = client.get("/api/brands/nonexistent-uuid/brandbrain/history")

        assert response.status_code == 404

    def test_history_items_have_required_fields(self, client):
        """Each history item should have id, created_at, diff_summary."""
        brand_id = "test-brand-id"
        response = client.get(f"/api/brands/{brand_id}/brandbrain/history")

        data = response.json()
        items = data.get("items", data)  # Handle both paginated and flat list

        for item in items:
            assert "id" in item
            assert "created_at" in item
            assert "diff_summary" in item

    def test_history_items_exclude_full_snapshot_by_default(self, client):
        """History items should NOT include full snapshot_json by default."""
        brand_id = "test-brand-id"
        response = client.get(f"/api/brands/{brand_id}/brandbrain/history")

        data = response.json()
        items = data.get("items", data)

        for item in items:
            assert "snapshot_json" not in item
            assert "diff_from_previous_json" not in item

    def test_respects_page_size_parameter(self, client):
        """Should respect ?page_size parameter."""
        brand_id = "test-brand-id"
        response = client.get(f"/api/brands/{brand_id}/brandbrain/history?page_size=5")

        data = response.json()
        items = data.get("items", data)

        assert len(items) <= 5

    def test_page_size_capped_at_50(self, client):
        """Per spec, max page_size is 50."""
        brand_id = "test-brand-id"
        response = client.get(f"/api/brands/{brand_id}/brandbrain/history?page_size=100")

        data = response.json()
        items = data.get("items", data)

        # Should be clamped to 50 max
        assert len(items) <= 50


# =============================================================================
# GET /api/brands/:id/brandbrain/compile/:compile_run_id/status
# =============================================================================


@pytest.mark.contract
@pytest.mark.skip(reason="Endpoint not implemented until PR-7")
class TestGetCompileStatusEndpoint:
    """
    Contract tests for GET /api/brands/:id/brandbrain/compile/:compile_run_id/status.

    Per spec Section 1.1:
    - P95 target: 30ms
    - Pure DB read, no computation
    - Returns CompileStatusResponse shape
    """

    def test_returns_200_for_existing_compile_run(self, client):
        """Should return 200 OK when compile run exists."""
        brand_id = "test-brand-id"
        compile_run_id = "test-compile-run-id"
        response = client.get(
            f"/api/brands/{brand_id}/brandbrain/compile/{compile_run_id}/status"
        )

        assert response.status_code == 200

    def test_returns_404_for_nonexistent_compile_run(self, client):
        """Should return 404 when compile run doesn't exist."""
        brand_id = "test-brand-id"
        response = client.get(
            f"/api/brands/{brand_id}/brandbrain/compile/nonexistent-uuid/status"
        )

        assert response.status_code == 404

    def test_status_response_has_required_fields(self, client):
        """Status response should have compile_run_id and status."""
        brand_id = "test-brand-id"
        compile_run_id = "test-compile-run-id"
        response = client.get(
            f"/api/brands/{brand_id}/brandbrain/compile/{compile_run_id}/status"
        )

        data = response.json()
        assert_has_required_fields(
            data,
            COMPILE_STATUS_REQUIRED_FIELDS,
            context="GET /status: ",
        )

    def test_status_is_valid_enum_value(self, client):
        """Status should be one of PENDING, RUNNING, SUCCEEDED, FAILED."""
        brand_id = "test-brand-id"
        compile_run_id = "test-compile-run-id"
        response = client.get(
            f"/api/brands/{brand_id}/brandbrain/compile/{compile_run_id}/status"
        )

        data = response.json()
        assert data["status"] in COMPILE_STATUS_VALID_STATUSES

    def test_succeeded_status_includes_snapshot(self, client):
        """When status is SUCCEEDED, response should include snapshot."""
        brand_id = "test-brand-id"
        compile_run_id = "succeeded-compile-run-id"
        response = client.get(
            f"/api/brands/{brand_id}/brandbrain/compile/{compile_run_id}/status"
        )

        data = response.json()
        if data["status"] == "SUCCEEDED":
            assert "snapshot" in data
            assert "evidence_status" in data

    def test_failed_status_includes_error(self, client):
        """When status is FAILED, response should include error."""
        brand_id = "test-brand-id"
        compile_run_id = "failed-compile-run-id"
        response = client.get(
            f"/api/brands/{brand_id}/brandbrain/compile/{compile_run_id}/status"
        )

        data = response.json()
        if data["status"] == "FAILED":
            assert "error" in data
            assert "evidence_status" in data

    def test_running_status_includes_progress(self, client):
        """When status is RUNNING, response should include progress."""
        brand_id = "test-brand-id"
        compile_run_id = "running-compile-run-id"
        response = client.get(
            f"/api/brands/{brand_id}/brandbrain/compile/{compile_run_id}/status"
        )

        data = response.json()
        if data["status"] == "RUNNING":
            assert "progress" in data
            progress = data["progress"]
            assert "stage" in progress
            assert "sources_completed" in progress
            assert "sources_total" in progress


# =============================================================================
# READ-PATH BOUNDARY TESTS
# =============================================================================


@pytest.mark.contract
@pytest.mark.skip(reason="Endpoint not implemented until PR-7")
class TestReadPathBoundary:
    """
    Tests verifying read-path endpoints don't trigger work.

    Per spec Section 1.1 (Read-Path vs Work-Path Boundary):
    "No read-path endpoint may trigger ingestion, normalization, or LLM work."
    "Violations of this rule constitute a bug."
    """

    def test_get_latest_does_not_trigger_compile(self, client):
        """GET /latest should not trigger any compile work."""
        # TODO PR-7: Mock compile service and verify it's never called
        brand_id = "test-brand-id"
        response = client.get(f"/api/brands/{brand_id}/brandbrain/latest")

        # Even for brands without snapshots, should return 404, not trigger compile
        assert response.status_code in (200, 404)
        # Verify no compile was triggered (will need mocking)

    def test_get_history_does_not_trigger_compile(self, client):
        """GET /history should not trigger any compile work."""
        brand_id = "test-brand-id"
        response = client.get(f"/api/brands/{brand_id}/brandbrain/history")

        assert response.status_code in (200, 404)

    def test_get_status_does_not_trigger_work(self, client):
        """GET /status should not trigger any async work."""
        brand_id = "test-brand-id"
        compile_run_id = "test-compile-run-id"
        response = client.get(
            f"/api/brands/{brand_id}/brandbrain/compile/{compile_run_id}/status"
        )

        # Should be a pure DB read
        assert response.status_code in (200, 404)


# =============================================================================
# SNAPSHOT JSON SHAPE TESTS
# =============================================================================


@pytest.mark.contract
@pytest.mark.skip(reason="Endpoint not implemented until PR-7")
class TestSnapshotJsonShape:
    """
    Tests verifying BrandBrainSnapshot JSON structure.

    Per spec Section 8.2 (Top-Level Shape):
    - positioning, voice, pillars, constraints, platform_profiles, examples, meta
    """

    def test_snapshot_has_top_level_sections(self, client):
        """snapshot_json should have all top-level sections from spec."""
        brand_id = "test-brand-id"
        response = client.get(f"/api/brands/{brand_id}/brandbrain/latest")

        data = response.json()
        snapshot = data.get("snapshot_json", {})

        required_sections = {
            "positioning",
            "voice",
            "pillars",
            "constraints",
            "platform_profiles",
            "examples",
            "meta",
        }
        assert_has_required_fields(
            snapshot,
            required_sections,
            context="snapshot_json: ",
        )

    def test_positioning_section_has_field_nodes(self, client):
        """positioning section should have FieldNode structure."""
        brand_id = "test-brand-id"
        response = client.get(f"/api/brands/{brand_id}/brandbrain/latest")

        data = response.json()
        positioning = data.get("snapshot_json", {}).get("positioning", {})

        # Each field should be a FieldNode with value, confidence, sources, locked
        expected_fields = ["what_we_do", "who_for", "differentiators", "proof_types"]
        for field_name in expected_fields:
            if field_name in positioning:
                field_node = positioning[field_name]
                assert "value" in field_node, f"{field_name} missing 'value'"
                assert "confidence" in field_node, f"{field_name} missing 'confidence'"

    def test_meta_section_has_required_fields(self, client):
        """meta section should have compiled_at, missing_inputs, etc."""
        brand_id = "test-brand-id"
        response = client.get(f"/api/brands/{brand_id}/brandbrain/latest")

        data = response.json()
        meta = data.get("snapshot_json", {}).get("meta", {})

        # Per spec Section 8.2
        assert "compiled_at" in meta
        assert "missing_inputs" in meta
        assert "confidence_summary" in meta
