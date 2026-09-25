# Linux読み取り経路の監査（2026-09-25）

この文書は、同日取得した非公開原本のうち、個体識別子を含まない結果だけを示す。原本はGit追跡対象外の `evidence/source-private-not-in-repository/read-paths-2026-09-25/` に保管する。以下は試験したLinux経路の観測であり、Windows純正ソフトの呼び出し経路や各fieldの正式意味を示さない。GETは各経路1回、追加試行なし。設定書き込みとpair/unpairは行っていない。

| 原本 | USB interface | descriptorの主な宣言 | GET結果 |
| --- | --- | --- | --- |
| `c652-interface0-1.json` | C652 MI_00 | Feature `0x43..0x47`、`0x50`、`0x60` は各8 byte。Input宣言なし | 7件すべて8-byte応答、Report ID一致 |
| `c652-interface2-1.json` | C652 MI_02 | Feature `0x08` は8 byte、`0x10` は32 byte、`0x43..0x47`・`0x50`・`0x60` は各8 byte。Input `0x03` は2 byte | GET `0x08` を含む8件すべて8-byte応答、Report ID一致 |
| `c658-interface0-1.json` | C658 MI_00 | Input `0x1b` は9 byte。対象Feature宣言なし | GET未実施 |
| `c658-interface1-1.json` | C658 MI_01 | Feature `0x08` は8 byte、`0x10` は32 byte。Input `0x03` は2 byte | この計画ではGET未実施 |

descriptorのSHA-256とtop-level Usage（`page:usage`）:

| USB interface | descriptor SHA-256 | Usage |
| --- | --- | --- |
| C652 MI_00 | `f3c1a890e7ac8c9345048389a50023cfd3d5fc522ef8110ecdf9daafa94c78e3` | `ff0a:0001` |
| C652 MI_02 | `8e31d4b6f8e0c5eb5ff01617d202f8f29421f514fd05a187a2ca3c777aea9efc` | `0001:0002`、`ff08:0001`、`ff0a:0001` |
| C658 MI_00 | `abd0fccf61bba84ac67aab1fdc65ca79ab2af86f70a864bc4c60360aa2ce1868` | `0001:0002` |
| C658 MI_01 | `6b205bb223c7adaccb757021ac7f1c90eef8a4d9cd6cbc0ee9e59d09f967d0eb` | `ff08:0001` |

C652 MI_02のGET `0x08`応答のbyte 1は`0x59`。C652の両interfaceでGET `0x43..0x47`応答のbyte 1は順に`00 00 59 00 00`で、7件の共通GET応答は両interface間で一致した。これは物理入力取得より前のsnapshotである。GET `0x50` / `0x60` はLinuxで応答を得たが、値の意味とWindows UIからの到達性は未検証。応答の識別子候補byteは公開しない。

`c652-physical-input-1.txt` はC652のevdev nodeに対する`evtest`を記録したが、デバイス情報の後に押下・解放の`Event:`行がない。利用者は、この時マウスをBluetooth接続で使用していたと報告した。これは無入力と整合するが、ログ自体はBluetooth接続を証明しない。

その後の `c652-physical-input-2.txt` はUSB bus `0x03`、VID:PID `256f:c652`、`Universal Receiver Mouse` と表示されたevdev nodeで、08:20:45～08:21:05 UTCに`BTN_LEFT` の押下・解放8組と `BTN_RIGHT` の押下・解放1組を記録した。08:27:00 UTCの読み取り専用snapshot `c652-slots-after-input.json` では5 slot中slot 2（Report `0x45`）だけが占有され、device-type候補byteは`0x59`だった。単一占有slotという条件と利用者のReceiver接続報告から、この入力はslot 2の接続個体に対応すると推定できる。ただしevdev event自体にslot IDはなく、個体IDを入力frameから直接照合したわけではない。入力node番号は再列挙で変わり得る。

## 主張ごとの判定

- Linuxで観測: C652 MI_02のGET `0x08`応答、MI_00とMI_02のGET `0x43..0x47`・`0x50`・`0x60`応答、単一占有slotとReceiver入力。
- この条件で未観測: GET失敗、複数slot占有時の入力対応。
- 未試験: C652 MI_01・MI_03・MI_04でのGET、slot `0..4` とMI `0..4`の一般対応、C658有線経路でのGET。
- Windows側の到達性は未検証: 純正broker / UIがGET `0x08`・`0x50`・`0x60`を実行したかどうか。

原本SHA-256（原本の内容は非公開）:

| 原本 | SHA-256 |
| --- | --- |
| `c652-interface0-1.json` | `aa5968b236bad6f96a93ed8e9b3775da9de1478cd7ee43c821631722932fd6e6` |
| `c652-interface2-1.json` | `025e894d6894ef522888433a988785f1b47564dfa8dd40231c8548db164ac626` |
| `c658-interface0-1.json` | `63979ca3284ce741d7e6fc528fec6896b743172da593c66e83560399e8297b97` |
| `c658-interface1-1.json` | `3f096fc7a3bc0648af4b7db110dd463edfd33e19455a4c231fb241df077613b4` |
| `c652-physical-input-1.txt` | `75103a18c9f877bace62fe47c4caa537e010ea6947c8098e27b33ae934f2c346` |
| `c652-physical-input-2.txt` | `c1f5534515c8eb3a207130a290c21bc8b3c50cade386deee139199db9c4968d9` |
| `c652-slots-after-input.json` | `47f1e902368467b7ecafed5cf9f710a95bcfe5eaeac8c1f1ee3851b7018045fb` |
