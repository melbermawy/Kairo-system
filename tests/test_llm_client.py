"""
LLM Client tests for PR-7.

Tests verify:
- Configuration loading from environment variables
- LLMClient.call behavior with mocked provider
- LLM_DISABLED mode (no real HTTP calls)
- Structured output parsing
- Error handling and logging
- Deterministic sampling defaults (temperature=0.0, top_p=1.0)
- Cost estimation

All tests use fake provider behavior - no real HTTP calls.
"""

import logging
from unittest.mock import patch
from uuid import uuid4

import pytest
from pydantic import BaseModel, Field

from kairo.hero.llm_client import (
    LLMCallError,
    LLMClient,
    LLMConfig,
    LLMResponse,
    StructuredOutputError,
    _is_responses_api_model,
    load_config_from_env,
    parse_structured_output,
    reset_default_client,
)


# =============================================================================
# TEST MODELS FOR STRUCTURED OUTPUT
# =============================================================================


class SimpleTestModel(BaseModel):
    """Simple test model for structured output parsing."""

    foo: str
    value: int = 0


class ComplexTestModel(BaseModel):
    """Complex test model with nested fields."""

    title: str
    items: list[str] = Field(default_factory=list)
    score: float = Field(ge=0, le=100)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture(autouse=True)
def reset_client():
    """Reset the default client before each test."""
    reset_default_client()
    yield
    reset_default_client()


@pytest.fixture
def mock_log_handler():
    """Fixture that captures logs from kairo.llm logger."""

    class MockHandler(logging.Handler):
        def __init__(self):
            super().__init__()
            self.records: list[logging.LogRecord] = []

        def emit(self, record):
            self.records.append(record)

        def clear(self):
            self.records.clear()

    handler = MockHandler()
    handler.setLevel(logging.INFO)

    llm_logger = logging.getLogger("kairo.llm")
    llm_logger.addHandler(handler)
    llm_logger.setLevel(logging.INFO)

    yield handler

    llm_logger.removeHandler(handler)
    handler.clear()


@pytest.fixture
def sample_brand_id():
    """Sample brand ID for tests."""
    return uuid4()


@pytest.fixture
def sample_run_id():
    """Sample run ID for tests."""
    return uuid4()


# =============================================================================
# CONFIGURATION TESTS
# =============================================================================


class TestLLMConfig:
    """Tests for LLMConfig and load_config_from_env."""

    def test_default_config_values(self):
        """Config has sensible defaults."""
        config = LLMConfig()

        assert config.fast_model_name == "gpt-5-nano"
        assert config.heavy_model_name == "gpt-5-pro"
        assert config.llm_disabled is False
        assert config.timeout_fast == 8.0
        assert config.timeout_heavy == 20.0
        assert config.max_tokens_fast == 1024
        assert config.max_tokens_heavy == 4096

    def test_default_deterministic_sampling(self):
        """Config has deterministic sampling defaults (temp=0.0, top_p=1.0)."""
        config = LLMConfig()

        assert config.temperature_fast == 0.0
        assert config.temperature_heavy == 0.0
        assert config.top_p_fast == 1.0
        assert config.top_p_heavy == 1.0

    def test_default_cost_rates(self):
        """Config has default cost rates."""
        config = LLMConfig()

        assert config.cost_fast_usd_per_1k == 0.01
        assert config.cost_heavy_usd_per_1k == 0.03

    def test_config_is_frozen(self):
        """Config is immutable."""
        config = LLMConfig()

        with pytest.raises(AttributeError):
            config.fast_model_name = "different-model"  # type: ignore

    def test_load_config_no_env_vars(self, monkeypatch):
        """Load config with no env vars set uses spec defaults."""
        # Clear relevant env vars
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("KAIRO_LLM_MODEL_FAST", raising=False)
        monkeypatch.delenv("KAIRO_LLM_MODEL_HEAVY", raising=False)
        monkeypatch.delenv("LLM_DISABLED", raising=False)

        config = load_config_from_env()

        # Per spec: use default model names regardless of API key
        assert config.fast_model_name == "gpt-5-nano"
        assert config.heavy_model_name == "gpt-5-pro"
        assert config.api_key is None
        assert config.llm_disabled is False

    def test_load_config_deterministic_defaults(self, monkeypatch):
        """Load config from env has deterministic sampling by default."""
        monkeypatch.delenv("KAIRO_LLM_TEMP_FAST", raising=False)
        monkeypatch.delenv("KAIRO_LLM_TEMP_HEAVY", raising=False)
        monkeypatch.delenv("KAIRO_LLM_TOP_P_FAST", raising=False)
        monkeypatch.delenv("KAIRO_LLM_TOP_P_HEAVY", raising=False)

        config = load_config_from_env()

        assert config.temperature_fast == 0.0
        assert config.temperature_heavy == 0.0
        assert config.top_p_fast == 1.0
        assert config.top_p_heavy == 1.0

    def test_load_config_with_model_names(self, monkeypatch):
        """Load config respects custom model names."""
        monkeypatch.setenv("KAIRO_LLM_MODEL_FAST", "custom-fast-model")
        monkeypatch.setenv("KAIRO_LLM_MODEL_HEAVY", "custom-heavy-model")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

        config = load_config_from_env()

        assert config.fast_model_name == "custom-fast-model"
        assert config.heavy_model_name == "custom-heavy-model"

    def test_load_config_with_custom_sampling_params(self, monkeypatch):
        """Load config respects custom sampling parameters."""
        monkeypatch.setenv("KAIRO_LLM_TEMP_FAST", "0.5")
        monkeypatch.setenv("KAIRO_LLM_TEMP_HEAVY", "0.3")
        monkeypatch.setenv("KAIRO_LLM_TOP_P_FAST", "0.9")
        monkeypatch.setenv("KAIRO_LLM_TOP_P_HEAVY", "0.95")

        config = load_config_from_env()

        assert config.temperature_fast == 0.5
        assert config.temperature_heavy == 0.3
        assert config.top_p_fast == 0.9
        assert config.top_p_heavy == 0.95

    def test_load_config_with_custom_cost_rates(self, monkeypatch):
        """Load config respects custom cost rates."""
        monkeypatch.setenv("KAIRO_LLM_COST_FAST_USD_PER_1K", "0.005")
        monkeypatch.setenv("KAIRO_LLM_COST_HEAVY_USD_PER_1K", "0.06")

        config = load_config_from_env()

        assert config.cost_fast_usd_per_1k == 0.005
        assert config.cost_heavy_usd_per_1k == 0.06

    def test_load_config_llm_disabled_true(self, monkeypatch):
        """LLM_DISABLED=true is correctly parsed."""
        monkeypatch.setenv("LLM_DISABLED", "true")

        config = load_config_from_env()

        assert config.llm_disabled is True

    def test_load_config_llm_disabled_one(self, monkeypatch):
        """LLM_DISABLED=1 is correctly parsed."""
        monkeypatch.setenv("LLM_DISABLED", "1")

        config = load_config_from_env()

        assert config.llm_disabled is True

    def test_load_config_llm_disabled_yes(self, monkeypatch):
        """LLM_DISABLED=yes is correctly parsed."""
        monkeypatch.setenv("LLM_DISABLED", "yes")

        config = load_config_from_env()

        assert config.llm_disabled is True

    def test_load_config_llm_disabled_false(self, monkeypatch):
        """LLM_DISABLED=false is correctly parsed as False."""
        monkeypatch.setenv("LLM_DISABLED", "false")

        config = load_config_from_env()

        assert config.llm_disabled is False

    def test_load_config_llm_disabled_empty(self, monkeypatch):
        """Empty LLM_DISABLED is correctly parsed as False."""
        monkeypatch.setenv("LLM_DISABLED", "")

        config = load_config_from_env()

        assert config.llm_disabled is False

    def test_load_config_custom_timeouts(self, monkeypatch):
        """Custom timeouts are parsed correctly."""
        monkeypatch.setenv("KAIRO_LLM_TIMEOUT_FAST", "15")
        monkeypatch.setenv("KAIRO_LLM_TIMEOUT_HEAVY", "60")

        config = load_config_from_env()

        assert config.timeout_fast == 15.0
        assert config.timeout_heavy == 60.0

    def test_load_config_custom_max_tokens(self, monkeypatch):
        """Custom max tokens are parsed correctly."""
        monkeypatch.setenv("KAIRO_LLM_MAX_TOKENS_FAST", "512")
        monkeypatch.setenv("KAIRO_LLM_MAX_TOKENS_HEAVY", "8192")

        config = load_config_from_env()

        assert config.max_tokens_fast == 512
        assert config.max_tokens_heavy == 8192

    def test_load_config_invalid_timeout_uses_default(self, monkeypatch):
        """Invalid timeout value falls back to default."""
        monkeypatch.setenv("KAIRO_LLM_TIMEOUT_FAST", "not-a-number")

        config = load_config_from_env()

        assert config.timeout_fast == 8.0

    def test_load_config_invalid_max_tokens_uses_default(self, monkeypatch):
        """Invalid max tokens value falls back to default."""
        monkeypatch.setenv("KAIRO_LLM_MAX_TOKENS_FAST", "not-a-number")

        config = load_config_from_env()

        assert config.max_tokens_fast == 1024

    def test_load_config_invalid_sampling_uses_default(self, monkeypatch):
        """Invalid sampling parameters fall back to defaults."""
        monkeypatch.setenv("KAIRO_LLM_TEMP_FAST", "not-a-number")
        monkeypatch.setenv("KAIRO_LLM_TOP_P_FAST", "invalid")

        config = load_config_from_env()

        assert config.temperature_fast == 0.0
        assert config.top_p_fast == 1.0


# =============================================================================
# LLM CLIENT CALL TESTS (FAKE PROVIDER)
# =============================================================================


class TestLLMClientCall:
    """Tests for LLMClient.call with mocked provider."""

    def test_call_returns_llm_response(self, sample_brand_id, sample_run_id):
        """call() returns a valid LLMResponse."""
        config = LLMConfig(
            api_key="test-key",
            fast_model_name="test-fast",
            heavy_model_name="test-heavy",
        )
        client = LLMClient(config=config)

        # Mock the provider call
        with patch.object(client, "_call_provider") as mock_provider:
            mock_provider.return_value = {
                "content": "Hello, world!",
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            }

            response = client.call(
                brand_id=sample_brand_id,
                flow="F1_today",
                prompt="Say hello",
                role="fast",
                run_id=sample_run_id,
            )

        assert isinstance(response, LLMResponse)
        assert response.raw_text == "Hello, world!"
        assert response.model == "test-fast"
        assert response.usage_tokens_in == 10
        assert response.usage_tokens_out == 20
        assert response.role == "fast"
        assert response.status == "success"
        assert response.latency_ms >= 0

    def test_call_fast_role_uses_fast_model(self, sample_brand_id):
        """call() with role='fast' uses fast model."""
        config = LLMConfig(
            api_key="test-key",
            fast_model_name="my-fast-model",
            heavy_model_name="my-heavy-model",
        )
        client = LLMClient(config=config)

        with patch.object(client, "_call_provider") as mock_provider:
            mock_provider.return_value = {
                "content": "response",
                "usage": {"prompt_tokens": 5, "completion_tokens": 5},
            }

            response = client.call(
                brand_id=sample_brand_id,
                flow="F1_today",
                prompt="test",
                role="fast",
            )

        assert response.model == "my-fast-model"
        mock_provider.assert_called_once()
        call_kwargs = mock_provider.call_args.kwargs
        assert call_kwargs["model"] == "my-fast-model"

    def test_call_heavy_role_uses_heavy_model(self, sample_brand_id):
        """call() with role='heavy' uses heavy model."""
        config = LLMConfig(
            api_key="test-key",
            fast_model_name="my-fast-model",
            heavy_model_name="my-heavy-model",
        )
        client = LLMClient(config=config)

        with patch.object(client, "_call_provider") as mock_provider:
            mock_provider.return_value = {
                "content": "response",
                "usage": {"prompt_tokens": 5, "completion_tokens": 5},
            }

            response = client.call(
                brand_id=sample_brand_id,
                flow="F2_package",
                prompt="test",
                role="heavy",
            )

        assert response.model == "my-heavy-model"
        mock_provider.assert_called_once()
        call_kwargs = mock_provider.call_args.kwargs
        assert call_kwargs["model"] == "my-heavy-model"

    def test_call_uses_deterministic_sampling_defaults(self, sample_brand_id):
        """call() uses deterministic sampling defaults (temp=0.0, top_p=1.0)."""
        config = LLMConfig(api_key="test-key")
        client = LLMClient(config=config)

        with patch.object(client, "_call_provider") as mock_provider:
            mock_provider.return_value = {
                "content": "response",
                "usage": {"prompt_tokens": 5, "completion_tokens": 5},
            }

            client.call(
                brand_id=sample_brand_id,
                flow="F1_today",
                prompt="test",
                role="fast",
            )

        call_kwargs = mock_provider.call_args.kwargs
        assert call_kwargs["temperature"] == 0.0
        assert call_kwargs["top_p"] == 1.0

    def test_call_with_system_prompt(self, sample_brand_id):
        """call() passes system_prompt to provider."""
        config = LLMConfig(api_key="test-key")
        client = LLMClient(config=config)

        with patch.object(client, "_call_provider") as mock_provider:
            mock_provider.return_value = {
                "content": "response",
                "usage": {"prompt_tokens": 5, "completion_tokens": 5},
            }

            client.call(
                brand_id=sample_brand_id,
                flow="F1_today",
                prompt="user prompt",
                system_prompt="You are a helpful assistant",
            )

        call_kwargs = mock_provider.call_args.kwargs
        assert call_kwargs["system_prompt"] == "You are a helpful assistant"

    def test_call_with_max_output_tokens_override(self, sample_brand_id):
        """call() respects max_output_tokens override."""
        config = LLMConfig(api_key="test-key", max_tokens_fast=1024)
        client = LLMClient(config=config)

        with patch.object(client, "_call_provider") as mock_provider:
            mock_provider.return_value = {
                "content": "response",
                "usage": {"prompt_tokens": 5, "completion_tokens": 5},
            }

            client.call(
                brand_id=sample_brand_id,
                flow="F1_today",
                prompt="test",
                max_output_tokens=500,
            )

        call_kwargs = mock_provider.call_args.kwargs
        assert call_kwargs["max_tokens"] == 500

    def test_call_logs_success_with_all_fields(
        self, sample_brand_id, sample_run_id, mock_log_handler
    ):
        """call() logs successful calls with all required fields."""
        config = LLMConfig(api_key="test-key", fast_model_name="test-model")
        client = LLMClient(config=config)

        with patch.object(client, "_call_provider") as mock_provider:
            mock_provider.return_value = {
                "content": "response",
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            }

            client.call(
                brand_id=sample_brand_id,
                flow="F1_today",
                prompt="test",
                run_id=sample_run_id,
                trigger_source="api",
            )

        assert len(mock_log_handler.records) == 1
        record = mock_log_handler.records[0]

        # Verify all required fields are present
        assert record.run_id == str(sample_run_id)
        assert record.brand_id == str(sample_brand_id)
        assert record.flow == "F1_today"
        assert record.trigger_source == "api"
        assert record.model == "test-model"
        assert record.role == "fast"
        assert record.status == "success"
        assert record.tokens_in == 10
        assert record.tokens_out == 20
        assert hasattr(record, "latency_ms")
        assert hasattr(record, "estimated_cost_usd")

    def test_call_generates_run_id_if_not_provided(
        self, sample_brand_id, mock_log_handler
    ):
        """call() generates run_id if not provided."""
        config = LLMConfig(api_key="test-key")
        client = LLMClient(config=config)

        with patch.object(client, "_call_provider") as mock_provider:
            mock_provider.return_value = {
                "content": "response",
                "usage": {"prompt_tokens": 5, "completion_tokens": 5},
            }

            client.call(
                brand_id=sample_brand_id,
                flow="F1_today",
                prompt="test",
                # No run_id provided
            )

        assert len(mock_log_handler.records) == 1
        record = mock_log_handler.records[0]
        # Should have a valid UUID string
        assert record.run_id is not None
        assert len(record.run_id) == 36  # UUID string length


# =============================================================================
# COST ESTIMATION TESTS
# =============================================================================


class TestCostEstimation:
    """Tests for cost estimation in LLMClient."""

    def test_response_includes_estimated_cost(self, sample_brand_id):
        """LLMResponse includes estimated_cost_usd."""
        config = LLMConfig(
            api_key="test-key",
            cost_fast_usd_per_1k=0.01,
        )
        client = LLMClient(config=config)

        with patch.object(client, "_call_provider") as mock_provider:
            mock_provider.return_value = {
                "content": "response",
                "usage": {"prompt_tokens": 100, "completion_tokens": 200},
            }

            response = client.call(
                brand_id=sample_brand_id,
                flow="F1_today",
                prompt="test",
                role="fast",
            )

        # total_tokens = 100 + 200 = 300
        # cost = 300 / 1000 * 0.01 = 0.003
        assert response.estimated_cost_usd is not None
        assert response.estimated_cost_usd == pytest.approx(0.003)

    def test_cost_uses_heavy_rate_for_heavy_role(self, sample_brand_id):
        """Cost estimation uses heavy rate for heavy role."""
        config = LLMConfig(
            api_key="test-key",
            cost_fast_usd_per_1k=0.01,
            cost_heavy_usd_per_1k=0.05,
        )
        client = LLMClient(config=config)

        with patch.object(client, "_call_provider") as mock_provider:
            mock_provider.return_value = {
                "content": "response",
                "usage": {"prompt_tokens": 500, "completion_tokens": 500},
            }

            response = client.call(
                brand_id=sample_brand_id,
                flow="F2_package",
                prompt="test",
                role="heavy",
            )

        # total_tokens = 500 + 500 = 1000
        # cost = 1000 / 1000 * 0.05 = 0.05
        assert response.estimated_cost_usd == pytest.approx(0.05)

    def test_cost_logged_with_call(self, sample_brand_id, mock_log_handler):
        """estimated_cost_usd is included in logs."""
        config = LLMConfig(
            api_key="test-key",
            cost_fast_usd_per_1k=0.02,
        )
        client = LLMClient(config=config)

        with patch.object(client, "_call_provider") as mock_provider:
            mock_provider.return_value = {
                "content": "response",
                "usage": {"prompt_tokens": 50, "completion_tokens": 50},
            }

            client.call(
                brand_id=sample_brand_id,
                flow="F1_today",
                prompt="test",
            )

        record = mock_log_handler.records[0]
        # total_tokens = 100, cost = 100 / 1000 * 0.02 = 0.002
        assert record.estimated_cost_usd == pytest.approx(0.002)

    def test_cost_with_custom_rates_from_env(self, sample_brand_id, monkeypatch):
        """Cost estimation uses rates from environment variables."""
        # Must explicitly disable LLM_DISABLED to use mocked provider
        monkeypatch.delenv("LLM_DISABLED", raising=False)
        monkeypatch.setenv("KAIRO_LLM_COST_FAST_USD_PER_1K", "0.005")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

        client = LLMClient()

        with patch.object(client, "_call_provider") as mock_provider:
            mock_provider.return_value = {
                "content": "response",
                "usage": {"prompt_tokens": 1000, "completion_tokens": 1000},
            }

            response = client.call(
                brand_id=sample_brand_id,
                flow="F1_today",
                prompt="test",
                role="fast",
            )

        # total_tokens = 2000, cost = 2000 / 1000 * 0.005 = 0.01
        assert response.estimated_cost_usd == pytest.approx(0.01)


# =============================================================================
# LLM_DISABLED BEHAVIOR TESTS
# =============================================================================


class TestLLMDisabled:
    """Tests for LLM_DISABLED behavior."""

    def test_disabled_returns_stub_response(self, sample_brand_id):
        """LLM_DISABLED returns deterministic stub response with valid JSON."""
        config = LLMConfig(llm_disabled=True, fast_model_name="disabled-model")
        client = LLMClient(config=config)

        # Patch _call_provider to raise if called
        with patch.object(client, "_call_provider") as mock_provider:
            mock_provider.side_effect = AssertionError(
                "_call_provider should not be called when disabled"
            )

            response = client.call(
                brand_id=sample_brand_id,
                flow="F1_today",
                prompt="Generate opportunities",
            )

        # Provider should not have been called
        mock_provider.assert_not_called()

        # Response should be a stub with valid JSON
        assert response.status == "disabled"
        # Stub returns valid JSON that can be parsed
        import json
        parsed = json.loads(response.raw_text)
        assert isinstance(parsed, dict)
        assert response.model == "disabled-model"

    def test_disabled_returns_flow_specific_stub(self, sample_brand_id):
        """LLM_DISABLED returns flow-specific stub JSON that matches expected schema."""
        config = LLMConfig(llm_disabled=True)
        client = LLMClient(config=config)

        # Test synthesis flow
        synthesis_response = client.call(
            brand_id=sample_brand_id,
            flow="F1_opportunities_synthesis",
            prompt="Generate opportunities",
        )
        import json
        parsed = json.loads(synthesis_response.raw_text)
        assert "opportunities" in parsed
        assert len(parsed["opportunities"]) >= 6  # min_length per schema

        # Test scoring flow - uses minimal schema now
        scoring_response = client.call(
            brand_id=sample_brand_id,
            flow="F1_opportunities_scoring",
            prompt="Score opportunities",
        )
        parsed = json.loads(scoring_response.raw_text)
        assert "scores" in parsed  # New minimal schema uses "scores" array
        assert all("score" in item and "idx" in item for item in parsed["scores"])

        # Test package flow
        package_response = client.call(
            brand_id=sample_brand_id,
            flow="F2_package",
            prompt="Create package",
        )
        parsed = json.loads(package_response.raw_text)
        assert "package" in parsed
        assert "thesis" in parsed["package"]

        # Test variants flow
        variants_response = client.call(
            brand_id=sample_brand_id,
            flow="F2_variants",
            prompt="Generate variants",
        )
        parsed = json.loads(variants_response.raw_text)
        assert "variants" in parsed
        assert len(parsed["variants"]) >= 1

    def test_disabled_includes_cost_estimate(self, sample_brand_id):
        """LLM_DISABLED stub response includes cost estimate."""
        config = LLMConfig(llm_disabled=True, cost_fast_usd_per_1k=0.01)
        client = LLMClient(config=config)

        response = client.call(
            brand_id=sample_brand_id,
            flow="F1_today",
            prompt="test prompt here",
        )

        assert response.estimated_cost_usd is not None
        assert response.estimated_cost_usd > 0

    def test_disabled_logs_with_status_disabled(
        self, sample_brand_id, mock_log_handler
    ):
        """LLM_DISABLED logs with status='disabled'."""
        config = LLMConfig(llm_disabled=True)
        client = LLMClient(config=config)

        with patch.object(client, "_call_provider"):
            client.call(
                brand_id=sample_brand_id,
                flow="F2_package",
                prompt="test",
            )

        assert len(mock_log_handler.records) == 1
        record = mock_log_handler.records[0]
        assert record.status == "disabled"

    def test_disabled_env_var(self, sample_brand_id, monkeypatch):
        """LLM_DISABLED env var disables real calls."""
        monkeypatch.setenv("LLM_DISABLED", "true")

        client = LLMClient()  # Will load config from env

        with patch.object(client, "_call_provider") as mock_provider:
            mock_provider.side_effect = AssertionError("Should not be called")

            response = client.call(
                brand_id=sample_brand_id,
                flow="F1_today",
                prompt="test",
            )

        assert response.status == "disabled"
        mock_provider.assert_not_called()


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================


class TestLLMClientErrors:
    """Tests for error handling in LLMClient."""

    def test_provider_error_raises_llm_call_error(self, sample_brand_id):
        """Provider error is wrapped in LLMCallError."""
        config = LLMConfig(api_key="test-key")
        client = LLMClient(config=config)

        with patch.object(client, "_call_provider") as mock_provider:
            mock_provider.side_effect = RuntimeError("Network error")

            with pytest.raises(LLMCallError) as exc_info:
                client.call(
                    brand_id=sample_brand_id,
                    flow="F1_today",
                    prompt="test",
                )

        assert "Network error" in str(exc_info.value)
        assert exc_info.value.original_error is not None

    def test_provider_error_logs_failure_with_error_summary(
        self, sample_brand_id, sample_run_id, mock_log_handler
    ):
        """Provider error is logged with status='failure' and error_summary."""
        config = LLMConfig(api_key="test-key")
        client = LLMClient(config=config)

        with patch.object(client, "_call_provider") as mock_provider:
            mock_provider.side_effect = RuntimeError("API timeout")

            with pytest.raises(LLMCallError):
                client.call(
                    brand_id=sample_brand_id,
                    flow="F1_today",
                    prompt="test",
                    run_id=sample_run_id,
                )

        assert len(mock_log_handler.records) == 1
        record = mock_log_handler.records[0]
        assert record.status == "failure"
        assert hasattr(record, "error_summary")
        assert "RuntimeError" in record.error_summary
        assert "API timeout" in record.error_summary

    def test_custom_provider_exception_wrapped(self, sample_brand_id, mock_log_handler):
        """Custom provider exceptions are wrapped in LLMCallError."""

        class FakeProviderError(Exception):
            """Simulates a provider-specific exception."""

            pass

        config = LLMConfig(api_key="test-key")
        client = LLMClient(config=config)

        with patch.object(client, "_call_provider") as mock_provider:
            mock_provider.side_effect = FakeProviderError("Rate limit exceeded")

            with pytest.raises(LLMCallError) as exc_info:
                client.call(
                    brand_id=sample_brand_id,
                    flow="F1_today",
                    prompt="test",
                )

        # Should wrap the custom exception
        assert isinstance(exc_info.value, LLMCallError)
        assert exc_info.value.original_error is not None
        assert isinstance(exc_info.value.original_error, FakeProviderError)

        # Log should include error type
        record = mock_log_handler.records[0]
        assert record.status == "failure"
        assert "FakeProviderError" in record.error_summary

    def test_failure_log_includes_all_context_fields(
        self, sample_brand_id, sample_run_id, mock_log_handler
    ):
        """Failure logs include all context fields."""
        config = LLMConfig(api_key="test-key", fast_model_name="test-model")
        client = LLMClient(config=config)

        with patch.object(client, "_call_provider") as mock_provider:
            mock_provider.side_effect = ValueError("Invalid prompt")

            with pytest.raises(LLMCallError):
                client.call(
                    brand_id=sample_brand_id,
                    flow="F2_package",
                    prompt="test",
                    run_id=sample_run_id,
                    trigger_source="cron",
                )

        record = mock_log_handler.records[0]

        # All context fields should be present even on failure
        assert record.run_id == str(sample_run_id)
        assert record.brand_id == str(sample_brand_id)
        assert record.flow == "F2_package"
        assert record.trigger_source == "cron"
        assert record.model == "test-model"
        assert record.role == "fast"
        assert record.status == "failure"
        assert hasattr(record, "latency_ms")


# =============================================================================
# STRUCTURED OUTPUT PARSING TESTS
# =============================================================================


class TestStructuredOutputParsing:
    """Tests for parse_structured_output helper."""

    def test_parse_valid_json(self):
        """Valid JSON is parsed correctly."""
        raw = '{"foo": "bar", "value": 42}'

        result = parse_structured_output(raw, SimpleTestModel)

        assert isinstance(result, SimpleTestModel)
        assert result.foo == "bar"
        assert result.value == 42

    def test_parse_json_with_whitespace(self):
        """JSON with leading/trailing whitespace is parsed."""
        raw = '  \n  {"foo": "baz", "value": 10}  \n  '

        result = parse_structured_output(raw, SimpleTestModel)

        assert result.foo == "baz"
        assert result.value == 10

    def test_parse_fenced_json(self):
        """JSON in markdown code fence is extracted and parsed."""
        raw = '```json\n{"foo": "fenced", "value": 99}\n```'

        result = parse_structured_output(raw, SimpleTestModel)

        assert result.foo == "fenced"
        assert result.value == 99

    def test_parse_fenced_json_without_language(self):
        """JSON in bare code fence (no 'json' label) is parsed."""
        raw = '```\n{"foo": "bare", "value": 1}\n```'

        result = parse_structured_output(raw, SimpleTestModel)

        assert result.foo == "bare"
        assert result.value == 1

    def test_parse_fenced_json_with_surrounding_text(self):
        """JSON in code fence with surrounding text is extracted."""
        raw = 'Here is the result:\n\n```json\n{"foo": "extracted", "value": 5}\n```\n\nThat is all.'

        result = parse_structured_output(raw, SimpleTestModel)

        assert result.foo == "extracted"
        assert result.value == 5

    def test_parse_complex_model(self):
        """Complex nested model is parsed correctly."""
        raw = '{"title": "Test", "items": ["a", "b", "c"], "score": 85.5}'

        result = parse_structured_output(raw, ComplexTestModel)

        assert result.title == "Test"
        assert result.items == ["a", "b", "c"]
        assert result.score == 85.5

    def test_parse_invalid_json_raises_error(self):
        """Invalid JSON raises StructuredOutputError."""
        raw = "not valid json at all"

        with pytest.raises(StructuredOutputError) as exc_info:
            parse_structured_output(raw, SimpleTestModel)

        assert "Invalid JSON" in str(exc_info.value)

    def test_parse_incomplete_json_raises_error(self):
        """Incomplete JSON raises StructuredOutputError."""
        raw = '{"foo": "incomplete'

        with pytest.raises(StructuredOutputError) as exc_info:
            parse_structured_output(raw, SimpleTestModel)

        assert "Invalid JSON" in str(exc_info.value)

    def test_parse_missing_required_field_raises_error(self):
        """Missing required field raises StructuredOutputError."""
        raw = '{"value": 10}'  # Missing 'foo' which is required

        with pytest.raises(StructuredOutputError) as exc_info:
            parse_structured_output(raw, SimpleTestModel)

        assert "Schema validation failed" in str(exc_info.value)
        assert "foo" in str(exc_info.value)

    def test_parse_invalid_field_type_raises_error(self):
        """Wrong field type raises StructuredOutputError."""
        raw = '{"foo": "ok", "value": "not-an-int"}'

        with pytest.raises(StructuredOutputError) as exc_info:
            parse_structured_output(raw, SimpleTestModel)

        assert "Schema validation failed" in str(exc_info.value)

    def test_parse_score_out_of_range_raises_error(self):
        """Score outside valid range raises StructuredOutputError."""
        raw = '{"title": "Test", "score": 150}'  # score must be <= 100

        with pytest.raises(StructuredOutputError) as exc_info:
            parse_structured_output(raw, ComplexTestModel)

        assert "Schema validation failed" in str(exc_info.value)

    def test_parse_default_values_applied(self):
        """Missing optional fields get default values."""
        raw = '{"foo": "minimal"}'  # 'value' has default of 0

        result = parse_structured_output(raw, SimpleTestModel)

        assert result.foo == "minimal"
        assert result.value == 0  # Default


# =============================================================================
# LLM RESPONSE TESTS
# =============================================================================


class TestLLMResponse:
    """Tests for LLMResponse dataclass."""

    def test_response_fields(self):
        """LLMResponse has all expected fields."""
        response = LLMResponse(
            raw_text="Hello",
            model="gpt-5-nano",
            usage_tokens_in=10,
            usage_tokens_out=20,
            latency_ms=150,
            role="fast",
            status="success",
            estimated_cost_usd=0.0003,
        )

        assert response.raw_text == "Hello"
        assert response.model == "gpt-5-nano"
        assert response.usage_tokens_in == 10
        assert response.usage_tokens_out == 20
        assert response.latency_ms == 150
        assert response.role == "fast"
        assert response.status == "success"
        assert response.estimated_cost_usd == 0.0003

    def test_response_default_status(self):
        """LLMResponse has default status of 'success'."""
        response = LLMResponse(
            raw_text="Hi",
            model="test",
            usage_tokens_in=5,
            usage_tokens_out=5,
            latency_ms=50,
            role="heavy",
        )

        assert response.status == "success"

    def test_response_default_cost_is_none(self):
        """LLMResponse has default estimated_cost_usd of None."""
        response = LLMResponse(
            raw_text="Hi",
            model="test",
            usage_tokens_in=5,
            usage_tokens_out=5,
            latency_ms=50,
            role="fast",
        )

        assert response.estimated_cost_usd is None


# =============================================================================
# INTEGRATION TESTS
# =============================================================================


class TestLLMClientIntegration:
    """Integration tests for LLMClient."""

    def test_full_flow_with_structured_output(self, sample_brand_id):
        """Full flow: call LLM and parse structured output."""
        config = LLMConfig(api_key="test-key")
        client = LLMClient(config=config)

        # Mock provider to return valid JSON
        with patch.object(client, "_call_provider") as mock_provider:
            mock_provider.return_value = {
                "content": '{"foo": "generated", "value": 123}',
                "usage": {"prompt_tokens": 50, "completion_tokens": 30},
            }

            response = client.call(
                brand_id=sample_brand_id,
                flow="F2_package",
                prompt="Generate a test object",
                role="heavy",
            )

        # Parse the response
        parsed = parse_structured_output(response.raw_text, SimpleTestModel)

        assert parsed.foo == "generated"
        assert parsed.value == 123

    def test_no_api_key_no_env_works_with_disabled(self, sample_brand_id, monkeypatch):
        """Without API key but with LLM_DISABLED, client works."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("LLM_DISABLED", "true")

        client = LLMClient()

        response = client.call(
            brand_id=sample_brand_id,
            flow="F1_today",
            prompt="test",
        )

        assert response.status == "disabled"

    def test_model_names_defaults(self, monkeypatch):
        """Default model names per spec: gpt-5-nano (fast), gpt-5-pro (heavy)."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("KAIRO_LLM_MODEL_FAST", raising=False)
        monkeypatch.delenv("KAIRO_LLM_MODEL_HEAVY", raising=False)

        config = load_config_from_env()

        # Per spec: default model names regardless of API key presence
        assert config.fast_model_name == "gpt-5-nano"
        assert config.heavy_model_name == "gpt-5-pro"

    def test_env_overrides_model_names_even_without_api_key(self, monkeypatch):
        """Explicit model names override test defaults even without API key."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("KAIRO_LLM_MODEL_FAST", "explicit-fast")
        monkeypatch.setenv("KAIRO_LLM_MODEL_HEAVY", "explicit-heavy")

        config = load_config_from_env()

        assert config.fast_model_name == "explicit-fast"
        assert config.heavy_model_name == "explicit-heavy"


# =============================================================================
# API ROUTING TESTS (Responses API vs Chat Completions)
# =============================================================================


class TestAPIRouting:
    """Tests for API routing based on model name (PR-7.1).

    GPT-5.x models use Responses API; older models use Chat Completions API.
    """

    def test_is_responses_api_model_gpt5_nano(self):
        """gpt-5-nano should use Responses API."""
        assert _is_responses_api_model("gpt-5-nano") is True

    def test_is_responses_api_model_gpt5_pro(self):
        """gpt-5-pro should use Responses API."""
        assert _is_responses_api_model("gpt-5-pro") is True

    def test_is_responses_api_model_gpt5_mini(self):
        """gpt-5-mini should use Responses API."""
        assert _is_responses_api_model("gpt-5-mini") is True

    def test_is_responses_api_model_gpt5_base(self):
        """gpt-5 (base) should use Responses API."""
        assert _is_responses_api_model("gpt-5") is True

    def test_is_responses_api_model_gpt51(self):
        """gpt-5.1 should use Responses API."""
        assert _is_responses_api_model("gpt-5.1") is True

    def test_is_responses_api_model_gpt51_mini(self):
        """gpt-5.1-mini should use Responses API."""
        assert _is_responses_api_model("gpt-5.1-mini") is True

    def test_is_responses_api_model_gpt4o_false(self):
        """gpt-4o should NOT use Responses API (uses Chat Completions)."""
        assert _is_responses_api_model("gpt-4o") is False

    def test_is_responses_api_model_gpt4o_mini_false(self):
        """gpt-4o-mini should NOT use Responses API."""
        assert _is_responses_api_model("gpt-4o-mini") is False

    def test_is_responses_api_model_gpt35_turbo_false(self):
        """gpt-3.5-turbo should NOT use Responses API."""
        assert _is_responses_api_model("gpt-3.5-turbo") is False

    def test_is_responses_api_model_case_insensitive(self):
        """Model name detection should be case-insensitive."""
        assert _is_responses_api_model("GPT-5-NANO") is True
        assert _is_responses_api_model("Gpt-5-Pro") is True

    def test_gpt5_model_routes_to_responses_api(self, sample_brand_id):
        """GPT-5 model should route to _call_responses_api."""
        config = LLMConfig(
            api_key="test-key",
            fast_model_name="gpt-5-nano",
        )
        client = LLMClient(config=config)

        with patch.object(client, "_call_responses_api") as mock_responses, \
             patch.object(client, "_call_chat_completions_api") as mock_chat:
            mock_responses.return_value = {
                "content": "response",
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            }

            client.call(
                brand_id=sample_brand_id,
                flow="F1_today",
                prompt="test",
                role="fast",
            )

        mock_responses.assert_called_once()
        mock_chat.assert_not_called()

    def test_gpt4_model_routes_to_chat_completions(self, sample_brand_id):
        """GPT-4 model should route to _call_chat_completions_api."""
        config = LLMConfig(
            api_key="test-key",
            fast_model_name="gpt-4o-mini",
        )
        client = LLMClient(config=config)

        with patch.object(client, "_call_responses_api") as mock_responses, \
             patch.object(client, "_call_chat_completions_api") as mock_chat:
            mock_chat.return_value = {
                "content": "response",
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            }

            client.call(
                brand_id=sample_brand_id,
                flow="F1_today",
                prompt="test",
                role="fast",
            )

        mock_chat.assert_called_once()
        mock_responses.assert_not_called()

    def test_responses_api_uses_correct_params(self, sample_brand_id):
        """Responses API call uses correct parameter names (input, instructions, max_output_tokens)."""
        config = LLMConfig(
            api_key="test-key",
            fast_model_name="gpt-5-nano",
            max_tokens_fast=512,
            temperature_fast=0.1,
            top_p_fast=0.9,
        )
        client = LLMClient(config=config)

        with patch.object(client, "_call_responses_api") as mock_responses:
            mock_responses.return_value = {
                "content": "response",
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            }

            client.call(
                brand_id=sample_brand_id,
                flow="F1_today",
                prompt="user prompt",
                system_prompt="system instructions",
                role="fast",
            )

        call_kwargs = mock_responses.call_args.kwargs
        assert call_kwargs["model"] == "gpt-5-nano"
        assert call_kwargs["prompt"] == "user prompt"
        assert call_kwargs["system_prompt"] == "system instructions"
        assert call_kwargs["max_tokens"] == 512
        assert call_kwargs["temperature"] == 0.1
        assert call_kwargs["top_p"] == 0.9

    def test_chat_completions_not_used_for_gpt5_pro(self, sample_brand_id):
        """Regression: Chat Completions API must NOT be used for gpt-5-pro."""
        config = LLMConfig(
            api_key="test-key",
            heavy_model_name="gpt-5-pro",
        )
        client = LLMClient(config=config)

        with patch.object(client, "_call_responses_api") as mock_responses, \
             patch.object(client, "_call_chat_completions_api") as mock_chat:
            mock_responses.return_value = {
                "content": "response",
                "usage": {"prompt_tokens": 50, "completion_tokens": 100},
            }

            client.call(
                brand_id=sample_brand_id,
                flow="F2_package",
                prompt="test",
                role="heavy",
            )

        # Chat completions must NOT be called for gpt-5-pro
        mock_chat.assert_not_called()
        # Responses API must be called
        mock_responses.assert_called_once()
        # Verify model passed correctly
        call_kwargs = mock_responses.call_args.kwargs
        assert call_kwargs["model"] == "gpt-5-pro"
