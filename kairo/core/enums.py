"""
Kairo domain enums.

PR-1: Canonical schema + migrations.
PR-1b: Added DecisionType for user interaction tracking.

All enums are defined as Django TextChoices for database storage as lowercase strings.
Per PR-map-and-standards: "TextChoices stored as lowercase snake_case strings".
"""

from django.db import models


class Channel(models.TextChoices):
    """Supported content distribution channels."""
    LINKEDIN = "linkedin", "LinkedIn"
    X = "x", "X (Twitter)"
    YOUTUBE = "youtube", "YouTube"
    INSTAGRAM = "instagram", "Instagram"
    TIKTOK = "tiktok", "TikTok"
    NEWSLETTER = "newsletter", "Newsletter"


class OpportunityType(models.TextChoices):
    """Types of content opportunities."""
    TREND = "trend", "Trend"
    EVERGREEN = "evergreen", "Evergreen"
    COMPETITIVE = "competitive", "Competitive"
    CAMPAIGN = "campaign", "Campaign"


class PackageStatus(models.TextChoices):
    """Status of a content package lifecycle."""
    DRAFT = "draft", "Draft"
    IN_REVIEW = "in_review", "In Review"
    SCHEDULED = "scheduled", "Scheduled"
    PUBLISHED = "published", "Published"
    ARCHIVED = "archived", "Archived"


class VariantStatus(models.TextChoices):
    """Status of a content variant."""
    DRAFT = "draft", "Draft"
    EDITED = "edited", "Edited"
    APPROVED = "approved", "Approved"
    SCHEDULED = "scheduled", "Scheduled"
    PUBLISHED = "published", "Published"
    REJECTED = "rejected", "Rejected"


class PatternStatus(models.TextChoices):
    """Status of a pattern template."""
    ACTIVE = "active", "Active"
    EXPERIMENTAL = "experimental", "Experimental"
    DEPRECATED = "deprecated", "Deprecated"


class PatternCategory(models.TextChoices):
    """Categories for pattern templates."""
    EVERGREEN = "evergreen", "Evergreen"
    LAUNCH = "launch", "Launch"
    EDUCATION = "education", "Education"
    ENGAGEMENT = "engagement", "Engagement"


class ExecutionEventType(models.TextChoices):
    """Types of execution/engagement events from platforms."""
    IMPRESSION = "impression", "Impression"
    CLICK = "click", "Click"
    LIKE = "like", "Like"
    COMMENT = "comment", "Comment"
    SHARE = "share", "Share"
    SAVE = "save", "Save"
    PROFILE_VISIT = "profile_visit", "Profile Visit"
    LINK_CLICK = "link_click", "Link Click"


class ExecutionSource(models.TextChoices):
    """Source of execution event data."""
    PLATFORM_WEBHOOK = "platform_webhook", "Platform Webhook"
    CSV_IMPORT = "csv_import", "CSV Import"
    MANUAL_ENTRY = "manual_entry", "Manual Entry"
    TEST_FIXTURE = "test_fixture", "Test Fixture"


class LearningSignalType(models.TextChoices):
    """Types of learning signals for the feedback loop."""
    PATTERN_PERFORMANCE_UPDATE = "pattern_performance_update", "Pattern Performance Update"
    OPPORTUNITY_SCORE_UPDATE = "opportunity_score_update", "Opportunity Score Update"
    CHANNEL_PREFERENCE_UPDATE = "channel_preference_update", "Channel Preference Update"
    GUARDRAIL_VIOLATION = "guardrail_violation", "Guardrail Violation"


class CreatedVia(models.TextChoices):
    """How an entity was created."""
    MANUAL = "manual", "Manual"
    AI_SUGGESTED = "ai_suggested", "AI Suggested"
    IMPORTED = "imported", "Imported"


class DecisionType(models.TextChoices):
    """
    User decision types for tracking interactions/intents.

    Used in ExecutionEvent to record user actions that influence
    the learning engine feedback loop.
    """
    OPPORTUNITY_PINNED = "opportunity_pinned", "Opportunity pinned"
    OPPORTUNITY_SNOOZED = "opportunity_snoozed", "Opportunity snoozed"
    OPPORTUNITY_IGNORED = "opportunity_ignored", "Opportunity ignored"
    PACKAGE_CREATED = "package_created", "Package created"
    PACKAGE_APPROVED = "package_approved", "Package approved"
    VARIANT_EDITED = "variant_edited", "Variant edited"
    VARIANT_APPROVED = "variant_approved", "Variant approved"
    VARIANT_REJECTED = "variant_rejected", "Variant rejected"


class TodayBoardState(models.TextChoices):
    """
    TodayBoard state machine states.

    PR0: Foundational scaffolding for opportunities v2.
    Per opportunities_v1_prd.md §0.2.

    State transitions:
    - not_generated_yet -> generating (via POST /regenerate/ or first-run auto-enqueue)
    - generating -> ready (success)
    - generating -> insufficient_evidence (evidence gates failed)
    - generating -> error (LLM error, timeout, etc.)
    - ready -> generating (via POST /regenerate/)
    - insufficient_evidence -> generating (via POST /regenerate/)
    - error -> generating (via POST /regenerate/)

    CRITICAL: GET /today/ MUST NEVER transition states except for first-run auto-enqueue.
    """
    NOT_GENERATED_YET = "not_generated_yet", "Not Generated Yet"
    GENERATING = "generating", "Generating"
    READY = "ready", "Ready"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence", "Insufficient Evidence"
    ERROR = "error", "Error"
