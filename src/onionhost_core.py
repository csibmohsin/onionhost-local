"""
OnionHost Core Controller.
Coordinates configuration, local web servers, Tor process, and website management.
"""

import os
import sys
import time
import signal
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from src.config_manager import ConfigManager
from src.server_manager import ServerManager
from src.tor_manager import TorManager
from src.website_manager import WebsiteManager
from src.security import validate_website_directory

logger = logging.getLogger("OnionHost.Core")


class OnionHostCore:
    _instance = None

    def __init__(self):
        self.config = ConfigManager()
        self.server_mgr = ServerManager()
        self.tor_mgr = TorManager(tor_binary_override=self.config.get("tor_binary"))
        self.website_mgr = WebsiteManager(self.config)
        self.running_sites: Dict[str, Dict[str, Any]] = {}
        self.start_time = time.time()

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = OnionHostCore()
        return cls._instance

    def prepare_site_id(self, folder_path: str) -> str:
        """Derives a clean, consistent site ID from the directory path or folder name."""
        p = Path(folder_path).resolve()
        base_name = p.name.lower()
        # Clean slug
        clean_slug = "".join(c if c.isalnum() else "_" for c in base_name).strip("_")
        if not clean_slug:
            clean_slug = "site"

        # Check existing sites to see if already mapped
        existing = self.config.find_site_by_path(str(p))
        if existing:
            return existing["id"]

        # Ensure uniqueness
        candidate = clean_slug
        count = 1
        while self.config.get_site(candidate) is not None:
            candidate = f"{clean_slug}_{count}"
            count += 1
        return candidate

    def start_hosting(self, folder_path: str, port: Optional[int] = None,
                      progress_callback=None) -> tuple[bool, Dict[str, Any], str]:
        """
        Hosts an HTML website folder as a Tor onion service.
        1. Validates folder path.
        2. Starts local HTTP server bound exclusively to 127.0.0.1.
        3. Starts or reconfigures Tor process.
        4. Waits for Tor bootstrap.
        5. Retrieves persistent .onion address.
        6. Updates configuration and runtime state.
        """
        valid, msg = validate_website_directory(folder_path)
        if not valid:
            return False, {}, msg

        resolved_folder = str(Path(folder_path).resolve())

        # If directory is completely empty or has no index.html, scaffold sample site
        index_file = Path(resolved_folder) / "index.html"
        if not index_file.exists():
            self.website_mgr.create_sample_website_if_needed(resolved_folder)

        # Get or create site registration
        site_id = self.prepare_site_id(resolved_folder)
        desired_port = port if port else self.config.get("default_http_port", 8000)

        # 1. Start Local HTTP Server
        if progress_callback:
            progress_callback(10, f"Starting local web server on port {desired_port}...")

        success, actual_port, err = self.server_mgr.start_site_server(site_id, resolved_folder, desired_port)
        if not success:
            return False, {}, f"Failed to start local web server: {err}"

        # Register in config
        site_info = self.config.register_or_update_site(
            site_id=site_id,
            name=Path(resolved_folder).name,
            folder_path=resolved_folder,
            local_port=actual_port,
            onion_port=80
        )

        # 2. Gather all active services for Tor configuration
        active_services = [site_info]
        # Include any other currently running sites
        for other_id, other_info in self.running_sites.items():
            if other_id != site_id:
                active_services.append(other_info)

        # 3. Start Tor
        if progress_callback:
            progress_callback(30, "Initializing Tor onion service...")

        if not self.tor_mgr.start_tor(active_services):
            self.server_mgr.stop_site_server(site_id)
            return False, {}, "Failed to launch Tor process."

        # 4. Wait for bootstrap
        if progress_callback:
            progress_callback(40, "Connecting to Tor network (bootstrapping)...")

        def tor_cb(pct, status_line):
            if progress_callback:
                progress_callback(min(90, 40 + int(pct * 0.5)), f"Tor: {status_line}")

        bootstrapped = self.tor_mgr.wait_for_bootstrap(timeout=60, callback=tor_cb)
        if not bootstrapped:
            self.server_mgr.stop_site_server(site_id)
            self.tor_mgr.stop_tor()
            return False, {}, f"Tor network bootstrap timed out or failed: {self.tor_mgr.bootstrap_status}"

        # 5. Retrieve Onion Address
        if progress_callback:
            progress_callback(95, "Resolving persistent .onion address...")

        onion_address = self.tor_mgr.get_onion_address(site_id, timeout=20)
        if not onion_address:
            return False, {}, "Tor bootstrapped, but failed to retrieve onion address from service directory."

        site_info["onion_address"] = onion_address
        site_info["status"] = "running"
        self.config.update_site_onion_address(site_id, onion_address)
        self.config.update_site_status(site_id, "running")
        self.config.set("active_site_id", site_id)

        self.running_sites[site_id] = site_info

        # Save runtime state (PIDs, etc.)
        self._record_runtime_state()

        if progress_callback:
            progress_callback(100, "Hosting online!")

        return True, site_info, ""

    def start_hosting_proxy(self, site_id: str, name: str, target_url: str, port: int = None, progress_callback=None) -> tuple[bool, Dict[str, Any], str]:
        """
        Hosts a live clear-web website URL as an onion service via local reverse proxy mirror.
        Traffic to .onion address is forwarded to the live target_url.
        """
        clean_url = target_url.strip()
        if not clean_url.startswith(('http://', 'https://')):
            clean_url = 'https://' + clean_url

        desired_port = port if port else self.config.get("default_http_port", 8090)

        if progress_callback:
            progress_callback(15, f"Starting local proxy forwarder on port {desired_port} for {clean_url}...")

        success, actual_port, err = self.server_mgr.start_site_proxy(site_id, clean_url, desired_port)
        if not success:
            return False, {}, f"Failed to start local proxy forwarder: {err}"

        # Register in config
        site_info = self.config.register_or_update_site(
            site_id=site_id,
            name=name,
            folder_path=clean_url,
            local_port=actual_port,
            onion_port=80
        )
        site_info["is_proxy"] = True
        site_info["target_url"] = clean_url
        site_info["subpath"] = ""
        self.config.settings.setdefault("sites", {}).setdefault(site_id, {})["is_proxy"] = True
        self.config.settings["sites"][site_id]["target_url"] = clean_url
        self.config.save_settings()

        # Gather active services
        active_services = [site_info]
        for other_id, other_info in self.running_sites.items():
            if other_id != site_id:
                active_services.append(other_info)

        if progress_callback:
            progress_callback(35, "Configuring Tor hidden service mirror...")

        if not self.tor_mgr.start_tor(active_services, force_restart=True):
            self.server_mgr.stop_site_server(site_id)
            return False, {}, "Failed to launch Tor process."

        bootstrapped = self.tor_mgr.wait_for_bootstrap(timeout=60)
        if not bootstrapped:
            self.server_mgr.stop_site_server(site_id)
            self.tor_mgr.stop_tor()
            return False, {}, "Tor bootstrap timed out."

        onion_address = self.tor_mgr.get_onion_address(site_id, timeout=20)
        if not onion_address:
            return False, {}, "Failed to retrieve .onion address from service directory."

        site_info["onion_address"] = onion_address
        site_info["status"] = "running"
        self.config.update_site_onion_address(site_id, onion_address)
        self.config.update_site_status(site_id, "running")
        self.running_sites[site_id] = site_info
        self._record_runtime_state()

        if progress_callback:
            progress_callback(100, "Tor mirror online!")

        return True, site_info, ""

    def stop_site(self, site_id: str) -> bool:
        """Stops hosting a specific site."""
        if site_id in self.running_sites:
            self.server_mgr.stop_site_server(site_id)
            del self.running_sites[site_id]
            self.config.update_site_status(site_id, "stopped")

        # If no sites running, stop Tor completely
        if not self.running_sites:
            self.tor_mgr.stop_tor()
            self.config.clear_runtime_state()
        else:
            # Reconfigure Tor with remaining sites
            self.tor_mgr.start_tor(list(self.running_sites.values()), force_restart=True)
            self._record_runtime_state()

        return True

    def start_multiple_sites(self, sites_config: List[Dict[str, Any]], progress_callback=None) -> Dict[str, Any]:
        """
        Hosts multiple website directories simultaneously.
        Each website gets its own local server port and persistent onion v3 address.
        """
        results = {}
        active_list = list(self.running_sites.values())

        for idx, item in enumerate(sites_config):
            folder_path = item.get("folder_path", "")
            port = item.get("port")

            # Check if this item is a live URL mirror proxy
            is_url_proxy = item.get("is_proxy") or str(folder_path).startswith(("http://", "https://"))
            if is_url_proxy:
                target_url = str(folder_path).strip()
                site_name = item.get("name") or ("Mirror_" + str(idx + 1))
                site_id = item.get("id") or "".join(c if c.isalnum() else "_" for c in site_name.lower()).strip("_")
                desired_port = port if port else self.config.get("default_http_port", 8090) + idx
                success, actual_port, err = self.server_mgr.start_site_proxy(site_id, target_url, desired_port)
                if not success:
                    results[site_id] = {"success": False, "error": err}
                    continue
                site_info = self.config.register_or_update_site(
                    site_id=site_id,
                    name=site_name,
                    folder_path=target_url,
                    local_port=actual_port,
                    onion_port=80
                )
                site_info["is_proxy"] = True
                site_info["target_url"] = target_url
                active_list = [s for s in active_list if s["id"] != site_id]
                active_list.append(site_info)
                results[site_id] = {"success": True, "site": site_info}
                continue

            valid, msg = validate_website_directory(folder_path)
            if not valid:
                results[folder_path] = {"success": False, "error": msg}
                continue

            resolved_folder = str(Path(folder_path).resolve())
            index_file = Path(resolved_folder) / "index.html"
            if not index_file.exists():
                self.website_mgr.create_sample_website_if_needed(resolved_folder)

            site_id = self.prepare_site_id(resolved_folder)
            desired_port = port if port else self.config.get("default_http_port", 8000) + idx

            success, actual_port, err = self.server_mgr.start_site_server(site_id, resolved_folder, desired_port)
            if not success:
                results[site_id] = {"success": False, "error": err}
                continue

            site_info = self.config.register_or_update_site(
                site_id=site_id,
                name=Path(resolved_folder).name,
                folder_path=resolved_folder,
                local_port=actual_port,
                onion_port=80
            )
            # Remove if already exists in active_list to avoid duplicate
            active_list = [s for s in active_list if s["id"] != site_id]
            active_list.append(site_info)
            results[site_id] = {"success": True, "site": site_info}

        if not active_list:
            return {"success": False, "results": results}

        # Start Tor with all active services
        if progress_callback:
            progress_callback(30, f"Configuring Tor for {len(active_list)} active websites...")

        self.tor_mgr.start_tor(active_list, force_restart=True)
        bootstrapped = self.tor_mgr.wait_for_bootstrap(timeout=60)
        if not bootstrapped:
            return {"success": False, "error": "Tor bootstrap timed out", "results": results}

        # Retrieve onion address for all newly started sites
        for site_id, res in results.items():
            if res.get("success"):
                onion_addr = self.tor_mgr.get_onion_address(site_id, timeout=20)
                if onion_addr:
                    res["site"]["onion_address"] = onion_addr
                    res["site"]["status"] = "running"
                    self.config.update_site_onion_address(site_id, onion_addr)
                    self.config.update_site_status(site_id, "running")
                    self.running_sites[site_id] = res["site"]

        self._record_runtime_state()
        return {"success": True, "running_sites": self.running_sites, "results": results}

    def stop_all(self):
        """Stops all running servers and the Tor daemon."""
        logger.info("Stopping all OnionHost services...")
        self.server_mgr.stop_all()
        self.tor_mgr.stop_tor()
        for site_id in list(self.running_sites.keys()):
            self.config.update_site_status(site_id, "stopped")
        self.running_sites.clear()
        self.config.clear_runtime_state()
        logger.info("All OnionHost services stopped.")

    def _record_runtime_state(self):
        """Records runtime PID and active site state into data/runtime.json."""
        state = {
            "pid": os.getpid(),
            "tor_pid": self.tor_mgr.process.pid if self.tor_mgr.process else None,
            "start_time": self.start_time,
            "running_sites": self.running_sites
        }
        self.config.save_runtime_state(state)

    def get_system_status(self) -> Dict[str, Any]:
        """Returns comprehensive status of the application."""
        tor_running = self.tor_mgr.is_running()
        active_count = len(self.running_sites)

        sites_data = []
        for s in self.config.list_sites():
            site_id = s["id"]
            is_active = site_id in self.running_sites and self.server_mgr.is_site_running(site_id)
            stats = self.server_mgr.get_site_stats(site_id) if is_active else None
            site_copy = dict(s)
            site_copy["is_active"] = is_active
            site_copy["stats"] = stats
            sites_data.append(site_copy)

        return {
            "tor_status": "Connected" if tor_running and self.tor_mgr.bootstrap_percent >= 100 else self.tor_mgr.bootstrap_status,
            "tor_running": tor_running,
            "tor_binary": self.tor_mgr.tor_binary_path,
            "bootstrap_percent": self.tor_mgr.bootstrap_percent,
            "active_sites_count": active_count,
            "sites": sites_data,
            "uptime_seconds": int(time.time() - self.start_time),
            "dashboard_port": self.config.get("dashboard_port", 5000)
        }

