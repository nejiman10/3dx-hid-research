# Linux統合：udev + systemd user service

この統合は、wired C658で全hidraw interfaceをopenしている間は通常のマウス入力が
維持された実機観測を、再接続対応の常駐回避策として実装します。原因をfirmware、
kernelまたは特定interfaceへ断定するものではありません。C652 Receiverは保持対象
から除外します。

v0.6.1のsystemd user service起動と、保持中のwired USBマウスの通常動作は実機で
確認済みです。USBを抜き差しした後の自動再openは別の確認項目として残します。

## 1. CLIをユーザー領域へ設置

```bash
install -Dm755 dist/c658-report10ctl.pyz ~/.local/bin/c658-report10ctl
~/.local/bin/c658-report10ctl --help
```

## 2. 単発診断

まずsudoなしで実行します。

```bash
~/.local/bin/c658-report10ctl hold-open --once
```

udev rule導入前は何も検出されない、またはpermission errorになる場合があります。
`--once`はopen直後にcloseする診断であり、入力停止の継続的回避にはなりません。

## 3. Linux統合を導入

```bash
./linux/install-linux-integration.sh
```

このスクリプトは次を行います。

1. `69-3dconnexion-c658.rules`を`/etc/udev/rules.d/`へ導入
2. udev ruleをreloadしてhidrawへ再適用
3. systemd user unitを`~/.config/systemd/user/`へ導入
4. `c658-hidraw-hold-open.service`をenableかつstart

udev ruleの導入時だけsudoを使用します。常駐service自体は一般ユーザー権限です。
ruleはC658とC652に`uaccess`を付けますが、hold-open serviceが保持するのはC658だけです。

## 4. 状態確認

```bash
systemctl --user status c658-hidraw-hold-open.service
journalctl --user -u c658-hidraw-hold-open.service -f
```

正常時にはC658の各interfaceについて次の形式が表示されます。

```text
{"event":"held","path":"/dev/hidrawN"}
```

抜くと`released`、再接続すると新しいnodeで`held`が記録されます。

### `status=218/CAPABILITIES`から更新する場合

v0.6.0のsystemd user unitには、一部環境のuser managerでは使用できない
`ProtectKernelModules`、`ProtectKernelTunables`、`ProtectControlGroups`が含まれて
いました。v0.6.1では削除済みです。新しいアーカイブで導入スクリプトを再実行すれば
unitが置換され、failed状態も解除されます。

```bash
./linux/install-linux-integration.sh
systemctl --user status c658-hidraw-hold-open.service
```

古いunitを手作業で直す場合は、`systemctl --user edit`で次を指定しても復旧できます。

```ini
[Service]
ProtectKernelModules=false
ProtectKernelTunables=false
ProtectControlGroups=false
```

反映後：

```bash
systemctl --user daemon-reload
systemctl --user reset-failed c658-hidraw-hold-open.service
systemctl --user restart c658-hidraw-hold-open.service
```

## 5. 動作確認

1. service起動状態でwired C658を接続
2. journalに複数の`held`が出ることを確認
3. 通常のカーソル移動とボタン操作を確認
4. C658を抜き差し
5. 新しいhidraw nodeが自動的に`held`になることを確認
6. 数分操作し、従来の入力停止が再発しないことを確認

問題がある場合はserviceを停止すれば保持handleはすべてcloseされます。

```bash
systemctl --user stop c658-hidraw-hold-open.service
```

## 6. アンインストール

```bash
systemctl --user disable --now c658-hidraw-hold-open.service
rm ~/.config/systemd/user/c658-hidraw-hold-open.service
systemctl --user daemon-reload
sudo rm /etc/udev/rules.d/69-3dconnexion-c658.rules
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=hidraw
rm ~/.local/bin/c658-report10ctl
```
