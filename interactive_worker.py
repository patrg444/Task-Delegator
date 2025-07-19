#!/usr/bin/env python3
"""
interactive_worker.py - Interactive worker that handles Claude CLI prompts
"""

import asyncio
import pexpect
import os
import json
import re
from pathlib import Path
from typing import Dict, Optional, Tuple, List
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class InteractiveWorker:
    """Worker that can handle interactive Claude CLI sessions"""
    
    def __init__(self, name: str, config_dir: Path):
        self.name = name
        self.config_dir = config_dir
        self.process = None
        self.task = None
        self.output_buffer = []
        self.state = "idle"  # idle, working, waiting_input, completed, error
        
    async def start_claude_session(self, prompt: str) -> pexpect.spawn:
        """Start an interactive Claude session"""
        env = os.environ.copy()
        env["CLAUDE_CONFIG_DIR"] = str(self.config_dir)
        
        # Start claude in interactive mode
        cmd = f"claude ask '{prompt}'"
        self.process = pexpect.spawn('/bin/bash', ['-c', cmd], env=env, encoding='utf-8')
        self.process.maxread = 10000
        self.process.timeout = 600  # 10 minute timeout
        
        return self.process
    
    def detect_prompt_type(self, output: str) -> Optional[str]:
        """Detect what type of prompt Claude is waiting for"""
        patterns = {
            'yes_no': [
                r'(?i)continue.*\?.*\(yes/no\)',
                r'(?i)proceed.*\?.*\(y/n\)',
                r'(?i)would you like.*\?',
                r'(?i)do you want.*\?',
                r'Press Enter to continue',
                r'(?i)continue with'
            ],
            'long_output': [
                r'Output is very long.*Continue\?',
                r'This response is getting long',
                r'Continue generating\?'
            ],
            'clarification': [
                r'(?i)which.*would you prefer',
                r'(?i)please clarify',
                r'(?i)could you specify'
            ],
            'completion': [
                r'(?i)task.*completed',
                r'(?i)finished.*implementation',
                r'(?i)done with',
                r'(?i)successfully.*implemented',
                r'(?i)here is the.*result'
            ]
        }
        
        for prompt_type, pattern_list in patterns.items():
            for pattern in pattern_list:
                if re.search(pattern, output):
                    return prompt_type
        
        return None
    
    def parse_task_completion(self, output: str) -> bool:
        """Determine if the task has been completed based on output"""
        completion_indicators = [
            r'(?i)task.*completed',
            r'(?i)implementation.*finished',
            r'(?i)successfully.*implemented',
            r'(?i)done with.*implementation',
            r'(?i)completed all.*steps',
            r'(?i)finished.*all.*tasks',
            r'(?i)here.*is.*the.*final',
            r'(?i)everything.*is.*now.*working'
        ]
        
        for pattern in completion_indicators:
            if re.search(pattern, output):
                return True
        
        # Check if Claude is asking what to do next (often means task is done)
        next_task_indicators = [
            r'(?i)what.*would.*you.*like.*next',
            r'(?i)anything.*else',
            r'(?i)is there.*anything.*else',
            r'(?i)what.*next'
        ]
        
        for pattern in next_task_indicators:
            if re.search(pattern, output):
                return True
        
        return False
    
    async def execute_task(self, task: Dict) -> Dict:
        """Execute a task with interactive handling"""
        self.task = task
        self.state = "working"
        self.output_buffer = []
        result = {
            "task_id": task.get('id'),
            "worker_id": self.name,
            "started_at": datetime.now().isoformat(),
            "interactions": []
        }
        
        try:
            # Start Claude session
            await self.start_claude_session(task.get('prompt', ''))
            
            output_chunk = ""
            task_completed = False
            
            while not task_completed:
                try:
                    # Read output
                    index = self.process.expect([
                        pexpect.EOF,
                        pexpect.TIMEOUT,
                        r'\n',
                        r'(?i)continue.*\?',
                        r'(?i)yes.*no',
                        r'(?i)\(y/n\)',
                        r'Press Enter',
                        r'>'  # Generic prompt
                    ], timeout=30)
                    
                    if index == 0:  # EOF
                        self.state = "completed"
                        break
                    elif index == 1:  # Timeout
                        # Check if task might be complete
                        if self.parse_task_completion(output_chunk):
                            task_completed = True
                            self.state = "completed"
                            break
                        else:
                            self.state = "waiting_input"
                            logger.warning(f"[{self.name}] Timeout - might need input")
                    
                    # Capture output
                    output_chunk += self.process.before + (self.process.after or '')
                    self.output_buffer.append(self.process.before)
                    
                    # Detect prompt type
                    prompt_type = self.detect_prompt_type(output_chunk)
                    
                    if prompt_type == 'yes_no' or prompt_type == 'long_output':
                        # Auto-continue
                        logger.info(f"[{self.name}] Auto-continuing (detected: {prompt_type})")
                        self.process.sendline('')  # Press Enter (default is yes)
                        result['interactions'].append({
                            'type': prompt_type,
                            'action': 'auto_continue',
                            'timestamp': datetime.now().isoformat()
                        })
                        output_chunk = ""  # Reset buffer
                        
                    elif prompt_type == 'completion':
                        # Task appears to be done
                        task_completed = True
                        self.state = "completed"
                        logger.info(f"[{self.name}] Task completed")
                        
                    elif prompt_type == 'clarification':
                        # Need human intervention
                        self.state = "waiting_input"
                        logger.warning(f"[{self.name}] Needs clarification - manual intervention required")
                        result['interactions'].append({
                            'type': 'clarification_needed',
                            'output': output_chunk[-500:],  # Last 500 chars
                            'timestamp': datetime.now().isoformat()
                        })
                        # For now, we'll mark as error and move on
                        raise Exception("Manual clarification needed")
                    
                    # Check for task completion in output
                    if self.parse_task_completion(output_chunk):
                        task_completed = True
                        self.state = "completed"
                
                except pexpect.exceptions.TIMEOUT:
                    # Final timeout check
                    if self.parse_task_completion(''.join(self.output_buffer)):
                        task_completed = True
                        self.state = "completed"
                    else:
                        raise Exception("Task timed out without completion")
            
            # Capture final output
            result['output'] = ''.join(self.output_buffer)
            result['completed_at'] = datetime.now().isoformat()
            result['status'] = 'success' if task_completed else 'incomplete'
            
        except Exception as e:
            logger.error(f"[{self.name}] Error: {e}")
            result['error'] = str(e)
            result['status'] = 'error'
            result['output'] = ''.join(self.output_buffer)
            self.state = "error"
        
        finally:
            # Clean up process
            if self.process and self.process.isalive():
                self.process.terminate()
                self.process.wait()
            
            self.state = "idle"
        
        return result

class InteractiveWorkerPool:
    """Manage a pool of interactive workers"""
    
    def __init__(self, accounts: Dict[str, Path]):
        self.workers = {}
        for name, config_dir in accounts.items():
            self.workers[name] = InteractiveWorker(name, config_dir)
    
    async def execute_task(self, worker_name: str, task: Dict) -> Dict:
        """Execute a task on a specific worker"""
        if worker_name not in self.workers:
            raise ValueError(f"Worker {worker_name} not found")
        
        worker = self.workers[worker_name]
        return await worker.execute_task(task)
    
    def get_worker_states(self) -> Dict[str, str]:
        """Get current state of all workers"""
        return {name: worker.state for name, worker in self.workers.items()}
    
    async def intervene(self, worker_name: str, input_text: str):
        """Send input to a waiting worker"""
        if worker_name not in self.workers:
            raise ValueError(f"Worker {worker_name} not found")
        
        worker = self.workers[worker_name]
        if worker.state == "waiting_input" and worker.process and worker.process.isalive():
            worker.process.sendline(input_text)
            logger.info(f"Sent input to {worker_name}: {input_text}")
        else:
            logger.warning(f"Worker {worker_name} is not waiting for input (state: {worker.state})")