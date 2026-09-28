# 実機HID report descriptorテストデータ

[`real_hid_descriptors.json`](real_hid_descriptors.json) は、[Linux読み取り経路の監査](../../../../evidence/read-paths-2026-09/README.md)の非公開原本4件から、`descriptor_hex` の全byteだけを取り出したものです。2026-09-25 UTCに標準ユーザーでUSB接続経路を読み取り、設定書き込みとpair/unpairは行っていません。C652の2件はReceiverのUSB interface、C658の2件は有線接続のUSB interfaceです。fixtureにはVID/PID、interface番号、取得日時、原本とdescriptorのSHA-256を付けています。原本のローカルpath、device node、GET応答は含めていません。

## 収録前確認

- 各原本のSHA-256を公開監査の記録と照合し、各descriptorのSHA-256を原本の記録と照合した。
- 140、338、78、208 byteの全byteをHID short itemとして順に確認した。途中で切れたitem、long item、reserved item、String Index / String Minimum / String Maximum itemはなかった。したがってdescriptor内に個体識別用の文字列値や文字列参照は見つからなかった。
- 収録対象はreport宣言とUsage等の静的なitemだけであり、個体識別子を含み得るGET応答やUSB serialは取り込んでいない。収録ファイルのmetadataにも個体固有値やホスト固有pathはない。
- fixtureのdescriptor SHA-256は[公開監査](../../../../evidence/read-paths-2026-09/README.md)の4件と一致する。descriptorの観測から実機の動作や各fieldの意味を追加で主張するものではない。

確認対象と出所はfixture内の `name`、`source_audit_sha256`、`captured_utc`、`transport`、`usb_interface` を参照してください。
