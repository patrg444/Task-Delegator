#!/usr/bin/env python3
"""
async_interactive_swarm.py - Enhanced swarm orchestrator with interactive worker support
"""

from __future__ import annotations
import asyncio
import os
import json
import sys
import time
from itertools import islice
from pathlib import Path
from typing import Any, Iterable, Dict, List, Tuple, Optional
from datetime import datetime
import logging
from concurrent.futures import ThreadPoolExecutor

from interactive_worker import InteractiveWorker
from async_swarm import Task

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class InteractiveSwarmOrchestrator:
    """Orchestrator that manages interactive Claude workers"""
    
    def __init__(self, accounts: Dict[str, Path], max_concurrent_tasks: int = 5):
        self.accounts = accounts
        self.max_concurrent = max_concurrent_tasks
        self.workers = {}
        self.task_queue = asyncio.Queue()
        self.results = {}
        self.stats = {
            'total_tasks': 0,
            'completed': 0,
            'failed': 0,
            'auto_continued': 0,
            'manual_interventions': 0,
            'start_time': None,
            'end_time': None
        }
        
        # Create workers
        for name, config_dir in accounts.items():
            self.workers[name] = InteractiveWorker(name, config_dir)
    
    def choose_worker_count(self, tasks: List[Task]) -> int:
        """Determine optimal worker count"""
        if not tasks:
            return 0
        
        total_weight = sum(task.weight for task in tasks)
        avg_priority = sum(task.priority for task in tasks) / len(tasks)
        
        # For interactive mode, we might want fewer workers to manage complexity
        if avg_priority >= 8 or total_weight > 20:
            suggested = min(len(tasks), len(self.accounts), self.max_concurrent)
        elif avg_priority >= 6 or total_weight > 10:
            suggested = min(max(2, len(tasks) // 3), len(self.accounts))
        else:
            suggested = min(max(1, len(tasks) // 4), len(self.accounts))
        
        logger.info(f"Workload: {len(tasks)} tasks, weight: {total_weight:.1f}, "
                   f"priority: {avg_priority:.1f} → using {suggested} workers")
        
        return suggested
    
    async def worker_loop(self, worker: InteractiveWorker):
        """Main loop for a worker"""
        while True:
            try:
                # Get task from queue
                task = await self.task_queue.get()
                
                if task is None:  # Sentinel
                    break
                
                logger.info(f"[{worker.name}] Starting task {task.id}")
                
                # Execute task with interactive handling
                result = await worker.execute_task(task.to_dict())
                
                # Update stats
                if result.get('status') == 'success':
                    self.stats['completed'] += 1
                else:
                    self.stats['failed'] += 1
                
                # Count auto-continuations
                interactions = result.get('interactions', [])
                auto_continues = sum(1 for i in interactions if i.get('action') == 'auto_continue')
                self.stats['auto_continued'] += auto_continues
                
                # Store result
                self.results[task.id] = result
                
                logger.info(f"[{worker.name}] Finished task {task.id} - {result.get('status')}")
                
            except Exception as e:
                logger.error(f"[{worker.name}] Error in worker loop: {e}")
                if task:
                    self.results[task.id] = {
                        'task_id': task.id,
                        'worker_id': worker.name,
                        'status': 'error',
                        'error': str(e)
                    }
                    self.stats['failed'] += 1
            
            finally:
                self.task_queue.task_done()
    
    async def monitor_workers(self):
        """Monitor worker states and provide status updates"""
        while self.stats['completed'] + self.stats['failed'] < self.stats['total_tasks']:
            await asyncio.sleep(5)  # Check every 5 seconds
            
            # Get worker states
            states = {name: worker.state for name, worker in self.workers.items()}
            
            # Count states
            state_counts = {}
            for state in states.values():
                state_counts[state] = state_counts.get(state, 0) + 1
            
            # Log status
            logger.info(f"Progress: {self.stats['completed']}/{self.stats['total_tasks']} completed, "
                       f"{self.stats['failed']} failed | "
                       f"Workers: {state_counts}")
            
            # Check for stuck workers
            waiting_workers = [name for name, state in states.items() if state == 'waiting_input']
            if waiting_workers:
                logger.warning(f"Workers waiting for input: {waiting_workers}")
                # In a real implementation, you might notify the user or take action
    
    async def orchestrate(self, tasks: List[Task]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Orchestrate task execution"""
        self.stats['total_tasks'] = len(tasks)
        self.stats['start_time'] = datetime.now()
        
        # Add tasks to queue
        for task in tasks:
            await self.task_queue.put(task)
        
        # Determine worker count
        num_workers = self.choose_worker_count(tasks)
        active_workers = list(islice(self.workers.items(), num_workers))
        
        # Add sentinels
        for _ in range(num_workers):
            await self.task_queue.put(None)
        
        # Start worker tasks
        worker_tasks = []
        for name, worker in active_workers:
            worker_task = asyncio.create_task(self.worker_loop(worker))
            worker_tasks.append(worker_task)
        
        # Start monitor task
        monitor_task = asyncio.create_task(self.monitor_workers())
        
        # Wait for all workers to complete
        await asyncio.gather(*worker_tasks)
        
        # Cancel monitor
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass
        
        self.stats['end_time'] = datetime.now()
        duration = (self.stats['end_time'] - self.stats['start_time']).total_seconds()
        self.stats['duration_seconds'] = duration
        self.stats['tasks_per_minute'] = (self.stats['total_tasks'] / duration) * 60 if duration > 0 else 0
        
        return self.results, self.stats

class InteractiveTaskManager:
    """High-level manager for interactive task execution"""
    
    def __init__(self, accounts: Dict[str, Path]):
        self.orchestrator = InteractiveSwarmOrchestrator(accounts)
    
    async def run_tasks(self, tasks: List[Task]) -> Dict[str, Any]:
        """Run tasks and return comprehensive results"""
        logger.info(f"Starting execution of {len(tasks)} tasks")
        
        results, stats = await self.orchestrator.orchestrate(tasks)
        
        # Compile summary
        summary = {
            'execution_stats': stats,
            'task_summary': {
                'total': len(tasks),
                'completed': stats['completed'],
                'failed': stats['failed'],
                'success_rate': (stats['completed'] / len(tasks) * 100) if tasks else 0
            },
            'automation_stats': {
                'auto_continued': stats['auto_continued'],
                'manual_interventions': stats['manual_interventions'],
                'automation_rate': (stats['auto_continued'] / 
                                  (stats['auto_continued'] + stats['manual_interventions']) * 100
                                  if stats['auto_continued'] + stats['manual_interventions'] > 0 else 100)
            },
            'performance': {
                'duration_seconds': stats.get('duration_seconds', 0),
                'tasks_per_minute': stats.get('tasks_per_minute', 0)
            },
            'results': results
        }
        
        return summary
    
    def print_summary(self, summary: Dict[str, Any]):
        """Print execution summary"""
        print("\n" + "="*60)
        print("EXECUTION SUMMARY")
        print("="*60)
        
        task_sum = summary['task_summary']
        print(f"\nTask Results:")
        print(f"  Total: {task_sum['total']}")
        print(f"  Completed: {task_sum['completed']} ({task_sum['success_rate']:.1f}%)")
        print(f"  Failed: {task_sum['failed']}")
        
        auto_stats = summary['automation_stats']
        print(f"\nAutomation:")
        print(f"  Auto-continued: {auto_stats['auto_continued']} times")
        print(f"  Manual interventions: {auto_stats['manual_interventions']}")
        print(f"  Automation rate: {auto_stats['automation_rate']:.1f}%")
        
        perf = summary['performance']
        print(f"\nPerformance:")
        print(f"  Duration: {perf['duration_seconds']:.1f} seconds")
        print(f"  Throughput: {perf['tasks_per_minute']:.1f} tasks/minute")
        
        print("\n" + "="*60)

# Example usage
async def main():
    """Example usage of interactive swarm"""
    
    # Configure accounts
    ACCOUNTS = {
        "account_A": Path.home() / ".claude-work",
        "account_B": Path.home() / ".claude-personal",
    }
    
    # Create tasks
    tasks = [
        Task("impl_1", "Implement a Python function to calculate fibonacci numbers with memoization", 
             "implementation", priority=8, weight=2),
        Task("debug_1", "Debug and fix the authentication middleware that's causing 401 errors", 
             "debugging", priority=9, weight=3),
        Task("analyze_1", "Analyze the codebase and identify performance bottlenecks", 
             "analysis", priority=7, weight=2.5),
        Task("doc_1", "Write comprehensive documentation for the REST API endpoints", 
             "documentation", priority=5, weight=1.5),
    ]
    
    # Run tasks
    manager = InteractiveTaskManager(ACCOUNTS)
    summary = await manager.run_tasks(tasks)
    
    # Print results
    manager.print_summary(summary)
    
    # Save detailed results
    with open('interactive_results.json', 'w') as f:
        json.dump(summary, f, indent=2)

if __name__ == "__main__":
    asyncio.run(main())