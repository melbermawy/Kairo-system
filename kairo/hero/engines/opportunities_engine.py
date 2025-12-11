"""
Opportunities Engine.

PR-3: Service Layer + Engines Layer Skeleton.

Manages opportunity lifecycle:
- Generation of Today board
- Scoring / re-scoring (via learning engine inputs)
- Board-level state: pin, snooze, staleness

Per docs/technical/03-engines-overview.md §5.

NOTE: PR-3 returns deterministic stub data. Real LLM/graph implementation comes in PR-8.
"""

from datetime import datetime, timezone
from uuid import UUID

from kairo.core.enums import Channel, CreatedVia, OpportunityType
from kairo.core.models import Brand
from kairo.hero.dto import (
    BrandSnapshotDTO,
    LearningSummaryDTO,
    OpportunityDTO,
    PersonaDTO,
    PillarDTO,
    TodayBoardDTO,
    TodayBoardMetaDTO,
)


def generate_today_board(brand_id: UUID) -> TodayBoardDTO:
    """
    Generate the Today board for a brand.

    Per PR-map-and-standards §PR-3:
    - Look up Brand by id (use kairo/core/models.py, not DTOs for the DB lookup)
    - Construct a hardcoded but realistic TodayBoardDTO
    - 6-10 OpportunityDTO items
    - Scores in [60, 95]
    - Primary channel in {linkedin, x}
    - Do not persist opportunities yet (no DB writes here in PR-3)

    Args:
        brand_id: UUID of the brand

    Returns:
        TodayBoardDTO with stub opportunities

    Raises:
        Brand.DoesNotExist: If brand not found
    """
    # Look up brand from DB to validate it exists
    brand = Brand.objects.get(id=brand_id)

    # Build brand snapshot from actual brand data
    snapshot = _build_brand_snapshot(brand)

    # Generate deterministic stub opportunities
    opportunities = _generate_stub_opportunities(brand_id, brand.name)

    # Build metadata
    now = datetime.now(timezone.utc)
    channel_mix = _compute_channel_mix(opportunities)

    meta = TodayBoardMetaDTO(
        generated_at=now,
        source="hero_f1",
        degraded=False,
        notes=["PR-3 stub implementation - real LLM generation comes in PR-8"],
        opportunity_count=len(opportunities),
        dominant_pillar=snapshot.pillars[0].name if snapshot.pillars else None,
        dominant_persona=snapshot.personas[0].name if snapshot.personas else None,
        channel_mix=channel_mix,
    )

    return TodayBoardDTO(
        brand_id=brand_id,
        snapshot=snapshot,
        opportunities=opportunities,
        meta=meta,
    )


def _build_brand_snapshot(brand: Brand) -> BrandSnapshotDTO:
    """
    Build a BrandSnapshotDTO from a Brand model.

    Loads related personas and pillars from DB.
    """
    # Load personas
    personas = []
    for persona in brand.personas.all():
        personas.append(
            PersonaDTO(
                id=persona.id,
                name=persona.name,
                role=persona.role or None,
                summary=persona.summary,
                priorities=persona.priorities or [],
                pains=persona.pains or [],
                success_metrics=persona.success_metrics or [],
                channel_biases=persona.channel_biases or {},
            )
        )

    # Load pillars
    pillars = []
    for pillar in brand.pillars.filter(is_active=True):
        pillars.append(
            PillarDTO(
                id=pillar.id,
                name=pillar.name,
                category=pillar.category or None,
                description=pillar.description,
                priority_rank=pillar.priority_rank,
                is_active=pillar.is_active,
            )
        )

    return BrandSnapshotDTO(
        brand_id=brand.id,
        brand_name=brand.name,
        positioning=brand.positioning or None,
        pillars=pillars,
        personas=personas,
        voice_tone_tags=brand.tone_tags or [],
        taboos=brand.taboos or [],
    )


def _generate_stub_opportunities(brand_id: UUID, brand_name: str) -> list[OpportunityDTO]:
    """
    Generate deterministic stub opportunities for PR-3.

    Returns 8 opportunities with realistic content based on brand.
    Scores range from 60-95, alternating channels.
    """
    now = datetime.now(timezone.utc)

    # Deterministic opportunity templates
    templates = [
        {
            "title": f"Industry trend: AI adoption in {brand_name}'s sector",
            "angle": "Rising discussion about AI tools - opportunity to share our perspective on practical implementation.",
            "type": OpportunityType.TREND,
            "channel": Channel.LINKEDIN,
            "score": 92.0,
        },
        {
            "title": "Weekly thought leadership post",
            "angle": "Regular cadence content about our core expertise area.",
            "type": OpportunityType.EVERGREEN,
            "channel": Channel.LINKEDIN,
            "score": 85.0,
        },
        {
            "title": "Competitor announcement response",
            "angle": "Competitor just announced a feature - opportunity to differentiate our approach.",
            "type": OpportunityType.COMPETITIVE,
            "channel": Channel.X,
            "score": 78.0,
        },
        {
            "title": "Customer success story",
            "angle": "Recent customer achieved notable results - great case study material.",
            "type": OpportunityType.EVERGREEN,
            "channel": Channel.LINKEDIN,
            "score": 88.0,
        },
        {
            "title": "Industry report commentary",
            "angle": "New industry report released - can provide contrarian take aligned with our positioning.",
            "type": OpportunityType.TREND,
            "channel": Channel.X,
            "score": 75.0,
        },
        {
            "title": "Behind the scenes: Product development",
            "angle": "Authenticity content showing how we build - builds trust with audience.",
            "type": OpportunityType.EVERGREEN,
            "channel": Channel.LINKEDIN,
            "score": 70.0,
        },
        {
            "title": "Quick tip thread",
            "angle": "Tactical advice thread format works well for engagement.",
            "type": OpportunityType.EVERGREEN,
            "channel": Channel.X,
            "score": 82.0,
        },
        {
            "title": "Event follow-up content",
            "angle": "Upcoming industry event - opportunity to share insights and connect.",
            "type": OpportunityType.CAMPAIGN,
            "channel": Channel.LINKEDIN,
            "score": 65.0,
        },
    ]

    opportunities = []
    for i, template in enumerate(templates):
        opp = OpportunityDTO(
            id=UUID(f"00000000-0000-0000-0000-{i:012d}"),
            brand_id=brand_id,
            title=template["title"],
            angle=template["angle"],
            type=template["type"],
            primary_channel=template["channel"],
            score=template["score"],
            score_explanation="PR-3 stub score - real scoring comes in PR-8",
            source="stub_engine",
            source_url=None,
            persona_id=None,
            pillar_id=None,
            suggested_channels=[Channel.LINKEDIN, Channel.X],
            is_pinned=(i == 0),  # Pin the top opportunity
            is_snoozed=False,
            snoozed_until=None,
            created_via=CreatedVia.AI_SUGGESTED,
            created_at=now,
            updated_at=now,
        )
        opportunities.append(opp)

    # Sort by score descending
    opportunities.sort(key=lambda x: x.score, reverse=True)

    return opportunities


def _compute_channel_mix(opportunities: list[OpportunityDTO]) -> dict[str, int]:
    """Compute channel distribution from opportunities."""
    mix: dict[str, int] = {}
    for opp in opportunities:
        channel_value = opp.primary_channel.value
        mix[channel_value] = mix.get(channel_value, 0) + 1
    return mix
