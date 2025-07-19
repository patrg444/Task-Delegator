"""Claude Task Delegator - Orchestrate multiple Claude CLI instances."""

__version__ = "0.1.0"

from .account_registry import AccountRegistry
from .core import Task, TaskLoader, SwarmOrchestrator
from .interactive import InteractiveWorker
from .shared_context import SharedContext

__all__ = [
    "AccountRegistry",
    "Task",
    "TaskLoader",
    "SwarmOrchestrator",
    "InteractiveWorker",
    "SharedContext",
]