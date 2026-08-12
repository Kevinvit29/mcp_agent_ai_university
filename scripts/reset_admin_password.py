#!/usr/bin/env python3
"""V30 compatibility wrapper for safe local administrator recovery."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.admin_recovery import main

if __name__ == "__main__":
    # Retain the old command line but delegate to the tested module path.
    raise SystemExit(main(["--reset-password", "--confirm-local-recovery", *sys.argv[1:]]))
