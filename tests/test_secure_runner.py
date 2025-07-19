"""Tests for secure command execution."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from task_delegator.secure_runner import PolicyEnforcer, SecureClaudeRunner


class TestSecureClaudeRunner:
    """Test suite for SecureClaudeRunner."""

    def test_validate_prompt(self):
        """Test prompt validation and sanitization."""
        runner = SecureClaudeRunner()

        # Normal prompt
        prompt = "Calculate 2+2"
        result = runner.validate_prompt(prompt)
        assert result == prompt

        # Prompt with null bytes
        prompt_with_null = "Calculate\x00 2+2"
        result = runner.validate_prompt(prompt_with_null)
        assert result == "Calculate 2+2"
        assert "\x00" not in result

        # Very long prompt
        long_prompt = "a" * 60000
        result = runner.validate_prompt(long_prompt)
        assert len(result) == 50000

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_run_claude_secure_success(self, mock_subprocess):
        """Test successful secure command execution."""
        # Mock subprocess
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (b'{"completion": "4"}', b"")
        mock_subprocess.return_value = mock_proc

        runner = SecureClaudeRunner()
        result = await runner.run_claude_secure(
            prompt="Calculate 2+2", config_dir=Path("/test/config"), timeout=30
        )

        assert result["success"] is True
        assert result["completion"] == "4"

        # Verify subprocess was called correctly
        mock_subprocess.assert_called_once()
        call_args = mock_subprocess.call_args
        assert call_args[0] == ("claude", "ask", "--json")
        assert call_args[1]["stdin"] == asyncio.subprocess.PIPE
        assert call_args[1]["env"]["CLAUDE_CONFIG_DIR"] == "/test/config"

        # Verify prompt was sent via stdin
        mock_proc.communicate.assert_called_once_with(input=b"Calculate 2+2")

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_run_claude_secure_failure(self, mock_subprocess):
        """Test handling of command failure."""
        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate.return_value = (b"", b"Error: Authentication required")
        mock_subprocess.return_value = mock_proc

        runner = SecureClaudeRunner()
        result = await runner.run_claude_secure(
            prompt="Test prompt", config_dir=Path("/test/config")
        )

        assert result["success"] is False
        assert "Authentication required" in result["error"]
        assert result["returncode"] == 1

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_run_claude_secure_timeout(self, mock_subprocess):
        """Test handling of command timeout."""
        mock_proc = AsyncMock()
        mock_proc.returncode = None  # Still running
        mock_proc.communicate.side_effect = asyncio.TimeoutError()
        mock_proc.terminate = MagicMock()
        mock_proc.wait = AsyncMock()
        mock_subprocess.return_value = mock_proc

        runner = SecureClaudeRunner()
        result = await runner.run_claude_secure(
            prompt="Test prompt", config_dir=Path("/test/config"), timeout=1
        )

        assert result["success"] is False
        assert "timed out" in result["error"]
        assert result.get("timeout") is True

        # Verify process was terminated
        mock_proc.terminate.assert_called_once()
        mock_proc.wait.assert_called_once()

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_run_claude_secure_invalid_json(self, mock_subprocess):
        """Test handling of invalid JSON response."""
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (b"Not valid JSON", b"")
        mock_subprocess.return_value = mock_proc

        runner = SecureClaudeRunner()
        result = await runner.run_claude_secure(
            prompt="Test prompt", config_dir=Path("/test/config"), json_output=True
        )

        assert result["success"] is False
        assert "Invalid JSON" in result["error"]
        assert result["raw_output"] == "Not valid JSON"

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_shell_injection_prevention(self, mock_subprocess):
        """Test that shell injection is prevented."""
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = (b'{"completion": "safe"}', b"")
        mock_subprocess.return_value = mock_proc

        runner = SecureClaudeRunner()

        # Attempt shell injection
        malicious_prompt = "Calculate 2+2; rm -rf /; echo 'pwned'"
        await runner.run_claude_secure(
            prompt=malicious_prompt, config_dir=Path("/test/config")
        )

        # Verify the command was NOT passed through shell
        call_args = mock_subprocess.call_args
        # Should be individual arguments, not a shell command
        assert call_args[0] == ("claude", "ask", "--json")
        # The malicious prompt should be sent via stdin, not command line
        mock_proc.communicate.assert_called_once_with(input=malicious_prompt.encode("utf-8"))

    def test_build_safe_command(self):
        """Test safe command building."""
        runner = SecureClaudeRunner()

        # Basic command
        cmd = runner.build_safe_command(["claude", "ask"])
        assert cmd == ["claude", "ask"]

        # With boolean flag
        cmd = runner.build_safe_command(["claude", "ask"], json=True)
        assert cmd == ["claude", "ask", "--json"]

        # With value flag
        cmd = runner.build_safe_command(["claude", "ask"], max_tokens=1000)
        assert cmd == ["claude", "ask", "--max-tokens", "1000"]

        # With underscore to dash conversion
        cmd = runner.build_safe_command(["claude", "ask"], output_format="json")
        assert cmd == ["claude", "ask", "--output-format", "json"]


class TestPolicyEnforcer:
    """Test suite for PolicyEnforcer."""

    def test_default_policies(self):
        """Test default policy configuration."""
        enforcer = PolicyEnforcer()

        # Normal prompt should pass
        allowed, reason = enforcer.check_prompt("Calculate 2+2")
        assert allowed is True
        assert reason is None

    def test_blocked_patterns(self):
        """Test blocking prompts with forbidden patterns."""
        config = {"blocked_patterns": ["rm -rf", "sudo", "password"]}
        enforcer = PolicyEnforcer(config)

        # Blocked patterns
        allowed, reason = enforcer.check_prompt("Please run rm -rf /")
        assert allowed is False
        assert "blocked pattern" in reason

        # Case insensitive
        allowed, reason = enforcer.check_prompt("SUDO apt-get update")
        assert allowed is False

        # Safe prompt
        allowed, reason = enforcer.check_prompt("Calculate fibonacci sequence")
        assert allowed is True

    def test_max_length_policy(self):
        """Test maximum prompt length policy."""
        config = {"max_prompt_length": 100}
        enforcer = PolicyEnforcer(config)

        # Under limit
        allowed, reason = enforcer.check_prompt("a" * 50)
        assert allowed is True

        # Over limit
        allowed, reason = enforcer.check_prompt("a" * 150)
        assert allowed is False
        assert "exceeds maximum length" in reason

    def test_confirmation_patterns(self):
        """Test patterns requiring confirmation."""
        config = {"require_confirmation": ["delete", "remove", "drop"]}
        enforcer = PolicyEnforcer(config)

        assert enforcer.needs_confirmation("Delete all files") is True
        assert enforcer.needs_confirmation("Calculate sum") is False

    @pytest.mark.asyncio
    async def test_on_prompt_hook(self):
        """Test the on_prompt hook."""
        config = {"blocked_patterns": ["dangerous"]}
        enforcer = PolicyEnforcer(config)

        # Safe prompt
        proceed, modified = await enforcer.on_prompt("Calculate 2+2", "worker_1")
        assert proceed is True
        assert modified == "Calculate 2+2"

        # Blocked prompt
        proceed, modified = await enforcer.on_prompt("Do something dangerous", "worker_1")
        assert proceed is False
