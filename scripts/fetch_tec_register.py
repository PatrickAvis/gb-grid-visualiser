#!/usr/bin/env python3
"""Download the NESO TEC (Transmission Entry Capacity) Register CSV."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tec_register import TEC_REGISTER_PATH, fetch_tec_register


def main() -> int:
    frame = fetch_tec_register()
    print(f"Saved {len(frame):,} TEC rows to {TEC_REGISTER_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
