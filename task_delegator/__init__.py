"""Claude Task Delegator - Orchestrate multiple Claude CLI instances."""

__version__ = "0.2.0"

from .account_registry import AccountRegistry
from .api_adapter import HybridClaudeRunner, configure_claude_runner
from .core import SwarmOrchestrator, Task, TaskLoader, TaskStatus, TaskType
from .monitor import LiveDashboard, MetricsCollector, MonitoredOrchestrator
from .secure_runner import PolicyEnforcer, SecureClaudeRunner

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
