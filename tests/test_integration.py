"""Integration tests for the task delegator system."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from task_delegator.account_registry import AccountRegistry
from task_delegator.secure_runner import SecureClaudeRunner


class MockClaudeResponse:
    """Mock Claude CLI responses for testing."""

    @staticmethod
    def success_response(content: str) -> tuple[bytes, bytes]:
        """Generate a successful JSON response."""
        response = json.dumps({"completion": content})
        return response.encode(), b""

    @staticmethod
    def error_response(error: str) -> tuple[bytes, bytes]:
        """Generate an error response."""
        return b"", error.encode()


@pytest.fixture
def mock_claude_cli():
    """Fixture that mocks Claude CLI subprocess calls."""
    with patch("asyncio.create_subprocess_exec") as mock_subprocess:
        # Create a mock process
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate.return_value = MockClaudeResponse.success_response(
            "Task completed successfully"
        )
        mock_subprocess.return_value = mock_proc

        yield mock_subprocess, mock_proc


class TestIntegration:
    """Integration tests for core functionality."""

    @pytest.mark.asyncio
    async def test_simple_task_execution(self, mock_claude_cli, tmp_path):
        """Test executing a simple task end-to-end."""
        mock_subprocess, mock_proc = mock_claude_cli

        # Create account registry
        config_file = tmp_path / "accounts.json"
        registry = AccountRegistry(config_file=config_file)
        registry.add_account("test", tmp_path / "test-config")

        # Execute task
        runner = SecureClaudeRunner()
        result = await runner.run_claude_secure(
            prompt="Write a hello world function",
            config_dir=registry.get_account_path("test"),
            timeout=30,
        )

        assert result["success"] is True
        assert result["completion"] == "Task completed successfully"

        # Verify subprocess was called correctly
        assert mock_subprocess.called
        call_args = mock_subprocess.call_args
        assert "CLAUDE_CONFIG_DIR" in call_args[1]["env"]

    @pytest.mark.asyncio
    async def test_multiple_workers_sequential(self, mock_claude_cli, tmp_path):
        """Test multiple workers executing tasks sequentially."""
        mock_subprocess, mock_proc = mock_claude_cli

        # Set up different responses for each task
        responses = [
            MockClaudeResponse.success_response("Task 1 done"),
            MockClaudeResponse.success_response("Task 2 done"),
            MockClaudeResponse.success_response("Task 3 done"),
        ]
        mock_proc.communicate.side_effect = responses

        # Create registry with multiple accounts
        config_file = tmp_path / "accounts.json"
        registry = AccountRegistry(config_file=config_file)

        workers = ["worker1", "worker2", "worker3"]
        for worker in workers:
            registry.add_account(worker, tmp_path / f"{worker}-config")

        # Execute tasks
        runner = SecureClaudeRunner()
        results = []

        for i, worker in enumerate(workers):
            result = await runner.run_claude_secure(
                prompt=f"Task {i+1}", config_dir=registry.get_account_path(worker)
            )
            results.append(result)

        # Verify all tasks completed
        assert all(r["success"] for r in results)
        assert results[0]["completion"] == "Task 1 done"
        assert results[1]["completion"] == "Task 2 done"
        assert results[2]["completion"] == "Task 3 done"

    @pytest.mark.asyncio
    async def test_error_handling_integration(self, tmp_path):
        """Test error handling across components."""
        with patch("asyncio.create_subprocess_exec") as mock_subprocess:
            # Simulate authentication error
            mock_proc = AsyncMock()
            mock_proc.returncode = 1
            mock_proc.communicate.return_value = MockClaudeResponse.error_response(
                "Error: Not authenticated"
            )
            mock_subprocess.return_value = mock_proc

            # Create registry and runner
            config_file = tmp_path / "accounts.json"
            registry = AccountRegistry(config_file=config_file)
            registry.add_account("test", tmp_path / "test-config")

            runner = SecureClaudeRunner()
            result = await runner.run_claude_secure(
                prompt="Test task", config_dir=registry.get_account_path("test")
            )

            assert result["success"] is False
            assert "Not authenticated" in result["error"]

    @pytest.mark.asyncio
    async def test_concurrent_execution_simulation(self, mock_claude_cli, tmp_path):
        """Test concurrent task execution simulation."""
        mock_subprocess, mock_proc = mock_claude_cli

        # Create response generator
        async def response_generator(task_num):
            await asyncio.sleep(0.1)  # Simulate work
            return MockClaudeResponse.success_response(f"Task {task_num} completed")

        # Mock different responses
        async def communicate_side_effect(stdin_input=None):
            task_num = stdin_input.decode().split()[-1] if stdin_input else "?"
            return await response_generator(task_num)

        mock_proc.communicate.side_effect = communicate_side_effect

        # Create registry
        config_file = tmp_path / "accounts.json"
        registry = AccountRegistry(config_file=config_file)

        # Add workers
        num_workers = 3
        for i in range(num_workers):
            registry.add_account(f"worker{i}", tmp_path / f"worker{i}-config")

        # Create tasks
        async def execute_task(worker_id: int, task_id: int):
            runner = SecureClaudeRunner()
            result = await runner.run_claude_secure(
                prompt=f"Execute task {task_id}",
                config_dir=registry.get_account_path(f"worker{worker_id}"),
            )
            return result

        # Execute tasks concurrently
        tasks = []
        for task_id in range(5):
            worker_id = task_id % num_workers
            tasks.append(execute_task(worker_id, task_id))

        results = await asyncio.gather(*tasks)

        # Verify all completed
        assert all(r["success"] for r in results)
        assert len(results) == 5

    def test_account_persistence(self, tmp_path):
        """Test that account configurations persist correctly."""
        config_file = tmp_path / "accounts.json"

        # Create and configure registry
        registry1 = AccountRegistry(config_file=config_file)
        registry1.add_account("prod", tmp_path / "prod-config")
        registry1.add_account("dev", tmp_path / "dev-config")

        # Simulate active accounts
        registry1._active_accounts.add("prod")
        registry1.save_config()

        # Load in new instance
        registry2 = AccountRegistry(config_file=config_file)
        accounts = registry2.list_accounts()

        assert "prod" in accounts
        assert "dev" in accounts
        assert accounts["prod"] == tmp_path / "prod-config"
        assert accounts["dev"] == tmp_path / "dev-config"

        # Check active status persisted
        assert "prod" in registry2._active_accounts
