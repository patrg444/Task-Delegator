#!/usr/bin/env python3
"""
config_manager.py - Manage multiple Claude account configurations
"""

import json
import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class ConfigManager:
    """Manage multiple Claude CLI configurations"""

    def __init__(self, base_dir: Path = Path.home() / ".claude-configs"):
        self.base_dir = base_dir
        self.base_dir.mkdir(exist_ok=True)
        self.accounts = {}
        self.load_accounts()

    def load_accounts(self):
        """Load existing account configurations"""
        config_file = self.base_dir / "accounts.json"
        if config_file.exists():
            with open(config_file) as f:
                self.accounts = json.load(f)
        else:
            # Default accounts
            self.accounts = {
                "work": str(Path.home() / ".claude-work"),
                "personal": str(Path.home() / ".claude-personal"),
                "research": str(Path.home() / ".claude-research"),
            }
            self.save_accounts()

    def save_accounts(self):
        """Save account configurations"""
        config_file = self.base_dir / "accounts.json"
        with open(config_file, "w") as f:
            json.dump(self.accounts, f, indent=2)

    def add_account(self, name: str, config_dir: str):
        """Add a new account configuration"""
        config_path = Path(config_dir)
        config_path.mkdir(parents=True, exist_ok=True)
        self.accounts[name] = str(config_path)
        self.save_accounts()
        logger.info(f"Added account '{name}' with config dir: {config_dir}")

    def check_login_status(self, account_name: str) -> bool:
        """Check if an account is logged in"""
        if account_name not in self.accounts:
            return False

        config_dir = self.accounts[account_name]
        env = os.environ.copy()
        env["CLAUDE_CONFIG_DIR"] = config_dir

        try:
            # Try a simple command to check if authenticated
            result = subprocess.run(
                ["claude", "ask", "--json", "test"],
                capture_output=True,
                text=True,
                env=env,
                timeout=5,
            )

            # If we get a proper JSON response, we're logged in
            if result.returncode == 0:
                try:
                    json.loads(result.stdout)
                    return True
                except json.JSONDecodeError:
                    pass

            return False

        except Exception as e:
            logger.error(f"Error checking login status for {account_name}: {e}")
            return False

    def login_account(self, account_name: str) -> bool:
        """Initiate login for an account (interactive)"""
        if account_name not in self.accounts:
            logger.error(f"Account '{account_name}' not found")
            return False

        config_dir = self.accounts[account_name]
        env = os.environ.copy()
        env["CLAUDE_CONFIG_DIR"] = config_dir

        print(f"\nInitiating login for account '{account_name}'...")
        print(f"Config directory: {config_dir}")

        try:
            # Run interactive login
            subprocess.run(["claude", "/login"], env=env, check=True)
            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"Login failed for {account_name}: {e}")
            return False

    def get_active_accounts(self) -> dict[str, str]:
        """Get all accounts that are currently logged in"""
        active = {}
        for name, path in self.accounts.items():
            if self.check_login_status(name):
                active[name] = path
        return active

    def setup_all_accounts(self):
        """Interactive setup for all configured accounts"""
        print("=== Claude Account Setup ===")
        print(f"Found {len(self.accounts)} configured accounts:\n")

        for name, path in self.accounts.items():
            print(f"Account: {name}")
            print(f"Config: {path}")

            if self.check_login_status(name):
                print("Status: ✓ Logged in")
            else:
                print("Status: ✗ Not logged in")
                response = input("Would you like to login now? (y/n): ")
                if response.lower() == "y":
                    self.login_account(name)

            print("-" * 40)

        # Summary
        active = self.get_active_accounts()
        print(f"\nActive accounts: {len(active)}/{len(self.accounts)}")
        if active:
            print("Ready to use:", ", ".join(active.keys()))


if __name__ == "__main__":
    # Run account setup
    manager = ConfigManager()
    manager.setup_all_accounts()
