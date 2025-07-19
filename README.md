# Claude Task Delegator

A sophisticated async task orchestration system for running multiple Claude CLI instances in parallel. One Claude account acts as the delegator/manager while others execute tasks concurrently.

## Features

- **Async Orchestration**: Uses Python asyncio for efficient parallel task execution
- **Dynamic Worker Allocation**: Automatically determines optimal worker count based on workload
- **Priority Queue**: Tasks are processed based on priority and weight
- **Multiple Input Formats**: Supports JSON, YAML, CSV, and plain text task files
- **Retry Logic**: Automatic retry with exponential backoff for failed tasks
- **Account Management**: Easy setup and management of multiple Claude accounts
- **Detailed Statistics**: Comprehensive execution stats and per-task results

## Architecture

- **async_swarm.py**: Core async orchestrator using asyncio
- **swarm_cli.py**: Command-line interface for easy operation
- **config_manager.py**: Manages multiple Claude account configurations
- **task_loader.py**: Loads tasks from various file formats
- **workers/**: Worker modules for task execution
- **shared/**: Shared task queues and results

## Installation

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Set up Claude accounts:
   ```bash
   ./swarm_cli.py setup
   ```

3. Create example task files:
   ```bash
   ./swarm_cli.py examples
   ```

## Usage

### Basic Usage

```bash
# Run tasks from a file
./swarm_cli.py run examples/tasks.json

# Specify max workers
./swarm_cli.py run tasks.yaml --workers 3

# Save results to specific file
./swarm_cli.py run tasks.csv --output results.json

# Dry run to preview tasks
./swarm_cli.py run tasks.txt --dry-run
```

### Task File Formats

#### JSON Format
```json
{
  "tasks": [
    {
      "id": "task_1",
      "prompt": "Analyze the codebase structure",
      "type": "code_analysis",
      "priority": 8,
      "weight": 2.5
    }
  ]
}
```

#### YAML Format
```yaml
tasks:
  - id: task_1
    prompt: Analyze the codebase structure
    type: code_analysis
    priority: 8
    weight: 2.5
```

#### CSV Format
```csv
id,prompt,type,priority,weight
task_1,"Analyze the codebase structure",code_analysis,8,2.5
```

#### Plain Text (one task per line)
```
Analyze the codebase structure
Implement user authentication
Write API documentation
```

### CLI Commands

- `run <file>` - Execute tasks from a file
- `setup` - Interactive setup for Claude accounts
- `list` - List configured accounts and their status
- `examples` - Create example task files

## How It Works

1. **Task Loading**: Tasks are loaded from your chosen file format
2. **Worker Selection**: System calculates optimal worker count based on:
   - Task count and total weight
   - Average priority
   - Available Claude accounts
3. **Priority Queue**: Tasks are queued with priority (higher priority = processed first)
4. **Parallel Execution**: Workers pull tasks from queue and execute via Claude CLI
5. **Result Aggregation**: Results are collected and saved with statistics

## Collaborative Mode with GitHub Integration

The system now supports collaborative development where multiple Claude instances work on the same GitHub repository:

### Features
- **Automatic GitHub repo creation**: Manager creates and configures the repository
- **Worker isolation**: Each worker clones the repo to their own workspace
- **Branch-based development**: Workers create feature branches for their tasks
- **Inter-worker communication**: Message passing system for coordination
- **Automatic PR creation**: System creates pull requests for review

### Running Collaborative Mode

```bash
# Create a new collaborative project
./run_collaborative.py my-project

# Use custom task file
./run_collaborative.py my-project tasks.json
```

### How Collaborative Mode Works

1. **Project Setup**: Manager creates GitHub repository (uses account: patrg444)
2. **Worker Initialization**: Each worker clones repo to separate workspace
3. **Task Assignment**: Workers receive tasks with repository context
4. **Branch Creation**: Each worker creates a feature branch
5. **Development**: Workers complete tasks, commit, and push changes
6. **Integration**: Manager creates PRs for all worker branches

### Interactive Worker Handling

The system handles Claude's interactive prompts automatically:
- **Yes/No prompts**: Auto-continues with default (Yes)
- **Long output**: Automatically continues generation
- **Task completion detection**: Recognizes when tasks are done
- **Error recovery**: Retries failed operations

## Advanced Features

### Custom Worker Count Logic

The system uses intelligent heuristics:
- High priority tasks (≥8) or heavy workloads → More workers
- Medium priority (≥6) → Moderate worker count
- Low priority → Minimal workers

### Error Handling

- Automatic retry with exponential backoff
- Detailed error logging per task
- Failed tasks are marked but don't stop execution

### Account Management

Each Claude account uses its own `CLAUDE_CONFIG_DIR`:
```python
ACCOUNTS = {
    "work": Path.home() / ".claude-work",
    "personal": Path.home() / ".claude-personal",
    "research": Path.home() / ".claude-research"
}
```

## Performance Tips

1. **Batch Similar Tasks**: Group similar prompts for better cache utilization
2. **Set Appropriate Weights**: Use weights to indicate computational complexity
3. **Priority Management**: Reserve high priorities (8-10) for critical tasks
4. **Monitor Rate Limits**: Even with multiple accounts, be mindful of API limits

## Architecture Components

### Core Modules
- **async_swarm.py**: Basic async orchestrator
- **interactive_worker.py**: Handles Claude CLI interactions with pexpect
- **shared_context.py**: Manages shared state and inter-worker communication
- **collaborative_swarm.py**: Full GitHub-integrated collaborative system
- **config_manager.py**: Manages multiple Claude account configurations

### Communication System

Workers communicate through a file-based message queue:
- **Broadcast messages**: Sent to all workers
- **Direct messages**: Sent to specific workers
- **State tracking**: Each worker's status is tracked
- **Message persistence**: Messages stored in `shared/messages/`

## Security Notes

- Each account maintains separate credentials
- No credentials are shared between workers
- Results are stored locally in the shared directory
- GitHub operations use the configured user account
- Always follow Anthropic's Terms of Service

## Troubleshooting

### Workers getting stuck
- Check `shared/state/` for worker status
- Look for "waiting_input" state
- Review worker logs for errors

### GitHub issues
- Ensure `gh` CLI is authenticated: `gh auth status`
- Check repository permissions
- Verify branch protection rules

### Performance
- Reduce concurrent workers if hitting rate limits
- Use task weights to balance workload
- Monitor `shared/messages/` for communication overhead