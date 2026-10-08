# Report `0x17` のdescriptor宣言とLinux power_supplyの限定観測

Report `0x17` の各fieldがdescriptorでどう宣言されているかを静的に確認し、Linuxがそれを電池として登録しているかを読み取り専用で確認した記録。調査の契機は、第三者のLinux実装 cadMousePro（GPLv3、<https://mouse.globalcode.info/v_0/cadMousePro.xhtml>）がCadMouse Pro Wirelessの電池残量をUPower経由で表示していると紹介ページに記載していたこと。cadMousePro のソースは参照しておらず、以下の主張の根拠にもしていない。

## 1. descriptorの静的確認

対象は[SDKテスト用の実機descriptor fixture](../../sdk/python/tests/data/real_hid_descriptors.json)の `c652_receiver_mi02`（SHA-256 `8e31d4b6f8e0c5eb5ff01617d202f8f29421f514fd05a187a2ca3c777aea9efc`）と `c658_wired_mi01`（SHA-256 `6b205bb223c7adaccb757021ac7f1c90eef8a4d9cd6cbc0ee9e59d09f967d0eb`）。両者のReport `0x17` 部分は同じitem列だった（前者はdescriptor offset 108、後者はoffset 30から始まる `c0` の直後）。

```text
a1 02        Collection (Logical)
85 17        Report ID 0x17
15 00        Logical Minimum 0
25 64        Logical Maximum 100
55 00        Unit Exponent 0
65 00        Unit None
05 06        Usage Page 0x06 (Generic Device Controls)
09 20        Usage 0x20 (Battery Strength)
75 08 95 01  Report Size 8, Report Count 1
81 02        Input (Data, Variable, Absolute)
15 00        Logical Minimum 0
25 01        Logical Maximum 1
06 00 ff     Usage Page 0xff00 (vendor)
09 27        Usage 0x27
75 01 95 01  Report Size 1, Report Count 1
81 02        Input (Data, Variable, Absolute)
```

この後に7 bitのConstant Inputが続き、Input Report `0x17` は3 byte（Report ID、8 bit、1 bit + padding）になる。Usage名はHID Usage Tablesの名称で、descriptorにString itemはない。

- byte 1はUsage Battery Strength、Logical範囲0..100として宣言されている。
- byte 2のbit 0はvendor Usage `0xff00:0x27`、Logical範囲0..1として宣言されている。descriptorからは意味を決められない。
- Bluetooth（BLE）接続時の設定node候補も3 byteの `0x17` Inputを宣言していたと、利用者側の解析が報告している。そのdescriptorは本リポジトリに収録しておらず、本監査では確認していない。

descriptorの宣言はdeviceがそう名乗っていることを示すだけで、送られる値の意味を保証しない。

## 2. Linux power_supplyの読み取り（2026-10-07）

利用者がReceiver C652経由で接続した状態で、sysfsを読み取り、結果を本文として転記した。hidrawの読み書き、設定・結合状態の書き込みは行っていない。画面やファイルとしての原本はない。

| 確認 | 結果 |
| --- | --- |
| `/sys/class/power_supply/` | `hid-0003:256F:C652.<HID instance>-battery` が存在（他に別機器の電池が1件） |
| 親のHID device | C652 USB interface 3（MI_03）。USB topologyとHID instance番号は公開しない |
| `type` / `scope` | `Battery` / `Device` |
| `present` / `online` | `1` / `1` |
| `capacity` | `70` |
| `status` | `Discharging` |
| `model_name` | `3Dconnexion 3Dconnexion Universal Receiver` |
| `capacity_level`、`manufacturer` | 属性なし |
| `upower -d` | この電池は列挙されず、別機器の電池と `DisplayDevice` だけ |

利用者は、`capacity` の `70` が同じマウスのBluetooth電池表示と同じ値だったと報告した。表示の時刻と画面は記録していない。`serial_number` 属性は読んでいない。

## 3. 限界

- MI_03のこの時点のdescriptor SHA-256は取得していない。MI_03を設定nodeとした過去の監査（[98%・100%限定比較](../report17-battery-2026-09/README.md)など）では `8e31d4b6…` だった。
- `capacity` は1点だけで、Report `0x17` のraw frameを同時に取得していない。kernelがbyte 1をそのまま `capacity` にしたことは、Linuxの一般的なBattery Strength処理からの推定である。
- `status=Discharging` は、kernelがvendor bitを使わず残量だけから決めた値と考えられる（推定）。充電状態の判定には使えない。
- UPowerが列挙しない理由は確認していない。
- 有線C658 MI_01も同じ宣言を持つ。有線経路のraw Report `0x17` は[有線matrix監査](../report03-core-matrix-2026-09/report03-wired_1.json)に記録があるが、有線接続時のpower_supplyは確認していない。Bluetooth（BLE）接続時のpower_supplyも確認していない。
