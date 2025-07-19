"""Account registry to manage Claude configurations without global state."""

import json
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class AccountRegistry:
    """Registry for managing multiple Claude account configurations."""

    def __init__(self, config_file: Path | None = None):
        """Initialize registry with optional config file."""
        self.config_file = config_file or Path.home() / ".claude-task-delegator" / "accounts.json"
        self._accounts: dict[str, Path] = {}
        self._active_accounts: set[str] = set()
        self.load_config()

    def load_config(self) -> None:
        """Load account configurations from file."""
        if self.config_file.exists():
            try:
                with open(self.config_file) as f:
                    data = json.load(f)
                    for name, path in data.get("accounts", {}).items():
                        self._accounts[name] = Path(path)
                    self._active_accounts = set(data.get("active", []))
                logger.info(f"Loaded {len(self._accounts)} accounts from {self.config_file}")
            except Exception as e:
                logger.error(f"Failed to load config: {e}")
                self._initialize_defaults()
        else:
            self._initialize_defaults()

    def _initialize_defaults(self) -> None:
        """Initialize with default account paths."""
        self._accounts = {
            "work": Path.home() / ".claude-work",
            "personal": Path.home() / ".claude-personal",
        }
        logger.info("Initialized with default accounts")

    def save_config(self) -> None:
        """Save current configuration to file."""
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "accounts": {name: str(path) for name, path in self._accounts.items()},
            "active": list(self._active_accounts),
        }
        with open(self.config_file, "w") as f:
            json.dump(data, f, indent=2)
        logger.info(f"Saved config to {self.config_file}")

    def add_account(self, name: str, config_dir: Path) -> None:
        """Add a new account configuration."""
        if name in self._accounts:
            logger.warning(f"Account {name} already exists, updating path")
        self._accounts[name] = config_dir
        config_dir.mkdir(parents=True, exist_ok=True)
        self.save_config()
        logger.info(f"Added account '{name}' with config dir: {config_dir}")

    def remove_account(self, name: str) -> bool:
        """Remove an account configuration."""
        if name in self._accounts:
            del self._accounts[name]
            self._active_accounts.discard(name)
            self.save_config()
            logger.info(f"Removed account '{name}'")
            return True
        return False

    def get_account_path(self, name: str) -> Path | None:
        """Get configuration path for an account."""
        return self._accounts.get(name)

    def list_accounts(self) -> dict[str, Path]:
        """Get all registered accounts."""
        return self._accounts.copy()

    def check_login_status(self, account_name: str) -> bool:
        """Check if an account is logged in."""
        if account_name not in self._accounts:
            return False

        config_dir = self._accounts[account_name]

        try:
            # Try a simple command to check if authenticated
            result = subprocess.run(
                ["claude", "ask", "--json", "test"],
                capture_output=True,
                text=True,
                env={"CLAUDE_CONFIG_DIR": str(config_dir)},
                timeout=5,
            )

            # If we get a proper JSON response, we're logged in
            if result.returncode == 0:
                try:
                    json.loads(result.stdout)
                    self._active_accounts.add(account_name)
                    return True
                except json.JSONDecodeError:
                    pass

            self._active_accounts.discard(account_name)
            return False

        except Exception as e:
            logger.error(f"Error checking login status for {account_name}: {e}")
            self._active_accounts.discard(account_name)
            return False

    def get_active_accounts(self) -> dict[str, Path]:
        """Get all accounts that are currently logged in."""
        active = {}
        for name, path in self._accounts.items():
            if self.check_login_status(name):
                active[name] = path
        self.save_config()  # Update active status
        return active

    def get_available_workers(self, max_workers: int | None = None) -> dict[str, Path]:
        """Get available worker accounts up to max_workers limit."""
        active = self.get_active_accounts()
        if max_workers is None:
            return active

        # Return first N active accounts
        limited = {}
        for i, (name, path) in enumerate(active.items()):
            if i >= max_workers:
                break
            limited[name] = path
        return limited

    def login_account(self, account_name: str) -> bool:
        """Initiate interactive login for an account."""
        if account_name not in self._accounts:
            logger.error(f"Account '{account_name}' not found")
            return False

        config_dir = self._accounts[account_name]

        print(f"\nInitiating login for account '{account_name}'...")
        print(f"Config directory: {config_dir}")

        try:
            # Run interactive login
            subprocess.run(
                ["claude", "/login"], env={"CLAUDE_CONFIG_DIR": str(config_dir)}, check=True
            )
            self._active_accounts.add(account_name)
            self.save_config()
            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"Login failed for {account_name}: {e}")
            return False

    def setup_all_accounts(self) -> int:
        """Interactive setup for all configured accounts. Returns number of active accounts."""
        print("=== Claude Account Setup ===")
        print(f"Found {len(self._accounts)} configured accounts:\n")

        for name, path in self._accounts.items():
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
        print(f"\nActive accounts: {len(active)}/{len(self._accounts)}")
        if active:
            print("Ready to use:", ", ".join(active.keys()))

        return len(active)
