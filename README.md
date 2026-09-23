# C658 / C652 Linux HID research

CadMouse Compact Wireless (`256f:c658`) と Universal Receiver (`256f:c652`) の非公式調査リポジトリです。3Dconnexionとは無関係です。

現在は静的解析に基づくReport構築とLinux用の実験toolがあり、Report `0x03` の全条件実機検証、code 6の効果、成功時のpairing監査は未完了です。`research-baseline-1` は監査前のローカルsnapshotで、完成releaseではありません。

自動テストは `./tools/run-tests.sh`、実機試験の準備と操作は [HARDWARE_TEST.md](HARDWARE_TEST.md) を参照してください。唯一の人間向け仕様正本は [SPEC.md](SPEC.md) です。

設定試験は利用者の設定を上書きする可能性があります。Receiverのpairingとunpairingは結合状態を変えるため、対象を確認してから実行してください。
