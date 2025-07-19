"""Claude Task Delegator - Orchestrate multiple Claude CLI instances."""

__version__ = "0.2.0"

from .account_registry import AccountRegistry
from .core import Task, TaskLoader, SwarmOrchestrator, TaskStatus, TaskType
from .secure_runner import SecureClaudeRunner, PolicyEnforcer
from .api_adapter import HybridClaudeRunner, configure_claude_runner
from .monitor import MetricsCollector, LiveDashboard, MonitoredOrchestrator

__all__ = [
    "AccountRegistry",
    "Task",
    "TaskStatus",
    "TaskType",
    "TaskLoader",
    "SwarmOrchestrator",
    "SecureClaudeRunner",
    "PolicyEnforcer",
    "HybridClaudeRunner",
    "configure_claude_runner",
    "MetricsCollector",
    "LiveDashboard",
    "MonitoredOrchestrator",
]