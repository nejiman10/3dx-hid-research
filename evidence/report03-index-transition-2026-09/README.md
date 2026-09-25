# Receiver の index 6→7 切り替え監査

[公開監査](c652-mi02-transition-1.json)は、Receiver C652 MI_02でradialボタンのhost indexを6、7、6、7と変更した2反復・4 phaseの記録。Report `0x10`の送信先descriptor SHA-256は `8e31d4b6f8e0c5eb5ff01617d202f8f29421f514fd05a187a2ca3c777aea9efc` で、[対象handle監査](../report10-handle-review-2026-09/README.md)と一致する。所有者が復元先に指定した完全32-byte値を非公開ファイルから読み、最後に再送した。この値はSDKの実験用fixtureと一致するが、実機から読み取った元設定や工場出荷値ではない。

| 反復 | index 6の移動後入力 | index 7送信直後の8秒間 | index 7の移動後入力 |
| --- | --- | --- | --- |
| 1 | `03 20` / `03 00` 各10回、PASS | raw `0x1b` 266 frame、Report `0x03`・evdevキー入力なし | `03 40` / `03 00` 各10回、PASS |
| 2 | `03 20` / `03 00` 各10回、PASS | raw `0x1b` 102 frame、Report `0x03`・evdevキー入力なし | `03 40` / `03 00` 各10回、PASS |

4回の送信はいずれもhost ioctl戻り値32。各phaseで送信時刻、移動指示、motion-bearing Report `0x1b`、操作指示、raw HIDとevdevの時系列を記録した。移動後の各30秒区間で想定外Report `0x03` bitmapはなく、4 phaseともPASSした。最後の指定値の再送もhost ioctl戻り値32で、転送待ち完了後にradialボタンの元のevdev入力を押下・解放各10回確認した。

試験者は終了後、index 7送信直後の8秒間にはボタンを押していないと申告した。この区間のraw `0x1b`には移動が記録されている。したがって、この区間にReport `0x03`がないことを旧mappingの不在や適用時刻の証明には使えない。移動後の2反復では過去の `03 20` 異常入力は再現しなかったが、過去試行のraw記録はないため、原因は旧mapping残留、転送遅延、その他の要因に分けられない。復元についても指定ボタンの操作上の確認であり、全設定byteのreadbackや永続性を確認していない。

原本と公開監査のSHA-256はともに `d668661a158981df0a86e3d0143acbd35e9c716c4bd5cdb13e4478cfe5b0ad8d`。原本はGit除外領域に保管した。公開前に個人パスと既知のReceiver ID形式を検査し、置換対象を検出しなかったため、公開版は原本と同一。`python3 tools/validate_public.py evidence/report03-index-transition-2026-09/c652-mi02-transition-1.json` で形式と記録内部の整合性を検証できる。監査の `success=true` は本試験のphaseと復元の判定であり、過去の異常試行の原因特定を意味しない。
