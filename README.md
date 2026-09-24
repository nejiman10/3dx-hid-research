# C658 / C652 Linux HID research

CadMouse Compact Wireless と Universal Receiver の Linux HID に関する非公式の調査リポジトリです。3Dconnexion とは無関係です。

- [SPEC.md](SPEC.md): 根拠の状態を明記した、人間向けプロトコル仕様の唯一の正本
- [HANDOFF.md](HANDOFF.md): 現在の作業状況と次に確認する事項
- [HARDWARE_TEST.md](HARDWARE_TEST.md): 実機試験の準備、操作、復元手順
- [docs/STATIC_ANALYSIS_REPORT.md](docs/STATIC_ANALYSIS_REPORT.md): 静的解析の原報告（仕様正本ではありません）
- [evidence/report03-core-matrix-2026-09/README.md](evidence/report03-core-matrix-2026-09/README.md): 匿名化したReport `0x03` matrix監査の案内
- [sdk/python/README.md](sdk/python/README.md): Python SDK と実験ツール

自動チェックは `./tools/run-tests.sh` で実行できます。実機への設定書き込みや Receiver のペアリング操作は状態を変更するため、実施前に [HARDWARE_TEST.md](HARDWARE_TEST.md) を確認してください。
