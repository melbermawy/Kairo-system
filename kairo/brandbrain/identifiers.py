"""
Identifier normalization for SourceConnection.

PR-1: Normalize identifiers before save to ensure uniqueness constraint works correctly.

Conservative approach: only normalize obvious duplicates, no heavy parsing.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse


def normalize_source_identifier(platform: str, capability: str, identifier: str) -> str:
    """
    Normalize a source identifier for deduplication.

    Args:
        platform: Platform name (instagram, linkedin, tiktok, youtube, web)
        capability: Capability type (posts, reels, company_posts, etc.)
        identifier: Raw identifier (URL, handle, slug)

    Returns:
        Normalized identifier string.

    Normalization rules (conservative):
    - Strip leading/trailing whitespace
    - Strip trailing slashes from URLs
    - Strip leading '@' from handles
    - LinkedIn company URLs: extract slug after /company/
    - Lowercase scheme and host for URLs
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
    """Normalize URL-based identifiers."""
    try:
        parsed = urlparse(identifier)

        # Lowercase scheme and host
        scheme = parsed.scheme.lower() if parsed.scheme else "https"
        host = parsed.netloc.lower() if parsed.netloc else ""

        # Strip www. prefix for consistency
        if host.startswith("www."):
            host = host[4:]

        # Get path and strip trailing slash
        path = parsed.path.rstrip("/")

        # LinkedIn company: extract slug
        if platform == "linkedin" and capability == "company_posts":
            match = re.search(r"/company/([^/?#]+)", path)
            if match:
                return match.group(1).lower()

        # Rebuild URL with normalized parts
        normalized = f"{scheme}://{host}{path}"

        # Strip trailing slash again (in case path was just "/")
        return normalized.rstrip("/")

    except Exception:
        # If parsing fails, just strip trailing slash
        return identifier.rstrip("/")


def _normalize_handle_identifier(platform: str, capability: str, identifier: str) -> str:
    """Normalize handle-based identifiers (non-URL)."""
    # Strip leading '@' for social handles
    if platform in ("instagram", "tiktok", "twitter") and identifier.startswith("@"):
        identifier = identifier[1:]

    # LinkedIn company slug: lowercase
    if platform == "linkedin" and capability == "company_posts":
        identifier = identifier.lower()

    return identifier
