#!/usr/bin/env python3
"""
Worker module for Claude instances
Executes tasks assigned by the delegator
"""

import json
import os
import time
import sys
from datetime import datetime
from typing import Dict, Optional


class Worker:
    def __init__(self, worker_id: str, config_path: str = "../config/worker.json"):
        self.worker_id = worker_id
        self.config_path = config_path
        self.tasks_dir = "../shared/tasks"
        self.results_dir = "../shared/results"
        self.current_task = None
        self.load_config()
        
    def load_config(self):
        """Load worker configuration"""
        if os.path.exists(self.config_path):
            with open(self.config_path, 'r') as f:
                self.config = json.load(f)
        else:
            self.config = {
                "poll_interval": 5,
                "max_task_duration": 3600
            }
    
    def find_available_task(self) -> Optional[Dict]:
        """Find an unassigned task to work on"""
        if not os.path.exists(self.tasks_dir):
            return None
            
        for filename in os.listdir(self.tasks_dir):
            if filename.endswith(".json"):
                task_path = os.path.join(self.tasks_dir, filename)
                
                with open(task_path, 'r') as f:
                    task = json.load(f)
                
                if task["status"] == "pending":
                    # Attempt to claim the task
                    task["status"] = "assigned"
                    task["assigned_to"] = self.worker_id
                    task["assigned_at"] = datetime.now().isoformat()
                    
                    try:
                        with open(task_path, 'w') as f:
                            json.dump(task, f, indent=2)
                        return task
                    except:
                        # Another worker might have claimed it
                        continue
        
        return None
    
    def execute_task(self, task: Dict) -> Dict:
        """Execute the assigned task"""
        print(f"Worker {self.worker_id} executing task {task['id']}: {task['description']}")
        
        # This is where the actual Claude instance would process the task
        # For now, we'll simulate task execution
        result = {
            "task_id": task["id"],
            "worker_id": self.worker_id,
            "status": "success",
            "started_at": datetime.now().isoformat(),
            "output": f"Task completed by worker {self.worker_id}"
        }
        
        # Simulate work being done
        time.sleep(2)
        
        result["completed_at"] = datetime.now().isoformat()
        return result
    
    def save_result(self, result: Dict):
        """Save task result to shared directory"""
        os.makedirs(self.results_dir, exist_ok=True)
        
        result_path = os.path.join(
            self.results_dir, 
            f"{result['task_id']}_result.json"
        )
        
        with open(result_path, 'w') as f:
            json.dump(result, f, indent=2)
        
        print(f"Worker {self.worker_id} saved result for task {result['task_id']}")
    
    def run(self):
        """Main worker loop"""
        print(f"Worker {self.worker_id} started")
        
        while True:
            try:
                # Look for available tasks
                task = self.find_available_task()
                
                if task:
                    self.current_task = task
                    result = self.execute_task(task)
                    self.save_result(result)
                    self.current_task = None
                else:
                    # No tasks available, wait
                    time.sleep(self.config["poll_interval"])
                    
            except KeyboardInterrupt:
                print(f"Worker {self.worker_id} shutting down")
                break
            except Exception as e:
                print(f"Worker {self.worker_id} error: {e}")
                time.sleep(self.config["poll_interval"])


if __name__ == "__main__":
    # Get worker ID from command line or use default
    worker_id = sys.argv[1] if len(sys.argv) > 1 else f"worker_{os.getpid()}"
    
    worker = Worker(worker_id)
    worker.run()