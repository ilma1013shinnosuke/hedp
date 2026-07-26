# Smart LEDZ Base 2.0.4連携

- knowledge_status: `offline-implementation-confirmed`
- reviewed_at: 2026-07-26
- observed_versions: Smart LEDZ Base 2.0.4、同型Gateway複数台
- primary_transport: LAN SSDP + local TCP

## 確認済み

Gateway discovery、TCP portへの接続、short frame、JSON request/response、request ID相関、
`ErrorCode=0`の受付判定を実機で確認している。Group、Scene、Schedule、Device、Sensorの
read-only要求と、限定的なScene、照明、Schedule操作の実績がある。

command直後は旧状態を返すことがあり、数秒後に反映するeventual consistencyがある。
受付成功と状態変化を分け、bounded read-backを行う。

## 初期Adapter

readerはGateway、Group、Scene、Schedule、Device、Sensor、現在の運転・予約を取得する。
transportはframingとJSON相関だけを担当する。executorはreader完成後に別経路で追加し、
Collectionからimportできないようにする。

現時点のオフラインreader部品は、すでにJSONへ復号・相関済みのGroup、Scene、Schedule、
Device、Sensor応答だけを受け取る。実機で確認済みの`ErrorCode=0`は受付済みとして表す。
確認済みのGroupList、GroupGet、DeviceList、GroupScheduleGet、照度応答は、家庭固有IDを
実行時設定の安全なaliasへ解決してから正規化する。名称、MAC、設定blob、未解決IDは
正規化境界を越えない。未知schemaは値を複製せず最上位field名だけで検出する。

引き継いだ2.0.4解析で確認済みのread-only command shapeだけを`read_commands`へ正式化した。
書込みcommandは同moduleへ入れない。別transportがframeのrequest IDと復号済みJSON objectを
渡した場合だけ、宣言済みread requestへ一対一で相関し、通知、重複、未宣言ID、欠落応答を
拒否する。fixtureの`request_id`はtransport入力を表すテスト用関連情報である。

Adapter本体はPython 3.11以上でOS非依存とし、Keychain、launchd、GUI、固定パスへ依存しない。
定期実行は外側へ分離し、macOSではlaunchd、Linuxではsystemd等へ差し替える。すべての
正規化結果はtimezone付き`observed_at`と`received_at`を持つ。イベントは秒精度を保ち、
機器横断の1分系列や長期集計は蓄積層で生成する。

Scene/Scheduleの定義、active、現在選択、実行中状態は同じ意味にしない。完全なpush event、
fragmented frame実機値、MQTT、認証token lifecycle、Sensor lux実値、個別照明の状態rowは
未確認である。未確認項目を推測で正規化しない。

Scene実行とSchedule選択にはoffline dry-run型だけを置く。Scene command shapeが既知でも、
対象Gatewayのfreshなruntime snapshot、good品質、readback対応、GroupとSceneの観測済み
対応関係がすべて揃わなければ`verified`または`would_dispatch`にしない。Schedule選択は
schemaとreadbackが未確認のため明示的にunsupportedとする。どちらにも送信transportはない。

未確認notificationはevent意味へ変換せず、read-only resyncを要求する。正規化前にpayload
byte数、nesting深さ、field数を上限検査し、fingerprint履歴も有限にする。保持可能な
top-level field名は`event`、`status`、`timestamp`、`type`の固定allowlistだけであり、
未知field名や値は保存しない。

`SmartLedzReadOnlyCollector`は確認済みの`GroupList`、`GroupGet`、`DeviceList`、
`GroupScheduleGet`、照度取得だけを一回の収集単位へ束ねる。transport interfaceは
`ReadCommand`を受ける`read`だけを公開し、Scene適用、点消灯、Schedule変更などの操作methodを
持たない。Gateway・Group・Scene・Schedule・Device・Sensorの家庭固有IDは実行時設定で
安全なaliasへ置換し、未対応の参照関係は`unknown`として件数を残す。

保存対象はGroupの点灯・明るさ、Scene定義、Schedule定義・step、Device参照、Sensor状態、
照度、品質、理由、取得時刻である。名称、元ID、IP、MAC、UDN、auth、設定blob、応答原文は
保存せず、各応答のSHA-256 fingerprintだけを証拠として残す。Group・Scene・Scheduleの
関係はaliasで維持し、定義、active、選択中、実行中を同じ状態として扱わない。

frame、request相関、read command、正規化、Collectorは匿名fixtureでオフライン試験済みで、
macOS固有APIへ依存しないためLinuxでも利用できる。`SmartLedzTcpReadTransport`は確認済みの
`ReadCommand`だけを受け、接続・読取timeoutを最大30秒、request ID相関を必須とする。
接続先と対象aliasは呼出側から注入する。環境変数による設定入口は用意済みだが、実TCP疎通、
認証、複数Gateway、
個別照明状態、push通知、現役DB保存、定期実行は未確認であり、本番稼働済みとは扱わない。

## 公開しない能力

backup、restore、OTA、Wi-Fi、cloud、Gateway初期化、機器kickout/import、認証変更を
通常Adapterへ入れない。Room/Scene/Scheduleの編集や全消灯は、read-only完成後も
能力単位の別承認とする。

## 保存

正常時は正規化現在値と変化を中心にし、Rawは初回schema、未知field、異常、操作検証へ
限定する。UDN、IP、MAC、serial、名称、auth、設定blobは通常Rawへ入れない。匿名fixtureには
short/fragmented frame、最小Group/Scene/Schedule/Device/Sensor responseだけを残す。

## 再確認条件

Baseアプリ、Gateway firmware、frame/schema、認証方式、Gateway交換、複数Gateway構成、
未知command/error、応答遅延の変化を検出したとき。旧・新fixtureを併存させる。
実通信設定はコードへ埋め込まず、`SUMICORE_SMARTLEDZ_HOST`と
`SUMICORE_SMARTLEDZ_PORT`を実行環境から読む。任意の
`SUMICORE_SMARTLEDZ_TIMEOUT_SECONDS`は30秒以下に制限する。移行期間中は同名の
`HEDP_`接頭辞も利用できる。家庭内アドレスは通常ログ、fixture、報告へ出さない。
