"""
Kairo Ingestion Module.

Ingestion Spec v2: TikTok + Instagram Trend Detection.

This module implements the ingestion pipeline for detecting trends from
social platforms and feeding them into the hero loop (F1 opportunities graph).

Pipeline stages:
1. Capture: Scrape surfaces (TikTok, Instagram, X, Reddit)
2. Normalize: Extract cluster keys, create NormalizedArtifacts
3. Aggregate: Build ClusterBuckets with velocity metrics
4. Score: Compute trend scores, manage lifecycle
5. Emit: Produce TrendSignalDTOs for hero integration
"""

default_app_config = "kairo.ingestion.apps.IngestionConfig"
