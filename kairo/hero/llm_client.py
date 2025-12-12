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

# =============================================================================
# TYPE DEFINITIONS
# =============================================================================

Role = Literal["fast", "heavy"]
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


@dataclass(frozen=True)
class LLMConfig:
    """
    LLM client configuration.

    Reads from environment variables with sensible defaults for tests.

    Environment Variables:
    - OPENAI_API_KEY: API key for OpenAI (required for real calls)
    - KAIRO_LLM_MODEL_FAST: Model name for fast role (default: gpt-4.1-mini)
    - KAIRO_LLM_MODEL_HEAVY: Model name for heavy role (default: gpt-5.1-thinking)
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

    # Model names
    fast_model_name: str = field(default_factory=lambda: "gpt-4.1-mini")
    heavy_model_name: str = field(default_factory=lambda: "gpt-5.1-thinking")

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

    # Get model names with defaults
    fast_model = os.getenv("KAIRO_LLM_MODEL_FAST", "gpt-4.1-mini")
    heavy_model = os.getenv("KAIRO_LLM_MODEL_HEAVY", "gpt-5.1-thinking")

    # If no API key set (test environment), use test model names
    # unless explicit model names were provided via env
    if not api_key and not llm_disabled:
        if not os.getenv("KAIRO_LLM_MODEL_FAST"):
            fast_model = "test-fast-model"
        if not os.getenv("KAIRO_LLM_MODEL_HEAVY"):
            heavy_model = "test-heavy-model"

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
            temperature = self.config.temperature_fast
            top_p = self.config.top_p_fast
            cost_per_1k = self.config.cost_fast_usd_per_1k
        else:
            model = self.config.heavy_model_name
            timeout = self.config.timeout_heavy
            default_max_tokens = self.config.max_tokens_heavy
            temperature = self.config.temperature_heavy
            top_p = self.config.top_p_heavy
            cost_per_1k = self.config.cost_heavy_usd_per_1k

        actual_max_tokens = max_output_tokens or default_max_tokens

        start_time = time.perf_counter()

        # Handle LLM_DISABLED mode
        if self.config.llm_disabled:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            tokens_in = len(prompt.split())  # Rough estimate
            tokens_out = 10
            total_tokens = tokens_in + tokens_out
            estimated_cost = total_tokens / 1000.0 * cost_per_1k

            response = LLMResponse(
                raw_text=f"[LLM_DISABLED STUB] prompt={prompt[:100]}...",
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
                temperature=temperature,
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

        This method houses the actual provider SDK call (OpenAI).
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
            Dict with 'content' and 'usage' keys

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

        # Build messages
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # Create client and make request
        client = openai.OpenAI(
            api_key=self.config.api_key,
            timeout=timeout,
        )

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
