#!/usr/bin/env python3
"""
collaborative_swarm.py - Full collaborative swarm with GitHub integration
"""

import asyncio
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from async_swarm import Task
from interactive_worker import InteractiveWorker
from shared_context import GitHubProjectManager, SharedContext, WorkerCommunicator

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class CollaborativeWorker(InteractiveWorker):
    """Enhanced worker with collaboration capabilities"""

    def __init__(self, name: str, config_dir: Path, shared_context: SharedContext):
        super().__init__(name, config_dir)
        self.shared_context = shared_context
        self.communicator = WorkerCommunicator(name, shared_context)
        self.workspace_path = None

    async def setup_workspace(self):
        """Set up worker's workspace by cloning the shared repository"""
        try:
            self.workspace_path = self.communicator.setup_workspace()
            logger.info(f"[{self.name}] Workspace set up at {self.workspace_path}")
            return True
        except Exception as e:
            logger.error(f"[{self.name}] Failed to set up workspace: {e}")
            return False

    async def execute_collaborative_task(self, task: dict) -> dict:
        """Execute a task with collaboration features"""
        # Update status
        self.communicator.update_status("starting", task.get("id"))

        # Check for messages before starting
        messages = self.communicator.check_messages()
        for msg in messages:
            logger.info(f"[{self.name}] Message from {msg['from']}: {msg['message']['type']}")

        # Get repository info
        repo_info = self.shared_context.get_github_repo()
        if not repo_info:
            return {
                "task_id": task.get("id"),
                "worker_id": self.name,
                "status": "error",
                "error": "No GitHub repository configured",
            }

        # Enhance task prompt with repository context
        original_prompt = task.get("prompt", "")
        enhanced_prompt = f"""You are working on a shared GitHub repository with other Claude instances.

Repository: {repo_info['url']}
Local workspace: {self.workspace_path}
GitHub username: patrg444

IMPORTANT INSTRUCTIONS:
1. First, navigate to your workspace directory: cd {self.workspace_path}
2. Pull the latest changes: git pull origin main
3. Create a new branch for your work: git checkout -b {self.name}-{task.get('id')}
4. Complete the task as described below
5. Commit your changes with descriptive messages
6. Push your branch: git push -u origin {self.name}-{task.get('id')}
7. DO NOT create a pull request - just push the branch

Original task: {original_prompt}

Remember:
- Work only within your workspace directory
- Make atomic commits for each logical change
- Include the task ID in your commit messages
- Coordinate with other workers if you see conflicts
"""

        # Update task with enhanced prompt
        task["prompt"] = enhanced_prompt

        # Update status
        self.communicator.update_status("working", task.get("id"))

        # Execute the task
        result = await self.execute_task(task)

        # Broadcast completion
        if result.get("status") == "success":
            self.communicator.broadcast_message(
                "task_completed",
                {
                    "task_id": task.get("id"),
                    "worker": self.name,
                    "branch": f"{self.name}-{task.get('id')}",
                },
            )

        # Update final status
        self.communicator.update_status("idle", None)

        return result


class CollaborativeSwarmManager:
    """Manages a collaborative swarm with GitHub integration"""

    def __init__(self, accounts: dict[str, Path], github_user: str = "patrg444"):
        self.accounts = accounts
        self.github_user = github_user
        self.shared_context = SharedContext()
        self.github_manager = GitHubProjectManager(self.shared_context)
        self.workers = {}
        self.project_name = None

    async def setup_project(self, project_name: str, description: str = ""):
        """Set up a new GitHub project for collaboration"""
        self.project_name = project_name

        logger.info(f"Creating GitHub repository: {project_name}")

        try:
            # Create GitHub repo
            repo_info = self.github_manager.create_github_repo(
                project_name,
                description or "Collaborative project managed by Claude swarm",
                private=True,
            )

            logger.info(f"Created repository: {repo_info['url']}")

            # Initialize with README
            readme_path = Path(repo_info["path"]) / "README.md"
            readme_content = f"""# {project_name}

{description}

## Collaborative Development

This project is being developed collaboratively by multiple Claude instances.

### Workers
- Each worker operates on their own branch
- Changes are integrated through pull requests
- Coordination happens through the shared context system

### Structure
- `/src` - Source code
- `/tests` - Test files
- `/docs` - Documentation

Generated by Claude Task Delegator
"""

            readme_path.write_text(readme_content)

            # Initial commit
            subprocess.run(["git", "add", "README.md"], cwd=repo_info["path"], check=True)
            subprocess.run(
                ["git", "commit", "-m", "Initial commit - project setup"],
                cwd=repo_info["path"],
                check=True,
            )
            subprocess.run(
                ["git", "push", "-u", "origin", "main"], cwd=repo_info["path"], check=True
            )

            # Create basic directory structure
            for dir_name in ["src", "tests", "docs"]:
                dir_path = Path(repo_info["path"]) / dir_name
                dir_path.mkdir(exist_ok=True)
                (dir_path / ".gitkeep").touch()

            subprocess.run(["git", "add", "."], cwd=repo_info["path"], check=True)
            subprocess.run(
                ["git", "commit", "-m", "Add project structure"], cwd=repo_info["path"], check=True
            )
            subprocess.run(["git", "push"], cwd=repo_info["path"], check=True)

            return repo_info

        except Exception as e:
            logger.error(f"Failed to setup project: {e}")
            raise

    async def initialize_workers(self):
        """Initialize all workers with workspaces"""
        tasks = []

        for name, config_dir in self.accounts.items():
            # Register worker
            self.shared_context.register_worker(name, str(config_dir))

            # Create worker
            worker = CollaborativeWorker(name, config_dir, self.shared_context)
            self.workers[name] = worker

            # Setup workspace
            tasks.append(worker.setup_workspace())

        results = await asyncio.gather(*tasks)

        successful = sum(1 for r in results if r)
        logger.info(f"Initialized {successful}/{len(self.workers)} workers successfully")

        return successful > 0

    async def orchestrate_tasks(self, tasks: list[Task]) -> dict[str, Any]:
        """Orchestrate collaborative task execution"""
        if not self.workers:
            raise Exception("No workers initialized")

        # Create task queue
        task_queue = asyncio.Queue()
        for task in tasks:
            await task_queue.put(task)

        # Add sentinels
        for _ in self.workers:
            await task_queue.put(None)

        # Results collection
        results = {}
        stats = {
            "total_tasks": len(tasks),
            "completed": 0,
            "failed": 0,
            "start_time": datetime.now(),
        }

        async def worker_loop(worker: CollaborativeWorker):
            """Worker execution loop"""
            while True:
                task = await task_queue.get()

                if task is None:
                    break

                try:
                    result = await worker.execute_collaborative_task(task.to_dict())
                    results[task.id] = result

                    if result.get("status") == "success":
                        stats["completed"] += 1
                    else:
                        stats["failed"] += 1

                except Exception as e:
                    logger.error(f"[{worker.name}] Task failed: {e}")
                    results[task.id] = {
                        "task_id": task.id,
                        "worker_id": worker.name,
                        "status": "error",
                        "error": str(e),
                    }
                    stats["failed"] += 1

                finally:
                    task_queue.task_done()

        # Start all workers
        worker_tasks = []
        for worker in self.workers.values():
            worker_task = asyncio.create_task(worker_loop(worker))
            worker_tasks.append(worker_task)

        # Wait for completion
        await asyncio.gather(*worker_tasks)

        stats["end_time"] = datetime.now()
        stats["duration"] = (stats["end_time"] - stats["start_time"]).total_seconds()

        return {
            "results": results,
            "stats": stats,
            "repository": self.shared_context.get_github_repo(),
            "worker_states": self.shared_context.get_all_worker_states(),
        }

    async def merge_worker_branches(self):
        """Create pull requests for all worker branches"""
        repo_info = self.shared_context.get_github_repo()
        if not repo_info:
            logger.error("No repository configured")
            return

        # Get all branches
        result = subprocess.run(
            ["git", "branch", "-r"], cwd=repo_info["path"], capture_output=True, text=True
        )

        branches = [b.strip() for b in result.stdout.split("\n") if b.strip()]
        worker_branches = [b for b in branches if any(w in b for w in self.workers)]

        logger.info(f"Found {len(worker_branches)} worker branches to merge")

        # Create PRs for each branch
        for branch in worker_branches:
            branch_name = branch.replace("origin/", "")
            if branch_name == "main":
                continue

            try:
                # Create pull request
                pr_result = subprocess.run(
                    [
                        "gh",
                        "pr",
                        "create",
                        "--base",
                        "main",
                        "--head",
                        branch_name,
                        "--title",
                        f"Merge {branch_name}",
                        "--body",
                        f"Automated merge of worker branch {branch_name}",
                    ],
                    cwd=repo_info["path"],
                    capture_output=True,
                    text=True,
                )

                if pr_result.returncode == 0:
                    logger.info(f"Created PR for branch {branch_name}")
                else:
                    logger.error(f"Failed to create PR for {branch_name}: {pr_result.stderr}")

            except Exception as e:
                logger.error(f"Error creating PR for {branch_name}: {e}")


# Example usage
async def main():
    """Example collaborative swarm execution"""

    # Configure accounts
    accounts = {
        "worker_1": Path.home() / ".claude-work",
        "worker_2": Path.home() / ".claude-personal",
    }

    # Create manager
    manager = CollaborativeSwarmManager(accounts, github_user="patrg444")

    # Setup project
    project_info = await manager.setup_project(
        "collaborative-demo", "Demo project for collaborative Claude development"
    )

    print(f"Created project: {project_info['url']}")

    # Initialize workers
    if not await manager.initialize_workers():
        print("Failed to initialize workers")
        return

    # Create tasks
    tasks = [
        Task(
            "feat_auth",
            "Implement user authentication with JWT tokens in src/auth.py",
            "implementation",
            priority=9,
            weight=3,
        ),
        Task(
            "feat_api",
            "Create REST API endpoints for user management in src/api.py",
            "implementation",
            priority=8,
            weight=2.5,
        ),
        Task(
            "test_auth",
            "Write comprehensive tests for authentication in tests/test_auth.py",
            "testing",
            priority=7,
            weight=2,
        ),
        Task(
            "doc_api",
            "Document all API endpoints in docs/api.md",
            "documentation",
            priority=6,
            weight=1.5,
        ),
    ]

    # Execute tasks
    print(f"\nExecuting {len(tasks)} tasks collaboratively...")
    results = await manager.orchestrate_tasks(tasks)

    # Print summary
    stats = results["stats"]
    print(f"\n{'='*60}")
    print("EXECUTION SUMMARY")
    print(f"{'='*60}")
    print(f"Total tasks: {stats['total_tasks']}")
    print(f"Completed: {stats['completed']}")
    print(f"Failed: {stats['failed']}")
    print(f"Duration: {stats['duration']:.1f}s")
    print(f"Repository: {results['repository']['url']}")

    # Optionally merge branches
    print("\nCreating pull requests for worker branches...")
    await manager.merge_worker_branches()


if __name__ == "__main__":
    asyncio.run(main())
