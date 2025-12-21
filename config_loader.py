"""
Configuration loader for Gofile API credentials
Handles loading API token and account ID from config file
"""

import json
import os
from typing import Dict, Optional


class Config:
    """Configuration manager for Gofile API credentials."""
    
    def __init__(self, config_file: str = "config.json"):
        """
        Initialize configuration manager.
        
        Args:
            config_file: Path to the configuration file (default: config.json)
        """
        self.config_file = config_file
        self._config = None
    
    def load(self) -> Dict[str, str]:
        """
        Load configuration from file.
        
        Returns:
            Dictionary containing configuration values
        
        Raises:
            FileNotFoundError: If config file doesn't exist
            json.JSONDecodeError: If config file is invalid JSON
        """
        if self._config is not None:
            return self._config
        
        if not os.path.exists(self.config_file):
            raise FileNotFoundError(
                f"Configuration file not found: {self.config_file}\n"
                f"Please create a config.json file with your API credentials."
            )
        
        with open(self.config_file, 'r') as f:
            self._config = json.load(f)
        
        return self._config
    
    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """
        Get a configuration value.
        
        Args:
            key: Configuration key
            default: Default value if key doesn't exist
        
        Returns:
            Configuration value or default
        """
        config = self.load()
        return config.get(key, default)
    
    @property
    def api_token(self) -> str:
        """Get the API token."""
        token = self.get('api_token')
        if not token:
            raise ValueError("API token not found in configuration")
        return token
    
    @property
    def account_id(self) -> str:
        """Get the account ID."""
        account_id = self.get('account_id')
        if not account_id:
            raise ValueError("Account ID not found in configuration")
        return account_id
    
    @property
    def buzzheavier_account_id(self) -> str:
        """Get the Buzzheavier account ID."""
        account_id = self.get('buzzheavier_account_id')
        if not account_id:
            raise ValueError("Buzzheavier account ID not found in configuration")
        return account_id
    
    @property
    def pixeldrain_api_key(self) -> str:
        """Get the Pixeldrain API key."""
        api_key = self.get('pixeldrain_api_key')
        if not api_key:
            raise ValueError("Pixeldrain API key not found in configuration")
        return api_key
    
    def save(self, config_data: Dict[str, str]) -> None:
        """
        Save configuration to file.
        
        Args:
            config_data: Dictionary of configuration values to save
        """
        with open(self.config_file, 'w') as f:
            json.dump(config_data, f, indent=2)
        
        self._config = config_data
    
    def update(self, key: str, value: str) -> None:
        """
        Update a single configuration value.
        
        Args:
            key: Configuration key to update
            value: New value
        """
        config = self.load()
        config[key] = value
        self.save(config)


def load_config(config_file: str = "config.json") -> Config:
    """
    Load configuration from file.
    
    Args:
        config_file: Path to configuration file
    
    Returns:
        Config object
    """
    return Config(config_file)


# Example usage
if __name__ == "__main__":
    try:
        config = load_config()
        print(f"API Token: {config.api_token[:10]}...")
        print(f"Account ID: {config.account_id}")
    except FileNotFoundError as e:
        print(f"Error: {e}")
    except Exception as e:
        print(f"Error loading config: {e}")
