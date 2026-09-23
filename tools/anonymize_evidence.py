#!/usr/bin/env python3
"""Create deterministic public JSON audits without device identifiers."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def pointer(path: tuple[str, ...]) -> str:
    return "/" + "/".join(item.replace("~", "~0").replace("/", "~1") for item in path)


def hex_bytes(value: str) -> list[str] | None:
    parts = value.lower().split()
    if parts and all(len(item) == 2 and all(c in "0123456789abcdef" for c in item) for item in parts):
        return parts
    return None


class Sanitizer:
    def __init__(self) -> None:
        self.identifiers: dict[str, str] = {}

    def token_for(self, raw: str) -> str:
        if raw not in self.identifiers:
            letter = chr(ord("A") + len(self.identifiers))
            self.identifiers[raw] = f"<ANONYMIZED:DEVICE_ID_{letter}:6_BYTES>"
        return self.identifiers[raw]

    def transform(self, value: Any, path: tuple[str, ...], changes: list[dict[str, str]]) -> Any:
        if isinstance(value, dict):
            return {
                key: self.transform(item, (*path, key), changes)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self.transform(item, (*path, str(index)), changes) for index, item in enumerate(value)]
        if not isinstance(value, str) or not path:
            return value

        key = path[-1]
        parts = hex_bytes(value)
        replacement: str | None = None
        if key == "serial_raw_hex" and parts and len(parts) == 6 and any(item != "00" for item in parts):
            replacement = self.token_for(" ".join(parts))
        elif key in {"raw_hex", "required_expect_raw", "observed_hex"} and parts and len(parts) == 8:
            if parts[1] == "59" and any(item != "00" for item in parts[2:]):
                replacement = f"{parts[0]} {parts[1]} {self.token_for(' '.join(parts[2:]))}"
        if replacement is not None:
            changes.append({"json_pointer": pointer(path), "replacement": replacement})
            return replacement
        return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    sanitizer = Sanitizer()
    records: list[dict[str, Any]] = []
    for source in sorted(args.source.glob("*.json")):
        document = json.loads(source.read_text(encoding="utf-8"))
        changes: list[dict[str, str]] = []
        public = sanitizer.transform(document, (), changes)
        destination = args.output / source.name
        destination.write_text(
            json.dumps(public, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        records.append({
            "file": source.name,
            "source_sha256": sha256(source),
            "public_sha256": sha256(destination),
            "redactions": changes,
        })
    manifest = {
        "schema": "c658-public-evidence-manifest/v1",
        "policy": "device identifiers replaced; original audits excluded from repository",
        "tokens": sorted(set(sanitizer.identifiers.values())),
        "files": records,
    }
    args.manifest.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    lines = [
        "# Evidence anonymization report",
        "",
        "Original audit files are not distributed. Device-identifier candidates were",
        "replaced with stable, visibly marked tokens. Source hashes allow the holder of",
        "a private original to verify provenance without publishing its identifier.",
        "",
        "| Public file | Redactions | Original SHA-256 | Public SHA-256 |",
        "|---|---:|---|---|",
    ]
    for item in records:
        lines.append(
            f"| `{item['file']}` | {len(item['redactions'])} | `{item['source_sha256']}` | `{item['public_sha256']}` |"
        )
    lines.extend(["", "## Replaced fields", ""])
    for item in records:
        for change in item["redactions"]:
            lines.append(
                f"- `{item['file']}{change['json_pointer']}` → `{change['replacement']}`"
            )
    if not any(item["redactions"] for item in records):
        lines.append("- None")
    args.report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

