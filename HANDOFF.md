# 作業引き継ぎ

この文書は継続作業の案内です。プロトコルの主張と根拠の状態は [SPEC.md](SPEC.md) を参照してください。

## 現在の焦点

- [SPEC.md](SPEC.md) には、有線・Receiver 経路での Report `0x03` の factorized core 試験結果が `OBSERVED` として記録されています。全物理ボタンと全 host index の組合せを網羅した結果ではありません。
- 実機試験の raw 監査 JSON はリポジトリに同梱されていません。現作業ツリーの `evidence/source-private-not-in-repository/` には Git の追跡対象外となる監査ファイルがあります。公開可能な証拠として扱う前に、試験条件、匿名化、内容の整合を確認する必要があります。欠けている記録を再構成しないでください。
- code 6 の効果、Receiver の index 6→7 切り替え時に観測された入力の原因、Report `0x17` の byte の意味は、[SPEC.md](SPEC.md) で未確定です。pairing / unpairing の成功時監査も未同梱です。

## 次に進める作業

1. 追跡対象外の監査 JSON を確認し、[HARDWARE_TEST.md](HARDWARE_TEST.md) に従って匿名化と `tools/validate_public.py` による検証を行う。raw 記録と [SPEC.md](SPEC.md) の観測記述を照合し、欠けている証拠は再構成せず再取得の要否を検討する。
2. 追加の実機検証が必要になったら、旧 mapping の残留と転送遅延を区別できる時系列を採る。code 6 は raw HID と evdev を併記し、Report `0x17` は異なる電池残量で比較する。目的と試験量を決めてから着手する。
3. pairing / unpairing の成功時には、操作前後の slot、送信内容、結果を含む自己完結した監査を取得する。Report `0x10` readback の失敗と hold-open flag の条件を調べる場合も、経路別に失敗内容を残す。

実機への書き込み、pairing / unpairing、復元は明示的な利用者の意図が必要です。全組合せを調べる大規模な試験は、その範囲と負担を確認してから実施してください。

## 最初に読むファイル

- [AGENTS.md](AGENTS.md): 作業と証拠の取り扱い
- [SPEC.md](SPEC.md): 根拠付きの主張と未確定事項
- [HARDWARE_TEST.md](HARDWARE_TEST.md): 実機試験と復元の手順
- [sdk/python/README.md](sdk/python/README.md): ツールの入口
