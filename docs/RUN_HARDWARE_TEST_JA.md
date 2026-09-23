# Report 0x10 実機確認手順

## 1. 接続候補を確認

マウスを動かしてスリープを解除してから実行します。

```bash
sudo python3 c658-report10ctl.pyz scan
```

表示された`/dev/hidrawN`を以後の`--device`へ指定します。番号やUSB
interface番号は固定しません。

## 2. 書込みなしの確認

```bash
python3 c658-report10ctl.pyz build
sudo python3 c658-report10ctl.pyz apply --device /dev/hidrawN
```

`apply`は`--commit`がない限りdry-runです。

## 3. Direct code 6を用いたend-to-end確認

推奨試験はbutton slot 7を一時的にcode 6 / wire `0x0f`へ変更します。

```bash
sudo python3 c658-report10ctl.pyz probe-direct \
  --device /dev/hidrawN \
  --slot 7 \
  --action unknown6 \
  --audit direct-code6-probe.json \
  --commit
```

各段階で次の順に案内されます。

1. マウスを動かしてawake状態にする。
2. Enterを押してReport `0x10`を送信する。
3. 指定した物理button（既定ではbutton 7）を押す。

CLIは以下の3段階すべてでLinux input eventを確認します。

1. software baselineの適用とbaseline入力
2. code 6の適用と`BTN_FORWARD`
3. software baselineの復元とbaseline入力

3段階すべてに成功した場合のみ`PASS`とします。`HIDIOCSFEATURE`の成功だけ
では合格にしません。

code 6の正式名称は不明です。`BTN_FORWARD`は最新のawake Receiver試験で
観測されたLinux eventであり、正式名称の根拠ではありません。

## input event nodeを自動検出できない場合

対象マウスのevent nodeを指定します。

version 0.2.1以降はsysfs探索を深さ制限しています。旧版が最初の案内前に
停止する場合は`Ctrl+C`で終了できます。この時点ではまだReportは送信されて
いません。

## input側hidrawをopen状態に保つ必要がある場合

input eventと同じHID deviceに属するhidraw候補を確認します。

```bash
event_root=$(readlink -f /sys/class/input/event13/device)
find "$event_root/../.." -maxdepth 2 -type d -name 'hidraw*' -printf '/dev/%f\n'
```

確認したnodeを`--keep-open`へ指定します。指定したfdはtarget検証後から
baseline復元完了まで閉じません。

```bash
sudo python3 c658-report10ctl.pyz probe-direct \
  --device /dev/hidraw15 \
  --event /dev/input/event13 \
  --keep-open /dev/hidrawM \
  --slot 1 \
  --action unknown6 \
  --audit direct-code6-slot1-probe.json \
  --commit
```

```bash
sudo python3 c658-report10ctl.pyz probe-direct \
  --device /dev/hidrawN \
  --event /dev/input/eventN \
  --slot 7 \
  --action unknown6 \
  --audit direct-code6-probe.json \
  --commit
```

## Lift Detectionを含む任意設定の適用

以下はLift Detection raw threshold `0x07`を設定する例です。C658 SmartUIでは
非表示のため、C658における物理効果は未確認です。

```bash
sudo python3 c658-report10ctl.pyz apply \
  --device /dev/hidrawN \
  --dpi 1600 \
  --lift 0x07 \
  --wheel inertial \
  --polling 1000 \
  --buttons left,right,middle,backward,forward,unknown6,host:0 \
  --commit
```

通常状態へ戻す場合はsoftware baselineを送信します。これはfactory defaultでは
ありません。

```bash
sudo python3 c658-report10ctl.pyz apply --device /dev/hidrawN --commit
```
