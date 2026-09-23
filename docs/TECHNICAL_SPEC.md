# 3Dconnexion C658 / C652 Linux technical notes

Status: research snapshot, 2026-09-22  
Target: CadMouse Compact Wireless `256f:c658`, Universal Receiver `256f:c652`  
Scope: normal HID configuration, buttons, host-routed actions, receiver pairing/control  
Excluded: DFU, firmware update, on-air radio protocol and cryptography

## 1. Evidence terminology

- **Static-confirmed**: reachable code path was recovered from 3DxWare 10.9.14.
- **Hardware-confirmed**: reproduced on the stated C658/C652 hardware under Linux.
- **Prior-static**: found in the earlier integrated reverse-engineering notes but not reproduced by the later independent MSI-only pass.
- **Inference**: best explanation of observations, not yet a controlled result.
- **Unknown**: evidence is insufficient. Unknown values must not be assigned guessed names.

The independently analysed MSI has SHA-256
`799a1f3f2c4effc5113a9838f26fa6386b470a24a3ab29330a474a0e7f6b5e99`.

## 2. HID topology and target selection

### 2.1 USB-connected C658

The Linux target is a `256f:c658` hidraw node whose report descriptor declares
Feature Report `0x10` with a total wire length of 32 bytes. On one observed
revision this was interface 1 with a 208-byte report descriptor. Hidraw numbers
and interface numbers are not stable identifiers and must not be hard-coded.

`HIDIOCGFEATURE(32)` for Report `0x10` returned `EPIPE` on the tested wired
C658. The current mouse configuration and factory default therefore cannot be
assumed to be readable.

### 2.2 C658 behind the Universal Receiver

Receiver management and paired-device HID paths are distinct. Mouse Report
`0x10` must not be sent to an arbitrary C652 management path.

The Linux procedure that worked on the tested receiver is:

1. Enumerate `256f:c652` hidraw nodes supporting 32-byte Feature Report `0x10`.
2. Issue 8-byte `GET_FEATURE 0x08` to each candidate.
3. Select the node for which `response[1] == 0x59`.
4. Send the ordinary 32-byte Report `0x10` to that same node.

Observed response:

```text
08 59 <ANONYMIZED:DEVICE_ID_A:6_BYTES>
```

No slot number, receiver wrapper, device type or serial number is added to
Report `0x10`. Selection is expressed by the paired-device handle.

Important evidence boundary: the independent MSI-only pass found no reachable
normal-path `HidD_GetFeature` call site for Report `0x08` in `HIDDev.dll`.
Therefore the Linux discovery method above is hardware-confirmed, but must not
be attributed to that particular recovered 3DxWare call chain without further
static evidence.

## 3. Report 0x10 configuration snapshot

The wire transfer is 32 bytes:

```text
byte 0      Report ID = 0x10
byte 1..31  complete configuration blob
```

The host constructs a complete 31-byte snapshot; this is not a read-modify-write
operation. The independent static pass confirmed that the blob is zeroed first
and that only offsets 1, 2, 3..6, 18..24, 26 and 30 are subsequently written.

| Blob offset | Wire offset | Meaning | Encoding / status |
|---:|---:|---|---|
| 0 | 1 | zero/reserved | constant `00` |
| 1 | 2 | DPI | `<=50:01`, `51..8199:floor(DPI/50)`, `>=8200:a4` |
| 2 | 3 | effective lift threshold | enabled low byte; disabled `1f` |
| 3..6 | 4..7 | wheel mode | normal `01 ff 00 00`; inertial `00 00 00 01` |
| 7..17 | 8..18 | zero/reserved | constant `00` |
| 18..24 | 19..25 | seven button mappings | direct or host-routed encoding |
| 25 | 26 | zero/reserved | constant `00` |
| 26 | 27 | wheel-related fixed field | constant `1e`; device meaning unknown |
| 27..29 | 28..30 | zero/reserved | constant `00` |
| 30 | 31 | polling divider | 1000/500/250/125 Hz -> `1/2/4/8` |

The generator contains lift-threshold logic, but the C658 SmartUI capability
gate disables the Lift Detection control; the visible UI is enabled only for
product `c650`. A Linux tool should not advertise C658 lift control as a
verified supported feature merely because the generic generator has the field.

### 3.1 Safe baseline policy

Report `0x10` is not reliably readable. A Linux implementation must construct a
complete structurally valid blob from known values. Such a payload is a
**software baseline**, not a claimed factory default.

The most recently used valid baseline was:

```text
00 1c 1f 01 ff 00 00 00 00 00 00 00 00 00 00 00
00 00 0a 0b 0c 0c 0e 0d 0c 00 1e 00 00 00 01
```

Only the relevant button mapping byte was changed during controlled Direct
Action tests, followed by restoration of the full baseline.

## 4. Button mapping and Direct Action

For each of seven button entries:

```text
device-direct: wire = 0x09 + action_code
host-routed:   wire = 0x28 + action_code
```

The first formula is statically confirmed in
`HIDDev.dll!SBHID_SendPIDConfig_2DMouse`; the second uses the host flag and is
also statically confirmed.

### 4.1 Statically named and reachable direct actions

| Action code | Wire | Static internal name | Linux hardware observation |
|---:|---:|---|---|
| 1 | `0x0a` | `HIDMouse_Left` | `BTN_LEFT` |
| 2 | `0x0b` | `HIDMouse_Right` | `BTN_RIGHT` |
| 3 | `0x0c` | `HIDMouse_Middle` / `HIDMouse_WheelButton` | `BTN_MIDDLE` |
| 4 | `0x0d` | `HIDMouse_Backward` | `BTN_SIDE` on the tested wired path |
| 5 | `0x0e` | `HIDMouse_Forward` | `BTN_EXTRA` on the tested wired path |
| 6 | `0x0f` | unknown default button-7 action | latest awake receiver run: `BTN_FORWARD` |

Code 6 is written by the C658 seven-button default initializer, but no binary
symbol proves its formal enum name. `HIDMouse_RadialMenu` is compared by the
profile mapper but returns code 0, so its display string is not proof that code
6 is named RadialMenu.

### 4.2 Values without a reachable C658 producer

- Wire `0x10` and `0x11` correspond arithmetically to action codes 7 and 8.
- Wire `0x12..0x27` correspond arithmetically to action codes 9..30.
- The independent static pass found no reachable C658 UI/profile producer,
  enum name or display string for codes 7..30.
- These values are `STATICALLY_UNUSED_OR_UNREACHABLE` in the normal C658 path.
- This does not prove that C658 firmware cannot interpret a manually injected
  value; such testing is firmware-capability research, not reconstruction of a
  supported 3DxWare feature.

The latest awake receiver experiment observed `0x10 -> BTN_MIDDLE` and
`0x11 -> BTN_BACK`. Older runs conflicted. These results must remain hardware
observations and must not be promoted to named 3DxWare Direct Actions.

### 4.3 Host-routed actions and Input Report 0x03

The C658 configuration defines seven host-routed bitmap positions:

```text
0001 0002 0004 0008 0010 0020 0040
```

The static parser compares Report ID, builds a little-endian bitmap from the
payload and emits transitions when a mask changes. Hardware matrix tests on
both the wired C658 and receiver path established that this bitmap identifies
the configured host action index, not the physical button-table slot:

| Host index | Wire value | Report `0x03` press payload | Status |
|---:|---:|---:|---|
| 0 | `0x28` | none observed | hardware-observed negative |
| 1 | `0x29` | `03 01` | hardware-confirmed |
| 2 | `0x2a` | `03 02` | hardware-confirmed |
| 3..6 | `0x2b..0x2e` | inferred `03 04..03 20` | not hardware-verified |
| 7 | `0x2f` | `03 40` | hardware-confirmed |
| 215 | `0xff` | none observed | hardware-observed negative |

Release is `03 00`. Physical left, right, middle, wheel, forward, back and
radial buttons can all carry a verified host-routed index; therefore physical
button names and host index names must remain separate in APIs and logs.

## 5. Sending, cache and sleeping receiver behaviour

The recovered generator:

- compares the generated 31-byte blob with a per-device last-successful cache;
- suppresses an identical blob;
- updates the cache only after a successful broker send;
- clears the cache after send failure;
- contains no immediate retry, delay, backoff, wake operation or
  receiver-child-specific queue.

Linux tests showed that the ioctl can return success even when the expected
button mapping is not subsequently observed. Receiver matrix tests also saw a
single old-mapping event after several successful writes. A fixed two-second
delay was not always sufficient. This supports, but does not prove, transfer
on a later wireless activity opportunity rather than immediate application.

Implementation consequence:

1. Ensure recent device activity before a receiver write.
2. Do not equate successful `HIDIOCSFEATURE` with confirmed mouse application.
3. After the write, prompt for mouse movement and automatically detect a
   motion-bearing Report `0x1b`; do not block on Enter.
4. Complete a positive verification phase only after the expected Report
   `0x03` or direct-button press count is observed; negative controls complete
   at the bounded observation timeout.
5. Allow a bounded resend after activity when confirmation fails.
6. Keep the complete intended blob in host-side state.

## 6. Receiver pairing and management

Independent static analysis confirmed pairing-table reads using
`GET_FEATURE (0x43 + slot)`. Report length is derived from the descriptor.
The SDK supplies both `receiver-slots` and the standalone
`examples/audit_receiver_slots.py`; each performs only GET operations for
`0x43..0x47` and preserves every raw 8-byte response in JSON.
Prior static analysis reconstructed the following management operations:

| Operation | Report | Status |
|---|---|---|
| pairing start/stop | `0x41 / subcommand 0x02` | Linux end-to-end hardware-confirmed |
| unpair slot | `0x41 / subcommand 0x04` | Linux end-to-end hardware-confirmed; ioctl may return `EPIPE` after effect |
| slot 0..4 information | GET `0x43..0x47` | independent static-confirmed |

Report `0x42` has no functional GET/SET call path in the independently analysed
normal C652 path. Specific reachable readers for Report `0x50` bytes 6..7 and
Report `0x60` fields were also not found. These must not be treated as required
features of the initial Linux CLI.

A safe pairing implementation should:

1. Snapshot slots 0..4.
2. Start pairing mode.
3. Wait for re-enumeration without blocking indefinitely.
4. Snapshot slots again and identify a newly occupied slot.
5. Stop pairing mode.
6. Verify ordinary input from the intended mouse.
7. Identify the paired C658 HID path and test normal Report `0x10` delivery.

The guarded unpair implementation accepts exactly one slot. A committing call
requires the current raw 8-byte slot response copied from a dry-run, an explicit
experimental commit flag and interactive `UNPAIR <slot>` confirmation. It
records before/after snapshots and succeeds only after that slot reads empty.
No bulk removal or inferred target selection is permitted.

Linux end-to-end testing confirmed that `41 04 <slot> 00 00` removes the
selected bond. The ioctl may return `EPIPE` even though the removal took effect,
because the HID endpoint can disconnect or re-enumerate before transport
completion is returned. `EPIPE` is therefore recorded as an ambiguous transport
result and does not stop polling. An empty target slot is the authoritative
effect confirmation. A subsequent pairing test successfully registered the
same C658 in a new slot and sent pairing stop.

## 7. Known lifecycle boundary

The following static chain is confirmed:

```text
main event loop
  -> pending download handler
  -> DownloadToKernel
  -> DownloadToKernelForSingleDevice
  -> 2D mouse dispatcher
  -> SBHID_SendPIDConfig_2DMouse
  -> broker SetBlob(type 6)
```

The complete edges from service startup, USB reconnect, resume and profile
change into the pending-download state are not fully reconstructed. Statements
such as “Report 0x10 is always resent on resume” must not be made yet.

### 7.1 Linux wired hidraw lifetime workaround

Hardware testing observed that ordinary wired mouse input could stop unless the
relevant hidraw nodes remained open. The exact kernel, firmware and interface
root cause is unknown. The Linux integration therefore applies an explicitly
labelled workaround rather than claiming a protocol requirement:

- enumerate every readable `256f:c658` hidraw interface;
- hold each interface `O_RDWR | O_NONBLOCK` without consuming input;
- exclude all `256f:c652` receiver interfaces from the holder;
- release disappeared paths and open new paths after reconnect;
- run as the active desktop user through a systemd user service;
- grant active-user hidraw access through udev `TAG+=uaccess`.

The holder performs no Feature Report writes. Report `0x10` reapplication after
reconnect or resume is a separate future policy and must not be inferred from
the presence of an open handle.

The v0.6.1 systemd user service was hardware-validated to start successfully
and preserve ordinary wired USB cursor/button operation while holding the C658
interfaces. Automatic path replacement after a live USB disconnect/reconnect
remains pending as a distinct lifecycle test.

## 8. Implementation-oriented conclusions

An initial Linux implementation may safely include:

- descriptor-based C658 Report `0x10` target discovery;
- C652 paired-device selection using the hardware-confirmed `0x08/0x59` test;
- complete 31-byte blob construction;
- DPI, wheel mode, polling divider and seven button mappings;
- named direct actions `0x0a..0x0e`;
- code `0x0f` only with an explicitly unknown/experimental label;
- host-routed `0x28+N` support after Report `0x03` end-to-end validation;
- receiver pairing after management-sequence validation;
- restore, audit log and bounded resend safeguards.

It should not initially expose:

- named Direct Actions for `0x10..0x27`;
- C658 Lift Detection as a verified UI-supported feature;
- Report `0x42`, `0x50` flags or `0x60` fields as required controls;
- configuration readback or factory-default recovery;
- DFU or arbitrary Feature Report writes.

## 9. Source artifacts

Static-analysis artifacts:

- `STATIC_ANALYSIS_REPORT.md`
- `direct_action_table.csv`
- `report10_fields.csv`
- `evidence_ledger.md`
- `investigation_classification.md`

Principal Linux observations:

- `direct-action-probe-20260922T101508Z.json`
- `direct-action-independent-20260922T134730Z.json`
- `direct-action-independent-20260922T140202Z.json`
- read-only descriptor and feature-report capture archives

Operational and environmental observations that are not part of the protocol
specification are deliberately separated into `EXPERIMENT_NOTES.md`.
