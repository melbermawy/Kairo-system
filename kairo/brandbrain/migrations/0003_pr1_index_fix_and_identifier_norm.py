"""
PR-1: Dual index strategy for published_at ordering.

Per review feedback, we need BOTH indexes to cover different query patterns:
- Pattern B: Filter by (brand_id, platform, content_type), order by published_at
  → idx_nei_brand_published_ct
- Pattern C: Filter by (brand_id, platform) only, order by published_at
  → idx_nei_brand_published (original name, but now platform-only)

This migration:
1. Drops the old idx_nei_brand_published (was platform+content_type from 0002)
2. Creates idx_nei_brand_published for Pattern C (platform-only)
3. Creates idx_nei_brand_published_ct for Pattern B (with content_type)

Note: Non-concurrent index creation is OK for now (pre-prod). Revisit before prod
if table has significant data - may need CREATE INDEX CONCURRENTLY with atomic=False.
"""

from django.db import migrations


class Migration(migrations.Migration):
    """Add dual index strategy for published_at ordering."""

    dependencies = [
        ("brandbrain", "0002_pr1_partial_constraints_indexes"),
    ]

    operations = [
        # Drop the old index (from 0002) to recreate with clear naming
        migrations.RunSQL(
            sql="DROP INDEX IF EXISTS idx_nei_brand_published;",
            reverse_sql="SELECT 1;",  # No-op for reverse
        ),
        # Pattern C: Filter by (brand_id, platform), order by published_at
        # Used when selecting across all content_types for a platform
        migrations.RunSQL(
            sql="""
                CREATE INDEX idx_nei_brand_published
                ON brandbrain_normalized_evidence_item (brand_id, platform, published_at DESC NULLS LAST);
            """,
            reverse_sql="DROP INDEX IF EXISTS idx_nei_brand_published;",
        ),
        # Pattern B: Filter by (brand_id, platform, content_type), order by published_at
        # Used when selecting specific content_type within a platform
        migrations.RunSQL(
            sql="""
                CREATE INDEX idx_nei_brand_published_ct
                ON brandbrain_normalized_evidence_item (brand_id, platform, content_type, published_at DESC NULLS LAST);
            """,
            reverse_sql="DROP INDEX IF EXISTS idx_nei_brand_published_ct;",
        ),
    ]
