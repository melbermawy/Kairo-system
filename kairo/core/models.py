"""
Kairo canonical domain models.

PR-1: Canonical schema + migrations.
PR-1b: Tenant model + Brand-scoped semantics.

Per docs/technical/02-canonical-objects.md and docs/prd/kairo-v1-prd.md §3.1.

Scoping hierarchy:
- Tenant → has many Brands
- Brand → has many snapshots, personas, pillars, patterns, opportunities, packages, variants, events
- Child models are scoped via Brand FK, not direct tenant_id

NOTE: LearningSummary (§3.1.10) is NOT persisted - it is an in-memory DTO
reconstructed on demand by the LearningEngine. Do not create a table for it.
"""

import uuid

from django.db import models
from django.utils import timezone

from .enums import (
    Channel,
    CreatedVia,
    DecisionType,
    ExecutionEventType,
    ExecutionSource,
    LearningSignalType,
    OpportunityType,
    PackageStatus,
    PatternCategory,
    PatternStatus,
    VariantStatus,
)


# =============================================================================
# ABSTRACT BASE CLASSES
# =============================================================================


class TimestampedModel(models.Model):
    """
    Abstract base class with created_at and updated_at timestamps.

    Per PR-map-and-standards: "Use timezone-aware datetime; auto_now, auto_now_add."
    """

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# =============================================================================
# TENANT
# =============================================================================


class Tenant(TimestampedModel):
    """
    Top-level tenant / organization.

    All brand-scoped data flows through Brand → Tenant.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)

    class Meta:
        db_table = "tenant"
        verbose_name = "Tenant"
        verbose_name_plural = "Tenants"

    def __str__(self):
        return self.name


# =============================================================================
# BRAND & BRAND CONTEXT
# =============================================================================


class Brand(TimestampedModel):
    """
    Brand entity - the central identity object.

    Per §3.1.1: "id, tenant_id, name, slug, primary_channel?, channels[],
    positioning, tone_tags[], taboos[], metadata{}, created_at, updated_at, deleted_at?"

    Scoped to Tenant via FK. All child models (personas, pillars, etc.) are
    scoped via Brand, not directly by tenant_id.

    Phase 1: Added owner field to link brands to users for access control.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.PROTECT,
        related_name="brands",
    )
    # Phase 1: User who owns this brand (for access control)
    # Using string reference to avoid circular import with kairo.users
    owner = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        related_name="owned_brands",
        null=True,
        blank=True,
        help_text="User who owns this brand",
    )
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=100)
    primary_channel = models.CharField(
        max_length=50,
        choices=Channel.choices,
        blank=True,
        null=True,
    )
    channels = models.JSONField(default=list, blank=True)
    positioning = models.TextField(blank=True)
    tone_tags = models.JSONField(default=list, blank=True)
    taboos = models.JSONField(default=list, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "brand"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "slug"],
                name="uniq_tenant_brand_slug",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "created_at"]),
        ]

    def __str__(self):
        return self.name

    @property
    def is_deleted(self):
        return self.deleted_at is not None


class BrandSnapshot(TimestampedModel):
    """
    Point-in-time snapshot of brand context for LLM prompts.

    Per §3.1.2: "brand_id, positioning_summary, tone_descriptors[],
    taboos[], pillars[], personas[]"

    Immutable once created - represents frozen state for reproducibility.
    snapshot_at is the explicit "as of" timestamp (not overloaded from created_at).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    brand = models.ForeignKey(
        Brand,
        on_delete=models.PROTECT,
        related_name="snapshots",
    )
    snapshot_at = models.DateTimeField(
        help_text="Point in time this snapshot represents"
    )
    positioning_summary = models.TextField(blank=True)
    tone_descriptors = models.JSONField(default=list)
    taboos = models.JSONField(default=list)
    pillars = models.JSONField(default=list)
    personas = models.JSONField(default=list)

    class Meta:
        db_table = "brand_snapshot"
        indexes = [
            models.Index(fields=["brand", "snapshot_at"]),
            models.Index(fields=["brand", "created_at"]),
        ]

    def __str__(self):
        return f"Snapshot for {self.brand.name} @ {self.snapshot_at}"


class Persona(TimestampedModel):
    """
    Target audience persona for a brand.

    Per §3.1.3: "id, tenant_id, brand_id, name, role?, summary,
    priorities[], pains[], success_metrics[], channel_biases{}"

    Scoped via Brand FK (tenant implied via brand.tenant).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    brand = models.ForeignKey(
        Brand,
        on_delete=models.PROTECT,
        related_name="personas",
    )
    name = models.CharField(max_length=255)
    role = models.CharField(max_length=255, blank=True)
    summary = models.TextField(blank=True)
    priorities = models.JSONField(default=list, blank=True)
    pains = models.JSONField(default=list, blank=True)
    success_metrics = models.JSONField(default=list, blank=True)
    channel_biases = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "persona"
        constraints = [
            models.UniqueConstraint(
                fields=["brand", "name"],
                name="unique_persona_brand_name",
            ),
        ]
        indexes = [
            models.Index(fields=["brand", "created_at"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.brand.name})"


class ContentPillar(TimestampedModel):
    """
    Content pillar / topic category for a brand.

    Per §3.1.4: "id, tenant_id, brand_id, name, category?, description,
    priority_rank, is_active"

    Scoped via Brand FK (tenant implied via brand.tenant).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    brand = models.ForeignKey(
        Brand,
        on_delete=models.PROTECT,
        related_name="pillars",
    )
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    priority_rank = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "content_pillar"
        constraints = [
            models.UniqueConstraint(
                fields=["brand", "name"],
                name="unique_pillar_brand_name",
            ),
        ]
        indexes = [
            models.Index(fields=["brand", "is_active"]),
            models.Index(fields=["brand", "created_at"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.brand.name})"


# =============================================================================
# PATTERNS
# =============================================================================


class PatternTemplate(TimestampedModel):
    """
    Reusable content pattern/template.

    Per §3.1.5: "id, tenant_id, brand_id?, name, category, status,
    beats[], supported_channels[], example_snippet?, performance_hint?,
    usage_count, last_used_at?, avg_engagement_score?, metadata{}"

    brand is nullable - patterns can be global (tenant-wide) or brand-specific.
    For global patterns, access tenant via the service layer context.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    brand = models.ForeignKey(
        Brand,
        on_delete=models.PROTECT,
        related_name="patterns",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255)
    category = models.CharField(
        max_length=50,
        choices=PatternCategory.choices,
        default=PatternCategory.EVERGREEN,
    )
    status = models.CharField(
        max_length=50,
        choices=PatternStatus.choices,
        default=PatternStatus.ACTIVE,
    )
    beats = models.JSONField(default=list)
    supported_channels = models.JSONField(default=list)
    example_snippet = models.TextField(blank=True)
    performance_hint = models.TextField(blank=True)
    usage_count = models.PositiveIntegerField(default=0)
    last_used_at = models.DateTimeField(null=True, blank=True)
    avg_engagement_score = models.FloatField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "pattern_template"
        indexes = [
            models.Index(fields=["brand", "status"]),
            models.Index(fields=["brand", "category"]),
            models.Index(fields=["brand", "created_at"]),
        ]

    def __str__(self):
        brand_name = self.brand.name if self.brand else "Global"
        return f"{self.name} ({brand_name})"


# =============================================================================
# OPPORTUNITIES & PACKAGES
# =============================================================================


class Opportunity(TimestampedModel):
    """
    Content opportunity (trend, evergreen idea, etc.).

    Per §3.1.6: "id, tenant_id, brand_id, type, score?, score_explanation?,
    title, angle?, source?, source_url?, persona_id?, pillar_id?,
    primary_channel?, suggested_channels[], is_pinned, is_snoozed,
    snoozed_until?, created_by_user_id?, created_via, last_touched_at?, metadata{}"

    Scoped via Brand FK (tenant implied via brand.tenant).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    brand = models.ForeignKey(
        Brand,
        on_delete=models.PROTECT,
        related_name="opportunities",
    )
    type = models.CharField(
        max_length=50,
        choices=OpportunityType.choices,
    )
    score = models.FloatField(null=True, blank=True)
    score_explanation = models.TextField(blank=True)
    title = models.CharField(max_length=500)
    angle = models.TextField(blank=True)
    source = models.CharField(max_length=255, blank=True)
    source_url = models.URLField(max_length=2000, blank=True)
    persona = models.ForeignKey(
        Persona,
        on_delete=models.SET_NULL,
        related_name="opportunities",
        null=True,
        blank=True,
    )
    pillar = models.ForeignKey(
        ContentPillar,
        on_delete=models.SET_NULL,
        related_name="opportunities",
        null=True,
        blank=True,
    )
    primary_channel = models.CharField(
        max_length=50,
        choices=Channel.choices,
        blank=True,
    )
    suggested_channels = models.JSONField(default=list, blank=True)
    is_pinned = models.BooleanField(default=False)
    is_snoozed = models.BooleanField(default=False)
    snoozed_until = models.DateTimeField(null=True, blank=True)
    created_by_user_id = models.UUIDField(null=True, blank=True)
    created_via = models.CharField(
        max_length=50,
        choices=CreatedVia.choices,
        default=CreatedVia.AI_SUGGESTED,
    )
    last_touched_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "opportunity"
        verbose_name_plural = "opportunities"
        indexes = [
            models.Index(fields=["brand", "created_at"]),
            models.Index(fields=["brand", "is_pinned", "is_snoozed"]),
            models.Index(fields=["brand", "type"]),
        ]

    def __str__(self):
        return self.title


class ContentPackage(TimestampedModel):
    """
    Content package grouping variants for multi-channel publication.

    Per §3.1.7: "id, tenant_id, brand_id, title, status, origin_opportunity_id?,
    persona_id?, pillar_id?, channels[], planned_publish_start?, planned_publish_end?,
    owner_user_id?, notes?, created_via, metrics_snapshot{}"

    Scoped via Brand FK (tenant implied via brand.tenant).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    brand = models.ForeignKey(
        Brand,
        on_delete=models.PROTECT,
        related_name="packages",
    )
    title = models.CharField(max_length=500)
    status = models.CharField(
        max_length=50,
        choices=PackageStatus.choices,
        default=PackageStatus.DRAFT,
    )
    origin_opportunity = models.ForeignKey(
        Opportunity,
        on_delete=models.SET_NULL,
        related_name="packages",
        null=True,
        blank=True,
    )
    persona = models.ForeignKey(
        Persona,
        on_delete=models.SET_NULL,
        related_name="packages",
        null=True,
        blank=True,
    )
    pillar = models.ForeignKey(
        ContentPillar,
        on_delete=models.SET_NULL,
        related_name="packages",
        null=True,
        blank=True,
    )
    channels = models.JSONField(default=list, blank=True)
    planned_publish_start = models.DateTimeField(null=True, blank=True)
    planned_publish_end = models.DateTimeField(null=True, blank=True)
    owner_user_id = models.UUIDField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_via = models.CharField(
        max_length=50,
        choices=CreatedVia.choices,
        default=CreatedVia.MANUAL,
    )
    metrics_snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "content_package"
        indexes = [
            models.Index(fields=["brand", "status"]),
            models.Index(fields=["brand", "created_at"]),
        ]

    def __str__(self):
        return self.title


class Variant(TimestampedModel):
    """
    Channel-specific content variant within a package.

    Per §3.1.8: "id, tenant_id, brand_id, package_id, channel, status,
    pattern_template_id?, raw_prompt_context{}, draft_text, edited_text?,
    approved_text?, generated_by_model?, proposed_at, scheduled_publish_at?,
    published_at?, last_evaluated_at?, eval_score?, eval_notes?, metadata{}"

    Scoped via Brand FK (tenant implied via brand.tenant).
    Also has package FK for direct access to parent package.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    brand = models.ForeignKey(
        Brand,
        on_delete=models.PROTECT,
        related_name="variants",
    )
    package = models.ForeignKey(
        ContentPackage,
        on_delete=models.CASCADE,
        related_name="variants",
    )
    channel = models.CharField(
        max_length=50,
        choices=Channel.choices,
    )
    status = models.CharField(
        max_length=50,
        choices=VariantStatus.choices,
        default=VariantStatus.DRAFT,
    )
    pattern_template = models.ForeignKey(
        PatternTemplate,
        on_delete=models.SET_NULL,
        related_name="variants",
        null=True,
        blank=True,
    )
    raw_prompt_context = models.JSONField(default=dict, blank=True)
    draft_text = models.TextField(blank=True)
    edited_text = models.TextField(blank=True)
    approved_text = models.TextField(blank=True)
    generated_by_model = models.CharField(max_length=100, blank=True)
    proposed_at = models.DateTimeField(default=timezone.now)
    scheduled_publish_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    last_evaluated_at = models.DateTimeField(null=True, blank=True)
    eval_score = models.FloatField(null=True, blank=True)
    eval_notes = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "variant"
        indexes = [
            models.Index(fields=["package", "channel"]),
            models.Index(fields=["package", "created_at"]),
            models.Index(fields=["brand", "status"]),
            models.Index(fields=["brand", "channel", "status"]),
            models.Index(fields=["brand", "created_at"]),
        ]

    def __str__(self):
        return f"{self.package.title} - {self.channel}"


# =============================================================================
# EXECUTION & LEARNING
# =============================================================================


class ExecutionEvent(TimestampedModel):
    """
    Platform engagement/execution event for a published variant.

    Per §3.1.9: "id, tenant_id, brand_id, variant_id, channel, event_type,
    event_value?, count?, source, occurred_at, received_at, metadata{}"

    Scoped via Brand FK (tenant implied via brand.tenant).
    Also tracks user decisions via decision_type (nullable).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    brand = models.ForeignKey(
        Brand,
        on_delete=models.PROTECT,
        related_name="execution_events",
    )
    variant = models.ForeignKey(
        Variant,
        on_delete=models.CASCADE,
        related_name="execution_events",
    )
    channel = models.CharField(
        max_length=50,
        choices=Channel.choices,
    )
    event_type = models.CharField(
        max_length=50,
        choices=ExecutionEventType.choices,
    )
    decision_type = models.CharField(
        max_length=50,
        choices=DecisionType.choices,
        null=True,
        blank=True,
        help_text="User decision type, if this event represents a user action",
    )
    event_value = models.TextField(blank=True)
    count = models.PositiveIntegerField(default=1)
    source = models.CharField(
        max_length=50,
        choices=ExecutionSource.choices,
    )
    occurred_at = models.DateTimeField()
    received_at = models.DateTimeField(default=timezone.now)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "execution_event"
        indexes = [
            models.Index(fields=["variant", "event_type"]),
            models.Index(fields=["brand", "occurred_at"]),
            models.Index(fields=["brand", "created_at"]),
            models.Index(fields=["channel", "event_type", "occurred_at"]),
        ]

    def __str__(self):
        return f"{self.event_type} on {self.variant}"


class LearningEvent(TimestampedModel):
    """
    Learning signal event for the feedback loop.

    Per §3.1.9 (Learning): "id, tenant_id, brand_id, signal_type,
    pattern_id?, opportunity_id?, variant_id?, payload{},
    derived_from[], effective_at"

    These events feed the LearningEngine to improve future suggestions.
    Scoped via Brand FK (tenant implied via brand.tenant).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    brand = models.ForeignKey(
        Brand,
        on_delete=models.PROTECT,
        related_name="learning_events",
    )
    signal_type = models.CharField(
        max_length=50,
        choices=LearningSignalType.choices,
    )
    pattern = models.ForeignKey(
        PatternTemplate,
        on_delete=models.SET_NULL,
        related_name="learning_events",
        null=True,
        blank=True,
    )
    opportunity = models.ForeignKey(
        Opportunity,
        on_delete=models.SET_NULL,
        related_name="learning_events",
        null=True,
        blank=True,
    )
    variant = models.ForeignKey(
        Variant,
        on_delete=models.SET_NULL,
        related_name="learning_events",
        null=True,
        blank=True,
    )
    payload = models.JSONField(default=dict)
    derived_from = models.JSONField(default=list, blank=True)
    effective_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "learning_event"
        indexes = [
            models.Index(fields=["brand", "signal_type"]),
            models.Index(fields=["brand", "effective_at"]),
            models.Index(fields=["brand", "created_at"]),
        ]

    def __str__(self):
        return f"{self.signal_type} for {self.brand.name}"


# =============================================================================
# NOTE: LearningSummary is NOT a persisted model
# =============================================================================
# Per §3.1.10 in kairo-v1-prd.md:
# "LearningSummary is an in-memory DTO, reconstructed on demand by the
# LearningEngine. Do not create a table for it."
#
# It will be defined as a dataclass or Pydantic model in the engines layer.
# =============================================================================
