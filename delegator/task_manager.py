#!/usr/bin/env python3
"""
Task Manager for Claude Delegator
Handles task distribution and monitoring
"""

import json
import os
import time
from datetime import datetime


class TaskManager:
    def __init__(self, config_path: str = "../config/delegator.json"):
        self.config_path = config_path
        self.tasks_dir = "../shared/tasks"
        self.results_dir = "../shared/results"
        self.active_tasks = {}
        self.load_config()

    def load_config(self):
        """Load delegator configuration"""
        if os.path.exists(self.config_path):
            with open(self.config_path) as f:
                self.config = json.load(f)
        else:
            self.config = {
                "max_concurrent_tasks": 5,
                "task_timeout": 3600,
                "worker_check_interval": 10,
            }

    def create_task(self, task_type: str, description: str, priority: int = 5) -> str:
        """Create a new task for workers"""
        task_id = f"task_{int(time.time())}_{os.urandom(4).hex()}"
        task = {
            "id": task_id,
            "type": task_type,
            "description": description,
            "priority": priority,
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            "assigned_to": None,
        }

        # Save task to shared directory
        task_path = os.path.join(self.tasks_dir, f"{task_id}.json")
        os.makedirs(self.tasks_dir, exist_ok=True)

        with open(task_path, "w") as f:
            json.dump(task, f, indent=2)

        self.active_tasks[task_id] = task
        return task_id

    def get_pending_tasks(self) -> list[dict]:
        """Get all pending tasks"""
        pending = []
        for _task_id, task in self.active_tasks.items():
            if task["status"] == "pending":
                pending.append(task)
        return sorted(pending, key=lambda x: x["priority"], reverse=True)

    def assign_task(self, task_id: str, worker_id: str):
        """Assign a task to a worker"""
        if task_id in self.active_tasks:
            self.active_tasks[task_id]["status"] = "assigned"
            self.active_tasks[task_id]["assigned_to"] = worker_id
            self.active_tasks[task_id]["assigned_at"] = datetime.now().isoformat()

            # Update task file
            task_path = os.path.join(self.tasks_dir, f"{task_id}.json")
            with open(task_path, "w") as f:
                json.dump(self.active_tasks[task_id], f, indent=2)

    def check_task_results(self):
        """Check for completed tasks in results directory"""
        os.makedirs(self.results_dir, exist_ok=True)

        for filename in os.listdir(self.results_dir):
            if filename.endswith(".json"):
                result_path = os.path.join(self.results_dir, filename)
                with open(result_path) as f:
                    result = json.load(f)

                task_id = result.get("task_id")
                if task_id in self.active_tasks:
                    self.active_tasks[task_id]["status"] = "completed"
                    self.active_tasks[task_id]["completed_at"] = result.get("completed_at")
                    print(f"Task {task_id} completed by {result.get('worker_id')}")


if __name__ == "__main__":
    # Example usage
    manager = TaskManager()

    # Create some example tasks
    task1 = manager.create_task("code_analysis", "Analyze the codebase structure", priority=8)
    task2 = manager.create_task("implementation", "Implement user authentication", priority=6)

    print(f"Created tasks: {task1}, {task2}")
    print(f"Pending tasks: {manager.get_pending_tasks()}")
