# C658 / C652 調査仕様

唯一の人間向け仕様正本。`CONFIRMED` は静的解析で到達経路・値を確認、または制御した反復実験で確認。`OBSERVED` は条件付き観測、`HYPOTHESIS` は説明仮説、`UNKNOWN` は根拠不足。Report `0x03` matrixの実機監査は[公開用証拠](evidence/report03-core-matrix-2026-09/README.md)に収録した。他の実機観測については、公開監査の有無を各項目で区別する。[静的解析原報告](docs/STATIC_ANALYSIS_REPORT.md)はsource artifactで、仕様正本ではない。

## Report 0x10

- [CONFIRMED] generatorは31-byte blobをゼロ初期化し、offset 1（DPI）、2（lift threshold）、3..6（wheel）、18..24（7 button）、26（固定 `1e`）、30（polling divider）を設定する。(source: docs/STATIC_ANALYSIS_REPORT.md)
- [OBSERVED] 試験したLinux HID descriptorはReport `0x10` を32-byte wire bufferとして宣言した。Linux実装はID `10` と31-byte blobから完全snapshotを作る。実機への最終適用の一般性は未検証。
- [CONFIRMED] direct buttonは `0x09 + action code`、host routedは `0x28 + action index` に変換する。(source: docs/STATIC_ANALYSIS_REPORT.md)
- [OBSERVED] 試験した有線C658とReceiver経由C658 handleの双方で、有効な現在設定readbackは得られなかった。失敗方法は試行ごとの観測であり、protocol定数ではない。全firmwareで不可能とは断定しない。
- [OBSERVED] 試験したReceiverでは32-byte Report `0x10`候補handleの `GET 08` が `08 59 ...` を返した経路がC658に対応した。このLinux選択法をvendor DLLの静的経路と同一視しない。
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
- [OBSERVED] pairingとunpairingの成功は手動確認済み。ただし成功時のraw監査JSONは同梱されず、公開再現証拠ではない。`EPIPE` の失敗記録だけから成功を証明しない。
- [HYPOTHESIS] pairing start `41 02 02 00 00`、stop `41 02 00 00 00`、unpair `41 04 <slot> 00 00` が管理packetの候補。成功監査で再検証する。
- [OBSERVED] systemd user service、有線USBマウス通常動作、USB再接続後の再取得は手動確認済み。raw監査は同梱されていない。
- [UNKNOWN] hold-open効果に必要なopen flag。現在のLinux実装は `O_RDWR` をaccess mode、`O_CLOEXEC` をFD継承防止、`O_NONBLOCK` をブロック回避に使う。protocol valueではない。

## 試験fixtureと証拠境界

- [OBSERVED] `latest_software_baseline_hex` と呼ばれた31-byte値は過去の試験用完全snapshotであり、factory defaultではない。ユーザー設定を上書きし得る。SDKの `latest_software_baseline()` は復元fixtureで、通常アプリの既定値として使わない。
- [UNKNOWN] 公開用証拠に含まれない過去raw記録の実行条件。存在しないファイルを確認済み根拠にしない。
