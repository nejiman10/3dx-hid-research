# Evidence anonymization report

Original audit files are not distributed. Device-identifier candidates were
replaced with stable, visibly marked tokens. Source hashes allow the holder of
a private original to verify provenance without publishing its identifier.

| Public file | Redactions | Original SHA-256 | Public SHA-256 |
|---|---:|---|---|
| `input-raw-receiver.json` | 0 | `19c7be12d69e8783369c697b1fd8e4cf0c780eab236b1eb1aa9da6d4ae0a2331` | `19c7be12d69e8783369c697b1fd8e4cf0c780eab236b1eb1aa9da6d4ae0a2331` |
| `input-raw-wired.json` | 0 | `acc93bcde2eced709c29494a2c16be96aad0b82fc277cc88d4945bd0ab098540` | `acc93bcde2eced709c29494a2c16be96aad0b82fc277cc88d4945bd0ab098540` |
| `pairing.json` | 4 | `393b13466a8e95dee968d063e87b37bf6d3dd1681aaea85b7bd1b973582c9770` | `fb2d1c7f32422531f244e48c37e3e725f8c820fd9992496afc456c9bb16f8cc5` |
| `receiver-slots.json` | 2 | `8b093084f72fcddd3ce456e81e34e2756e32f2988ed1f4a7b8774a4c4c57e852` | `cf58689ec75dcc3810f7276d73ada23d00056628f057b34cd372a9807396a1ac` |
| `report03-matrix-receiver-2(1).json` | 0 | `229480dfaf3aa7f7fba08e49125d855826d1a734ee2b2dba36a991c1e7644e5e` | `229480dfaf3aa7f7fba08e49125d855826d1a734ee2b2dba36a991c1e7644e5e` |
| `report03-matrix-receiver-2.json` | 0 | `dc64ab821efdbdb876cf7f49203e1a82888a5c47f74e211cf3b2a015d27056e6` | `dc64ab821efdbdb876cf7f49203e1a82888a5c47f74e211cf3b2a015d27056e6` |
| `report03-matrix-wired-2.json` | 0 | `0e467ef30a0912e054f5205afbabc5fe82b9b0debc81094ab55c4c68dd50603c` | `0e467ef30a0912e054f5205afbabc5fe82b9b0debc81094ab55c4c68dd50603c` |
| `report03-matrix-wired-check.json` | 0 | `678a2a0291cb4ececef74368421a50296c62afab820b394b76b538e0d9ac5dcd` | `678a2a0291cb4ececef74368421a50296c62afab820b394b76b538e0d9ac5dcd` |
| `unpair.json` | 5 | `d4b994cac9add0d88d0126af36435f52c56539fcf283ba6bce55e002f95a2cad` | `8ff7ad47d4ffd040c05f3123f29f1df636044659974c1d698959fb08df5b4ce0` |

## Replaced fields

- `pairing.json/snapshots/4/slots/1/serial_raw_hex` → `<ANONYMIZED:DEVICE_ID_A:6_BYTES>`
- `pairing.json/snapshots/4/slots/1/raw_hex` → `44 59 <ANONYMIZED:DEVICE_ID_A:6_BYTES>`
- `pairing.json/new_slots/0/serial_raw_hex` → `<ANONYMIZED:DEVICE_ID_A:6_BYTES>`
- `pairing.json/new_slots/0/raw_hex` → `44 59 <ANONYMIZED:DEVICE_ID_A:6_BYTES>`
- `receiver-slots.json/slots/0/serial_raw_hex` → `<ANONYMIZED:DEVICE_ID_A:6_BYTES>`
- `receiver-slots.json/slots/0/raw_hex` → `43 59 <ANONYMIZED:DEVICE_ID_A:6_BYTES>`
- `unpair.json/target_before/serial_raw_hex` → `<ANONYMIZED:DEVICE_ID_A:6_BYTES>`
- `unpair.json/target_before/raw_hex` → `43 59 <ANONYMIZED:DEVICE_ID_A:6_BYTES>`
- `unpair.json/required_expect_raw` → `43 59 <ANONYMIZED:DEVICE_ID_A:6_BYTES>`
- `unpair.json/before/0/serial_raw_hex` → `<ANONYMIZED:DEVICE_ID_A:6_BYTES>`
- `unpair.json/before/0/raw_hex` → `43 59 <ANONYMIZED:DEVICE_ID_A:6_BYTES>`

## Normative specification copies

The same device identifier was also removed from the public normative copies.
These edits are described in machine-readable form by
`spec/ANONYMIZATION_MANIFEST.json`:

- `spec/KNOWN_VALUES.json/receiver_paired_device_probe/observed_hex`
- `spec/EVIDENCE_STATUS.csv`, record `RX01`, column `source`
- `docs/TECHNICAL_SPEC.md`, Receiver paired-device response example
