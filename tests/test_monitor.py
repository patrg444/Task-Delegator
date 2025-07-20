"""Tests for the monitoring module."""

import asyncio
import contextlib
import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from task_delegator.monitor import (
    LiveDashboard,
    MetricsCollector,
    MonitoredOrchestrator,
    MonitoringServer,
    example_with_monitoring,
)


class TestMetricsCollector:
    """Test the metrics collector."""

    @pytest.fixture
    def collector(self):
        """Create a metrics collector."""
        return MetricsCollector(window_size=10)

    def test_init(self, collector):
        """Test initialization."""
        assert collector.window_size == 10
        assert collector.success_count == 0
        assert collector.failure_count == 0
        assert len(collector.task_times) == 0
        assert isinstance(collector.start_time, datetime)

    def test_record_task_completion_success(self, collector):
        """Test recording successful task completion."""
        collector.record_task_completion(
            task_id="task_1",
            worker_id="worker_1",
            task_type="general",
            execution_time=5.0,
            success=True,
        )

        assert collector.success_count == 1
        assert collector.failure_count == 0
        assert len(collector.task_times) == 1
        assert collector.task_times[0] == 5.0

        # Check worker metrics
        assert collector.worker_metrics["worker_1"]["tasks_completed"] == 1
        assert collector.worker_metrics["worker_1"]["tasks_failed"] == 0
        assert collector.worker_metrics["worker_1"]["total_time"] == 5.0
        assert collector.worker_metrics["worker_1"]["last_active"] is not None

        # Check task type metrics
        assert collector.task_type_metrics["general"]["count"] == 1
        assert collector.task_type_metrics["general"]["success"] == 1
        assert collector.task_type_metrics["general"]["failed"] == 0
        assert collector.task_type_metrics["general"]["avg_time"] == 5.0

    def test_record_task_completion_failure(self, collector):
        """Test recording failed task completion."""
        collector.record_task_completion(
            task_id="task_1",
            worker_id="worker_1",
            task_type="general",
            execution_time=3.0,
            success=False,
        )

        assert collector.success_count == 0
        assert collector.failure_count == 1
        assert collector.worker_metrics["worker_1"]["tasks_completed"] == 0
        assert collector.worker_metrics["worker_1"]["tasks_failed"] == 1
        assert collector.task_type_metrics["general"]["success"] == 0
        assert collector.task_type_metrics["general"]["failed"] == 1

    def test_record_multiple_tasks(self, collector):
        """Test recording multiple tasks."""
        # Record several tasks
        for i in range(5):
            collector.record_task_completion(
                task_id=f"task_{i}",
                worker_id=f"worker_{i % 2}",
                task_type="general" if i % 2 == 0 else "special",
                execution_time=float(i + 1),
                success=i % 3 != 0,  # Fail every 3rd task
            )

        assert collector.success_count == 3
        assert collector.failure_count == 2
        assert len(collector.task_times) == 5

        # Check task type metrics averaging
        general_metrics = collector.task_type_metrics["general"]
        assert general_metrics["count"] == 3
        assert general_metrics["avg_time"] == pytest.approx(3.0)  # (1+3+5)/3

    def test_record_rate_limit(self, collector):
        """Test recording rate limit events."""
        assert len(collector.rate_limit_events) == 0

        collector.record_rate_limit("worker_1", 30.0)
        assert len(collector.rate_limit_events) == 1
        assert collector.rate_limit_events[0][1] == "worker_1"

    def test_window_size_limit(self, collector):
        """Test that window size is respected."""
        # Record more tasks than window size
        for i in range(15):
            collector.record_task_completion(
                task_id=f"task_{i}",
                worker_id="worker_1",
                task_type="general",
                execution_time=float(i),
                success=True,
            )

        # Should only keep last 10
        assert len(collector.task_times) == 10
        assert collector.task_times[0] == 5.0  # First 5 were dropped

    def test_get_summary(self, collector):
        """Test getting metrics summary."""
        # Record some tasks
        collector.record_task_completion("t1", "w1", "type1", 5.0, True)
        collector.record_task_completion("t2", "w1", "type1", 10.0, True)
        collector.record_task_completion("t3", "w2", "type2", 7.0, False)
        collector.record_rate_limit("w1", 30.0)

        summary = collector.get_summary()

        # Check overview
        assert summary["overview"]["total_tasks"] == 3
        assert summary["overview"]["success_count"] == 2
        assert summary["overview"]["failure_count"] == 1
        assert summary["overview"]["success_rate"] == pytest.approx(66.67, rel=0.1)

        # Check performance
        assert summary["performance"]["avg_execution_time"] == pytest.approx(7.33, rel=0.1)
        assert summary["performance"]["min_execution_time"] == 5.0
        assert summary["performance"]["max_execution_time"] == 10.0
        assert summary["performance"]["recent_tasks"] == 3

        # Check workers
        assert "w1" in summary["workers"]
        assert "w2" in summary["workers"]

        # Check task types
        assert "type1" in summary["task_types"]
        assert "type2" in summary["task_types"]

        # Check rate limits
        assert summary["rate_limits"]["recent_events"] == 1
        # last_event is a tuple (datetime, worker_id)
        assert isinstance(summary["rate_limits"]["last_event"], tuple)
        assert summary["rate_limits"]["last_event"][1] == "w1"

    def test_get_summary_empty(self, collector):
        """Test getting summary with no data."""
        summary = collector.get_summary()

        assert summary["overview"]["total_tasks"] == 0
        assert summary["overview"]["success_rate"] == 0
        assert summary["performance"]["avg_execution_time"] == 0
        assert summary["performance"]["min_execution_time"] == 0
        assert summary["performance"]["max_execution_time"] == 0


class TestLiveDashboard:
    """Test the live dashboard."""

    @pytest.fixture
    def dashboard(self):
        """Create a dashboard with collector."""
        collector = MetricsCollector()
        return LiveDashboard(collector)

    def test_format_duration(self, dashboard):
        """Test duration formatting."""
        assert dashboard.format_duration(30) == "30.0s"
        assert dashboard.format_duration(90) == "1.5m"
        assert dashboard.format_duration(3900) == "1.1h"

    def test_render_empty(self, dashboard):
        """Test rendering with no data."""
        output = dashboard.render()

        assert "CLAUDE TASK DELEGATOR - LIVE DASHBOARD" in output
        assert "OVERVIEW" in output
        assert "PERFORMANCE" in output
        assert "WORKERS" in output
        assert "TASK TYPES" in output

    def test_render_with_data(self, dashboard):
        """Test rendering with metrics data."""
        # Add some data
        dashboard.metrics.record_task_completion("t1", "worker_1", "general", 5.0, True)
        dashboard.metrics.record_task_completion("t2", "worker_2", "special", 7.0, False)
        dashboard.metrics.record_rate_limit("worker_1", 30.0)

        output = dashboard.render()

        assert "Total Tasks: 2" in output
        assert "Success: 1" in output
        assert "Failed: 1" in output
        assert "worker_1" in output
        assert "worker_2" in output
        assert "general" in output
        assert "special" in output
        assert "RATE LIMITS" in output
        assert "Last Event: worker_1" in output

    @pytest.mark.asyncio
    async def test_run_and_stop(self, dashboard):
        """Test running and stopping the dashboard."""
        dashboard.running = True

        # Create a task that stops after one iteration
        async def stop_after_delay():
            await asyncio.sleep(0.1)
            dashboard.running = False

        # Run dashboard with stopper
        with patch("builtins.print"):  # Suppress output
            await asyncio.gather(
                dashboard.run(update_interval=0.05),
                stop_after_delay(),
            )

        assert dashboard.running is False

    @pytest.mark.asyncio
    async def test_keyboard_interrupt(self, dashboard):
        """Test handling keyboard interrupt."""
        with patch("builtins.print") as mock_print:
            # Simulate KeyboardInterrupt
            with patch("asyncio.sleep", side_effect=KeyboardInterrupt):
                await dashboard.run()

            # Check that proper message was printed
            mock_print.assert_any_call("\nDashboard stopped.")


class TestMonitoringServer:
    """Test the monitoring HTTP server."""

    @pytest.fixture
    def server(self):
        """Create a monitoring server."""
        collector = MetricsCollector()
        return MonitoringServer(collector, port=8889)

    @pytest.mark.asyncio
    async def test_handle_metrics(self, server):
        """Test handling metrics request."""
        # Mock reader and writer
        reader = AsyncMock()
        reader.read.return_value = b"GET /metrics HTTP/1.1\r\n\r\n"

        writer = AsyncMock()
        writer.write = MagicMock()

        # Add some data
        server.metrics.record_task_completion("t1", "w1", "general", 5.0, True)

        await server.handle_metrics(reader, writer)

        # Check response was written
        writer.write.assert_called_once()
        response = writer.write.call_args[0][0].decode()
        assert "HTTP/1.1 200 OK" in response
        assert "Content-Type: application/json" in response
        assert "Access-Control-Allow-Origin: *" in response

        # Check JSON content
        body_start = response.find("\r\n\r\n") + 4
        body = response[body_start:]
        data = json.loads(body)
        assert data["overview"]["total_tasks"] == 1

    @pytest.mark.asyncio
    async def test_handle_metrics_error(self, server):
        """Test error handling in metrics request."""
        # Mock reader and writer with error
        reader = AsyncMock()
        reader.read.side_effect = Exception("Test error")
        writer = AsyncMock()

        with patch("task_delegator.monitor.logger") as mock_logger:
            await server.handle_metrics(reader, writer)
            mock_logger.error.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_stop(self, server):
        """Test starting and stopping the server."""
        # Mock the server creation
        mock_server = AsyncMock()
        mock_server.sockets = [MagicMock()]
        mock_server.sockets[0].getsockname.return_value = ("127.0.0.1", 8889)

        with patch("asyncio.start_server", return_value=mock_server):
            # Start server in background
            server_task = asyncio.create_task(server.start())

            # Wait a bit then stop
            await asyncio.sleep(0.1)
            await server.stop()

            # Cancel the server task
            server_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await server_task

        mock_server.close.assert_called_once()


class TestLiveDashboard2:
    """Additional tests for LiveDashboard."""

    @pytest.fixture
    def dashboard(self):
        """Create a dashboard with collector."""
        collector = MetricsCollector()
        return LiveDashboard(collector)

    def test_render_with_string_last_active(self, dashboard):
        """Test rendering when last_active is a string (ISO format)."""
        # Add worker data with string timestamp
        dashboard.metrics.worker_metrics["worker_1"] = {
            "tasks_completed": 5,
            "tasks_failed": 0,
            "total_time": 25.0,
            "last_active": datetime.now().isoformat(),  # String timestamp
        }

        output = dashboard.render()

        assert "worker_1" in output
        assert "5" in output  # tasks_completed
        # Should handle string timestamp conversion
        assert "Active" in output or "Idle" in output

    def test_render_with_inactive_worker(self, dashboard):
        """Test rendering with worker that has no last_active."""
        # Add worker data with no last_active
        dashboard.metrics.worker_metrics["worker_1"] = {
            "tasks_completed": 0,
            "tasks_failed": 0,
            "total_time": 0.0,
            "last_active": None,
        }

        output = dashboard.render()

        assert "worker_1" in output
        assert "Inactive" in output


class TestMonitoredOrchestrator:
    """Test the monitored orchestrator."""

    @pytest.fixture
    def orchestrator(self):
        """Create a monitored orchestrator."""
        base = MagicMock()
        return MonitoredOrchestrator(base, enable_dashboard=False)

    @pytest.mark.asyncio
    async def test_orchestrate_basic(self, orchestrator):
        """Test basic orchestration with monitoring."""
        # Mock base orchestrator response
        orchestrator.base.orchestrate = AsyncMock(
            return_value={
                "success": True,
                "results": {
                    "task_1": {
                        "started_at": "2024-01-01T10:00:00",
                        "completed_at": "2024-01-01T10:00:05",
                        "assigned_to": "worker_1",
                        "type": "general",
                        "status": "completed",
                    }
                },
            }
        )

        tasks = ["task1", "task2"]
        result = await orchestrator.orchestrate_with_monitoring(tasks)

        assert result["success"] is True
        assert "metrics" in result
        assert orchestrator.metrics.success_count == 1

    @pytest.mark.asyncio
    async def test_orchestrate_with_http_server(self, orchestrator):
        """Test orchestration with HTTP server enabled."""
        orchestrator.base.orchestrate = AsyncMock(return_value={"success": True, "results": {}})

        # Mock the monitoring server
        with patch("task_delegator.monitor.MonitoringServer") as mock_server_class:
            mock_server = AsyncMock()
            mock_server_class.return_value = mock_server

            await orchestrator.orchestrate_with_monitoring(
                ["task"], enable_http_server=True, server_port=8890
            )

            mock_server_class.assert_called_once_with(orchestrator.metrics, 8890)
            mock_server.start.assert_called_once()
            mock_server.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_orchestrate_with_dashboard(self, orchestrator):
        """Test orchestration with dashboard enabled."""
        orchestrator.base.orchestrate = AsyncMock(return_value={"success": True, "results": {}})
        orchestrator.dashboard = MagicMock()
        orchestrator.dashboard.run = AsyncMock()

        await orchestrator.orchestrate_with_monitoring(["task"])

        orchestrator.dashboard.run.assert_called_once()
        assert orchestrator.dashboard.running is False

    @pytest.mark.asyncio
    async def test_cleanup_on_error(self, orchestrator):
        """Test cleanup when orchestration fails."""
        orchestrator.base.orchestrate = AsyncMock(side_effect=Exception("Test error"))
        orchestrator.dashboard = MagicMock()
        orchestrator.dashboard.run = AsyncMock()

        with pytest.raises(Exception, match="Test error"):
            await orchestrator.orchestrate_with_monitoring(["task"], enable_http_server=True)

        # Ensure cleanup happened
        assert orchestrator.dashboard.running is False


@pytest.mark.asyncio
async def test_example_with_monitoring():
    """Test the example monitoring function."""
    # The imports happen inside the function, so we need to patch there
    with (
        patch("task_delegator.account_registry.AccountRegistry") as mock_registry_class,
        patch("task_delegator.core.SwarmOrchestrator") as mock_orchestrator_class,
        patch("task_delegator.core.Task") as mock_task_class,
        patch("builtins.print") as mock_print,
    ):
        # Setup mocks
        mock_registry = mock_registry_class.return_value

        # Mock MonitoredOrchestrator with proper async method
        mock_monitored = MagicMock()
        mock_monitored.orchestrate_with_monitoring = AsyncMock()

        # Patch MonitoredOrchestrator in the monitor module
        with patch("task_delegator.monitor.MonitoredOrchestrator", return_value=mock_monitored):
            # Mock Task creation
            mock_task_class.side_effect = lambda task_id, prompt, task_type: MagicMock(
                id=task_id, prompt=prompt, task_type=task_type
            )

            # Run the example
            await example_with_monitoring()

            # Verify it was called correctly
            mock_registry_class.assert_called_once()
            mock_orchestrator_class.assert_called_once_with(mock_registry)

            # Check that tasks were created
            assert mock_task_class.call_count == 10

            # Check that monitoring was called
            mock_monitored.orchestrate_with_monitoring.assert_called_once()
            call_args = mock_monitored.orchestrate_with_monitoring.call_args
            tasks = call_args[0][0]
            assert len(tasks) == 10
            assert call_args[1]["enable_http_server"] is True
            assert call_args[1]["server_port"] == 8888

            # Check print statements
            assert mock_print.call_count == 2
            mock_print.assert_any_call("Execution complete!")
            mock_print.assert_any_call("Metrics available at: http://localhost:8888/")
