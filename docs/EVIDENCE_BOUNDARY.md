# Evidence boundary

Implementation snapshot: 2026-09-22

Primary inputs:

- `TECHNICAL_SPEC.md`
- `KNOWN_VALUES.json`
- `EVIDENCE_STATUS.csv`
- `STATIC_ANALYSIS_REPORT.md`
- Independent MSI SHA-256:
  `799a1f3f2c4effc5113a9838f26fa6386b470a24a3ab29330a474a0e7f6b5e99`

## Implemented as confirmed encoding

- A complete zero-initialized 31-byte blob
- DPI at blob offset 1
- effective lift threshold at blob offset 2
- wheel constants at offsets 3..6
- seven button mappings at offsets 18..24
- fixed `0x1e` at offset 26
- polling divider at offset 30
- direct encoding `0x09 + action_code`
- host-routed encoding `0x28 + action_index`

## Explicit uncertainty retained

- Direct code 6 / wire `0x0f` is reachable from C658 default initialization,
  but its formal enum name is unknown. The public name is
  `UNKNOWN_DIRECT_CODE_6`.
- Direct wire `0x10..0x27` has no reachable C658 producer in the analysed
  normal UI/profile path. It is inspection-only and cannot be encoded through
  the supported API.
- Lift Detection's generic generator field is implemented, but C658 SmartUI
  does not expose the control. Its physical effect on C658 remains unverified.
- C652 `GET 0x08`, byte 1 `0x59` is a Linux hardware-observed discovery rule;
  it is not attributed to the independently recovered normal DLL call path.
- A successful Feature Report ioctl is not proof of wireless application.
- The CLI therefore requires a matching Linux `EV_KEY` press for each phase of
  the controlled direct-action probe and verifies baseline restoration.
- The 31-byte blob generator is statically confirmed. The final broker/kernel
  Report-ID prefix path has lower static confidence, while the 32-byte Linux
  transfer format is hardware-supported by the prior tests.

## Deliberately excluded

- Direct names or supported encoders for wire `0x10..0x27`
- arbitrary Feature Report writes
- configuration/factory-default readback
- unpairing
- DFU, firmware update, radio packets and cryptography

## Experimental prior-static implementation

Pairing start `41 02 02 00 00` and stop `41 02 00 00 00` are implemented only
behind `--commit-experimental-pairing`. These complete packets came from the
earlier integrated static analysis and were not reproduced by the independent
MSI-only pass. Slot `GET 0x43..0x47` is independently static-confirmed; the
8-byte device-type/serial interpretation remains prior-static and raw bytes are
always retained.

Report `0x17` observations currently correlate `17 64 01` with an actively
charging indicator and `17 64 00` with receiver use or USB charge completion.
The second data byte is recorded only as `UNKNOWN_CHARGING_STATE_CANDIDATE`;
neither data field has a confirmed formal name.

Wired matrix hardware evidence confirms that Report `0x03` bitmap semantics
follow the host-routed action index rather than the physical button-table slot:
host index 1 (`0x29`) produced bitmap `0x01`, and host index 2 (`0x2a`)
produced bitmap `0x02`, each for ten press/release cycles. Host index 0
(`0x28`) produced no Report `0x03` in that run. Index 7 (`0x2f`) later
produced bitmap `0x40`; indices 3..6 remain pending.

Receiver matrix observation showed one stale old-mapping event immediately
after several writes (for example old `03 02` before new `03 40`, and one
ordinary button event before nine host-routed cycles). This supports a
receiver-to-mouse application delay. A fixed two-second delay was not always
sufficient. The CLI therefore asks for mouse movement and automatically waits
for a motion-bearing Report `0x1b`, then uses a configurable settle interval
and finishes positive phases only after the expected input count is observed.
This policy does not claim an exact firmware latency.
