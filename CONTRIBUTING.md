# Contributing to Claude Task Delegator

Thank you for your interest in contributing to Claude Task Delegator! This guide explains our development process, coding standards, and architectural decisions.

## Development Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/patrg444/Task-Delegator.git
   cd Task-Delegator
   ```

2. **Create a virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install development dependencies**
   ```bash
   pip install -e ".[dev]"
   ```

4. **Install pre-commit hooks**
   ```bash
   pre-commit install
   ```

## Code Style and Standards

### Python Version
- We support Python 3.10, 3.11, and 3.12
- Use type hints for all function signatures
- Follow PEP 8 with these modifications:
  - Line length: 100 characters
  - Use Black for formatting

### Tools
- **Black**: Code formatting (automatically applied)
- **Ruff**: Fast linting and code quality
- **MyPy**: Static type checking
- **pytest**: Testing framework

### Pre-commit Hooks
Our pre-commit hooks will automatically:
- Format code with Black
- Fix common issues with Ruff
- Check for security issues
- Validate YAML/JSON/TOML files

## Architecture Overview

### Core Components

1. **AccountRegistry** (`account_registry.py`)
   - Manages multiple Claude account configurations
   - No global state - pass instances where needed
   - Handles login status checking

2. **SecureClaudeRunner** (`secure_runner.py`)
   - Executes Claude CLI commands safely
   - Prevents shell injection attacks
   - Handles timeouts and errors gracefully

3. **SwarmOrchestrator** (various implementations)
   - Coordinates multiple workers
   - Dynamic worker allocation based on workload
   - Priority-based task queue

### Worker Heuristics

The system uses intelligent heuristics to determine worker count:

```python
def choose_worker_count(tasks: List[Task], max_workers: int) -> int:
    """
    Worker allocation strategy:
    - High priority (≥8) or heavy workload (>20): Use maximum workers
    - Medium priority (≥6) or moderate load (>10): Use ~50% of workers
    - Low priority: Use minimal workers (25% or 1)
    """
```

### Priority Queue Logic

Tasks are queued with a composite key:
```python
priority_key = -task.priority * task.weight
```

This means:
- Higher priority = lower key value = processed first
- Weight acts as a multiplier for priority
- To make weight represent cost instead: use `priority / weight`

## Testing

### Running Tests
```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=task_delegator

# Run specific test file
pytest tests/test_account_registry.py

# Run tests in parallel
pytest -n auto
```

### Writing Tests
- Place tests in the `tests/` directory
- Use `pytest` fixtures for common setup
- Mock external dependencies (Claude CLI, subprocess, etc.)
- Aim for >80% code coverage

Example test structure:
```python
@pytest.fixture
def mock_claude_cli():
    """Mock Claude CLI responses."""
    with patch('asyncio.create_subprocess_exec') as mock:
        # Setup mock
        yield mock

def test_feature(mock_claude_cli):
    """Test description."""
    # Test implementation
```

## Making Changes

### Workflow

1. **Create a feature branch**
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes**
   - Write tests for new functionality
   - Update documentation as needed
   - Ensure all tests pass

3. **Commit with descriptive messages**
   ```bash
   git commit -m "feat: add support for custom task priorities"
   ```

4. **Push and create PR**
   ```bash
   git push origin feature/your-feature-name
   ```

### Commit Message Format
We follow conventional commits:
- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation changes
- `test:` Test additions/changes
- `refactor:` Code refactoring
- `perf:` Performance improvements
- `chore:` Maintenance tasks

## API vs CLI Implementation

Currently, we use the Claude CLI via subprocess. Future plans include:

1. **HTTP API Adapter**
   - Feature flag to switch between CLI and API
   - In-process execution for better performance
   - Removes need for pexpect parsing

2. **Migration Path**
   - Keep CLI as fallback
   - Abstract interface for both implementations
   - Gradual migration based on user needs

## Security Considerations

### Command Injection Prevention
- Never use `shell=True` in subprocess calls
- Pass arguments as lists, not strings
- Validate and sanitize all user inputs

### Policy Hooks
The `PolicyEnforcer` class allows custom security policies:
```python
config = {
    'blocked_patterns': ['rm -rf', 'sudo'],
    'require_confirmation': ['delete', 'drop'],
    'max_prompt_length': 50000
}
```

## Performance Optimization

### Current Bottlenecks
1. Subprocess overhead for each Claude call
2. File-based message passing for worker communication
3. Sequential task assignment

### Planned Improvements
1. HTTP API for in-process execution
2. Redis/RabbitMQ for message passing
3. Predictive task assignment based on worker performance

## Questions or Issues?

- Open an issue for bugs or feature requests
- Join discussions for architectural decisions
- Check existing PRs to avoid duplicate work

Thank you for contributing!