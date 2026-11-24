"""
OnionHost Browser Dashboard Application.
Provides a modern, lightweight, developer-first management UI
strictly bound to 127.0.0.1.
"""

import os
import sys
import logging
import urllib.parse
from pathlib import Path
from flask import Flask, render_template, request, jsonify, abort

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.onionhost_core import OnionHostCore
from src.config_manager import ConfigManager
from src.security import is_safe_path

# Configure logging
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
APP_LOG_FILE = LOGS_DIR / "app.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(APP_LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("OnionHost.Dashboard")

app = Flask(
    __name__,
    template_folder=str(Path(__file__).parent / "templates"),
    static_folder=str(Path(__file__).parent / "static")
)
app.config["SECRET_KEY"] = os.urandom(24)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100MB max upload

core = OnionHostCore.get_instance()


# -------------------------------------------------------------
# Security Middleware: STRICT Localhost Enforcement
# -------------------------------------------------------------
@app.before_request
def restrict_to_localhost():
    client_ip = request.remote_addr
    # Permit only localhost IPv4 and IPv6 loopback
    if client_ip not in ["127.0.0.1", "::1", "localhost"]:
        logger.warning(f"Unauthorized external access attempt blocked from IP: {client_ip}")
        abort(403, "Access Denied: OnionHost Dashboard is strictly restricted to local host.")


# -------------------------------------------------------------
# HTML Views
# -------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


# -------------------------------------------------------------
# REST API Endpoints
# -------------------------------------------------------------
@app.route("/api/status", methods=["GET"])
def api_status():
    status = core.get_system_status()
    return jsonify({"success": True, "data": status})


@app.route("/api/sites", methods=["GET"])
def api_list_sites():
    status = core.get_system_status()
    return jsonify({"success": True, "sites": status["sites"]})


@app.route("/api/sites/host", methods=["POST"])
def api_host_site():
    data = request.get_json() or {}
    folder_path = data.get("folder_path", "").strip()
    port = data.get("port")
    if port:
        try:
            port = int(port)
        except ValueError:
            port = None

    if not folder_path:
        return jsonify({"success": False, "error": "Folder path is required."}), 400

    success, site_info, err = core.start_hosting(folder_path=folder_path, port=port)
    if not success:
        return jsonify({"success": False, "error": err}), 400

    return jsonify({"success": True, "site": site_info, "message": "Hosting started successfully."})


@app.route("/api/sites/<site_id>/stop", methods=["POST"])
def api_stop_site(site_id):
    core.stop_site(site_id)
    return jsonify({"success": True, "message": f"Site '{site_id}' stopped."})


@app.route("/api/sites/<site_id>/restart", methods=["POST"])
def api_restart_site(site_id):
    site = core.config.get_site(site_id)
    if not site:
        return jsonify({"success": False, "error": "Site not found."}), 404

    core.stop_site(site_id)
    if site.get("is_proxy") or str(site.get("path", "")).startswith(("http://", "https://")):
        success, site_info, err = core.start_hosting_proxy(
            site_id=site_id,
            name=site.get("name", site_id),
            target_url=site.get("target_url") or site.get("path"),
            port=site.get("local_port")
        )
    else:
        success, site_info, err = core.start_hosting(
            folder_path=site["path"],
            port=site.get("local_port")
        )
    if not success:
        return jsonify({"success": False, "error": err}), 400

    return jsonify({"success": True, "site": site_info, "message": "Site restarted successfully."})


@app.route("/api/sites/host_url", methods=["POST"])
def api_host_url():
    """
    Hosts an external website URL (e.g. https://www.csib.co.in)
    as a live Tor .onion mirror.
    """
    data = request.get_json() or {}
    url = data.get("url", "").strip()
    name = data.get("name", "").strip()
    port = data.get("port")
    if port:
        try:
            port = int(port)
        except ValueError:
            port = None

    if not url:
        return jsonify({"success": False, "error": "Target website URL is required."}), 400

    clean_url = url
    if not clean_url.startswith(("http://", "https://")):
        clean_url = "https://" + clean_url

    parsed = urllib.parse.urlparse(clean_url)
    site_name = name or parsed.netloc or "WebMirror"
    site_id = "".join(c if c.isalnum() else "_" for c in site_name.lower()).strip("_")
    if not site_id:
        site_id = "url_mirror"

    # Avoid clash with existing IDs if needed
    count = 1
    orig_id = site_id
    while core.config.get_site(site_id) is not None:
        site_id = f"{orig_id}_{count}"
        count += 1

    success, site_info, err = core.start_hosting_proxy(
        site_id=site_id,
        name=site_name,
        target_url=clean_url,
        port=port
    )
    if not success:
        return jsonify({"success": False, "error": err}), 400

    return jsonify({
        "success": True,
        "site": site_info,
        "full_onion_url": f"http://{site_info['onion_address']}",
        "message": f"Tor Onion Mirror online for {clean_url}!"
    })


@app.route("/api/stop_all", methods=["POST"])
def api_stop_all():
    core.stop_all()
    return jsonify({"success": True, "message": "All OnionHost services stopped."})


@app.route("/api/sites/<site_id>", methods=["DELETE"])
def api_delete_site(site_id):
    core.stop_site(site_id)
    removed = core.config.remove_site(site_id)
    if removed:
        return jsonify({"success": True, "message": f"Site '{site_id}' unregistered."})
    return jsonify({"success": False, "error": "Site not found."}), 404


@app.route("/api/sites/<site_id>/files", methods=["GET"])
def api_list_files(site_id):
    subpath = request.args.get("path", "")
    success, files, err = core.website_mgr.list_files(site_id, subpath)
    if not success:
        return jsonify({"success": False, "error": err}), 400
    return jsonify({"success": True, "files": files, "current_path": subpath})


@app.route("/api/sites/<site_id>/upload", methods=["POST"])
def api_upload_file(site_id):
    if "file" not in request.files:
        return jsonify({"success": False, "error": "No file part in request."}), 400

    f = request.files["file"]
    if not f or not f.filename:
        return jsonify({"success": False, "error": "Empty filename."}), 400

    subpath = request.form.get("path", "")
    success, msg = core.website_mgr.upload_file(site_id, subpath, f.filename, f.stream)
    if not success:
        return jsonify({"success": False, "error": msg}), 400
    return jsonify({"success": True, "message": msg})


@app.route("/api/sites/<site_id>/delete_file", methods=["POST"])
def api_delete_file(site_id):
    data = request.get_json() or {}
    rel_path = data.get("path", "").strip()
    if not rel_path:
        return jsonify({"success": False, "error": "Path is required."}), 400

    success, msg = core.website_mgr.delete_file(site_id, rel_path)
    if not success:
        return jsonify({"success": False, "error": msg}), 400
    return jsonify({"success": True, "message": msg})


@app.route("/api/sites/host_port", methods=["POST"])
def api_host_port():
    data = request.get_json() or {}
    service_name = data.get("name", "").strip() or "Local Service"
    port = data.get("port")
    subpath = data.get("subpath", "").strip()

    if not port:
        return jsonify({"success": False, "error": "Local port is required."}), 400

    try:
        port = int(port)
    except ValueError:
        return jsonify({"success": False, "error": "Invalid port number."}), 400

    site_id = "".join(c if c.isalnum() else "_" for c in service_name.lower()).strip("_") or f"port_{port}"
    count = 1
    orig_id = site_id
    while core.config.get_site(site_id) is not None:
        site_id = f"{orig_id}_{count}"
        count += 1

    clean_sub = subpath if (not subpath or subpath.startswith('/')) else '/' + subpath
    service_info = {
        "id": site_id,
        "name": service_name,
        "path": f"http://127.0.0.1:{port}{clean_sub}",
        "local_port": port,
        "onion_port": 80,
        "subpath": clean_sub,
        "is_proxy": True
    }

    core.config.register_or_update_site(
        site_id=site_id,
        name=service_name,
        folder_path=service_info["path"],
        local_port=port,
        onion_port=80
    )

    active_services = list(core.running_sites.values())
    active_services = [s for s in active_services if s["id"] != site_id]
    active_services.append(service_info)

    core.tor_mgr.start_tor(active_services, force_restart=True)
    bootstrapped = core.tor_mgr.wait_for_bootstrap(timeout=60)
    if not bootstrapped:
        return jsonify({"success": False, "error": "Tor bootstrap timed out while binding local port."}), 400

    onion_addr = core.tor_mgr.get_onion_address(site_id, timeout=20)
    if not onion_addr:
        return jsonify({"success": False, "error": "Failed to retrieve .onion address from Tor."}), 400

    service_info["onion_address"] = onion_addr
    service_info["status"] = "running"
    core.config.update_site_onion_address(site_id, onion_addr)
    core.config.update_site_status(site_id, "running")
    core.running_sites[site_id] = service_info
    core._record_runtime_state()

    full_onion_url = f"http://{onion_addr}{clean_sub}"

    return jsonify({
        "success": True,
        "site": service_info,
        "full_onion_url": full_onion_url,
        "message": f"Local server on port {port} is now live on Tor!"
    })


@app.route("/api/sites/create_new", methods=["POST"])
def api_create_new_site():
    data = request.get_json() or {}
    site_name = data.get("name", "").strip()
    custom_path = data.get("custom_path", "").strip()
    port = data.get("port")
    auto_start = data.get("auto_start", True)

    if not site_name:
        return jsonify({"success": False, "error": "Site name is required."}), 400

    success, folder_path, msg = core.website_mgr.create_new_website(site_name, custom_path or None)
    if not success:
        return jsonify({"success": False, "error": msg}), 400

    site_info = None
    if auto_start:
        ok, site_info, err = core.start_hosting(folder_path=folder_path, port=int(port) if port else None)
        if not ok:
            return jsonify({"success": False, "error": f"Folder created, but hosting failed: {err}"}), 400

    return jsonify({
        "success": True,
        "folder_path": folder_path,
        "site": site_info,
        "message": f"Website '{site_name}' created successfully!"
    })


@app.route("/api/sites/start_multiple", methods=["POST"])
def api_start_multiple():
    data = request.get_json() or {}
    sites_list = data.get("sites", [])
    if not sites_list or not isinstance(sites_list, list):
        return jsonify({"success": False, "error": "List of sites required."}), 400

    result = core.start_multiple_sites(sites_list)
    return jsonify(result)


@app.route("/api/sites/<site_id>/open_tor", methods=["POST"])
def api_open_tor_browser(site_id):
    site = core.config.get_site(site_id)
    if not site or not site.get("onion_address"):
        return jsonify({"success": False, "error": "Site not found or .onion address not generated yet."}), 404

    onion_url = f"http://{site['onion_address']}"
    tor_browser_exe = r"C:\Users\mohsin\Desktop\Sessions\Tor Browser\Browser\firefox.exe"
    import subprocess
    if Path(tor_browser_exe).exists():
        try:
            subprocess.Popen([tor_browser_exe, onion_url])
            return jsonify({"success": True, "message": f"Tor Browser opened for {onion_url}"})
        except Exception as e:
            return jsonify({"success": False, "error": f"Error launching Tor Browser: {str(e)}"}), 500
    else:
        import webbrowser
        webbrowser.open(onion_url)
        return jsonify({"success": True, "message": "Opened onion link in system browser."})


@app.route("/api/sites/<site_id>/mkdir", methods=["POST"])
def api_mkdir(site_id):
    data = request.get_json() or {}
    subpath = data.get("path", "")
    folder_name = data.get("folder_name", "").strip()

    if not folder_name:
        return jsonify({"success": False, "error": "Folder name is required."}), 400

    success, msg = core.website_mgr.create_subfolder(site_id, subpath, folder_name)
    if not success:
        return jsonify({"success": False, "error": msg}), 400
    return jsonify({"success": True, "message": msg})


@app.route("/api/sites/<site_id>/file_content", methods=["GET"])
def api_get_file_content(site_id):
    rel_path = request.args.get("path", "").strip()
    if not rel_path:
        return jsonify({"success": False, "error": "File path is required."}), 400

    success, content, err = core.website_mgr.read_file_content(site_id, rel_path)
    if not success:
        return jsonify({"success": False, "error": err}), 400

    return jsonify({"success": True, "content": content, "path": rel_path})


@app.route("/api/sites/<site_id>/save_file", methods=["POST"])
def api_save_file_content(site_id):
    data = request.get_json() or {}
    rel_path = data.get("path", "").strip()
    content = data.get("content", "")

    if not rel_path:
        return jsonify({"success": False, "error": "File path is required."}), 400

    success, msg = core.website_mgr.save_file_content(site_id, rel_path, content)
    if not success:
        return jsonify({"success": False, "error": msg}), 400

    return jsonify({"success": True, "message": msg})


@app.route("/api/stats", methods=["GET"])
def api_stats():
    system = core.get_system_status()
    total_reqs = 0
    total_bytes = 0
    all_recent = []

    for s in system["sites"]:
        stats = s.get("stats")
        if stats:
            total_reqs += stats.get("total_requests", 0)
            total_bytes += stats.get("total_bytes", 0)
            for req in stats.get("recent_requests", []):
                req_copy = dict(req)
                req_copy["site_name"] = s.get("name")
                all_recent.append(req_copy)

    # Sort recent requests descending by timestamp
    all_recent.sort(key=lambda r: r.get("timestamp", ""), reverse=True)

    def fmt_bytes(n):
        for unit in ['B', 'KB', 'MB', 'GB']:
            if abs(n) < 1024.0:
                return f"{n:3.1f} {unit}"
            n /= 1024.0
        return f"{n:.1f} TB"

    return jsonify({
        "success": True,
        "total_requests": total_reqs,
        "total_bytes": total_bytes,
        "total_bytes_formatted": fmt_bytes(total_bytes),
        "active_sites": system["active_sites_count"],
        "uptime_seconds": system["uptime_seconds"],
        "recent_requests": all_recent[:50]
    })


@app.route("/api/logs", methods=["GET"])
def api_logs():
    tor_logs = core.tor_mgr.get_recent_logs(100)
    app_logs = []
    if APP_LOG_FILE.exists():
        try:
            with open(APP_LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
                app_logs = [line.strip() for line in f.readlines()[-100:]]
        except Exception:
            pass

    return jsonify({
        "success": True,
        "tor_logs": tor_logs,
        "app_logs": app_logs
    })


@app.route("/api/logs/clear", methods=["POST"])
def api_clear_logs():
    try:
        if APP_LOG_FILE.exists():
            with open(APP_LOG_FILE, "w", encoding="utf-8") as f:
                f.write("")
        tor_log = BASE_DIR / "logs" / "tor.log"
        if tor_log.exists():
            with open(tor_log, "w", encoding="utf-8") as f:
                f.write("")
        return jsonify({"success": True, "message": "Logs cleared."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def start_dashboard(host="127.0.0.1", port=5000, debug=False):
    """Starts the Flask dashboard web server bound strictly to 127.0.0.1."""
    print("=" * 60)
    print("      ONIONHOST - LOCAL DASHBOARD")
    print("=" * 60)
    print(f"Dashboard URL: http://{host}:{port}")
    print("Access restricted exclusively to localhost (127.0.0.1)")
    print("Press CTRL+C to terminate dashboard.")
    print("=" * 60)
    app.run(host=host, port=port, debug=debug, use_reloader=False)


if __name__ == "__main__":
    start_dashboard()

