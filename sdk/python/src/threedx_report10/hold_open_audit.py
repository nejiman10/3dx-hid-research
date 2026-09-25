"""Bounded, interactive wired C658 hold-open comparison.

Discovery uses sysfs only.  The experiment never sends HID reports or reads a
hidraw FD; conditions B and C differ only in the access mode used to hold it.
"""

from __future__ import annotations

import argparse
import fcntl
import glob
import hashlib
import json
import os
import select
import selectors
import signal
import stat
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .hid_descriptor import feature_report_wire_lengths, input_report_wire_lengths
from .input_events import BTN_LEFT, EV_KEY, INPUT_EVENT

UNIT = "c658-hidraw-hold-open.service"
SYSFS_HIDRAW = Path("/sys/class/hidraw")
DEV_ROOT = Path("/dev")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class WiredNode:
    path: str
    usb_interface: str
    usb_parent: str
    descriptor_sha256: str
    report10_length: int | None
    input03_length: int | None
    event_paths: tuple[str, ...]

    def public_record(self) -> dict[str, object]:
        record = asdict(self)
        record.pop("usb_parent")
        return record


def _hid_id(uevent: str) -> tuple[int, int, int] | None:
    for line in uevent.splitlines():
        if line.startswith("HID_ID="):
            parts = line.removeprefix("HID_ID=").split(":")
            if len(parts) == 3:
                try:
                    return tuple(int(part, 16) for part in parts)  # type: ignore[return-value]
                except ValueError:
                    return None
    return None


def _interface_root(device: Path) -> tuple[str, str]:
    for ancestor in (device, *device.parents):
        number = ancestor / "bInterfaceNumber"
        if number.is_file():
            return number.read_text(encoding="ascii").strip(), str(ancestor.parent)
    raise RuntimeError("USB interface number was not found in sysfs")


def _event_paths(device: Path, dev_root: Path) -> tuple[str, ...]:
    patterns = (
        device / "input" / "input*" / "event*",
        device / "input*" / "event*",
        device / "*" / "input" / "input*" / "event*",
        device / "*" / "input*" / "event*",
    )
    names = {Path(match).name for pattern in patterns for match in glob.glob(str(pattern))}
    return tuple(str(dev_root / "input" / name) for name in sorted(names) if name.startswith("event"))


def discover_wired(
    sysfs_root: Path = SYSFS_HIDRAW, dev_root: Path = DEV_ROOT,
) -> list[WiredNode]:
    """Find USB C658 nodes without opening any hidraw device."""
    nodes = []
    for entry in sorted(sysfs_root.glob("hidraw*")):
        device = (entry / "device").resolve()
        try:
            if _hid_id((device / "uevent").read_text(encoding="utf-8")) != (3, 0x256F, 0xC658):
                continue
            descriptor = (device / "report_descriptor").read_bytes()
            interface, parent = _interface_root(device)
            features = feature_report_wire_lengths(descriptor)
            inputs = input_report_wire_lengths(descriptor)
            nodes.append(WiredNode(
                path=str(dev_root / entry.name), usb_interface=interface, usb_parent=parent,
                descriptor_sha256=hashlib.sha256(descriptor).hexdigest(),
                report10_length=features.get(0x10), input03_length=inputs.get(0x03),
                event_paths=_event_paths(device, dev_root),
            ))
        except FileNotFoundError:
            # A disconnect may remove a sysfs node while it is being inspected.
            continue
    return nodes


def _validate_one_device(nodes: list[WiredNode]) -> None:
    if not nodes:
        raise RuntimeError("no wired C658 hidraw interfaces are present")
    if len({node.usb_parent for node in nodes}) != 1:
        raise RuntimeError("more than one wired C658 USB device is present")
    if len({node.usb_interface for node in nodes}) != len(nodes):
        raise RuntimeError("duplicate USB interface number in wired C658 nodes")


def _shape(nodes: list[WiredNode]) -> set[tuple[str, str]]:
    return {(node.usb_interface, node.descriptor_sha256) for node in nodes}


def _visible_other_holders(nodes: list[WiredNode]) -> int:
    """Count visible processes with the target hidraw paths open."""
    targets = {node.path for node in nodes}
    holders = 0
    for process in Path("/proc").iterdir():
        if not process.name.isdecimal() or int(process.name) == os.getpid():
            continue
        try:
            links = list((process / "fd").iterdir())
        except (OSError, PermissionError):
            continue
        for link in links:
            try:
                if os.readlink(link) in targets:
                    holders += 1
                    break
            except OSError:
                continue
    return holders


def _service_state() -> str:
    result = subprocess.run(
        ["systemctl", "--user", "show", "--property=ActiveState", "--value", UNIT],
        capture_output=True, text=True, timeout=10, check=False,
    )
    state = result.stdout.strip()
    if result.returncode != 0 or state not in {"active", "inactive", "failed"}:
        raise RuntimeError(f"cannot determine user service state: {result.stderr.strip()}")
    return state


def _service_action(action: str) -> None:
    subprocess.run(["systemctl", "--user", action, UNIT],
                   capture_output=True, text=True, timeout=15, check=True)


def _write_audit(path: Path, document: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def preflight() -> dict[str, object]:
    nodes = discover_wired()
    return {
        "time": _now(), "service_state": _service_state(),
        "wired_nodes": [node.public_record() for node in nodes],
        "hidraw_readable": bool(nodes) and all(os.access(node.path, os.R_OK) for node in nodes),
        "hidraw_read_write": bool(nodes) and all(
            os.access(node.path, os.R_OK | os.W_OK) for node in nodes),
        "event_readable": sorted({path for node in nodes for path in node.event_paths
                                  if os.access(path, os.R_OK)}),
        "root_user": os.geteuid() == 0,
    }


def _answer(prompt: str, seconds: float) -> str:
    print(prompt + " [y=はい / n=いいえ / u=不明]: ", end="", flush=True)
    ready, _, _ = select.select([sys.stdin], [], [], seconds)
    if not ready:
        print(flush=True)
        raise TimeoutError("operator response timed out")
    answer = sys.stdin.readline().strip().lower()
    choices = {"y": "y", "yes": "y", "はい": "y", "n": "n", "no": "n",
               "いいえ": "n", "u": "u", "unknown": "u", "不明": "u"}
    if answer not in choices:
        raise RuntimeError("answer must be y, n, or u (yes/no/unknown also accepted)")
    return choices[answer]


def _enter(prompt: str, seconds: float) -> None:
    print(prompt + " Enterを押してください: ", end="", flush=True)
    ready, _, _ = select.select([sys.stdin], [], [], seconds)
    if not ready:
        print(flush=True)
        raise TimeoutError("reconnect prompt timed out")
    sys.stdin.readline()


def _prompt_reconnect(baseline: list[WiredNode], seconds: float = 45) -> list[WiredNode]:
    _enter("USBケーブルを外し、外したら", 60)
    deadline = time.monotonic() + seconds
    while discover_wired() and time.monotonic() < deadline:
        time.sleep(0.25)
    if discover_wired():
        raise TimeoutError("wired C658 did not disappear after unplug")
    _enter("USBケーブルを接続し、接続したら", 60)
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        nodes = discover_wired()
        if nodes and _shape(nodes) == _shape(baseline):
            _validate_one_device(nodes)
            return nodes
        time.sleep(0.25)
    raise TimeoutError("wired C658 did not return with the expected interfaces and descriptors")


def _hold(nodes: list[WiredNode], mode: str, records: list[dict[str, object]]) -> list[int]:
    if mode == "A":
        return []
    if mode in {"MI00", "MI01"}:
        selected = [node for node in nodes if node.usb_interface == mode[2:]]
        if len(selected) != 1:
            raise RuntimeError(f"expected exactly one interface {mode[2:]}")
    elif mode in {"B", "C"}:
        selected = nodes
    else:
        raise RuntimeError(f"unsupported hold condition: {mode}")
    flags = (os.O_RDWR if mode == "C" else os.O_RDONLY) | os.O_CLOEXEC | os.O_NONBLOCK
    fds: list[int] = []
    try:
        for node in selected:
            record: dict[str, object] = {
                "path": node.path, "interface": node.usb_interface, "requested_flags": flags,
                "time": _now(),
            }
            records.append(record)
            try:
                fd = os.open(node.path, flags)
                fds.append(fd)
                if not stat.S_ISCHR(os.fstat(fd).st_mode):
                    raise RuntimeError(f"not a character device: {node.path}")
                record.update({
                    "result": "held", "effective_status_flags": fcntl.fcntl(fd, fcntl.F_GETFL),
                    "effective_fd_flags": fcntl.fcntl(fd, fcntl.F_GETFD),
                })
            except OSError as exc:
                record.update({"result": "open-error", "errno": exc.errno, "error": str(exc)})
                raise
        return fds
    except BaseException:
        for fd in fds:
            os.close(fd)
        raise


def _capture_evdev(paths: list[str], seconds: float) -> dict[str, object]:
    """Open evdev only after both manual checks, recording the observer effect."""
    result: dict[str, object] = {"started_at": _now(), "duration_seconds": seconds,
                                 "presses": 0, "releases": 0, "relative_events": 0,
                                 "opened_paths": [], "open_errors": []}
    selector = selectors.DefaultSelector()
    fds: list[int] = []
    pending: dict[int, bytearray] = {}
    try:
        for path in paths:
            try:
                fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK)
            except OSError as exc:
                result["open_errors"].append({"path": path, "errno": exc.errno})
                continue
            fds.append(fd)
            pending[fd] = bytearray()
            selector.register(fd, selectors.EVENT_READ, path)
            result["opened_paths"].append(path)
        if not fds:
            raise RuntimeError("no input event node could be opened as the standard user")
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            for key, _ in selector.select(max(0, deadline - time.monotonic())):
                fd = int(key.fd)
                try:
                    chunk = os.read(fd, INPUT_EVENT.size * 32)
                except BlockingIOError:
                    continue
                if not chunk:
                    continue
                pending[fd].extend(chunk)
                while len(pending[fd]) >= INPUT_EVENT.size:
                    item = bytes(pending[fd][:INPUT_EVENT.size])
                    del pending[fd][:INPUT_EVENT.size]
                    _sec, _usec, kind, code, value = INPUT_EVENT.unpack(item)
                    if kind == EV_KEY and code == BTN_LEFT and value == 1:
                        result["presses"] += 1
                    elif kind == EV_KEY and code == BTN_LEFT and value == 0:
                        result["releases"] += 1
                    elif kind == 0x02:
                        result["relative_events"] += 1
        result["finished_at"] = _now()
        return result
    finally:
        selector.close()
        for fd in fds:
            os.close(fd)


def _run_phase(
    mode: str, baseline: list[WiredNode], phase: dict[str, object], save,
) -> None:
    nodes = _prompt_reconnect(baseline)
    reconnected_monotonic = time.monotonic()
    phase["reconnected_at"] = _now()
    phase["nodes"] = [node.public_record() for node in nodes]
    phase["open_records"] = []
    phase["planned_held_interfaces"] = (
        [] if mode == "A" else [node.usb_interface for node in nodes
                                if mode in {"B", "C"} or node.usb_interface == mode[2:]])
    save()
    fds: list[int] = []
    try:
        fds = _hold(nodes, mode, phase["open_records"])
        if mode != "A":
            phase["fds_held_at"] = _now()
        current = discover_wired()
        if _shape(current) != _shape(nodes) or {node.path for node in current} != {node.path for node in nodes}:
            raise RuntimeError("wired target changed while opening the hold FDs")
        phase["visible_other_holders"] = _visible_other_holders(nodes)
        if phase["visible_other_holders"]:
            raise RuntimeError("another visible process holds a target hidraw node")
        phase["observation_started_at"] = _now()
        phase["settle_target_seconds"] = 30
        save()
        print(f"条件{mode}: 再接続の検知から30秒待ちます。停止までの秒数は測りません。", flush=True)
        time.sleep(max(0, reconnected_monotonic + 30 - time.monotonic()))
        phase["settled_at"] = _now()
        phase["settle_elapsed_seconds"] = round(time.monotonic() - reconnected_monotonic, 3)
        save()
        print("カーソルを動かし、左クリックを1回してください。", flush=True)
        phase["manual_after_idle"] = _answer(
            "30秒以上経過した後のカーソル移動と左クリックは正常でしたか", 45)
        phase["manual_after_idle_answered_at"] = _now()
        save()
        event_paths = sorted({path for node in nodes for path in node.event_paths})
        print("これから10秒間、左クリックを3回押下・解放してください。", flush=True)
        phase["evdev"] = _capture_evdev(event_paths, 10)
        save()
        phase["operator_three_clicks"] = _answer(
            "10秒間に左ボタンを物理的に3回押下・解放しましたか（画面の反応は問いません）", 45)
        phase["finished_at"] = _now()
        save()
    finally:
        for fd in fds:
            os.close(fd)
        phase["fds_closed_at"] = _now()
        save()


def _prior_baseline(path: Path, nodes: list[WiredNode]) -> dict[str, object]:
    raw = path.read_bytes()
    prior = json.loads(raw)
    if prior.get("schema") != "3dx-hold-open-audit/v1":
        raise RuntimeError("prior audit has the wrong schema")
    if prior.get("service_initial") != prior.get("service_final") or prior.get("restoration_failure"):
        raise RuntimeError("prior audit did not record service restoration")
    conditions = prior.get("conditions", [])
    if prior.get("prior_condition_A"):
        control = prior["prior_condition_A"]
        if "n" not in (control.get("manual_immediate"), control.get("manual_after_idle")):
            raise RuntimeError("prior chain does not record a failed condition A")
        if not conditions or conditions[0].get("condition") != "B":
            raise RuntimeError("prior audit does not contain condition B")
        reference = conditions[0]
        events = reference.get("evdev") or {}
        opens = reference.get("open_records") or []
        expected_interfaces = {node.usb_interface for node in nodes}
        held_interfaces = {item.get("interface") for item in opens
                           if item.get("result") == "held"
                           and item.get("requested_flags", 0) & os.O_ACCMODE == os.O_RDONLY}
        if (reference.get("failure") or reference.get("manual_after_idle") != "y"
                or reference.get("operator_three_clicks") != "y"
                or events.get("presses", 0) < 3 or events.get("releases", 0) < 3
                or len(opens) != len(nodes) or held_interfaces != expected_interfaces
                or reference.get("visible_other_holders") != 0):
            raise RuntimeError("prior condition B was not fully confirmed")
        observed_shape = {(item["usb_interface"], item["descriptor_sha256"])
                          for item in reference.get("nodes", [])}
        if observed_shape != _shape(nodes):
            raise RuntimeError("wired interfaces or descriptors differ from prior condition B")
        return {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "condition_A": control,
            "condition_B": {
                "time": reference.get("started_at"),
                "manual_immediate": reference.get("manual_immediate"),
                "manual_after_idle": "y",
                "evdev_presses": events["presses"], "evdev_releases": events["releases"],
            },
            "remaining_conditions": ["C"],
            "prior_failure": prior.get("failure"),
        }
    if not conditions or conditions[0].get("condition") != "A":
        raise RuntimeError("prior audit does not contain condition A")
    control = conditions[0]
    if "n" not in (control.get("manual_immediate"), control.get("manual_after_idle")):
        raise RuntimeError("prior condition A did not record an input failure")
    observed_shape = {(item["usb_interface"], item["descriptor_sha256"])
                      for item in control.get("nodes", [])}
    if observed_shape != _shape(nodes):
        raise RuntimeError("wired interfaces or descriptors differ from prior condition A")
    evdev = control.get("evdev") or {}
    return {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "time": control.get("started_at"),
        "manual_immediate": control.get("manual_immediate"),
        "manual_after_idle": control.get("manual_after_idle"),
        "evdev_presses": evdev.get("presses"),
        "evdev_releases": evdev.get("releases"),
        "operator_clicks_in_prior_audit": control.get("operator_three_clicks"),
        "remaining_conditions": ["B", "C"],
        "prior_failure": prior.get("failure"),
    }


def run(audit_path: Path, *, prior_audit: Path | None = None,
        stop_after_b: bool = False, compare_interfaces: bool = False) -> int:
    if os.geteuid() == 0:
        raise RuntimeError("run as the standard user; sudo is not permitted")
    if not sys.stdin.isatty():
        raise RuntimeError("interactive terminal input is required")
    if audit_path.exists():
        raise RuntimeError(f"audit already exists: {audit_path}")
    if compare_interfaces and (prior_audit is not None or stop_after_b):
        raise RuntimeError("interface comparison cannot use --prior-audit or --stop-after-B")
    initial = preflight()
    nodes = discover_wired()
    _validate_one_device(nodes)
    if compare_interfaces and {node.usb_interface for node in nodes} != {"00", "01"}:
        raise RuntimeError("interface comparison requires exactly MI00 and MI01")
    if not initial["hidraw_read_write"] or not initial["event_readable"]:
        raise RuntimeError("standard-user hidraw or evdev access is insufficient; stop without sudo")
    document: dict[str, object] = {
        "schema": "3dx-hold-open-audit/v1", "started_at": _now(),
        "service_initial": initial["service_state"],
        "baseline_nodes": [node.public_record() for node in nodes],
        "conditions": [], "hid_report_writes": False,
        "observer_note": "evdev FDs are opened only after manual input checks",
    }
    if prior_audit is not None:
        document["prior_condition_A"] = _prior_baseline(prior_audit, nodes)
    modes = (("B", "MI00", "MI01", "B") if compare_interfaces else
             document["prior_condition_A"]["remaining_conditions"]
             if prior_audit is not None else ("A", "B", "C"))
    if compare_interfaces:
        document["interface_comparison"] = True
    if stop_after_b:
        if "B" not in modes:
            raise RuntimeError("the prior audit leaves no condition B to test")
        modes = modes[:modes.index("B") + 1]
        document["planned_stop_after_B"] = True
    _write_audit(audit_path, document)
    if compare_interfaces:
        print("全interface保持を前後の対照とし、MI00のみ、MI01のみを各1回試します。", flush=True)
    elif prior_audit is None:
        print("A: FD保持なし。Aで入力異常が再現した場合だけB: O_RDONLY"
              + ("を試します。" if stop_after_b else "、C: O_RDWRを試します。"), flush=True)
    else:
        print("前回の監査を参照し、残る条件 " + ", ".join(modes)
              + " を試します。", flush=True)
    print("各条件は再接続の検知から30秒待った後に入力を確認します。回答待ちは各45秒です。", flush=True)
    print(f"user serviceの初期状態: {initial['service_state']}。終了・中断時に元へ戻します。", flush=True)
    previous_term = signal.getsignal(signal.SIGTERM)

    def interrupt(_signum: int, _frame: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    initially_active = initial["service_state"] == "active"
    try:
        if initially_active:
            document["service_stop_started_at"] = _now()
            _write_audit(audit_path, document)
            _service_action("stop")
            if _service_state() != "inactive":
                raise RuntimeError("hold-open user service did not become inactive")
            document["service_stopped_at"] = _now()
            _write_audit(audit_path, document)
        elif _service_state() != initial["service_state"]:
            raise RuntimeError("user service state changed before the comparison")
        for mode in modes:
            phase: dict[str, object] = {"condition": mode, "started_at": _now()}
            document["conditions"].append(phase)
            _write_audit(audit_path, document)
            try:
                _run_phase(mode, nodes, phase, lambda: _write_audit(audit_path, document))
            except BaseException as exc:
                phase["failure"] = str(exc)
                raise
            finally:
                _write_audit(audit_path, document)
            if phase.get("operator_three_clicks") != "y":
                document["stopped_after_operator_check"] = "physical three-click operation was not confirmed"
                break
            if compare_interfaces and mode == "B" and (
                    phase.get("manual_after_idle") != "y"
                    or phase.get("evdev", {}).get("presses", 0) < 3
                    or phase.get("evdev", {}).get("releases", 0) < 3):
                document["stopped_after_control"] = "full-interface positive control was not confirmed"
                break
            if mode == "A" and phase["manual_after_idle"] != "n":
                document["stopped_after_A"] = "baseline symptom did not clearly reproduce"
                break
        document["completed_at"] = _now()
    except BaseException as exc:
        document["failure"] = str(exc) or type(exc).__name__
    finally:
        previous_int = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        if initially_active:
            try:
                document["service_restore_started_at"] = _now()
                _service_action("start")
                document["service_final"] = _service_state()
                if document["service_final"] != "active":
                    document["restoration_failure"] = "user service did not return to active"
            except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                document["restoration_failure"] = str(exc)
        else:
            try:
                document["service_final"] = _service_state()
            except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                document["restoration_failure"] = str(exc)
        if document.get("service_final") == initial["service_state"]:
            print("最後にカーソルを動かし、左クリックを1回して入力を確認してください。", flush=True)
            try:
                document["operation_after_restore"] = _answer("終了時の通常入力は正常ですか", 45)
            except (OSError, RuntimeError) as exc:
                document["operation_after_restore"] = "u"
                document["operation_check_error"] = str(exc)
        document["finished_at"] = _now()
        _write_audit(audit_path, document)
        signal.signal(signal.SIGINT, previous_int)
        signal.signal(signal.SIGTERM, previous_term)
    print(f"非公開監査: {audit_path}")
    if document.get("restoration_failure"):
        print(f"SERVICE RESTORATION FAILED: {document['restoration_failure']}", file=sys.stderr)
    elif initially_active:
        print(f"user service restored: {document.get('service_final')}")
    return 1 if (document.get("failure") or document.get("restoration_failure")
                 or document.get("stopped_after_operator_check") or document.get("stopped_after_control")
                 or document.get("operation_after_restore") != "y") else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="read-only wired C658 hold-open comparison")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("preflight", help="sysfs and user-service checks only")
    trial = sub.add_parser("run", help="interactive A/B/C trial; temporarily stops active user service")
    trial.add_argument("--audit", type=Path, required=True, help="new private JSON audit path")
    trial.add_argument("--prior-audit", type=Path,
                       help="verified prior A or B audit; run only remaining conditions")
    trial.add_argument("--stop-after-B", action="store_true",
                       help="repeat A/B only; omit condition C")
    trial.add_argument("--compare-interfaces", action="store_true",
                       help="full-interface controls around MI00-only and MI01-only holds")
    args = parser.parse_args(argv)
    try:
        if args.command == "preflight":
            print(json.dumps(preflight(), ensure_ascii=False, indent=2))
            return 0
        return run(args.audit, prior_audit=args.prior_audit,
                   stop_after_b=args.stop_after_B,
                   compare_interfaces=args.compare_interfaces)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
