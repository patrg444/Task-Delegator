#!/usr/bin/env python3
"""
async_swarm.py – Enhanced task-swarm orchestrator for multiple Claude Code CLI instances
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime
from itertools import islice
from pathlib import Path
from typing import Any

# ---- Configure logging -----------------------------------------------------

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ---- 1. Configure your Claude accounts here -------------------------------

ACCOUNTS: dict[str, Path] = {
    "account_A": Path.home() / ".claude-work",
    "account_B": Path.home() / ".claude-personal",
    # Add more accounts / paths if you have more logins
}

# ---- 2. Task types and workload generation --------------------------------


class Task:
    """Enhanced task with metadata"""

    def __init__(
        self,
        task_id: str,
        prompt: str,
        task_type: str = "general",
        priority: int = 5,
        weight: float = 1.0,
    ):
        self.id = task_id
        self.prompt = prompt
        self.type = task_type
        self.priority = priority
        self.weight = weight
        self.created_at = datetime.now()
        self.started_at = None
        self.completed_at = None
        self.assigned_to = None
        self.result = None
        self.error = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "prompt": self.prompt,
            "type": self.type,
            "priority": self.priority,
            "weight": self.weight,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "assigned_to": self.assigned_to,
            "result": self.result,
            "error": self.error,
        }


def generate_tasks(workload_config: dict) -> list[Task]:
    """Generate tasks from configuration"""
    tasks = []

    # Example workload types
    if "code_analysis" in workload_config:
        for i, file_path in enumerate(workload_config["code_analysis"]):
            tasks.append(
                Task(
                    f"analyze_{i}",
                    f"Analyze the code structure and patterns in {file_path}",
                    "code_analysis",
                    priority=7,
                    weight=2.0,
                )
            )

    if "implementation" in workload_config:
        for i, feature in enumerate(workload_config["implementation"]):
            tasks.append(
                Task(
                    f"implement_{i}",
                    f"Implement {feature}",
                    "implementation",
                    priority=8,
                    weight=3.0,
                )
            )

    if "documentation" in workload_config:
        for i, component in enumerate(workload_config["documentation"]):
            tasks.append(
                Task(
                    f"doc_{i}",
                    f"Write documentation for {component}",
                    "documentation",
                    priority=5,
                    weight=1.5,
                )
            )

    return tasks


# ---- 3. Dynamic worker count selection -------------------------------------


def choose_worker_count(tasks: list[Task], max_workers: int) -> int:
    """
    Smarter heuristic based on task weights and priorities
    """
    if not tasks:
        return 0

    total_weight = sum(task.weight for task in tasks)
    avg_priority = sum(task.priority for task in tasks) / len(tasks)

    # More workers for high-priority or heavy workloads
    if avg_priority >= 8 or total_weight > 20:
        suggested = min(len(tasks), max_workers)
    elif avg_priority >= 6 or total_weight > 10:
        suggested = min(max(2, len(tasks) // 2), max_workers)
    else:
        suggested = min(max(1, len(tasks) // 4), max_workers)

    logger.info(
        f"Workload analysis: {len(tasks)} tasks, total weight: {total_weight:.1f}, "
        f"avg priority: {avg_priority:.1f} → using {suggested} workers"
    )

    return suggested


# ---- 4. Enhanced worker coroutine ------------------------------------------


async def run_claude(prompt: str, config_dir: Path, timeout: float = 300) -> str:
    """
    Run Claude CLI with timeout and better error handling
    """
    env = os.environ.copy()
    env["CLAUDE_CONFIG_DIR"] = str(config_dir)

    try:
        proc = await asyncio.create_subprocess_exec(
            "claude",
            "ask",
            "--json",
            prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        raw_out, raw_err = await asyncio.wait_for(proc.communicate(), timeout=timeout)

        if proc.returncode != 0:
            raise RuntimeError(f"Claude CLI failed: {raw_err.decode()}")

        reply = json.loads(raw_out)
        return reply["completion"]

    except asyncio.TimeoutError:
        if proc:
            proc.terminate()
            await proc.wait()
        raise RuntimeError(f"Claude CLI timed out after {timeout}s")
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Invalid JSON from Claude CLI: {e}")


async def worker(
    name: str,
    config_dir: Path,
    queue: asyncio.PriorityQueue[tuple[float, Task]],
    results: dict[str, Task],
    stats: dict[str, Any],
    retry_count: int = 3,
    retry_delay: float = 2.0,
):
    """Enhanced worker with retries and statistics"""
    worker_stats = {"tasks_completed": 0, "tasks_failed": 0, "total_time": 0, "errors": []}

    while True:
        try:
            # Priority queue returns (priority, task)
            _, task = await queue.get()

            if task is None:  # Sentinel
                queue.task_done()
                break

            task.assigned_to = name
            task.started_at = datetime.now()
            start_time = time.time()

            # Retry logic
            last_error = None
            for attempt in range(retry_count):
                try:
                    logger.info(f"[{name}] Starting task {task.id}: {task.prompt[:50]}...")
                    answer = await run_claude(task.prompt, config_dir)
                    task.result = answer
                    task.completed_at = datetime.now()

                    elapsed = time.time() - start_time
                    worker_stats["tasks_completed"] += 1
                    worker_stats["total_time"] += elapsed

                    logger.info(f"[{name}] Completed task {task.id} in {elapsed:.1f}s")
                    break

                except Exception as exc:
                    last_error = exc
                    if attempt < retry_count - 1:
                        logger.warning(
                            f"[{name}] Retry {attempt + 1}/{retry_count} for task {task.id}: {exc}"
                        )
                        await asyncio.sleep(retry_delay * (attempt + 1))
                    else:
                        task.error = str(exc)
                        worker_stats["tasks_failed"] += 1
                        worker_stats["errors"].append(
                            {
                                "task_id": task.id,
                                "error": str(exc),
                                "timestamp": datetime.now().isoformat(),
                            }
                        )
                        logger.error(
                            f"[{name}] Failed task {task.id} after {retry_count} attempts: {exc}"
                        )

            results[task.id] = task

        except Exception as exc:
            logger.error(f"[{name}] Unexpected error: {exc}")
        finally:
            queue.task_done()

    stats[name] = worker_stats
    logger.info(
        f"[{name}] Shutting down. Stats: {worker_stats['tasks_completed']} completed, "
        f"{worker_stats['tasks_failed']} failed"
    )


# ---- 5. Enhanced orchestrator ----------------------------------------------


async def orchestrate(tasks: list[Task]) -> tuple[dict[str, Task], dict[str, Any]]:
    """
    Orchestrate task execution with priority queue and statistics
    """
    results: dict[str, Task] = {}
    stats: dict[str, Any] = {}

    # Priority queue (lower number = higher priority)
    queue: asyncio.PriorityQueue[tuple[float, Task]] = asyncio.PriorityQueue()

    # Enqueue tasks with priority (negative priority for proper ordering)
    for task in tasks:
        priority_value = -task.priority * task.weight  # Higher priority/weight = lower value
        await queue.put((priority_value, task))

    # Choose worker count and add sentinels
    num_workers = choose_worker_count(tasks, len(ACCOUNTS))
    for _ in range(num_workers):
        await queue.put((float("inf"), None))  # Sentinels have lowest priority

    # Start workers
    chosen_accounts = list(islice(ACCOUNTS.items(), num_workers))
    start_time = time.time()

    coros = [worker(name, cfg_dir, queue, results, stats) for name, cfg_dir in chosen_accounts]

    await asyncio.gather(*coros)

    total_time = time.time() - start_time
    stats["total_execution_time"] = total_time
    stats["tasks_per_second"] = len(tasks) / total_time if total_time > 0 else 0

    return results, stats


# ---- 6. Result aggregation and reporting -----------------------------------


def aggregate_results(results: dict[str, Task], stats: dict[str, Any]) -> dict:
    """Aggregate results by task type and generate summary"""
    summary = {
        "execution_stats": stats,
        "task_summary": {
            "total": len(results),
            "completed": sum(1 for t in results.values() if t.result and not t.error),
            "failed": sum(1 for t in results.values() if t.error),
        },
        "by_type": {},
        "results": {},
    }

    # Group by task type
    for task in results.values():
        task_type = task.type
        if task_type not in summary["by_type"]:
            summary["by_type"][task_type] = {"count": 0, "completed": 0, "failed": 0, "avg_time": 0}

        summary["by_type"][task_type]["count"] += 1
        if task.result and not task.error:
            summary["by_type"][task_type]["completed"] += 1
        else:
            summary["by_type"][task_type]["failed"] += 1

        # Store individual results
        summary["results"][task.id] = task.to_dict()

    return summary


# ---- 7. Main execution -----------------------------------------------------


async def main():
    """Main execution function"""
    # Example workload configuration
    workload_config = {
        "code_analysis": ["src/main.py", "src/utils.py", "src/models.py"],
        "implementation": [
            "user authentication system",
            "data validation layer",
            "caching mechanism",
        ],
        "documentation": ["API endpoints", "database schema", "deployment guide"],
    }

    # Generate tasks
    tasks = generate_tasks(workload_config)
    logger.info(f"Generated {len(tasks)} tasks")

    # Execute
    results, stats = await orchestrate(tasks)

    # Aggregate and save results
    summary = aggregate_results(results, stats)

    # Save to file
    output_path = Path("claude-task-delegator/shared/results/execution_summary.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        json.dump(summary, f, indent=2)

    logger.info(f"Execution complete. Results saved to {output_path}")

    # Print summary
    print("\n=== Execution Summary ===")
    print(f"Total tasks: {summary['task_summary']['total']}")
    print(f"Completed: {summary['task_summary']['completed']}")
    print(f"Failed: {summary['task_summary']['failed']}")
    print(f"Total time: {stats['total_execution_time']:.1f}s")
    print(f"Tasks/second: {stats['tasks_per_second']:.2f}")


if __name__ == "__main__":
    asyncio.run(main())
