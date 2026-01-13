"""
PR-1: Add partial unique constraints and partial indexes.

Per spec v2.4 Section 1.2 and 2.3:
- NormalizedEvidenceItem partial unique constraints for dedupe
- ApifyRun partial index for TTL freshness check
- NormalizedEvidenceItem recency index for bundling

These require raw SQL as Django ORM doesn't support partial constraints natively.

PR-5: Made PostgreSQL-specific operations skip on SQLite for test compatibility.
"""

from django.db import connection, migrations


def is_postgresql():
    """Check if we're running on PostgreSQL."""
    return connection.vendor == "postgresql"


def run_if_postgresql(sql):
    """Return a function that runs SQL only on PostgreSQL."""
    def forward(apps, schema_editor):
        if is_postgresql():
            schema_editor.execute(sql)
    return forward


def reverse_if_postgresql(sql):
    """Return a function that runs reverse SQL only on PostgreSQL."""
    def reverse(apps, schema_editor):
        if is_postgresql():
            schema_editor.execute(sql)
    return reverse


class Migration(migrations.Migration):
    """Add partial unique constraints and indexes per spec."""

    dependencies = [
        ("brandbrain", "0001_pr1_initial_models"),
        ("apify", "0002_pr1_brandbrain_fields"),
    ]

    operations = [
        # =============================================================================
        # NormalizedEvidenceItem Partial Unique Constraints
        # Per spec Section 1.2 and 2.3
        # =============================================================================

        # UNIQUE(brand_id, platform, content_type, external_id) WHERE external_id IS NOT NULL
        migrations.RunPython(
            run_if_postgresql("""
                CREATE UNIQUE INDEX uniq_nei_external_id
                ON brandbrain_normalized_evidence_item (brand_id, platform, content_type, external_id)
                WHERE external_id IS NOT NULL;
            """),
            reverse_if_postgresql("DROP INDEX IF EXISTS uniq_nei_external_id;"),
        ),

        # UNIQUE(brand_id, platform, content_type, canonical_url) WHERE platform='web'
        migrations.RunPython(
            run_if_postgresql("""
                CREATE UNIQUE INDEX uniq_nei_web_canonical_url
                ON brandbrain_normalized_evidence_item (brand_id, platform, content_type, canonical_url)
                WHERE platform = 'web';
            """),
            reverse_if_postgresql("DROP INDEX IF EXISTS uniq_nei_web_canonical_url;"),
        ),

        # =============================================================================
        # ApifyRun Partial Index for TTL Check
        # Per spec Section 1.2: Latest successful ApifyRun per source
        # =============================================================================

        # Index for: SELECT ... FROM apify_run
        #            WHERE source_connection_id=? AND status='succeeded'
        #            ORDER BY created_at DESC LIMIT 1
        migrations.RunPython(
            run_if_postgresql("""
                CREATE INDEX idx_apifyrun_source_success
                ON apify_run (source_connection_id, created_at DESC)
                WHERE status = 'succeeded';
            """),
            reverse_if_postgresql("DROP INDEX IF EXISTS idx_apifyrun_source_success;"),
        ),

        # =============================================================================
        # NormalizedEvidenceItem Recency Index for Bundling
        # Per spec Section 1.2: published_at-based sorting for bundle selection
        # =============================================================================

        migrations.RunPython(
            run_if_postgresql("""
                CREATE INDEX idx_nei_brand_published
                ON brandbrain_normalized_evidence_item (brand_id, platform, published_at DESC NULLS LAST);
            """),
            reverse_if_postgresql("DROP INDEX IF EXISTS idx_nei_brand_published;"),
        ),
    ]
