"""Tests for API adapter and hybrid runner."""

import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from task_delegator.api_adapter import (
    ClaudeAPIAdapter,
    HybridClaudeRunner,
    RateLimitAwareOrchestrator,
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

    def test_ensure_client_success(self):
        """Test _ensure_client successful path."""
        adapter = ClaudeAPIAdapter(api_key="test_key")
        adapter._client = None

        # Test the normal path - should just log info
        with patch("task_delegator.api_adapter.logger") as mock_logger:
            adapter._ensure_client()
            mock_logger.info.assert_called_once_with("API client initialized")

    def test_ensure_client_initialization_error(self):
        """Test _ensure_client handling initialization error."""
        adapter = ClaudeAPIAdapter(api_key="test_key")
        adapter._client = None

        # Mock an error during initialization
        with (
            patch("task_delegator.api_adapter.logger") as mock_logger,
            pytest.raises(Exception, match="Init failed"),
        ):
            # Force an exception by mocking the logger.info to raise
            mock_logger.info.side_effect = Exception("Init failed")
            adapter._ensure_client()

            # Check that error was logged
            mock_logger.error.assert_called_once()

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
        with (
            patch.dict(os.environ, {"CLAUDE_USE_API": "true"}),
            patch("task_delegator.api_adapter.USE_API_MODE", True),
        ):
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
        with (
            patch.dict(os.environ, {"CLAUDE_USE_API": "true"}),
            patch("task_delegator.api_adapter.USE_API_MODE", True),
        ):
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

    def test_get_stats_api_mode(self):
        """Test getting runtime statistics in API mode."""
        with (
            patch.dict(os.environ, {"CLAUDE_USE_API": "true"}),
            patch("task_delegator.api_adapter.USE_API_MODE", True),
        ):
            runner = HybridClaudeRunner(api_key="test_key")
            stats = runner.get_stats()

            assert stats["mode"] == "api"
            assert "rate_limiter" in stats
            assert "consecutive_429s" in stats["rate_limiter"]
            assert "current_delay" in stats["rate_limiter"]


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

    @pytest.mark.asyncio
    async def test_api_client_initialization_error(self):
        """Test handling of API client initialization error."""
        adapter = ClaudeAPIAdapter(api_key="test_key")

        # Mock the _ensure_client to raise an exception
        with patch.object(adapter, "_ensure_client", side_effect=Exception("Init failed")):
            result = await adapter.run_claude_api("Test prompt")

            assert result["success"] is False
            assert "Init failed" in result["error"]

    def test_extract_retry_after(self):
        """Test extracting retry after value."""
        adapter = ClaudeAPIAdapter(api_key="test_key")

        # Currently returns default value
        retry_after = adapter._extract_retry_after(Exception("Rate limited"))
        assert retry_after == 30.0

    @pytest.mark.asyncio
    async def test_api_adapter_other_error(self):
        """Test handling of non-rate-limit errors."""
        adapter = ClaudeAPIAdapter(api_key="test_key")

        # Mock sleep to raise a different error
        with patch("asyncio.sleep", side_effect=Exception("Network error")):
            result = await adapter.run_claude_api("Test")

            assert result["success"] is False
            assert "Network error" in result["error"]
            assert result.get("rate_limited") is None


class TestRateLimitAwareOrchestrator:
    """Test the rate limit aware orchestrator."""

    @pytest.mark.asyncio
    async def test_adaptive_worker_loop_basic(self):
        """Test basic adaptive worker loop functionality."""
        # Create mock base orchestrator
        mock_base = MagicMock()
        mock_base.task_queue = AsyncMock()
        mock_base.registry = MagicMock()
        mock_base.registry.get_active_accounts.return_value = ["account1", "account2"]

        orchestrator = RateLimitAwareOrchestrator(mock_base, use_api=True)

        # Create a mock task
        mock_task = MagicMock()
        mock_task.prompt = "Test prompt"

        # Set up the queue to return task then None (sentinel)
        mock_base.task_queue.get.side_effect = [
            (1, mock_task),
            (None, None),  # Sentinel to exit loop
        ]

        # Mock the runner
        with patch("task_delegator.api_adapter.configure_claude_runner") as mock_configure:
            mock_runner = AsyncMock()
            mock_configure.return_value = mock_runner
            mock_runner.run_claude.return_value = {"success": True, "completion": "Done"}

            # Run the worker loop
            await orchestrator.adaptive_worker_loop("worker_1", Path("/tmp"))

            # Verify task was processed
            mock_runner.run_claude.assert_called_once_with(
                prompt="Test prompt", config_dir=Path("/tmp")
            )

    @pytest.mark.asyncio
    async def test_adaptive_worker_loop_rate_limit(self):
        """Test worker loop handling rate limits."""
        mock_base = MagicMock()
        mock_base.task_queue = AsyncMock()
        mock_base.registry = MagicMock()
        mock_base.registry.get_active_accounts.return_value = ["account1"]

        orchestrator = RateLimitAwareOrchestrator(mock_base, use_api=True)

        # Create a mock task
        mock_task = MagicMock()
        mock_task.prompt = "Test prompt"
        mock_task.priority_key.return_value = 1

        # First get returns task, second returns None
        mock_base.task_queue.get.side_effect = [
            (1, mock_task),
            (None, None),
        ]

        with patch("task_delegator.api_adapter.configure_claude_runner") as mock_configure:
            mock_runner = AsyncMock()
            mock_configure.return_value = mock_runner
            # Return rate limited response
            mock_runner.run_claude.return_value = {
                "success": False,
                "rate_limited": True,
                "retry_after": 15,
            }

            await orchestrator.adaptive_worker_loop("worker_1", Path("/tmp"))

            # Check that task was put back in queue
            mock_base.task_queue.put.assert_called_once_with((1, mock_task))
            # Worker delay gets cleared after use, so it won't be present anymore

    @pytest.mark.asyncio
    async def test_adaptive_worker_loop_timeout(self):
        """Test worker loop handling queue timeout."""
        mock_base = MagicMock()
        mock_base.task_queue = AsyncMock()

        orchestrator = RateLimitAwareOrchestrator(mock_base)

        # Make get timeout, then return None
        mock_base.task_queue.get.side_effect = [
            asyncio.TimeoutError,
            (None, None),
        ]

        with patch("task_delegator.api_adapter.configure_claude_runner") as mock_configure:
            mock_runner = AsyncMock()
            mock_configure.return_value = mock_runner

            # Should handle timeout gracefully
            await orchestrator.adaptive_worker_loop("worker_1", Path("/tmp"))

    @pytest.mark.asyncio
    async def test_adaptive_worker_loop_with_delay(self):
        """Test worker loop with existing delay."""
        mock_base = MagicMock()
        mock_base.task_queue = AsyncMock()

        orchestrator = RateLimitAwareOrchestrator(mock_base)
        orchestrator.worker_delays["worker_1"] = 0.1  # Small delay for testing

        mock_base.task_queue.get.side_effect = [(None, None)]

        with patch("asyncio.sleep") as mock_sleep:
            await orchestrator.adaptive_worker_loop("worker_1", Path("/tmp"))

            # Verify delay was applied
            mock_sleep.assert_called_once_with(0.1)
            assert "worker_1" not in orchestrator.worker_delays

    @pytest.mark.asyncio
    async def test_adaptive_worker_loop_error_handling(self):
        """Test error handling in worker loop."""
        mock_base = MagicMock()
        mock_base.task_queue = AsyncMock()

        orchestrator = RateLimitAwareOrchestrator(mock_base)

        # First get raises exception, second returns None
        mock_base.task_queue.get.side_effect = [
            Exception("Queue error"),
            (None, None),
        ]

        with patch("task_delegator.api_adapter.logger") as mock_logger:
            await orchestrator.adaptive_worker_loop("worker_1", Path("/tmp"))

            # Verify error was logged
            mock_logger.error.assert_called_once()
