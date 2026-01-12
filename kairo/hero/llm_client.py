"""
LLM Client Module.

PR-7: LLM Client + Model Policy (No Graphs Yet).

Provides a single, well-specified LLM client with:
- Config-driven model selection (via environment variables)
- Stable call interface with RunContext observability
- Structured output parsing helper
- LLM_DISABLED mode for tests and eval runs
- Cost estimation hooks

Per docs/technical/05-llm-and-deepagents-conventions.md:
- Two classes of models: "fast" (cheaper, quick tasks) and "heavy" (smart, higher quality)
- Model selection is config-driven, not hardcoded
- Single client exports consistent interface
- All LLM calls go through this client; no direct provider SDK calls elsewhere

Temperature/sampling policy (deterministic by default for eval):
- Default: temperature=0.0, top_p=1.0 (fully deterministic)
- Override via env: KAIRO_LLM_TEMP_FAST, KAIRO_LLM_TOP_P_FAST, etc.

API Routing (PR-7.1):
- GPT-5.x models (gpt-5-*, gpt-5.1-*, etc.) use the Responses API
- Older models (gpt-4o, gpt-3.5-turbo, etc.) use Chat Completions API
- This routing is automatic based on model name prefix detection

This module does NOT contain any graphs or agents - it's pure infrastructure.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Mapping, Sequence, TypeVar

from pydantic import BaseModel, ValidationError

if TYPE_CHECKING:
    from uuid import UUID

logger = logging.getLogger("kairo.llm")

# Import observability logging (late import to avoid circular dependency issues)
_obs_module = None


def _get_obs_module():
    """Lazy import of observability module to avoid circular imports."""
    global _obs_module
    if _obs_module is None:
        try:
            from kairo.hero import observability_store

            _obs_module = observability_store
        except ImportError:
            _obs_module = False  # Mark as unavailable
    return _obs_module if _obs_module else None

# =============================================================================
# TYPE DEFINITIONS
# =============================================================================

Role = Literal["fast", "heavy"]


# =============================================================================
# STUB JSON RESPONSES FOR LLM_DISABLED MODE
# =============================================================================

# Stub responses keyed by flow name. Each stub must parse correctly against
# the expected Pydantic schema for that flow.

# Diverse titles to avoid deduplication filtering (Jaccard similarity threshold is 0.75)
_STUB_OPPORTUNITY_TITLES = [
    "AI automation transforming customer workflows today",
    "Revenue forecasting accuracy improvements with data science",
    "Building trust through transparent communication",
    "Competitive analysis reveals market positioning gaps",
    "Customer success stories drive social proof",
    "Industry report highlights emerging technology trends",
    "Behind the scenes product development journey",
    "Weekly insights for executive decision makers",
]

_STUB_SYNTHESIS_OUTPUT = {
    "opportunities": [
        {
            "title": _STUB_OPPORTUNITY_TITLES[i],
            "angle": f"Unique angle {i}: This stub opportunity demonstrates the value we deliver to our target personas through clear communication and actionable insights.",
            "type": ["trend", "evergreen", "competitive", "campaign", "trend", "evergreen", "trend", "evergreen"][i],
            "primary_channel": "linkedin" if i % 2 == 0 else "x",
            "suggested_channels": ["linkedin", "x"],
            "reasoning": f"Stub reasoning {i} for eval purposes.",
            "why_now": f"Stub timing {i}: Current market dynamics and recent developments make this topic particularly relevant for our audience right now.",
            "source": "stub_source",
            "source_url": None,
            "persona_hint": None,
            "pillar_hint": None,
        }
        for i in range(8)
    ]
}

# New minimal scoring output format - just idx, score, band, reason
_STUB_SCORING_OUTPUT = {
    "scores": [
        {
            "idx": i,
            "score": 75 + (i * 2) % 20,  # Scores: 75, 77, 79, 81, 83, 85, 87, 89
            "band": "strong",  # All stub scores are 65+
            "reason": f"Stub score {i}: Good alignment.",
        }
        for i in range(8)
    ]
}

_STUB_PACKAGE_OUTPUT = {
    "package": {
        "title": "Stub package: Demonstrating value through clear communication",
        "thesis": "Our stub thesis shows how clear, value-driven content builds trust and drives meaningful engagement with our target audience.",
        "summary": "This stub package demonstrates the content approach for eval purposes. It covers the key points that matter to our audience.",
        "primary_channel": "linkedin",
        "channels": ["linkedin", "x"],
        "cta": "Learn more about our approach",
        "pattern_hints": ["thought_leadership", "case_study"],
        "persona_hint": None,
        "pillar_hint": None,
        "notes_for_humans": "Stub package for eval - replace with real LLM output",
        "reasoning": "Stub reasoning for package generation.",
    }
}

_STUB_VARIANTS_OUTPUT = {
    "variants": [
        {
            "channel": "linkedin",
            "title": "Stub LinkedIn Post: Delivering Value",
            "body": "Here's what we've learned about this opportunity:\n\nThe key insight is that our audience cares deeply about value and transparency.\n\nWhen you focus on clear communication, everything else follows.\n\nWhat's your experience with this?",
            "call_to_action": "Share your thoughts below",
            "pattern_hint": "thought_leadership",
            "reasoning": "Stub variant for LinkedIn channel.",
        },
        {
            "channel": "x",
            "title": None,
            "body": "Key insight: value and transparency drive trust.\n\nWhen you focus on clear communication, everything else follows.\n\n🧵",
            "call_to_action": None,
            "pattern_hint": "thread_starter",
            "reasoning": "Stub variant for X channel.",
        },
    ]
}


def _get_stub_json_for_flow(flow: str) -> str:
    """
    Get stub JSON response for a given flow.

    Returns valid JSON that parses against the expected schema for each flow.
    Falls back to an empty object for unknown flows.
    """
    flow_lower = flow.lower()

    if "synthesis" in flow_lower:
        return json.dumps(_STUB_SYNTHESIS_OUTPUT)
    elif "scoring" in flow_lower:
        return json.dumps(_STUB_SCORING_OUTPUT)
    elif "package" in flow_lower:
        return json.dumps(_STUB_PACKAGE_OUTPUT)
    elif "variant" in flow_lower:
        return json.dumps(_STUB_VARIANTS_OUTPUT)
    else:
        # Unknown flow - return a placeholder that signals it's a stub
        return json.dumps({"_stub": True, "_flow": flow})


Status = Literal["success", "failure", "disabled"]

T = TypeVar("T", bound=BaseModel)


# =============================================================================
# EXCEPTIONS
# =============================================================================


class LLMCallError(Exception):
    """
    Exception raised when an LLM call fails.

    Wraps the underlying provider error with additional context.
    No provider-specific exception types escape this module.
    """

    def __init__(self, message: str, original_error: Exception | None = None):
        super().__init__(message)
        self.original_error = original_error


class StructuredOutputError(Exception):
    """
    Exception raised when structured output parsing fails.

    Raised when:
    - Raw text is not valid JSON
    - JSON doesn't validate against the target Pydantic model
    """

    pass


# =============================================================================
# CONFIGURATION
# =============================================================================


def _is_responses_api_model(model: str) -> bool:
    """
    Check if a model should use the Responses API.

    GPT-5.x models (gpt-5-*, gpt-5.1-*, etc.) require the Responses API.
    Older models (gpt-4o, gpt-3.5-turbo, etc.) use Chat Completions API.

    Args:
        model: Model name string

    Returns:
        True if model should use Responses API, False for Chat Completions
    """
    # GPT-5 family models use Responses API
    # Pattern: gpt-5, gpt-5-*, gpt-5.1, gpt-5.1-*, etc.
    model_lower = model.lower()
    return model_lower.startswith("gpt-5")


@dataclass(frozen=True)
class LLMConfig:
    """
    LLM client configuration.

    Reads from environment variables with sensible defaults for tests.

    Environment Variables:
    - OPENAI_API_KEY: API key for OpenAI (required for real calls)
    - KAIRO_LLM_MODEL_FAST: Model name for fast role (default: gpt-5-nano)
    - KAIRO_LLM_MODEL_HEAVY: Model name for heavy role (default: gpt-5-pro)
    - LLM_DISABLED: Set to "true" or "1" to disable real LLM calls
    - KAIRO_LLM_TIMEOUT_FAST: Timeout in seconds for fast calls (default: 8)
    - KAIRO_LLM_TIMEOUT_HEAVY: Timeout in seconds for heavy calls (default: 20)
    - KAIRO_LLM_MAX_TOKENS_FAST: Max output tokens for fast (default: 1024)
    - KAIRO_LLM_MAX_TOKENS_HEAVY: Max output tokens for heavy (default: 4096)
    - KAIRO_LLM_TEMP_FAST: Temperature for fast role (default: 0.0)
    - KAIRO_LLM_TEMP_HEAVY: Temperature for heavy role (default: 0.0)
    - KAIRO_LLM_TOP_P_FAST: Top-p for fast role (default: 1.0)
    - KAIRO_LLM_TOP_P_HEAVY: Top-p for heavy role (default: 1.0)
    - KAIRO_LLM_COST_FAST_USD_PER_1K: Cost per 1K tokens for fast (default: 0.01)
    - KAIRO_LLM_COST_HEAVY_USD_PER_1K: Cost per 1K tokens for heavy (default: 0.03)
    """

    # Model names (aligned with load_config_from_env defaults)
    # Valid GPT-5 models: gpt-5-nano (fast), gpt-5-pro (heavy)
    fast_model_name: str = field(default_factory=lambda: "gpt-5-nano")
    heavy_model_name: str = field(default_factory=lambda: "gpt-5-pro")

    # API key (may be None if LLM_DISABLED)
    api_key: str | None = None

    # Disable flag
    llm_disabled: bool = False

    # Timeouts (seconds)
    timeout_fast: float = 8.0
    timeout_heavy: float = 20.0

    # Max output tokens
    max_tokens_fast: int = 1024
    max_tokens_heavy: int = 4096

    # Sampling parameters (deterministic by default for eval reproducibility)
    temperature_fast: float = 0.0
    temperature_heavy: float = 0.0
    top_p_fast: float = 1.0
    top_p_heavy: float = 1.0

    # Cost estimation (USD per 1K tokens)
    cost_fast_usd_per_1k: float = 0.01
    cost_heavy_usd_per_1k: float = 0.03


def load_config_from_env() -> LLMConfig:
    """
    Load LLM configuration from environment variables.

    Returns sensible defaults if environment variables are not set,
    allowing tests to run without any configuration.
    """
    # Parse LLM_DISABLED as boolean
    disabled_str = os.getenv("LLM_DISABLED", "").lower().strip()
    llm_disabled = disabled_str in ("true", "1", "yes", "on")

    # Get API key (may be None)
    api_key = os.getenv("OPENAI_API_KEY")

    # Get model names with defaults (per spec: gpt-5-nano fast, gpt-5-pro heavy)
    # Valid GPT-5 models: gpt-5-nano, gpt-5-mini, gpt-5, gpt-5-pro
    fast_model = os.getenv("KAIRO_LLM_MODEL_FAST", "gpt-5-nano")
    heavy_model = os.getenv("KAIRO_LLM_MODEL_HEAVY", "gpt-5-pro")

    # Parse timeouts
    try:
        timeout_fast = float(os.getenv("KAIRO_LLM_TIMEOUT_FAST", "8"))
    except ValueError:
        timeout_fast = 8.0

    try:
        timeout_heavy = float(os.getenv("KAIRO_LLM_TIMEOUT_HEAVY", "20"))
    except ValueError:
        timeout_heavy = 20.0

    # Parse max tokens
    try:
        max_tokens_fast = int(os.getenv("KAIRO_LLM_MAX_TOKENS_FAST", "1024"))
    except ValueError:
        max_tokens_fast = 1024

    try:
        max_tokens_heavy = int(os.getenv("KAIRO_LLM_MAX_TOKENS_HEAVY", "4096"))
    except ValueError:
        max_tokens_heavy = 4096

    # Parse sampling parameters (deterministic defaults)
    try:
        temperature_fast = float(os.getenv("KAIRO_LLM_TEMP_FAST", "0.0"))
    except ValueError:
        temperature_fast = 0.0

    try:
        temperature_heavy = float(os.getenv("KAIRO_LLM_TEMP_HEAVY", "0.0"))
    except ValueError:
        temperature_heavy = 0.0

    try:
        top_p_fast = float(os.getenv("KAIRO_LLM_TOP_P_FAST", "1.0"))
    except ValueError:
        top_p_fast = 1.0

    try:
        top_p_heavy = float(os.getenv("KAIRO_LLM_TOP_P_HEAVY", "1.0"))
    except ValueError:
        top_p_heavy = 1.0

    # Parse cost parameters
    try:
        cost_fast = float(os.getenv("KAIRO_LLM_COST_FAST_USD_PER_1K", "0.01"))
    except ValueError:
        cost_fast = 0.01

    try:
        cost_heavy = float(os.getenv("KAIRO_LLM_COST_HEAVY_USD_PER_1K", "0.03"))
    except ValueError:
        cost_heavy = 0.03

    return LLMConfig(
        fast_model_name=fast_model,
        heavy_model_name=heavy_model,
        api_key=api_key,
        llm_disabled=llm_disabled,
        timeout_fast=timeout_fast,
        timeout_heavy=timeout_heavy,
        max_tokens_fast=max_tokens_fast,
        max_tokens_heavy=max_tokens_heavy,
        temperature_fast=temperature_fast,
        temperature_heavy=temperature_heavy,
        top_p_fast=top_p_fast,
        top_p_heavy=top_p_heavy,
        cost_fast_usd_per_1k=cost_fast,
        cost_heavy_usd_per_1k=cost_heavy,
    )


# =============================================================================
# RESPONSE MODEL
# =============================================================================


@dataclass
class LLMResponse:
    """
    Response from an LLM call.

    Contains the raw text output along with usage, timing, and cost metadata.
    """

    raw_text: str
    model: str
    usage_tokens_in: int
    usage_tokens_out: int
    latency_ms: int
    role: Role
    status: Status = "success"
    estimated_cost_usd: float | None = None


# =============================================================================
# STRUCTURED OUTPUT PARSING
# =============================================================================


def parse_structured_output(raw_text: str, target: type[T]) -> T:
    """
    Parse raw LLM output into a Pydantic model.

    Handles both:
    - Pure JSON
    - JSON fenced by markdown triple-backticks (```json ... ```)

    Args:
        raw_text: Raw text output from LLM
        target: Pydantic BaseModel class to parse into

    Returns:
        Parsed and validated Pydantic model instance

    Raises:
        StructuredOutputError: If JSON is invalid or validation fails
    """
    # Strip whitespace
    text = raw_text.strip()

    # Try to extract JSON from markdown code fence
    # Handles: ```json\n{...}\n``` and ```\n{...}\n```
    fence_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
    match = re.search(fence_pattern, text)
    if match:
        text = match.group(1).strip()

    # Try to parse as JSON
    try:
        # Use Pydantic v2's model_validate_json for efficient parsing
        return target.model_validate_json(text)
    except json.JSONDecodeError as e:
        raise StructuredOutputError(
            f"Invalid JSON in LLM output: {e}. Raw text: {raw_text[:200]}..."
        ) from e
    except ValidationError as e:
        # Include Pydantic error summary
        error_summary = "; ".join(
            f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}"
            for err in e.errors()
        )
        raise StructuredOutputError(
            f"Schema validation failed: {error_summary}. Raw text: {raw_text[:200]}..."
        ) from e


# =============================================================================
# LLM CLIENT
# =============================================================================


class LLMClient:
    """
    Single LLM client for all Kairo LLM usage.

    Per PR-map-and-standards §PR-7:
    - All LLM calls in the codebase must go through this client
    - No graph or module may call provider SDK directly
    - Supports LLM_DISABLED mode for tests and eval runs

    Usage:
        client = LLMClient()
        response = client.call(
            brand_id=brand_uuid,
            flow="F2_package",
            prompt="Generate a thesis for this opportunity",
            role="heavy",
            system_prompt="You are a content strategist...",
        )
    """

    def __init__(self, config: LLMConfig | None = None):
        """
        Initialize the LLM client.

        Args:
            config: Optional LLMConfig. If None, loads from environment.
        """
        self.config = config or load_config_from_env()

    def call(
        self,
        *,
        brand_id: "UUID",
        flow: str,
        prompt: str,
        role: Role = "fast",
        tools: Sequence[Mapping[str, Any]] | None = None,
        system_prompt: str | None = None,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        run_id: "UUID | None" = None,
        trigger_source: str = "api",
    ) -> LLMResponse:
        """
        Make an LLM call.

        All calls are logged for observability with run_id, brand_id, flow, etc.

        Args:
            brand_id: UUID of the brand (for observability)
            flow: Flow identifier (F1_today, F2_package, F3_learning)
            prompt: The user/main prompt
            role: "fast" or "heavy" - determines model and parameters
            tools: Optional list of tool definitions (for future use)
            system_prompt: Optional system prompt
            max_output_tokens: Override max output tokens (uses config default if None)
            temperature: Override temperature (uses config default for role if None)
            run_id: Optional run ID for correlation (auto-generated if None)
            trigger_source: Trigger source for observability (api, cron, eval, manual)

        Returns:
            LLMResponse with raw_text and metadata

        Raises:
            LLMCallError: If the LLM call fails (wraps all provider exceptions)
        """
        from uuid import uuid4

        # Generate run_id if not provided
        if run_id is None:
            run_id = uuid4()

        # Get model and parameters for role
        if role == "fast":
            model = self.config.fast_model_name
            timeout = self.config.timeout_fast
            default_max_tokens = self.config.max_tokens_fast
            default_temperature = self.config.temperature_fast
            top_p = self.config.top_p_fast
            cost_per_1k = self.config.cost_fast_usd_per_1k
        else:
            model = self.config.heavy_model_name
            timeout = self.config.timeout_heavy
            default_max_tokens = self.config.max_tokens_heavy
            default_temperature = self.config.temperature_heavy
            top_p = self.config.top_p_heavy
            cost_per_1k = self.config.cost_heavy_usd_per_1k

        actual_max_tokens = max_output_tokens or default_max_tokens
        actual_temperature = temperature if temperature is not None else default_temperature

        start_time = time.perf_counter()

        # Handle LLM_DISABLED mode
        if self.config.llm_disabled:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            tokens_in = len(prompt.split())  # Rough estimate
            # Get stub JSON based on flow - this must parse against the expected schema
            stub_text = _get_stub_json_for_flow(flow)
            tokens_out = len(stub_text.split())
            total_tokens = tokens_in + tokens_out
            estimated_cost = total_tokens / 1000.0 * cost_per_1k

            response = LLMResponse(
                raw_text=stub_text,
                model=model,
                usage_tokens_in=tokens_in,
                usage_tokens_out=tokens_out,
                latency_ms=latency_ms,
                role=role,
                status="disabled",
                estimated_cost_usd=estimated_cost,
            )

            self._log_call(
                run_id=run_id,
                brand_id=brand_id,
                flow=flow,
                trigger_source=trigger_source,
                model=model,
                role=role,
                latency_ms=latency_ms,
                tokens_in=response.usage_tokens_in,
                tokens_out=response.usage_tokens_out,
                status="disabled",
                estimated_cost_usd=estimated_cost,
            )

            return response

        # Make actual provider call
        try:
            result = self._call_provider(
                model=model,
                prompt=prompt,
                system_prompt=system_prompt,
                tools=tools,
                max_tokens=actual_max_tokens,
                temperature=actual_temperature,
                top_p=top_p,
                timeout=timeout,
            )

            latency_ms = int((time.perf_counter() - start_time) * 1000)
            tokens_in = result["usage"]["prompt_tokens"]
            tokens_out = result["usage"]["completion_tokens"]
            total_tokens = tokens_in + tokens_out
            estimated_cost = total_tokens / 1000.0 * cost_per_1k

            response = LLMResponse(
                raw_text=result["content"],
                model=model,
                usage_tokens_in=tokens_in,
                usage_tokens_out=tokens_out,
                latency_ms=latency_ms,
                role=role,
                status="success",
                estimated_cost_usd=estimated_cost,
            )

            self._log_call(
                run_id=run_id,
                brand_id=brand_id,
                flow=flow,
                trigger_source=trigger_source,
                model=model,
                role=role,
                latency_ms=latency_ms,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                status="success",
                estimated_cost_usd=estimated_cost,
            )

            return response

        except Exception as exc:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            error_summary = f"{exc.__class__.__name__}: {str(exc)[:100]}"

            self._log_call(
                run_id=run_id,
                brand_id=brand_id,
                flow=flow,
                trigger_source=trigger_source,
                model=model,
                role=role,
                latency_ms=latency_ms,
                tokens_in=0,
                tokens_out=0,
                status="failure",
                error_summary=error_summary,
            )

            # Wrap all provider exceptions in LLMCallError
            raise LLMCallError(
                f"LLM call failed: {exc}",
                original_error=exc,
            ) from exc

    def _call_provider(
        self,
        *,
        model: str,
        prompt: str,
        system_prompt: str | None,
        tools: Sequence[Mapping[str, Any]] | None,
        max_tokens: int,
        temperature: float,
        top_p: float,
        timeout: float,
    ) -> dict[str, Any]:
        """
        Internal method to call the LLM provider.

        Routes to either Responses API or Chat Completions API based on model.
        GPT-5.x models use Responses API; older models use Chat Completions.

        Tests should patch this method to avoid real HTTP calls.

        Args:
            model: Model name
            prompt: User prompt
            system_prompt: Optional system prompt
            tools: Optional tool definitions
            max_tokens: Max output tokens
            temperature: Sampling temperature
            top_p: Top-p sampling parameter
            timeout: Request timeout in seconds

        Returns:
            Dict with 'content' and 'usage' keys (normalized across both APIs)

        Raises:
            Exception: Any provider error (will be wrapped by caller)
        """
        # Import openai here to allow tests to run without it installed
        try:
            import openai
        except ImportError as e:
            raise LLMCallError(
                "OpenAI package not installed. Install with: pip install openai"
            ) from e

        # Check for API key
        if not self.config.api_key:
            raise LLMCallError(
                "OPENAI_API_KEY not set. Set the environment variable or use LLM_DISABLED=true for testing."
            )

        # Create client
        client = openai.OpenAI(
            api_key=self.config.api_key,
            timeout=timeout,
        )

        # Route based on model - GPT-5.x uses Responses API
        if _is_responses_api_model(model):
            return self._call_responses_api(
                client=client,
                model=model,
                prompt=prompt,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
            )
        else:
            return self._call_chat_completions_api(
                client=client,
                model=model,
                prompt=prompt,
                system_prompt=system_prompt,
                tools=tools,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
            )

    def _call_responses_api(
        self,
        *,
        client: Any,
        model: str,
        prompt: str,
        system_prompt: str | None,
        max_tokens: int,
        temperature: float,
        top_p: float,
    ) -> dict[str, Any]:
        """
        Call OpenAI Responses API (for GPT-5.x models).

        The Responses API uses different parameter names:
        - 'input' instead of 'messages'
        - 'instructions' instead of system message
        - 'max_output_tokens' instead of 'max_tokens'
        - Response has 'output_text' and 'usage.input_tokens/output_tokens'

        Args:
            client: OpenAI client instance
            model: Model name (must be gpt-5.x)
            prompt: User prompt
            system_prompt: Optional system instructions
            max_tokens: Max output tokens
            temperature: Sampling temperature
            top_p: Top-p sampling parameter

        Returns:
            Dict with 'content' and 'usage' keys (normalized format)
        """
        # Build request kwargs for Responses API
        request_kwargs: dict[str, Any] = {
            "model": model,
            "input": prompt,
            "max_output_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
        }

        # Add system instructions if provided
        if system_prompt:
            request_kwargs["instructions"] = system_prompt

        # Make the Responses API call
        response = client.responses.create(**request_kwargs)

        # Extract content and usage (Responses API format)
        content = response.output_text or ""
        usage = {
            "prompt_tokens": response.usage.input_tokens if response.usage else 0,
            "completion_tokens": response.usage.output_tokens if response.usage else 0,
        }

        return {"content": content, "usage": usage}

    def _call_chat_completions_api(
        self,
        *,
        client: Any,
        model: str,
        prompt: str,
        system_prompt: str | None,
        tools: Sequence[Mapping[str, Any]] | None,
        max_tokens: int,
        temperature: float,
        top_p: float,
    ) -> dict[str, Any]:
        """
        Call OpenAI Chat Completions API (for older models like gpt-4o).

        Args:
            client: OpenAI client instance
            model: Model name
            prompt: User prompt
            system_prompt: Optional system prompt
            tools: Optional tool definitions
            max_tokens: Max output tokens
            temperature: Sampling temperature
            top_p: Top-p sampling parameter

        Returns:
            Dict with 'content' and 'usage' keys
        """
        # Build messages
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # Build request kwargs
        request_kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
        }

        # Add tools if provided (for future use)
        if tools:
            request_kwargs["tools"] = list(tools)

        response = client.chat.completions.create(**request_kwargs)

        # Extract content and usage
        content = response.choices[0].message.content or ""
        usage = {
            "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
            "completion_tokens": (
                response.usage.completion_tokens if response.usage else 0
            ),
        }

        return {"content": content, "usage": usage}

    def _log_call(
        self,
        *,
        run_id: "UUID",
        brand_id: "UUID",
        flow: str,
        trigger_source: str,
        model: str,
        role: Role,
        latency_ms: int,
        tokens_in: int,
        tokens_out: int,
        status: Status,
        error_summary: str | None = None,
        estimated_cost_usd: float | None = None,
    ) -> None:
        """
        Log an LLM call for observability.

        Logs are structured with all required fields per PR-6/PR-7.
        Also writes to observability sink (PR-11) if enabled.

        Required fields:
        - run_id
        - brand_id
        - flow
        - trigger_source
        - model
        - role
        - latency_ms
        - tokens_in
        - tokens_out
        - status
        - estimated_cost_usd (when available)
        - error_summary (on failure)
        """
        log_data = {
            "run_id": str(run_id),
            "brand_id": str(brand_id),
            "flow": flow,
            "trigger_source": trigger_source,
            "model": model,
            "role": role,
            "latency_ms": latency_ms,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "status": status,
        }

        if estimated_cost_usd is not None:
            log_data["estimated_cost_usd"] = estimated_cost_usd

        if error_summary:
            log_data["error_summary"] = error_summary

        if status == "failure":
            logger.error("LLM call failed", extra=log_data)
        else:
            logger.info("LLM call completed", extra=log_data)

        # Also write to observability sink (PR-11)
        obs = _get_obs_module()
        if obs:
            obs.log_llm_call(
                run_id=run_id,
                brand_id=brand_id,
                flow=flow,
                model=model,
                role=role,
                latency_ms=latency_ms,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                status=status,
                estimated_cost_usd=estimated_cost_usd,
                error_summary=error_summary,
            )


# =============================================================================
# MODULE-LEVEL CONVENIENCE
# =============================================================================

# Default client instance (lazy-loaded)
_default_client: LLMClient | None = None


def get_default_client() -> LLMClient:
    """
    Get the default LLM client instance.

    Creates the client on first call using environment configuration.
    """
    global _default_client
    if _default_client is None:
        _default_client = LLMClient()
    return _default_client


def reset_default_client() -> None:
    """
    Reset the default client (useful for tests).
    """
    global _default_client
    _default_client = None
