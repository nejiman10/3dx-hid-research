# 実機試験手順

## 前提

Linux、Python 3.10以上、対象C658/C652、操作できる物理マウスを用意する。設定書き込みを伴う試験はユーザー設定を上書きする。現在設定のreadbackは期待せず、所有者が指定した完全32-byte復元値を先に別途保管する。実機から得たsnapshotか、所有者が意図して指定した値かを区別して記録する。SDK同梱の `latest_software_baseline()` は静的解析をもとに構築した実験用初期値であり、保存済み設定やfactory defaultではない。継続前に上書きと復元値を確認する。probeには指定値を `--baseline-report10-hex '10 ...'` または非公開ファイルの `--baseline-report10-file` で渡す。保存値がない場合だけ `--accept-test-fixture` を明示する。

`python3 tools/build_zipapp.py --source sdk/python/src --output /tmp/c658-report10ctl.pyz` でtoolを作る。`python3 /tmp/c658-report10ctl.pyz scan --json` でReport `0x10` target、Report `0x03` input hidraw、input eventを特定する。`/dev/hidrawN` は実行ごとに読み替える。

ReceiverへReport `0x10`を書き込む試験では、各送信の直前に対象nodeのpath、USB interface、descriptor hash、Report宣言を再同定する。書き込みに使う同じfdでGET `0x08`を行い、ioctl戻り値、応答長、Report ID、byte 1、およびbytes 2..7と対象slotの応答との一致・不一致を非公開監査に記録する。slotの占有状態も同時に確認し、対象が一意に定まらなければ送信しない。GETとSETの間に再列挙やnode変更があれば選択からやり直す。送信後にもnodeを再同定し、host戻り値、転送機会、raw入力、復元結果を別々に記録する。公開資料には識別子の実値やローカルpathを載せない。

## Report `0x10` の読み戻し監査

読み取り専用の `audit-read-paths --report10-readback` を使う。実行時のscan結果、USB interface、descriptor、標準ユーザーのACLを確認し、接続状態を記録する。Receiverのinterface番号は再ペアリング等で変わり得るため、以前のMI番号を固定しない。C652ではGET `0x08`の候補応答を確認してからGET `0x10`へ進む。有線C658ではGET `0x10`だけを送る。GETの結果はioctl戻り値またはerrno、応答長、Report ID一致を記録する。32-byte応答があっても現在設定としての意味は別途検証する。sudoが必要な場合は試験を停止する。

```bash
python3 /tmp/c658-report10ctl.pyz scan --json
timeout --signal=TERM --kill-after=2s 30s python3 /tmp/c658-report10ctl.pyz \
  audit-read-paths --device /dev/hidrawTARGET \
  --audit evidence/source-private-not-in-repository/readback/attempt-1.json \
  --report10-readback
```

監査先directoryを先に作成する。失敗時の再試行は同じ接続・descriptorで1回までとし、新しい監査ファイル名を使う。非公開原本にはraw応答やローカルpathが残るため、公開資料には匿名化した結果だけを移す。

## 有線C658の継続利用確認手順

この手順による確認結果は[hold-open証拠](evidence/hold-open-2026-09/README.md)に記録した。このLinux環境での実用上の動作を確認する。停止までの秒数や、接続直後の数秒間に人が入力できたかは測定しない。既存の `c658-hidraw-hold-open.service` を稼働させたまま確認し、interface別の保持比較は行わない。sudoは使わない。

有線接続した状態で標準ユーザーのターミナルから次を実行する。`root_user` が `true`、対象interfaceが見つからない、権限が不足する、またはserviceが`active`でなければ試験を始めずに記録する。serviceやudev ruleの新規導入・有効化は行わない。

```bash
TEST_START=$(date --iso-8601=seconds)
printf '%s\n' "$TEST_START"
python3 tools/audit_hold_open.py preflight
systemctl --user is-active c658-hidraw-hold-open.service
```

開始時刻を控え、通常どおりカーソル移動、クリック、スクロールができることを確認する。USBケーブルを1回外して再接続し、その後10分以上、普段の使い方でマウスを使用する。急いで入力する必要はない。途中の入力停止、意図しない切断、使いにくさがあれば時刻と症状を記録して終了する。終了時刻と、通常動作を確認できたかを記録する。

終了後に次を実行し、serviceが`active`で、再接続後に対象interfaceの`held`記録があるか確認する。journalに再取得が見えない場合は、通常動作だけで再取得を確認済みにしない。結果はローカルpathなどを除いて[証拠](evidence/hold-open-2026-09/README.md)へ記録する。

```bash
date --iso-8601=seconds
systemctl --user is-active c658-hidraw-hold-open.service
journalctl --user -u c658-hidraw-hold-open.service --since "$TEST_START" --no-pager
```

## Report 0x03 matrix

有線とReceiverで個別に実行する。下記のtargetとinput nodeはscan結果から選ぶ。必須の `core` は17 phase/transport。radialでhost index 1..7、host index 1で全物理ボタン、index 0/215のnegative controlを前後positive controlで挟む。重複するradial/index 1を再利用する。`smoke` は最初の5 phaseだけ、`exhaustive` は全49組合せを含む53 phaseで、明示的に指定した場合だけ実行する。

各phaseで表示された物理ボタンを10回以上press/releaseする。操作完了にEnterは使わない。書き込み後はマウスを動かし、motion-bearing Report `1b` の検出を待つ。開始前に残りphase数、必要操作数、設定された最長所要時間を表示する。既定ではpositive・negativeとも`--phase-seconds`の全時間を記録し、最初に別bitmapが出ても収集を続ける。復元後の動作確認も全時間記録する。時間短縮が必要な場合だけ`--early-exit`を明示する（positive phaseは必要回数達成または想定外入力で早期終了し、転送遅延の切り分けには使用しない）。

```bash
sudo python3 /tmp/c658-report10ctl.pyz probe-report03-matrix \
  --device /dev/hidrawTARGET --input-hidraw /dev/hidrawINPUT \
  --event /dev/input/eventN --profile core --presses 10 \
  --phase-seconds 30 --motion-timeout 30 --baseline-report10-hex '10 ...' \
  --audit /tmp/report03-wired.json --commit
```

Receiver経路では `--device`、`--input-hidraw`、`--event` をReceiver側で選び、監査名を `/tmp/report03-receiver.json` とする。監査JSONはphase前後に永続保存される。中断後は同じdevice・入力node・baseline・時間設定で`--resume`を追加する。条件が一致しない場合は再開しない。未PASS phaseから再実行し、旧試行は `previous_attempts` に残す。以前の早期終了auditも、同じ時間設定なら全時間収集で再開できる。入力が足りない場合は新しい監査ファイルを指定して `--phase-seconds` を増やす。表示と記録は物理ボタン名を使う。

positive phaseのPASSはtransfer待ち、指定回数のpressとrelease、unexpected Report `03` bitmapなし、旧mapping由来入力なし、capture完了をすべて要する。negative PASSはactivity、前後positive PASS、規定時間中の対象Report `03`なしを要する。異なるbitmapは全時間記録後もFAILのままだが、raw frameの時系列から初期の旧bitmapと後半の期待bitmapを区別できる。timeoutやtransfer未確認はINCONCLUSIVE。overall successには必須phaseすべてPASS、baseline送信、transfer待ち、復元後の10回の物理入力確認が必要。

Report `0x10` 対象handleだけを限定確認する場合は `--profile handle` を使う。所有者が復元先として指定した完全32-byte値を非公開のhexテキストファイルに保存し、`--baseline-report10-file` に渡す。このprofileはradialボタン（slot 7）だけをhost index 1へ変更する1 phaseで、復元時は同じボタンの元のdirect動作を確認する。事前に元mappingが既知のdirect動作で、変更後のwire値と異なることを検査する。送信・復元のioctl時刻と戻り値、転送機会、raw HID・evdev入力を監査する。設定書き込みと復元の実施指示を得てから `--commit` を使う。入力nodeと保存値は現時点で確認し、監査をGit除外の `evidence/source-private-not-in-repository/` 以下に保存する。

Receiverのindex 6→7切り替えを調べる場合は `--profile transition` を使う。radialボタンだけをindex 6、7、6、7と変更する2反復・4 phaseで、各phaseは移動による転送機会の後に10回押下・解放する。各index 7送信直後は意図的にマウスを動かさず、既定8秒間に同ボタンを2回押下・解放する。この区間のraw HID・evdev、送信・操作指示のUTC時刻とmonotonic時刻、次の移動と入力を同一監査に残す。ボタン操作自体も転送機会になり得るため、移動前区間を「転送前」と解釈しない。入力評価がFAILでも4 phaseを記録してから指定値を再送し、復元後の物理入力を確認する。全時間収集を必須とし、`--resume`と`--early-exit`は使えない。既定時間の上限目安は約6分、必要操作は復元分を含めて少なくとも54回。新しい監査ファイルをGit除外の `evidence/source-private-not-in-repository/` に指定する。実施前にReceiver接続、現時点のnode、所有者が指定する復元先を確認し、設定書き込みと復元の実施指示を得る。

## Direct code 6

raw HIDとevdevの両方を指定する。所有者指定の完全32-byte復元値が選択ボタンの既知direct mappingを含むことを確認する。probeは既知mapping、code 6、既知mappingの3区間をこの順で送信し、各区間でmotion-bearing Report `0x1b`を待ってから指定ボタンを10回以上押下・解放する。各区間のraw HID、evdev、送信時刻とioctl戻り値を一体で監査し、最後の既知mapping区間を復元確認とする。code 6の特定Linux eventは事前に期待値として指定しない。監査の `hardware_effect` は解釈前の `UNKNOWN` のまま保存する。下記の設定上限は約3分、操作は少なくとも30回。入力nodeと復元値を現時点で再確認し、設定書き込みと復元の実施指示を得てから実行する。

```bash
python3 /tmp/c658-report10ctl.pyz probe-direct \
  --device /dev/hidrawTARGET --input-hidraw /dev/hidrawINPUT \
  --event /dev/input/eventN --slot 7 --action unknown6 \
  --baseline-report10-file /path/to/private/baseline.hex \
  --presses 10 --timeout 30 --motion-timeout 30 \
  --audit /path/to/private/direct-code6.json --commit
```

## Receiver pairing / unpairing

`scan` と `receiver-slots` で現時点の管理handleと全slot snapshotを取り、対象マウスをReceiverモードにしてから `audit-receiver-input` で解除前の左ボタン入力をraw HIDとevdevの両方に記録する。入力が確認できなければ解除しない。pair/unpairは結合状態を変える。操作後は新しいnodeを再走査し、同じ入力監査を取る。個々のCLI監査は別ファイルなので、試験後に時刻・slot・物理入力を照合して一体の成功監査にまとめる。pair CLIの `success` は新しいslotの占有と停止packetを示し、物理入力の成功判定は別途必要。失敗したEPIPEだけでunpair成功扱いしない。

```bash
python3 /tmp/c658-report10ctl.pyz scan --json
python3 /tmp/c658-report10ctl.pyz receiver-slots \
  --device /dev/hidrawMANAGEMENT --audit /path/to/private/before-slots.json
python3 /tmp/c658-report10ctl.pyz audit-receiver-input \
  --input-hidraw /dev/hidrawINPUT --event /dev/input/eventN \
  --presses 10 --seconds 30 --audit /path/to/private/input-before.json

python3 /tmp/c658-report10ctl.pyz unpair \
  --device /dev/hidrawMANAGEMENT --slot SLOT --audit /path/to/private/unpair.json
python3 /tmp/c658-report10ctl.pyz unpair \
  --device /dev/hidrawMANAGEMENT --slot SLOT --expect-raw 'RAW_FROM_FRESH_DRY_RUN' \
  --audit /path/to/private/unpair.json --commit-experimental-unpair

python3 /tmp/c658-report10ctl.pyz scan --json
python3 /tmp/c658-report10ctl.pyz pair \
  --device /dev/hidrawMANAGEMENT --audit /path/to/private/pair.json \
  --commit-experimental-pairing

python3 /tmp/c658-report10ctl.pyz scan --json
python3 /tmp/c658-report10ctl.pyz audit-receiver-input \
  --input-hidraw /dev/hidrawNEW_INPUT --event /dev/input/eventNEW \
  --presses 10 --seconds 30 --audit /path/to/private/input-after.json
```

unpairはdry-runに出た対象slotの8-byte raw値を人が照合し、直後のcommit commandへ入力する。slotまたはraw値が変わっていたら実行しない。pairingモードはpair CLIが終了処理で停止packetを試みる。pair後の物理入力が確認できない場合は、監査を成功として公開せず、slot snapshotと有線またはBluetoothの復旧経路を確認する。node番号は再列挙で変わり得るため各段階で読み替える。通常ユーザーに対象nodeのACLがある環境ではsudoを使わない。

## 復元と緊急時

probeはfinally節で指定したbaselineを再送し、転送待ちと物理入力を監査する。中断後も `baseline_restored` と `baseline_operation_confirmed` を確認する。緊急時はマウスを有線で接続し直し、保存した所有者の完全snapshotを送る。

```bash
sudo python3 /tmp/c658-report10ctl.pyz restore-report10 \
  --device /dev/hidrawTARGET --baseline-report10-hex '10 ...' \
  --audit /tmp/emergency-restore.json --commit
```

`10 ...` は保存した32-byte値で置き換える。このコマンドは送信を監査するが、復元した物理入力は人が確認する。保存値がない場合はfactory defaultを推測せず、試験を停止して元の設定を手動で再構成する。`apply --commit` の既定値は試験fixtureなので、復元値として無条件には使用しない。

監査JSONにはtool git commit、時刻、transport、VID/PID、選択node、descriptor hash、subcommand/options、送信Report `10`、物理ボタン、期待値、必要回数、transfer待ち、raw HID、evdev、実測回数、unexpected input、phase result、復元結果、失敗理由を残す。公開前に個体ID、ユーザー名、ホームディレクトリを削除し、`python3 tools/validate_public.py /tmp/report03-wired.json` で検査する。この検証は失敗監査の内部整合性も受け入れるため、試験の成否はJSONの `success` とphase結果を別途確認する。
