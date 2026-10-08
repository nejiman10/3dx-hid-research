# 未完了の作業

このファイルは未完了項目と達成条件の正本です。項目番号は再開時の参照に使うため、並べ替える際も再利用しません。プロトコルの主張と根拠の状態は [SPEC.md](SPEC.md)、実機操作と復元の手順は [HARDWARE_TEST.md](HARDWARE_TEST.md) を参照してください。

実機試験では着手前に目的、区別したい説明、試験条件、反復回数、所要時間を決めます。結果は成功・失敗・判定不能を含めて匿名化した監査として `evidence/` に保存し、検証したうえで `SPEC.md` の該当箇所を更新します。原因を特定できない場合は `UNKNOWN` を維持し、試験条件と限界を記録します。

## 9. Windows VMで純正ソフトの実行経路を観測する（推奨）

目的: Linuxでは判定できない純正ソフトのGET `0x08`、Report `0x50` / `0x60` の到達性とSetBlobの送信先を実行時に確認する。pair/unpair UIの判定条件は項目4を併用する場合だけ対象とする。この項目は推奨であり、項目7・8の達成条件には含めない。

計画: 再確認報告と同じhashのインストーラ・バイナリ、VM snapshot、USB passthrough対象を確認する。有線C658とReceiver経路を別セッションで観測し、各Windows HID handleをinterfaceに対応付け、列挙からGET/SETとUI通知までの時刻・report・戻り値を記録する。まず各経路1セッションとし、通常の接続と設定同期を観測する。複数の一致handleがある場合は送信先を個別に記録し、観測できない呼び出しは「不在」と断定せず観測条件を残す。pairing/unpairingを試す場合は項目4の計画と実施指示を別途満たす。純正ソフトの起動自体が設定を書き換え得るため、VMへ実機を渡す前に所有者のsnapshotと復元方法を確保し、利用者の明示的な実施指示を得る。所要時間と追加反復は環境確認後に決める。

達成条件: 試した経路のhandle対応、API/USB送受信、UI上の結果、可能な範囲の物理動作と復元結果を匿名化した監査に残す。報告書の主張ごとに支持・反証・未決定を判定し、`SPEC.md` を更新する。Windows VMを実施しない場合は、この項目とWindows固有の主張を未検証のまま残す。

## 10. 1台のReceiverに2台のマウスを結合した場合の設定送信先を調べる

目的: 2台が同時に結合された条件で、各マウスの設定送信先nodeとReceiverのslotの対応を調べる。現時点の単一占有slotの観測は[SPEC.mdのReceiver管理節](SPEC.md#receiver管理とlinux実装)を参照する。

計画: 実施前に2台の識別方法、現在の結合・設定状態、復元方法、試験回数と所要時間を決め、所有者の明示的な実施指示を得る。実行時に各nodeのtransport・interface・descriptorを再同定し、slotの前後状態と各マウスの物理入力を記録する。設定送信を行う場合は、送信先node、host戻り値、転送機会、各マウスで観測した効果と復元結果を区別して記録する。識別子の実値は公開しない。

達成条件: 試した条件で各マウスとslot、設定送信先nodeの対応を再確認できる匿名化監査を残す。各マウスのGET `0x08` bytes 2..7同士が一致するか、および各マウスの同bytesが自分のslotのbytes 2..7とだけ一致するかを記録する。識別子の実値は公開せず、一致・不一致・判定不能のみを残す。支持できる範囲と未決定の点を`SPEC.md`に反映する。

## 13. 有線・Receiverモード切り替えで設定の挙動が変わる原因を調べる

目的: [同時接続監査](evidence/cross-route-management-2026-09/README.md)で、一方の経路へ送った試験値の効果が切り替え後の他方に現れず、保存済み値の送信後に見た入力分類が切り替え後に戻った原因を調べる。経路ごとに設定を保持する、切り替え時に設定を再適用・初期化する、送信時の適用漏れなどを区別する。

計画: 実施前に復元値、試験回数、所要時間を決め、所有者の実施指示を得る。経路Aに試験値を送り効果を確認し、Bへ切り替えて入力を確認した後、Aへ戻して試験値が残るかを確認する。Bに別の試験値を先に送る対照条件も検討する。各段階でnodeを再同定し、送信先、host戻り値、転送機会、物理入力を別々に記録する。判定にはLinuxイベント名よりraw Report `0x03` / `0x1b`を優先し、利用者が見た動作も別に記録する。

達成条件: 試した条件で、経路ごとの保持、切り替え時の再適用・初期化、その他の説明それぞれを支持・反証・判定不能のいずれかに判定した匿名化監査を残し、`SPEC.md`に反映する。

## 14. Report `0x17` とLinux `power_supply` の対応を経路ごとに確かめる

目的: [descriptorとpower_supplyの限定観測](evidence/report17-power-supply-2026-10/README.md)は、Receiver経由の1点だけである。byte 1とLinux `capacity` の対応、`status` がbyte 2を反映しないか、有線・Bluetooth接続で同じ電池が作られるか、UPowerが列挙しない理由を区別する。

計画: 読み取りだけで行う（設定・結合状態の書き込みはしない）。Receiver、有線、Bluetoothの各経路で（Bluetoothの限定観測は[Bluetooth LE接続節](SPEC.md#bluetooth-le接続)を参照）、同じ時間帯にraw Report `0x17` の取得と `power_supply` の `capacity`・`status`・`type`・`scope` の読み取りを行い、親のHID deviceのdescriptor SHA-256を記録する。可能なら充電ケーブルの有無で各1回比べる。UPowerについては `upower -d` の列挙とUPowerのdebug出力を記録する。各経路1回を基本とし、所要時間は経路の切り替えを含めて30分程度を見込む。識別子の実値（`serial_number`、Bluetooth address、USB topology）は公開しない。

達成条件: 試した各経路で、raw byte 1と `capacity`、byte 2と `status` の一致・不一致、`power_supply` の有無、UPowerの列挙結果を匿名化した監査に残し、[SPEC.mdのReport 0x17節](SPEC.md#report-0x17)を更新する。試せなかった経路は条件とともに未確認として残す。

## 15. Bluetooth LE経路の設定の保持を調べる

目的: [Bluetooth LE接続の限定観測](evidence/bluetooth-le-spike-2026-10/README.md)では、Bluetoothで送った設定が再接続や電源の入れ直しの後に消え、慣性がBluetooth接続のたびに有効になると利用者が報告した。Bluetooth経路が別の設定を持つのか、どの操作で設定が失われるのか、Bluetoothへの送信が有線・Receiverの設定に影響するかを区別する。項目13の延長である。

計画: 実施前に復元値、試験回数、所要時間を決め、所有者の実施指示を得る。Bluetoothに試験値（効果を物理入力で判定できるradialのhost index など）を送って効果を確かめ、(a) Bluetoothの切断・再接続、(b) 電源の入れ直し、(c) Receiverまたは有線へ切り替えてBluetoothへ戻す、の各操作の後に効果が残るかを1回ずつ確かめる。各段階でnodeを再同定し、送信先、host戻り値、転送機会、raw Report `0x03` / `0x1b` を記録する。Bluetoothへの送信の後にReceiver・有線の効果が変わるかも記録する。

達成条件: 試した各操作で設定が残る・消える・判定不能のいずれかを匿名化した監査に残し、[SPEC.mdのBluetooth LE接続節](SPEC.md#bluetooth-le接続)を更新する。
