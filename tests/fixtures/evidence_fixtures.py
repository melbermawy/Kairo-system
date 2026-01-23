"""
Evidence Test Fixtures for PR1.

Per opportunities_v1_prd.md §13 - Golden Path Anti-Cheat.

These fixtures provide:
1. Sufficient evidence (passes all gates)
2. Insufficient evidence (fails basic quality gates)
3. Low-quality evidence (passes basic, fails usability)
4. Adversarial evidence (duplicates, missing fields, etc.)

CRITICAL: These are test fixtures only. They do NOT call Apify.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest


def create_evidence_item(
    brand_id: UUID,
    *,
    platform: str = "instagram",
    content_type: str = "post",
    author_ref: str | None = None,
    text_primary: str | None = None,
    text_secondary: str | None = None,
    published_at: datetime | None = None,
    has_transcript: bool = False,
    is_low_value: bool = False,
    canonical_url: str | None = None,
    external_id: str | None = None,
) -> dict:
    """Create a NormalizedEvidenceItem kwargs dict for testing."""
    now = datetime.now(timezone.utc)
    item_id = uuid4()

    return {
        "id": item_id,
        "brand_id": brand_id,
        "platform": platform,
        "content_type": content_type,
        "external_id": external_id or str(uuid4())[:8],
        "canonical_url": canonical_url or f"https://{platform}.com/p/{item_id}",
        "published_at": published_at or (now - timedelta(days=1)),
        "author_ref": author_ref or f"@author_{uuid4().hex[:6]}",
        "title": None,
        "text_primary": text_primary or f"Sample content for testing purposes. This is item {item_id}.",
        "text_secondary": text_secondary,
        "hashtags": ["test", "content"],
        "metrics_json": {"likes": 100, "comments": 10},
        "media_json": {},
        "raw_refs": [],
        "flags_json": {
            "has_transcript": has_transcript,
            "is_low_value": is_low_value,
        },
    }


def create_sufficient_evidence(brand_id: UUID) -> list[dict]:
    """
    Create evidence that passes ALL gates.

    Requirements (per PRD §6.1-6.2):
    - >= 8 items
    - >= 6 items with text
    - >= 30% transcript coverage
    - At least 1 platform from {instagram, tiktok}
    - At least 1 item < 7 days old
    - >= 4 items with >= 30 char text
    - >= 3 distinct authors
    - >= 6 distinct URLs
    - < 20% duplicates
    - >= 60% items with content
    """
    now = datetime.now(timezone.utc)
    items = []

    # Create 10 diverse items with COMPLETELY DIFFERENT content
    # to avoid duplicate detection
    content_templates = [
        "Marketing strategies for growing your audience organically through consistent posting.",
        "Product review showcasing the latest features and user experience improvements.",
        "Behind the scenes look at our design process and creative workflow daily.",
        "Customer success story highlighting how they achieved their business goals.",
        "Industry news roundup covering the most important developments this week.",
        "Tutorial explaining step by step how to use advanced features effectively.",
        "Team spotlight introducing our amazing engineers and their projects.",
        "Event announcement for our upcoming virtual conference and workshops.",
        "Competitive analysis comparing different approaches in the market today.",
        "Community highlights featuring user generated content and testimonials.",
    ]

    # Different authors for each - no overlap
    authors = [f"@unique_creator_{i}" for i in range(10)]  # 10 distinct authors
    platforms = ["instagram", "tiktok", "instagram", "tiktok", "instagram",
                 "tiktok", "instagram", "tiktok", "instagram", "tiktok"]

    for i in range(10):
        items.append(create_evidence_item(
            brand_id,
            platform=platforms[i],
            content_type="reel" if platforms[i] == "instagram" else "short_video",
            author_ref=authors[i],  # Each item has unique author
            text_primary=content_templates[i],  # Each item has unique content
            text_secondary=f"Unique transcript content for video number {i} discussing {content_templates[i][:20]}" if i % 3 == 0 else None,
            has_transcript=i % 3 == 0,  # 4/10 = 40% transcript coverage
            published_at=now - timedelta(days=i),  # Fresh items
        ))

    return items


def create_insufficient_evidence(brand_id: UUID) -> list[dict]:
    """
    Create evidence that FAILS basic quality gates.

    Phase 3: MIN_EVIDENCE_ITEMS is now 2 (relaxed for BYOK users).
    This creates only 1 item to fail the minimum requirement.
    """
    now = datetime.now(timezone.utc)
    items = []

    # Only 1 item - insufficient (< 2)
    items.append(create_evidence_item(
        brand_id,
        platform="instagram",
        author_ref="@creator_0",
        text_primary="Short content 0",
        published_at=now,
    ))

    return items


def create_low_quality_evidence(brand_id: UUID) -> list[dict]:
    """
    Create evidence that passes BASIC gates but FAILS usability gates.

    This has enough items but:
    - Not enough items with substantial text (< 4 with >= 30 chars)
    - All from same author (< 3 distinct)
    """
    now = datetime.now(timezone.utc)
    items = []
    single_author = "@single_creator"

    # 10 items from same author with short text
    for i in range(10):
        items.append(create_evidence_item(
            brand_id,
            platform="instagram" if i % 2 == 0 else "tiktok",
            author_ref=single_author,  # All same author
            text_primary=f"Hi {i}",  # Very short text (< 30 chars)
            text_secondary=f"transcript {i}" if i % 3 == 0 else None,
            has_transcript=i % 3 == 0,
            published_at=now - timedelta(days=i),
        ))

    return items


def create_adversarial_duplicates(brand_id: UUID) -> list[dict]:
    """
    Create evidence with high duplicate ratio (> 20%).

    Near-duplicates: same author + similar text.
    """
    now = datetime.now(timezone.utc)
    items = []
    authors = ["@creator_a", "@creator_b"]

    # Base content that will be duplicated
    base_text = "This is the original content that will appear multiple times with minor variations in different items."

    # Create 10 items, 4 of which are near-duplicates
    for i in range(10):
        if i < 4:
            # Near-duplicates: same author, similar text
            text = base_text + f" Variation {i}."
            author = "@creator_a"
        else:
            # Unique items
            text = f"Completely unique content for item {i}. This has different words and structure."
            author = authors[i % 2]

        items.append(create_evidence_item(
            brand_id,
            platform="instagram" if i % 2 == 0 else "tiktok",
            author_ref=author,
            text_primary=text,
            text_secondary=f"transcript {i}" if i % 3 == 0 else None,
            has_transcript=i % 3 == 0,
            published_at=now - timedelta(days=i),
        ))

    return items


def create_adversarial_missing_thumbnails(brand_id: UUID) -> list[dict]:
    """
    Create evidence where media_json has no thumbnail_url.

    This tests that generation handles missing optional fields.
    """
    now = datetime.now(timezone.utc)
    items = create_sufficient_evidence(brand_id)

    # Clear all thumbnail data
    for item in items:
        item["media_json"] = {}  # No thumbnail

    return items


def create_adversarial_missing_metrics(brand_id: UUID) -> list[dict]:
    """
    Create evidence where metrics_json is empty.

    This tests that generation handles missing metrics.
    """
    now = datetime.now(timezone.utc)
    items = create_sufficient_evidence(brand_id)

    # Clear all metrics
    for item in items:
        item["metrics_json"] = {}

    return items


def create_adversarial_stale_evidence(brand_id: UUID) -> list[dict]:
    """
    Create evidence that is all older than MIN_FRESHNESS_DAYS.

    This should fail the freshness gate.
    """
    now = datetime.now(timezone.utc)
    items = []
    authors = [f"@creator_{i}" for i in range(5)]

    # All items older than 7 days
    for i in range(10):
        items.append(create_evidence_item(
            brand_id,
            platform="instagram" if i % 2 == 0 else "tiktok",
            author_ref=authors[i % len(authors)],
            text_primary=f"Stale content from {30 + i} days ago. This is substantial text that passes length requirements.",
            text_secondary=f"transcript {i}" if i % 3 == 0 else None,
            has_transcript=i % 3 == 0,
            published_at=now - timedelta(days=30 + i),  # All stale
        ))

    return items


def create_adversarial_wrong_platforms(brand_id: UUID) -> list[dict]:
    """
    Create evidence with no required platforms (instagram, tiktok).

    This should fail the platform diversity gate.
    """
    now = datetime.now(timezone.utc)
    items = []
    authors = [f"@creator_{i}" for i in range(5)]

    # All linkedin - not in required platforms
    for i in range(10):
        items.append(create_evidence_item(
            brand_id,
            platform="linkedin",
            content_type="text_post",
            author_ref=authors[i % len(authors)],
            text_primary=f"LinkedIn content {i}. This is substantial text for the item.",
            text_secondary=f"transcript {i}" if i % 3 == 0 else None,
            has_transcript=i % 3 == 0,
            published_at=now - timedelta(days=i),
        ))

    return items


def create_adversarial_no_transcripts(brand_id: UUID) -> list[dict]:
    """
    Create evidence with zero transcript coverage.

    This should fail the transcript coverage gate (< 30%).
    """
    now = datetime.now(timezone.utc)
    items = []
    authors = [f"@creator_{i}" for i in range(5)]

    # All items without transcripts
    for i in range(10):
        items.append(create_evidence_item(
            brand_id,
            platform="instagram" if i % 2 == 0 else "tiktok",
            author_ref=authors[i % len(authors)],
            text_primary=f"Content {i} without any transcript. This is substantial text for the item to pass length gate.",
            text_secondary=None,  # No transcript
            has_transcript=False,  # No transcript
            published_at=now - timedelta(days=i),
        ))

    return items


# =============================================================================
# PYTEST FIXTURES
# =============================================================================


@pytest.fixture
def brand_with_sufficient_evidence(db, tenant):
    """Create a brand with sufficient evidence for generation."""
    from kairo.brandbrain.models import NormalizedEvidenceItem
    from kairo.core.models import Brand

    brand = Brand.objects.create(
        tenant=tenant,
        name="Brand With Sufficient Evidence",
        slug="brand-with-sufficient-evidence",
        positioning="Has enough evidence for generation",
    )

    evidence_data = create_sufficient_evidence(brand.id)
    for data in evidence_data:
        NormalizedEvidenceItem.objects.create(**data)

    return brand


@pytest.fixture
def brand_with_insufficient_evidence(db, tenant):
    """Create a brand with insufficient evidence (fails basic gates)."""
    from kairo.brandbrain.models import NormalizedEvidenceItem
    from kairo.core.models import Brand

    brand = Brand.objects.create(
        tenant=tenant,
        name="Brand With Insufficient Evidence",
        slug="brand-with-insufficient-evidence",
        positioning="Not enough evidence",
    )

    evidence_data = create_insufficient_evidence(brand.id)
    for data in evidence_data:
        NormalizedEvidenceItem.objects.create(**data)

    return brand


@pytest.fixture
def brand_with_low_quality_evidence(db, tenant):
    """Create a brand with low-quality evidence (fails usability gates)."""
    from kairo.brandbrain.models import NormalizedEvidenceItem
    from kairo.core.models import Brand

    brand = Brand.objects.create(
        tenant=tenant,
        name="Brand With Low Quality Evidence",
        slug="brand-with-low-quality-evidence",
        positioning="Low quality evidence",
    )

    evidence_data = create_low_quality_evidence(brand.id)
    for data in evidence_data:
        NormalizedEvidenceItem.objects.create(**data)

    return brand


@pytest.fixture
def brand_with_duplicate_evidence(db, tenant):
    """Create a brand with high duplicate ratio."""
    from kairo.brandbrain.models import NormalizedEvidenceItem
    from kairo.core.models import Brand

    brand = Brand.objects.create(
        tenant=tenant,
        name="Brand With Duplicate Evidence",
        slug="brand-with-duplicate-evidence",
        positioning="Too many duplicates",
    )

    evidence_data = create_adversarial_duplicates(brand.id)
    for data in evidence_data:
        NormalizedEvidenceItem.objects.create(**data)

    return brand


@pytest.fixture
def brand_with_stale_evidence(db, tenant):
    """Create a brand with all stale evidence."""
    from kairo.brandbrain.models import NormalizedEvidenceItem
    from kairo.core.models import Brand

    brand = Brand.objects.create(
        tenant=tenant,
        name="Brand With Stale Evidence",
        slug="brand-with-stale-evidence",
        positioning="All evidence is old",
    )

    evidence_data = create_adversarial_stale_evidence(brand.id)
    for data in evidence_data:
        NormalizedEvidenceItem.objects.create(**data)

    return brand
