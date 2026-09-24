# Report 0x03 core matrix 監査

このディレクトリには、有線とReceiver経路の `probe-report03-matrix` 監査5件を公開用に保存する。JSONは実行時の監査をそのまま匿名化処理したもので、欠けたphaseや入力を補っていない。作成方法と原本・公開版のSHA-256は [ANONYMIZATION.md](ANONYMIZATION.md) と [manifest.json](manifest.json) を参照。

| 監査 | 経路 | 記録されたphase | 結果 |
|---|---|---:|---|
| [report03-wired.json](report03-wired.json) | 有線 | 1/17 | 最初のphaseで入力不足、INCONCLUSIVE |
| [report03-wired_1.json](report03-wired_1.json) | 有線 | 17/17 | 全phase PASS、復元後の入力確認あり |
| [report03-wireless.json](report03-wireless.json) | Receiver | 1/17 | 最初のphaseで想定外evdev入力、FAIL |
| [report03-wireless_1.json](report03-wireless_1.json) | Receiver | 17/17 | 全phase PASS、復元後の入力確認あり。再開前の試行は `previous_attempts` に保持 |
| [report03-wireless_2.json](report03-wireless_2.json) | Receiver | 14/17 | middle-host-index-1で想定外evdev入力、FAIL |

2件の成功監査は、[SPEC.md](../../SPEC.md) のReport `0x03` factorized core観測の根拠。失敗監査は異なる試行であり、成功監査を取り消すものではない。Receiverのindex 7で `03 20` を得たとされる別試行は、この5件に含まれない。code 6、Report `0x17`、pairing/unpairingの監査もここには含まれない。

匿名化処理では置換対象の個体IDは検出されず、公開JSONと原本のハッシュは一致した。公開前の検査では個人のパスと既知のReceiver ID形式を検出しなかった。`python3 tools/validate_public.py` で5件の形式・記録内部の整合性を検証できる。失敗監査の検証成功は、実機試験の成功を意味しない。
