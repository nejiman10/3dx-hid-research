# 未完了の作業

このファイルは未完了項目と達成条件の正本です。項目番号は再開時の参照に使うため、並べ替える際も再利用しません。プロトコルの主張と根拠の状態は [SPEC.md](SPEC.md)、実機操作と復元の手順は [HARDWARE_TEST.md](HARDWARE_TEST.md) を参照してください。

実機試験では着手前に目的、区別したい説明、試験条件、反復回数、所要時間を決めます。結果は成功・失敗・判定不能を含めて匿名化した監査として `evidence/` に保存し、検証したうえで `SPEC.md` の該当箇所を更新します。原因を特定できない場合は `UNKNOWN` を維持し、試験条件と限界を記録します。

## 2. direct code 6の効果を調べる

目的: [SPEC.mdのDirect Action](SPEC.md#direct-action) に残るhardware effectの不明点を調べる。

達成条件: 旧mappingの影響を確認できる前後対照を設け、書き込み、転送機会、物理操作、raw HID、evdev、復元後の動作を一体で監査する。観測された効果と判断できない効果を分けて `SPEC.md` に反映する。

## 3. Report `0x17` のbyte候補を比較する

目的: [SPEC.mdのReport 0x17](SPEC.md#report-0x17) にある電池残量・充電状態の仮説を検討する。

達成条件: 独立に確認した異なる電池残量と充電条件で、条件・時刻・raw frameを記録して比較する。値が変わらない場合もその条件を記録する。比較から支持できる範囲と未確定部分を `SPEC.md` に反映する。

## 4. pairingとunpairingの成功監査を取得する

目的: [SPEC.mdのReceiver管理](SPEC.md#receiver管理とlinux実装) にある手動確認結果と管理packet候補を、再検証できる監査で裏づける。

達成条件: 操作ごとに対象handle、操作前後のslot snapshot、送信内容、時刻、API結果、物理入力による確認、失敗や復旧の経過を自己完結した監査に残す。成功の判断は前後のslotと動作の観測に基づけ、失敗記録だけで成功扱いしない。匿名化・検証後に `SPEC.md` を更新する。

## 5. Report `0x10` readbackの失敗条件を調べる

目的: [SPEC.mdのReport 0x10](SPEC.md#report-0x10) にある、現在設定のreadbackと復元方法の不明点を減らす。

達成条件: 有線とReceiverの経路を分け、対象interface、descriptor、要求内容、戻り値またはerrno、試験条件を記録する。成功時は得た値の意味を別途検証し、失敗時は経路・試行条件ごとに失敗を残す。得られない設定値を推測で補わず、`SPEC.md` の根拠状態を更新する。

## 6. hold-openの成立条件を調べる

目的: [SPEC.mdのReceiver管理](SPEC.md#receiver管理とlinux実装) にあるopen flagの不明点を調べる。

達成条件: 比較するflagと観測する動作を事前に定義し、経路ごとのopen結果、動作、失敗を記録する。systemd serviceやudev ruleの導入を試す場合は、実施指示を得てから行う。結果と限界を `SPEC.md` に反映する。

## 9. Windows VMで純正ソフトの実行経路を観測する（推奨）

目的: Linuxでは判定できない純正ソフトのGET `0x08`、Report `0x50` / `0x60` の到達性とSetBlobの送信先を実行時に確認する。pair/unpair UIの判定条件は項目4を併用する場合だけ対象とする。この項目は推奨であり、項目7・8の達成条件には含めない。

計画: 再確認報告と同じhashのインストーラ・バイナリ、VM snapshot、USB passthrough対象を確認する。有線C658とReceiver経路を別セッションで観測し、各Windows HID handleをinterfaceに対応付け、列挙からGET/SETとUI通知までの時刻・report・戻り値を記録する。まず各経路1セッションとし、通常の接続と設定同期を観測する。複数の一致handleがある場合は送信先を個別に記録し、観測できない呼び出しは「不在」と断定せず観測条件を残す。pairing/unpairingを試す場合は項目4の計画と実施指示を別途満たす。純正ソフトの起動自体が設定を書き換え得るため、VMへ実機を渡す前に所有者のsnapshotと復元方法を確保し、利用者の明示的な実施指示を得る。所要時間と追加反復は環境確認後に決める。

達成条件: 試した経路のhandle対応、API/USB送受信、UI上の結果、可能な範囲の物理動作と復元結果を匿名化した監査に残す。報告書の主張ごとに支持・反証・未決定を判定し、`SPEC.md` を更新する。Windows VMを実施しない場合は、この項目とWindows固有の主張を未検証のまま残す。
