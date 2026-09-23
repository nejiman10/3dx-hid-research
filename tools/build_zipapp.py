#!/usr/bin/env python3
"""Build a byte-reproducible c658-report10ctl zipapp."""

from __future__ import annotations

import argparse
import stat
import zipfile
from pathlib import Path


MAIN = "from threedx_report10.cli import main\n\nraise SystemExit(main())\n"
FIXED_TIME = (1980, 1, 1, 0, 0, 0)


def add(archive: zipfile.ZipFile, name: str, data: bytes, mode: int = 0o644) -> None:
    info = zipfile.ZipInfo(name, FIXED_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | mode) << 16
    archive.writestr(info, data, compresslevel=9)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("wb") as stream:
        stream.write(b"#!/usr/bin/env python3\n")
        with zipfile.ZipFile(stream, "w") as archive:
            add(archive, "__main__.py", MAIN.encode())
            for path in sorted(args.source.rglob("*.py")):
                add(archive, path.relative_to(args.source).as_posix(), path.read_bytes())
    args.output.chmod(0o755)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

