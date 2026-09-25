# direct code 6 の前後対照監査

[公開監査](c652-mi02-direct6-1.json)は、Receiver C652 MI_02でradialボタン（slot 7）の既知direct mapping `0x0c`、code 6のwire `0x0f`、既知mapping `0x0c`を順に送った1回の限定試験である。Report `0x10`を宣言する対象とraw入力は同じhidraw interfaceで、descriptor SHA-256は `8e31d4b6f8e0c5eb5ff01617d202f8f29421f514fd05a187a2ca3c777aea9efc`。各Reportは32 byteで、変更したのはslot 7のmapping byteだけである。

復元先は所有者が指定した完全32-byte値で、SHA-256は `261e11e9a07afda732660b9ddbfb6529b6d6f61a1320199eb02d95549dfe3c28`。これはSDKの実験用fixtureと一致するが、実機からreadbackした元設定やfactory defaultではない。試験終了時に同じ値を再送した。監査の `baseline_restored` はhost送信を、`baseline_operation_confirmed` は選択ボタンの動作を示す。全設定byteのdevice側readbackは行っていない。

| 区間 | mapping byte | host ioctl | 移動Report | evdev押下・解放 | raw Report `0x1b` button byte |
| --- | --- | ---: | --- | --- | --- |
| 既知mapping・前 | `0x0c` | 32 | 観測 | `BTN_MIDDLE` 各12件 | `0x04` を12件 |
| code 6 | `0x0f` | 32 | 観測 | `BTN_FORWARD` 各11件 | `0x20` を11件 |
| 既知mapping・後 | `0x0c` | 32 | 観測 | `BTN_MIDDLE` 各10件 | `0x04` を11件 |

試験者は3区間で表示されたradialボタンの操作回数と、終了後に元の動作へ戻ったことを確認した。raw frameの件数は物理操作回数と常に一対一とは限らないため、表の前後対照の合格判定はevdevの押下・解放各10件以上に基づく。code 6区間にReport `0x03`は出ていない。転送機会の指標はmotion-bearing Report `0x1b`であり、device内部の適用時刻の証明ではない。

この条件ではcode 6設定後に `BTN_FORWARD` が観測され、直前の既知mapping `0x0c`の残留だけでは説明できない。正式名称、他の個体・経路での効果、永続性は未検証である。Linuxのevent名を純正action名として扱わない。

監査は通常ユーザーで実行し、sudoは使用していない。使用したzipappのSHA-256は `2f413bed51ea8ff52e4bc5c8147f1d465e4e7b0ab37905b2570cb1367e5ed88d`。監査の `tool_git_commit` は実行時のHEADであり、追加した対照試験コードは実行時に未commitだったため、その値だけでは実行ソースを特定できない。公開監査には個体識別子やホームディレクトリを含めていない。

`python3 tools/validate_public.py evidence/direct6-controlled-2026-09/c652-mi02-direct6-1.json` で公開内容と監査内部の整合性を検査できる。
