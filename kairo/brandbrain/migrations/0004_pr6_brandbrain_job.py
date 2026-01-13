"""
PR-6: Add BrandBrainJob model for durable job queue.

This model provides a DB-backed job queue for compile jobs,
replacing the ThreadPoolExecutor from PR-5 with durable persistence.

Features:
- Job leasing via status + locked_at + locked_by
- Retry with exponential backoff via available_at
- max_attempts limit with last_error tracking
"""

from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    """Add BrandBrainJob model for durable job queue."""

    dependencies = [
        ("brandbrain", "0003_pr1_index_fix_and_identifier_norm"),
        ("core", "0001_initial"),  # For Brand foreign key
    ]

    operations = [
        migrations.CreateModel(
            name="BrandBrainJob",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "job_type",
                    models.CharField(
                        choices=[("compile", "Compile BrandBrain")],
                        default="compile",
                        max_length=50,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("running", "Running"),
                            ("succeeded", "Succeeded"),
                            ("failed", "Failed"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("attempts", models.PositiveIntegerField(default=0)),
                ("max_attempts", models.PositiveIntegerField(default=3)),
                ("last_error", models.TextField(blank=True, null=True)),
                ("locked_at", models.DateTimeField(blank=True, null=True)),
                ("locked_by", models.CharField(blank=True, max_length=255, null=True)),
                ("available_at", models.DateTimeField(auto_now_add=True)),
                ("params_json", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                (
                    "brand",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="brandbrain_jobs",
                        to="core.brand",
                    ),
                ),
                (
                    "compile_run",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="jobs",
                        to="brandbrain.brandbraincompilerun",
                    ),
                ),
            ],
            options={
                "db_table": "brandbrain_job",
            },
        ),
        migrations.AddIndex(
            model_name="brandbrainjob",
            index=models.Index(
                fields=["status", "available_at"],
                name="idx_job_status_available",
            ),
        ),
        migrations.AddIndex(
            model_name="brandbrainjob",
            index=models.Index(
                fields=["brand", "-created_at"],
                name="idx_job_brand_created",
            ),
        ),
    ]
