"""
Apify sample loader helper for golden tests.

PR-0: Provides utilities to load sample JSON files from var/apify_samples/
for use in normalization golden tests.

Directory structure:
    var/apify_samples/
    ├── {actor_id}/           # e.g., "apify_instagram-scraper"
    │   ├── {run_uuid}/       # e.g., "fc694124-0928-4c32-8c8b-871483c1a51f"
    │   │   ├── item_0.json
    │   │   ├── item_1.json
    │   │   └── ...
    │   └── {another_run_uuid}/
    └── ...

Usage:
    from tests.helpers.apify_samples import load_sample, list_sample_dirs

    # List available actor directories
    actors = list_sample_dirs()

    # Load a specific sample
    sample = load_sample("apify_instagram-scraper", item_index=0)
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


# Anchor to project root - var/apify_samples/ relative to repo root
def _get_samples_root() -> Path:
    """Get the absolute path to var/apify_samples/ directory."""
    # Navigate from this file to project root
    # tests/helpers/apify_samples.py -> tests/helpers -> tests -> project_root
    project_root = Path(__file__).parent.parent.parent
    samples_root = project_root / "var" / "apify_samples"
    return samples_root


SAMPLES_ROOT = _get_samples_root()

# Valid actor directory pattern (alphanumeric with underscores, tildes, hyphens)
VALID_ACTOR_PATTERN = re.compile(r"^[\w~-]+$")

# Valid UUID pattern for run directories
UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class SampleNotFoundError(Exception):
    """Raised when a requested sample cannot be found."""

    pass


class InvalidPathError(Exception):
    """Raised when a path component fails validation (path traversal protection)."""

    pass


def _validate_actor_name(actor_name: str) -> None:
    """
    Validate actor name to prevent path traversal attacks.

    Args:
        actor_name: The actor directory name to validate.

    Raises:
        InvalidPathError: If the actor name contains invalid characters.
    """
    if not actor_name:
        raise InvalidPathError("Actor name cannot be empty")

    if not VALID_ACTOR_PATTERN.match(actor_name):
        raise InvalidPathError(
            f"Invalid actor name '{actor_name}'. "
            "Must contain only alphanumeric characters, underscores, tildes, or hyphens."
        )

    # Extra safety: no path separators or special sequences
    if ".." in actor_name or "/" in actor_name or "\\" in actor_name:
        raise InvalidPathError(f"Invalid actor name '{actor_name}': path traversal detected")


def _validate_item_index(item_index: int) -> None:
    """
    Validate item index is non-negative.

    Args:
        item_index: The item index to validate.

    Raises:
        ValueError: If item_index is negative.
    """
    if item_index < 0:
        raise ValueError(f"item_index must be non-negative, got {item_index}")


def list_sample_dirs() -> list[str]:
    """
    List all actor directories in var/apify_samples/.

    Returns:
        Sorted list of actor directory names (e.g., ["apify_instagram-scraper", ...]).
        Excludes hidden directories and non-directories.

    Raises:
        SampleNotFoundError: If the samples root directory doesn't exist.
    """
    if not SAMPLES_ROOT.exists():
        raise SampleNotFoundError(f"Samples directory not found: {SAMPLES_ROOT}")

    if not SAMPLES_ROOT.is_dir():
        raise SampleNotFoundError(f"Samples path is not a directory: {SAMPLES_ROOT}")

    dirs = []
    for entry in SAMPLES_ROOT.iterdir():
        # Skip hidden directories and non-directories
        if entry.name.startswith("."):
            continue
        if not entry.is_dir():
            continue
        # Skip directories that don't match the valid pattern
        if not VALID_ACTOR_PATTERN.match(entry.name):
            continue
        dirs.append(entry.name)

    return sorted(dirs)


def list_run_dirs(actor_name: str) -> list[str]:
    """
    List all run directories for a given actor.

    Args:
        actor_name: The actor directory name (e.g., "apify_instagram-scraper").

    Returns:
        Sorted list of run UUIDs available for this actor.

    Raises:
        InvalidPathError: If actor_name fails validation.
        SampleNotFoundError: If the actor directory doesn't exist.
    """
    _validate_actor_name(actor_name)

    actor_dir = SAMPLES_ROOT / actor_name
    if not actor_dir.exists():
        raise SampleNotFoundError(f"Actor directory not found: {actor_dir}")

    if not actor_dir.is_dir():
        raise SampleNotFoundError(f"Actor path is not a directory: {actor_dir}")

    runs = []
    for entry in actor_dir.iterdir():
        if entry.name.startswith("."):
            continue
        if not entry.is_dir():
            continue
        # Only include valid UUID directories
        if UUID_PATTERN.match(entry.name):
            runs.append(entry.name)

    return sorted(runs)


def load_sample(
    actor_name: str,
    item_index: int = 0,
    run_uuid: str | None = None,
) -> dict[str, Any]:
    """
    Load a sample JSON file from var/apify_samples/.

    Args:
        actor_name: The actor directory name (e.g., "apify_instagram-scraper").
        item_index: The item number to load (default 0). Files are named item_N.json.
        run_uuid: Optional specific run UUID. If not provided, uses the first
            available run directory (sorted alphabetically).

    Returns:
        Parsed JSON content as a dictionary.

    Raises:
        InvalidPathError: If actor_name fails validation.
        SampleNotFoundError: If the requested sample doesn't exist.
        ValueError: If item_index is negative.

    Example:
        >>> sample = load_sample("apify_instagram-scraper", item_index=0)
        >>> sample["id"]
        '3601328990659355969'
    """
    _validate_actor_name(actor_name)
    _validate_item_index(item_index)

    actor_dir = SAMPLES_ROOT / actor_name
    if not actor_dir.exists():
        raise SampleNotFoundError(f"Actor directory not found: {actor_dir}")

    # Determine which run directory to use
    if run_uuid is not None:
        # Validate run_uuid format
        if not UUID_PATTERN.match(run_uuid):
            raise InvalidPathError(f"Invalid run UUID format: {run_uuid}")
        run_dir = actor_dir / run_uuid
    else:
        # Use first available run directory
        runs = list_run_dirs(actor_name)
        if not runs:
            raise SampleNotFoundError(f"No run directories found for actor: {actor_name}")
        run_dir = actor_dir / runs[0]

    if not run_dir.exists():
        raise SampleNotFoundError(f"Run directory not found: {run_dir}")

    # Build the item filename
    item_filename = f"item_{item_index}.json"
    item_path = run_dir / item_filename

    if not item_path.exists():
        raise SampleNotFoundError(
            f"Sample item not found: {item_path}. "
            f"Available items: {list(run_dir.glob('item_*.json'))}"
        )

    # Load and parse JSON
    with open(item_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_sample_path(
    actor_name: str,
    item_index: int = 0,
    run_uuid: str | None = None,
) -> Path:
    """
    Get the path to a sample JSON file without loading it.

    Same arguments as load_sample().

    Returns:
        Path object pointing to the sample file.

    Raises:
        Same as load_sample().
    """
    _validate_actor_name(actor_name)
    _validate_item_index(item_index)

    actor_dir = SAMPLES_ROOT / actor_name
    if not actor_dir.exists():
        raise SampleNotFoundError(f"Actor directory not found: {actor_dir}")

    if run_uuid is not None:
        if not UUID_PATTERN.match(run_uuid):
            raise InvalidPathError(f"Invalid run UUID format: {run_uuid}")
        run_dir = actor_dir / run_uuid
    else:
        runs = list_run_dirs(actor_name)
        if not runs:
            raise SampleNotFoundError(f"No run directories found for actor: {actor_name}")
        run_dir = actor_dir / runs[0]

    if not run_dir.exists():
        raise SampleNotFoundError(f"Run directory not found: {run_dir}")

    item_path = run_dir / f"item_{item_index}.json"
    if not item_path.exists():
        raise SampleNotFoundError(f"Sample item not found: {item_path}")

    return item_path
