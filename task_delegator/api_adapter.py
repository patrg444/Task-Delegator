"""HTTP API adapter for Claude (alternative to CLI)."""

import asyncio
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Feature flag to enable API mode
USE_API_MODE = os.environ.get("CLAUDE_USE_API", "false").lower() == "true"


class RateLimiter:
    """Simple rate limiter with exponential backoff."""

    def __init__(self, initial_delay: float = 1.0, max_delay: float = 60.0):
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.current_delay = initial_delay
        self.last_request = 0.0
        self.consecutive_429s = 0

    async def wait_if_needed(self):
        """Wait if we're rate limited."""
        if self.consecutive_429s > 0:
            delay = min(self.current_delay * (2**self.consecutive_429s), self.max_delay)
            logger.warning(f"Rate limited, waiting {delay:.1f}s")
            await asyncio.sleep(delay)

    def record_success(self):
        """Record successful request."""
        self.consecutive_429s = 0
        self.current_delay = self.initial_delay
        self.last_request = time.time()

    def record_rate_limit(self, retry_after: float | None = None):
        """Record rate limit hit."""
        self.consecutive_429s += 1
        if retry_after:
            self.current_delay = retry_after
        logger.warning(f"Rate limit hit #{self.consecutive_429s}")


class ClaudeAPIAdapter:
    """
    Adapter for using Claude via HTTP API instead of CLI.

    Note: This is a template implementation. Actual implementation
    would require the anthropic Python SDK.
    """

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.rate_limiter = RateLimiter()
        self._client = None

        if not self.api_key:
            logger.warning("No API key found. API mode will not work.")

    def _ensure_client(self):
        """Ensure API client is initialized."""
        if self._client is None and self.api_key:
            try:
                # In real implementation:
                # from anthropic import AsyncAnthropic
                # self._client = AsyncAnthropic(api_key=self.api_key)
                logger.info("API client initialized")
            except Exception as e:
                logger.error(f"Failed to initialize API client: {e}")
                raise

    async def run_claude_api(
        self, prompt: str, max_tokens: int = 4096, temperature: float = 0.7, timeout: float = 300
    ) -> dict[str, Any]:
        """
        Run Claude via API.

        Returns:
            Dict with same structure as CLI runner for compatibility
        """
        if not self.api_key:
            return {"success": False, "error": "No API key configured"}

        # Wait for rate limiter
        await self.rate_limiter.wait_if_needed()

        try:
            self._ensure_client()

            # Simulated API call
            # In real implementation:
            # response = await self._client.messages.create(
            #     model="claude-3-opus-20240229",
            #     max_tokens=max_tokens,
            #     temperature=temperature,
            #     messages=[{"role": "user", "content": prompt}]
            # )

            # Simulate response
            await asyncio.sleep(0.5)  # Simulate network delay

            # Record success
            self.rate_limiter.record_success()

            return {
                "success": True,
                "completion": f"[API Mode] Simulated response to: {prompt[:50]}...",
                "usage": {"input_tokens": len(prompt.split()), "output_tokens": 100},
            }

        except Exception as e:
            # Check if it's a rate limit error
            if "rate_limit" in str(e).lower() or "429" in str(e):
                retry_after = self._extract_retry_after(e)
                self.rate_limiter.record_rate_limit(retry_after)

                return {
                    "success": False,
                    "error": "Rate limited",
                    "retry_after": retry_after,
                    "rate_limited": True,
                }

            # Other errors
            logger.error(f"API error: {e}")
            return {"success": False, "error": str(e)}

    def _extract_retry_after(self, error: Exception) -> float | None:
        """Extract retry-after value from rate limit error."""
        # In real implementation, parse the error response
        # For now, return a default
        return 30.0


class HybridClaudeRunner:
    """
    Hybrid runner that can use either CLI or API based on configuration.
    """

    def __init__(self, api_key: str | None = None):
        self.api_adapter = ClaudeAPIAdapter(api_key) if USE_API_MODE else None
        self.cli_runner = None  # Lazy import to avoid circular dependency
        self.mode = "api" if USE_API_MODE and api_key else "cli"
        logger.info(f"HybridClaudeRunner initialized in {self.mode} mode")

    async def run_claude(
        self, prompt: str, config_dir: Path | None = None, timeout: float = 300, **kwargs
    ) -> dict[str, Any]:
        """
        Run Claude using the configured method (API or CLI).

        This provides a unified interface regardless of backend.
        """
        if self.mode == "api":
            return await self.api_adapter.run_claude_api(prompt=prompt, timeout=timeout, **kwargs)
        else:
            # Use CLI runner
            if self.cli_runner is None:
                from .secure_runner import SecureClaudeRunner

                self.cli_runner = SecureClaudeRunner()

            if config_dir is None:
                return {"success": False, "error": "config_dir required for CLI mode"}

            return await self.cli_runner.run_claude_secure(
                prompt=prompt, config_dir=config_dir, timeout=timeout
            )

    def get_stats(self) -> dict[str, Any]:
        """Get runtime statistics."""
        stats = {"mode": self.mode, "timestamp": datetime.now().isoformat()}

        if self.mode == "api" and self.api_adapter:
            stats["rate_limiter"] = {
                "consecutive_429s": self.api_adapter.rate_limiter.consecutive_429s,
                "current_delay": self.api_adapter.rate_limiter.current_delay,
            }

        return stats


# Example configuration for switching modes
def configure_claude_runner(prefer_api: bool = False) -> HybridClaudeRunner:
    """
    Configure Claude runner based on environment and preferences.

    Args:
        prefer_api: Whether to prefer API mode if available

    Returns:
        Configured HybridClaudeRunner
    """
    # Check for API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")

    # Override mode if requested
    if prefer_api and api_key:
        os.environ["CLAUDE_USE_API"] = "true"

    runner = HybridClaudeRunner(api_key=api_key)

    logger.info(f"Claude runner configured: mode={runner.mode}")

    return runner


# Rate limit aware orchestrator extension
class RateLimitAwareOrchestrator:
    """
    Extended orchestrator that handles rate limits intelligently.
    """

    def __init__(self, base_orchestrator, use_api: bool = False):
        self.base = base_orchestrator
        self.use_api = use_api
        self.worker_delays: dict[str, float] = {}

    async def adaptive_worker_loop(self, worker_id: str, config_dir: Path):
        """Worker loop with adaptive rate limit handling."""

        # Create hybrid runner for this worker
        runner = configure_claude_runner(prefer_api=self.use_api)

        while True:
            try:
                # Check if we need to delay this worker
                if worker_id in self.worker_delays:
                    delay = self.worker_delays[worker_id]
                    logger.info(f"[{worker_id}] Delaying {delay}s due to rate limit")
                    await asyncio.sleep(delay)
                    del self.worker_delays[worker_id]

                # Get task (with timeout to check for delays)
                try:
                    _, task = await asyncio.wait_for(self.base.task_queue.get(), timeout=5.0)
                except asyncio.TimeoutError:
                    continue

                if task is None:  # Sentinel
                    break

                # Execute task
                result = await runner.run_claude(prompt=task.prompt, config_dir=config_dir)

                # Handle rate limiting
                if result.get("rate_limited"):
                    retry_after = result.get("retry_after", 30)
                    self.worker_delays[worker_id] = retry_after

                    # Put task back in queue
                    await self.base.task_queue.put((task.priority_key(), task))

                    # Reduce worker count if many are rate limited
                    if len(self.worker_delays) > len(self.base.registry.get_active_accounts()) / 2:
                        logger.warning("Many workers rate limited, consider reducing concurrency")

            except Exception as e:
                logger.error(f"[{worker_id}] Error in adaptive loop: {e}")

            finally:
                self.base.task_queue.task_done()
