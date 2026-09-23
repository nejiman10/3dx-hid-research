# 高度実機試験手順：Report 0x03・Receiver slot・cache・pairing

## 0. 最初に対象nodeを分離する

```bash
sudo python3 dist/c658-report10ctl.pyz scan --all --json
```

次の3種類を別々に記録します。

- `receiver-c658-handle`: Wireless C658へReport `0x10`を送るnode
- `report03-input`: Input Report `0x03`を読むnode
- `receiver-management`: slot読取りとpairingに使うnode

同じnodeとは限りません。Report `0x10`をmanagement nodeへ送らないでください。

## 1. Receiver slotをread-onlyで取得

この操作はFeature Reportを書き込みません。

```bash
sudo python3 dist/c658-report10ctl.pyz receiver-slots \
  --device /dev/hidrawMANAGEMENT \
  --audit slots-before.json
```

実行内容は`GET_FEATURE 0x43..0x47`です。各responseは8 bytesのraw hexを
必ず保存します。`byte 1=device_type`、`byte 2..7=serial`という解釈は
prior-staticです。`device_type=0x00`をempty、C658候補を`0x59`として表示します。

## 2. Report 0x03のread-only monitor

すでにhost-routed mappingが適用されている場合に使用します。

```bash
sudo python3 dist/c658-report10ctl.pyz monitor-report03 \
  --input-hidraw /dev/hidrawREPORT03 \
  --host-index 1 \
  --timeout 30 \
  --audit report03-monitor.json
```

実機結果により、bitmapは物理slotではなくhost indexに対応します。

```text
host index 1..7 = 01 02 04 08 10 20 40
```

pressとreleaseの両transitionが得られた場合のみ成功です。

### framesが空の場合のraw入力経路診断

`monitor-report03`と`probe-report03`の両方で`frames: []`の場合は、Report IDを
限定せず複数hidrawを同時監視します。この試験は終了時にsoftware baselineを
復元します。案内中にマウスを動かし、radialボタンと他のボタンを数個押してください。

```bash
sudo python3 dist/c658-report10ctl.pyz probe-input-raw \
  --device /dev/hidraw15 \
  --input-hidraw /dev/hidraw14 \
  --input-hidraw /dev/hidraw15 \
  --slot 7 --timeout 30 \
  --audit input-raw-wired.json --commit
```

Receiverでは`--device /dev/hidraw5`とし、scanで得たC652 hidraw候補を
`--input-hidraw`として繰り返し指定します。監査JSONの`reports`はpath、長さ、
先頭byte（暫定Report ID）、raw hexを保存します。`reports: []`ならhidraw層では
入力を観測できていません。

## 3. Report 0x03 end-to-end probe

指定ボタンだけをhost-routed `0x28+N`へ変更し、Report `0x03`のpress/releaseを
確認後、software baselineを復元して通常EV_KEYも確認します。

```bash
sudo python3 dist/c658-report10ctl.pyz probe-report03 \
  --device /dev/hidrawREPORT10 \
  --input-hidraw /dev/hidrawREPORT03 \
  --event /dev/input/event13 \
  --slot 7 \
  --host-index 1 \
  --timeout 30 \
  --audit report03-probe.json \
  --commit
```

案内後にradialボタンを押して離します。復元段階でも同じradialボタンを
押します。Receiver経由では送信直前にマウスを動かしてawakeにしてください。

## 4. Linux SDK send-cache probe

```bash
sudo python3 dist/c658-report10ctl.pyz probe-cache \
  --device /dev/hidrawREPORT10 \
  --slot 7 \
  --audit cache-probe.json \
  --commit
```

確認する順序は次のとおりです。

1. baselineを送信しcacheへ保存
2. 同一baselineを抑止
3. 変更blobを送信
4. host-side fault injectionでcache clear
5. baselineを再送
6. baselineを最終復元

これはLinux SDKで同じpolicyを実装・確認する試験です。Windows 3DxWare内部
cacheをLinuxから観測したものではありません。fault injection時はioctlを発行
しないため、device故障を模擬するものでもありません。

## 5. Code 6の証拠境界

既存の`probe-direct --action unknown6`で、wire `0x0f`に対するfirmwareの
実機挙動を確認できます。C658 default initializerがcode 6を書き込むこと自体は
独立静的解析の事実であり、Report `0x10` readback不能のため、device実機だけで
initializer到達性を証明することはできません。

## 6. Pairing前の必須条件

1. Receiver management nodeが1個だけであること。
2. `receiver-slots`を実行して空きslotが存在すること。
3. 現在のpairing状態とraw responseを保存すること。
4. pairing対象Mouseの物理的なpairing開始手順を準備すること。
5. pairing後にReport `0x10`を確認できる手順が成立していること。

まずdry-runを実行します。これはslot GETだけを行い、Report `0x41`は書きません。

```bash
sudo python3 dist/c658-report10ctl.pyz pair \
  --device /dev/hidrawMANAGEMENT \
  --audit pairing.json
```

表示されるpacketは次のとおりです。

```text
start = 41 02 02 00 00
stop  = 41 02 00 00 00
```

これらはprior-staticであり、独立MSI-only解析では完全packetを再確認できて
いません。

## 7. Experimental pairing

```bash
sudo python3 dist/c658-report10ctl.pyz pair \
  --device /dev/hidrawMANAGEMENT \
  --timeout 60 \
  --poll-interval 1 \
  --expect-type 0x59 \
  --audit pairing.json \
  --commit-experimental-pairing
```

`PAIR`と入力した後、Mouse側の物理pairing手順を行います。CLIは次を実施します。

1. slot 0..4のbefore snapshot
2. pairing start
3. Receiver再列挙を許容しながらslotをpoll
4. 新規occupied slotを検出
5. 成否にかかわらず`finally`でpairing stopを試行
6. 新しいslotとC658 paired-device handleを監査ログへ保存

新規slotを検出しても、bond成立の一次確認です。続けて実際のMouse inputと
Receiver配下Report `0x10`を確認してください。

## 8. Experimental unpair

既存のslot 0を最初の試験対象にしないでください。安全な検証順序は、空きslotへ
試験用Mouseをpairingし、そのとき新規作成されたslotだけをunpairする方法です。

まずdry-runします。GETのみで、解除packetは送信しません。

```bash
sudo python3 dist/c658-report10ctl.pyz unpair \
  --device /dev/hidrawMANAGEMENT \
  --slot NEW_SLOT \
  --audit unpair.json
```

表示された`required_expect_raw`を一字も変更せず、次のコマンドへ指定します。
以下のraw値は例であり、そのまま使用してはいけません。

```bash
sudo python3 dist/c658-report10ctl.pyz unpair \
  --device /dev/hidrawMANAGEMENT \
  --slot NEW_SLOT \
  --expect-raw "44 59 <ANONYMIZED:DEVICE_ID_EXAMPLE:6_BYTES>" \
  --timeout 15 --poll-interval 0.5 \
  --audit unpair.json \
  --commit-experimental-unpair
```

表示内容を再確認し、`UNPAIR NEW_SLOT`と入力します。CLIは次を行います。

1. 指定slotがoccupiedであることを確認
2. 現在のraw 8 bytesが`--expect-raw`と完全一致することを確認
3. `41 04 <slot> 00 00`を1回だけ送信
4. Receiver再列挙を許容しながらslotをpoll
5. 対象slotがemptyになった時点で自動完了
6. before、途中snapshot、afterを監査JSONへ保存

unpairによりHID endpointが切断または再列挙されると、requestが適用済みでも
ioctlが`EPIPE (Broken pipe)`を返す場合があります。v0.5.2以降はこの場合も
失敗確定とはせずslot pollを続け、対象slotがemptyなら成功と判定します。
監査JSONには`packet_sent: false`、`ioctl_error.name: EPIPE`、
`target_empty_confirmed: true`がそれぞれ保存され、transport完了と実機効果を
混同しません。

成功後、同じ試験用Mouseを`pair`で再pairして復旧可能性を確認してください。
`41 04 <slot> 00 00`はprior-staticであり、最初の実機成功までは正式確定では
ありません。試験用Mouseを用意できない場合、現在のslot 0を解除する試験には
再pair不能となるリスクがあります。

## 9. Report 0x03 段階matrix試験

`probe-report03-matrix`は各phaseでReport `0x10`を適用し、指定した全hidrawの
raw reportとevdevの`EV_KEY`を同時記録します。書込み後は案内に従ってボタンを
押さずにマウスを動かしてください。Report `0x1b`のX/Y変化を検出すると転送待ちを
自動完了するため、Enter操作は不要です。`NOW`表示後は名称で案内されたボタンを
既定10回押してください。期待した入力の立上りを指定回数検出した時点でphaseを
自動完了します。負対照は期待入力がないため`--phase-seconds`まで観測します。
終了時および例外時にはsoftware baselineを復元し、復元後もマウス移動を検出して
レシーバ転送機会を確認します。

Receiver実機では固定2秒待っても切替直後の最初の1回だけ旧mappingが出る場合が
ありました。このため固定時間だけを転送完了条件にはせず、書込み後のマウス移動を
必須とします。移動検出後は既定2秒のsettle期間を設けます。settle期間の入力も
`settle_raw_reports`と`settle_key_events`へ分離保存されます。必要時は
`--settle-seconds 3`のように延長できます。移動検出の上限は既定30秒で、
`--motion-timeout`で変更できます。

1. 選択ボタンでdirect right、host index 0/1、unknown direct code 6を比較
2. 選択経路でdirect right対照と、実機確認済みhost index 1を反復
3. 選択ボタンでhost index 0、1、2、7、215を比較
4. left、right、middle、wheel、forward、back、radialを順にhost index 1へ設定

有線（第一～第四段階）：

```bash
sudo python3 dist/c658-report10ctl.pyz probe-report03-matrix \
  --device /dev/hidraw15 \
  --input-hidraw /dev/hidraw14 \
  --input-hidraw /dev/hidraw15 \
  --event /dev/input/event13 \
  --stages 1,2,3,4 --slot 7 \
  --presses 10 --motion-timeout 30 --settle-seconds 2 --phase-seconds 12 \
  --audit report03-matrix-wired.json --commit
```

レシーバー（第一～第四段階）：

```bash
sudo python3 dist/c658-report10ctl.pyz probe-report03-matrix \
  --device /dev/hidraw5 \
  --input-hidraw /dev/hidraw5 \
  --input-hidraw /dev/hidraw10 \
  --input-hidraw /dev/hidraw11 \
  --input-hidraw /dev/hidraw12 \
  --input-hidraw /dev/hidraw13 \
  --event /dev/input/event11 \
  --stages 1,2,3,4 --slot 7 \
  --presses 10 --motion-timeout 30 --settle-seconds 2 --phase-seconds 12 \
  --audit report03-matrix-receiver.json --commit
```

一部だけ再試験する場合は`--stages 3`または`--stages 4`とします。
各`phases[].summary`にはReport ID別件数、Report `0x03`の有無、host index mask、
Report `0x1b`のbutton byte別件数が記録されます。

実機でhost index 1（wire `0x29`）からbitmap `0x01`、host index 2
（wire `0x2a`）からbitmap `0x02`を各10回確認済みです。host index 0
（wire `0x28`）からはReport `0x03`を観測していません。

## 10. Receiver slot 0..4 のread-only監査

組込みコマンドはGET_FEATURE `0x43..0x47`を順に読み、各応答のraw 8 bytesを
改変せず監査JSONへ保存します。書込みは行いません。

```bash
sudo python3 dist/c658-report10ctl.pyz receiver-slots \
  --device /dev/hidraw10 --audit receiver-slots.json
```

SDK checkoutから小さな単体プログラムだけを使う場合：

```bash
sudo PYTHONPATH=src python3 examples/audit_receiver_slots.py \
  --device /dev/hidraw10 --audit receiver-slots.json
```

`/dev/hidraw10`は例です。`scan`で`receiver-management`となったnodeを指定し、
paired-device handleやwired C658 nodeは指定しないでください。

Report `0x17`の`17 64 01`は充電進行中、`17 64 00`は非充電または充電完了と
相関します。正式名称は未確定のため`UNKNOWN_CHARGING_STATE_CANDIDATE`として
のみ記録します。
