#!/usr/bin/env python
"""
Helper script to run manage.py with .env values taking precedence.

This works around rogue DATABASE_URL exports in your shell environment.
See docs/notes/dev_env_database_url_fix.md for details.

Usage:
    python scripts/run_manage.py <command> [args...]

Examples:
    python scripts/run_manage.py check
    python scripts/run_manage.py migrate
    python scripts/run_manage.py shell
    python scripts/run_manage.py runserver
"""

import os
import sys
from pathlib import Path

# Ensure we're in the project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))


def load_env_with_override():
    """Load .env and force-override DATABASE_URL if present in .env."""
    env_path = PROJECT_ROOT / ".env"

    if not env_path.exists():
        return

    # Parse .env manually to get DATABASE_URL
    env_vars = {}
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                # Remove surrounding quotes if present
                if (value.startswith('"') and value.endswith('"')) or \
                   (value.startswith("'") and value.endswith("'")):
                    value = value[1:-1]
                env_vars[key] = value

    # Force-override DATABASE_URL from .env
    if "DATABASE_URL" in env_vars:
        current = os.environ.get("DATABASE_URL", "")
        env_value = env_vars["DATABASE_URL"]

        if current and current != env_value:
            # Check if current is localhost and .env is not
            if "localhost" in current and "localhost" not in env_value:
                print(
                    f"\033[93m⚠️  Overriding rogue DATABASE_URL\033[0m",
                    file=sys.stderr,
                )
                print(
                    f"   Shell had: {current[:50]}...",
                    file=sys.stderr,
                )
                print(
                    f"   Using .env: {env_value[:50]}...",
                    file=sys.stderr,
                )
                print(file=sys.stderr)

        os.environ["DATABASE_URL"] = env_value


def main():
    load_env_with_override()

    # Set Django settings module
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "kairo.settings")

    # Import and run Django's management command
    from django.core.management import execute_from_command_line

    # Build argv: ['manage.py', <command>, <args>...]
    argv = ["manage.py"] + sys.argv[1:]
    execute_from_command_line(argv)


if __name__ == "__main__":
    main()
