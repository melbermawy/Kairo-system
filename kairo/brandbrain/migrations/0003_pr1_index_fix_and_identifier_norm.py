"""
PR-1: Fix idx_nei_brand_published to include content_type.

Per review feedback:
- Current: (brand_id, platform, published_at DESC NULLS LAST)
- Desired: (brand_id, platform, content_type, published_at DESC NULLS LAST)
"""

from django.db import migrations


class Migration(migrations.Migration):
    """Fix idx_nei_brand_published index to include content_type."""

    dependencies = [
        ("brandbrain", "0002_pr1_partial_constraints_indexes"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                DROP INDEX IF EXISTS idx_nei_brand_published;
                CREATE INDEX idx_nei_brand_published
                ON brandbrain_normalized_evidence_item (brand_id, platform, content_type, published_at DESC NULLS LAST);
            """,
            reverse_sql="""
                DROP INDEX IF EXISTS idx_nei_brand_published;
                CREATE INDEX idx_nei_brand_published
                ON brandbrain_normalized_evidence_item (brand_id, platform, published_at DESC NULLS LAST);
            """,
        ),
    ]
