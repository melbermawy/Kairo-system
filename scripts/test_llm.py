#!/usr/bin/env python
"""
One-shot LLM verification script.

PR-7: Tests that LLM is properly wired in the compile pipeline.

Usage:
    # Test with real LLM (requires OPENAI_API_KEY)
    python scripts/test_llm.py

    # Test with LLM disabled (stub mode)
    LLM_DISABLED=1 python scripts/test_llm.py

    # Show detailed output
    python scripts/test_llm.py --verbose

Expected output:
    - LLM config summary
    - Sample synthesis result (or stub)
    - Token usage if real LLM was called
"""

import argparse
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Set up Django before importing models
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "kairo.settings")

import django
django.setup()


def main():
    parser = argparse.ArgumentParser(description="Test LLM integration in compile pipeline")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")
    args = parser.parse_args()

    print("=" * 60)
    print("LLM INTEGRATION TEST")
    print("=" * 60)

    # Check environment
    llm_disabled = os.environ.get("LLM_DISABLED", "").lower() in ("true", "1", "yes", "on")
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    openai_key_present = bool(openai_key)
    openai_key_preview = f"{openai_key[:8]}...{openai_key[-4:]}" if len(openai_key) > 12 else "(not set)"

    print(f"\nEnvironment:")
    print(f"  LLM_DISABLED: {llm_disabled}")
    print(f"  OPENAI_API_KEY: {openai_key_preview}")
    print(f"  KAIRO_LLM_MODEL_HEAVY: {os.environ.get('KAIRO_LLM_MODEL_HEAVY', 'gpt-5-pro (default)')}")

    # Test LLMClient directly
    print("\n" + "-" * 60)
    print("Testing LLMClient directly...")
    print("-" * 60)

    from kairo.hero.llm_client import LLMClient, LLMCallError

    client = LLMClient()
    print(f"\nClient config:")
    print(f"  llm_disabled: {client.config.llm_disabled}")
    print(f"  heavy_model: {client.config.heavy_model_name}")
    print(f"  fast_model: {client.config.fast_model_name}")
    print(f"  api_key set: {bool(client.config.api_key)}")

    # Make a test call
    test_brand_id = uuid4()
    test_prompt = "Say 'Hello from Kairo' in exactly 5 words."

    print(f"\nMaking test call...")
    print(f"  brand_id: {test_brand_id}")
    print(f"  prompt: {test_prompt}")

    try:
        response = client.call(
            brand_id=test_brand_id,
            flow="test_llm_script",
            prompt=test_prompt,
            role="fast",  # Use fast model for quick test
        )

        print(f"\n✓ LLM call succeeded!")
        print(f"  status: {response.status}")
        print(f"  model: {response.model}")
        print(f"  tokens_in: {response.usage_tokens_in}")
        print(f"  tokens_out: {response.usage_tokens_out}")
        print(f"  latency_ms: {response.latency_ms}")
        print(f"  response: {response.raw_text[:200]}...")

    except LLMCallError as e:
        print(f"\n✗ LLM call failed: {e}")
        if not client.config.api_key:
            print("  Hint: Set OPENAI_API_KEY or use LLM_DISABLED=1 for stub mode")
        return 1

    # Test the synthesis function directly
    print("\n" + "-" * 60)
    print("Testing _synthesize_brandbrain function...")
    print("-" * 60)

    from kairo.brandbrain.compile.worker import _synthesize_brandbrain, _create_stub_draft

    # Mock data
    mock_answers = {
        "tier0.what_we_do": "We help companies automate their marketing workflows",
        "tier0.who_for": "B2B SaaS companies with 10-100 employees",
        "tier0.primary_goal": "Generate qualified leads through thought leadership content",
        "tier0.cta_posture": "soft",
    }

    mock_bundle = None  # No real bundle for this test
    mock_feature_report = None

    if llm_disabled or not openai_key_present:
        print("\nUsing stub (LLM disabled or no API key)...")
        result = _create_stub_draft(mock_answers, mock_bundle, mock_feature_report)
        llm_meta = {"provider": None, "model": None, "used": False, "error": "LLM_DISABLED" if llm_disabled else "no API key"}
    else:
        print("\nCalling _synthesize_brandbrain with real LLM...")
        try:
            result, llm_meta = _synthesize_brandbrain(
                brand_id=test_brand_id,
                compile_run_id=uuid4(),
                answers=mock_answers,
                bundle=mock_bundle,
                feature_report=mock_feature_report,
            )
        except Exception as e:
            print(f"\n✗ Synthesis failed: {e}")
            result = _create_stub_draft(mock_answers, mock_bundle, mock_feature_report)
            llm_meta = {"provider": "openai", "model": None, "used": False, "error": str(e)}

    print(f"\nLLM Meta:")
    print(f"  provider: {llm_meta.get('provider')}")
    print(f"  model: {llm_meta.get('model')}")
    print(f"  used: {llm_meta.get('used')}")
    print(f"  tokens_in: {llm_meta.get('tokens_in', 0)}")
    print(f"  tokens_out: {llm_meta.get('tokens_out', 0)}")
    print(f"  error: {llm_meta.get('error')}")

    print(f"\nResult summary:")
    print(f"  _stub: {result.get('_stub')}")
    print(f"  _note: {result.get('_note')}")

    if args.verbose:
        print(f"\nFull result:")
        print(json.dumps(result, indent=2, default=str))

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    if llm_meta.get("used"):
        print(f"\n✓ LLM WAS CALLED")
        print(f"  Provider: {llm_meta.get('provider')}")
        print(f"  Model: {llm_meta.get('model')}")
        print(f"  Tokens: {llm_meta.get('tokens_in', 0)} in, {llm_meta.get('tokens_out', 0)} out")
    else:
        print(f"\n✗ LLM WAS NOT CALLED")
        print(f"  Reason: {llm_meta.get('error', 'unknown')}")

    if result.get("_stub"):
        print(f"\n⚠ Output is STUB (not real LLM synthesis)")
    else:
        print(f"\n✓ Output is REAL LLM synthesis")
        if "positioning" in result and "differentiators" in result.get("positioning", {}):
            diff_count = len(result["positioning"]["differentiators"])
            print(f"  differentiators: {diff_count}")
        if "voice" in result and "tone_tags" in result.get("voice", {}):
            tags = result["voice"]["tone_tags"]
            print(f"  tone_tags: {tags}")
        if "content" in result and "content_pillars" in result.get("content", {}):
            pillars = len(result["content"]["content_pillars"])
            print(f"  content_pillars: {pillars}")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
