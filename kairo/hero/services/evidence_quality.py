"""
Evidence Quality Gates: Hard enforcement for opportunities synthesis.

PR1: Evidence quality gates for opportunities v2.
Per opportunities_v1_prd.md §6.1-6.4.

CRITICAL INVARIANTS:
1. Gates MUST block progression - no "warn but proceed"
2. If gates fail -> transition to insufficient_evidence
3. NO bypass, NO softening thresholds

These are MINIMUM requirements. Below these, synthesis MUST NOT run.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kairo.hero.services.evidence_service import EvidenceItem

logger = logging.getLogger("kairo.hero.services.evidence_quality")


# =============================================================================
# THRESHOLDS (Per PRD §6.1)
# =============================================================================

# Minimum total evidence items
MIN_EVIDENCE_ITEMS = 8

# Minimum items with non-empty text
MIN_ITEMS_WITH_TEXT = 6

# Minimum transcript coverage (fraction of items with transcripts)
MIN_TRANSCRIPT_COVERAGE = 0.3

# Maximum age of evidence to consider (days)
MAX_EVIDENCE_AGE_DAYS = 30

# Required platforms (at least one must be present)
REQUIRED_PLATFORMS = {"instagram", "tiktok"}

# Minimum freshness (at least one item must be newer than this)
MIN_FRESHNESS_DAYS = 7


# =============================================================================
# USABILITY THRESHOLDS (Per PRD §6.2)
# =============================================================================

# Minimum text length for "substantial" content
MIN_TEXT_LENGTH = 30

# Minimum items with substantial text
MIN_ITEMS_WITH_LONG_TEXT = 4

# Minimum distinct authors
MIN_DISTINCT_AUTHORS = 3

# Minimum distinct URLs
MIN_DISTINCT_URLS = 6

# Maximum near-duplicate ratio
MAX_DUPLICATE_RATIO = 0.2

# Minimum content ratio (items with text / total items)
MIN_CONTENT_RATIO = 0.6

# Near-duplicate text similarity threshold (Jaccard)
DUPLICATE_SIMILARITY_THRESHOLD = 0.8


# =============================================================================
# RESULT TYPES
# =============================================================================


@dataclass
class EvidenceShortfall:
    """Details about why evidence was insufficient."""

    required_items: int = MIN_EVIDENCE_ITEMS
    found_items: int = 0
    required_platforms: list[str] = field(default_factory=lambda: list(REQUIRED_PLATFORMS))
    found_platforms: list[str] = field(default_factory=list)
    missing_platforms: list[str] = field(default_factory=list)
    transcript_coverage: float = 0.0
    min_transcript_coverage: float = MIN_TRANSCRIPT_COVERAGE
    failures: list[str] = field(default_factory=list)


@dataclass
class QualityCheckResult:
    """Result of evidence quality check."""

    passed: bool
    shortfall: EvidenceShortfall | None = None
    summary: dict = field(default_factory=dict)


@dataclass
class UsabilityCheckResult:
    """Result of evidence usability check."""

    passed: bool
    failures: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


@dataclass
class FullValidationResult:
    """Result of combined quality + usability validation."""

    can_proceed: bool
    failure_reason: str | None = None
    diagnostics: dict = field(default_factory=dict)


# =============================================================================
# QUALITY CHECK (Basic Gates - PRD §6.1)
# =============================================================================


def check_evidence_quality(
    evidence: list["EvidenceItem"],
    *,
    min_items: int = MIN_EVIDENCE_ITEMS,
    min_items_with_text: int = MIN_ITEMS_WITH_TEXT,
    min_transcript_coverage: float = MIN_TRANSCRIPT_COVERAGE,
    required_platforms: set[str] | None = None,
    min_freshness_days: int = MIN_FRESHNESS_DAYS,
) -> QualityCheckResult:
    """
    Check basic quality gates for evidence.

    Per PRD §6.1 - Minimum Evidence Requirements.

    CRITICAL: This is a hard gate. If it fails, synthesis MUST NOT run.

    Args:
        evidence: List of evidence items
        min_items: Minimum total items required
        min_items_with_text: Minimum items with non-empty text
        min_transcript_coverage: Minimum fraction with transcripts
        required_platforms: Set of platforms (at least one required)
        min_freshness_days: At least one item must be newer than this

    Returns:
        QualityCheckResult with passed=False if any gate fails
    """
    if required_platforms is None:
        required_platforms = REQUIRED_PLATFORMS

    failures = []
    now = datetime.now(timezone.utc)
    freshness_cutoff = now - timedelta(days=min_freshness_days)

    # Count evidence characteristics
    total_items = len(evidence)
    items_with_text = 0
    items_with_transcript = 0
    platforms_found: set[str] = set()
    has_fresh_item = False

    for e in evidence:
        # Platform tracking
        platforms_found.add(e.platform)

        # Text tracking
        if e.text_primary and len(e.text_primary.strip()) > 0:
            items_with_text += 1

        # Transcript tracking
        if e.has_transcript or (e.text_secondary and len(e.text_secondary.strip()) > 0):
            items_with_transcript += 1

        # Freshness tracking
        if e.published_at:
            pub_time = e.published_at
            if pub_time.tzinfo is None:
                pub_time = pub_time.replace(tzinfo=timezone.utc)
            if pub_time >= freshness_cutoff:
                has_fresh_item = True

    transcript_coverage = items_with_transcript / total_items if total_items > 0 else 0.0

    # Check gates
    # Gate 1: Minimum total items
    if total_items < min_items:
        failures.append(
            f"insufficient_items: {total_items} items found, need {min_items}"
        )

    # Gate 2: Minimum items with text
    if items_with_text < min_items_with_text:
        failures.append(
            f"insufficient_text_items: {items_with_text} items have text, need {min_items_with_text}"
        )

    # Gate 3: Platform diversity
    required_found = platforms_found & required_platforms
    if not required_found:
        failures.append(
            f"missing_required_platforms: found {platforms_found}, need at least one of {required_platforms}"
        )

    # Gate 4: Transcript coverage
    if transcript_coverage < min_transcript_coverage:
        failures.append(
            f"insufficient_transcript_coverage: {transcript_coverage:.1%} coverage, need {min_transcript_coverage:.1%}"
        )

    # Gate 5: Freshness
    if not has_fresh_item and total_items > 0:
        failures.append(
            f"stale_evidence: no items newer than {min_freshness_days} days"
        )

    # Build shortfall details
    missing_platforms = list(required_platforms - platforms_found)
    shortfall = EvidenceShortfall(
        required_items=min_items,
        found_items=total_items,
        required_platforms=list(required_platforms),
        found_platforms=list(platforms_found),
        missing_platforms=missing_platforms,
        transcript_coverage=transcript_coverage,
        min_transcript_coverage=min_transcript_coverage,
        failures=failures,
    )

    # Build summary
    summary = {
        "total_items": total_items,
        "items_with_text": items_with_text,
        "items_with_transcript": items_with_transcript,
        "transcript_coverage": transcript_coverage,
        "platforms": list(platforms_found),
        "has_fresh_item": has_fresh_item,
    }

    passed = len(failures) == 0

    if not passed:
        logger.info(
            "Evidence quality check FAILED: %s",
            "; ".join(failures),
        )

    return QualityCheckResult(
        passed=passed,
        shortfall=shortfall if not passed else None,
        summary=summary,
    )


# =============================================================================
# USABILITY CHECK (Hardened Gates - PRD §6.2)
# =============================================================================


def compute_text_similarity(text_a: str, text_b: str) -> float:
    """
    Jaccard similarity of word sets.

    Per PRD §6.2 - Near-Duplicate Detection.
    """
    if not text_a or not text_b:
        return 0.0

    words_a = set(text_a.lower().split())
    words_b = set(text_b.lower().split())

    if not words_a or not words_b:
        return 0.0

    intersection = len(words_a & words_b)
    union = len(words_a | words_b)

    return intersection / union if union > 0 else 0.0


def detect_near_duplicates(
    evidence: list["EvidenceItem"],
    similarity_threshold: float = DUPLICATE_SIMILARITY_THRESHOLD,
) -> list[tuple[str, str]]:
    """
    Detect near-duplicate evidence pairs.

    Per PRD §6.2 - Near-Duplicate Detection.

    Two items are near-duplicates if:
    - Same author_ref AND Jaccard similarity >= threshold
    - OR same canonical_url (exact duplicate)

    Returns:
        List of (id_a, id_b) pairs that are near-duplicates
    """
    duplicates: list[tuple[str, str]] = []

    # Exact URL duplicates
    url_to_ids: dict[str, list[str]] = {}
    for e in evidence:
        url_to_ids.setdefault(e.canonical_url, []).append(str(e.id))

    for ids in url_to_ids.values():
        if len(ids) > 1:
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    duplicates.append((ids[i], ids[j]))

    # Text similarity duplicates (same author)
    author_groups: dict[str, list["EvidenceItem"]] = {}
    for e in evidence:
        author_groups.setdefault(e.author_ref, []).append(e)

    for items in author_groups.values():
        if len(items) < 2:
            continue
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                sim = compute_text_similarity(
                    items[i].text_primary, items[j].text_primary
                )
                if sim >= similarity_threshold:
                    duplicates.append((str(items[i].id), str(items[j].id)))

    return duplicates


def check_evidence_usability(
    evidence: list["EvidenceItem"],
    *,
    min_text_length: int = MIN_TEXT_LENGTH,
    min_items_with_long_text: int = MIN_ITEMS_WITH_LONG_TEXT,
    min_distinct_authors: int = MIN_DISTINCT_AUTHORS,
    min_distinct_urls: int = MIN_DISTINCT_URLS,
    max_duplicate_ratio: float = MAX_DUPLICATE_RATIO,
    min_content_ratio: float = MIN_CONTENT_RATIO,
) -> UsabilityCheckResult:
    """
    Check if evidence is actually usable for synthesis.

    Per PRD §6.2 - Evidence Usability Gates (HARDENED).

    This runs AFTER basic quality checks pass.
    LLM synthesis MUST NOT run unless usability gates pass.

    Args:
        evidence: List of evidence items
        min_text_length: Minimum character count for "substantial" text
        min_items_with_long_text: Minimum items with substantial text
        min_distinct_authors: Minimum unique author_ref values
        min_distinct_urls: Minimum unique canonical_url values
        max_duplicate_ratio: Maximum fraction of near-duplicates
        min_content_ratio: Minimum fraction with any text content

    Returns:
        UsabilityCheckResult with passed=False if any gate fails
    """
    failures = []
    stats = {}

    if not evidence:
        return UsabilityCheckResult(
            passed=False,
            failures=["no_evidence: empty evidence list"],
            stats={"total_items": 0},
        )

    # Text length check
    items_with_long_text = sum(
        1 for e in evidence
        if e.text_primary and len(e.text_primary.strip()) >= min_text_length
    )
    stats["items_with_long_text"] = items_with_long_text
    if items_with_long_text < min_items_with_long_text:
        failures.append(
            f"insufficient_text_length: only {items_with_long_text} items have "
            f">={min_text_length} chars (need {min_items_with_long_text})"
        )

    # Distinct authors check
    distinct_authors = len({e.author_ref for e in evidence})
    stats["distinct_authors"] = distinct_authors
    if distinct_authors < min_distinct_authors:
        failures.append(
            f"insufficient_author_diversity: only {distinct_authors} distinct authors "
            f"(need {min_distinct_authors})"
        )

    # Distinct URLs check
    distinct_urls = len({e.canonical_url for e in evidence})
    stats["distinct_urls"] = distinct_urls
    if distinct_urls < min_distinct_urls:
        failures.append(
            f"insufficient_url_diversity: only {distinct_urls} distinct URLs "
            f"(need {min_distinct_urls})"
        )

    # Near-duplicate check
    duplicates = detect_near_duplicates(evidence)
    duplicate_ratio = len(duplicates) / len(evidence) if evidence else 0.0
    stats["duplicate_pairs"] = len(duplicates)
    stats["duplicate_ratio"] = duplicate_ratio
    if duplicate_ratio > max_duplicate_ratio:
        failures.append(
            f"too_many_duplicates: {duplicate_ratio:.1%} duplicate ratio "
            f"(max {max_duplicate_ratio:.1%})"
        )

    # Non-empty content ratio
    items_with_content = sum(
        1 for e in evidence
        if (e.text_primary and e.text_primary.strip()) or
           (e.text_secondary and e.text_secondary.strip())
    )
    content_ratio = items_with_content / len(evidence) if evidence else 0.0
    stats["items_with_content"] = items_with_content
    stats["content_ratio"] = content_ratio
    if content_ratio < min_content_ratio:
        failures.append(
            f"insufficient_content: only {content_ratio:.1%} items have text content "
            f"(need {min_content_ratio:.1%})"
        )

    passed = len(failures) == 0

    if not passed:
        logger.info(
            "Evidence usability check FAILED: %s",
            "; ".join(failures),
        )

    return UsabilityCheckResult(
        passed=passed,
        failures=failures,
        stats=stats,
    )


# =============================================================================
# COMBINED VALIDATION (PRD §6.3)
# =============================================================================


def validate_evidence_for_synthesis(
    evidence: list["EvidenceItem"],
) -> FullValidationResult:
    """
    Full evidence validation before synthesis.

    Per PRD §6.3 - Combined Quality + Usability Flow.

    CRITICAL: Synthesis MUST NOT run unless this returns can_proceed=True.

    Returns:
        FullValidationResult with can_proceed and failure details
    """
    # Step 1: Basic quality gates
    quality_result = check_evidence_quality(evidence)
    if not quality_result.passed:
        return FullValidationResult(
            can_proceed=False,
            failure_reason="quality_gate_failed",
            diagnostics={
                "shortfall": {
                    "required_items": quality_result.shortfall.required_items if quality_result.shortfall else MIN_EVIDENCE_ITEMS,
                    "found_items": quality_result.shortfall.found_items if quality_result.shortfall else 0,
                    "required_platforms": quality_result.shortfall.required_platforms if quality_result.shortfall else list(REQUIRED_PLATFORMS),
                    "found_platforms": quality_result.shortfall.found_platforms if quality_result.shortfall else [],
                    "missing_platforms": quality_result.shortfall.missing_platforms if quality_result.shortfall else [],
                    "transcript_coverage": quality_result.shortfall.transcript_coverage if quality_result.shortfall else 0.0,
                    "min_transcript_coverage": quality_result.shortfall.min_transcript_coverage if quality_result.shortfall else MIN_TRANSCRIPT_COVERAGE,
                    "failures": quality_result.shortfall.failures if quality_result.shortfall else [],
                },
                "summary": quality_result.summary,
            },
        )

    # Step 2: Usability gates (runs ONLY if quality passes)
    usability_result = check_evidence_usability(evidence)
    if not usability_result.passed:
        return FullValidationResult(
            can_proceed=False,
            failure_reason="usability_gate_failed",
            diagnostics={
                "failures": usability_result.failures,
                "stats": usability_result.stats,
            },
        )

    # All gates passed
    return FullValidationResult(
        can_proceed=True,
        failure_reason=None,
        diagnostics={
            "summary": quality_result.summary,
            "usability_stats": usability_result.stats,
        },
    )
