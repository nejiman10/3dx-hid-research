# C658 / C652 Linux HID research

CadMouse Compact Wireless と Universal Receiver の Linux HID に関する非公式の調査リポジトリです。3Dconnexion とは無関係です。

- [SPEC.md](SPEC.md): 根拠の状態を明記した、人間向けプロトコル仕様の唯一の正本
- [TODO.md](TODO.md): 未完了の作業と達成条件の正本
- [HANDOFF.md](HANDOFF.md): 次に着手する項目番号と再開時の注意点
- [HARDWARE_TEST.md](HARDWARE_TEST.md): 実機試験の準備、操作、復元手順
- [docs/STATIC_ANALYSIS_REPORT.md](docs/STATIC_ANALYSIS_REPORT.md): 静的解析の原報告（仕様正本ではありません）
- [docs/STATIC_ANALYSIS_REPORT_2.md](docs/STATIC_ANALYSIS_REPORT_2.md): 作成者による静的経路の再確認報告（独立検証前）
- [evidence/report03-core-matrix-2026-09/README.md](evidence/report03-core-matrix-2026-09/README.md): 匿名化したReport `0x03` matrix監査の案内
- [evidence/read-paths-2026-09/README.md](evidence/read-paths-2026-09/README.md): Receiver読み取り経路の匿名化済み監査
- [evidence/report10-readback-2026-09/README.md](evidence/report10-readback-2026-09/README.md): Report `0x10` 読み戻し失敗条件の限定監査
- [evidence/hold-open-2026-09/README.md](evidence/hold-open-2026-09/README.md): 有線C658のhold-open限定監査と継続利用確認
- [evidence/report10-handle-review-2026-09/README.md](evidence/report10-handle-review-2026-09/README.md): Report `0x10` 対象handleと効果の監査
- [evidence/report03-index-transition-2026-09/README.md](evidence/report03-index-transition-2026-09/README.md): Receiverのindex 6→7限定監査
- [evidence/direct6-controlled-2026-09/README.md](evidence/direct6-controlled-2026-09/README.md): direct code 6の前後対照監査
- [evidence/receiver-repair-2026-09/README.md](evidence/receiver-repair-2026-09/README.md): Receiver結合解除・再ペアリングの匿名化監査
- [sdk/python/README.md](sdk/python/README.md): Python SDK と実験ツール

自動チェックは `./tools/run-tests.sh` で実行できます。実機への設定書き込みや Receiver のペアリング操作は状態を変更するため、実施前に [HARDWARE_TEST.md](HARDWARE_TEST.md) を確認してください。
