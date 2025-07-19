"""Real-time monitoring dashboard for task execution."""

import asyncio
import json
import logging
from collections import defaultdict, deque
from datetime import datetime
from typing import Any, cast

logger = logging.getLogger(__name__)


class MetricsCollector:
    """Collect and aggregate metrics from task execution."""

    def __init__(self, window_size: int = 100):
        self.window_size = window_size
        self.task_times: deque[float] = deque(maxlen=window_size)
        self.success_count = 0
        self.failure_count = 0
        self.worker_metrics: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "tasks_completed": 0,
                "tasks_failed": 0,
                "total_time": 0.0,
                "last_active": None,
            }
        )
        self.task_type_metrics: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"count": 0, "success": 0, "failed": 0, "avg_time": 0.0}
        )
        self.rate_limit_events: deque[tuple[datetime, str]] = deque(maxlen=50)
        self.start_time = datetime.now()

    def record_task_completion(
        self, task_id: str, worker_id: str, task_type: str, execution_time: float, success: bool
    ):
        """Record task completion metrics."""
        self.task_times.append(execution_time)

        if success:
            self.success_count += 1
            self.worker_metrics[worker_id]["tasks_completed"] += 1
            self.task_type_metrics[task_type]["success"] += 1
        else:
            self.failure_count += 1
            self.worker_metrics[worker_id]["tasks_failed"] += 1
            self.task_type_metrics[task_type]["failed"] += 1

        self.worker_metrics[worker_id]["total_time"] += execution_time
        self.worker_metrics[worker_id]["last_active"] = datetime.now()

        # Update task type metrics
        self.task_type_metrics[task_type]["count"] += 1
        type_metrics = self.task_type_metrics[task_type]
        type_metrics["avg_time"] = (
            type_metrics["avg_time"] * (type_metrics["count"] - 1) + execution_time
        ) / type_metrics["count"]

    def record_rate_limit(self, worker_id: str, retry_after: float):
        """Record rate limit event."""
        self.rate_limit_events.append((datetime.now(), worker_id))

    def get_summary(self) -> dict[str, Any]:
        """Get current metrics summary."""
        total_tasks = self.success_count + self.failure_count
        uptime = (datetime.now() - self.start_time).total_seconds()

        return {
            "overview": {
                "total_tasks": total_tasks,
                "success_count": self.success_count,
                "failure_count": self.failure_count,
                "success_rate": (self.success_count / total_tasks * 100) if total_tasks > 0 else 0,
                "uptime_seconds": uptime,
                "tasks_per_minute": (total_tasks / uptime * 60) if uptime > 0 else 0,
            },
            "performance": {
                "avg_execution_time": (
                    sum(self.task_times) / len(self.task_times) if self.task_times else 0
                ),
                "min_execution_time": min(self.task_times) if self.task_times else 0,
                "max_execution_time": max(self.task_times) if self.task_times else 0,
                "recent_tasks": len(self.task_times),
            },
            "workers": dict(self.worker_metrics),
            "task_types": dict(self.task_type_metrics),
            "rate_limits": {
                "recent_events": len(self.rate_limit_events),
                "last_event": self.rate_limit_events[-1] if self.rate_limit_events else None,
            },
        }


class LiveDashboard:
    """Simple text-based live dashboard."""

    def __init__(self, metrics_collector: MetricsCollector):
        self.metrics = metrics_collector
        self.running = False

    def format_duration(self, seconds: float) -> str:
        """Format duration in human-readable format."""
        if seconds < 60:
            return f"{seconds:.1f}s"
        elif seconds < 3600:
            return f"{seconds/60:.1f}m"
        else:
            return f"{seconds/3600:.1f}h"

    def render(self) -> str:
        """Render dashboard as text."""
        summary = self.metrics.get_summary()

        # Clear screen (ANSI escape code)
        output = ["\033[2J\033[H"]  # Clear screen and move cursor to top

        # Header
        output.append("=" * 60)
        output.append("CLAUDE TASK DELEGATOR - LIVE DASHBOARD")
        output.append("=" * 60)
        output.append("")

        # Overview
        overview = summary["overview"]
        output.append("OVERVIEW")
        output.append("-" * 30)
        output.append(f"Uptime: {self.format_duration(overview['uptime_seconds'])}")
        output.append(f"Total Tasks: {overview['total_tasks']}")
        output.append(f"Success: {overview['success_count']} ({overview['success_rate']:.1f}%)")
        output.append(f"Failed: {overview['failure_count']}")
        output.append(f"Throughput: {overview['tasks_per_minute']:.1f} tasks/min")
        output.append("")

        # Performance
        perf = summary["performance"]
        output.append("PERFORMANCE")
        output.append("-" * 30)
        output.append(f"Avg Time: {perf['avg_execution_time']:.1f}s")
        output.append(f"Min Time: {perf['min_execution_time']:.1f}s")
        output.append(f"Max Time: {perf['max_execution_time']:.1f}s")
        output.append("")

        # Workers
        output.append("WORKERS")
        output.append("-" * 30)
        output.append(f"{'Worker':<15} {'Completed':<10} {'Failed':<8} {'Avg Time':<10} {'Status'}")
        output.append("-" * 60)

        for worker_id, stats in summary["workers"].items():
            total = stats["tasks_completed"] + stats["tasks_failed"]
            avg_time = stats["total_time"] / total if total > 0 else 0
            last_active = stats["last_active"]

            if last_active:
                if isinstance(last_active, str):
                    last_active = datetime.fromisoformat(last_active)
                idle_time = (datetime.now() - last_active).total_seconds()
                status = "Active" if idle_time < 30 else f"Idle {self.format_duration(idle_time)}"
            else:
                status = "Inactive"

            output.append(
                f"{worker_id:<15} {stats['tasks_completed']:<10} "
                f"{stats['tasks_failed']:<8} {avg_time:<10.1f} {status}"
            )

        output.append("")

        # Task Types
        output.append("TASK TYPES")
        output.append("-" * 30)
        output.append(f"{'Type':<15} {'Count':<8} {'Success':<8} {'Failed':<8} {'Avg Time'}")
        output.append("-" * 50)

        for task_type, stats in summary["task_types"].items():
            output.append(
                f"{task_type:<15} {stats['count']:<8} {stats['success']:<8} "
                f"{stats['failed']:<8} {stats['avg_time']:.1f}s"
            )

        output.append("")

        # Rate Limits
        rate_limits = summary["rate_limits"]
        if rate_limits["recent_events"] > 0:
            output.append("RATE LIMITS")
            output.append("-" * 30)
            output.append(f"Recent Events: {rate_limits['recent_events']}")
            if rate_limits["last_event"]:
                output.append(
                    f"Last Event: {rate_limits['last_event']['worker_id']} "
                    f"(retry after {rate_limits['last_event']['retry_after']}s)"
                )

        output.append("")
        output.append(f"Last Update: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        return "\n".join(output)

    async def run(self, update_interval: float = 2.0):
        """Run the live dashboard."""
        self.running = True

        try:
            while self.running:
                print(self.render())
                await asyncio.sleep(update_interval)
        except KeyboardInterrupt:
            self.running = False
            print("\nDashboard stopped.")


class MonitoringServer:
    """
    Simple HTTP server for monitoring (optional).

    This provides a JSON endpoint for external monitoring tools.
    """

    def __init__(self, metrics_collector: MetricsCollector, port: int = 8888):
        self.metrics = metrics_collector
        self.port = port
        self.server: asyncio.Server | None = None

    async def handle_metrics(self, reader, writer):
        """Handle HTTP request for metrics."""
        try:
            # Read request (simple, just ignore it)
            await reader.read(1024)

            # Get metrics
            metrics_data = self.metrics.get_summary()
            response_body = json.dumps(metrics_data, indent=2, default=str)

            # Send HTTP response
            response = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: application/json\r\n"
                f"Content-Length: {len(response_body)}\r\n"
                "Access-Control-Allow-Origin: *\r\n"
                "\r\n"
                f"{response_body}"
            )

            writer.write(response.encode())
            await writer.drain()

        except Exception as e:
            logger.error(f"Error handling metrics request: {e}")
        finally:
            writer.close()
            await writer.wait_closed()

    async def start(self):
        """Start the monitoring server."""
        self.server = await asyncio.start_server(self.handle_metrics, "127.0.0.1", self.port)

        if self.server and self.server.sockets:
            addr = self.server.sockets[0].getsockname()
            logger.info(f"Monitoring server started at http://{addr[0]}:{addr[1]}/")

            async with self.server:
                await self.server.serve_forever()

    async def stop(self):
        """Stop the monitoring server."""
        if self.server:
            self.server.close()
            await self.server.wait_closed()


# Integration with orchestrator
class MonitoredOrchestrator:
    """Orchestrator with integrated monitoring."""

    def __init__(self, base_orchestrator, enable_dashboard: bool = False):
        self.base = base_orchestrator
        self.metrics = MetricsCollector()
        self.dashboard = LiveDashboard(self.metrics) if enable_dashboard else None
        self.monitoring_server: MonitoringServer | None = None

    async def orchestrate_with_monitoring(
        self, tasks: list[Any], enable_http_server: bool = False, server_port: int = 8888
    ) -> dict[str, Any]:
        """Run orchestration with monitoring enabled."""

        # Start monitoring server if requested
        server_task = None
        if enable_http_server:
            self.monitoring_server = MonitoringServer(self.metrics, server_port)
            server_task = asyncio.create_task(self.monitoring_server.start())

        # Start dashboard if enabled
        dashboard_task = None
        if self.dashboard:
            dashboard_task = asyncio.create_task(self.dashboard.run())

        try:
            # Run orchestration
            result = await self.base.orchestrate(tasks)

            # Update metrics from results
            for task_id, task_data in result.get("results", {}).items():
                if "completed_at" in task_data and "started_at" in task_data:
                    # Calculate execution time
                    start = datetime.fromisoformat(task_data["started_at"])
                    end = datetime.fromisoformat(task_data["completed_at"])
                    execution_time = (end - start).total_seconds()

                    self.metrics.record_task_completion(
                        task_id=task_id,
                        worker_id=task_data.get("assigned_to", "unknown"),
                        task_type=task_data.get("type", "general"),
                        execution_time=execution_time,
                        success=task_data.get("status") == "completed",
                    )

            # Add metrics to result
            result["metrics"] = self.metrics.get_summary()

            return cast(dict[str, Any], result)

        finally:
            # Stop monitoring components
            if dashboard_task and self.dashboard:
                self.dashboard.running = False
                dashboard_task.cancel()

            if server_task and self.monitoring_server:
                await self.monitoring_server.stop()
                server_task.cancel()


# Example usage
async def example_with_monitoring():
    """Example of using monitoring with orchestration."""
    from .account_registry import AccountRegistry
    from .core import SwarmOrchestrator, Task, TaskType

    # Setup
    registry = AccountRegistry()
    base_orchestrator = SwarmOrchestrator(registry)
    monitored = MonitoredOrchestrator(base_orchestrator, enable_dashboard=True)

    # Create tasks
    tasks = [Task(f"task_{i}", f"Process item {i}", TaskType.GENERAL) for i in range(10)]

    # Run with monitoring
    await monitored.orchestrate_with_monitoring(tasks, enable_http_server=True, server_port=8888)

    print("Execution complete!")
    print("Metrics available at: http://localhost:8888/")


if __name__ == "__main__":
    asyncio.run(example_with_monitoring())
