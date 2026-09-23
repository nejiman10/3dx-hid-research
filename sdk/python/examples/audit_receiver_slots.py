#!/usr/bin/env python3
"""Read-only C652 GET_FEATURE 0x43..0x47 audit."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from threedx_report10 import read_receiver_slots


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit C652 receiver slots 0..4")
    parser.add_argument("--device", required=True, help="validated C652 management hidraw")
    parser.add_argument("--audit", required=True, help="output JSON path")
    args = parser.parse_args()
    slots = read_receiver_slots(args.device)
    document = {
        "schema": "c652-slot-snapshot/v1",
        "time": datetime.now(timezone.utc).isoformat(),
        "device": args.device,
        "operation": "GET_FEATURE 0x43..0x47",
        "write_performed": False,
        "slots": [slot.to_dict() for slot in slots],
    }
    Path(args.audit).write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(document, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
