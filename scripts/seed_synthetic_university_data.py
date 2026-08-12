#!/usr/bin/env python3
"""V30 CLI wrapper for the reusable synthetic data seeder.

Use `python -m app.synthetic_seed` inside the backend container whenever possible.
This wrapper keeps the documented script command compatible with Windows, macOS,
and Linux while avoiding import-path ambiguity.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.synthetic_seed import main

if __name__ == "__main__":
    raise SystemExit(main())
