"""
Identifier normalization for SourceConnection.

PR-1: Normalize identifiers before save to ensure uniqueness constraint works correctly.

Conservative approach: only normalize obvious duplicates, no heavy parsing.

Platform-specific rules:
- instagram/tiktok: strip leading '@' from handles
- linkedin company_posts: if URL, extract slug; if slug, lowercase
- web/youtube: only trim whitespace + strip trailing slash from URLs
- ALL URLs: lowercase scheme+host only (preserve path case and query string)
"""

from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse


def normalize_source_identifier(platform: str, capability: str, identifier: str) -> str:
    """
    Normalize a source identifier for deduplication.

    Args:
        platform: Platform name (instagram, linkedin, tiktok, youtube, web)
        capability: Capability type (posts, reels, company_posts, etc.)
        identifier: Raw identifier (URL, handle, slug)

    Returns:
        Normalized identifier string.

    Normalization rules (conservative, platform-aware):
    - Strip leading/trailing whitespace (all)
    - URLs: lowercase scheme+host only, preserve path case and query string
    - URLs: strip trailing slash from path only
    - instagram/tiktok handles: strip leading '@'
    - linkedin company_posts URLs: extract slug after /company/
    - linkedin company_posts slugs: lowercase
    - web/youtube: no handle rules, only URL normalization
    """
    if not identifier:
        return identifier

    # Strip whitespace
    identifier = identifier.strip()

    if not identifier:
        return identifier

    # Check if it looks like a URL (case-insensitive check)
    lower = identifier.lower()
    is_url = lower.startswith(("http://", "https://", "//"))

    if is_url:
        identifier = _normalize_url_identifier(platform, capability, identifier)
    else:
        identifier = _normalize_handle_identifier(platform, capability, identifier)

    return identifier


def _normalize_url_identifier(platform: str, capability: str, identifier: str) -> str:
    """
    Normalize URL-based identifiers.

    Rules:
    - Lowercase scheme and host only (NOT path or query)
    - Strip trailing slash from path
    - Preserve query string and fragment
    - LinkedIn company URLs: extract and lowercase slug
    - No www stripping (too risky for general use)
    """
    try:
        parsed = urlparse(identifier)

        # Lowercase scheme and host only
        scheme = parsed.scheme.lower() if parsed.scheme else "https"
        host = parsed.netloc.lower() if parsed.netloc else ""

        # Path: strip trailing slash, but preserve case
        path = parsed.path.rstrip("/")

        # LinkedIn company: extract slug (special case)
        if platform == "linkedin" and capability == "company_posts":
            # For LinkedIn, we DO strip www and extract just the slug
            match = re.search(r"/company/([^/?#]+)", path, re.IGNORECASE)
            if match:
                return match.group(1).lower()

        # Rebuild URL preserving query and fragment
        # urlunparse expects: (scheme, netloc, path, params, query, fragment)
        normalized = urlunparse((
            scheme,
            host,
            path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        ))

        return normalized

    except Exception:
        # If parsing fails, just strip trailing slash
        return identifier.rstrip("/")


def _normalize_handle_identifier(platform: str, capability: str, identifier: str) -> str:
    """
    Normalize handle-based identifiers (non-URL).

    Rules:
    - instagram/tiktok: strip leading '@'
    - linkedin company_posts: lowercase slug
    - web/youtube: no handle rules (shouldn't have handles anyway)
    """
    # Strip leading '@' for social handles only
    if platform in ("instagram", "tiktok") and identifier.startswith("@"):
        identifier = identifier[1:]

    # LinkedIn company slug: lowercase
    if platform == "linkedin" and capability == "company_posts":
        identifier = identifier.lower()

    return identifier
