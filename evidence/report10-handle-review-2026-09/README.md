# Report `0x10` 対象handleと効果の監査

## 既存監査の再評価

既存の[有線成功監査](../report03-core-matrix-2026-09/report03-wired_1.json)と[Receiver成功監査](../report03-core-matrix-2026-09/report03-wireless_1.json)を、後日の[interface・descriptor監査](../read-paths-2026-09/README.md)と照合した。この再評価には追加の実機操作はない。

| 経路 | 既存監査の送信先 | descriptor SHA-256の一致先 | 結果 |
| --- | --- | --- | --- |
| 有線 C658 | 監査中のReport `0x10` target | C658 MI_01（`6b205bb223c7adaccb757021ac7f1c90eef8a4d9cd6cbc0ee9e59d09f967d0eb`） | 17/17 phase PASS |
| Receiver C652 | 監査中のReport `0x10` target | C652 MI_02（`8e31d4b6f8e0c5eb5ff01617d202f8f29421f514fd05a187a2ca3c777aea9efc`） | 17/17 phase PASS |

両監査の `baseline_source` は `provided-host-snapshot` だが、記録されたbaseline値はSDKの `latest_software_baseline()` と完全一致する。したがって所有者の元設定を保存した値とは確認できない。各phaseの送信Reportは32 byte、先頭は`0x10`で、baselineとの差分はボタンmappingの1 byteだけだった。送信後にphase記録へ進んだため、hostの `set_feature` 呼び出しは例外なく戻ったと分かる。ただしioctlの数値戻り値と送信時刻は監査に保存されていない。

転送機会は各17 phaseの `transfer_wait_completed=true` とmotion-bearing raw Report `0x1b` で記録された。15のpositive phaseでは物理操作時に期待するraw Report `0x03` の押下・解放を各条件10回以上記録し、2つのnegative controlでは対象Report `0x03`を観測しなかった。全17 phaseがPASSした。ここで確認した効果は試験したhandle・snapshot・操作条件に限る。

最後に実験用fixtureと同じbaselineを再送し、転送待ちが完了した。有線ではevdevの指定ボタン押下・解放10組、Receiverでは31組を記録し、両監査とも `baseline_operation_confirmed=true`。これは確認したボタン動作への復帰を示す。所有者の元設定への復元、全設定byteの永続復元、readbackでの同一性は確認していない。

Linuxで試験した各handleの結果は、純正Windows brokerが同じhandleを選ぶか、複数handleへ送るかを示さない。両監査の送信先descriptor hashと後日のdescriptor hashが一致することはinterface対応の根拠だが、同一個体・同一接続時刻の証明ではない。

## Receiver C652 MI_02 の限定試験

[公開監査](c652-mi02-handle-1.json)は、所有者が明示的に復元先として指定した完全32-byte値を入力にした1 phaseの記録。指定値はSDKの実験用fixtureと一致するが、マウスから読み取った工場出荷値や元設定のsnapshotではない。Report `0x10`を宣言するC652 MI_02のdescriptor SHA-256は上表のReceiver側と一致した。radialボタンのbyte 25を`0x0c`から`0x29`へ変え、他のbyteは保持した。

| 判定対象 | 監査で確認した結果 |
| --- | --- |
| 変更Reportの送信 | 送信開始・終了時刻とhost ioctl戻り値32を記録 |
| 転送機会 | マウス移動によるraw Report `0x1b`を記録し、待機完了 |
| 変更後の物理操作 | radialボタンのraw Report `0x03`押下・解放を各10回、phase PASS |
| 指定値の再送 | 復元の送信開始・終了時刻とhost ioctl戻り値32を記録 |
| 復元後の物理操作 | 転送待ち完了後、radialボタンの元のevdev入力を押下・解放各10回 |

監査の `success=true` は、送信、転送機会、変更後入力、復元後入力という条件に対する結果。全設定byteのreadback、永続復元、純正Windows brokerのhandle選択は検証していない。監査の `tool_git_commit` は実行時のHEADを表す。この限定試験用profileは実行時には未commitだったため、その値だけでは使用したツールのソース全体を特定できない。

原本と公開監査のSHA-256はともに `a0a22bc2500af6f035a778abd15c17b9da4a257df89b1d0fdc3efcf5c1413f8a`。原本はGit除外領域に保管し、公開前に個人パスと既知のReceiver ID形式を検査した。置換対象の個体IDは検出されず、公開監査は原本と同一。`python3 tools/validate_public.py evidence/report10-handle-review-2026-09/c652-mi02-handle-1.json` で監査の形式と記録内部の整合性を検証できる。
