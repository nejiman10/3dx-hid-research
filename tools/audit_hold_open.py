#!/usr/bin/env python3
"""Run the wired C658 hold-open audit from a source checkout."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sdk" / "python" / "src"))

from threedx_report10.hold_open_audit import main


if __name__ == "__main__":
    raise SystemExit(main())
