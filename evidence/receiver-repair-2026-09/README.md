# Receiver結合解除と再ペアリングの監査

[一体監査](c652-slot2-to-slot3-cycle.json)には、実行時に保存した7件の匿名化済み監査を欠落なく含めた。解除前後のslot snapshot、解除前の物理入力、unpair、pair、再ペアリング直後に失敗した入力監査、再試行で成功した入力監査を時系列で保持している。個体識別子を含む実行時の照合値はGit除外領域に保管し、公開監査には含めない。

| 段階 | 観測 |
| --- | --- |
| 解除前 | C652 Receiverのslot 2だけが占有。paired-device handleのraw Report `0x1b`に左ボタン押下遷移10回、evdevに `BTN_LEFT` 押下・解放各10回 |
| unpair | 管理handleに `41 04 02 00 00` を送るhost呼び出しが例外なく完了。slot 2の空化を後続snapshotで確認 |
| pair | `41 02 02 00 00` による開始後、slot 3が新たに占有され、`41 02 00 00 00` の停止呼び出しが完了 |
| 最初の入力確認 | 古い `/dev/input/event12` が再列挙後に存在せず、入力収集前に失敗。失敗監査を保持 |
| 再試行 | 現在のevent nodeを再取得し、同じpaired-device handleのraw Report `0x1b`に左ボタン押下遷移10回、evdevに `BTN_LEFT` 押下・解放各10回。試験者も通常動作を確認 |

slotの空化、再占有、物理入力は独立の観測として扱う。CLIの `success` は各コマンドの判定であり、pairコマンド単独では物理入力を確認しない。一体監査の成功判定は解除前後の入力とslot変化の両方を要する。マウス入力のraw frame自体はslot番号を含まず、同一個体であることは単一占有slotと試験者の操作報告から推定する。host APIの数値戻り値はこの監査に保存されていないため、例外のない呼び出し完了とslot/入力変化以上は主張しない。別個体・別firmwareでの一般性や純正Windowsソフトの経路は未検証。

実行時のCLIは未commitの変更を含むため、各監査の `tool_git_commit` だけでは完全なソースを特定できない。結合操作時に構築したzipappのSHA-256は `d05ddc045958cc6e915428309c69c4696019469ca54be5f4d2ca345caf84b1bc`。各原本のSHA-256は一体監査の `source_sha256` に記録した。`python3 tools/validate_public.py evidence/receiver-repair-2026-09/c652-slot2-to-slot3-cycle.json` で公開内容とslot・時系列・入力回数の内部整合性を検査できる。
