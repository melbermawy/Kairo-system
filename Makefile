# Kairo Makefile
#
# Common development tasks for the Kairo project.

.PHONY: help install test test-unit test-db test-brandbrain test-contract test-ci lint clean

# Default target
help:
	@echo "Kairo Development Commands"
	@echo ""
	@echo "Setup:"
	@echo "  make install        Install dependencies (including dev)"
	@echo ""
	@echo "Testing:"
	@echo "  make test           Run full test suite (all markers)"
	@echo "  make test-unit      Run fast unit tests only (<=5s, no DB)"
	@echo "  make test-db        Run DB tests (requires migrations)"
	@echo "  make test-brandbrain Run BrandBrain unit tests"
	@echo "  make test-contract  Run contract tests (currently skipped)"
	@echo "  make test-ci        CI PR gate: unit tests only (<=5s)"
	@echo ""
	@echo "Code Quality:"
	@echo "  make lint           Run linters (if configured)"
	@echo ""
	@echo "Maintenance:"
	@echo "  make clean          Remove cache files"

# =============================================================================
# SETUP
# =============================================================================

install:
	pip install -e ".[dev]"

# =============================================================================
# TESTING
#
# Markers:
#   unit      - Fast unit tests (NO Django DB, NO migrations, pure Python)
#   db        - Tests requiring Django DB (runs migrations, slower)
#   contract  - Contract tests (may be skipped until endpoints exist)
#   integration - Integration tests (external services, full stack)
#
# CI runs test-unit by default for fast feedback (<=5s).
# DB tests run separately and are slower due to migrations.
# =============================================================================

# Run full test suite (all tests, including skipped contract tests)
test:
	pytest tests/ -v

# Run fast unit tests only - CI default, target <=5s
# NO Django DB, NO migrations, pure Python only
test-unit:
	pytest tests/ -m "unit" -q

# Run DB tests (requires Django, runs migrations)
# Use --reuse-db for faster subsequent runs
test-db:
	pytest tests/ -m "db" -q --reuse-db

# Run BrandBrain unit tests specifically (subset of test-unit)
test-brandbrain:
	pytest tests/brandbrain/ tests/helpers/test_apify_samples.py -m "unit" -q

# Run contract tests (currently skipped, will pass when PR-7 lands)
test-contract:
	pytest tests/ -m "contract" -v

# CI command: fast unit tests only (PR gate)
# Must complete in <=5s, no DB access
test-ci:
	pytest tests/ -m "unit" -q --tb=short

# =============================================================================
# CODE QUALITY
# =============================================================================

lint:
	@echo "Linting not yet configured. Add ruff/black/mypy as needed."

# =============================================================================
# MAINTENANCE
# =============================================================================

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
