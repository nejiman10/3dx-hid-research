# 3DxWinCore64.msi 独立静的解析報告

解析日: 2026-09-22 UTC  
対象: 3DxWare 10.9.14 core MSI、CadMouse Compact Wireless (USB PID `C658`) および Universal Receiver (USB PID `C652`)  
範囲: USB/HID通常設定、button設定、Receiver管理通信  
除外: DFU、firmware update、Receiver内部radio packet、暗号  

## 結論要約

最優先の Direct Action について、C658 の通常profile/UIから device向けに生成できる名前付き action は code 1～5であり、wire値は `0x0a～0x0e` である。C658 default初期化には code 6 / wire `0x0f` も実到達するが、binary内に code 6 のenum名を直接結び付けるsymbolはないため、名称は断定しない。C658の第7 buttonがradial-menu usageであり表示文字列が存在することは相関証拠としてのみ扱う。

`0x12～0x27` は `wire=0x09+action_code` という算術から code 9～30を逆算できるだけで、3DxServiceのprofile mapper、default C658 config、capability/UI pathのどこにもproducerがない。各値を個別に調査した結果、名称は `UNKNOWN`、C658では `STATICALLY_UNUSED_OR_UNREACHABLE` と判定した。enum/文字列を推測で補完していない。

Report 0x10 payload generatorは31 bytesをzero初期化し、変更するのは blob offsets 1 (DPI), 2 (lift effective threshold), 3～6 (wheel mode constants), 18～24 (7 button mappings), 26 (`0x1e` fixed), 30 (polling divider)だけである。buttonはdirectなら `0x09+code`、host-routedなら `0x28+code`。同一31-byte blobはcache比較で送信抑止され、成功時のみcacheへ保存される。失敗時はcacheがzero clearされるが、その関数内にwake/retry/backoff/delayはない。

C652 pairing tableは `GET_FEATURE` Report `0x43+slot` で取得する。Report 0x42の機能的GET/SET call pathは見つからない。HID API importの全xrefを調べた結果、Report 0x08をGETするcall siteもないため、そのresponse bytes 2～7を使う到達可能なpathもない。Report 0x50 byte6～7およびReport 0x60各byteについても、C658/C652通常管理pathにspecific compare/store/display branchは見つからない。generic HID descriptor parserの存在は、個別reportの機能実装とは数えていない。

## 対象ファイルとSHA-256

MSI:

- `3DxWinCore64.msi`
- size: 50,323,456 bytes
- SHA-256: `799a1f3f2c4effc5113a9838f26fa6386b470a24a3ab29330a474a0e7f6b5e99`
- MSI metadata: x64 Installation Database; Title `3Dconnexion 3DxWinCore`; WiX 3.11.2.4516; MSI timestamps 2026-06-20

主要証拠:

| File | SHA-256 | Role |
|---|---|---|
| `3DxService.exe` | `a7debf2ded0b85fa2f6961dde0956803564507199fb0667f7faab61fd1470479` | profile parse、action mapping、per-device config |
| `UdDev/HIDDev.dll` | `d7b4c5612834db49606881908cf956262b50404ce0cd152635e69bd29a1b8c58` | Report parser、31-byte generator、HID management |
| `3DxSmartUi.exe` | `d89f61d4430824c7b7ee1b8c83d3f96a12b8a3d757c17f499da5de22382b78ff` | UI capability gate、Global.xml writer |
| `Cfg/Base.xml` | `c59523ae876de1f81fab1fa84218c00e14ff1d92b8bea57fe7265e0999ed0660` | PID/class/button masks/actions |
| `Cfg/Global.xml` | `664eaef15ee56c684b2f5f1877920626608e6e5e31ff60091d5b6e29c0f5be1e` | inherited defaults |
| `Drivers/3DxHID/Win64/3dxhid.sys` | `a2683f6e196df49c32265084e1751c05b73962dd1cf1e3e09d68e8e636504755` | broker/kernel boundary補助調査 |

完全な抽出物一覧と各SHA-256は作業付属物 `file_inventory.csv` / `file_inventory_sha256.txt` に保存した。

## 展開・分類結果

- 展開ファイル数: 650
- 展開総量: 約80 MiB
- PE: 74
- native PE: 42
- managed PE: 32
- `3DxService.exe`: PE32+ x86-64 native、2,491,824 bytes
- `3DxProfileServer.exe`: PE32+ x86-64 native、1,834,928 bytes
- `UdDev/HIDDev.dll`: PE32+ x86-64 native、949,168 bytes
- `3DxSmartUi.exe`: PE32 x86 managed、2,188,208 bytes
- `3DxPair.exe`: PE32 x86 managed、1,108,400 bytes

PDB本体は含まれないが、native binariesにはbuild path文字列が残る。`HIDDev.pdb` と `3DxService.pdb` のrelease build path、および 2026-06-20 build timestampを確認した。

## 使用ツール

| Tool | Version / use |
|---|---|
| msitools `msiextract` | 0.103; MSI展開 |
| 7-Zip | 23.01; container確認 |
| cabextract | 1.11 |
| GNU `file`, `strings`, `sha256sum`, `rg` | format/string/hash/xref候補 |
| GNU objdump | Binutils 2.42; native disassembly |
| radare2 | 5.5.0; function/xref/call graph/disassembly |
| ILSpyCmd | 9.1.0.7988; managed decompile |
| .NET SDK/runtime | 8.0.130 / 8.0.30 |
| Python | 3.12.14; inventory補助 |
| pefile / dnfile / olefile / capstone | 2024.8.26 / 0.18.0 / 0.47 / 5.0.9 |

Linuxだけを使用し、`/dev/hidraw*`, usbfs, libusb, hidapi、Windows VM/Wineを開いていない。実機へのHID read/writeは行っていない。

## 抽出・解析方法

1. MSI自身のsize/SHA-256/metadataを採取。
2. `msiextract`で全内容を展開し、各fileのsize/SHA-256/MIMEを台帳化。
3. PE CLR directoryとmetadataを見てmanaged/native分類。
4. 全PEからASCII/UTF-16LE stringsをoffset付き抽出。XML/profile/resourcesを横断検索。
5. `3DxSmartUi.exe`をILSpyでC#へdecompileし、UI event、capability gate、XML writesを追跡。
6. `3DxService.exe`でaction ID比較関数、direct/host discriminator、profile parser、per-device config struct writes、callersを逆解析。
7. `HIDDev.dll`で2D generator、Input Report parser、全 `HidD_GetFeature` / `HidD_SetFeature` import xrefs、pairing table、cache/send branchを逆解析。
8. Base.xmlのC658/C652 capability・C658 ReportID03/masksとnative call pathを相互参照。
9. 値が算術上生成可能なだけの場合と、C658 source→generator→sendまでのpathがある場合を分離。

## Direct Action

### 変換式

`HIDDev.dll!SBHID_SendPIDConfig_2DMouse` は7 entriesを処理する。entryは16-byte strideで、host flagが config `+0x60+i*0x10`、action codeが `+0x64+i*0x10`。

```text
if host_flag == 0:
    wire = (0x09 + action_code) & 0xff
else:
    wire = (0x28 + action_code) & 0xff
blob[18 + i] = wire
```

`3DxService.exe!DownloadToKernelForSingleDevice` はprofile actionがdirect-capableならhost flag=0としてmapperを呼び、そうでなければhost flag=1としてhost action indexを格納する。後者が`0x28+N`形式である。deviceにはrouting byteを送るが、実actionは3DxService側で処理する。

### 名前付きdirect codes

| code | wire | internal ID | display resource | C658 reachability |
|---:|---:|---|---|---|
| 1 | 0x0a | `HIDMouse_Left` | Primary Mouse Function | profile/defaultから到達 |
| 2 | 0x0b | `HIDMouse_Right` | Secondary Mouse Function | profile/defaultから到達 |
| 3 | 0x0c | `HIDMouse_Middle` / `HIDMouse_WheelButton` | Middle Mouse Function / Mouse Wheel Button | profile/defaultから到達 |
| 4 | 0x0d | `HIDMouse_Backward` | Backward Mouse Button | profile/defaultから到達 |
| 5 | 0x0e | `HIDMouse_Forward` | Forward Mouse Button | profile/defaultから到達 |
| 6 | 0x0f | `UNKNOWN_DEFAULT_BUTTON7` | radial-menu表示との相関のみ | C658 defaultから到達、profile mapperからは生成不可 |

`HIDMouse_RadialMenu` はmapper内で文字列比較されるが、結果にかかわらずcode 0でreturnする。したがって「文字列がある」ことを code 6 のenum名の証明には使用していない。一方、C658 default 7th entryにはcode 6が書かれ、Base.xmlの第7 usageはradial menuなので、相関はmedium confidenceで記録した。

### 0x12～0x27

wire `0x12～0x27` はcode `9～30` に一対一対応する。しかし、C658 pathでこれらを作るcase/default/profile valueがない。`direct_action_table.csv` は30 wire valuesを省略せず個別行にし、0x12～0x27の各行に「producer/name/display stringなし」を記録した。これはdevice firmwareがその値を解釈しないという断定ではなく、3DxWare 10.9.14 MSIのC658通常設定pathから送れないという静的判定である。

## Report 0x10 configuration generator

### 31-byte blob

31 bytesは最初に全zero。その後のwrite-setは以下だけ。

| Blob offset | Report wire offset* | Field |
|---:|---:|---|
| 0 | 1 | zero/reserved |
| 1 | 2 | DPI encoding |
| 2 | 3 | effective lift threshold (`0x1f` when disabled) |
| 3～6 | 4～7 | wheel mode constants |
| 7～17 | 8～18 | zero/reserved |
| 18～24 | 19～25 | button 1～7 mapping |
| 25 | 26 | zero/reserved |
| 26 | 27 | fixed `0x1e` |
| 27～29 | 28～30 | zero/reserved |
| 30 | 31 | polling-rate divider |

\* wire offsetは32-byte Feature Reportのbyte0をReport ID `0x10`とした位置。31-byte payloadのstore自体はnative codeで確定しているが、broker/kernel boundaryの最終Report-ID前置にはsymbolがないため、この列だけはmedium confidence。詳細は `report10_fields.csv`。

### C658 settings

- DPI: generatorに到達。50 unitごとのbyte、range clampあり。UI側の完全なDPI editor call chainは今回確定できず、mutable判定はservice config入力としてのもの。
- Lift Threshold: generatorは一般2D mouseとして存在。C658のSmartUiでは `HasLiftDetection("c658") == false` なのでcontrol非表示。Global.xml inherited defaultや手編集可能性と「C658 UIで選択可能」を区別した。
- Wheel mode: `MouseWheelInertia` checkboxからuser Global.xmlへ保存し、generatorのnormal/inertial branchに到達。
- Polling rate: 125/250/500/1000 UI radioからUpdateRateへ保存し、divider 8/4/2/1となる。
- Buttons: 7 fields。direct vs host-routedは前述のbase加算で区別。

### Input Report 0x03

Base.xmlのC658はReport ID `03` とmasks `0001,0002,0004,0008,0010,0020,0040` を7 HID buttonsへ対応させる。HIDDevのgeneric parserはpacket[0]をdescriptor entryのReportIDと比較し、packet[1]から最大4 bytesをlittle-endian bitmap化する。entryのpress/release masksと前回bitmapを比較し、transition時にevent helperを呼ぶ。これにより Report 0x03 bitmapとbutton routingのhost側関係は静的に確認できた。

## Receiver管理通信

### Report 0x42

`GetPairingTable` はcontrol deviceがopen済みであることを確認し、HID report descriptorから0x43 entryのreport lengthを取得する。slot loopでreport byte0へ `0x43+slot` を設定し、`HidD_GetFeature(handle, buffer, report_length)` を呼ぶ。したがって確認された操作はGET、IDは0x43～、lengthはdescriptor-derived (`report payload length + 1`)。

Report 0x42については、HIDDev内のHID API全xrefとimmediate producerを調査したが、機能的GET/SETはない。`0x42` immediateの出現はlog formatting buffer lengthなどで、report byte storeではない。よって「列挙されている可能性」と「実際に呼ばれること」を分離し、通常C652管理pathではunused/unreachableとした。

### Report 0x50 / 0x60 / GET_FEATURE 0x08

`HidD_GetFeature` importのcall siteは以下に限られる。

- pairing table: 0x43+slot
- pairing/identity variants: 0x48またはdescriptor-derived ID
- battery-related: 0x09, 0x0a
- NP firmware version: 0x23

Report 0x08を実際にGETするcall siteはない。identity parserにはID 0x08用caseがあるが、呼出元がないため到達可能とは判定しない。従ってresponse bytes 2～7の使用はない。

Report 0x50/0x60についてもspecific HID GET/SET producer、byte6～7 reader、per-byte compare/display/storeは確認できない。Input Report specific dispatcherは0x50/0x60をhandled IDに含めない。generic descriptor parserは登録された任意Report IDを形式上処理できるが、C652用の0x50/0x60 descriptor entry/call sourceがないため、機能実装の証拠には数えない。

## 設定送信lifecycle

確認したcall chain:

```text
3DxService main message/event loop
  -> pending download handler (0x140042b40)
  -> DownloadToKernel (0x140032950)
  -> DownloadToKernelForSingleDevice (0x1400348b0)
  -> per-device config dispatch
  -> HIDDev 2D-mouse dispatch (0x180030b30)
  -> SBHID_SendPIDConfig_2DMouse (0x180030e90)
  -> TdxBrokerApi_SendCommand(kTdxBrokerApiSetBlob, type 6)
```

`UpdateConnectedDeviceList`のarrival/departure handlerは同定した。またmain loopはpending download handlerを反復呼出しする。しかし、arrival/reconnect/resume/profile-changeの各producerがどのstate bitを立て、それがReport 0x10 sendまで進む全edgeを完全には復元できなかった。この部分は `NEEDS_MORE_STATIC_ANALYSIS` または `UNKNOWN` とし、文字列だけで送信条件を断定しない。

確定事項:

- last-successful blob cacheはper-device object `+0x2728`、31 bytes。
- identical blobは送らない。
- successful broker send後にcache copy。
- broker send failure時はcacheをzero clear。
- failure branchに即時retry、Sleep、backoff、wake、receiver-child専用queueはない。
- 後続の上位download invocationがあれば、zero cacheとの比較により再送候補となる。

未確定事項:

- service startupにおけるdevice存在/ready stateの全条件。
- USB reconnect arrivalからpending download bitまでの完全edge。
- `Resume` eventからReport 0x10までの完全edge。
- profile file change通知からpending downloadまでの全producer。
- Receiver配下C658について、generator外の一般broker queueが持つwake semantics。

## 確認済み事項

- C658/C652のPID、class、support status、connection types。
- C658の7 button Report 0x03 masks。
- direct action code 1～5、code 6 default store、direct/host wire変換。
- C658 pathにcode 7～30 producerがないこと。
- 31-byte payloadの全offset write census。
- wheel mode、polling rate、lift gate、DPI encoding。
- cache/送信抑止/success/failure branch。
- C652 pairing table GET 0x43+slot。
- HID feature API全xrefと0x08/0x42/0x50/0x60の到達性判定。

## 否定できた事項

- 「0x12～0x27に名前付きDirect Actionがあり、C658 UI/profileから選択・送信できる」: 否定。算術consumerだけ。
- 「文字列 `HIDMouse_RadialMenu` があるのでcode 6である」: 否定。mapperは0を返す。
- 「C658 SmartUiからLiftDetectionを選択できる」: 否定。c650-only gate。
- 「Report 0x42をC652 pairing table取得に使う」: 否定。実callは0x43+slot。
- 「GET_FEATURE 0x08を通常pathで呼びresponse bytes 2～7を使用する」: 否定。GET call siteなし。
- 「HIDDev generatorが失敗時に即時retry/backoff/wakeする」: 否定。

## 未確定事項

- code 6の正式enum/internal name。
- device firmwareにおけるwire 0x10～0x27の潜在意味。host側producerがないので本MSIの機能とは扱わない。
- 31-byte broker blobがkernel driver内でReport 0x10 byte1～31へ最終転記されるstrip済みhelperのsymbol名。
- arrival/reconnect/resume/profile-changeごとの完全state machine。

## 実機検証が必要な事項

静的に送信可能と確認した内容についてのみ、将来の実機試験候補を分離する。

- wire 0x0a～0x0fがC658で期待するdevice behaviorを生むこと。
- direct/host-routed mappingでInput Report 0x03 transitionとhost actionが一致すること。
- DPI clamp、wheel constants、polling dividerのdevice-side effect。
- USB直結とC652配下で、同じblobがいつ受理されるか。
- send failure後、どの外部eventが再downloadを起こすか。

wire 0x12～0x27の意味を調べる試験は、本MSIの通常UI/profileから到達不能という結論を覆すものではない。firmware capabilityの別調査になる。

## 再現手順

以下はLinux上のread-only static workflow。実機/HID nodeへアクセスしない。

```bash
sha256sum 3DxWinCore64.msi
file 3DxWinCore64.msi
mkdir extracted
msiextract -C extracted 3DxWinCore64.msi
find extracted -type f -print0 | sort -z | xargs -0 sha256sum > file_inventory_sha256.txt
find extracted -type f -print0 | xargs -0 file > file_types.txt
```

Managed decompile:

```bash
ilspycmd -p -o 3DxSmartUi_src extracted/3Dconnexion/3DxWinCore/3DxSmartUi.exe
rg -n 'HasLiftDetection|MouseWheelInertia|UpdateRate|LiftDetection' 3DxSmartUi_src
```

Native strings/xrefs:

```bash
strings -a -t x  extracted/3Dconnexion/3DxWinCore/3DxService.exe > service.ascii.txt
strings -el -t x extracted/3Dconnexion/3DxWinCore/3DxService.exe > service.utf16.txt
strings -a -t x  extracted/3Dconnexion/3DxWinCore/UdDev/HIDDev.dll > hiddev.ascii.txt
strings -el -t x extracted/3Dconnexion/3DxWinCore/UdDev/HIDDev.dll > hiddev.utf16.txt
objdump -d -M intel extracted/3Dconnexion/3DxWinCore/UdDev/HIDDev.dll > HIDDev.objdump.txt
r2 -A extracted/3Dconnexion/3DxWinCore/UdDev/HIDDev.dll
```

radare2内の主要確認:

```text
s 0x180030e90; pdf     # 31-byte generator
s 0x18001b6d0; pdf     # GetPairingTable
s 0x18003eb00; pdf     # generic input/bitmap parser
axt @ sym.imp.HID.DLL_HidD_GetFeature
axt @ sym.imp.HID.DLL_HidD_SetFeature
```

Service側:

```text
s 0x140033190; pdf     # direct action ID -> code
s 0x1400348b0; pdf     # DownloadToKernelForSingleDevice
s 0x140032950; pdf     # DownloadToKernel
axt @ 0x1400348b0
```

## 成果物相互参照

- `direct_action_table.csv`: wire 0x0a～0x27を全行列挙。
- `report10_fields.csv`: 31 payload offsetsを全行列挙。
- `evidence_ledger.md`: claimごとのbinary/offset/xref/代替解釈。
- `investigation_classification.md`: 指定された6分類。

