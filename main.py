"""
OnionHost Main Entrypoint.
Starts either the CLI or Web Dashboard depending on arguments.
"""

import sys
from pathlib import Path

# Ensure project root in sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from onionhost import main

if __name__ == "__main__":
    sys.exit(main())

