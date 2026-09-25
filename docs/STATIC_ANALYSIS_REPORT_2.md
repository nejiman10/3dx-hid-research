# 3DxWare 10.9.14 静的解析経路 再確認報告

再確認日: 2026-09-24 UTC
対象: 3DxWare 10.9.14 core MSI の保持バイナリ、逆解析結果、抽出台帳
除外: firmware/DFU、実機試験、device firmware 内部実装

## 1. 結論の分類

### 訂正が必要

1. 旧報告の「GET FEATURE 0x08 の到達可能な呼び出しなし」は誤り。
   - `HIDDev.dll` の `CUSBDev::GetPairingCode` 相当 `0x18003ae90` は、Report ID `0x08` または `0x51` を選び、`0x18003afcf` で `HidD_GetFeature` を呼ぶ。
   - `Mgl3DCtlrRPCService.exe` は C652/C664 の `MI_0..MI_4` handle を列挙し、Report ID `0x08`、8 bytes を `DeviceIoControl(IOCTL_HID_GET_FEATURE=0x000B0192)` で取得して logical PID を決める。
   - 旧結論は主に `HIDDev.dll` の `HidD_GetFeature` import xref を対象にしていたが、同関数の `0x08/0x51` 分岐を取り違え、さらに broker の `DeviceIoControl` wrapper を探索対象に含めていなかった。

2. 旧報告の「Report 0x50/0x60 の specific GET producer なし」は範囲不足。
   - managed `3DxPair.exe` に `GetAllTypes`（0x50）と `GetSerialNumber`（0x60）があり、いずれも 8-byte `IOCTL_HID_GET_FEATURE` を発行する。
   - ただし両関数とも `3DxPair.exe` 内の直接 call xref は0件である。関数本体の存在と、通常 UI 経路からの到達性は分けて扱う。

3. SetBlob の送信先を「primary handle、失敗時 secondary fallback」とする説明は、この版の broker 実装と一致しない。
   - broker は15個の flat entry を走査し、logical PID が一致する全 handle に無条件で送る。
   - 最初の成功で停止せず、戻り値による fallback もしない。primary/secondary/slot wrapper の選択ロジックはこの経路にない。

### 維持

1. Universal Receiver の slot 情報は Report `0x43+slot` で取得する。5-slot の通常範囲は `0x43..0x47`。
2. SetBlob は HIDDev の31-byte blobを named pipeで brokerへ渡し、brokerが Report `0x10` または分割 Report `0x0c` を `IOCTL_HID_SET_FEATURE` で送る。
3. Report 0x42 を pairing-table GET に使う経路は、今回再確認した `HIDDev.dll` と `3DxPair.exe` の通常 Universal Receiver 経路にはない。

### 原資料不足または静的解析だけでは未決定

1. Report 0x60 bytes 1..5 のプロトコル上の正式名称。コード上の field 名は `host_id`、関数名は `GetSerialNumber` で矛盾するため、本報告では **5-byte identifier** とする。
2. GET 0x60 の実行時到達性。直接 caller はないが、reflection 等の非直接呼び出しを完全には否定できない。
3. wired aggregate における「primary」の firmware/driver 側定義。broker user-mode codeには primary 選択がない。
4. `3dxhid.sys` より下流の USB control transfer 完了条件。保持物には Windows HID class driver の binary/source がなく、実機も対象外である。

## 2. 対象バイナリ

MSI: `3DxWinCore64.msi`, 50,323,456 bytes, SHA-256 `799a1f3f2c4effc5113a9838f26fa6386b470a24a3ab29330a474a0e7f6b5e99`。

| Binary | Version | SHA-256 | 今回の用途 |
|---|---|---|---|
| `UdDev/HIDDev.dll` | File `10.8.26171.3006`; Product `17.9.14.3006` | `d7b4c5612834db49606881908cf956262b50404ce0cd152635e69bd29a1b8c58` | `HidD_GetFeature` xref、GetPairingCode、SetBlob client |
| `Mgl3DCtlrRPCService.exe` | File `2.0.26171.3006`; Product `17.9.14.3006` | `2db2dc793e16ca7dbaff3ffd4caa32f6f9a509fec65defc94134da31fd93738d` | HID列挙、GET 0x08、SetBlob server、最終 HID IOCTL |
| `3DxPair.exe` | File/Product `2.5.26171.3006` | `658a5f6d60623b48e748dc8b34be40d76a3168881373888ab530632189c15592` | GET 0x43..0x47/0x50/0x60、slot/MI、pair/unpair |
| `Drivers/3DxHID/Win64/3dxhid.sys` | `1.6.7.695` | `a2683f6e196df49c32265084e1751c05b73962dd1cf1e3e09d68e8e636504755` | driver stack 境界の確認 |

インストーラの名称は 10.9.14 だが、主要 native binary の ProductVersion は `17.9.14.3006` である。本報告は上表の hash を同一性の基準とする。

## 3. 調査範囲と旧報告の欠落理由

- 展開650 files、PE 74本の import table を再走査した。`HidD_GetFeature` を直接 import するのは `HIDDev.dll` のみ。
- `HIDDev.dll` の `HidD_GetFeature` 全6 call siteを再解析した。
- `DeviceIoControl` の直接使用を別途調べ、broker の HID GET/SET wrapperを解析した。
- managed `3DxPair.exe` は PE import だけでは P/Invoke の `DeviceIoControl` callを捕捉できないため、ILSpyで全 assembly を再decompileし、method bodyと直接 call xrefを調べた。
- `GetProcAddress` 等による動的解決を全74 PEで完全に否定するところまでは行っていない。「存在しない」は上記 direct import、P/Invoke metadata、確認済み wrapper と call graph の範囲に限定する。

旧報告の主な誤りは、(a) `HidD_GetFeature` というAPI名のxrefに探索を寄せ、同等の HID IOCTL wrapperを別経路として扱わなかったこと、(b) managed `3DxPair.exe` の receiver 管理実装を対象に含めなかったこと、の2点である。

## 4. GET FEATURE 0x08

### 4.1 HIDDev.dll の直接経路

`HidD_GetFeature` の全 call site:

| Call address | Caller | Report ID |
|---:|---|---|
| `0x18001b830` | `GetPairingTable` `0x18001b6d0` | `0x43 + index` |
| `0x1800345f1` | `0x1800344c0` | `0x0a` |
| `0x1800348d9` | `0x1800344c0` | `0x09` 系 |
| `0x18003afcf` | `CUSBDev::GetPairingCode` 相当 `0x18003ae90` | `0x08` または `0x51` |
| `0x18003b94f` | `0x18003b840` | `0x48` |
| `0x18003bd38` | `0x18003bba0` | `0x23` |

`0x18003ae90` の分岐:

- `0x18003aeb2`: object PIDを `0xC652` と比較。
- PID C652 かつ firmware version `>= 1.10` のとき `0x18003aed5` で Report ID `0x51`。
- それ以外は `0x18003aedc` で Report ID `0x08`。
- HID descriptor cacheから該当 report lengthを探し、`0x18003afc4` で byte0へIDを書き、object先頭のhandleを `0x18003afcf` の `HidD_GetFeature` へ渡す。
- 成功時は `0x18003afea` から parser `0x180016e10` へ渡す。

確認した caller xref は `0x180015f18`, `0x18001cb69`, `0x18001cd63`, `0x18001cf46`, `0x18001d15c`, `0x18001df75`, `0x18001e146`, export `UdDevOpenName` 内 `0x18002588f`。したがって「parserだけ存在し callerなし」ではない。

### 4.2 broker の C652 paired-device handle 経路

`Mgl3DCtlrRPCService.exe` の経路:

```text
HID enumeration 0x1400048b0
  -> VID 0x256f確認 0x140004980..0x14000498c
  -> physical PID C652/C664確認 0x140004992..0x1400049a8
  -> MI番号parser 0x1400043a0
  -> MI < 5 gate 0x1400049d4..0x1400049dd
  -> logical-PID resolver 0x140004500 at 0x140004a2d
  -> buffer[0] = 0x08 at 0x140004527
  -> GET wrapper 0x140001330 at 0x14000452d
  -> DeviceIoControl(handle, 0x000B0192, ..., out=8) at 0x1400013af
  -> response byte1を logical PIDへmap 0x14000454b..0x14000460d
  -> entry+0x12へ logical PID保存 0x140004e36..0x140004e3b
```

`0x000B0192` はこの assembly自身でも `3DxPair.exe` と同じ `IOCTL_HID_GET_FEATURE` 値として使われている。broker wrapper `0x140001330` の direct caller xref は `0x140004500` の `0x14000452d` のみで、同 wrapper からの GETは常に8 bytesである。

結論: C652の `MI_0..MI_4` handle、すなわち paired-device interface 候補に対する GET 0x08 は実在する。旧報告の結論は撤回する。

## 5. Report 0x50 と 0x60

### 5.1 旧報告で実際に調べていた範囲

旧報告の否定は、主に以下に限定されていた。

- `HIDDev.dll` の `HidD_GetFeature` import全xref。
- `HIDDev.dll` の specific input-report dispatcher。
- C658/C652通常 service pathで見つかった native call graph。

この範囲では、0x50/0x60の direct `HidD_GetFeature` callは確かに存在しない。この限定結論は維持する。しかし `3DxPair.exe` の managed P/Invoke経路を含めた「インストール全体に存在しない」という表現は誤りである。

### 5.2 Report 0x50

`3DxPair.exe`, `EuclidControl.GetAllTypes`, RVA `0x5acc`:

```text
byte[8]を確保
  -> byte0 = 0x50 (IL_0012..IL_0014)
  -> HidClientGetFeature(handle, buffer, sizeof(GetAllTypesStruct)) (IL_0034)
  -> DeviceIoControl(IOCTL_HID_GET_FEATURE=0x000B0192) in
     HidClientGetFeature RVA 0x55c0, IL_0085
```

8-byte layoutは `[0]=report_id`, `[1..5]=device_type_by_slot[5]`, `[6..7]=flags (UInt16, little-endian host layout)`。method bodyは responseをこのstructへmarshalする。

ただし full decompileの direct call検索では `GetAllTypes` の callerは0件。よって **GET実装は確認、通常 UI からの到達性は未確認** とする。

### 5.3 Report 0x60

`3DxPair.exe`, `EuclidControl.GetSerialNumber`, RVA `0x594c`:

```text
byte[8]を確保
  -> byte0 = 0x60 (IL_000b..IL_000d)
  -> HidClientGetFeature(handle, buffer, 8) (IL_0024)
  -> DeviceIoControl(IOCTL_HID_GET_FEATURE=0x000B0192) in
     HidClientGetFeature RVA 0x55c0, IL_0085
```

declared layoutは `[0]=report_id`, `[1..5]=5-byte field`, `[6..7]=version (UInt16)`。値の利用を追うと、bytes 1..5だけを reverseし、各byteを `ToString("X")`（zero paddingなし）で連結して返す。bytes 6..7の `version` はこのmethodでは読まれない。

したがって名前だけで決めずに言えることは次の通り。

- 5-byte fieldは、method内で表示用の16進identifier文字列へ変換される。
- field declarationは `host_id`、method名は `GetSerialNumber` である。
- protocol上の正式意味を host ID または serial number のどちらかに断定するだけの利用先はない。
- `GetSerialNumber` 自体の直接 callerは0件で、返値の後続 consumerも確認できない。

本報告ではこのfieldを **5-byte identifier** と記す。GET実装の存在は確認、意味と到達性は未決定である。

## 6. SetBlob の送信先

### 6.1 clientからbroker

`HIDDev.dll`:

```text
SBHID_SendPIDConfig_2DMouse 0x180030e90
  -> 31-byte blobを構築
  -> 0x18003179d: blob pointer
  -> 0x1800317a2: command=6 (SetBlob)
  -> 0x1800317a7: object+0xc80 の logical PID
  -> pipe client 0x1800655e0 at 0x1800317af
  -> 36-byte packet = command:u16, logical_pid:u16, blob[31], padding
  -> WriteFile(pipe, 36) at 0x1800656be
```

### 6.2 broker受信からsend dispatcher

`Mgl3DCtlrRPCService.exe`:

```text
pipe server setup 0x1400016e0
  -> callback 0x140005230
  -> event type==3, size>=36 at 0x140005239..0x140005242
  -> packet parser 0x140003990 at 0x140005247
  -> command 6 branch 0x140003aa6
  -> per-logical-PID 48-byte config cacheへpayload copy
  -> dispatcher 0x140002ea0 at 0x140003b39
```

PID別dispatchにより、full config pathは `0x140002f5e..0x140002fa7` から sender `0x140005170`、split pathは `0x140002fca..` から sender `0x140004fa0` へ進む。対象 logical PIDによっては default/no-send caseもある。

### 6.3 handle選択と最終HID API

full path `0x140005170`:

- 15 entries (`0x438 / 0x48`) を全走査。
- `entry+8 != NULL` を `0x1400051a7` で確認。
- `entry+0x12 == logical PID` を `0x1400051af` で確認。
- 一致するたび `entry+0` のhandleを取り、`0x1400051ec` で `0x140005080` を呼ぶ。
- `0x140005080` は Report ID `0x10`、長さ19または32を構築し、`0x1400050dd` / `0x140005159` から SET wrapper `0x140001230` へ渡す。

split path `0x140004fa0` も同じ15 entriesを全走査し、`0x140004fee` で logical PIDを比較する。一致する各handleへ Report ID `0x0c`、8 bytesを `0x140005038` から `0x140001230` へ渡す。

最終 user-mode HID API:

```text
SET wrapper 0x140001230
  -> DeviceIoControl(handle, 0x000B0191, input_buffer, length, ...)
     at 0x1400012a6
  -> overlapped completion + exact byte-count check
```

`0x000B0191` は `IOCTL_HID_SET_FEATURE`。この先は Windows HID class/driver stackであり、保持物だけからUSB control transferまでの全内部経路は再確認不能である。

### 6.4 requested cases

| 項目 | 判定 | 根拠 |
|---|---|---|
| logical PIDに一致するhandle | 確認 | entry `+0x12` 比較。全一致handleが対象。 |
| wired aggregateのprimary handle | 明示選択なし | brokerにprimary flag/first-only branchなし。1件だけ一致すれば結果的に1件だが、primary概念ではない。 |
| Receiverのpaired-device handle | 確認 | C652/C664 MI<5を列挙し、各handleのGET 0x08 response byte1からlogical PIDをentry+0x12へ保存。後の一致走査で対象。 |
| secondaryへのfallback | なし | send結果で次候補を選ぶ分岐なし。全一致handleへ最初から送る。個別send戻り値もloop制御に使わない。 |
| slot wrapper | SetBlob経路にはなし | brokerはflat 15-entry tableだけ。slot番号はSetBlob packetにもsender引数にもない。 |

## 7. Report 0x43..0x47、5 slot、MI_n

`3DxPair.exe`, `UniversalReceiver.EnumerateConnectedDevices`, RVA `0xe350`:

- constructor default `MaxSlotCount=5`。
- `min(MaxSlotCount, 5)` 回のloopで slot `0..4` を処理。
- `EuclidControl.GetSlotInfo` RVA `0x5a30` は8-byte bufferのbyte0を `0x43+slot` にし、RVA `0x55c0` の GET wrapperへ渡す。
- `GetInfo` layoutは `[0]=report_id`, `[1]=device_type`, `[2..7]=serial_number[6]`。
- consumerはbytes 2..7を順方向の big-endian hex文字列としてUInt64化し、非zeroかつ `< 0xFFFFFFFFFF` の場合に `char(device_type) + decimal_value` のserial表示を作る。

slotとMIの対応:

- `UniversalReceiver.GetInterfaceFromSlotNumber` RVA `0xe34b` は引数をそのまま返す。
- `UniversalReceiver.GetSlotFromInterfaceNumber` RVA `0xe34b` も引数をそのまま返す。
- enumerationはdevice instance IDの `&MI_nn` をparseし、このidentity mappingでslotを選ぶ。

従って通常 `UniversalReceiver` classでは `slot 0..4 <-> MI_0..MI_4` が静的に確認できる。broker側の C652/C664 gateもMI<5で一致する。ただし派生 receiver classがmappingをoverrideする可能性は class別に評価が必要であり、SetBlob broker自身はslot mappingを使わない。

`HIDDev.dll!GetPairingTable` `0x18001b6d0` も `0x18001b820` で `0x43+index` を作り、`0x18001b830` で `HidD_GetFeature` を呼ぶ。ただしこのnative functionのloop上限は7 (`index < 7`) で、UIの5-slot制限とは同一ではない。5-slotを根拠にnative loopまで5回と記述してはならない。

## 8. pair/unpair の成功判定

### unpair

`3DxPair.exe`:

```text
OverviewPanel.Device_DeleteClicked RVA 0xc140
  -> ReceiverInfo.FreeSlot(slot)
  -> UniversalReceiver.FreeSlot RVA 0xeac4
  -> EuclidControl.FreeSlot RVA 0x5b78
  -> [0x41, 0x04, slot, 0, 0] を5 bytesで
     HidClientSetFeature RVA 0x571c
  -> DeviceIoControl(IOCTL_HID_SET_FEATURE=0x000B0191)
```

成功は `DeviceIoControl/GetOverlappedResult` がtrueかつ returned byte countが要求sizeと一致したことだけで判定する。slotが実際に空になったことをGETし直して確認する処理はこのcall chainにない。UI callerはfalse時にlogを出すだけである。

### pair

- pairing mode SETの成功は `ChangePairingMode` RVA `0x5ce4` -> `HidClientSetFeature` のI/O完了とbyte count一致。
- `PairingPanel.SetPairingMode` RVA `0xa1b4` はそのbool returnを破棄するため、UI上のpair成功表示条件そのものではない。
- Universal Receiver側では `DeviceContext.ThreadProc` RVA `0x251c` が input report `0x17` または `0x1b` を読み、初回の `byte1 != 0` で `OnDeviceConnected` -> `PairingPanel.OnPairingDone` RVA `0xa0d8` を発火する。
- Integrated C664側では `IntegratedReceiverC664.ThreadProc` RVA `0xf248` が Report `0x1b` を読み、`byte1 == 1` をsuccess、それ以外をerror codeとして扱う。

従ってpairの「SET要求が通った」と「新しいpaired deviceを成功としてUIへ通知した」は別判定である。firmware内部でpairingが成立した条件は静的host解析だけでは決定できない。

## 9. 否定範囲の明記

今回「ない」としたものと探索範囲:

- `HIDDev.dll` からの direct GET 0x50/0x60: 同DLLの `HidD_GetFeature` 全6 xrefを調査。該当なし。
- broker GET wrapperからの0x50/0x60: `0x140001330` の direct caller全xrefを調査。callerは `0x140004500` のみでbyte0は0x08固定。
- `3DxPair.exe` の `GetAllTypes` / `GetSerialNumber` direct caller: ILSpy full-project decompile後のmethod call検索で0件。reflection/外部instrumentationは未排除。
- SetBlob primary/secondary fallback: `0x140003990`, `0x140002ea0`, `0x140005170`, `0x140005080`, `0x140004fa0`, `0x140001230` と15-entry enumerationを調査。該当branch/fieldなし。
- SetBlob slot wrapper: 36-byte pipe packet、broker config table、両senderの引数とentry field使用を調査。slot indexの伝達・照合なし。

## 10. 最終整理

| 論点 | 最終判定 |
|---|---|
| GET 0x08 | **訂正**。HIDDev direct pathとbroker C652/C664 MI pathの両方に存在。 |
| GET 0x50 | **訂正**。3DxPairに8-byte GET実装あり。ただしdirect callerなし。 |
| GET 0x60 | **訂正**。3DxPairに8-byte GET実装あり。ただしdirect callerなし。 |
| 0x60 5-byte field | **未決定**。値は逆順hex identifierとして返る。host_id/serialの正式意味は断定不可。 |
| SetBlob receiver child | **確認**。GET 0x08でlogical PIDを付与されたC652 MI handleが一致送信対象。 |
| SetBlob primary/fallback | **統合資料の表現を訂正**。primary選択・secondary fallbackではなく、logical PID一致全handleへbroadcast。 |
| 0x43..0x47 | **確認**。8 bytes = report_id, device_type, serial_number[6]。 |
| five slots / MI_n | **確認**。UniversalReceiverではslot nとMI_nがidentity mapping、n=0..4。 |
| pair/unpair success | **確認範囲を限定**。SET成功はI/O完了。pair UI成功は後続input/connection event。unpair後のGET verificationなし。 |

以上は保持されていた同一hashのバイナリと再生成した逆解析結果に基づく。原資料がない firmware/HID class内部と実機挙動については結論を拡張しない。
