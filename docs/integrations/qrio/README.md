# Qrio Lock / Hub連携

- knowledge_status: `offline-implementation-confirmed`
- reviewed_at: 2026-07-26
- primary_transport: Qrio cloud HTTPS
- risk: 住居の物理セキュリティ

## 確認済み

login/refresh、機器一覧、施錠状態、履歴、設定、電池、firmware、Hub登録状態を実環境で
確認している。施錠・解錠はoperation jobを発行し、terminal statusと状態再取得で確認する
方式が実測されている。Hub到達不能時のtimeoutも確認済みである。

これらは非公開API解析を含むため、正式運用前に利用規約と継続利用の可否を確認する。
model codeを市販型番へ推測変換しない。

## 初期Adapter

初期統合はreader-onlyとする。status、health、history、settingsを読み、event IDで重複を
抑止する。認証処理はtransportへ隔離し、tokenや家庭固有IDをRaw、通常ログ、fixtureへ
出さない。

正式なオフラインReader契約は`src/hedp/adapters/qrio/`へ置く。transport interfaceには
status、health、historyだけを公開し、lock/unlock/settings変更methodを持たせない。
正規化時に実Lock IDを実行時設定のaliasへ変換し、名称、Lock/Hub ID、履歴文言を捨てる。
履歴event IDはRaw値を保持せずSHA-256 dedupe keyへ変換する。

履歴の`logged_at`は秒以下の精度を保ち、定期statusは取得時刻をobserved/received時刻とする。
push/WebSocketは未確認なので、当面はstatusとhistoryの低負荷取得で変化を回復する。
AdapterはPython 3.11以上のOS非依存コードとし、Keychain、launchd、固定パスへ依存しない。
非公開cloud transportの正式実装と定期実行は、利用規約・継続利用性と実機read-only試験後に
外側へ追加する。

`QrioReadOnlyCollector`はstatus、health、historyを一回の収集単位へまとめる。保存するのは
aliasへ置換した状態、品質、理由、電池・firmware・Hub状態、設定状態、履歴時刻、action、
SHA-256化したevent重複キーである。実Lock/Hub/event ID、名称、履歴文言、認証情報、
API response原文は保存しない。原文の代わりに応答ごとのSHA-256 fingerprintだけを残し、
同一応答の証拠と秘密情報の非保存を両立する。

CollectorとReaderはPython 3.11以上のOS非依存コードで、匿名fixtureによるオフライン試験済み。
macOS Keychain、launchd、固定パスには依存せず、将来Linuxへ同じコードを移せる。
`QrioHttpsReadTransport`は設定済みのstatus、health、history URLに対するHTTPS GETだけを許可し、
timeoutを最大30秒、応答を最大4 MiBに制限する。非公開endpointを推測して内蔵せず、認証値と
URLは呼出側から注入する。環境変数による設定入口は用意済みだが、token更新、実API疎通、
現役DB保存、定期実行はまだ実装・適格性確認していない。
これらが済むまで本番稼働済みとは扱わない。

executorは別process/permissionでのみ構築する。施錠、解錠、設定変更は能力を分ける。
解錠は高リスクで、実行直前承認、fresh state、対象一致、単発送信、job確認、read-backを
必須とする。timeoutや結果不明では自動再送しない。

`QrioOperationAdapter`は、読み取り用Transportとは別の注入された操作Transportだけを
呼び出す。共通ExecutionGateを通過した単一対象の`lock`または`unlock`だけを受け付け、
送信は常に1回である。受付と実状態を分け、受付後に既存Readerのstatusを1回読み戻す。
期待状態を確認できた場合だけ`completed`、不一致は`failed`、確認不能は`unknown`とする。
read-back callableは引数なしとし、操作Requestや公開Receiptから家庭固有IDを渡さない。
vendor job参照はjob checkerへメモリ内で渡すだけで、公開Receiptや操作結果へ含めない。
timeout、既知のtransport失敗、job確認失敗、read-back失敗だけを安全な共通結果へ変換し、
想定外のプログラム例外は成功・結果不明として隠さず上位へ伝播させる。

Adapter自身は権限、承認、期限、重複、手動操作cooldownを判断しない。これらは
ExecutionGateの責任であり、本Adapterを直接、本番自動化やCLIへ接続してはならない。
現時点の操作TransportはProtocolと匿名fixtureのみで、実endpoint・認証・実機操作は
実装していない。実Transport追加には、通信仕様の実測、秘密値を含まない契約fixture、
追記型監査、再起動時の未完了操作整理、高リスク個別審査が必要である。

## 対象外

指紋や暗証番号を使う入口認証装置の自作、Qrioとの自作連携、SwitchBot純正製品との
採用比較は行わない。これらを将来タスクへ戻さない。既存のQrio reader知識や一般的な
高リスク操作契約は、この対象外判断とは分けて保持する。

## 保存

現在状態、電池、firmware、Hub、設定と、施解錠・auto-lock・operation terminal eventを
残す。住居の入退室履歴は高プライバシーであり、既定の10年保存対象にしない。正常status
Rawは短期、異常・job結果・read-back不一致を優先する。

## 再確認条件

Qrioアプリ/API版、token lifecycle、job status、機種/Hub交換、複数Lock、共有権限、
firmware、Hub offline挙動が変わったとき。BLE/LAN/pushは未解析で、別経路として扱う。
実通信設定はコードへ埋め込まず、`SUMICORE_QRIO_STATUS_URL_TEMPLATE`、
`SUMICORE_QRIO_HEALTH_URL`、`SUMICORE_QRIO_HISTORY_URL_TEMPLATE`、
`SUMICORE_QRIO_AUTHORIZATION`、`SUMICORE_QRIO_LOCK_ID`を実行環境から読む。
任意設定は`SUMICORE_QRIO_TARGET_REF`、`SUMICORE_QRIO_TIMEOUT_SECONDS`、
`SUMICORE_QRIO_MAXIMUM_RESPONSE_BYTES`である。移行期間中は同名の`HEDP_`接頭辞も
利用できる。URL、認証値、家庭固有IDは通常ログ、fixture、報告へ出さない。
