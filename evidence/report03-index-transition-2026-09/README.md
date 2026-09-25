# Receiver の index 6→7 切り替え監査

[初回監査](c652-mi02-transition-1.json)と[再試験監査](c652-mi02-transition-2.json)は、Receiver C652 MI_02でradialボタンのhost indexを各回6、7、6、7と変更した記録。両監査のReport `0x10`送信先descriptor SHA-256は `8e31d4b6f8e0c5eb5ff01617d202f8f29421f514fd05a187a2ca3c777aea9efc` で、[対象handle監査](../report10-handle-review-2026-09/README.md)と一致する。両監査で所有者が復元先に指定した同じ完全32-byte値を非公開ファイルから読み、最後に再送した。この値はSDKの実験用fixtureと一致するが、実機から読み取った元設定や工場出荷値ではない。

## 初回監査

| 反復 | index 6の移動後入力 | index 7送信直後の8秒間 | index 7の移動後入力 |
| --- | --- | --- | --- |
| 1 | `03 20` / `03 00` 各10回、PASS | raw `0x1b` 266 frame、Report `0x03`・evdevキー入力なし | `03 40` / `03 00` 各10回、PASS |
| 2 | `03 20` / `03 00` 各10回、PASS | raw `0x1b` 102 frame、Report `0x03`・evdevキー入力なし | `03 40` / `03 00` 各10回、PASS |

4回の送信はいずれもhost ioctl戻り値32。各phaseで送信時刻、移動指示、motion-bearing Report `0x1b`、操作指示、raw HIDとevdevの時系列を記録した。移動後の各30秒区間で想定外Report `0x03` bitmapはなく、4 phaseともPASSした。最後の指定値の再送もhost ioctl戻り値32で、転送待ち完了後にradialボタンの元のevdev入力を押下・解放各10回確認した。

試験者は終了後、index 7送信直後の8秒間にはボタンを押していないと申告した。この区間のraw `0x1b`には移動が記録されている。したがって、この区間にReport `0x03`がないことを旧mappingの不在や適用時刻の証明には使えない。移動後の2反復では過去の `03 20` 異常入力は再現しなかったが、過去試行のraw記録はないため、原因は旧mapping残留、転送遅延、その他の要因に分けられない。復元についても指定ボタンの操作上の確認であり、全設定byteのreadbackや永続性を確認していない。

## 再試験

同じ4 phaseをもう一度実施した。各index 6の移動後区間には `03 20` / `03 00`、各index 7の移動後区間には `03 40` / `03 00` を押下・解放各10回記録し、4 phaseすべてPASSした。各送信のhost ioctl戻り値は32。指定値の再送もhost ioctl戻り値32で、転送待ち後にradialボタンの元のevdev入力を押下・解放各10回確認した。

今回はindex 7送信直後の8秒間に、両反復とも `03 40` / `03 00` を各2組記録した。`03 20` はこの区間にも移動後のindex 7区間にも出ていない。ただし最初の `03 40` より前にmotion-bearing Report `0x1b` が反復1で35 frame、反復2で145 frame記録された。送信完了から最初の移動までそれぞれ約2.079秒、1.069秒、最初の `03 40` まで約2.844秒、3.128秒だった。したがって新mappingの入力は「明示的な移動指示より前」に確認できるが、「最初の転送機会より前」の適用は示さない。試験者の物理操作をraw frameの時刻より細かく独立計測したわけでもない。過去の異常入力はこの再試験でも再現せず、旧mapping残留・転送遅延などの原因は引き続き不明。

## 公開版と検証

原本はGit除外領域に保管した。公開前に個人パスと既知のReceiver ID形式を検査し、置換対象を検出しなかったため、各公開版は原本と同一。

| 監査 | 原本・公開版のSHA-256 |
| --- | --- |
| [初回](c652-mi02-transition-1.json) | `d668661a158981df0a86e3d0143acbd35e9c716c4bd5cdb13e4478cfe5b0ad8d` |
| [再試験](c652-mi02-transition-2.json) | `9129311c14c00b336d3289c8a608e5c106b523491ec13f35d6a9d34e2516d037` |

`python3 tools/validate_public.py evidence/report03-index-transition-2026-09/c652-mi02-transition-1.json evidence/report03-index-transition-2026-09/c652-mi02-transition-2.json` で形式と記録内部の整合性を検証できる。両監査の `success=true` は各phaseと復元の判定であり、過去の異常試行の原因特定を意味しない。
