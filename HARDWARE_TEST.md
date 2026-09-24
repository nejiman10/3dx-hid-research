# 実機試験手順

## 前提

Linux、Python 3.10以上、対象C658/C652、操作できる物理マウスを用意する。試験はユーザー設定を上書きする。現在設定のreadbackは期待せず、所有者が保存した完全Report `0x10` snapshotを先に別途保管する。SDK同梱の `latest_software_baseline()` は過去の試験fixtureでありfactory defaultではない。継続前に上書きと復元値を確認する。probeには保存値を `--baseline-report10-hex '10 ...'` で渡す。保存値がない場合だけ `--accept-test-fixture` を明示する。

`python3 tools/build_zipapp.py --source sdk/python/src --output /tmp/c658-report10ctl.pyz` でtoolを作る。`sudo python3 /tmp/c658-report10ctl.pyz scan --json` でReport `0x10` target、Report `0x03` input hidraw、input eventを特定する。`/dev/hidrawN` は実行ごとに読み替える。

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

## Direct code 6

raw HIDとevdevの両方を指定する。対象の物理ボタンを操作する。特定のLinux eventは期待しない。監査の `hardware_effect` はUNKNOWNのまま残す。

```bash
sudo python3 /tmp/c658-report10ctl.pyz probe-direct \
  --device /dev/hidrawTARGET --input-hidraw /dev/hidrawINPUT \
  --event /dev/input/eventN --slot 7 --action unknown6 \
  --baseline-report10-hex '10 ...' --audit /tmp/direct-code6.json --commit
```

## Receiver pairing / unpairing

`receiver-slots` で事前snapshotを取り、管理handleを選ぶ。pair/unpairは結合状態を変える。成功時監査は開始・停止packet、before/afterのslot、対象handle、時刻、成功理由を一体のJSONに保存する。失敗したEPIPEだけで成功扱いしない。

```bash
sudo python3 /tmp/c658-report10ctl.pyz pair \
  --device /dev/hidrawMANAGEMENT --audit /tmp/pair.json \
  --commit-experimental-pairing

sudo python3 /tmp/c658-report10ctl.pyz unpair \
  --device /dev/hidrawMANAGEMENT --slot 0 --audit /tmp/unpair.json
```

unpairはdry-runに出た対象slotの8-byte raw値を照合し、同じcommandに `--expect-raw '43 ...' --commit-experimental-unpair` を追加する。対象slotが一致しなければ実行しない。

## 復元と緊急時

probeはfinally節で指定したbaselineを再送し、転送待ちと物理入力を監査する。中断後も `baseline_restored` と `baseline_operation_confirmed` を確認する。緊急時はマウスを有線で接続し直し、保存した所有者の完全snapshotを送る。

```bash
sudo python3 /tmp/c658-report10ctl.pyz restore-report10 \
  --device /dev/hidrawTARGET --baseline-report10-hex '10 ...' \
  --audit /tmp/emergency-restore.json --commit
```

`10 ...` は保存した32-byte値で置き換える。このコマンドは送信を監査するが、復元した物理入力は人が確認する。保存値がない場合はfactory defaultを推測せず、試験を停止して元の設定を手動で再構成する。`apply --commit` の既定値は試験fixtureなので、復元値として無条件には使用しない。

監査JSONにはtool git commit、時刻、transport、VID/PID、選択node、descriptor hash、subcommand/options、送信Report `10`、物理ボタン、期待値、必要回数、transfer待ち、raw HID、evdev、実測回数、unexpected input、phase result、復元結果、失敗理由を残す。公開前に個体ID、ユーザー名、ホームディレクトリを削除し、`python3 tools/validate_public.py /tmp/report03-wired.json` で検査する。
