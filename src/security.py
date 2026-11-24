"""
Security utilities for OnionHost.
Ensures path safety, prevents directory traversal, and validates inputs.
"""

import os
import re
from pathlib import Path


def is_safe_path(base_dir: str, target_path: str) -> bool:
    """
    Validates that target_path is strictly within base_dir.
    Resolves relative paths, symlinks, and directory traversal attempts.
    """
    try:
        base = Path(base_dir).resolve()
        target = Path(target_path).resolve()
        
        # Check if target is equal to base or a subpath of base
        # On Windows, drive letters and case must be accounted for
        if base == target:
            return True
        return base in target.parents
    except Exception:
        return False


def sanitize_filename(filename: str) -> str:
    """
    Sanitizes a user-supplied filename to prevent directory traversal
    and illegal characters on Windows/Linux filesystems.
    """
    # Remove any directory parts
    clean_name = os.path.basename(filename)
    # Remove null bytes
    clean_name = clean_name.replace("\x00", "")
    # Remove path traversal tokens
    clean_name = re.sub(r"\.\.+", ".", clean_name)
    # Allow alphanumeric, dashes, underscores, and dots
    clean_name = re.sub(r'[^a-zA-Z0-9_\-\.\ ]', '', clean_name).strip()
    
    if not clean_name:
        clean_name = "unnamed_file"
    return clean_name


def validate_website_directory(folder_path: str) -> tuple[bool, str]:
    """
    Validates that a folder exists and is a directory.
    Returns (is_valid, message).
    """
    if not folder_path:
        return False, "Website directory path cannot be empty."
    
    path = Path(folder_path)
    if not path.exists():
        return False, f"Directory does not exist: {folder_path}"
    
    if not path.is_dir():
        return False, f"Path is not a directory: {folder_path}"
    
    return True, "Valid directory."

