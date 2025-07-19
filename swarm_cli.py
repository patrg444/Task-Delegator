#!/usr/bin/env python3
"""
swarm_cli.py - Command-line interface for the Claude Task Delegator
"""

import asyncio
import argparse
import json
import sys
from pathlib import Path
from typing import List, Dict, Any
import logging

from async_swarm import Task, orchestrate, aggregate_results, ACCOUNTS
from config_manager import ConfigManager
from task_loader import TaskLoader

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SwarmCLI:
    """Command-line interface for task swarm orchestration"""
    
    def __init__(self):
        self.config_manager = ConfigManager()
        self.task_loader = TaskLoader()
    
    async def run_tasks(self, 
                       task_source: str,
                       max_workers: int = None,
                       output_file: str = None,
                       dry_run: bool = False):
        """Run tasks from a source file"""
        
        # Load tasks
        logger.info(f"Loading tasks from: {task_source}")
        task_data = self.task_loader.load_tasks(task_source)
        
        # Convert to Task objects
        tasks = []
        for i, data in enumerate(task_data):
            task_id = data.get('id', f'task_{i}')
            prompt = data.get('prompt', '')
            task_type = data.get('type', 'general')
            priority = data.get('priority', 5)
            weight = data.get('weight', 1.0)
            
            tasks.append(Task(task_id, prompt, task_type, priority, weight))
        
        logger.info(f"Loaded {len(tasks)} tasks")
        
        if dry_run:
            print("\n=== Dry Run - Tasks to be executed ===")
            for task in tasks:
                print(f"ID: {task.id}")
                print(f"Type: {task.type}")
                print(f"Priority: {task.priority}")
                print(f"Weight: {task.weight}")
                print(f"Prompt: {task.prompt[:100]}...")
                print("-" * 40)
            return
        
        # Check available accounts
        active_accounts = self.config_manager.get_active_accounts()
        if not active_accounts:
            logger.error("No active Claude accounts found. Run setup first.")
            return
        
        # Update global ACCOUNTS with active accounts
        global ACCOUNTS
        ACCOUNTS = {name: Path(path) for name, path in active_accounts.items()}
        
        if max_workers:
            max_workers = min(max_workers, len(ACCOUNTS))
        else:
            max_workers = len(ACCOUNTS)
        
        logger.info(f"Using up to {max_workers} workers from {len(ACCOUNTS)} available accounts")
        
        # Execute tasks
        results, stats = await orchestrate(tasks)
        
        # Generate summary
        summary = aggregate_results(results, stats)
        
        # Save results
        if output_file:
            output_path = Path(output_file)
        else:
            output_path = Path('claude-task-delegator/shared/results') / f'run_{int(asyncio.get_event_loop().time())}.json'
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w') as f:
            json.dump(summary, f, indent=2)
        
        logger.info(f"Results saved to: {output_path}")
        
        # Print summary
        self.print_summary(summary)
    
    def print_summary(self, summary: Dict[str, Any]):
        """Print execution summary"""
        print("\n=== Execution Summary ===")
        print(f"Total tasks: {summary['task_summary']['total']}")
        print(f"Completed: {summary['task_summary']['completed']}")
        print(f"Failed: {summary['task_summary']['failed']}")
        
        if 'execution_stats' in summary:
            stats = summary['execution_stats']
            if 'total_execution_time' in stats:
                print(f"Total time: {stats['total_execution_time']:.1f}s")
            if 'tasks_per_second' in stats:
                print(f"Tasks/second: {stats['tasks_per_second']:.2f}")
        
        print("\n=== Results by Type ===")
        for task_type, type_stats in summary.get('by_type', {}).items():
            print(f"{task_type}: {type_stats['completed']}/{type_stats['count']} completed")
    
    def setup_accounts(self):
        """Interactive account setup"""
        self.config_manager.setup_all_accounts()
    
    def list_accounts(self):
        """List all configured accounts"""
        print("=== Configured Claude Accounts ===")
        
        for name, path in self.config_manager.accounts.items():
            status = "✓ Active" if self.config_manager.check_login_status(name) else "✗ Inactive"
            print(f"{name}: {path} [{status}]")
        
        active = self.config_manager.get_active_accounts()
        print(f"\nTotal: {len(self.config_manager.accounts)} accounts, {len(active)} active")

def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description="Claude Task Delegator - Orchestrate multiple Claude instances"
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # Run command
    run_parser = subparsers.add_parser('run', help='Run tasks from a file')
    run_parser.add_argument('task_file', help='Path to task file (JSON, YAML, CSV, or TXT)')
    run_parser.add_argument('-w', '--workers', type=int, help='Maximum number of workers')
    run_parser.add_argument('-o', '--output', help='Output file for results')
    run_parser.add_argument('--dry-run', action='store_true', help='Show tasks without executing')
    
    # Setup command
    setup_parser = subparsers.add_parser('setup', help='Setup Claude accounts')
    
    # List command
    list_parser = subparsers.add_parser('list', help='List configured accounts')
    
    # Examples command
    examples_parser = subparsers.add_parser('examples', help='Create example task files')
    
    args = parser.parse_args()
    
    cli = SwarmCLI()
    
    if args.command == 'run':
        asyncio.run(cli.run_tasks(
            args.task_file,
            max_workers=args.workers,
            output_file=args.output,
            dry_run=args.dry_run
        ))
    elif args.command == 'setup':
        cli.setup_accounts()
    elif args.command == 'list':
        cli.list_accounts()
    elif args.command == 'examples':
        from task_loader import create_example_files
        create_example_files()
        print("Example task files created in claude-task-delegator/examples/")
    else:
        parser.print_help()

if __name__ == "__main__":
    main()