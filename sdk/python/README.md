# C658 Report 0x10 Linux SDK

Evidence-bounded Python SDK for constructing and sending the complete
3Dconnexion CadMouse Compact Wireless (`256f:c658`) Feature Report `0x10`,
including the paired-device path exposed by Universal Receiver `256f:c652`.

It also installs `c658-report10ctl`, a guarded hardware verification tool that
connects directly to this SDK.

Version 0.6.2 records successful hardware validation of the systemd user
service and ordinary wired USB mouse operation; automatic reopen after a live
USB reconnect remains a separate validation item. Version 0.6.1 removed
kernel-capability hardening directives that caused
`status=218/CAPABILITIES` under some systemd user managers. Version 0.6.0 added
a reconnect-aware wired C658 hidraw hold-open daemon,
active-user udev access rules, a hardened systemd user unit, and an installation
workflow for the hardware-confirmed input-stop workaround. Version 0.5.2 treats
`EPIPE` during unpair as an ambiguous transport completion
and continues polling; an empty target slot is authoritative success evidence.
Version 0.5.1 added guarded experimental unpair for one explicitly verified
receiver slot. Commit requires the exact 8-byte dry-run snapshot, an explicit
commit flag, and an interactive slot confirmation; before/after snapshots are
recorded. Version 0.5.0 replaces Enter-based receiver waiting with automatic post-write
Report 0x1b movement detection and completes positive phases when the requested
expected input count is observed. It also includes a standalone read-only
receiver-slot audit example. Version 0.4.2 added a recorded post-write settle interval to prevent stale
wireless mappings from contaminating the first trial. Version 0.4.1 corrected Report 0x03 interpretation using hardware evidence
(host index 1 -> bit 0, index 2 -> bit 1), uses physical button names in prompts,
and uses host index 1 for all-button tests. Version 0.4.0 added the staged `probe-report03-matrix` direct/host-index/all-slot
hardware investigation. Version 0.3.1 added unfiltered, simultaneous multi-hidraw input capture for
diagnosing Report 0x03 routing. Version 0.3.0 added Report 0x03 input discovery and bitmap verification,
read-only Receiver slot snapshots, a Linux SDK send-cache probe, and guarded
experimental pairing with forced stop and audit logging.

## Implemented fields

- Exact 32-byte wire report (`0x10` + complete 31-byte snapshot)
- DPI clamp and encoding
- Lift Detection byte
- Normal/inertial wheel constants
- Seven button entries
- Direct actions `0x0a..0x0f`
- Host-routed encoding `0x28 + action_index`
- Fixed byte `0x1e`, zero-reserved fields and polling divider
- Descriptor-based hidraw discovery
- Linux-observed C652 paired-device probe: `GET 0x08`, response byte 1 `0x59`
- Explicit Feature Report write boundary and bounded confirmation callback
- Reconnect-aware hold-open service for every wired C658 hidraw interface
- udev `uaccess` rules for C658/C652 and a systemd user unit

## Evidence labels preserved in the API

The sixth reachable direct code is named
`DirectAction.UNKNOWN_DIRECT_CODE_6`. It is not called RadialMenu because the
analysed binary does not prove that formal name.

Direct wire values `0x10..0x27` are not available to the encoder. The inspection
API reports them as `UNKNOWN_UNREACHABLE_DIRECT_WIRE_0xNN`.

Lift Detection is implemented as requested, but the recovered C658 SmartUI gate
hides this control (the UI path enables it for product `c650`). Therefore this
SDK labels it as an experimental C658 control. The encoded rule is:

- disabled: `0x1f`
- enabled: caller-supplied raw low byte `0x00..0xff`

## Install and test

```bash
python3 -m pip install -e .
python3 -m unittest discover -s tests -v
```

No third-party runtime dependency is required.

The supplied `c658-report10ctl.pyz` can be executed without installation:

```bash
python3 c658-report10ctl.pyz --help
```

## Hardware verification tool

First discover candidate nodes without writing:

```bash
c658-report10ctl scan
```

Preview the exact baseline bytes:

```bash
c658-report10ctl build
```

`apply` is a dry-run unless `--commit` is supplied:

```bash
c658-report10ctl apply --device /dev/hidrawN
c658-report10ctl apply --device /dev/hidrawN --commit
```

The recommended controlled end-to-end test uses button slot 7 and direct code
6. It validates the baseline first, applies wire `0x0f`, observes
`BTN_FORWARD`, restores the software baseline, and physically verifies the
restoration:

```bash
sudo c658-report10ctl probe-direct \
  --device /dev/hidrawN \
  --event /dev/input/eventN \
  --keep-open /dev/hidrawM \
  --slot 7 \
  --action unknown6 \
  --audit direct-code6-probe.json \
  --commit
```

The tool prompts before each transfer so the mouse can be moved and kept awake.
If sysfs cannot resolve the associated input node, specify it explicitly:

```bash
sudo c658-report10ctl probe-direct \
  --device /dev/hidrawN \
  --event /dev/input/eventN \
  --commit
```

`BTN_FORWARD` is the latest awake-receiver observation for code 6. It remains
an experimental expected result and is not used as the action's formal name.

## Build a report without device access

```python
from threedx_report10 import Report10Config

report = Report10Config.latest_software_baseline().to_wire_report()
assert len(report) == 32
print(report.hex(" "))
```

`latest_software_baseline()` is a host-side restoration baseline. It is not a
factory default.

See `examples/build_report.py` for code 6, Lift Detection and host-routed use.

## Discover a target

```python
from threedx_report10 import discover_receiver_c658_handles, discover_wired_c658

wired = discover_wired_c658()
receiver_children = discover_receiver_c658_handles()
```

Discovery never writes. It does not hard-code `/dev/hidrawN` or an interface
number. The receiver probe is hardware-confirmed on the tested receiver, but the
independent MSI-only analysis did not find a reachable normal-path `GET 0x08`
call in `HIDDev.dll`.

## Explicit write

```python
from threedx_report10 import HidrawDevice, Report10Config

config = Report10Config.latest_software_baseline()
with HidrawDevice("/dev/hidrawN") as device:
    device.apply_report10(config)
```

Writing requires appropriate device permissions. A successful
`HIDIOCSFEATURE` call confirms host-side submission only; it does not prove that
a wireless mouse applied the configuration. Use `apply_report10_bounded()` with
a caller-supplied physical confirmation function when application must be
verified. The SDK intentionally does not invent a wake gesture, delay or retry
policy.

## Scope

Pairing and unpair are available only as explicitly experimental commands. Their
exact
5-byte packets are prior-static evidence and require first Linux end-to-end
validation. The tool snapshots slots, requires a free slot, times out, and
attempts to stop pairing mode in `finally`. Unpair is restricted to one slot,
requires its exact current raw snapshot, and polls until that slot is empty.

This package does not implement bulk unpairing, DFU, firmware update,
factory-default readback, arbitrary Feature Report writes, or unsupported named
actions for direct wire values `0x10..0x27`.

See `RUN_ADVANCED_TESTS_JA.md` for Report 0x03, slot, cache, and pairing steps.
See `INSTALL_LINUX_JA.md` for the udev and systemd user-service installation.
