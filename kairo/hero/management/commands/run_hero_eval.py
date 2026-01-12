"""
Management command to run the hero loop eval.

PR-10: Offline Eval Harness + Fixtures.

Usage:
    python manage.py run_hero_eval --brand-slug <slug> [--llm-enabled] [--max-opportunities <n>]

This command runs the F1 (Today board) and F2 (Package + Variants) flows
against fixture data and outputs metrics + artifacts.

Per docs/eval/evalHarness.md and PR-map-and-standards §PR-10:
- Accepts --brand-slug (required)
- Optional --llm-enabled to use real LLM (default: disabled for CI)
- Optional --max-opportunities to limit F2 processing
- Outputs JSON + Markdown to docs/eval/hero_loop/

Failure Behavior:
- Validation errors (missing fixture, invalid brand slug) raise CommandError
- Eval errors are captured in EvalResult.errors and reported
- Non-zero exit code on error status
"""

import os
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from kairo.hero.eval.f1_f2_hero_loop import (
    EvalResult,
    run_hero_loop_eval,
    _get_brand_fixture,
    _load_brands_fixture,
)


class Command(BaseCommand):
    """Run the hero loop eval for a brand."""

    help = "Run the hero loop eval for a brand (F1 + F2 flows)"

    def add_arguments(self, parser):
        # 10b: --brand-slug is not required when --list-brands is used
        parser.add_argument(
            "--brand-slug",
            type=str,
            required=False,  # Will validate manually
            help="Slug of the brand to evaluate (from fixtures)",
        )
        parser.add_argument(
            "--llm-enabled",
            action="store_true",
            default=False,
            help="Enable real LLM calls (default: disabled for CI)",
        )
        parser.add_argument(
            "--max-opportunities",
            type=int,
            default=3,
            help="Max opportunities to process for F2 (default: 3)",
        )
        parser.add_argument(
            "--output-dir",
            type=str,
            default=None,
            help="Output directory for artifacts (default: docs/eval/hero_loop/)",
        )
        parser.add_argument(
            "--list-brands",
            action="store_true",
            default=False,
            help="List available brand slugs from fixtures",
        )

    def handle(self, *args, **options):
        # Handle --list-brands (doesn't require --brand-slug)
        if options["list_brands"]:
            self._list_brands()
            return

        # 10b: Validate --brand-slug is provided if not listing brands
        brand_slug = options.get("brand_slug")
        if not brand_slug:
            raise CommandError(
                "--brand-slug is required when not using --list-brands\n"
                "Use --list-brands to see available brand slugs"
            )
        llm_enabled = options["llm_enabled"]
        max_opportunities = options["max_opportunities"]
        output_dir_str = options["output_dir"]

        # Validate brand fixture exists
        brand_fixture = _get_brand_fixture(brand_slug)
        if not brand_fixture:
            available = self._get_available_slugs()
            raise CommandError(
                f"Brand fixture not found: {brand_slug}\n"
                f"Available brands: {', '.join(available)}"
            )

        # Validate max_opportunities
        if max_opportunities <= 0:
            raise CommandError(f"--max-opportunities must be positive, got: {max_opportunities}")

        # Parse output directory
        output_dir = Path(output_dir_str) if output_dir_str else None

        self.stdout.write(f"Running hero loop eval for brand: {brand_slug}")
        self.stdout.write(f"  LLM enabled: {llm_enabled}")
        self.stdout.write(f"  Max opportunities for F2: {max_opportunities}")

        # Run eval
        result = run_hero_loop_eval(
            brand_slug=brand_slug,
            llm_disabled=not llm_enabled,
            max_opportunities=max_opportunities,
            output_dir=output_dir,
        )

        # Report results
        self._report_results(result)

        # 10b: Exit with error if eval failed or had stage failures
        if result.status in ("error", "failed"):
            raise CommandError(f"Eval failed: {'; '.join(result.errors)}")

    def _list_brands(self):
        """List available brand slugs from fixtures."""
        brands_data = _load_brands_fixture()
        brands = brands_data.get("brands", [])

        if not brands:
            self.stdout.write(self.style.WARNING("No brands found in fixtures"))
            return

        self.stdout.write("Available brand slugs:")
        for brand in brands:
            slug = brand.get("brand_slug", "")
            name = brand.get("brand_name", "")
            eval_id = brand.get("eval_brand_id", "")
            self.stdout.write(f"  - {slug} ({name}) [eval_id: {eval_id}]")

    def _get_available_slugs(self) -> list[str]:
        """Get list of available brand slugs."""
        brands_data = _load_brands_fixture()
        return [b.get("brand_slug", "") for b in brands_data.get("brands", [])]

    def _report_results(self, result: EvalResult):
        """Report eval results to stdout."""
        self.stdout.write("")
        self.stdout.write("=" * 60)
        self.stdout.write(f"EVAL RESULTS: {result.brand_slug}")
        self.stdout.write("=" * 60)
        self.stdout.write(f"Run ID: {result.run_id}")
        self.stdout.write(f"Status: {result.status}")
        self.stdout.write(f"LLM Disabled: {result.llm_disabled}")
        self.stdout.write("")

        # Metrics summary
        self.stdout.write("METRICS:")
        for key, value in result.metrics.items():
            if isinstance(value, float):
                self.stdout.write(f"  {key}: {value:.2f}")
            else:
                self.stdout.write(f"  {key}: {value}")

        self.stdout.write("")

        # Per-case summary
        for case in result.cases:
            self.stdout.write(f"CASE: {case.eval_brand_id}")

            # 10b: Show stage status prominently
            stage = case.stage_status
            f1_emoji = {"ok": "✅", "degraded": "⚠️", "failed": "❌"}.get(stage.f1_status, "?")
            f2_emoji = {"ok": "✅", "degraded": "⚠️", "failed": "❌"}.get(stage.f2_status, "?")
            self.stdout.write(f"  Stage Status:")
            self.stdout.write(f"    F1 (Opportunities): {f1_emoji} {stage.f1_status}")
            self.stdout.write(f"    F2 (Packages/Variants): {f2_emoji} {stage.f2_status}")
            if stage.failure_reason:
                self.stdout.write(f"    Failure reason: {stage.failure_reason}")
            self.stdout.write(f"    Structurally valid: {stage.is_structurally_valid()}")

            self.stdout.write(f"  Opportunities: {case.opportunity_count} ({case.valid_opportunity_count} valid)")
            self.stdout.write(f"  Packages: {case.package_count}")
            self.stdout.write(f"  Variants: {case.variant_count}")
            self.stdout.write(f"  Taboo violations: {case.taboo_violations}")
            self.stdout.write(f"  Golden matches: {case.golden_match_count}")

            if case.warnings:
                self.stdout.write("  Warnings:")
                for warning in case.warnings[:5]:  # Show first 5
                    self.stdout.write(f"    - {warning[:80]}")
                if len(case.warnings) > 5:
                    self.stdout.write(f"    ... and {len(case.warnings) - 5} more")

        self.stdout.write("")

        # Errors
        if result.errors:
            self.stdout.write(self.style.ERROR("ERRORS:"))
            for error in result.errors:
                self.stdout.write(f"  - {error}")
        else:
            self.stdout.write(self.style.SUCCESS("No errors."))

        self.stdout.write("")
        self.stdout.write("=" * 60)
