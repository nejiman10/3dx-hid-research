# Python research SDK

This package builds complete C658 Report `0x10` snapshots and provides guarded hardware probes. The sole human-readable specification is [SPEC.md](../../SPEC.md); experimental procedures are in [HARDWARE_TEST.md](../../HARDWARE_TEST.md).

## Build and inspect the command line tool

Requires Linux and Python 3.10 or later. The package has no third-party runtime dependencies. From the repository root, build the executable zipapp and inspect its available commands:

```bash
python3 tools/build_zipapp.py --source sdk/python/src --output /tmp/c658-report10ctl.pyz
python3 /tmp/c658-report10ctl.pyz --help
```

Read [HARDWARE_TEST.md](../../HARDWARE_TEST.md) before using commands that write device settings or change Receiver pairing.

`Report10Config.latest_software_baseline()` builds a test starting configuration from statically analyzed byte meanings. It is not a saved device setting or factory default and can overwrite user settings. Save the owner's configuration before any write. `UNKNOWN_DIRECT_CODE_6` has no fixed hardware event expectation.

`audit-read-paths --device /dev/hidrawN --audit evidence/source-private-not-in-repository/read-paths/audit.json` records one node's descriptor, interface and bounded receiver GET results. Add `--report10-readback` to limit the requests to GET `0x10` on a USB interface declaring the 32-byte Feature report, with GET `0x08` as a control on C652. The C652 candidate response must match the observed `08 59` prefix before GET `0x10`; interface numbers are recorded at runtime. Create the private audit directory before running it. The JSON can contain device identifiers and raw response bytes; review it before publication.

From the repository root, `python3 tools/audit_hold_open.py preflight` checks the wired C658 interfaces and standard-user access without opening hidraw. The interactive `run` subcommand is a research comparison that temporarily stops the user service. The practical-use result is recorded in [the hold-open evidence](../../evidence/hold-open-2026-09/README.md); its procedure remains in [HARDWARE_TEST.md](../../HARDWARE_TEST.md#有線c658の継続利用確認手順).
