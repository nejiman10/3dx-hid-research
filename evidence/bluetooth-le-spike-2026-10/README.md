# Bluetooth LE接続の限定観測（cadratスパイク、2026-10-08）

cadratの試作ブランチ（`spike/everything-works-cr6uv0`、commit `fda56a3`〜`8b7f6a2`、マージしない）を利用者のPCで実行し、Bluetooth LE（HOGP）接続のC658について読み取り・入力・設定送信を試した記録。結果は利用者がプロジェクトの会話に貼った端末出力と報告を本文として転記した。raw監査ファイル（時刻付きJSON）は作っていない。機器ID、シリアル番号、Bluetooth address、USB topologyの実値は載せず、一致・不一致だけを残す。

試作の実装はcadratのもので、本リポジトリのSDKでは再現していない。以下は1台のマウス・1台のReceiver・1台のPC・1日の観測であり、試験計画（[HARDWARE_TEST.md](../../HARDWARE_TEST.md)）に沿って事前に回数や判定基準を決めたものではない。

## 1. 接続と列挙（読み取り）

事前確認（2026-10-06、読み取りのみ）: `bluetoothctl info` にHID over GATT（`00001812`）があり、C658のhidrawは2つとも `/sys/devices/virtual/misc/uhid/0005:256F:C658.*` の下にあった。利用者側でdescriptorを本リポジトリのSDK（`hid_descriptor.py`、`0a66eb5`）で解析した結果は次のとおり。descriptor本体は本リポジトリに収録していない。

| node | Feature wire長 | Input wire長 | 比較 |
| --- | --- | --- | --- |
| 入力用 | なし | `0x1b`=9 | 有線C658 MI_00とバイト単位で同一と報告 |
| 設定用 | `0x10`=32、`0x08`=8 | `0x03`=2、`0x17`=3、`0xff`=2 | 有線MI_01の `0x03`/`0x17`/`0x10`/`0x08` 部分と同一と報告。MI_01の `0x0b`/`0x0d`/`0x1a` Featureと `0x0e`/`0x0f`/`0x20` はない。先頭にvendor collection（usage page `ff00`、Input `0xff`）がある |

試作の `list --nodes --redact` を、Receiver、Bluetooth、有線の各接続で実行した（転記、hidraw番号は当時のもの）。

```text
# Bluetooth接続中
#  MOUSE      ACTIVE     ROUTES
1  c658:id-1  bluetooth  bluetooth (/dev/hidraw17, BLE)
                         receiver standby (recv:port-…, slot 3, /dev/hidraw14, MI_03)
NODE           IF     PRODUCT    STATUS
/dev/hidraw11  MI_00  256f:c652  candidate (management)
…
/dev/hidraw14  MI_03  256f:c652  candidate (receiver setting, management, id id-1)
/dev/hidraw16  BT     256f:c658  rejected (no-feature-0x10)
/dev/hidraw17  BT     256f:c658  candidate (bluetooth setting, id id-1)
```

- 設定用nodeへのGET `0x08`（長さ8）は成功し、`resp[1]` は `0x59` だった。
- `--redact` は1つの出力の中で同じ値に同じ `id-N` を振る。Bluetooth設定nodeとReceiver MI_03のGET `0x08` bytes 2..7は同じ `id-1` だった。有線接続時の有線MI_01も、Receiver MI_03と同じ `id-1` だった。3経路の値は一致した。
- Bluetooth接続中も有線接続中も、Receiver C652 MI_03は列挙され、GET `0x08` に応答した。Bluetooth接続中に有線C658のnodeはなく、有線接続中にBluetoothのnodeはなかった。
- Bluetoothの設定nodeを開くには、uhidの下にUSBの属性がないため、`KERNELS=="0005:256F:C658.*"` で照合するudevルール（`TAG+="uaccess"`）を別に追加した。

## 2. シリアル番号表示との比較

GET `0x08` bytes 2..7をbig-endianの整数とし、`char(resp[1])` と10進表記を続けた文字列（[再確認報告 §7](../../docs/STATIC_ANALYSIS_REPORT_2.md)が純正ソフトのslot応答の表示方法として述べる形）を試作が表示した。利用者は、この文字列がマウス本体のラベルのシリアル番号と一致したと報告した。bytes 2..7の16進表記はラベルにないと報告した。値は記録しない。

## 3. 電池（power_supply とInput Report `0x17`）

- Receiver、Bluetooth、有線のどの接続中も、`/sys/class/power_supply/` のHIDの電池は、親がC652 MI_03のものだけだった。Bluetooth（uhid）と有線C658のHID deviceを親とする電池はなかった。
- その `capacity` は3回とも `62`、`status` は `Discharging` だった。Bluetooth・有線接続中にもこの値が出ていたが、どの経路のReport `0x17` に由来するかは区別していない。
- Bluetooth接続中に試作の `monitor` で60秒間、設定用nodeとReceiver MI_03を `read(2)` で読んだ。Bluetoothの設定用nodeから `17 3e 00` を12回取得した（byte 1の `0x3e` は十進62）。間隔は約1.5秒の対と、約4.5〜16.5秒の間隔が混在した。同じ60秒間、Receiver MI_03からは何も取得しなかった。
- 有線接続中のraw Report `0x17` はこの試作では取得していない。

## 4. 設定送信（Report `0x10`）

利用者の明示的な指示で、Bluetoothの設定用nodeへ32-byteのReport `0x10` を送った。送信の直前に同じfdでGET `0x08` を照合し、`HIDIOCSFEATURE(32)` を1回送った。

- DPIだけを変えた送信（DPI 1400 → 800）の後、利用者はポインタが遅くなったと報告した。その後のD-Bus経由の送信でDPI 800 → 200 → 1400を順に送り、切り替わりを確認したと報告した。送信したwire値の例（DPI 800、ボタンの割り当てとpolling dividerは利用者のTOMLのまま）:

  ```text
  1000101f01ff000000000000000000000000000a0b0c0c0e0d29001e00000001
  ```

- radialにhost index 1（wire `0x29`）を割り当てたReportを送った後、Bluetooth接続中のradial押下で、設定用nodeからReport `0x03` の押下と解放が3組届いた（試作のデーモンが `0x03` bitmapを解析して出したsignalとして確認。raw frameは記録していない）。割り当て前（radialが `0x0c`）は、全ボタンを押してもReport `0x03` は届かなかった。
- 利用者は、Bluetoothで送った設定は、マウスの電源を入れ直したり別の経路で接続し直したりすると消える様子だと報告した。また、wheel（慣性）は有線とReceiverでは無効に設定しているが、Bluetoothで接続すると毎回有効になっていると報告した。これらの前後でdeviceからの読み戻しはしておらず、送信と再接続の時刻も記録していない。

## 5. hold-open

利用者は、Bluetooth接続中にどのプロセスもhidrawを開いていない状態でも、入力が止まらなかったと報告した。この状態の継続時間と操作回数は記録していない。

## 6. 限界

- 1台・1日の観測で、raw監査ファイルはない。効果（DPI、慣性、入力の継続）は利用者の体感・報告である。
- Bluetoothの設定が消える条件（電源、経路の切り替え、Bluetoothの再接続のどれか）と、毎回の慣性有効が初期値によるのかは区別していない。
- Bluetoothへの送信が有線・Receiverの設定に影響するかは調べていない。
- descriptorの解析結果は利用者側の報告で、本リポジトリにdescriptor fixtureとして収録していない。
