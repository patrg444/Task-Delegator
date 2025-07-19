#!/usr/bin/env python3
"""
run_collaborative.py - Simple script to run collaborative swarm
"""

import asyncio
import sys
from pathlib import Path

from collaborative_swarm import CollaborativeSwarmManager, Task


async def main():
    # Check command line arguments
    if len(sys.argv) < 2:
        print("Usage: ./run_collaborative.py <project_name> [task_file]")
        print("Example: ./run_collaborative.py my-project tasks.json")
        sys.exit(1)

    project_name = sys.argv[1]
    task_file = sys.argv[2] if len(sys.argv) > 2 else None

    # Configure your Claude accounts here
    ACCOUNTS = {
        "worker_1": Path.home() / ".claude-work",
        "worker_2": Path.home() / ".claude-personal",
        # Add more accounts as needed
    }

    # Create manager
    print(f"Creating collaborative swarm for project: {project_name}")
    manager = CollaborativeSwarmManager(ACCOUNTS, github_user="patrg444")

    # Setup GitHub project
    print("Setting up GitHub repository...")
    try:
        project_info = await manager.setup_project(
            project_name, f"Collaborative development project: {project_name}"
        )
        print(f"✓ Created repository: {project_info['url']}")
    except Exception as e:
        print(f"✗ Failed to create repository: {e}")
        return

    # Initialize workers
    print(f"\nInitializing {len(ACCOUNTS)} workers...")
    if not await manager.initialize_workers():
        print("✗ Failed to initialize workers")
        return
    print("✓ Workers initialized with local workspaces")

    # Load or create tasks
    if task_file and Path(task_file).exists():
        # Load tasks from file
        from task_loader import TaskLoader

        task_data = TaskLoader.load_tasks(task_file)
        tasks = []
        for data in task_data:
            tasks.append(
                Task(
                    data.get("id", f"task_{len(tasks)}"),
                    data.get("prompt", ""),
                    data.get("type", "general"),
                    data.get("priority", 5),
                    data.get("weight", 1.0),
                )
            )
        print(f"\nLoaded {len(tasks)} tasks from {task_file}")
    else:
        # Default demo tasks
        tasks = [
            Task(
                "setup_structure",
                "Create the basic project structure with src/, tests/, and docs/ directories. Add a .gitignore file for Python projects.",
                "setup",
                priority=10,
                weight=1,
            ),
            Task(
                "create_models",
                "Create a User model class in src/models.py with fields: id, username, email, created_at",
                "implementation",
                priority=8,
                weight=2,
            ),
            Task(
                "create_utils",
                "Create utility functions in src/utils.py for: password hashing, email validation, and timestamp generation",
                "implementation",
                priority=7,
                weight=2,
            ),
            Task(
                "write_tests",
                "Write unit tests in tests/test_models.py to test the User model",
                "testing",
                priority=6,
                weight=2,
            ),
            Task(
                "create_readme",
                "Update the README.md with project description, installation instructions, and usage examples",
                "documentation",
                priority=5,
                weight=1,
            ),
        ]
        print(f"\nUsing {len(tasks)} demo tasks")

    # Execute tasks
    print("\nExecuting tasks collaboratively...")
    print("Each worker will:")
    print("  1. Clone the repository to their workspace")
    print("  2. Create a feature branch")
    print("  3. Complete their assigned task")
    print("  4. Push changes to their branch")
    print()

    results = await manager.orchestrate_tasks(tasks)

    # Print results
    stats = results["stats"]
    print(f"\n{'='*60}")
    print("EXECUTION COMPLETE")
    print(f"{'='*60}")
    print(f"Repository: {results['repository']['url']}")
    print(f"Total tasks: {stats['total_tasks']}")
    print(f"✓ Completed: {stats['completed']}")
    print(f"✗ Failed: {stats['failed']}")
    print(f"Duration: {stats['duration']:.1f} seconds")

    # Show task results
    print("\nTask Results:")
    for task_id, result in results["results"].items():
        status_icon = "✓" if result["status"] == "success" else "✗"
        worker = result.get("worker_id", "unknown")
        print(f"  {status_icon} {task_id} (by {worker})")
        if result.get("error"):
            print(f"    Error: {result['error']}")

    # Create pull requests
    if stats["completed"] > 0:
        print("\nCreating pull requests for completed work...")
        await manager.merge_worker_branches()
        print("✓ Pull requests created - review them on GitHub")

    print("\nNext steps:")
    print(f"1. Review the pull requests at {results['repository']['url']}/pulls")
    print("2. Merge approved changes")
    print(f"3. Run more tasks by calling: ./run_collaborative.py {project_name} <new_tasks.json>")


if __name__ == "__main__":
    asyncio.run(main())
