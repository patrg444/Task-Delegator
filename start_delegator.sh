#!/bin/bash
# Start the Claude Task Delegator

echo "Starting Claude Task Delegator..."

# Create necessary directories
mkdir -p shared/tasks shared/results logs

# Start the delegator
cd delegator
python3 task_manager.py
