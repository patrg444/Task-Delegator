#!/usr/bin/env python3
"""
task_loader.py - Load tasks from various sources (files, APIs, etc.)
"""

import csv
import json
import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


class TaskLoader:
    """Load and parse tasks from different sources"""

    @staticmethod
    def load_from_json(file_path: str | Path) -> list[dict[str, Any]]:
        """Load tasks from JSON file"""
        with open(file_path) as f:
            data = json.load(f)

        if isinstance(data, list):
            return data
        elif isinstance(data, dict) and "tasks" in data:
            return data["tasks"]
        else:
            raise ValueError("JSON must contain a list of tasks or a dict with 'tasks' key")

    @staticmethod
    def load_from_yaml(file_path: str | Path) -> list[dict[str, Any]]:
        """Load tasks from YAML file"""
        with open(file_path) as f:
            data = yaml.safe_load(f)

        if isinstance(data, list):
            return data
        elif isinstance(data, dict) and "tasks" in data:
            return data["tasks"]
        else:
            raise ValueError("YAML must contain a list of tasks or a dict with 'tasks' key")

    @staticmethod
    def load_from_csv(file_path: str | Path) -> list[dict[str, Any]]:
        """Load tasks from CSV file"""
        tasks = []
        with open(file_path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Convert numeric fields
                if "priority" in row:
                    row["priority"] = int(row["priority"])
                if "weight" in row:
                    row["weight"] = float(row["weight"])
                tasks.append(row)
        return tasks

    @staticmethod
    def load_from_text(
        file_path: str | Path, task_type: str = "general", priority: int = 5
    ) -> list[dict[str, Any]]:
        """Load tasks from plain text file (one task per line)"""
        tasks = []
        with open(file_path) as f:
            for i, line in enumerate(f):
                line = line.strip()
                if line and not line.startswith("#"):  # Skip empty lines and comments
                    tasks.append(
                        {
                            "id": f"task_{i}",
                            "prompt": line,
                            "type": task_type,
                            "priority": priority,
                            "weight": 1.0,
                        }
                    )
        return tasks

    @classmethod
    def load_tasks(cls, source: str | Path) -> list[dict[str, Any]]:
        """Auto-detect format and load tasks"""
        path = Path(source)

        if not path.exists():
            raise FileNotFoundError(f"Task file not found: {source}")

        suffix = path.suffix.lower()

        if suffix == ".json":
            return cls.load_from_json(path)
        elif suffix in [".yaml", ".yml"]:
            return cls.load_from_yaml(path)
        elif suffix == ".csv":
            return cls.load_from_csv(path)
        elif suffix in [".txt", ".text"]:
            return cls.load_from_text(path)
        else:
            # Try to detect format from content
            try:
                return cls.load_from_json(path)
            except (json.JSONDecodeError, ValueError):
                try:
                    return cls.load_from_yaml(path)
                except (yaml.YAMLError, ValueError):
                    # Default to text format
                    return cls.load_from_text(path)


# Example task file formats:

EXAMPLE_JSON = """
{
  "tasks": [
    {
      "id": "analyze_1",
      "prompt": "Analyze the performance bottlenecks in the data processing pipeline",
      "type": "code_analysis",
      "priority": 8,
      "weight": 2.5
    },
    {
      "id": "implement_1",
      "prompt": "Implement caching layer for API responses",
      "type": "implementation",
      "priority": 7,
      "weight": 3.0
    }
  ]
}
"""

EXAMPLE_YAML = """
tasks:
  - id: analyze_1
    prompt: Analyze the performance bottlenecks in the data processing pipeline
    type: code_analysis
    priority: 8
    weight: 2.5

  - id: implement_1
    prompt: Implement caching layer for API responses
    type: implementation
    priority: 7
    weight: 3.0
"""

EXAMPLE_CSV = """
id,prompt,type,priority,weight
analyze_1,"Analyze the performance bottlenecks in the data processing pipeline",code_analysis,8,2.5
implement_1,"Implement caching layer for API responses",implementation,7,3.0
"""


def create_example_files():
    """Create example task files"""
    examples_dir = Path("examples")
    examples_dir.mkdir(exist_ok=True, parents=True)

    # JSON example
    with open(examples_dir / "tasks.json", "w") as f:
        f.write(EXAMPLE_JSON)

    # YAML example
    with open(examples_dir / "tasks.yaml", "w") as f:
        f.write(EXAMPLE_YAML)

    # CSV example
    with open(examples_dir / "tasks.csv", "w") as f:
        f.write(EXAMPLE_CSV)

    # Text example
    with open(examples_dir / "tasks.txt", "w") as f:
        f.write(
            """# Example task list
Analyze the performance bottlenecks in the data processing pipeline
Implement caching layer for API responses
Write unit tests for the authentication module
Optimize database queries in the user service
Create documentation for the REST API endpoints
"""
        )

    logger.info(f"Created example task files in {examples_dir}")


if __name__ == "__main__":
    create_example_files()
