# TODO 11: 接続識別子とinterfaceの読み取り監査

2026-09-27 09:32:35 JST、有線C658とC652 Receiverを同時にUSB接続した状態で1回の限定監査を行った。利用者は両方を接続したと申告した。Linux sysfsで各USB interfaceを再同定し、descriptorを取得した。各nodeの`udevadm info`とUSB親deviceのsysfs `serial`を確認した。GETはdescriptorで宣言されたReportだけに送り、設定SETとpair/unpairは行っていない。全7 nodeの読み取りは約0.5秒で終了した。識別子の実値、ホスト固有path、raw応答を含む原本はGit除外の `evidence/source-private-not-in-repository/todo11-2026-09-27/attempt-1.json` に保管する（SHA-256 `c8a8c6beba7e0623809b43f4306c9b4b0e7b2039e8baf4c71d525b31b95d5084`）。

| 経路 | interface | descriptor SHA-256 | 主なFeature宣言 | 読み取り結果 |
| --- | --- | --- | --- | --- |
| Receiver C652 | MI_00 | `f3c1a890e7ac8c9345048389a50023cfd3d5fc522ef8110ecdf9daafa94c78e3` | `0x41` 5 byte、slot `0x43..0x47` 各8 byte | slot GET 5件成功 |
| Receiver C652 | MI_01 | 同上 | 同上 | slot GET 5件成功 |
| Receiver C652 | MI_02 | 同上 | 同上 | slot GET 5件成功 |
| Receiver C652 | MI_03 | `8e31d4b6f8e0c5eb5ff01617d202f8f29421f514fd05a187a2ca3c777aea9efc` | 上記に加えて `0x08` 8 byte、`0x10` 32 byte | slot GET 5件とGET `0x08` 成功 |
| Receiver C652 | MI_04 | `f3c1a890e7ac8c9345048389a50023cfd3d5fc522ef8110ecdf9daafa94c78e3` | `0x41` 5 byte、slot `0x43..0x47` 各8 byte | slot GET 5件成功 |
| 有線C658 | MI_00 | `abd0fccf61bba84ac67aab1fdc65ca79ab2af86f70a864bc4c60360aa2ce1868` | 対象Feature宣言なし | GET未実施 |
| 有線C658 | MI_01 | `6b205bb223c7adaccb757021ac7f1c90eef8a4d9cd6cbc0ee9e59d09f967d0eb` | `0x08` 8 byte、`0x10` 32 byte | GET `0x08` 成功 |

**R5:** 試験したC658とC652のUSB親deviceではsysfs `serial` fileがなく、各interfaceの`udevadm info`にも `ID_SERIAL`、`ID_SERIAL_SHORT`、`ID_USB_SERIAL_SHORT` がなかった。`udevadm`は全nodeで終了コード0。USB serialの値がないため、抜き差し・別portでの値の安定性は比較できず、実施していない。この観測は試験した2台と接続条件に限る。

**R6:** Receiverの5 interfaceに対するslot GETは各5件とも8 byteでReport IDが一致し、byte 1は全interfaceでslot 3だけ `0x59`、他4 slotは `0x00` だった。C652 MI_03と有線C658 MI_01のGET `0x08`も8 byteでReport IDが一致し、両方のbyte 1は `0x59`。識別子候補bytes 2..7の一致表は次の通り。生値は公開しない。

| 比較 | 結果 |
| --- | --- |
| 占有slot 3 ↔ C652 MI_03 GET `0x08` | 一致 |
| 占有slot 3 ↔ 有線C658 MI_01 GET `0x08` | 一致 |
| C652 MI_03 GET `0x08` ↔ 有線C658 MI_01 GET `0x08` | 一致 |
| USB serial ↔ 上記候補値 | USB serialが取得できず比較不可 |

**R7:** ReceiverのMI_00..MI_04すべてのdescriptorがFeature `0x41`を5 byteで宣言していた。宣言だけでは、管理命令が実際にどのinterfaceで有効かは決まらない。

**R8:** 同時接続下でC652はMI_00..MI_04、有線C658はMI_00..MI_01として列挙された。Report `0x10`を32 byteと宣言する候補は各deviceに1 nodeずつだった。Receiver側C652 MI_03のGET `0x08` byte 1はこの状態でも `0x59`。同時接続中の物理入力と設定の伝播は試験していない。

識別子候補の3者一致は、単一占有slotの今回の構成で、slotと設定候補nodeが同じ機器を指すという説明を支持する。複数機器接続時の一意性、識別子fieldの正式意味、他個体・firmwareへの適用は未確認である。
