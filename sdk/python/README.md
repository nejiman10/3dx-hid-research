# Python research SDK

This package builds complete C658 Report `0x10` snapshots and provides guarded hardware probes. The sole human-readable specification is [SPEC.md](../../SPEC.md); experimental procedures are in [HARDWARE_TEST.md](../../HARDWARE_TEST.md).

`Report10Config.latest_software_baseline()` builds a test starting configuration from statically analyzed byte meanings. It is not a saved device setting or factory default and can overwrite user settings. Save the owner's configuration before any write. `UNKNOWN_DIRECT_CODE_6` has no fixed hardware event expectation.

For [TODO item 7](../../TODO.md#7-linux実機でreceiverの読み取り経路を検証する), `audit-read-paths --device /dev/hidrawN --audit evidence/source-private-not-in-repository/read-paths/audit.json` records one node's descriptor, interface and bounded GET results. Create the private audit directory before running it. The JSON can contain device identifiers; review it before publication.
