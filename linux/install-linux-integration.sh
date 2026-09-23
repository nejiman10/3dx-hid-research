#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
user_unit_dir=${XDG_CONFIG_HOME:-"$HOME/.config"}/systemd/user

if ! command -v c658-report10ctl >/dev/null 2>&1; then
    echo "error: c658-report10ctl is not installed in PATH" >&2
    echo "install first with: python3 -m pip install --user ." >&2
    exit 1
fi

install -d "$user_unit_dir"
install -m 0644 "$script_dir/c658-hidraw-hold-open.service" \
    "$user_unit_dir/c658-hidraw-hold-open.service"

echo "Installing the udev access rule requires administrator permission."
sudo install -m 0644 "$script_dir/69-3dconnexion-c658.rules" \
    /etc/udev/rules.d/69-3dconnexion-c658.rules
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=hidraw

systemctl --user daemon-reload
systemctl --user reset-failed c658-hidraw-hold-open.service 2>/dev/null || true
systemctl --user enable --now c658-hidraw-hold-open.service

echo "Installed. Reconnect the mouse if access was not granted immediately."
echo "Check with: systemctl --user status c658-hidraw-hold-open.service"
echo "Logs: journalctl --user -u c658-hidraw-hold-open.service -f"
