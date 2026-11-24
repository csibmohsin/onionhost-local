"""
Local HTTP Server Manager for OnionHost.
Provides secure, localhost-only static web servers for hosted folders.
Includes path traversal protection, MIME handling, and traffic statistics.
"""

import os
import sys
import time
import socket
import logging
import mimetypes
import shutil
import subprocess
import urllib.request
import urllib.error
import urllib.parse
import ssl
from pathlib import Path
from collections import deque
from typing import Dict, Optional, List, Any
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import threading

from src.security import is_safe_path

logger = logging.getLogger("OnionHost.Server")

# Extra MIME types for modern web assets
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("font/woff", ".woff")
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("font/ttf", ".ttf")
mimetypes.add_type("font/otf", ".otf")
mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("video/mp4", ".mp4")
mimetypes.add_type("video/webm", ".webm")


class SiteStats:
    """Thread-safe statistics tracker for a hosted website."""
    def __init__(self, max_recent: int = 100):
        self.lock = threading.Lock()
        self.start_time = time.time()
        self.total_requests = 0
        self.total_bytes = 0
        self.recent_requests = deque(maxlen=max_recent)

    def record_request(self, method: str, path: str, status_code: int, size: int, client_ip: str):
        with self.lock:
            self.total_requests += 1
            self.total_bytes += size
            self.recent_requests.appendleft({
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "method": method,
                "path": path,
                "status": status_code,
                "size": size,
                "client": client_ip
            })

    def get_summary(self) -> Dict[str, Any]:
        with self.lock:
            uptime_seconds = int(time.time() - self.start_time)
            return {
                "uptime_seconds": uptime_seconds,
                "uptime_formatted": self._format_uptime(uptime_seconds),
                "total_requests": self.total_requests,
                "total_bytes": self.total_bytes,
                "total_bytes_formatted": self._format_bytes(self.total_bytes),
                "recent_requests": list(self.recent_requests)
            }

    @staticmethod
    def _format_uptime(seconds: int) -> str:
        d = seconds // 86400
        h = (seconds % 86400) // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        if d > 0:
            return f"{d}d {h}h {m}m {s}s"
        if h > 0:
            return f"{h}h {m}m {s}s"
        if m > 0:
            return f"{m}m {s}s"
        return f"{s}s"

    @staticmethod
    def _format_bytes(num_bytes: int) -> str:
        for unit in ['B', 'KB', 'MB', 'GB']:
            if abs(num_bytes) < 1024.0:
                return f"{num_bytes:3.1f} {unit}"
            num_bytes /= 1024.0
        return f"{num_bytes:.1f} TB"


def make_onionhost_handler(website_dir: str, stats: SiteStats):
    """
    Factory creating a secure SimpleHTTPRequestHandler subclass bound
    strictly to the given website directory and tracking statistics.
    """
    resolved_root = str(Path(website_dir).resolve())

    class OnionHostHTTPHandler(SimpleHTTPRequestHandler):
        server_version = "OnionHost/1.0"
        sys_version = ""

        def __init__(self, *args, **kwargs):
            # Pass directory explicitly
            super().__init__(*args, directory=resolved_root, **kwargs)

        def log_message(self, format_str, *args):
            # Route HTTP server log to OnionHost logger
            msg = "%s - - [%s] %s" % (
                self.client_address[0],
                self.log_date_time_string(),
                format_str % args
            )
            logger.info(msg)

        def translate_path(self, path):
            """
            Secure path translation ensuring zero directory traversal.
            Rejects access to hidden files and ensures destination path
            is strictly within resolved_root.
            """
            # Use base translate_path to get candidate path
            candidate_path = super().translate_path(path)
            candidate_resolved = Path(candidate_path).resolve()

            # Ensure candidate is inside resolved_root
            if not is_safe_path(resolved_root, str(candidate_resolved)):
                logger.warning(f"Forbidden path traversal attempt blocked: {path}")
                return None

            # Disallow hidden files/directories (e.g. .git, .env)
            parts = candidate_resolved.relative_to(resolved_root).parts
            for part in parts:
                if part.startswith(".") and part not in [".", ".."]:
                    logger.warning(f"Access to hidden resource blocked: {path}")
                    return None

            return str(candidate_resolved)

        def send_error(self, code, message=None, explain=None):
            stats.record_request(self.command, self.path, code, 0, self.client_address[0])
            super().send_error(code, message, explain)

        def send_response(self, code, message=None):
            self.last_status = code
            super().send_response(code, message)

        def end_headers(self):
            # Security headers
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "SAMEORIGIN")
            self.send_header("X-XSS-Protection", "1; mode=block")
            super().end_headers()

        def copyfile(self, source, outputfile):
            """Override to count bytes transferred for stats."""
            length = 0
            buf_size = 64 * 1024
            while True:
                buf = source.read(buf_size)
                if not buf:
                    break
                outputfile.write(buf)
                length += len(buf)
            status = getattr(self, "last_status", 200)
            stats.record_request(self.command, self.path, status, length, self.client_address[0])

        def do_GET(self):
            path_translated = self.translate_path(self.path)
            if path_translated is None:
                self.send_error(HTTPStatus.FORBIDDEN, "Access Denied")
                return
            super().do_GET()

        def do_HEAD(self):
            path_translated = self.translate_path(self.path)
            if path_translated is None:
                self.send_error(HTTPStatus.FORBIDDEN, "Access Denied")
                return
            super().do_HEAD()

    return OnionHostHTTPHandler


def make_onionhost_proxy_handler(target_base_url: str, stats: SiteStats):
    """
    Factory creating a reverse-proxy HTTP handler that forwards requests
    from Tor to an external live website (e.g. https://www.csib.co.in)
    and streams responses back, acting as a live Tor Onion Mirror.
    Handles transparent decompression, link rewriting, and modern browser headers.
    """
    import requests
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    parsed_base = urllib.parse.urlparse(target_base_url)
    base_host = parsed_base.netloc
    clean_base = target_base_url.rstrip("/")

    # Compute URL variants for link rewriting
    if "://" in clean_base:
        _, no_proto = clean_base.split("://", 1)
    else:
        no_proto = clean_base
    clean_no_proto = no_proto.rstrip("/")
    no_www = clean_no_proto.replace("www.", "")

    variants_slash = [
        f"https://{clean_no_proto}/",
        f"http://{clean_no_proto}/",
        f"//{clean_no_proto}/",
        f"https://{no_www}/",
        f"http://{no_www}/",
        f"//{no_www}/",
    ]
    variants_plain = [
        f"https://{clean_no_proto}",
        f"http://{clean_no_proto}",
        f"//{clean_no_proto}",
        f"https://{no_www}",
        f"http://{no_www}",
        f"//{no_www}",
    ]

    # Shared persistent session with keep-alive
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(max_retries=2, pool_connections=10, pool_maxsize=20)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    class OnionHostProxyHandler(SimpleHTTPRequestHandler):
        server_version = "OnionHost-Proxy/2.0"
        sys_version = ""

        def log_message(self, format_str, *args):
            logger.info(f"[Proxy] {self.client_address[0]} - {format_str % args}")

        def _handle_proxy(self):
            path = self.path
            if not path.startswith("/"):
                path = "/" + path
            target_url = clean_base + path
            method = self.command

            # Upstream headers simulating a modern Tor / Firefox browser
            req_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/115.0",
                "Accept": "*/*",
                "Host": base_host,
                "Referer": clean_base + "/",
            }
            # Forward relevant client headers
            for h in ["Cookie", "Content-Type", "Authorization", "Accept-Language"]:
                val = self.headers.get(h)
                if val:
                    req_headers[h] = val

            # Read request body if present
            body = None
            if method in ["POST", "PUT", "PATCH"]:
                content_len = int(self.headers.get("Content-Length", 0))
                if content_len > 0:
                    body = self.rfile.read(content_len)

            try:
                # requests automatically decompresses gzip, deflate, and br into .content
                try:
                    upstream_resp = session.request(
                        method=method,
                        url=target_url,
                        data=body,
                        headers=req_headers,
                        allow_redirects=True,
                        timeout=(8, 25),
                        verify=False,
                        stream=False,
                    )
                except (requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError):
                    # If HTTPS connection failed or timed out, attempt plain HTTP fallback
                    if target_url.startswith("https://"):
                        fallback_url = "http://" + target_url[8:]
                        upstream_resp = session.request(
                            method=method,
                            url=fallback_url,
                            data=body,
                            headers=req_headers,
                            allow_redirects=True,
                            timeout=(8, 25),
                            verify=False,
                            stream=False,
                        )
                    else:
                        raise

                status_code = upstream_resp.status_code
                resp_data = upstream_resp.content  # Guaranteed uncompressed bytes!
                content_type = upstream_resp.headers.get("Content-Type", "")

                # If text/html or text/css, rewrite absolute upstream domain links to relative roots
                ct_lower = content_type.lower()
                if "text/html" in ct_lower or "text/css" in ct_lower:
                    try:
                        encoding = upstream_resp.encoding or "utf-8"
                        text = resp_data.decode(encoding, errors="replace")
                        for var in variants_slash:
                            text = text.replace(var, "/")
                        for var in variants_plain:
                            text = text.replace(var, "/")
                        resp_data = text.encode("utf-8")
                        # Ensure charset is utf-8
                        if "charset=" in content_type:
                            import re
                            content_type = re.sub(r'charset=[^\s;]+', 'charset=utf-8', content_type)
                        else:
                            content_type = f"{content_type}; charset=utf-8"
                    except Exception as e:
                        logger.warning(f"Link rewrite warning for {target_url}: {e}")

                self.send_response(status_code)

                # Skip hop-by-hop and restrictive headers
                # Crucial: content-encoding must be stripped because resp_data is uncompressed!
                skip_headers = {
                    "transfer-encoding",
                    "connection",
                    "content-length",
                    "content-encoding",
                    "content-security-policy",
                    "strict-transport-security",
                    "x-frame-options",
                }

                for k, v in upstream_resp.headers.items():
                    if k.lower() not in skip_headers:
                        if k.lower() == "content-type":
                            self.send_header("Content-Type", content_type)
                        elif k.lower() == "location":
                            loc = v
                            for var in variants_slash:
                                loc = loc.replace(var, "/")
                            for var in variants_plain:
                                loc = loc.replace(var, "/")
                            self.send_header("Location", loc or "/")
                        else:
                            self.send_header(k, v)

                # Send exact uncompressed length
                self.send_header("Content-Length", str(len(resp_data)))
                self.send_header("X-Proxy-By", "OnionHost-C2")
                self.end_headers()

                if method != "HEAD":
                    self.wfile.write(resp_data)

                stats.record_request(method, self.path, status_code, len(resp_data), self.client_address[0])

            except requests.exceptions.RequestException as e:
                logger.error(f"Proxy upstream error for {target_url}: {e}")
                err_msg = f"OnionHost Proxy Mirror Error connecting to {clean_base}: {e}".encode("utf-8")
                self.send_response(502)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(err_msg)))
                self.end_headers()
                if method != "HEAD":
                    self.wfile.write(err_msg)
                stats.record_request(method, self.path, 502, len(err_msg), self.client_address[0])
            except Exception as e:
                logger.error(f"Proxy internal error for {target_url}: {e}")
                err_msg = f"OnionHost Proxy Internal Error: {e}".encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(err_msg)))
                self.end_headers()
                if method != "HEAD":
                    self.wfile.write(err_msg)
                stats.record_request(method, self.path, 500, len(err_msg), self.client_address[0])

        def do_GET(self):
            self._handle_proxy()

        def do_POST(self):
            self._handle_proxy()

        def do_HEAD(self):
            self._handle_proxy()

        def do_OPTIONS(self):
            self._handle_proxy()

        def do_PUT(self):
            self._handle_proxy()

        def do_DELETE(self):
            self._handle_proxy()

    return OnionHostProxyHandler

    return OnionHostProxyHandler


class ProxyServerInstance:
    """Represents a running local reverse proxy server that mirrors an external website for an onion service."""
    def __init__(self, site_id: str, target_url: str, port: int, host: str = "127.0.0.1"):
        self.site_id = site_id
        self.target_url = target_url
        self.port = port
        self.host = host
        self.stats = SiteStats()
        self.server: Optional[ThreadingHTTPServer] = None
        self.thread: Optional[threading.Thread] = None
        self.is_running = False

    def start(self) -> bool:
        if self.is_running:
            return True
        handler_cls = make_onionhost_proxy_handler(self.target_url, self.stats)
        try:
            self.server = ThreadingHTTPServer((self.host, self.port), handler_cls)
            self.server.daemon_threads = True
            self.is_running = True
            self.thread = threading.Thread(target=self._run_server, daemon=True, name=f"ProxyServer-{self.site_id}")
            self.thread.start()
            logger.info(f"Local Reverse Proxy for site '{self.site_id}' started on {self.host}:{self.port} mirroring {self.target_url}")
            return True
        except Exception as e:
            logger.error(f"Failed to start proxy server on {self.host}:{self.port}: {e}")
            self.is_running = False
            return False

    def _run_server(self):
        try:
            if self.server:
                self.server.serve_forever()
        except Exception as e:
            logger.error(f"Proxy server error for '{self.site_id}': {e}")
        finally:
            self.is_running = False

    def stop(self):
        if not self.is_running:
            return
        if self.server:
            try:
                self.server.shutdown()
                self.server.server_close()
            except Exception as e:
                logger.warning(f"Error shutting down proxy server for '{self.site_id}': {e}")
            self.server = None
        self.is_running = False


class LocalServerInstance:
    """Represents a running local HTTP server for one site."""
    def __init__(self, site_id: str, directory: str, port: int, host: str = "127.0.0.1"):
        self.site_id = site_id
        self.directory = str(Path(directory).resolve())
        self.port = port
        self.host = host
        self.stats = SiteStats()
        self.server: Optional[ThreadingHTTPServer] = None
        self.thread: Optional[threading.Thread] = None
        self.php_process: Optional[subprocess.Popen] = None
        self.is_running = False
        self.is_php = self._detect_php()

    def _detect_php(self) -> bool:
        try:
            p = Path(self.directory)
            return any(p.glob("*.php"))
        except Exception:
            return False

    def _find_php_binary(self) -> Optional[str]:
        candidates = [
            r"D:\xampp\php\php.exe",
            r"C:\xampp\php\php.exe",
            shutil.which("php.exe") or shutil.which("php")
        ]
        for c in candidates:
            if c and Path(c).is_file():
                return str(Path(c).resolve())
        return None

    def start(self) -> bool:
        """Starts the HTTP or PHP server on a dedicated background thread/process."""
        if self.is_running:
            return True

        # If site contains PHP files and PHP is available, run PHP built-in server
        if self.is_php:
            php_exe = self._find_php_binary()
            if php_exe:
                try:
                    logger.info(f"PHP detected for site '{self.site_id}'. Starting PHP server with {php_exe}...")
                    cmd = [php_exe, "-S", f"{self.host}:{self.port}", "-t", self.directory]
                    self.php_process = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                    )
                    self.is_running = True
                    logger.info(f"PHP Server for site '{self.site_id}' started at http://{self.host}:{self.port} serving {self.directory}")
                    return True
                except Exception as e:
                    logger.warning(f"Could not start PHP server for '{self.site_id}': {e}. Falling back to Python HTTP server.")

        handler_cls = make_onionhost_handler(self.directory, self.stats)
        try:
            self.server = ThreadingHTTPServer((self.host, self.port), handler_cls)
            self.server.daemon_threads = True
            self.is_running = True
            self.thread = threading.Thread(target=self._run_server, daemon=True, name=f"HttpServer-{self.site_id}")
            self.thread.start()
            logger.info(f"Local HTTP server for site '{self.site_id}' started at http://{self.host}:{self.port} serving {self.directory}")
            return True
        except Exception as e:
            logger.error(f"Failed to start HTTP server on {self.host}:{self.port}: {e}")
            self.is_running = False
            return False

    def _run_server(self):
        try:
            if self.server:
                self.server.serve_forever()
        except Exception as e:
            logger.error(f"HTTP Server error for '{self.site_id}': {e}")
        finally:
            self.is_running = False

    def stop(self):
        """Stops the HTTP or PHP server."""
        if not self.is_running:
            return

        if self.php_process:
            logger.info(f"Stopping PHP server for site '{self.site_id}' on port {self.port}...")
            try:
                self.php_process.terminate()
                self.php_process.kill()
            except Exception:
                pass
            self.php_process = None

        if self.server:
            logger.info(f"Stopping HTTP server for site '{self.site_id}' on port {self.port}...")
            try:
                self.server.shutdown()
                self.server.server_close()
            except Exception as e:
                logger.warning(f"Error shutting down server for '{self.site_id}': {e}")
            self.server = None

        self.is_running = False


class ServerManager:
    """Manages one or more local HTTP server instances."""
    def __init__(self):
        self.servers: Dict[str, LocalServerInstance] = {}
        self._lock = threading.Lock()

    @staticmethod
    def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
        """Checks if a local TCP port is already occupied."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            try:
                s.bind((host, port))
                return False
            except socket.error:
                return True

    def find_available_port(self, start_port: int = 8000, host: str = "127.0.0.1") -> int:
        """Finds the next available local port starting from start_port."""
        port = start_port
        while port < 65535:
            if not self.is_port_in_use(port, host):
                return port
            port += 1
        raise RuntimeError("No available TCP port found in range 8000-65535.")

    def start_site_server(self, site_id: str, directory: str, port: int) -> tuple[bool, int, str]:
        """
        Starts local server for a site.
        Returns (success, actual_port, error_message).
        """
        with self._lock:
            # If already running, return
            existing = self.servers.get(site_id)
            if existing and existing.is_running:
                return True, existing.port, ""

            # Check port availability
            if self.is_port_in_use(port):
                # Try finding another port if requested port is taken
                new_port = self.find_available_port(port + 1)
                logger.warning(f"Port {port} in use; switched to available port {new_port}")
                port = new_port

            instance = LocalServerInstance(site_id, directory, port)
            success = instance.start()
            if success:
                self.servers[site_id] = instance
                return True, port, ""
            else:
                return False, port, f"Could not bind to 127.0.0.1:{port}"

    def start_site_proxy(self, site_id: str, target_url: str, port: int) -> tuple[bool, int, str]:
        """
        Starts local reverse proxy server mirroring target_url.
        Returns (success, actual_port, error_message).
        """
        with self._lock:
            existing = self.servers.get(site_id)
            if existing and existing.is_running:
                return True, existing.port, ""

            if self.is_port_in_use(port):
                new_port = self.find_available_port(port + 1)
                logger.warning(f"Port {port} in use; switched to available port {new_port}")
                port = new_port

            instance = ProxyServerInstance(site_id, target_url, port)
            success = instance.start()
            if success:
                self.servers[site_id] = instance
                return True, port, ""
            else:
                return False, port, f"Could not bind to 127.0.0.1:{port}"

    def stop_site_server(self, site_id: str):
        """Stops the local server for a specific site."""
        with self._lock:
            instance = self.servers.get(site_id)
            if instance:
                instance.stop()
                del self.servers[site_id]

    def stop_all(self):
        """Stops all running local HTTP servers."""
        with self._lock:
            for site_id, instance in list(self.servers.items()):
                instance.stop()
            self.servers.clear()

    def get_site_stats(self, site_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves stats summary for a site."""
        instance = self.servers.get(site_id)
        if instance:
            return instance.stats.get_summary()
        return None

    def is_site_running(self, site_id: str) -> bool:
        instance = self.servers.get(site_id)
        return bool(instance and instance.is_running)

