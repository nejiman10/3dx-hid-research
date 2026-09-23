#!/usr/bin/env python3
"""Validate public repository structure, data files and privacy boundary."""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_TEXT = ("/" + "home" + "/", "/" + "workspace" + "/", "shiji" + "rim")
VENDOR_BINARY_SUFFIXES = {".msi", ".dll", ".exe", ".sys", ".cab"}
RAW_ID = re.compile(r"(?:08|4[3-7]) 59(?: [0-9a-fA-F]{2}){6}")


def fail(message: str) -> None:
    print(f"public validation failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def walk_values(value, path=()):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from walk_values(item, (*path, key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from walk_values(item, (*path, str(index)))
    else:
        yield path, value


def main() -> int:
    if (ROOT / "evidence/source-private-not-in-repository").exists():
        fail("private source evidence directory is present")
    for path in ROOT.rglob("*"):
        relative = path.relative_to(ROOT)
        if relative.parts and relative.parts[0] == "release":
            continue
        if path.is_file() and path.suffix.lower() in VENDOR_BINARY_SUFFIXES:
            fail(f"vendor binary-like file included: {relative}")
        if not path.is_file() or ".git" in path.parts or path.suffix in {".pyc", ".gz"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for forbidden in FORBIDDEN_TEXT:
            if forbidden in text:
                fail(f"private path/name {forbidden!r} in {relative}")
        if RAW_ID.search(text):
            fail(f"unredacted Receiver/C658 identifier in {relative}")

    json_paths = sorted(
        path for path in ROOT.rglob("*.json")
        if not path.relative_to(ROOT).parts or path.relative_to(ROOT).parts[0] != "release"
    )
    for path in json_paths:
        document = json.loads(path.read_text(encoding="utf-8"))
        for keys, value in walk_values(document):
            if keys and keys[-1] == "serial_raw_hex" and isinstance(value, str):
                parts = value.split()
                if len(parts) == 6 and any(item != "00" for item in parts):
                    fail(f"unredacted serial field in {path.relative_to(ROOT)}: /{'/'.join(keys)}")

    with (ROOT / "spec/EVIDENCE_STATUS.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if not rows or any(None in row for row in rows):
        fail("EVIDENCE_STATUS.csv is empty or malformed")
    manifest = json.loads((ROOT / "evidence/public/manifest.json").read_text(encoding="utf-8"))
    if not manifest.get("files") or not manifest.get("tokens"):
        fail("evidence manifest has no files or anonymization token")
    print(f"public validation passed: {len(json_paths)} JSON files, {len(rows)} evidence rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
