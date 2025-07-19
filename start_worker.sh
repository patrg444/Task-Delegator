#!/bin/bash
# Start a Claude Worker instance

WORKER_ID=${1:-"worker_$$"}

echo "Starting Claude Worker: $WORKER_ID"

# Create necessary directories
mkdir -p shared/tasks shared/results logs

# Start the worker
cd workers
python3 worker.py "$WORKER_ID"