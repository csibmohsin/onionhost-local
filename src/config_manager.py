"""
Configuration Manager for OnionHost.
Manages global settings, website site registries, and runtime state.
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
TOR_DATA_DIR = DATA_DIR / "tor"
SERVICES_DIR = DATA_DIR / "services"
LOGS_DIR = BASE_DIR / "logs"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
RUNTIME_FILE = DATA_DIR / "runtime.json"

DEFAULT_TOR_BROWSER_EXE = r"C:\Users\mohsin\Desktop\Sessions\Tor Browser\Browser\TorBrowser\Tor\tor.exe"

logger = logging.getLogger("OnionHost.Config")


class ConfigManager:
    def __init__(self):
        self._ensure_directories()
        self.settings: Dict[str, Any] = self._load_default_settings()
        self.load_settings()

    def _ensure_directories(self):
        """Create required project directories if they do not exist."""
        for directory in [CONFIG_DIR, DATA_DIR, TOR_DATA_DIR, SERVICES_DIR, LOGS_DIR]:
            directory.mkdir(parents=True, exist_ok=True)

    def _load_default_settings(self) -> Dict[str, Any]:
        return {
            "version": "1.0.0",
            "tor_binary": DEFAULT_TOR_BROWSER_EXE if Path(DEFAULT_TOR_BROWSER_EXE).exists() else "tor.exe",
            "dashboard_port": 5000,
            "dashboard_host": "127.0.0.1",
            "default_http_port": 8000,
            "sites": {},
            "active_site_id": None
        }

    def load_settings(self) -> Dict[str, Any]:
        """Loads configuration from settings.json."""
        if SETTINGS_FILE.exists():
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.settings.update(data)
            except Exception as e:
                logger.error(f"Error loading settings file: {e}")
        else:
            self.save_settings()
        return self.settings

    def save_settings(self) -> bool:
        """Saves current settings to settings.json."""
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=4)
            return True
        except Exception as e:
            logger.error(f"Error saving settings file: {e}")
            return False

    def get(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)

    def set(self, key: str, value: Any) -> bool:
        self.settings[key] = value
        return self.save_settings()

    # --- Site Registry Operations ---

    def list_sites(self) -> List[Dict[str, Any]]:
        """Return list of all configured sites."""
        return list(self.settings.get("sites", {}).values())

    def get_site(self, site_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve site details by site_id."""
        return self.settings.get("sites", {}).get(site_id)

    def find_site_by_path(self, folder_path: str) -> Optional[Dict[str, Any]]:
        """Check if a folder path is already registered under any site."""
        resolved = str(Path(folder_path).resolve())
        for site in self.list_sites():
            try:
                if str(Path(site.get("path", "")).resolve()) == resolved:
                    return site
            except Exception:
                continue
        return None

    def register_or_update_site(self, site_id: str, name: str, folder_path: str,
                                local_port: int, onion_port: int = 80) -> Dict[str, Any]:
        """Registers a new website or updates an existing one."""
        resolved_path = str(Path(folder_path).resolve())
        site_data = self.settings.get("sites", {}).get(site_id, {})
        site_data.update({
            "id": site_id,
            "name": name,
            "path": resolved_path,
            "local_port": local_port,
            "onion_port": onion_port,
            "service_dir": str((SERVICES_DIR / site_id).resolve()),
            "status": site_data.get("status", "stopped"),
            "onion_address": site_data.get("onion_address", None)
        })
        self.settings.setdefault("sites", {})[site_id] = site_data
        self.save_settings()
        return site_data

    def remove_site(self, site_id: str) -> bool:
        """Removes a site registration."""
        if site_id in self.settings.get("sites", {}):
            del self.settings["sites"][site_id]
            self.save_settings()
            return True
        return False

    def update_site_onion_address(self, site_id: str, onion_address: str):
        """Updates the recorded onion address for a site."""
        if site_id in self.settings.get("sites", {}):
            self.settings["sites"][site_id]["onion_address"] = onion_address
            self.save_settings()

    def update_site_status(self, site_id: str, status: str):
        """Updates the status (running/stopped) of a site."""
        if site_id in self.settings.get("sites", {}):
            self.settings["sites"][site_id]["status"] = status
            self.save_settings()

    # --- Runtime State Operations (for CLI / IPC stop/status) ---

    def load_runtime_state(self) -> Dict[str, Any]:
        """Loads live process and hosting runtime information."""
        if RUNTIME_FILE.exists():
            try:
                with open(RUNTIME_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def save_runtime_state(self, state: Dict[str, Any]):
        """Persists live runtime state."""
        try:
            with open(RUNTIME_FILE, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=4)
        except Exception as e:
            logger.error(f"Error saving runtime state: {e}")

    def clear_runtime_state(self):
        """Clears runtime state upon full shutdown."""
        if RUNTIME_FILE.exists():
            try:
                RUNTIME_FILE.unlink(missing_ok=True)
            except Exception:
                pass

