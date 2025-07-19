#!/usr/bin/env python3
"""
shared_context.py - Shared context and communication between workers
"""

import fcntl
import json
import logging
import os
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SharedContext:
    """Manages shared context between workers including GitHub repo info"""

    def __init__(self, base_dir: Path = Path("shared")):
        self.base_dir = base_dir
        self.context_file = base_dir / "context.json"
        self.messages_dir = base_dir / "messages"
        self.state_dir = base_dir / "state"

        # Create directories
        self.base_dir.mkdir(exist_ok=True)
        self.messages_dir.mkdir(exist_ok=True)
        self.state_dir.mkdir(exist_ok=True)

        # Initialize context
        self._init_context()

        # Lock for thread-safe operations
        self._lock = threading.Lock()

    def _init_context(self):
        """Initialize shared context file"""
        if not self.context_file.exists():
            initial_context = {
                "github_repo": None,
                "project_path": None,
                "workers": {},
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
            }
            self._write_json_atomic(self.context_file, initial_context)

    def _write_json_atomic(self, file_path: Path, data: dict):
        """Write JSON atomically with file locking"""
        temp_path = file_path.with_suffix(".tmp")

        with open(temp_path, "w") as f:
            # Acquire exclusive lock
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

        # Atomic rename
        temp_path.rename(file_path)

    def _read_json_safe(self, file_path: Path) -> dict:
        """Read JSON with file locking"""
        with open(file_path) as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                return json.load(f)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def set_github_repo(self, repo_url: str, local_path: str):
        """Set the GitHub repository information"""
        context = self._read_json_safe(self.context_file)
        context["github_repo"] = repo_url
        context["project_path"] = local_path
        context["updated_at"] = datetime.now().isoformat()
        self._write_json_atomic(self.context_file, context)

        logger.info(f"Set GitHub repo: {repo_url} at {local_path}")

    def get_github_repo(self) -> dict[str, str] | None:
        """Get GitHub repository information"""
        context = self._read_json_safe(self.context_file)
        if context.get("github_repo"):
            return {"url": context["github_repo"], "path": context["project_path"]}
        return None

    def register_worker(self, worker_id: str, config_dir: str):
        """Register a worker in the shared context"""
        context = self._read_json_safe(self.context_file)
        context["workers"][worker_id] = {
            "config_dir": config_dir,
            "registered_at": datetime.now().isoformat(),
            "last_seen": datetime.now().isoformat(),
            "status": "active",
        }
        context["updated_at"] = datetime.now().isoformat()
        self._write_json_atomic(self.context_file, context)

    def update_worker_status(self, worker_id: str, status: str, task_id: str | None = None):
        """Update worker status"""
        state_file = self.state_dir / f"{worker_id}.json"
        state = {
            "worker_id": worker_id,
            "status": status,
            "current_task": task_id,
            "updated_at": datetime.now().isoformat(),
        }
        self._write_json_atomic(state_file, state)

    def send_message(self, from_worker: str, to_worker: str | None, message: dict[str, Any]):
        """Send a message between workers"""
        msg_id = f"{int(time.time())}_{from_worker}"
        message_data = {
            "id": msg_id,
            "from": from_worker,
            "to": to_worker,  # None means broadcast
            "message": message,
            "timestamp": datetime.now().isoformat(),
            "read_by": [],
        }

        msg_file = self.messages_dir / f"{msg_id}.json"
        self._write_json_atomic(msg_file, message_data)

        logger.info(f"Message sent from {from_worker} to {to_worker or 'all'}")

    def get_messages(self, worker_id: str, mark_read: bool = True) -> list[dict[str, Any]]:
        """Get messages for a worker"""
        messages = []

        for msg_file in self.messages_dir.glob("*.json"):
            try:
                msg_data = self._read_json_safe(msg_file)

                # Check if message is for this worker
                if (
                    msg_data["to"] is None or msg_data["to"] == worker_id
                ) and worker_id not in msg_data["read_by"]:
                    messages.append(msg_data)

                    if mark_read:
                        # Mark as read
                        msg_data["read_by"].append(worker_id)
                        self._write_json_atomic(msg_file, msg_data)

            except Exception as e:
                logger.error(f"Error reading message {msg_file}: {e}")

        return sorted(messages, key=lambda x: x["timestamp"])

    def get_all_worker_states(self) -> dict[str, dict[str, Any]]:
        """Get current state of all workers"""
        states = {}

        for state_file in self.state_dir.glob("*.json"):
            try:
                worker_id = state_file.stem
                state = self._read_json_safe(state_file)
                states[worker_id] = state
            except Exception as e:
                logger.error(f"Error reading state for {worker_id}: {e}")

        return states


class GitHubProjectManager:
    """Manages GitHub repository setup and synchronization"""

    def __init__(self, shared_context: SharedContext):
        self.context = shared_context

    def create_github_repo(
        self, repo_name: str, description: str = "", private: bool = True
    ) -> dict[str, str]:
        """Create a new GitHub repository"""
        cmd = [
            "gh",
            "repo",
            "create",
            repo_name,
            "--description",
            description,
            "--private" if private else "--public",
            "--clone",
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            raise Exception(f"Failed to create repo: {result.stderr}")

        # Parse output to get repo URL
        output_lines = result.stdout.strip().split("\n")
        repo_url = None
        for line in output_lines:
            if line.startswith("https://github.com/"):
                repo_url = line.strip()
                break

        if not repo_url:
            # Try to construct URL
            username = subprocess.run(
                ["gh", "api", "user", "--jq", ".login"], capture_output=True, text=True
            ).stdout.strip()
            repo_url = f"https://github.com/{username}/{repo_name}"

        # Get local path
        local_path = os.path.abspath(repo_name)

        # Store in shared context
        self.context.set_github_repo(repo_url, local_path)

        return {"url": repo_url, "path": local_path}

    def clone_repo_for_worker(self, worker_id: str, worker_dir: Path) -> str:
        """Clone the shared repository for a worker"""
        repo_info = self.context.get_github_repo()
        if not repo_info:
            raise Exception("No GitHub repository configured")

        # Create worker-specific clone
        clone_path = worker_dir / f"workspace_{worker_id}"
        clone_path.parent.mkdir(exist_ok=True)

        cmd = ["git", "clone", repo_info["url"], str(clone_path)]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            raise Exception(f"Failed to clone repo: {result.stderr}")

        logger.info(f"Cloned repo for worker {worker_id} at {clone_path}")
        return str(clone_path)

    def sync_worker_changes(self, worker_id: str, worker_path: str, commit_message: str):
        """Sync worker changes back to GitHub"""
        # Stage all changes
        subprocess.run(["git", "add", "-A"], cwd=worker_path, check=True)

        # Commit with worker ID
        commit_msg = f"[{worker_id}] {commit_message}"
        subprocess.run(["git", "commit", "-m", commit_msg], cwd=worker_path, check=True)

        # Pull latest changes (rebase to avoid merge commits)
        subprocess.run(["git", "pull", "--rebase"], cwd=worker_path, check=True)

        # Push changes
        subprocess.run(["git", "push"], cwd=worker_path, check=True)

        logger.info(f"Synced changes from worker {worker_id}")


class WorkerCommunicator:
    """Handles communication for a specific worker"""

    def __init__(self, worker_id: str, shared_context: SharedContext):
        self.worker_id = worker_id
        self.context = shared_context
        self.github_manager = GitHubProjectManager(shared_context)

    def setup_workspace(self) -> str:
        """Set up workspace by cloning the shared repository"""
        worker_dir = Path(f"workers/{self.worker_id}")
        return self.github_manager.clone_repo_for_worker(self.worker_id, worker_dir)

    def broadcast_message(self, message_type: str, data: Any):
        """Broadcast a message to all workers"""
        message = {"type": message_type, "data": data}
        self.context.send_message(self.worker_id, None, message)

    def send_to_worker(self, target_worker: str, message_type: str, data: Any):
        """Send a message to a specific worker"""
        message = {"type": message_type, "data": data}
        self.context.send_message(self.worker_id, target_worker, message)

    def check_messages(self) -> list[dict[str, Any]]:
        """Check for new messages"""
        return self.context.get_messages(self.worker_id)

    def update_status(self, status: str, task_id: str | None = None):
        """Update this worker's status"""
        self.context.update_worker_status(self.worker_id, status, task_id)

    def sync_code_changes(self, workspace_path: str, message: str):
        """Sync code changes to GitHub"""
        self.github_manager.sync_worker_changes(self.worker_id, workspace_path, message)


# Example enhanced task prompt that includes repository context
def create_task_prompt_with_context(task_description: str, repo_info: dict[str, str]) -> str:
    """Create a task prompt that includes repository context"""
    return f"""You are working on a shared GitHub repository with other Claude instances.

Repository: {repo_info['url']}
Local path: {repo_info['path']}

IMPORTANT:
- Always work within the repository directory
- Commit your changes frequently with descriptive messages
- Pull latest changes before starting major work
- Coordinate with other workers via the messaging system

Task: {task_description}

Please complete this task, making sure to:
1. Navigate to the repository directory first
2. Pull the latest changes
3. Implement the required functionality
4. Test your changes
5. Commit with a clear message
6. Push your changes
"""
