"""
Website Content and File Management for OnionHost.
Manages browsing website directories, file uploads, safe deletions,
and default template scaffolding.
"""

import os
import shutil
import logging
from pathlib import Path
from typing import List, Dict, Optional, Any

from src.security import is_safe_path, sanitize_filename, validate_website_directory

logger = logging.getLogger("OnionHost.Website")


class WebsiteManager:
    def __init__(self, config_manager):
        self.config = config_manager

    def validate_folder(self, folder_path: str) -> tuple[bool, str]:
        return validate_website_directory(folder_path)

    def list_files(self, site_id: str, subpath: str = "") -> tuple[bool, Any, str]:
        """
        Lists files and directories inside a website folder.
        Safely enforces that subpath stays inside the website root.
        Returns (success, files_data, error_message).
        """
        site = self.config.get_site(site_id)
        if not site:
            return False, [], f"Site '{site_id}' not found."

        site_root = Path(site["path"]).resolve()
        target_dir = (site_root / subpath.lstrip("/\\")).resolve()

        if not is_safe_path(str(site_root), str(target_dir)):
            return False, [], "Access denied: Path traversal outside website root detected."

        if not target_dir.exists():
            return False, [], "Requested directory does not exist."

        if not target_dir.is_dir():
            return False, [], "Requested path is a file, not a directory."

        results = []
        try:
            for entry in sorted(os.scandir(target_dir), key=lambda e: (not e.is_dir(), e.name.lower())):
                # Skip hidden files
                if entry.name.startswith("."):
                    continue
                try:
                    stat = entry.stat()
                    rel_path = str(Path(entry.path).relative_to(site_root)).replace("\\", "/")
                    results.append({
                        "name": entry.name,
                        "path": rel_path,
                        "is_dir": entry.is_dir(),
                        "size": stat.st_size if not entry.is_dir() else 0,
                        "size_formatted": self._format_size(stat.st_size) if not entry.is_dir() else "--",
                        "modified": int(stat.st_mtime)
                    })
                except Exception as e:
                    logger.debug(f"Error reading file entry {entry.name}: {e}")
            return True, results, ""
        except Exception as e:
            logger.error(f"Error scanning directory {target_dir}: {e}")
            return False, [], str(e)

    def upload_file(self, site_id: str, subpath: str, filename: str, file_stream) -> tuple[bool, str]:
        """
        Safely saves an uploaded file stream into a website's folder.
        Sanitizes the filename and verifies destination directory.
        """
        site = self.config.get_site(site_id)
        if not site:
            return False, f"Site '{site_id}' not found."

        site_root = Path(site["path"]).resolve()
        target_dir = (site_root / subpath.lstrip("/\\")).resolve()

        if not is_safe_path(str(site_root), str(target_dir)):
            return False, "Access denied: Destination outside website folder."

        target_dir.mkdir(parents=True, exist_ok=True)

        safe_name = sanitize_filename(filename)
        dest_file = (target_dir / safe_name).resolve()

        if not is_safe_path(str(site_root), str(dest_file)):
            return False, "Access denied: File destination traversal blocked."

        try:
            with open(dest_file, "wb") as f:
                shutil.copyfileobj(file_stream, f)
            logger.info(f"File uploaded safely: {dest_file}")
            return True, f"File '{safe_name}' uploaded successfully."
        except Exception as e:
            logger.error(f"Upload failed: {e}")
            return False, f"Error saving file: {str(e)}"

    def delete_file(self, site_id: str, relative_file_path: str) -> tuple[bool, str]:
        """
        Safely deletes a file within the website root.
        """
        site = self.config.get_site(site_id)
        if not site:
            return False, f"Site '{site_id}' not found."

        site_root = Path(site["path"]).resolve()
        target_file = (site_root / relative_file_path.lstrip("/\\")).resolve()

        if not is_safe_path(str(site_root), str(target_file)):
            return False, "Access denied: Cannot delete file outside website root."

        if not target_file.exists():
            return False, "File does not exist."

        try:
            if target_file.is_dir():
                shutil.rmtree(target_file)
            else:
                target_file.unlink()
            logger.info(f"Deleted: {target_file}")
            return True, "Item deleted successfully."
        except Exception as e:
            logger.error(f"Error deleting file {target_file}: {e}")
            return False, f"Failed to delete item: {str(e)}"

    def create_subfolder(self, site_id: str, subpath: str, folder_name: str) -> tuple[bool, str]:
        """Safely creates a new subdirectory inside a website folder."""
        site = self.config.get_site(site_id)
        if not site:
            return False, f"Site '{site_id}' not found."

        site_root = Path(site["path"]).resolve()
        target_parent = (site_root / subpath.lstrip("/\\")).resolve()

        if not is_safe_path(str(site_root), str(target_parent)):
            return False, "Access denied: Target parent outside website folder."

        clean_folder = sanitize_filename(folder_name)
        new_dir = (target_parent / clean_folder).resolve()

        if not is_safe_path(str(site_root), str(new_dir)):
            return False, "Access denied: Traversal blocked."

        try:
            new_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created subfolder: {new_dir}")
            return True, f"Folder '{clean_folder}' created successfully."
        except Exception as e:
            return False, f"Failed to create folder: {str(e)}"

    def read_file_content(self, site_id: str, relative_path: str) -> tuple[bool, str, str]:
        """Reads text content of a file for the in-dashboard code editor."""
        site = self.config.get_site(site_id)
        if not site:
            return False, "", f"Site '{site_id}' not found."

        site_root = Path(site["path"]).resolve()
        target_file = (site_root / relative_path.lstrip("/\\")).resolve()

        if not is_safe_path(str(site_root), str(target_file)):
            return False, "", "Access denied: Path traversal outside website root."

        if not target_file.exists() or not target_file.is_file():
            return False, "", "File not found or is a directory."

        # Limit to 5MB for text editing
        if target_file.stat().st_size > 5 * 1024 * 1024:
            return False, "", "File too large to edit in browser (max 5MB)."

        try:
            with open(target_file, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            return True, content, ""
        except Exception as e:
            return False, "", f"Error reading file: {str(e)}"

    def save_file_content(self, site_id: str, relative_path: str, content: str) -> tuple[bool, str]:
        """Saves edited text content back to a file."""
        site = self.config.get_site(site_id)
        if not site:
            return False, f"Site '{site_id}' not found."

        site_root = Path(site["path"]).resolve()
        target_file = (site_root / relative_path.lstrip("/\\")).resolve()

        if not is_safe_path(str(site_root), str(target_file)):
            return False, "Access denied: Path traversal outside website root."

        try:
            target_file.parent.mkdir(parents=True, exist_ok=True)
            with open(target_file, "w", encoding="utf-8") as f:
                f.write(content)
            logger.info(f"Saved file content: {target_file}")
            return True, "File saved successfully."
        except Exception as e:
            return False, f"Error saving file: {str(e)}"

    def create_new_website(self, site_name: str, custom_path: Optional[str] = None) -> tuple[bool, str, str]:
        """Creates a brand new website directory with starter boilerplate."""
        clean_name = sanitize_filename(site_name)
        if not clean_name:
            clean_name = "new_site"

        if custom_path and custom_path.strip():
            folder_path = Path(custom_path.strip()).resolve()
        else:
            base_sites = self.config.settings.get("sites_dir")
            if not base_sites:
                base_sites = str((Path(__file__).resolve().parent.parent / "hosted_sites").resolve())
            folder_path = Path(base_sites) / clean_name

        try:
            folder_path.mkdir(parents=True, exist_ok=True)
            self.create_sample_website_if_needed(str(folder_path))
            return True, str(folder_path), f"Website folder ready at: {folder_path}"
        except Exception as e:
            return False, "", f"Failed to create website folder: {str(e)}"

    @staticmethod
    def create_sample_website_if_needed(target_dir: str):
        """Scaffolds a professional sample website if target directory has no index.html."""
        p = Path(target_dir)
        p.mkdir(parents=True, exist_ok=True)
        index_file = p / "index.html"
        style_file = p / "style.css"
        script_file = p / "script.js"

        if not index_file.exists():
            index_html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ONIONHOST IS WORKING!</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <div class="container">
        <div class="badge">SECURE ONION SERVICE</div>
        <h1 class="hero-title">ONIONHOST IS WORKING!</h1>
        <p class="hero-subtitle">
            This website is hosted directly from a local Windows computer over the Tor network.
        </p>

        <div class="card-grid">
            <div class="card">
                <div class="card-icon">&#127760;</div>
                <h3>Zero Port-Forwarding</h3>
                <p>Traversing NAT and firewalls seamlessly via Tor v3 end-to-end encrypted onion circuits.</p>
            </div>
            <div class="card">
                <div class="card-icon">&#128274;</div>
                <h3>Private &amp; Decentralized</h3>
                <p>No paid hosting, no VPS, no public IP leaks, and no domain renewal fees.</p>
            </div>
            <div class="card">
                <div class="card-icon">&#9889;</div>
                <h3>Self-Hosted Control</h3>
                <p>Static files served from your Windows workstation with full file and log management.</p>
            </div>
        </div>

        <div class="status-panel">
            <div class="status-indicator">
                <span class="dot"></span>
                <strong>Status:</strong> <span class="status-text">Online &amp; Serving Requests</span>
            </div>
            <div class="timestamp" id="timestamp"></div>
        </div>

        <footer>
            Powered by <strong>OnionHost</strong> &bull; Anonymous, Local-First Tor Hosting
        </footer>
    </div>
    <script src="script.js"></script>
</body>
</html>
"""
            with open(index_file, "w", encoding="utf-8") as f:
                f.write(index_html)

        if not style_file.exists():
            css = """* {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background: #f8fafc;
    color: #0f172a;
    display: flex;
    justify-content: center;
    align-items: center;
    min-height: 100vh;
    padding: 24px;
}
.container {
    max-width: 800px;
    width: 100%;
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 16px;
    padding: 48px;
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.04);
    text-align: center;
}
.badge {
    display: inline-block;
    padding: 6px 14px;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.05em;
    color: #4f46e5;
    background: #eef2ff;
    border-radius: 9999px;
    margin-bottom: 20px;
    text-transform: uppercase;
}
.hero-title {
    font-size: 36px;
    font-weight: 800;
    color: #1e1b4b;
    margin-bottom: 12px;
    letter-spacing: -0.02em;
}
.hero-subtitle {
    font-size: 17px;
    color: #64748b;
    line-height: 1.6;
    margin-bottom: 36px;
}
.card-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
    gap: 20px;
    margin-bottom: 36px;
    text-align: left;
}
.card {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 24px;
}
.card-icon {
    font-size: 28px;
    margin-bottom: 12px;
}
.card h3 {
    font-size: 16px;
    font-weight: 700;
    color: #1e293b;
    margin-bottom: 8px;
}
.card p {
    font-size: 14px;
    color: #64748b;
    line-height: 1.5;
}
.status-panel {
    background: #f1f5f9;
    border-radius: 10px;
    padding: 16px 20px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 14px;
    margin-bottom: 28px;
}
.status-indicator {
    display: flex;
    align-items: center;
    gap: 8px;
}
.dot {
    width: 10px;
    height: 10px;
    background: #10b981;
    border-radius: 50%;
    display: inline-block;
    box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.2);
    animation: pulse 2s infinite;
}
@keyframes pulse {
    0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.5); }
    70% { transform: scale(1); box-shadow: 0 0 0 6px rgba(16, 185, 129, 0); }
    100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
}
footer {
    font-size: 13px;
    color: #94a3b8;
}
footer strong {
    color: #475569;
}
"""
            with open(style_file, "w", encoding="utf-8") as f:
                f.write(css)

        if not script_file.exists():
            js = """document.addEventListener('DOMContentLoaded', () => {
    const timeElem = document.getElementById('timestamp');
    if (timeElem) {
        const updateTime = () => {
            const now = new Date();
            timeElem.textContent = 'Server Time: ' + now.toLocaleTimeString() + ' UTC ' + (now.getTimezoneOffset() / -60 >= 0 ? '+' : '') + (now.getTimezoneOffset() / -60);
        };
        updateTime();
        setInterval(updateTime, 1000);
    }
    console.log("OnionHost sample website loaded successfully.");
});
"""
            with open(script_file, "w", encoding="utf-8") as f:
                f.write(js)

    @staticmethod
    def _format_size(num_bytes: int) -> str:
        for unit in ['B', 'KB', 'MB', 'GB']:
            if abs(num_bytes) < 1024.0:
                return f"{num_bytes:3.1f} {unit}"
            num_bytes /= 1024.0
        return f"{num_bytes:.1f} TB"

