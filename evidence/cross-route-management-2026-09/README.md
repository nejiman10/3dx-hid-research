# 同時接続時の設定送信と管理interfaceの限定監査

2026-09-27 10:41～11:05 JST、C658のUSBケーブルとC652 ReceiverをPCに挿したまま、利用者がマウスの有線・Receiverモードを切り替えて経路間の設定効果とReceiverの管理interfaceを調べた。各段階でsysfsのUSB interface、VID:PID、descriptor、Report宣言を再同定した。C658は有線モードでMI_00・MI_01として列挙され、ReceiverモードではC658 nodeが列挙されなかった。C652はMI_00..MI_04として残った。入力は各20秒のraw HIDとevdevで記録した。表中の押下回数には同数の解放が伴う。各非公開原本のSHA-256は[source-hashes.txt](source-hashes.txt)に記す。原本には識別子候補・ローカルnode・raw frameが含まれるため、Git除外領域の `evidence/source-private-not-in-repository/cross-route-management-2026-09-27/` に保持し、ここには実値を掲載しない。

`BTN_FORWARD`（Linux EV_KEY 277）と`BTN_MIDDLE`（274）はLinuxが出したイベント名であり、アプリ上の操作結果を示す名前ではない。利用者は、開始前と最終状態のradialボタンは「進む」動作をせず、ミドルスイッチを押したときと同じ動作だと報告した。開始前・最終状態のradial押下ではraw Report `0x1b`のbutton byte `0x20`とEV_KEY 277、保存済み値を送ってEV_KEY 274となった観測では同byte `0x04`を記録した。Report `0x10`の送信hex、raw入力、Linuxイベント、利用者が確認した操作結果を別々に扱う。開始前と最終状態のReport `0x10`設定byteは読み戻せていない。

最初の有線入力preflightは収集側がMI_01だけを開き、移動と通常ボタンを出すMI_00を開かなかったため入力0件だった。収集先をMI_00・MI_01と対応eventへ修正した次の20秒窓では、移動とradialのEV_KEY 277を25組記録した。初回の空結果はデバイスの無入力の根拠には使わない。

## 一方のReport `0x10`送信が他方の入力に現れるか

復元先は所有者が過去に指定した32-byte値（SHA-256 `261e11e9a07afda732660b9ddbfb6529b6d6f61a1320199eb02d95549dfe3c28`）を使用した。この値はSDKの実験用設定と一致し、実機から読み戻した現在設定ではない。開始前のradialは有線・ReceiverともLinux上で`BTN_FORWARD`と記録されたが、復元先のradial設定byteは中ボタンを指定する `0x0c`。利用者は、この値への変更を承知して実施を指示した。試験Reportは復元先の32 byteからradialのwire byte 25だけを `0x29`（host index 1）へ変えた。各Report `0x10`送信のioctl戻り値は32。送信完了、送信後の移動による転送機会、物理入力を別々に記録した。

| 段階 | 送信先と操作 | 観測 |
| --- | --- | --- |
| 事前 | Receiver、有線でradial入力 | それぞれ `BTN_FORWARD` 15組、25組 |
| 有線→Receiver | C658 MI_01へ試験Report `0x10` | 有線側で移動とReport `0x03` bitmap `0x01`の押下・解放20組。Receiverへ切り替えた後は移動と `BTN_FORWARD` 20組で、試験値の効果は現れなかった |
| 有線側復元 | C658 MI_01へ保存済み値 | 有線側で移動と `BTN_MIDDLE` 20組 |
| Receiver初回 | C652 MI_03へ試験Report | Receiver側で移動と `BTN_FORWARD` 20組。物理適用は確認できなかった。有線へ切り替えた後は `BTN_MIDDLE` 20組 |
| Receiver復元 | C652 MI_03へ保存済み値 | Receiver側で移動と `BTN_MIDDLE` 20組 |
| Receiver追加1回 | 復元値を出発点に、C652 MI_03へ同じ試験Report | Receiver側で移動とReport `0x03` bitmap `0x01`の押下・解放20組。有線へ切り替えた後は `BTN_MIDDLE` 20組で、試験値の効果は現れなかった |
| Receiver側復元 | C652 MI_03へ保存済み値 | Receiver側で移動と `BTN_MIDDLE` 19組 |

送信した経路で試験値によるReport `0x03`入力を確認した後、モードを切り替えたもう一方の入力には同じReport `0x03`を観測しなかった。一方、後述の管理命令監査後に、保存済み値の送信後に見たLinuxイベント`BTN_MIDDLE`がモード切り替え後に`BTN_FORWARD`へ戻ることも観測した。従って、今回の切り替えを伴う方法だけでは、設定の非伝播と切り替え時の再適用・初期化などを区別できず、経路間の設定伝播は判定不能である。Receiver初回送信の物理適用が見えなかった原因も未決定である。

## Receiver MI_02の管理命令

[先行結合監査](../receiver-repair-2026-09/README.md)では管理nodeへの解除・再ペアリング後にslot変化と物理入力を確認している。そのnodeは同日の早い時点の[読み取り経路監査](../read-paths-2026-09/README.md)でMI_00と同定されたnodeと同じだが、各write時点のinterface番号は原本にない。先行するdescriptor監査でReceiverの全5 interfaceがFeature `0x41`を5 byteで宣言したため、MI_02で1サイクルを試した。着手直前のMI_02 descriptor SHA-256は `f3c1a890e7ac8c9345048389a50023cfd3d5fc522ef8110ecdf9daafa94c78e3`。5 slot GETはslot 3だけbyte 1が `0x59` で、解除前のReceiver入力も確認済み。利用者は解除・再ペアリングを指示し、マウス側のペアリング操作を行った。

| 操作 | host結果 | 独立した観測 |
| --- | --- | --- |
| MI_02へ解除 `41 04 03 00 00` | ioctlは `EPIPE`（errno 32） | 後続GETでslot 3が空になった。`EPIPE`だけを成功根拠にしない |
| MI_02へ開始 `41 02 02 00 00`、停止 `41 02 00 00 00` | 各ioctl戻り値5 | slot 4が新たに占有され、停止命令もMI_02へ送れた |
| 再接続後 | C652の設定候補はMI_04へ移動 | MI_04で移動とradialの `BTN_FORWARD` 10組を確認した |

今回の個体ではMI_02からの解除・開始・停止がslot変化と入力復旧につながった。先行監査のMI_00への対応は状況証拠にとどまるため、MI_00とMI_02の両方が効くという厳密な比較は未完了である。全interface、他個体、全slotでの有効性も未試験である。

再ペアリング後、保存済み値を新しいC652 MI_04へ1回送った時点ではLinuxイベントは `BTN_FORWARD` 10組のままで、同じ値の2回目の送信後に `BTN_MIDDLE` 10組となった。有線側も再ペアリング後に `BTN_FORWARD` 10組となり、保存済み値の送信後には `BTN_MIDDLE` 10組となった。最後にReceiverへ切り替えた後は再び `BTN_FORWARD` 10組だった。これらはraw入力とLinuxイベントの観測であり、32-byte設定全体のreadbackや永続復元を示さない。利用者は最終的に試験開始前と同じ操作結果（ミドルスイッチを押したときと同じ動作）を希望し、現在のReceiverモードでそれを報告したため、追加送信は行っていない。

## 効果が見えなかった送信の送信先を再点検

非公開原本は冒頭に示した `cross-route-management-2026-09-27/` にある。依頼時に指定された `todo12-2026-09-27/` は存在しないため、前者の同日監査と同じ非公開領域に保存された送信スクリプトを照合した。ここにはnode番号と識別子の実値を載せない。

| 事例 | 送信時の記録と前後の対応 | 判定 |
| --- | --- | --- |
| Receiver初回 | 試験値の書き込み監査はC652 MI_03、期待した設定候補descriptor hash、ioctl戻り値32を記録した。直前のReceiver入力監査と直後の入力監査は、書き込み監査と同じhidraw pathを使用した | 記録上はMI_03に送信。別MIへの誤送信を示す記録はないが、効果が見えなかった原因は判定不能 |
| slot 4への再ペアリング後の1回目 | pair監査はslot 4占有を記録し、pair後の入力監査は新しいC652 MI_04のhidraw pathを使用した。1回目と2回目の書き込み監査はいずれもそのpath、MI_04、期待した設定候補descriptor hash、ioctl戻り値32を記録し、後続の入力監査も同じpathを使用した | 再列挙前の旧nodeや別MIへ送ったという記録はない。効果が2回目まで見えなかった原因は判定不能 |

保存された送信スクリプトは毎回、該当Report宣言を持つ候補が一意であることとdescriptor hashを確認し、Receiver候補でGET `0x08`の長さ・Report ID・byte 1が `0x59` であること、およびbytes 2..7が唯一の占有slotの候補値と一致することを検査する。書き込み監査が生成されていることは、その選択処理が例外なく終わったことと整合する。ただし監査JSONにはGET `0x08`応答、照合結果、実施時刻が保存されず、GETとSETは別のfdで行われた。各書き込み直前の同一fdでの照合成功までは原本から検証できない。descriptor hashは書き込み前の選択時に取得したもので、直後の入力監査にはdescriptor hashがない。送信先取り違えの積極的な根拠はないが、送信から物理適用までの原因を特定する証拠もない。
