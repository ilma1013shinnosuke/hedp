# Panasonic HE-WU46KQ エコキュート連携

- knowledge_status: `offline-implementation-confirmed`
- reviewed_at: 2026-07-26
- primary_transport: ECHONET Lite
- cloud_app: 「スマホでおふろ」は補助調査

## 方針

非公開クラウドAPIより、公開標準ECHONET Liteの電気温水器classを優先する。実機から
property mapをread-onlyで取得し、実装項目を確定する。規格上存在するpropertyを、
当該機が実装していると推測しない。

実測では複数のGet/Set propertyが確認され、限定的な沸き増し開始・停止試験の記録がある。
正式統合はreaderを先に作り、Set能力は公開しない。

## オフラインproperty map解析

`src/hedp/adapters/ecocute/echonet.py` は通信を行わない純粋なread-only Get
builderとframe/property map decoderである。`0x9D`（INF）、`0x9E`（Set）、
`0x9F`（Get）のlist形式とbitmap形式を
検証してEPC集合へ復号する。匿名fixtureには2026-07-24に観測したSet map 14件とGet map
41件だけを保持し、家庭内アドレス、機器ID、通常値EDTは含めない。

read-only capabilityは同一観測のGet mapに存在し、Set mapに存在しないEPCだけを返す。
Set可能性や未知EPCの意味は推測しない。未知EPCは数値のままproperty mapとcapability結果に
残り、名称は付与しない。Get requestはbytesまで生成するが、この部品自身はUDP送信、Set、
保存、設定を実行しない。

Get responseは定期照合、INFは秒精度のevent更新として共通Observationへ正規化する。INFに
含まれないpropertyをmissingとは扱わず、後続の定期Getで現在値を回復する。値のないproperty、
未知値、未知EPCはそれぞれ`missing`または`unknown`とし、0や前回値で埋めない。

AdapterはPython 3.11以上のOS非依存コードとし、macOS固有機能へ依存しない。UDP transportと
定期実行は外側へ分離し、将来Linux/systemdへ移してもReaderを変更しない。

## 正式read-only Adapter

`transport.py`はECHONET Liteのunicast UDP通信だけを担当し、公開interfaceは`Get`
だけである。Set要求を生成・送信する経路は持たない。送信先はprivateまたはlink-local IPv4
に限定し、送信元、transaction ID、機器class、宛先object、応答serviceが一致した応答だけを
採用する。timeoutと受信datagram数には上限があり、例外へIPアドレスやpacketを含めない。

`collector.py`は最初にINF・Set・Get property mapを読み、実機がGet可能と広告した項目と、
意味を確認済みの状態EPCとの共通部分だけを取得する。mapと状態の応答原文は同じRawDataへ
可逆なhexとして保持し、正規化値には品質と理由を付ける。未知EPCを推測せず、家庭内IPや
機器固有識別子をmetadataへ保存しない。

この実装は匿名fixtureと偽UDP socketでオフライン検証済みであり、macOS固有APIへ依存しない。
したがってLinuxでも同じReaderを使用できる。実機疎通、INFの欠落特性、対応EPCの値・単位、
定期実行、現役DB保存はまだ適格性確認前であり、本番稼働済みとは扱わない。

接続設定はコードへ埋め込まず、`SUMICORE_ECOCUTE_HOST`（旧名
`HEDP_ECOCUTE_HOST`も移行期間中は可）を環境設定から読む。任意設定は接頭辞付きの
`SUMICORE_ECOCUTE_PORT`、`SUMICORE_ECOCUTE_INSTANCE_CODE`、
`SUMICORE_ECOCUTE_TARGET_ALIAS`で、秘密値や
家庭内アドレスを文書・fixture・Gitへ保存しない。

## 読み取り候補

動作状態、沸き上げ設定・状態、昼間沸き増し許可、給湯中は実装可能性が高い。残湯量、
タンク湯温・容量、給湯可能湯量、警報、設定温度、風呂状態は、当該機のproperty mapと
値の実測を根拠に能力化する。

## 操作

沸き増し、風呂自動、追いだき、予約、休止などを一括して「給湯操作」にしない。
各能力を分け、現在状態、機器予約、手動操作、受付、実状態を別に扱う。給湯・加熱に
関わるため、結果不明時の盲目的再送を禁止する。

`operation.py`と`EcoCuteSetUdpTransport`は、読み取りAdapterとは別の操作専用経路である。
現時点では個別の「沸き増し」等を公開せず、対象の安全な別名、Set/Get map、観測時刻、
最大有効時間をまとめた`RuntimeCapabilitySnapshot`に存在するEPCだけを、正確なEDTを
指定して1回送れる最小部品としている。別対象のsnapshot、期限切れsnapshot、仕様書に
存在するだけの
EPCや、過去の別firmwareで観測したEPCは許可しない。値の意味・範囲が実機で確定するまで、
上位のCapabilityDescriptorへ登録してはならない。

操作はprivate/link-local IPv4へのunicastだけを許可し、自動再送しない。送信受付と結果を
分離し、受付後は0〜30秒に制限された待機を経て、注入されたread-only transportで同じ
EPCを読み戻す。待機処理も注入するため、オフライン試験では実時間を待たない。読めない、値が一致
しない、timeoutになった場合を成功扱いしない。DispatchReceiptには安全な別名、EPC、
時刻、受付区分、試行回数だけを残し、IP、packet、EDT、機器IDを含めない。
VerificationResultは確認方法、品質、確認時刻と
`matched`、`not_matched`、`unavailable`、`not_supported`を分ける。最終Outcomeは
確認一致だけを`completed`、拒否・不一致を`failed`、それ以外を`unknown`とする。

この実装と試験はオフライン限定であり、ExecutionGate、永続監査台帳、実機Set適格性確認
にはまだ接続していない。従って本番操作可能を意味しない。実機試験では、property mapを
同じsessionで再取得し、低リスクな単一EPCについて開始前snapshot、明示承認、1回送信、
bounded read-back、純正操作による復旧を順番に確認する。

## 沸き上げ時刻と将来の最適化

匿名化したHE-WU46KQ実機property mapでは、エネルギーシフト参加`0xC7`と昼間沸き上げ
シフト時刻1 `0xCA`がGet/Set対象であり、開始基準時刻`0xC8`、シフト回数`0xC9`、
予測電力量`0xCB`、時間当たり消費電力量`0xCC`がGet対象である。ONタイマ時刻`0x91`と
第二シフト`0xCD`〜`0xCF`は実機mapにない。

ECHONET Lite Web API機器仕様1.6.0では、`0xCA`の設定値は09:00〜17:00の1時間刻みである。
`0xC8`も20:00〜01:00の1時間刻みを表す。従って、公開標準から確認できるこの実機の
エネルギーシフト指定粒度は1時間であり、本体内部が1分または5分周期で制御しているとは
断定できない。手動沸き上げを任意時刻に依頼できても、compressorの実開始時刻や安全制御を
SumiCoreが直接決められることを意味しない。

将来SumiCoreが料金、太陽光余剰、必要湯量から時刻を判断する場合も、本体の温度、圧力、
凍結防止、異常停止、最低湯量等の機器制御を置き換えない。SumiCoreは許可されたシフトや
沸き増しの意図を出し、開始前snapshot、受付、`0xB2`沸き上げ中状態、警報、終了後snapshotで
結果を確認する。

## 本体自動機能との境界

HE-WU46KQの公式取扱説明書では、通常の沸き上げモードは使用量を学習する
「おまかせ節約」と「おまかせ」の2種類で、常時無効という第3のモードは示されていない。
利用者が設定できる抑制手段には、当日夜間時間帯までの「昼停止」、毎日の指定時間帯を
1時間単位で避けるダブルピークカット、1〜15日の「休止設定」がある。昼停止は沸き増しで
解除され、休止解除日は必要湯量不足により昼間沸き上げが起こり得る。ソーラーチャージは
昼停止・ピークカットより優先されるため、複数の仕組みを同時に使わない。

従って「本体の自動機能をできる限り止める」は次の2種類に分ける。

- HomeCoreへ移せる利用者向け機能: 学習に基づく沸き上げ時刻・量、昼間沸き上げ、
  ソーラーチャージ、ふろ予約、自動たし湯、エコナビ保温等。個別のread/write能力と
  復旧手段を確認できたものだけ段階的に移す。
- 本体へ残す機器保護・安全機能: 温度・圧力・圧縮機制御、異常停止、凍結予防、
  漏電保護。休止中やピークカット中でも低外気温時は凍結予防のためポンプや
  沸き上げが作動する。これを異常や命令違反として扱わず、停止対象にしない。

自動配管洗浄は設定上は切れるが、説明書は衛生維持のため「入」を推奨し、入浴剤使用時には
「入」を求めている。ふろ凍結予防も設定上は「しない」を選べるが、0 ℃以下ではポンプが
作動する場合があり、配管破損防止のため原則として停止対象にしない。

HomeCore主導運転へ移す場合も、一度に本体自動運転を止めない。まずread-only観測、
次に本体自動運転を残した提案運転、次に短期間だけ抑制してHomeCoreから必要量を確保する
試験、最後に限定運用の順で適格性を確認する。HomeCore停止、状態の鮮度切れ、通信断、
残湯不足、異常・警報、時刻ずれ、判断材料不足が発生した場合の復帰方法を先に定義する。
ただし、本体に永続的な「自動沸き上げOFF」がないため、HomeCoreが故障時に自動で元の
モードへ戻せるとは未確認である。戻せない間は、長期の本番切替を認めない。

取得は状態依存とする。待機中は画面表示、起動・再接続、15〜30分の低頻度照合を候補とし、
操作直後は短い間隔のbounded read-back、その後は1分程度で開始・継続・終了を確認する。
実機INF通知の対象と欠落特性を確認できた場合は、通知を主経路として照合頻度を下げる。

参照:

- ECHONET Lite Web API Guidelines Device Specifications Version 1.6.0
  https://echonet.jp/wp/wp-content/uploads/pdf/General/Standard/web_api/ECHONET_Lite_Web_API_Dev_Specs_v1.6.0.pdf
- HP給湯機・HEMSコントローラ間アプリケーション通信インタフェース仕様書 Version 1.10
  https://echonet.jp/wp/wp-content/uploads/pdf/General/Standard/AIF/hp/hp_aif_ver1.10.pdf
- HE-WU46KQS 家庭用ヒートポンプ給湯機 取扱説明書
  https://hvac.panasonic.com/search/add-on/hvac/fileDownload2.jsp?volumeName=00001&itemID=t000100177941&hinban=HE-WU46KQS

## 保存

通常pollは正規化現在値と状態変化を中心にする。property map変更、decode失敗、未知EPC、
異常値、操作read-back不一致だけRaw価値を高くする。Android AVD、APK、認証済み画面は
正式Adapterに含めない。

## 再確認条件

本体・無線Adapterのfirmware、ECHONET property map、AIF仕様、アプリ版、AiSEG2構成、
未知EPC、値の範囲・単位変更を検出したとき。
