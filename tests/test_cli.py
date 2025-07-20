"""Tests for the CLI module."""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from task_delegator.cli import TaskDelegatorCLI, main
from task_delegator.core import Task, TaskType


class TestTaskDelegatorCLI:
    """Test the main CLI class."""

    @pytest.fixture
    def cli(self):
        """Create a CLI instance."""
        return TaskDelegatorCLI()

    @pytest.fixture
    def sample_tasks(self, tmp_path):
        """Create a sample tasks file."""
        tasks_file = tmp_path / "tasks.json"
        tasks = {
            "tasks": [
                {
                    "id": "test_1",
                    "prompt": "Test task 1",
                    "type": "general",
                    "priority": 5,
                },
                {
                    "id": "test_2",
                    "prompt": "Test task 2",
                    "type": "implementation",
                    "priority": 8,
                },
            ]
        }
        with open(tasks_file, "w") as f:
            json.dump(tasks, f)
        return tasks_file

    @pytest.mark.asyncio
    async def test_run_tasks_basic(self, cli, sample_tasks, tmp_path):
        """Test basic task execution."""
        output_file = tmp_path / "results.json"

        # Mock the orchestrator
        with patch("task_delegator.cli.SwarmOrchestrator") as mock_orchestrator_class:
            mock_orchestrator = AsyncMock()
            mock_orchestrator_class.return_value = mock_orchestrator
            mock_orchestrator.orchestrate.return_value = {
                "success": True,
                "summary": {
                    "total_tasks": 2,
                    "completed": 2,
                    "failed": 0,
                    "success_rate": 100.0,
                    "total_time": 10.5,
                    "tasks_per_minute": 11.4,
                },
                "worker_stats": {
                    "worker_1": {
                        "tasks_completed": 2,
                        "tasks_failed": 0,
                        "average_task_time": 5.25,
                    }
                },
            }

            await cli.run_tasks(sample_tasks, max_workers=2, output_file=output_file)

            # Verify orchestrator was called
            mock_orchestrator.orchestrate.assert_called_once()

            # Verify output file was created
            assert output_file.exists()
            with open(output_file) as f:
                results = json.load(f)
                assert results["success"] is True

    @pytest.mark.asyncio
    async def test_run_tasks_with_monitoring(self, cli, sample_tasks):
        """Test task execution with monitoring enabled."""
        # Mock both orchestrators
        with (
            patch("task_delegator.cli.SwarmOrchestrator") as mock_swarm_class,
            patch("task_delegator.cli.MonitoredOrchestrator") as mock_monitored_class,
        ):
            mock_base = MagicMock()
            mock_swarm_class.return_value = mock_base

            mock_monitored = AsyncMock()
            mock_monitored_class.return_value = mock_monitored
            mock_monitored.orchestrate_with_monitoring.return_value = {
                "success": True,
                "summary": {"total_tasks": 2, "completed": 2},
            }

            await cli.run_tasks(sample_tasks, enable_monitoring=True)

            # Verify monitored orchestrator was used
            mock_monitored_class.assert_called_once_with(mock_base, enable_dashboard=True)
            mock_monitored.orchestrate_with_monitoring.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_tasks_failure(self, cli, sample_tasks, capsys):
        """Test handling of execution failure."""
        with patch("task_delegator.cli.SwarmOrchestrator") as mock_orchestrator_class:
            mock_orchestrator = AsyncMock()
            mock_orchestrator_class.return_value = mock_orchestrator
            mock_orchestrator.orchestrate.return_value = {
                "success": False,
                "error": "Test failure",
            }

            await cli.run_tasks(sample_tasks)

            captured = capsys.readouterr()
            assert "Execution failed: Test failure" in captured.out

    def test_print_summary_success(self, cli, capsys):
        """Test printing execution summary."""
        result = {
            "success": True,
            "summary": {
                "total_tasks": 10,
                "completed": 9,
                "failed": 1,
                "success_rate": 90.0,
                "total_time": 120.5,
                "tasks_per_minute": 5.0,
            },
            "worker_stats": {
                "worker_1": {
                    "tasks_completed": 5,
                    "tasks_failed": 0,
                    "average_task_time": 12.0,
                },
                "worker_2": {
                    "tasks_completed": 4,
                    "tasks_failed": 1,
                    "average_task_time": 13.0,
                },
            },
        }

        cli._print_summary(result)
        captured = capsys.readouterr()

        assert "EXECUTION SUMMARY" in captured.out
        assert "Total tasks: 10" in captured.out
        assert "Completed: 9" in captured.out
        assert "Failed: 1" in captured.out
        assert "Success rate: 90.0%" in captured.out
        assert "Total time: 120.5s" in captured.out
        assert "Throughput: 5.0 tasks/min" in captured.out
        assert "WORKER STATISTICS:" in captured.out
        assert "worker_1:" in captured.out
        assert "Completed: 5" in captured.out

    def test_setup_accounts(self, cli):
        """Test account setup."""
        with patch.object(cli.registry, "setup_all_accounts", return_value=2):
            cli.setup_accounts()  # Should succeed with 2 accounts

        # Test with no accounts
        with (
            patch.object(cli.registry, "setup_all_accounts", return_value=0),
            pytest.raises(SystemExit) as exc_info,
        ):
            cli.setup_accounts()
            assert exc_info.value.code == 1

    def test_list_accounts(self, cli, capsys):
        """Test listing accounts."""
        with (
            patch.object(
                cli.registry,
                "list_accounts",
                return_value={
                    "account1": Path("/path/to/account1"),
                    "account2": Path("/path/to/account2"),
                },
            ),
            patch.object(
                cli.registry, "check_login_status", side_effect=[True, False]
            ),
            patch.object(cli.registry, "get_active_accounts", return_value=["account1"]),
        ):
            cli.list_accounts()
            captured = capsys.readouterr()

            assert "CONFIGURED ACCOUNTS" in captured.out
            assert "account1" in captured.out
            assert "✓ Active" in captured.out
            assert "account2" in captured.out
            assert "✗ Inactive" in captured.out
            assert "Total: 2 accounts, 1 active" in captured.out

    def test_create_example_tasks(self, cli, tmp_path):
        """Test creating example tasks file."""
        output_file = tmp_path / "example.json"
        cli.create_example_tasks(output_file)

        assert output_file.exists()
        with open(output_file) as f:
            data = json.load(f)
            assert "tasks" in data
            assert len(data["tasks"]) == 5
            assert data["tasks"][0]["id"] == "example_1"
            assert data["tasks"][0]["type"] == "implementation"


class TestMainFunction:
    """Test the main entry point."""

    def test_main_no_args(self):
        """Test main with no arguments."""
        with (
            patch("sys.argv", ["claude-delegator"]),
            patch("sys.exit") as mock_exit,
        ):
            main()
            mock_exit.assert_called_once_with(1)

    def test_main_run_command(self, tmp_path):
        """Test main with run command."""
        tasks_file = tmp_path / "tasks.json"
        tasks_file.write_text('{"tasks": []}')

        with (
            patch("sys.argv", ["claude-delegator", "run", str(tasks_file)]),
            patch("asyncio.run") as mock_run,
        ):
            main()
            mock_run.assert_called_once()

    def test_main_run_missing_file(self):
        """Test main with missing task file."""
        with (
            patch("sys.argv", ["claude-delegator", "run", "missing.json"]),
            patch("sys.exit") as mock_exit,
            patch("builtins.print"),  # Suppress print output
        ):
            main()
            # The exit is called twice - once for file not found, once in exception handler
            assert mock_exit.call_count == 2
            mock_exit.assert_any_call(1)

    def test_main_run_with_options(self, tmp_path):
        """Test main with run command and options."""
        tasks_file = tmp_path / "tasks.json"
        output_file = tmp_path / "output.json"
        tasks_file.write_text('{"tasks": []}')

        with (
            patch(
                "sys.argv",
                [
                    "claude-delegator",
                    "run",
                    str(tasks_file),
                    "-w",
                    "3",
                    "-o",
                    str(output_file),
                    "-m",
                    "--use-api",
                ],
            ),
            patch("asyncio.run") as mock_run,
        ):
            main()
            
            # Get the called coroutine
            coro = mock_run.call_args[0][0]
            # Extract the parameters from the coroutine
            assert coro.cr_frame.f_locals["max_workers"] == 3
            assert coro.cr_frame.f_locals["output_file"] == output_file
            assert coro.cr_frame.f_locals["enable_monitoring"] is True
            assert coro.cr_frame.f_locals["use_api"] is True

    def test_main_setup_command(self):
        """Test main with setup command."""
        with (
            patch("sys.argv", ["claude-delegator", "setup"]),
            patch("task_delegator.cli.TaskDelegatorCLI.setup_accounts") as mock_setup,
        ):
            main()
            mock_setup.assert_called_once()

    def test_main_list_command(self):
        """Test main with list command."""
        with (
            patch("sys.argv", ["claude-delegator", "list"]),
            patch("task_delegator.cli.TaskDelegatorCLI.list_accounts") as mock_list,
        ):
            main()
            mock_list.assert_called_once()

    def test_main_example_command(self, tmp_path):
        """Test main with example command."""
        output_file = tmp_path / "example.json"

        with (
            patch("sys.argv", ["claude-delegator", "example", "-o", str(output_file)]),
            patch(
                "task_delegator.cli.TaskDelegatorCLI.create_example_tasks"
            ) as mock_create,
        ):
            main()
            mock_create.assert_called_once_with(output_file)

    def test_main_keyboard_interrupt(self):
        """Test handling keyboard interrupt."""
        with (
            patch("sys.argv", ["claude-delegator", "setup"]),
            patch(
                "task_delegator.cli.TaskDelegatorCLI.setup_accounts",
                side_effect=KeyboardInterrupt,
            ),
            patch("sys.exit") as mock_exit,
        ):
            main()
            mock_exit.assert_called_once_with(1)

    def test_main_exception(self):
        """Test handling general exception."""
        with (
            patch("sys.argv", ["claude-delegator", "setup"]),
            patch(
                "task_delegator.cli.TaskDelegatorCLI.setup_accounts",
                side_effect=Exception("Test error"),
            ),
            patch("sys.exit") as mock_exit,
        ):
            main()
            mock_exit.assert_called_once_with(1)