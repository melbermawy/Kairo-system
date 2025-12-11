"""
Content Engine.

PR-3: Service Layer + Engines Layer Skeleton.
PR-6: Added RunContext + structured logging.

Owns ContentPackage and Variant lifecycles:
- Create packages from opportunities
- Manage multi-channel variants
- Handle workflow statuses (draft → in_review → scheduled → published)

Per docs/technical/03-engines-overview.md §7.

NOTE: PR-3 returns deterministic stub data with NO DB writes.
Real LLM/graph implementation comes in PR-9.
"""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from kairo.core.enums import Channel, CreatedVia, PackageStatus, VariantStatus
from kairo.core.models import ContentPackage, Variant
from kairo.hero.dto import ContentPackageDTO, VariantDTO
from kairo.hero.observability import log_engine_event
from kairo.hero.run_context import RunContext


def create_package_from_opportunity(
    ctx: RunContext,
    opportunity_id: UUID,
) -> ContentPackage:
    """
    Create a content package from an opportunity.

    PR-3 stub behavior:
    - Does NOT create any rows in the DB
    - Returns a fake in-memory ContentPackage instance
    - Has a deterministic UUID based on inputs
    - Has status set to draft

    Real implementation (PR-9) will:
    - Persist ContentPackage to DB
    - Call package graph for thesis generation
    - Respect idempotency (same brand+opportunity = same package)

    PR-6: Now requires RunContext for observability.

    Args:
        ctx: RunContext with run_id, brand_id, flow, trigger_source
        opportunity_id: UUID of the source opportunity

    Returns:
        In-memory ContentPackage instance (not persisted)
    """
    log_engine_event(
        ctx,
        engine="content_engine",
        operation="create_package_from_opportunity",
        status="start",
        extra={"opportunity_id": str(opportunity_id)},
    )

    try:
        now = datetime.now(timezone.utc)

        # Generate deterministic package ID based on brand + opportunity
        # This ensures idempotency for stub behavior
        package_id = _deterministic_uuid(ctx.brand_id, opportunity_id, "package")

        # Create in-memory ContentPackage (NOT saved to DB)
        package = ContentPackage(
            id=package_id,
            brand_id=ctx.brand_id,
            title=f"Package from opportunity {str(opportunity_id)[:8]}",
            status=PackageStatus.DRAFT,
            origin_opportunity_id=opportunity_id,
            persona_id=None,
            pillar_id=None,
            channels=[Channel.LINKEDIN.value, Channel.X.value],
            planned_publish_start=None,
            planned_publish_end=None,
            owner_user_id=None,
            notes="PR-3 stub package - real generation comes in PR-9",
            created_via=CreatedVia.AI_SUGGESTED,
        )
        # Set timestamps manually since we're not saving
        package.created_at = now
        package.updated_at = now

        log_engine_event(
            ctx,
            engine="content_engine",
            operation="create_package_from_opportunity",
            status="success",
            extra={"package_id": str(package.id)},
        )

        return package

    except Exception as exc:
        log_engine_event(
            ctx,
            engine="content_engine",
            operation="create_package_from_opportunity",
            status="failure",
            error_summary=f"{exc.__class__.__name__}: {exc}",
        )
        raise


def generate_variants_for_package(ctx: RunContext, package_id: UUID) -> list[Variant]:
    """
    Generate content variants for a package across its target channels.

    PR-3 stub behavior:
    - Returns a list of fake in-memory Variant objects
    - Generates 2 variants (LinkedIn and X)
    - Does NOT persist to DB

    Real implementation (PR-9) will:
    - Persist Variant rows to DB
    - Call variants graph for content generation
    - Reject if variants already exist (no regeneration in PRD-1)

    PR-6: Now requires RunContext for observability.

    Args:
        ctx: RunContext with run_id, brand_id, flow, trigger_source
        package_id: UUID of the package

    Returns:
        List of in-memory Variant instances (not persisted)
    """
    log_engine_event(
        ctx,
        engine="content_engine",
        operation="generate_variants_for_package",
        status="start",
        extra={"package_id": str(package_id)},
    )

    try:
        now = datetime.now(timezone.utc)

        variants = []

        # Generate variant for each supported channel
        channels_content = {
            Channel.LINKEDIN: {
                "body": (
                    "Here's what we've learned about building great products:\n\n"
                    "1. Start with the problem, not the solution\n"
                    "2. Talk to customers before writing code\n"
                    "3. Ship early, iterate often\n"
                    "4. Measure what matters\n\n"
                    "What would you add to this list?"
                ),
                "cta": "Share your thoughts in the comments",
            },
            Channel.X: {
                "body": (
                    "Product lesson learned the hard way:\n\n"
                    "Don't build features nobody asked for.\n\n"
                    "Talk to 10 customers before writing a single line of code.\n\n"
                    "Thread 🧵"
                ),
                "cta": "Follow for more",
            },
        }

        for i, (channel, content) in enumerate(channels_content.items()):
            variant_id = _deterministic_uuid(package_id, UUID(int=i), "variant")

            variant = Variant(
                id=variant_id,
                brand_id=ctx.brand_id,
                package_id=package_id,
                channel=channel.value,
                status=VariantStatus.DRAFT,
                pattern_template_id=None,
                raw_prompt_context={"stub": True},
                draft_text=content["body"],
                edited_text="",
                approved_text="",
                generated_by_model="stub-pr3",
                proposed_at=now,
                scheduled_publish_at=None,
                published_at=None,
                last_evaluated_at=None,
                eval_score=None,
                eval_notes="",
                metadata={"pr3_stub": True},
            )
            # Set timestamps manually since we're not saving
            variant.created_at = now
            variant.updated_at = now

            variants.append(variant)

        log_engine_event(
            ctx,
            engine="content_engine",
            operation="generate_variants_for_package",
            status="success",
            extra={"num_variants": len(variants)},
        )

        return variants

    except Exception as exc:
        log_engine_event(
            ctx,
            engine="content_engine",
            operation="generate_variants_for_package",
            status="failure",
            error_summary=f"{exc.__class__.__name__}: {exc}",
        )
        raise


def package_to_dto(package: ContentPackage) -> ContentPackageDTO:
    """
    Convert a ContentPackage model to ContentPackageDTO.

    Helper for service layer.
    """
    return ContentPackageDTO(
        id=package.id,
        brand_id=package.brand_id,
        title=package.title,
        status=PackageStatus(package.status),
        origin_opportunity_id=package.origin_opportunity_id,
        persona_id=package.persona_id,
        pillar_id=package.pillar_id,
        channels=[Channel(c) for c in (package.channels or [])],
        planned_publish_start=package.planned_publish_start,
        planned_publish_end=package.planned_publish_end,
        owner_user_id=package.owner_user_id,
        notes=package.notes or None,
        created_via=CreatedVia(package.created_via),
        created_at=package.created_at,
        updated_at=package.updated_at,
    )


def variant_to_dto(variant: Variant) -> VariantDTO:
    """
    Convert a Variant model to VariantDTO.

    Helper for service layer.
    """
    # Determine active body based on status
    body = variant.draft_text
    if variant.edited_text:
        body = variant.edited_text
    if variant.approved_text:
        body = variant.approved_text

    return VariantDTO(
        id=variant.id,
        package_id=variant.package_id,
        brand_id=variant.brand_id,
        channel=Channel(variant.channel),
        status=VariantStatus(variant.status),
        pattern_template_id=variant.pattern_template_id,
        body=body,
        call_to_action=None,  # Not in model, would come from metadata
        generated_by_model=variant.generated_by_model or None,
        proposed_at=variant.proposed_at,
        scheduled_publish_at=variant.scheduled_publish_at,
        published_at=variant.published_at,
        eval_score=variant.eval_score,
        eval_notes=variant.eval_notes or None,
        created_at=variant.created_at,
        updated_at=variant.updated_at,
    )


def _deterministic_uuid(base1: UUID, base2: UUID, salt: str) -> UUID:
    """
    Generate a deterministic UUID from two input UUIDs and a salt.

    This ensures idempotency - same inputs always produce same output.
    """
    import hashlib

    combined = f"{base1}{base2}{salt}".encode()
    hash_bytes = hashlib.sha256(combined).digest()[:16]
    return UUID(bytes=hash_bytes)
