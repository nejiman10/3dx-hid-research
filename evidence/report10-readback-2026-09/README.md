# Report `0x10` 読み戻しの限定監査（2026-09-25）

標準ユーザーでLinux `HIDIOCGFEATURE`を実行した。設定書き込み、pair/unpair、sudoは使っていない。各監査プロセスに30秒の上限を設け、両経路とも初回と同条件での再試行を各1回に限定した。GETの直前にUSB VID:PID、interface番号、descriptorを取得した。対象の接続状態は利用者の申告で確認したもので、監査JSON単独では物理接続を証明しない。

実行したzipappのSHA-256は `a03f8511d0d3ea2b4a299e54d7ea21cd538ebb8e81a11e726a058012035bc9af`。実行時のソースには未commit変更があるため、HEADだけでは実行コードを特定できない。

| 経路・接続条件 | 実行時interface / descriptor SHA-256 | 要求と結果（初回、再試行とも同じ） |
| --- | --- | --- |
| 有線C658、利用者がUSB接続を確認 | MI_01 / `6b205bb223c7adaccb757021ac7f1c90eef8a4d9cd6cbc0ee9e59d09f967d0eb` | GET `0x10`、要求32 byte。2回とも `EPIPE`（errno 32）。応答なし |
| Receiver C652、利用者がReceiver接続を確認 | MI_03 / `8e31d4b6f8e0c5eb5ff01617d202f8f29421f514fd05a187a2ca3c777aea9efc` | 対照GET `0x08`は2回とも8 byte、Report ID一致、候補byteが既存観測の`0x59`と一致。GET `0x10`は2回ともioctl戻り値2、応答2 byte、Report ID一致。32-byte設定値は得られず |

Receiver対象は[以前の監査](../read-paths-2026-09/README.md)ではMI_02だったが、今回はMI_03だった。最初の準備試行は旧MI_02固定の安全ガードによりGETを1件も送らず終了した。その後、USB interface番号を実行時に記録し、descriptorがFeature `0x10`を32 byteとして宣言することと、ReceiverのGET `0x08`応答を確認する方式に修正した。管理interfaceなど、Report `0x10`を宣言しないnodeにはGET `0x10`を送っていない。

この結果は、試験したLinux handle・接続・要求長で有線GETが`EPIPE`、Receiver GETが短い応答になったことを示す。`EPIPE`だけでdevice側のprotocol拒否とは判定できず、2-byte応答を現在設定やfactory defaultとして解釈できない。異なる要求形式、firmware、Windows経路は未試験である。

非公開原本はGit除外の `evidence/source-private-not-in-repository/report10-readback-2026-09-25/` に保管した。公開文書にはnode番号、raw応答、個体識別情報を含めない。

| 非公開原本 | GET時刻（UTC） | SHA-256 |
| --- | --- | --- |
| `receiver-1.json`（旧MIガードによるGET前停止） | GETなし | `545164f4b72e9f854d45386babbd113a1b6467642130b1d829630fecd410c0bd` |
| `wired-1.json` | 13:53:55 | `7cb872dfff4ed02176a58383b968841909bf687b1e3e6a4d8a76cf6da9f464cf` |
| `wired-2.json` | 13:54:10 | `7f8ea223672b2faf51cd934e405980e221bec1bddd8a006490daa797e84400d7` |
| `receiver-2.json` | 13:55:01 | `8287fcab01bd4f6696a34efab33cb32e6e291721750c41bf0cc7e72b12f93b11` |
| `receiver-3.json` | 13:55:18–13:55:19 | `316ab40642b804ed6d9eac3539f4ae6dd120f73d94baa56200935ab19d8ed743` |
