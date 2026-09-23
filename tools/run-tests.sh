#!/bin/sh
set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
temporary_dir=$(mktemp -d)
trap 'rm -rf "$temporary_dir"' EXIT HUP INT TERM

PYTHONPATH="$repo_dir/sdk/python/src" \
    python3 -m unittest discover -s "$repo_dir/sdk/python/tests" -v

python3 "$repo_dir/tools/validate_public.py"
sh -n "$repo_dir/linux/install-linux-integration.sh"

if command -v systemd-analyze >/dev/null 2>&1; then
    systemd-analyze verify "$repo_dir/linux/c658-hidraw-hold-open.service"
fi

python3 "$repo_dir/tools/build_zipapp.py" \
    --source "$repo_dir/sdk/python/src" --output "$temporary_dir/one.pyz"
python3 "$repo_dir/tools/build_zipapp.py" \
    --source "$repo_dir/sdk/python/src" --output "$temporary_dir/two.pyz"
cmp "$temporary_dir/one.pyz" "$temporary_dir/two.pyz"
"$temporary_dir/one.pyz" --help >/dev/null

echo "all reproducibility and conformance checks passed"

