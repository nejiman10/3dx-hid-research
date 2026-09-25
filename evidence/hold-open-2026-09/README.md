# 有線C658 hold-open限定監査（2026-09-25）

項目6の初回試行。標準ユーザーで実行し、既存のuser serviceを一時停止した。条件Aはhidraw FDを保持せず、有線USBの抜き差し後に入力を確認した。sysfsからC658の2 interfaceを再取得し、descriptorは試験前後で一致した。別プロセスによる対象hidraw保持は、実行ユーザーから見える範囲で0件だった。設定Reportの送信、pair/unpair、sudoは行っていない。

| 記録 | 結果 |
| --- | --- |
| C658 MI_00 descriptor SHA-256 | `abd0fccf61bba84ac67aab1fdc65ca79ab2af86f70a864bc4c60360aa2ce1868` |
| C658 MI_01 descriptor SHA-256 | `6b205bb223c7adaccb757021ac7f1c90eef8a4d9cd6cbc0ee9e59d09f967d0eb` |
| 接続直後の手動入力確認 | 正常（利用者回答 `y`） |
| 約30秒後の手動入力確認 | 異常（利用者回答 `n`） |
| 続く10秒間のevdev監視 | C658 MI_00に属するevent nodeを開いた。左ボタン押下0件、解放0件、相対移動event 0件 |
| 物理操作 | 監査内の3回操作確認は回答期限切れ。利用者が後続の会話で、この10秒間に左クリックを3回行ったと報告 |
| user service | 監査前 `active`、試験中は停止、終了時 `active`。監査内の復元後動作確認は有効な回答なし。利用者は後続の会話で、有線で通常動作を確認してReceiverへ戻したと報告 |

利用者は、USB接続直後に使える時間は「ほんの数秒」とも報告した。監査は停止に至る正確な秒数を測っていない。手動回答とevent数は、この条件で入力が使えなくなったことと整合する。ただし観測したのは1回の条件Aであり、原因や必要なopen flagは決まらない。evdevのFDを開いたのは手動異常確認後であり、監視自体の影響は排除できない。

監査コマンドは3回操作したかの回答を6秒で打ち切り、条件B/Cへ進む前に終了した。これは入力異常とは別の試験手順上の失敗である。実装の回答期限を延ばし、条件Aの監査を参照してB/Cから続ける機能を追加した。元の監査には `failure=operator response timed out` と、復元後の回答が不明だったことをそのまま残す。

非公開原本はGit除外の `evidence/source-private-not-in-repository/hold-open/attempt-1.json` に保管。原本SHA-256は `de0530693a33a0deaeddf3b591df2c970ffb573cdfac4601a1d8eafc6c2bfcda`。

## 継続試行：条件B/C

条件Aの監査を参照し、同じdescriptorを持つ有線C658の2 interfaceで継続した。user serviceは試行前後とも`active`、試行中は停止。実行ユーザーから見える他のhidraw holderは各条件0件だった。

| 条件 | 記録 |
| --- | --- |
| B: 全interfaceを`O_RDONLY | O_CLOEXEC | O_NONBLOCK`で保持 | 2 interfaceともopen成功。再接続後約0.05秒でFD保持を開始。接続直後・約30秒後とも手動入力正常との監査回答。10秒間のevdev監視で左ボタン押下3件、解放3件、相対移動781件。利用者は3回操作したと回答。 |
| C: 全interfaceを`O_RDWR | O_CLOEXEC | O_NONBLOCK`で保持 | 2 interfaceともopen成功。再接続後約0.05秒でFD保持を開始。接続直後の監査回答が12秒で期限切れとなり、30秒後とevdevは未観測。後続の会話で利用者は接続直後に使えたと報告した。 |
| 終了状態 | 両条件のFDは閉じられ、user serviceは`active`に復元。監査内の復元後入力確認は`u`。後続の会話で利用者は現在有線で正常と報告した。 |

条件Aで観測した約30秒後の入力異常と、条件Bで観測した正常入力は、FD保持が入力状態へ影響する可能性を支持する。各条件1回のため再現性・因果関係・必要なinterfaceは未確定。条件Bの成功から、この試行条件ではread-only FD保持で正常入力が可能だった。条件Cとの30秒後の比較はまだできない。evdev監視は手動確認後に開始しており、監視FDの影響も排除していない。

非公開原本はGit除外の `evidence/source-private-not-in-repository/hold-open/attempt-2.json` に保管。原本SHA-256は `1ff6f8e034a72f0c9ed99f6b1c36aef2a1400e224ee316e5f05d51006626ec24`。監査は `failure=operator response timed out` のまま保存し、利用者の後続報告を監査回答へ書き換えない。実行時のソースには未commit変更があり、HEADだけでは使用コードを特定できない。

## 継続試行：条件Cの完了

2回目の監査を参照し、条件Cのみを再試行した。同じdescriptorの2 interfaceを再接続後約0.05秒で `O_RDWR | O_CLOEXEC | O_NONBLOCK` で開き、約54秒間保持した。両interfaceのopenは成功し、実行ユーザーから見える他のhidraw holderは0件だった。接続直後と約30秒後の手動入力はともに正常との監査回答。続く10秒間のevdev監視で左ボタン押下3件、解放3件、相対移動2156件を記録し、利用者も3回操作したと回答した。監視用event FDを開いたのは手動確認後である。

監査に失敗はなく、両hidraw FDを閉じてuser serviceを試験前の`active`へ復元した。復元後の通常入力も監査内で正常との回答だった。これにより初回のA、2回目のB、3回目のCについて、限定した同一手順の結果がそろった。AとB/Cの差はFD保持が入力状態へ影響する可能性を支持するが、各条件1回かつ別々の再接続試行のため、再現性と因果関係はまだ確定しない。B/Cとも正常だったため、この条件ではread-write access modeが正常入力の必要条件とは示されない。どちらのinterface保持が必要かも未試験である。

非公開原本はGit除外の `evidence/source-private-not-in-repository/hold-open/attempt-3.json` に保管。原本SHA-256は `dd3926df1507dddb774f5ae473afcee9545bf9430ee0547eb02433bdeb068535`。公開文書にはnode番号やローカルpathを含めない。実行時のソースには未commit変更があり、HEADだけでは使用コードを特定できない。

## A/B反復試行：条件Aまで

4回目の監査はA/Bを各1回反復する計画だった。条件Aでhidraw FDを保持せず再接続し、同じ2 interfaceとdescriptorを確認した。実行ユーザーから見える他のhidraw holderは0件。接続直後の監査回答は`y`だが、利用者はカーソル移動とクリックを試す前に回答し、実際にはその時点ですでに動作が止まっていた可能性があると後で報告した。したがって接続直後の正常動作は未確認とする。

約30秒後の監査回答は`n`。利用者はカーソル移動と左クリックを実際に試したが反応しなかったと確認した。続く10秒間に左ボタンを物理的に3回押下・解放したと利用者が後で確認したが、evdev監査は左ボタン押下・解放各0件、相対移動0件だった。監査内の「3回操作できましたか」には`n`と答えており、当時の設問は物理操作と画面反応のどちらを問うか曖昧だった。後続の報告を監査回答へ書き換えず、両者を分けて保存する。

ツールはこの`n`で条件Bへ進まず終了した。監査コマンドの終了コードは当時0で、`stopped_after_operator_check`があるため試験計画としては途中終了である。現在のツールは物理的な押下・解放を明示して尋ね、未確認なら非ゼロで終了する。user serviceは試験前後とも`active`で、復元後の通常入力は監査内で正常との回答だった。条件Aの約30秒後の入力異常は再観測され、直後の正常動作は判定不能。条件Bの反復は未実施である。

非公開原本はGit除外の `evidence/source-private-not-in-repository/hold-open/attempt-4.json` に保管。原本SHA-256は `1e441b0c5a1e9ecb4c8ef1fe251fab005d16923947334981738fecf2b3efb1ac`。実行時のソースには未commit変更があり、HEADだけでは使用コードを特定できない。

## 条件Bの反復試行

4回目の条件Aを参照し、5回目の監査で条件Bのみ反復した。同じdescriptorの2 interfaceを再接続後約0.05秒で `O_RDONLY | O_CLOEXEC | O_NONBLOCK` で開き、約58秒間保持した。両interfaceのopenは成功し、実行ユーザーから見える他のhidraw holderは0件だった。接続直後と約30秒後の手動入力はともに正常との監査回答。続く10秒間のevdev監視で左ボタン押下3件、解放3件、相対移動967件を記録し、利用者も物理的に3回操作したと回答した。

監査に失敗はなく、両hidraw FDを閉じ、user serviceを試験前の`active`へ復元した。復元後の通常入力も監査内で正常との回答だった。Aの約30秒後の異常とBの正常動作はそれぞれ2回観測できた。これは全interfaceのread-only FD保持と正常動作の関連を支持する。ただし、各条件は別の再接続試行であり、FD保持そのものの因果効果、必要なinterfaceや他のflagの必要性を確定しない。条件Cの完了観測は1回である。

非公開原本はGit除外の `evidence/source-private-not-in-repository/hold-open/attempt-5.json` に保管。原本SHA-256は `dd1ad5576be96b455fa19bcd96c3c252592bc2f6c444ac729292243b2c0dc43d`。実行時のソースには未commit変更があり、HEADだけでは使用コードを特定できない。

## 試験目的の見直し

利用者は、FDを保持しない状態ではUSB接続後5秒以下で反応が止まることがあり、停止前に人が入力イベントを発生させて検証する時間的余裕がないと報告した。これは停止時刻の計測値ではない。上記の監査からは、後続の操作窓での入力異常と正常入力の差を評価できるが、入力停止までの秒数や接続直後の正常動作を定量的に示すことはできない。

項目6は現行user serviceが通常使用中と再接続後に実用上十分な入力を維持するかの確認へ変更した。MI00/MI01個別保持の比較は現在の達成条件に含めない。既存の監査結果と非公開原本は変更しない。

## 現行user serviceでの継続利用確認

利用者は、現行の有線C658を1日以上、カーソル移動・クリック・スクロールを含む通常利用で問題なく使えたと報告した。USB再接続後にserviceが対象interfaceを掴み直したこともsystemd journalの`held`記録で確認した。開始・終了の正確な時刻とraw journalは公開証拠に含めず、node番号などのローカル識別子も記録しない。

確認対象のunit定義は `c658-hidraw-hold-open.service` で、`c658-report10ctl hold-open --poll-interval 1` を起動する。実装は1秒ごとにhidrawを列挙し、VID:PID `256f:c658` に一致する全C658 interfaceを `O_RDWR | O_CLOEXEC | O_NONBLOCK` でopenして保持し、消失時にcloseする。Receiver `256f:c652` は対象外。通常動作の1日以上は、C658/C652のhidrawに `TAG+="uaccess"` を付けるルールがある状態で確認された。利用者によると、この期間はinput event用ルールなしで動作していた。今回の確認にあたり、利用者がinput event用の2規則を追加した。これらはinput event nodeへのアクセス権用で、hold-open serviceはhidrawだけを開く。リポジトリ同梱のudevルールはhidraw向け2規則である。

この結果をもってTODO項目6を完了とする。根拠は当該Linux環境でhidraw用ルールにより1日以上通常動作したという利用者報告と、再接続時のjournal上の再取得記録である。今回追加されたinput event用ルールはこの期間の動作条件ではない。これは当該環境と期間の実用確認であり、別環境での保証や停止原因の確定を意味しない。継続利用の手順は [HARDWARE_TEST.md](../../HARDWARE_TEST.md#有線c658の継続利用確認手順) に残す。
