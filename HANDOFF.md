# 作業引き継ぎ

この文書は継続作業の案内です。プロトコルの主張と根拠の状態は [SPEC.md](SPEC.md) を参照してください。

## 現在の焦点

- [SPEC.md](SPEC.md) には、有線・Receiver 経路での Report `0x03` の factorized core 試験結果が `OBSERVED` として記録されています。[匿名化済みの監査5件](evidence/report03-core-matrix-2026-09/README.md)に、有線とReceiverの全17 phase成功監査、途中終了・失敗監査を収録しました。全物理ボタンと全 host index の組合せを網羅した結果ではありません。
- 5件の原本は作業時点で `evidence/source-private-not-in-repository/` にあり、Git追跡対象外です。公開版のハッシュと原本ハッシュは一致し、置換対象の個体IDは見つかりませんでした。欠けている記録を再構成しないでください。
- code 6 の効果、Receiver の index 6→7 切り替え時に観測された入力の原因、Report `0x17` の byte の意味は、[SPEC.md](SPEC.md) で未確定です。pairing / unpairing の成功時監査も未同梱です。

## 次に進める作業

1. Receiverのindex 7試行時に `03 20` が出たという過去観測は、今回収録した5件には含まれません。根拠の再取得が必要なら、旧mappingの残留と転送遅延を区別できる時系列を採る。目的と試験量を決めてから着手する。
2. code 6 は raw HID と evdev を併記して効果を調べる。Report `0x17` は異なる電池残量で比較する。今回の監査は `17 64 01` / `17 64 00` のraw frameを含むが、byteの意味は確定しない。
3. pairing / unpairing の成功時には、操作前後の slot、送信内容、結果を含む自己完結した監査を取得する。Report `0x10` readback の失敗と hold-open flag の条件を調べる場合も、経路別に失敗内容を残す。

実機への書き込み、pairing / unpairing、復元は明示的な利用者の意図が必要です。全組合せを調べる大規模な試験は、その範囲と負担を確認してから実施してください。

## 最初に読むファイル

- [AGENTS.md](AGENTS.md): 作業と証拠の取り扱い
- [SPEC.md](SPEC.md): 根拠付きの主張と未確定事項
- [HARDWARE_TEST.md](HARDWARE_TEST.md): 実機試験と復元の手順
- [sdk/python/README.md](sdk/python/README.md): ツールの入口
