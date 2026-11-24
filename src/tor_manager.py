"""
Tor Process and Onion Service Manager for OnionHost.
Manages Tor detection, automatic download of Tor Expert Bundle if needed,
generation of independent torrc configuration, subprocess lifecycle,
and persistent v3 onion address retrieval.
"""

import os
import sys
import time
import shutil
import tarfile
import logging
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import requests

from src.security import is_safe_path

logger = logging.getLogger("OnionHost.Tor")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
TOR_DATA_DIR = DATA_DIR / "tor"
SERVICES_DIR = DATA_DIR / "services"
LOGS_DIR = BASE_DIR / "logs"
TOR_LOG_FILE = LOGS_DIR / "tor.log"
CONFIG_DIR = BASE_DIR / "config"
TORRC_FILE = CONFIG_DIR / "torrc"
BIN_DIR = BASE_DIR / "bin" / "tor"

TOR_BROWSER_DEFAULT_PATH = r"C:\Users\mohsin\Desktop\Sessions\Tor Browser\Browser\TorBrowser\Tor\tor.exe"
TOR_OFFICIAL_DOWNLOAD_PAGE = "https://www.torproject.org/download/tor/"


class TorManager:
    def __init__(self, tor_binary_override: Optional[str] = None):
        self.tor_binary_override = tor_binary_override
        self.tor_binary_path: Optional[str] = None
        self.process: Optional[subprocess.Popen] = None
        self.bootstrap_percent = 0
        self.bootstrap_status = "Not started"
        self._ensure_dirs()
        self.locate_or_install_tor()

    def _ensure_dirs(self):
        for d in [DATA_DIR, TOR_DATA_DIR, SERVICES_DIR, LOGS_DIR, CONFIG_DIR, BIN_DIR]:
            d.mkdir(parents=True, exist_ok=True)

    def locate_or_install_tor(self) -> str:
        """
        Locates a valid Tor executable.
        1. Checks override or configured path.
        2. Inspects existing Tor Browser directory:
           C:\\Users\\mohsin\\Desktop\\Sessions\\Tor Browser\\Browser\\TorBrowser\\Tor\\tor.exe
        3. Checks local bin/tor/tor.exe
        4. Checks system PATH
        5. If not found, downloads official Tor Expert Bundle.
        """
        candidates = []
        if self.tor_binary_override and Path(self.tor_binary_override).exists():
            candidates.append(self.tor_binary_override)

        user_profile = os.environ.get("USERPROFILE", "")
        local_app_data = os.environ.get("LOCALAPPDATA", "")

        candidates.append(TOR_BROWSER_DEFAULT_PATH)
        if user_profile:
            candidates.append(os.path.join(user_profile, "Desktop", "Tor Browser", "Browser", "TorBrowser", "Tor", "tor.exe"))
            candidates.append(os.path.join(user_profile, "OneDrive", "Desktop", "Tor Browser", "Browser", "TorBrowser", "Tor", "tor.exe"))
        if local_app_data:
            candidates.append(os.path.join(local_app_data, "Tor Browser", "Browser", "TorBrowser", "Tor", "tor.exe"))
        candidates.append(r"C:\Program Files\Tor\tor.exe")
        candidates.append(r"C:\Program Files (x86)\Tor\tor.exe")
        candidates.append(str((BIN_DIR / "tor.exe").resolve()))

        # Check system path
        which_tor = shutil.which("tor.exe") or shutil.which("tor")
        if which_tor:
            candidates.append(which_tor)

        for candidate in candidates:
            if candidate and Path(candidate).is_file():
                version = self._test_tor_binary(candidate)
                if version:
                    logger.info(f"Using Tor binary: {candidate} (Version: {version})")
                    self.tor_binary_path = str(Path(candidate).resolve())
                    return self.tor_binary_path

        # If none found, attempt automatic download of Tor Expert Bundle
        logger.warning("No compatible Tor binary detected. Attempting to download Tor Expert Bundle...")
        downloaded = self.download_tor_expert_bundle()
        if downloaded:
            self.tor_binary_path = downloaded
            return self.tor_binary_path

        raise FileNotFoundError(
            "Could not locate or download a functional tor.exe. "
            "Please ensure internet connectivity or verify Tor Browser installation."
        )

    def _test_tor_binary(self, binary_path: str) -> Optional[str]:
        """Runs tor.exe --version to verify executable viability."""
        try:
            res = subprocess.run(
                [binary_path, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            if res.returncode == 0:
                first_line = res.stdout.strip().split("\n")[0]
                return first_line
        except Exception as e:
            logger.debug(f"Testing Tor candidate {binary_path} failed: {e}")
        return None

    def download_tor_expert_bundle(self) -> Optional[str]:
        """
        Downloads official Tor Expert Bundle for Windows 64-bit directly from torproject.org.
        Extracts tor.exe into bin/tor/.
        """
        logger.info(f"Fetching official Tor Expert Bundle download link from {TOR_OFFICIAL_DOWNLOAD_PAGE}...")
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            resp = requests.get(TOR_OFFICIAL_DOWNLOAD_PAGE, headers=headers, timeout=15)
            resp.raise_for_status()

            # Search for windows x86_64 expert bundle link (.tar.gz)
            import re
            matches = re.findall(
                r'href=[\'"]([^\'"]*tor-expert-bundle-windows-x86_64[^\'"]*\.tar\.gz)[\'"]',
                resp.text,
                re.IGNORECASE
            )

            if not matches:
                # Try relative link match
                matches = re.findall(
                    r'href=[\'"]([^\'"]*windows-x86_64[^\'"]*\.tar\.gz)[\'"]',
                    resp.text,
                    re.IGNORECASE
                )

            if not matches:
                logger.error("Could not locate Tor Expert Bundle download link on torproject.org.")
                return None

            download_url = matches[0]
            if not download_url.startswith("http"):
                from urllib.parse import urljoin
                download_url = urljoin(TOR_OFFICIAL_DOWNLOAD_PAGE, download_url)

            logger.info(f"Downloading Tor Expert Bundle from: {download_url}")
            bundle_file = BIN_DIR / "tor-expert-bundle.tar.gz"

            with requests.get(download_url, headers=headers, stream=True, timeout=60) as r:
                r.raise_for_status()
                with open(bundle_file, "wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        f.write(chunk)

            logger.info("Extracting Tor Expert Bundle...")
            with tarfile.open(bundle_file, "r:gz") as tar:
                # Find tor.exe in archive
                for member in tar.getmembers():
                    if member.name.endswith("tor.exe"):
                        member.name = "tor.exe"
                        tar.extract(member, path=BIN_DIR)
                        break

            # Cleanup bundle file
            bundle_file.unlink(missing_ok=True)

            tor_exe = BIN_DIR / "tor.exe"
            if tor_exe.exists():
                logger.info(f"Tor successfully extracted to {tor_exe}")
                return str(tor_exe.resolve())
            return None
        except Exception as e:
            logger.error(f"Error downloading Tor Expert Bundle: {e}")
            return None

    def generate_torrc(self, services: List[Dict[str, Any]]) -> str:
        """
        Generates an independent torrc configuration file.
        Each website in services gets its own persistent HiddenServiceDir and HiddenServicePort.
        Paths are formatted with forward slashes for Tor compatibility on Windows.
        """
        tor_data_str = str(TOR_DATA_DIR.resolve()).replace("\\", "/")
        tor_log_str = str(TOR_LOG_FILE.resolve()).replace("\\", "/")

        lines = [
            "# Auto-generated configuration for OnionHost",
            "# Independent instance - does not touch Tor Browser profile",
            f"DataDirectory {tor_data_str}",
            "SocksPort 0",
            f"Log notice file {tor_log_str}",
            "AvoidDiskWrites 1",
            ""
        ]

        for s in services:
            site_id = s["id"]
            local_port = s.get("local_port", 8000)
            onion_port = s.get("onion_port", 80)
            service_dir = (SERVICES_DIR / site_id).resolve()
            service_dir.mkdir(parents=True, exist_ok=True)
            service_dir_str = str(service_dir).replace("\\", "/")

            lines.extend([
                f"# Onion service for site: {s.get('name', site_id)}",
                f"HiddenServiceDir {service_dir_str}",
                f"HiddenServicePort {onion_port} 127.0.0.1:{local_port}",
                f"HiddenServiceVersion 3",
                ""
            ])

        content = "\n".join(lines)
        with open(TORRC_FILE, "w", encoding="utf-8") as f:
            f.write(content)

        return str(TORRC_FILE)

    def _cleanup_orphaned_tor_processes(self):
        """Terminates any old OnionHost tor.exe process without touching Tor Browser."""
        if sys.platform != "win32":
            return
        try:
            cmd = 'powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \\"Name = \'tor.exe\'\\" | Where-Object { $_.CommandLine -like \'*myonion site*\' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"'
            subprocess.run(cmd, shell=True, capture_output=True, timeout=5, check=False)
        except Exception:
            pass

    def start_tor(self, services: List[Dict[str, Any]], force_restart: bool = False) -> bool:
        """
        Starts the independent Tor process configured with the given services.
        If already running with the exact same services, keeps running.
        If active services changed or force_restart is True, cleanly restarts Tor with all services.
        """
        services_keys = sorted([s["id"] for s in services])
        current_keys = getattr(self, "_active_service_keys", [])

        if self.is_running() and not force_restart and services_keys == current_keys:
            logger.info("Tor process is already running with requested services.")
            return True

        if self.is_running():
            logger.info("Active services changed. Reconfiguring Tor with all active services...")
            self.stop_tor()
            time.sleep(1)

        self._cleanup_orphaned_tor_processes()
        self._active_service_keys = services_keys

        if not self.tor_binary_path:
            self.locate_or_install_tor()

        # Generate config
        torrc_path = self.generate_torrc(services)

        # Remove stale lock if present
        lock_file = TOR_DATA_DIR / "lock"
        if lock_file.exists():
            try:
                lock_file.unlink(missing_ok=True)
            except Exception:
                pass

        # Clear or rotate old tor log file
        try:
            with open(TOR_LOG_FILE, "w", encoding="utf-8") as f:
                f.write(f"--- OnionHost Tor Session Started at {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        except Exception:
            pass

        cmd = [self.tor_binary_path, "-f", torrc_path]
        logger.info(f"Launching Tor with {len(services)} onion service(s): {' '.join(cmd)}")

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            self.bootstrap_status = "Connecting"
            self.bootstrap_percent = 5
            return True
        except Exception as e:
            logger.error(f"Failed to launch Tor process: {e}")
            self.process = None
            return False

    def is_running(self) -> bool:
        """Checks if the managed Tor subprocess is active."""
        if self.process is None:
            return False
        ret = self.process.poll()
        return ret is None

    def wait_for_bootstrap(self, timeout: int = 60, callback=None) -> bool:
        """
        Monitors Tor bootstrap progress until 100% or timeout.
        Updates bootstrap status and percent.
        """
        start_time = time.time()
        last_percent = 0

        while time.time() - start_time < timeout:
            if not self.is_running():
                self.bootstrap_status = "Failed (Process exited prematurely)"
                logger.error("Tor process terminated unexpectedly during bootstrap.")
                return False

            # Check log file or process output for bootstrap notifications
            if TOR_LOG_FILE.exists():
                try:
                    with open(TOR_LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()
                        for line in lines[-15:]:
                            if "Bootstrapped" in line:
                                import re
                                match = re.search(r"Bootstrapped (\d+)%", line)
                                if match:
                                    percent = int(match.group(1))
                                    self.bootstrap_percent = percent
                                    if percent > last_percent:
                                        last_percent = percent
                                        self.bootstrap_status = f"Bootstrapping ({percent}%)"
                                        if callback:
                                            callback(percent, line.strip())
                                if "Bootstrapped 100%" in line:
                                    self.bootstrap_percent = 100
                                    self.bootstrap_status = "Connected"
                                    return True
                except Exception:
                    pass

            time.sleep(0.5)

        if self.bootstrap_percent >= 100:
            self.bootstrap_status = "Connected"
            return True

        self.bootstrap_status = f"Timeout reached at {self.bootstrap_percent}%"
        return False

    def get_onion_address(self, site_id: str, timeout: int = 15) -> Optional[str]:
        """
        Reads the generated persistent .onion address from the service directory.
        Waits up to timeout seconds if the file is being written.
        """
        hostname_file = SERVICES_DIR / site_id / "hostname"
        start_time = time.time()
        while time.time() - start_time < timeout:
            if hostname_file.exists():
                try:
                    with open(hostname_file, "r", encoding="utf-8") as f:
                        onion_addr = f.read().strip()
                        if onion_addr.endswith(".onion"):
                            return onion_addr
                except Exception:
                    pass
            time.sleep(0.5)
        return None

    def stop_tor(self):
        """Gracefully terminates the Tor process."""
        if not self.is_running():
            self.process = None
            return

        logger.info("Stopping Tor process...")
        try:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("Tor process did not exit gracefully, killing it.")
                self.process.kill()
        except Exception as e:
            logger.warning(f"Error terminating Tor process: {e}")
        finally:
            self.process = None
            self.bootstrap_status = "Stopped"
            self.bootstrap_percent = 0

    def get_recent_logs(self, max_lines: int = 100) -> List[str]:
        """Returns recent lines from tor.log."""
        if not TOR_LOG_FILE.exists():
            return []
        try:
            with open(TOR_LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
                return [line.strip() for line in lines[-max_lines:]]
        except Exception:
            return []

