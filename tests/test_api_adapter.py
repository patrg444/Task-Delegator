"""Tests for API adapter and hybrid runner."""

import asyncio
import os
from unittest.mock import AsyncMock, patch

import pytest

from task_delegator.api_adapter import (
    ClaudeAPIAdapter,
    HybridClaudeRunner,
    RateLimiter,
    configure_claude_runner,
)


class TestRateLimiter:
    """Test rate limiting functionality."""

    @pytest.mark.asyncio
    async def test_no_delay_initially(self):
        """Test no delay on first request."""
        limiter = RateLimiter()

        start = asyncio.get_event_loop().time()
        await limiter.wait_if_needed()
        elapsed = asyncio.get_event_loop().time() - start

        assert elapsed < 0.1  # Should be immediate

    @pytest.mark.asyncio
    async def test_delay_after_rate_limit(self):
        """Test delay after rate limit hit."""
        limiter = RateLimiter(initial_delay=0.1)
        limiter.record_rate_limit()

        start = asyncio.get_event_loop().time()
        await limiter.wait_if_needed()
        elapsed = asyncio.get_event_loop().time() - start

        assert elapsed >= 0.1  # Should wait at least initial delay

    def test_exponential_backoff(self):
        """Test exponential backoff calculation."""
        limiter = RateLimiter(initial_delay=1.0, max_delay=60.0)

        # First rate limit
        limiter.record_rate_limit()
        assert limiter.consecutive_429s == 1

        # Second rate limit
        limiter.record_rate_limit()
        assert limiter.consecutive_429s == 2

        # Reset on success
        limiter.record_success()
        assert limiter.consecutive_429s == 0

    def test_max_delay_cap(self):
        """Test that delay is capped at max_delay."""
        limiter = RateLimiter(initial_delay=1.0, max_delay=10.0)

        # Many consecutive rate limits
        for _ in range(10):
            limiter.record_rate_limit()

        # Delay should be capped
        assert limiter.current_delay <= 10.0


class TestClaudeAPIAdapter:
    """Test Claude API adapter."""

    def test_init_with_api_key(self):
        """Test initialization with API key."""
        adapter = ClaudeAPIAdapter(api_key="test_key_123")
        assert adapter.api_key == "test_key_123"

    def test_init_from_env(self):
        """Test initialization from environment."""
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "env_key_456"}):
            adapter = ClaudeAPIAdapter()
            assert adapter.api_key == "env_key_456"

    @pytest.mark.asyncio
    async def test_no_api_key_error(self):
        """Test error when no API key provided."""
        adapter = ClaudeAPIAdapter(api_key=None)

        result = await adapter.run_claude_api("Test prompt")

        assert result["success"] is False
        assert "No API key" in result["error"]

    @pytest.mark.asyncio
    async def test_simulated_success(self):
        """Test simulated successful API call."""
        adapter = ClaudeAPIAdapter(api_key="test_key")

        result = await adapter.run_claude_api("Calculate 2+2")

        assert result["success"] is True
        assert "completion" in result
        assert "usage" in result

    @pytest.mark.asyncio
    async def test_rate_limit_handling(self):
        """Test rate limit detection and handling."""
        adapter = ClaudeAPIAdapter(api_key="test_key")

        # Mock the sleep in run_claude_api to raise rate limit error
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            # Make sleep raise a rate limit error
            mock_sleep.side_effect = Exception("429 rate_limit_error")

            result = await adapter.run_claude_api("Test")

            assert result["success"] is False
            assert result.get("rate_limited") is True
            assert "retry_after" in result


class TestHybridClaudeRunner:
    """Test hybrid Claude runner."""

    def test_init_api_mode(self):
        """Test initialization in API mode."""
        with patch.dict(os.environ, {"CLAUDE_USE_API": "true"}), patch("task_delegator.api_adapter.USE_API_MODE", True):
            runner = HybridClaudeRunner(api_key="test_key")
            assert runner.mode == "api"
            assert runner.api_adapter is not None

    def test_init_cli_mode(self):
        """Test initialization in CLI mode."""
        with patch.dict(os.environ, {"CLAUDE_USE_API": "false"}):
            runner = HybridClaudeRunner()
            assert runner.mode == "cli"
            assert runner.api_adapter is None

    @pytest.mark.asyncio
    async def test_run_claude_api_mode(self):
        """Test running in API mode."""
        with patch.dict(os.environ, {"CLAUDE_USE_API": "true"}), patch("task_delegator.api_adapter.USE_API_MODE", True):
            runner = HybridClaudeRunner(api_key="test_key")

            result = await runner.run_claude("Test prompt")

            assert result["success"] is True
            assert "[API Mode]" in result["completion"]

    @pytest.mark.asyncio
    @patch("task_delegator.secure_runner.SecureClaudeRunner.run_claude_secure")
    async def test_run_claude_cli_mode(self, mock_cli, tmp_path):
        """Test running in CLI mode."""
        with patch.dict(os.environ, {"CLAUDE_USE_API": "false"}):
            runner = HybridClaudeRunner()

            # Mock CLI response
            mock_cli.return_value = {"success": True, "completion": "CLI response"}

            result = await runner.run_claude("Test prompt", config_dir=tmp_path)

            assert result["success"] is True
            assert result["completion"] == "CLI response"
            mock_cli.assert_called_once()

    @pytest.mark.asyncio
    async def test_cli_mode_requires_config_dir(self):
        """Test CLI mode requires config_dir."""
        with patch.dict(os.environ, {"CLAUDE_USE_API": "false"}):
            runner = HybridClaudeRunner()

            result = await runner.run_claude("Test prompt")

            assert result["success"] is False
            assert "config_dir required" in result["error"]

    def test_get_stats(self):
        """Test getting runtime statistics."""
        runner = HybridClaudeRunner()
        stats = runner.get_stats()

        assert "mode" in stats
        assert "timestamp" in stats


class TestConfigureClaudeRunner:
    """Test runner configuration."""

    def test_configure_default(self):
        """Test default configuration."""
        with patch.dict(os.environ, {}, clear=True):
            runner = configure_claude_runner()
            assert runner.mode == "cli"

    def test_configure_with_api_key(self):
        """Test configuration with API key."""
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test_key"}):
            configure_claude_runner(prefer_api=True)
            assert os.environ.get("CLAUDE_USE_API") == "true"

    def test_configure_prefer_api_no_key(self):
        """Test preferring API without key falls back to CLI."""
        with patch.dict(os.environ, {}, clear=True):
            runner = configure_claude_runner(prefer_api=True)
            assert runner.mode == "cli"  # Falls back to CLI
