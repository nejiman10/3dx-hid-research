# C658 / C652 調査仕様

唯一の人間向け仕様正本。`CONFIRMED` は静的解析で到達経路・値を確認、または制御した反復実験で確認。`OBSERVED` は条件付き観測、`HYPOTHESIS` は説明仮説、`UNKNOWN` は根拠不足。Report `0x03` matrixの実機監査は[公開用証拠](evidence/report03-core-matrix-2026-09/README.md)に収録した。他の実機観測については、公開監査の有無を各項目で区別する。[静的解析原報告](docs/STATIC_ANALYSIS_REPORT.md)と[静的経路の再確認報告](docs/STATIC_ANALYSIS_REPORT_2.md)は調査資料であり、仕様正本ではない。後者の新規主張は報告者による静的再確認結果として受け取り、リポジトリ内の原資料による独立検証は未了である。

## Report 0x10

- [CONFIRMED] generatorは31-byte blobをゼロ初期化し、offset 1（DPI）、2（lift threshold）、3..6（wheel）、18..24（7 button）、26（固定 `1e`）、30（polling divider）を設定する。(source: docs/STATIC_ANALYSIS_REPORT.md)
- [OBSERVED] 試験したLinux HID descriptorはReport `0x10` を32-byte wire bufferとして宣言した。Linux実装はID `10` と31-byte blobから完全snapshotを作る。実機への最終適用の一般性は未検証。
- [OBSERVED] 既存の有線C658とReceiver経由C652のReport `0x03`成功監査では、Report `0x10`送信先のdescriptor hashが後日のC658 MI_01、C652 MI_02にそれぞれ一致した。各17 phaseで実験用fixtureと同じbaselineのボタンmappingを1 byteだけ変えたReportを送信し、hostの送信呼び出し完了、転送機会、期待する物理入力を別々に記録した。最後にbaselineを再送して指定ボタンの入力を確認したが、所有者の元設定への復元は確認していない。ioctlの数値戻り値と送信時刻も監査にない。このLinux結果からWindows brokerの送信先は決められない。(evidence: [対象handle再評価](evidence/report10-handle-review-2026-09/README.md))
- [OBSERVED] 所有者が復元先に指定した32-byte値を使ったReceiver C652 MI_02の限定試験では、radialボタンmappingの1 byteだけを変更したReport `0x10`の送信と復元が、いずれもhost APIで32 byteを返した。変更後にmotion-bearing Report `0x1b`と、物理操作に対応するraw Report `0x03`の押下・解放10組を記録した。復元後も転送機会と元のevdev入力10組を確認した。これらは試験したLinux handle・接続・設定値での効果と操作上の復元を支持するが、全設定byteのreadbackや永続性、純正Windows brokerの送信先選択は検証していない。(evidence: [対象handle監査](evidence/report10-handle-review-2026-09/README.md))
- [CONFIRMED] direct buttonは `0x09 + action code`、host routedは `0x28 + action index` に変換する。(source: docs/STATIC_ANALYSIS_REPORT.md)
- [OBSERVED] 試験した有線C658とReceiver経由C658 handleの双方で、有効な現在設定readbackは得られなかった。失敗方法は試行ごとの観測であり、protocol定数ではない。全firmwareで不可能とは断定しない。
- [OBSERVED] 試験したReceiverでは32-byte Report `0x10`候補handleの `GET 08` が `08 59 ...` を返した。今回もC652 MI_02で8-byte応答のbyte 1が`59`だった。単一占有slotとReceiver入力は観測したが、GET `0x08`の値から個体を直接同定したわけではない。このLinux選択法をvendor DLLの静的経路と同一視しない。(evidence: [読み取り監査](evidence/read-paths-2026-09/README.md))
- [UNKNOWN] deviceからの現在設定・factory defaultの復元。Linux実装はhost側に保存した設定を正本とし、Report `0x10`を完全snapshotとして送る。

## Direct Action

- [CONFIRMED] action codes 1..5はwire `0a..0e` に対応し、静的名称は順に `HIDMouse_Left`、`HIDMouse_Right`、`HIDMouse_Middle` / `HIDMouse_WheelButton`、`HIDMouse_Backward`、`HIDMouse_Forward`。(source: docs/STATIC_ANALYSIS_REPORT.md)
- [CONFIRMED] code 6はwire `0f`でC658 default initializerから静的到達可能。正式名称は見つかっていない。(source: docs/STATIC_ANALYSIS_REPORT.md)
- [UNKNOWN] code 6の正式名称とhardware effect。公開名は `UNKNOWN_DIRECT_CODE_6`、効果は `UNKNOWN`。過去に書き込み試行後の区間で `BTN_FORWARD` が観測されたが、旧mapping混入があり因果関係は未確認。
- [CONFIRMED] 通常のC658 UI/profile経路にcode 7..30の到達producerは見つからなかった。この範囲のfirmware解釈可能性は別問題。(source: docs/STATIC_ANALYSIS_REPORT.md)

## Input Report 0x03

- [CONFIRMED] 静的descriptorはmask `0001 0002 0004 0008 0010 0020 0040` を定義し、parserはReport ID `03` のpayloadをlittle endian bitmapとしてtransitionを処理する。(source: docs/STATIC_ANALYSIS_REPORT.md)
- [OBSERVED] 試験した有線経路とReceiver経路では、radialにhost index 1..7を順に設定でき、対応するpress bitmap `03 01`、`03 02`、`03 04`、`03 08`、`03 10`、`03 20`、`03 40` とrelease `03 00` を各条件10回以上観測した。factorized coreの全17 phaseは両経路でPASSした。これは試験した個体・経路・条件での結果であり、全firmwareや全物理ボタン×全indexの保証ではない。(evidence: [有線監査](evidence/report03-core-matrix-2026-09/report03-wired_1.json), [Receiver監査](evidence/report03-core-matrix-2026-09/report03-wireless_1.json))
- [OBSERVED] Receiverの別のradial/index 7書き込み試行後、収集区間に `03 20` が1回観測され、期待する `03 40` はその区間に現れなかった。その後の試行ではindex 7で `03 40` が反復して得られた。`03 20` の観測自体は残すが、index 7の固定出力として扱わない。この異常試行のraw監査は現公開証拠に含まれず、条件と時系列を再確認できない。
- [UNKNOWN] 上記index 7試行時の `03 20` の原因。転送遅延、以前のindex 6 mappingの残留、その他の一過性要因を区別できていない。
- [HYPOTHESIS] Receiverは書き込み後のactivity opportunityまで新mappingを反映しない場合がある。motion-bearing Report `1b` は機会の指標であり、適用完了の証明ではない。

## Report 0x17

- [OBSERVED] raw frame `17 64 01` と `17 64 00` が観測された。前者と後者の双方は[有線matrix監査](evidence/report03-core-matrix-2026-09/report03-wired_1.json)、後者は[Receiver matrix監査](evidence/report03-core-matrix-2026-09/report03-wireless_1.json)に記録されている。USB充電器での充電完了後にも後者を見たという過去観測については、今回の公開監査に試験条件が含まれない。
- [HYPOTHESIS] byte 0はReport ID、byte 1は電池残量候補で `64` はdecimal 100の可能性、byte 2は充電状態flag候補で `01` が充電中、`00` が非充電または充電完了と相関する可能性がある。
- [UNKNOWN] byte 1のbattery percentage意味、byte 2の正式意味。異なる残量でbyte 1が変わるまで確定しない。

## Receiver管理とLinux実装

- [CONFIRMED] 静的経路はslot情報の `GET 43..47` を含む。(source: docs/STATIC_ANALYSIS_REPORT.md)
- [OBSERVED] 試験したLinux C652 MI_00とMI_02では、宣言された8-byte Feature Report `0x43..0x47`、`0x50`、`0x60` のGETがそれぞれ8-byte応答を返した。両interfaceの共通GET応答は一致した。接続切替後のsnapshotではslot 2だけが占有され、Receiverのevdev経路で物理入力を観測した。単一占有slotと利用者の接続報告から入力とslot 2の対応を推定できるが、入力frameにslot IDはない。`0x50` / `0x60` の値の意味とWindows UIからの到達性は未検証。(evidence: [読み取り監査](evidence/read-paths-2026-09/README.md))
- [HYPOTHESIS] 再確認報告は、`HIDDev.dll` の `GET 0x08/0x51` 分岐とbrokerのC652 paired-device handleに対する `GET 0x08` 経路を主張する。旧報告の「到達可能な `GET 0x08` なし」と対立しており、示されたcaller・対象handle・HID APIまでの経路は独立検証前である。(source: [再確認報告 §4](docs/STATIC_ANALYSIS_REPORT_2.md))
- [HYPOTHESIS] 再確認報告は、`3DxPair.exe` にReport `0x50` と `0x60` の8-byte GET実装があるが、両関数の直接callerは見つからないとする。旧報告での「specific GET producerなし」は調査モジュールの範囲に依存する。通常UIからの到達性と実機応答は未検証である。(source: [再確認報告 §5](docs/STATIC_ANALYSIS_REPORT_2.md))
- [HYPOTHESIS] 再確認報告は、SetBlobのbroker経路がlogical PIDに一致する全handleへ送信し、C652 paired-device handleも対象になり得るとする。primary handle選択、secondary fallback、slot wrapperは当該経路に見つからなかったという否定範囲も独立検証前である。(source: [再確認報告 §6](docs/STATIC_ANALYSIS_REPORT_2.md))
- [HYPOTHESIS] 再確認報告は、通常Universal Receiverのslot `0..4` と `MI_0..MI_4` の対応、およびslot GETの8-byte応答内のdevice typeと6-byte識別子を主張する。実装に同じ解釈があっても、それだけを独立した根拠としない。(source: [再確認報告 §7](docs/STATIC_ANALYSIS_REPORT_2.md))
- [UNKNOWN] 再確認報告が示すReport `0x60` の5-byte fieldの正式意味と、`0x50` / `0x60` GETの通常UIからの到達性。field名、関数名、未確認の実行時応答だけで意味を確定しない。(source: [再確認報告 §5](docs/STATIC_ANALYSIS_REPORT_2.md))
- [HYPOTHESIS] 再確認報告は、純正pair UIの成功通知はSET完了とは別の入力・接続eventによる一方、純正unpair経路の成功判定はI/O完了でslot空化を再確認しないとする。これはLinux実装の成功判定とは別の主張であり、純正経路の独立検証と実機の前後観測が未了である。(source: [再確認報告 §8](docs/STATIC_ANALYSIS_REPORT_2.md))
- [OBSERVED] pairingとunpairingの成功は手動確認済み。ただし成功時のraw監査JSONは同梱されず、公開再現証拠ではない。`EPIPE` の失敗記録だけから成功を証明しない。
- [HYPOTHESIS] pairing start `41 02 02 00 00`、stop `41 02 00 00 00`、unpair `41 04 <slot> 00 00` が管理packetの候補。成功監査で再検証する。
- [OBSERVED] systemd user service、有線USBマウス通常動作、USB再接続後の再取得は手動確認済み。raw監査は同梱されていない。
- [UNKNOWN] hold-open効果に必要なopen flag。現在のLinux実装は `O_RDWR` をaccess mode、`O_CLOEXEC` をFD継承防止、`O_NONBLOCK` をブロック回避に使う。protocol valueではない。

## 試験fixtureと証拠境界

- [OBSERVED] `latest_software_baseline_hex` と呼ばれた31-byte値は、マウス内の工場出荷時設定32-byteの取得が実際上困難だったため、静的解析で特定したbyteの意味をもとに構築した実験用初期値である。設定を変更して出力を確認する試験などに用いるための値であり、実機から取得したsnapshotやfactory defaultではない。SDKの `latest_software_baseline()` もこの実験用設定を生成する。送信するとユーザー設定を上書きし得るため、通常アプリの既定値や元の設定への復元値として使わない。
- [UNKNOWN] 公開用証拠に含まれない過去raw記録の実行条件。存在しないファイルを確認済み根拠にしない。
