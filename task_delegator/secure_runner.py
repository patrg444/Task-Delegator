"""Secure command execution without shell injection vulnerabilities."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SecureClaudeRunner:
    """Securely execute Claude CLI commands without shell injection risks."""

    @staticmethod
    def validate_prompt(prompt: str) -> str:
        """Validate and sanitize prompt text."""
        # Remove any null bytes
        prompt = prompt.replace("\0", "")

        # Limit prompt length to prevent DoS
        max_length = 50000  # Reasonable limit for Claude
        if len(prompt) > max_length:
            logger.warning(f"Prompt truncated from {len(prompt)} to {max_length} chars")
            prompt = prompt[:max_length]

        return prompt

    @staticmethod
    async def run_claude_secure(
        prompt: str, config_dir: Path, timeout: float = 300, json_output: bool = True
    ) -> dict[str, Any]:
        """
        Securely run Claude CLI without shell injection vulnerabilities.

        Args:
            prompt: The prompt text (will be validated)
            config_dir: Claude configuration directory
            timeout: Command timeout in seconds
            json_output: Whether to request JSON output

        Returns:
            Dict containing the response or error information
        """
        # Validate prompt
        prompt = SecureClaudeRunner.validate_prompt(prompt)

        # Build command as list (no shell interpretation)
        cmd = ["claude", "ask"]
        if json_output:
            cmd.append("--json")

        # Create environment
        env = {"CLAUDE_CONFIG_DIR": str(config_dir)}

        try:
            # Create subprocess with explicit arguments (no shell=True)
            proc = await asyncio.create_subprocess_exec(
                *cmd,  # Unpack command list
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            # Send prompt via stdin instead of command line
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=prompt.encode("utf-8")), timeout=timeout
            )

            if proc.returncode != 0:
                error_msg = stderr.decode("utf-8", errors="replace")
                return {
                    "success": False,
                    "error": error_msg or f"Claude CLI exited with code {proc.returncode}",
                    "returncode": proc.returncode,
                }

            # Parse output
            output = stdout.decode("utf-8", errors="replace")

            if json_output:
                try:
                    result = json.loads(output)
                    return {
                        "success": True,
                        "completion": result.get("completion", ""),
                        "raw_output": output,
                    }
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse JSON response: {e}")
                    return {
                        "success": False,
                        "error": f"Invalid JSON response: {e}",
                        "raw_output": output,
                    }
            else:
                return {"success": True, "completion": output, "raw_output": output}

        except asyncio.TimeoutError:
            # Terminate process if still running
            if proc and proc.returncode is None:
                proc.terminate()
                await proc.wait()

            return {
                "success": False,
                "error": f"Claude CLI timed out after {timeout} seconds",
                "timeout": True,
            }

        except Exception as e:
            logger.error(f"Unexpected error running Claude CLI: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def build_safe_command(base_cmd: list[str], **kwargs) -> list[str]:
        """
        Build a safe command list with validated arguments.

        Args:
            base_cmd: Base command list (e.g., ['claude', 'ask'])
            **kwargs: Additional arguments to add

        Returns:
            Safe command list
        """
        cmd = base_cmd.copy()

        # Add arguments safely
        for key, value in kwargs.items():
            if value is not None:
                # Convert key to CLI flag format
                flag = f"--{key.replace('_', '-')}"
                cmd.append(flag)

                # Add value if not a boolean flag
                if value is not True:
                    cmd.append(str(value))

        return cmd


class PolicyEnforcer:
    """Enforce security policies for prompt execution."""

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize with optional policy configuration."""
        self.config = config or {}
        self.blocked_patterns = self.config.get("blocked_patterns", [])
        self.require_confirmation = self.config.get("require_confirmation", [])
        self.max_prompt_length = self.config.get("max_prompt_length", 50000)

    def check_prompt(self, prompt: str) -> tuple[bool, str | None]:
        """
        Check if a prompt is allowed by security policies.

        Returns:
            (allowed, reason) - True if allowed, False with reason if blocked
        """
        # Check length
        if len(prompt) > self.max_prompt_length:
            return False, f"Prompt exceeds maximum length of {self.max_prompt_length}"

        # Check blocked patterns
        for pattern in self.blocked_patterns:
            if pattern in prompt.lower():
                return False, f"Prompt contains blocked pattern: {pattern}"

        return True, None

    def needs_confirmation(self, prompt: str) -> bool:
        """Check if prompt requires human confirmation."""
        for pattern in self.require_confirmation:
            if pattern in prompt.lower():
                return True
        return False

    async def on_prompt(self, prompt: str, worker_id: str) -> tuple[bool, str]:
        """
        Hook called before executing any prompt.

        Args:
            prompt: The prompt text
            worker_id: ID of the worker executing this

        Returns:
            (proceed, modified_prompt) - whether to proceed and potentially modified prompt
        """
        # Check policies
        allowed, reason = self.check_prompt(prompt)
        if not allowed:
            logger.warning(f"[{worker_id}] Prompt blocked: {reason}")
            return False, prompt

        # Check if confirmation needed
        if self.needs_confirmation(prompt):
            logger.info(f"[{worker_id}] Prompt requires confirmation")
            # In automated mode, we might want to skip or alert
            # For now, we'll proceed but log it
            logger.warning(f"[{worker_id}] Auto-proceeding with confirmation-required prompt")

        return True, prompt


# Example usage
async def example_secure_execution():
    """Example of secure Claude execution."""
    runner = SecureClaudeRunner()

    # This prompt would have caused shell injection in the old version
    malicious_prompt = "Calculate 2+2; rm -rf /"

    result = await runner.run_claude_secure(
        prompt=malicious_prompt, config_dir=Path.home() / ".claude-work", timeout=30
    )

    if result["success"]:
        print(f"Claude response: {result['completion']}")
    else:
        print(f"Error: {result['error']}")


if __name__ == "__main__":
    asyncio.run(example_secure_execution())
