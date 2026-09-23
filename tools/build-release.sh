#!/bin/sh
set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
release_dir="$repo_dir/release"
archive="$release_dir/c658-protocol-research-baseline-1.tar.gz"

"$repo_dir/tools/run-tests.sh"
mkdir -p "$release_dir"
temporary_dir=$(mktemp -d)
trap 'rm -rf "$temporary_dir"' EXIT HUP INT TERM
stage="$temporary_dir/c658-protocol-research-baseline-1"
mkdir -p "$stage"

tar -C "$repo_dir" \
    --exclude='.git' \
    --exclude='release' \
    --exclude='evidence/source-private-not-in-repository' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    -cf - . | tar -C "$stage" -xf -

python3 "$repo_dir/tools/build_zipapp.py" \
    --source "$repo_dir/sdk/python/src" \
    --output "$stage/tools/c658-report10ctl.pyz"

tar -C "$temporary_dir" --sort=name --mtime='@0' --owner=0 --group=0 \
    --numeric-owner -cf - c658-protocol-research-baseline-1 | gzip -n -9 > "$archive"
(cd "$release_dir" && sha256sum "$(basename "$archive")" > "$(basename "$archive").sha256")
echo "$archive"
