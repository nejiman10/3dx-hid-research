# C658/C652 Linux Protocol Research

Unofficial, evidence-bounded research and reference SDK for the 3Dconnexion
CadMouse Compact Wireless (`256f:c658`) and Universal Receiver (`256f:c652`).
This project is not affiliated with or endorsed by 3Dconnexion.

Research Baseline 1 covers normal USB/HID configuration, Report `0x10`, direct
and host-routed buttons, Input Report `0x03`, Receiver slots, pairing/unpairing,
and the Linux wired-hidraw lifetime workaround. Firmware update, DFU, radio
packets and cryptography are out of scope.

## Normative sources

When files disagree, use this order:

1. `docs/TECHNICAL_SPEC.md` — normative protocol behaviour.
2. `spec/KNOWN_VALUES.json` — normative machine-readable constants.
3. `spec/EVIDENCE_STATUS.csv` — confidence and evidence boundary.
4. `sdk/python/tests/` — executable conformance vectors.
5. `evidence/public/` — anonymized hardware observations.
6. `docs/STATIC_ANALYSIS_REPORT.md` — static-analysis evidence.
7. `sdk/python/src/` — reference implementation, not an independent truth.

New evidence changes the specification first. An implementation discrepancy
without new evidence changes the code. Unresolved meanings remain explicitly
`UNKNOWN`.

## Reproduce validation

Requirements: Linux, Python 3.10 or later, POSIX shell, GNU tar, gzip and
`systemd-analyze` when systemd unit verification is desired.

```bash
./tools/run-tests.sh
```

The command uses only Python's standard library, validates every public JSON
and CSV file, checks the anonymization boundary, runs 43 SDK unit tests, builds
the zipapp twice and compares the bytes, verifies shell syntax, and verifies
the systemd unit when `systemd-analyze` is available.

Build the deterministic public archive:

```bash
./tools/build-release.sh
```

## Privacy

Hardware identifiers are replaced with visibly marked tokens such as
`<ANONYMIZED:DEVICE_ID_A:6_BYTES>`. See
`evidence/ANONYMIZATION_REPORT.md`, `evidence/public/manifest.json`, and
`spec/ANONYMIZATION_MANIFEST.json`. Original audit files are deliberately not
part of the repository or release archive.

## Safety

Pairing and unpairing packets alter Receiver state. They remain behind explicit
experimental commit flags, exact slot snapshots and confirmations. A successful
HID ioctl is not treated as proof that a wireless mouse applied a setting.

