"""Tests for core components."""

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from task_delegator.account_registry import AccountRegistry
from task_delegator.core import SwarmOrchestrator, Task, TaskStatus, TaskType, WorkerStats


class TestTask:
    """Test Task dataclass."""

    def test_task_creation(self):
        """Test basic task creation."""
        task = Task(
            id="test_1", prompt="Test prompt", type=TaskType.IMPLEMENTATION, priority=8, weight=2.5
        )

        assert task.id == "test_1"
        assert task.prompt == "Test prompt"
        assert task.type == TaskType.IMPLEMENTATION
        assert task.priority == 8
        assert task.weight == 2.5
        assert task.status == TaskStatus.PENDING
        assert isinstance(task.created_at, datetime)

    def test_task_to_dict(self):
        """Test task serialization."""
        task = Task(id="test_1", prompt="Test")
        task_dict = task.to_dict()

        assert task_dict["id"] == "test_1"
        assert task_dict["prompt"] == "Test"
        assert task_dict["type"] == "general"
        assert task_dict["status"] == "pending"
        assert "created_at" in task_dict

    def test_task_from_dict(self):
        """Test task deserialization."""
        data = {
            "id": "test_1",
            "prompt": "Test prompt",
            "type": "implementation",
            "priority": 7,
            "weight": 2.0,
            "status": "completed",
            "created_at": datetime.now().isoformat(),
        }

        task = Task.from_dict(data)
        assert task.id == "test_1"
        assert task.type == TaskType.IMPLEMENTATION
        assert task.status == TaskStatus.COMPLETED
        assert task.priority == 7

    def test_priority_key(self):
        """Test priority key calculation."""
        task1 = Task("1", "Task 1", priority=10, weight=1.0)
        task2 = Task("2", "Task 2", priority=5, weight=2.0)
        task3 = Task("3", "Task 3", priority=10, weight=2.0)

        # Higher priority and weight = lower key (higher in queue)
        # task3: -10 * 2.0 = -20
        # task1: -10 * 1.0 = -10
        # task2: -5 * 2.0 = -10
        assert task3.priority_key() < task1.priority_key()
        assert task3.priority_key() < task2.priority_key()
        # task1 and task2 have same priority key
        assert task1.priority_key() == task2.priority_key()


class TestWorkerStats:
    """Test WorkerStats tracking."""

    def test_record_success(self):
        """Test recording successful task."""
        stats = WorkerStats("worker_1")

        stats.record_success(10.5)
        assert stats.tasks_completed == 1
        assert stats.total_execution_time == 10.5
        assert stats.average_task_time == 10.5
        assert stats.last_task_completed is not None

        stats.record_success(5.5)
        assert stats.tasks_completed == 2
        assert stats.total_execution_time == 16.0
        assert stats.average_task_time == 8.0

    def test_record_failure(self):
        """Test recording failed task."""
        stats = WorkerStats("worker_1")

        stats.record_failure("Test error", "task_1")
        assert stats.tasks_failed == 1
        assert len(stats.errors) == 1
        assert stats.errors[0]["task_id"] == "task_1"
        assert stats.errors[0]["error"] == "Test error"


class TestSwarmOrchestrator:
    """Test SwarmOrchestrator."""

    @pytest.fixture
    def orchestrator(self, tmp_path):
        """Create orchestrator with test registry."""
        registry = AccountRegistry(config_file=tmp_path / "test_accounts.json")
        return SwarmOrchestrator(registry)

    def test_choose_worker_count(self, orchestrator):
        """Test worker count selection logic."""
        # Mock active accounts
        with patch.object(orchestrator.registry, "get_active_accounts") as mock_active:
            mock_active.return_value = {
                "worker1": Path("/tmp/worker1"),
                "worker2": Path("/tmp/worker2"),
                "worker3": Path("/tmp/worker3"),
            }

            # Empty tasks
            assert orchestrator.choose_worker_count([]) == 0

            # High priority tasks
            high_priority_tasks = [
                Task(f"t{i}", f"Task {i}", priority=9, weight=1.0) for i in range(10)
            ]
            count = orchestrator.choose_worker_count(high_priority_tasks)
            assert count > 0  # Should use multiple workers
            assert count <= 3  # Should not exceed available workers

            # Low priority tasks
            low_priority_tasks = [
                Task(f"t{i}", f"Task {i}", priority=3, weight=1.0) for i in range(10)
            ]
            count = orchestrator.choose_worker_count(low_priority_tasks)
            assert count >= 1  # Should use minimal workers

    @pytest.mark.asyncio
    @patch("task_delegator.core.SecureClaudeRunner.run_claude_secure")
    async def test_worker_loop_success(self, mock_run, orchestrator, tmp_path):
        """Test successful task execution in worker loop."""
        # Setup mock
        mock_run.return_value = {"success": True, "completion": "Task completed"}

        # Add task to queue
        task = Task("test_1", "Test task")
        await orchestrator.task_queue.put((task.priority_key(), task))
        await orchestrator.task_queue.put((float("inf"), None))  # Sentinel

        # Run worker
        await orchestrator.worker_loop("worker_1", tmp_path)

        # Check results
        assert "test_1" in orchestrator.results
        result = orchestrator.results["test_1"]
        assert result.status == TaskStatus.COMPLETED
        assert result.result == "Task completed"
        assert result.assigned_to == "worker_1"

        # Check stats
        stats = orchestrator.worker_stats["worker_1"]
        assert stats.tasks_completed == 1
        assert stats.tasks_failed == 0

    @pytest.mark.asyncio
    @patch("task_delegator.core.SecureClaudeRunner.run_claude_secure")
    async def test_worker_loop_failure(self, mock_run, orchestrator, tmp_path):
        """Test failed task execution in worker loop."""
        # Setup mock
        mock_run.return_value = {"success": False, "error": "API error"}

        # Add task
        task = Task("test_1", "Test task")
        await orchestrator.task_queue.put((task.priority_key(), task))
        await orchestrator.task_queue.put((float("inf"), None))

        # Run worker
        await orchestrator.worker_loop("worker_1", tmp_path)

        # Check results
        assert "test_1" in orchestrator.results
        result = orchestrator.results["test_1"]
        assert result.status == TaskStatus.FAILED
        assert result.error == "API error"

        # Check stats
        stats = orchestrator.worker_stats["worker_1"]
        assert stats.tasks_completed == 0
        assert stats.tasks_failed == 1

    @pytest.mark.asyncio
    async def test_orchestrate_no_workers(self, orchestrator):
        """Test orchestration with no active workers."""
        tasks = [Task("1", "Task 1")]

        # Mock no active accounts
        orchestrator.registry.get_available_workers = MagicMock(return_value={})

        result = await orchestrator.orchestrate(tasks)

        assert result["success"] is False
        assert "No active workers" in result["error"]

    @pytest.mark.asyncio
    @patch("task_delegator.core.SecureClaudeRunner.run_claude_secure")
    async def test_orchestrate_full_flow(self, mock_run, tmp_path):
        """Test full orchestration flow."""
        # Create orchestrator with mock registry
        registry = AccountRegistry(config_file=tmp_path / "test_accounts.json")
        registry.add_account("worker_1", tmp_path / "worker1_config")
        registry.add_account("worker_2", tmp_path / "worker2_config")

        # Mock active accounts
        with patch.object(registry, "get_available_workers") as mock_workers:
            mock_workers.return_value = {
                "worker_1": tmp_path / "worker1_config",
                "worker_2": tmp_path / "worker2_config",
            }

            orchestrator = SwarmOrchestrator(registry)

            # Mock Claude responses
            mock_run.return_value = {"success": True, "completion": "Done"}

            # Create tasks
            tasks = [Task(f"task_{i}", f"Do task {i}", priority=5 + i) for i in range(5)]

            # Run orchestration
            result = await orchestrator.orchestrate(tasks)

            assert result["success"] is True
            assert result["summary"]["total_tasks"] == 5
            assert result["summary"]["completed"] == 5
            assert result["summary"]["failed"] == 0
            assert result["summary"]["success_rate"] == 100.0

            # Check all tasks completed
            for i in range(5):
                assert f"task_{i}" in result["results"]
