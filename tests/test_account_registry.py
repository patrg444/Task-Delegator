"""Tests for AccountRegistry class."""

from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from task_delegator.account_registry import AccountRegistry


class TestAccountRegistry:
    """Test suite for AccountRegistry."""

    @pytest.fixture
    def temp_config(self, tmp_path):
        """Create temporary config file."""
        config_file = tmp_path / "accounts.json"
        return config_file

    @pytest.fixture
    def registry(self, temp_config):
        """Create AccountRegistry instance with temp config."""
        return AccountRegistry(config_file=temp_config)

    def test_initialization_defaults(self, registry):
        """Test initialization with default accounts."""
        accounts = registry.list_accounts()
        assert "work" in accounts
        assert "personal" in accounts
        assert accounts["work"] == Path.home() / ".claude-work"
        assert accounts["personal"] == Path.home() / ".claude-personal"

    def test_add_account(self, registry, tmp_path):
        """Test adding a new account."""
        test_dir = tmp_path / "test-account"
        registry.add_account("test", test_dir)

        accounts = registry.list_accounts()
        assert "test" in accounts
        assert accounts["test"] == test_dir
        assert test_dir.exists()

    def test_remove_account(self, registry):
        """Test removing an account."""
        registry.add_account("temp", Path("/tmp/temp"))
        assert "temp" in registry.list_accounts()

        result = registry.remove_account("temp")
        assert result is True
        assert "temp" not in registry.list_accounts()

        # Try removing non-existent account
        result = registry.remove_account("nonexistent")
        assert result is False

    def test_save_and_load_config(self, temp_config, tmp_path):
        """Test saving and loading configuration."""
        # Create and configure registry
        registry1 = AccountRegistry(config_file=temp_config)
        custom_path = tmp_path / "custom"
        registry1.add_account("custom", custom_path)
        registry1._active_accounts.add("custom")
        registry1.save_config()

        # Load in new registry
        registry2 = AccountRegistry(config_file=temp_config)
        accounts = registry2.list_accounts()

        assert "custom" in accounts
        assert accounts["custom"] == custom_path
        assert "custom" in registry2._active_accounts

    @patch("subprocess.run")
    def test_check_login_status_success(self, mock_run, registry):
        """Test checking login status when logged in."""
        mock_run.return_value = MagicMock(returncode=0, stdout='{"completion": "test response"}')

        result = registry.check_login_status("work")
        assert result is True
        assert "work" in registry._active_accounts

        # Verify subprocess was called correctly
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert call_args[0][0] == ["claude", "ask", "--json", "test"]
        assert "CLAUDE_CONFIG_DIR" in call_args[1]["env"]

    @patch("subprocess.run")
    def test_check_login_status_failure(self, mock_run, registry):
        """Test checking login status when not logged in."""
        mock_run.return_value = MagicMock(returncode=1, stdout="Error: Not authenticated")

        result = registry.check_login_status("work")
        assert result is False
        assert "work" not in registry._active_accounts

    @patch("subprocess.run")
    def test_check_login_status_invalid_json(self, mock_run, registry):
        """Test checking login status with invalid JSON response."""
        mock_run.return_value = MagicMock(returncode=0, stdout="Not valid JSON")

        result = registry.check_login_status("work")
        assert result is False

    def test_get_account_path(self, registry):
        """Test getting account path."""
        path = registry.get_account_path("work")
        assert path == Path.home() / ".claude-work"

        path = registry.get_account_path("nonexistent")
        assert path is None

    @patch.object(AccountRegistry, "check_login_status")
    def test_get_active_accounts(self, mock_check, registry):
        """Test getting active accounts."""

        # Mock login status
        def check_side_effect(name):
            return name == "work"

        mock_check.side_effect = check_side_effect

        active = registry.get_active_accounts()
        assert "work" in active
        assert "personal" not in active
        assert len(active) == 1

    @patch.object(AccountRegistry, "get_active_accounts")
    def test_get_available_workers(self, mock_active, registry):
        """Test getting available workers with limit."""
        mock_active.return_value = {
            "work": Path("/work"),
            "personal": Path("/personal"),
            "extra": Path("/extra"),
        }

        # No limit
        workers = registry.get_available_workers()
        assert len(workers) == 3

        # With limit
        workers = registry.get_available_workers(max_workers=2)
        assert len(workers) == 2

        # Limit exceeds available
        workers = registry.get_available_workers(max_workers=10)
        assert len(workers) == 3

    @patch("subprocess.run")
    @patch("builtins.print")
    def test_login_account_success(self, mock_print, mock_run, registry):
        """Test successful account login."""
        mock_run.return_value = MagicMock(returncode=0)

        result = registry.login_account("work")
        assert result is True
        assert "work" in registry._active_accounts

        # Verify subprocess was called with correct env
        call_args = mock_run.call_args
        assert call_args[0][0] == ["claude", "/login"]
        assert "CLAUDE_CONFIG_DIR" in call_args[1]["env"]

    @patch("subprocess.run")
    def test_login_account_failure(self, mock_run, registry):
        """Test failed account login."""
        import subprocess

        mock_run.side_effect = subprocess.CalledProcessError(1, ["claude", "/login"])

        result = registry.login_account("work")
        assert result is False

    def test_login_nonexistent_account(self, registry):
        """Test login attempt for non-existent account."""
        result = registry.login_account("nonexistent")
        assert result is False

    def test_load_config_with_error(self, tmp_path):
        """Test loading config with error."""
        config_file = tmp_path / "bad_config.json"
        config_file.write_text("invalid json")
        
        with patch("task_delegator.account_registry.logger") as mock_logger:
            registry = AccountRegistry(config_file=config_file)
            
            # Should log error and initialize defaults
            mock_logger.error.assert_called_once()
            # Default accounts depend on user's home directory
            assert len(registry._accounts) > 0  # At least some default accounts

    def test_check_login_status_error(self, registry):
        """Test check_login_status with error."""
        # Use an account that exists in the fixture
        test_account = "work"
        assert test_account in registry._accounts
        
        with (
            patch("subprocess.run", side_effect=Exception("Command failed")),
            patch("task_delegator.account_registry.logger") as mock_logger,
        ):
            result = registry.check_login_status(test_account)
            
            assert result is False
            mock_logger.error.assert_called_once()
            assert test_account not in registry._active_accounts

    def test_setup_all_accounts(self, registry, monkeypatch, capsys):
        """Test interactive setup of all accounts."""
        # Registry has 'work' and 'personal' accounts
        # Mock user inputs - 'n' for first not-logged-in account, 'y' for second
        inputs = iter(["y"])  # Only one response needed for personal account
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))
        
        # Mock check_login_status to return different values
        check_results = [True, False]  # work logged in, personal not
        registry.check_login_status = Mock(side_effect=check_results)
        
        # Mock login_account
        registry.login_account = Mock(return_value=True)
        
        # Mock get_active_accounts to return work account
        registry.get_active_accounts = Mock(return_value={"work": Path("/Users/patrickgloria/.claude-work")})
        
        active_count = registry.setup_all_accounts()
        
        assert active_count == 1
        assert registry.login_account.call_count == 1  # Called for "personal"
        
        captured = capsys.readouterr()
        assert "Claude Account Setup" in captured.out
        assert "✓ Logged in" in captured.out
        assert "✗ Not logged in" in captured.out
        assert "Ready to use: work" in captured.out

    def test_setup_all_accounts_all_active(self, registry, monkeypatch, capsys):
        """Test setup when all accounts are already active."""
        # All accounts logged in
        registry.check_login_status = Mock(return_value=True)
        registry.get_active_accounts = Mock(return_value={
            "home": Path("/tmp/home"),
            "work": Path("/tmp/work"),
            "personal": Path("/tmp/personal")
        })
        
        active_count = registry.setup_all_accounts()
        
        assert active_count == 3
        
        captured = capsys.readouterr()
        assert "Ready to use: home, work, personal" in captured.out
