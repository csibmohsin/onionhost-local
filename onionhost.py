#!/usr/bin/env python3
"""
OnionHost CLI Interface.
Command-line controller for hosting static websites over Tor.
"""

import os
import sys
import time
import signal
import argparse
import webbrowser
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.onionhost_core import OnionHostCore
from src.config_manager import ConfigManager

TOR_BROWSER_EXE = r"C:\Users\mohsin\Desktop\Sessions\Tor Browser\Browser\firefox.exe"


def print_banner():
    banner = """========================================
          ONIONHOST
========================================"""
    print(banner)


def handle_stop():
    """Stops any running OnionHost background or daemon instances."""
    config = ConfigManager()
    runtime = config.load_runtime_state()
    if not runtime:
        print("[OnionHost] No running OnionHost instance found.")
        return 0

    pid = runtime.get("pid")
    tor_pid = runtime.get("tor_pid")
    stopped_any = False

    if tor_pid:
        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/F", "/PID", str(tor_pid)], capture_output=True)
            else:
                os.kill(tor_pid, signal.SIGTERM)
            print(f"[OnionHost] Stopped Tor process (PID: {tor_pid}).")
            stopped_any = True
        except Exception:
            pass

    if pid and pid != os.getpid():
        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
            else:
                os.kill(pid, signal.SIGTERM)
            print(f"[OnionHost] Stopped OnionHost server process (PID: {pid}).")
            stopped_any = True
        except Exception:
            pass

    config.clear_runtime_state()
    # Also update site statuses to stopped
    for site in config.list_sites():
        config.update_site_status(site["id"], "stopped")

    print("[OnionHost] All services have been stopped.")
    return 0


def handle_status():
    """Displays current hosting and Tor status."""
    config = ConfigManager()
    runtime = config.load_runtime_state()
    print_banner()
    if not runtime:
        print("Status: STOPPED (No active hosting sessions)")
        print("\nRegistered websites:")
        sites = config.list_sites()
        if not sites:
            print("  No websites registered yet. Run: onionhost <path_to_website>")
        else:
            for s in sites:
                print(f"  - {s.get('name', 'Site')} ({s.get('id')})")
                print(f"    Folder: {s.get('path')}")
                print(f"    Onion:  {s.get('onion_address', 'Not yet generated')}")
                print(f"    Port:   {s.get('local_port')}")
        print("========================================")
        return 0

    print("Status: RUNNING")
    print(f"Process PID: {runtime.get('pid')}")
    print(f"Tor PID:     {runtime.get('tor_pid')}")
    running_sites = runtime.get("running_sites", {})
    for site_id, site in running_sites.items():
        print(f"\nWebsite:      {site.get('path')}")
        print(f"Local Server: http://127.0.0.1:{site.get('local_port')}")
        print(f"Onion:        {site.get('onion_address')}")
    print("========================================")
    return 0


def handle_list():
    """Lists all configured sites."""
    config = ConfigManager()
    sites = config.list_sites()
    print_banner()
    print("Configured Websites:")
    if not sites:
        print("  No websites registered yet.")
        print("  Run 'onionhost <folder>' to host your first website.")
    else:
        for i, s in enumerate(sites, 1):
            status = s.get("status", "stopped").upper()
            print(f"\n[{i}] {s.get('name')} (Status: {status})")
            print(f"    Path:    {s.get('path')}")
            print(f"    Port:    {s.get('local_port')}")
            print(f"    Onion:   {s.get('onion_address', 'None')}")
            print(f"    Service: {s.get('service_dir')}")
    print("========================================")
    return 0


def handle_open(target: Optional[str] = None):
    """Opens the active onion address or dashboard."""
    config = ConfigManager()
    runtime = config.load_runtime_state()

    onion_url = None
    if runtime and "running_sites" in runtime:
        for s in runtime["running_sites"].values():
            if s.get("onion_address"):
                onion_url = f"http://{s['onion_address']}"
                break

    if not onion_url:
        # Check registered sites
        for s in config.list_sites():
            if s.get("onion_address"):
                onion_url = f"http://{s['onion_address']}"
                break

    dashboard_url = f"http://127.0.0.1:{config.get('dashboard_port', 5000)}"

    if onion_url:
        print(f"[OnionHost] Opening Onion URL: {onion_url}")
        if Path(TOR_BROWSER_EXE).exists():
            print(f"[OnionHost] Launching Tor Browser ({TOR_BROWSER_EXE})...")
            try:
                subprocess.Popen([TOR_BROWSER_EXE, onion_url])
                return 0
            except Exception as e:
                print(f"[OnionHost] Error launching Tor Browser: {e}")

        # Fallback to default browser
        print("[OnionHost] Opening in system browser (Note: Tor Browser required for .onion links)...")
        webbrowser.open(onion_url)
    else:
        print(f"[OnionHost] No active onion site found. Opening Dashboard: {dashboard_url}")
        webbrowser.open(dashboard_url)
    return 0


def run_host_cli(folder_path: str, port: Optional[int] = None):
    """Runs the primary onionhost command for local folders or live website URLs."""
    core = OnionHostCore.get_instance()

    # Detect if user entered a live website URL (e.g. www.csib.co.in or https://...)
    is_url = folder_path.startswith(("http://", "https://", "www.")) or any(folder_path.endswith(tld) for tld in [".com", ".in", ".org", ".net", ".io", ".co"])

    def progress(pct, msg):
        try:
            if sys.stdout:
                sys.stdout.write(f"\r[{pct:>3}%] {msg:<50}")
                sys.stdout.flush()
        except Exception:
            pass

    if is_url:
        clean_url = folder_path
        if not clean_url.startswith(("http://", "https://")):
            clean_url = "https://" + clean_url
        import urllib.parse
        parsed = urllib.parse.urlparse(clean_url)
        site_name = parsed.netloc or "WebMirror"
        site_id = "".join(c if c.isalnum() else "_" for c in site_name.lower()).strip("_") or "mirror"

        print(f"\nStarting OnionHost Tor Mirror for: {clean_url}...")
        success, site_info, err = core.start_hosting_proxy(
            site_id=site_id,
            name=site_name,
            target_url=clean_url,
            port=port,
            progress_callback=progress
        )
    else:
        resolved_path = str(Path(folder_path).resolve())
        if not Path(resolved_path).exists() or not Path(resolved_path).is_dir():
            print(f"Error: Directory '{folder_path}' does not exist or is not a directory.")
            return 1

        print("\nStarting OnionHost...")
        success, site_info, err = core.start_hosting(
            folder_path=resolved_path,
            port=port,
            progress_callback=progress
        )

    print("\n")

    if not success:
        print(f"[ERROR] Failed to start hosting: {err}")
        core.stop_all()
        return 1

    local_url = f"http://127.0.0.1:{site_info['local_port']}"
    onion_url = site_info["onion_address"]

    output = f"""========================================
          ONIONHOST
========================================

Website: {site_info['path']}
Local Server: {local_url}

Tor Status: Connected
Onion Service: Active

Your Onion Website:

{onion_url}

Hosting: RUNNING

Press CTRL+C to stop hosting.

========================================"""
    print(output)

    # Setup graceful exit on SIGINT or SIGTERM
    def shutdown_handler(signum, frame):
        print("\n\nShutting down OnionHost...")
        core.stop_all()
        print("Hosting stopped cleanly. Goodbye.")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, shutdown_handler)

    try:
        while True:
            time.sleep(1)
            # Monitor health
            if not core.tor_mgr.is_running():
                print("\n[WARNING] Tor process terminated unexpectedly. Attempting restart...")
                time.sleep(2)
    except KeyboardInterrupt:
        shutdown_handler(None, None)

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="OnionHost - Self-hosted Tor Onion Website Hosting directly from your Windows computer.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  onionhost "C:\\MyWebsite"
  onionhost "C:\\MyWebsite" --port 8000
  onionhost --stop
  onionhost --status
  onionhost --list
  onionhost --open
  onionhost --dashboard
        """
    )

    parser.add_argument("folder", nargs="?", default=None, help="Path to the HTML website directory to host.")
    parser.add_argument("--port", "-p", type=int, default=None, help="Local HTTP server port (default: 8000).")
    parser.add_argument("--stop", action="store_true", help="Stop any active OnionHost services.")
    parser.add_argument("--status", action="store_true", help="Check current hosting and Tor status.")
    parser.add_argument("--list", "-l", action="store_true", help="List all configured websites.")
    parser.add_argument("--open", "-o", action="store_true", help="Open active onion site in Tor Browser or Dashboard.")
    parser.add_argument("--dashboard", "-d", action="store_true", help="Start the web dashboard UI.")

    args = parser.parse_args()

    if args.stop:
        return handle_stop()

    if args.status:
        return handle_status()

    if args.list:
        return handle_list()

    if args.open:
        return handle_open()

    if args.dashboard:
        from dashboard.app import start_dashboard
        start_dashboard()
        return 0

    if args.folder:
        return run_host_cli(args.folder, args.port)

    # If no arguments provided, show banner and help
    print_banner()
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
