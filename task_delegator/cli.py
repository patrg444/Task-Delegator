"""Command-line interface for task delegator."""

import asyncio
import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional
import logging

from .account_registry import AccountRegistry
from .core import SwarmOrchestrator, Task, TaskType, TaskLoader
from .monitor import MonitoredOrchestrator
from .api_adapter import configure_claude_runner

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TaskDelegatorCLI:
    """Main CLI for task delegation."""
    
    def __init__(self):
        self.registry = AccountRegistry()
    
    async def run_tasks(
        self,
        task_file: Path,
        max_workers: Optional[int] = None,
        output_file: Optional[Path] = None,
        enable_monitoring: bool = False,
        use_api: bool = False
    ):
        """Run tasks from a file."""
        # Load tasks
        logger.info(f"Loading tasks from {task_file}")
        tasks = TaskLoader.from_file(task_file)
        logger.info(f"Loaded {len(tasks)} tasks")
        
        # Setup orchestrator
        orchestrator = SwarmOrchestrator(
            self.registry,
            max_concurrent_workers=max_workers or 5
        )
        
        # Wrap with monitoring if requested
        if enable_monitoring:
            orchestrator = MonitoredOrchestrator(orchestrator, enable_dashboard=True)
            result = await orchestrator.orchestrate_with_monitoring(
                tasks,
                enable_http_server=True
            )
        else:
            result = await orchestrator.orchestrate(tasks)
        
        # Save results
        if output_file:
            with open(output_file, 'w') as f:
                json.dump(result, f, indent=2)
            logger.info(f"Results saved to {output_file}")
        
        # Print summary
        self._print_summary(result)
    
    def _print_summary(self, result: dict):
        """Print execution summary."""
        if not result.get('success'):
            print(f"Execution failed: {result.get('error')}")
            return
        
        summary = result.get('summary', {})
        print("\n" + "="*60)
        print("EXECUTION SUMMARY")
        print("="*60)
        print(f"Total tasks: {summary.get('total_tasks', 0)}")
        print(f"Completed: {summary.get('completed', 0)}")
        print(f"Failed: {summary.get('failed', 0)}")
        print(f"Success rate: {summary.get('success_rate', 0):.1f}%")
        print(f"Total time: {summary.get('total_time', 0):.1f}s")
        print(f"Throughput: {summary.get('tasks_per_minute', 0):.1f} tasks/min")
        
        # Worker stats
        worker_stats = result.get('worker_stats', {})
        if worker_stats:
            print("\nWORKER STATISTICS:")
            for worker_id, stats in worker_stats.items():
                print(f"  {worker_id}:")
                print(f"    Completed: {stats['tasks_completed']}")
                print(f"    Failed: {stats['tasks_failed']}")
                print(f"    Avg time: {stats['average_task_time']:.1f}s")
    
    def setup_accounts(self):
        """Interactive account setup."""
        active_count = self.registry.setup_all_accounts()
        if active_count == 0:
            print("\nNo active accounts. Please login to at least one account.")
            sys.exit(1)
    
    def list_accounts(self):
        """List all configured accounts."""
        accounts = self.registry.list_accounts()
        print("CONFIGURED ACCOUNTS")
        print("="*40)
        
        for name, path in accounts.items():
            status = "✓ Active" if self.registry.check_login_status(name) else "✗ Inactive"
            print(f"{name:<20} {status}")
            print(f"  Config: {path}")
        
        active = self.registry.get_active_accounts()
        print(f"\nTotal: {len(accounts)} accounts, {len(active)} active")
    
    def create_example_tasks(self, output_file: Path):
        """Create example task file."""
        example_tasks = [
            {
                "id": "example_1",
                "prompt": "Write a Python function to calculate fibonacci numbers",
                "type": "implementation",
                "priority": 7,
                "weight": 2.0
            },
            {
                "id": "example_2", 
                "prompt": "Analyze the time complexity of quicksort algorithm",
                "type": "code_analysis",
                "priority": 8,
                "weight": 1.5
            },
            {
                "id": "example_3",
                "prompt": "Debug why the authentication middleware returns 401 errors",
                "type": "debugging",
                "priority": 9,
                "weight": 3.0
            },
            {
                "id": "example_4",
                "prompt": "Write unit tests for the user registration endpoint",
                "type": "testing",
                "priority": 6,
                "weight": 2.0
            },
            {
                "id": "example_5",
                "prompt": "Document the REST API endpoints with examples",
                "type": "documentation",
                "priority": 5,
                "weight": 1.0
            }
        ]
        
        with open(output_file, 'w') as f:
            json.dump({"tasks": example_tasks}, f, indent=2)
        
        print(f"Created example tasks file: {output_file}")
        print(f"Run with: claude-delegator run {output_file}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Claude Task Delegator - Orchestrate multiple Claude instances"
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # Run command
    run_parser = subparsers.add_parser('run', help='Run tasks from a file')
    run_parser.add_argument('task_file', type=Path, help='Path to task file (JSON)')
    run_parser.add_argument('-w', '--workers', type=int, help='Maximum number of workers')
    run_parser.add_argument('-o', '--output', type=Path, help='Output file for results')
    run_parser.add_argument('-m', '--monitor', action='store_true', help='Enable live monitoring')
    run_parser.add_argument('--use-api', action='store_true', help='Use API instead of CLI')
    
    # Setup command
    setup_parser = subparsers.add_parser('setup', help='Setup Claude accounts')
    
    # List command  
    list_parser = subparsers.add_parser('list', help='List configured accounts')
    
    # Example command
    example_parser = subparsers.add_parser('example', help='Create example task file')
    example_parser.add_argument('-o', '--output', type=Path, default=Path('example_tasks.json'),
                               help='Output file name')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    cli = TaskDelegatorCLI()
    
    try:
        if args.command == 'run':
            if not args.task_file.exists():
                print(f"Error: Task file not found: {args.task_file}")
                sys.exit(1)
            
            asyncio.run(cli.run_tasks(
                args.task_file,
                max_workers=args.workers,
                output_file=args.output,
                enable_monitoring=args.monitor,
                use_api=args.use_api
            ))
            
        elif args.command == 'setup':
            cli.setup_accounts()
            
        elif args.command == 'list':
            cli.list_accounts()
            
        elif args.command == 'example':
            cli.create_example_tasks(args.output)
            
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()