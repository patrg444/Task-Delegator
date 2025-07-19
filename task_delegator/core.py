"""Core components for task delegation."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from .account_registry import AccountRegistry
from .secure_runner import PolicyEnforcer, SecureClaudeRunner

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """Task execution status."""

    PENDING = "pending"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskType(Enum):
    """Types of tasks."""

    GENERAL = "general"
    CODE_ANALYSIS = "code_analysis"
    IMPLEMENTATION = "implementation"
    DEBUGGING = "debugging"
    TESTING = "testing"
    DOCUMENTATION = "documentation"
    RESEARCH = "research"


@dataclass
class Task:
    """Enhanced task with metadata and tracking."""

    id: str  # noqa: A003
    prompt: str
    type: TaskType = TaskType.GENERAL  # noqa: A003
    priority: int = 5  # 1-10, higher is more important
    weight: float = 1.0  # Computational weight/cost
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    assigned_to: str | None = None
    assigned_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert task to dictionary."""
        return {
            "id": self.id,
            "prompt": self.prompt,
            "type": self.type.value,
            "priority": self.priority,
            "weight": self.weight,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "assigned_to": self.assigned_to,
            "assigned_at": self.assigned_at.isoformat() if self.assigned_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "result": self.result,
            "error": self.error,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Task:
        """Create task from dictionary."""
        # Convert string enums back to enum types
        task_type = TaskType(data.get("type", "general"))
        status = TaskStatus(data.get("status", "pending"))

        # Parse datetime fields
        created_at = (
            datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.now()
        )
        assigned_at = (
            datetime.fromisoformat(data["assigned_at"]) if data.get("assigned_at") else None
        )
        started_at = datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None
        completed_at = (
            datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None
        )

        return cls(
            id=data["id"],
            prompt=data["prompt"],
            type=task_type,
            priority=data.get("priority", 5),
            weight=data.get("weight", 1.0),
            status=status,
            created_at=created_at,
            assigned_to=data.get("assigned_to"),
            assigned_at=assigned_at,
            started_at=started_at,
            completed_at=completed_at,
            result=data.get("result"),
            error=data.get("error"),
            metadata=data.get("metadata", {}),
        )

    def priority_key(self) -> float:
        """Calculate priority key for queue ordering (lower is higher priority)."""
        # Could be customized: e.g., priority / weight for cost-based
        return -self.priority * self.weight


class WorkerProtocol(Protocol):
    """Protocol for worker implementations."""

    async def execute_task(self, task: Task) -> Task:
        """Execute a task and return updated task with results."""
        ...


@dataclass
class WorkerStats:
    """Statistics for a worker."""

    worker_id: str
    tasks_completed: int = 0
    tasks_failed: int = 0
    total_execution_time: float = 0.0
    average_task_time: float = 0.0
    last_task_completed: datetime | None = None
    errors: list[dict[str, Any]] = field(default_factory=list)

    def record_success(self, execution_time: float):
        """Record successful task completion."""
        self.tasks_completed += 1
        self.total_execution_time += execution_time
        self.average_task_time = self.total_execution_time / (
            self.tasks_completed + self.tasks_failed
        )
        self.last_task_completed = datetime.now()

    def record_failure(self, error: str, task_id: str):
        """Record task failure."""
        self.tasks_failed += 1
        self.errors.append(
            {"task_id": task_id, "error": error, "timestamp": datetime.now().isoformat()}
        )


class SwarmOrchestrator:
    """Main orchestrator for task distribution."""

    def __init__(
        self,
        account_registry: AccountRegistry,
        max_concurrent_workers: int = 5,
        policy_enforcer: PolicyEnforcer | None = None,
    ):
        self.registry = account_registry
        self.max_concurrent = max_concurrent_workers
        self.policy = policy_enforcer or PolicyEnforcer()
        self.runner = SecureClaudeRunner()
        self.worker_stats: dict[str, WorkerStats] = {}
        self.task_queue: asyncio.PriorityQueue[tuple[float, Task]] = asyncio.PriorityQueue()
        self.results: dict[str, Task] = {}

    def choose_worker_count(self, tasks: list[Task]) -> int:
        """
        Determine optimal worker count based on workload.

        Strategy:
        - High priority (≥8) or heavy load (>20): Maximum workers
        - Medium priority (≥6) or moderate load (>10): ~50% workers
        - Low priority: Minimal workers (25% or 1)
        """
        if not tasks:
            return 0

        total_weight = sum(task.weight for task in tasks)
        avg_priority = sum(task.priority for task in tasks) / len(tasks)
        available_workers = len(self.registry.get_active_accounts())

        if avg_priority >= 8 or total_weight > 20:
            suggested = min(len(tasks), available_workers, self.max_concurrent)
        elif avg_priority >= 6 or total_weight > 10:
            suggested = min(max(2, len(tasks) // 2), available_workers)
        else:
            suggested = min(max(1, len(tasks) // 4), available_workers)

        logger.info(
            f"Workload analysis: {len(tasks)} tasks, "
            f"weight: {total_weight:.1f}, priority: {avg_priority:.1f} "
            f"→ using {suggested} workers"
        )

        return suggested

    async def worker_loop(self, worker_id: str, config_dir: Path):
        """Main execution loop for a worker."""
        stats = self.worker_stats.setdefault(worker_id, WorkerStats(worker_id))

        while True:
            try:
                # Get task from priority queue
                _, task = await self.task_queue.get()

                if task is None:  # Sentinel
                    break

                # Update task status
                task.status = TaskStatus.ASSIGNED
                task.assigned_to = worker_id
                task.assigned_at = datetime.now()

                logger.info(f"[{worker_id}] Starting task {task.id}")

                # Check security policy
                allowed, modified_prompt = await self.policy.on_prompt(task.prompt, worker_id)

                if not allowed:
                    task.status = TaskStatus.FAILED
                    task.error = "Blocked by security policy"
                    self.results[task.id] = task
                    stats.record_failure("Security policy", task.id)
                    continue

                # Execute task
                task.prompt = modified_prompt
                task.status = TaskStatus.IN_PROGRESS
                task.started_at = datetime.now()
                start_time = time.time()

                result = await self.runner.run_claude_secure(
                    prompt=task.prompt, config_dir=config_dir, timeout=300
                )

                execution_time = time.time() - start_time

                if result["success"]:
                    task.status = TaskStatus.COMPLETED
                    task.result = result["completion"]
                    task.completed_at = datetime.now()
                    stats.record_success(execution_time)
                    logger.info(f"[{worker_id}] Completed task {task.id} in {execution_time:.1f}s")
                else:
                    task.status = TaskStatus.FAILED
                    task.error = result.get("error", "Unknown error")
                    stats.record_failure(task.error, task.id)
                    logger.error(f"[{worker_id}] Failed task {task.id}: {task.error}")

                self.results[task.id] = task

            except Exception as e:
                logger.error(f"[{worker_id}] Unexpected error: {e}")
                if task and task.id not in self.results:
                    task.status = TaskStatus.FAILED
                    task.error = str(e)
                    self.results[task.id] = task
                    stats.record_failure(str(e), task.id)

            finally:
                self.task_queue.task_done()

    async def orchestrate(self, tasks: list[Task]) -> dict[str, Any]:
        """
        Orchestrate task execution across workers.

        Returns:
            Dictionary with results, statistics, and metadata
        """
        start_time = time.time()

        # Reset state
        self.results.clear()
        self.worker_stats.clear()

        # Add tasks to priority queue
        for task in tasks:
            await self.task_queue.put((task.priority_key(), task))

        # Get available workers
        worker_count = self.choose_worker_count(tasks)
        workers = self.registry.get_available_workers(max_workers=worker_count)

        if not workers:
            logger.error("No active workers available")
            return {
                "success": False,
                "error": "No active workers available",
                "results": {},
                "stats": {},
            }

        # Add sentinels for workers
        for _ in workers:
            await self.task_queue.put((float("inf"), None))

        # Start worker tasks
        worker_tasks = []
        for worker_id, config_dir in workers.items():
            worker_task = asyncio.create_task(self.worker_loop(worker_id, config_dir))
            worker_tasks.append(worker_task)

        # Wait for all workers to complete
        await asyncio.gather(*worker_tasks)

        # Calculate summary statistics
        total_time = time.time() - start_time
        completed = sum(1 for t in self.results.values() if t.status == TaskStatus.COMPLETED)
        failed = sum(1 for t in self.results.values() if t.status == TaskStatus.FAILED)

        return {
            "success": True,
            "summary": {
                "total_tasks": len(tasks),
                "completed": completed,
                "failed": failed,
                "success_rate": (completed / len(tasks) * 100) if tasks else 0,
                "total_time": total_time,
                "tasks_per_minute": (len(tasks) / total_time * 60) if total_time > 0 else 0,
            },
            "results": {task_id: task.to_dict() for task_id, task in self.results.items()},
            "worker_stats": {
                worker_id: {
                    "tasks_completed": stats.tasks_completed,
                    "tasks_failed": stats.tasks_failed,
                    "average_task_time": stats.average_task_time,
                    "total_time": stats.total_execution_time,
                }
                for worker_id, stats in self.worker_stats.items()
            },
        }


class TaskLoader:
    """Load tasks from various sources."""

    @staticmethod
    def from_file(file_path: Path) -> list[Task]:
        """Load tasks from JSON file."""
        with open(file_path) as f:
            data = json.load(f)

        tasks_data = data if isinstance(data, list) else data.get("tasks", [])
        return [Task.from_dict(task_data) for task_data in tasks_data]

    @staticmethod
    def from_prompts(prompts: list[str], task_type: TaskType = TaskType.GENERAL) -> list[Task]:
        """Create tasks from a list of prompts."""
        return [
            Task(id=f"task_{i}", prompt=prompt, type=task_type, priority=5, weight=1.0)
            for i, prompt in enumerate(prompts)
        ]
