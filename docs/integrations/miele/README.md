# Miele@home連携

- knowledge_status: `offline-implementation-confirmed`
- reviewed_at: 2026-07-26
- primary_transport: Miele cloud OAuth REST + SSE候補
- initial_scope: read-only + offline operation contract

## 現在の知見

洗濯乾燥機の状態、program、phase、残時間、EcoFeedback等をcloudから取得する候補実装と
実Rawがある。read-only Reader、有限SSE parser、Collectorは正式なオフラインAdapterとして
test・lint済みである。一方、実OAuth transportと実SSEの長時間確認は未完了である。

既存候補には無制限の再接続loopがあり、そのまま移植しない。現時点では正式なtransport、
SSE framing、resume、認証失効、429/5xxの契約がないため、推測で再接続policyを実装しない。
匿名化した有限transcriptで契約を確認した後に、再接続回数、wall clock、backoffへ上限を
設ける。queueやcircuit breakerはreaderの所有境界が決まるまで別課題とする。

## 初期Adapter

OAuth、REST、SSE接続をtransportに隔離し、readerを公開する。SSEが利用不能な場合の
低頻度poll fallbackは、API負荷とrate limitを確認してから採用する。家電操作executorは
作らない。例外として、`START_SCHEDULED_PROGRAM`の型付きrequest、短命なcapability
snapshot、既存状態を再利用するreadback port、dry-run gateだけをオフライン契約として
持つ。gateの`would_dispatch`は実機成功や受付を意味せず、通信は一切行わない。

operation契約にはメーカーURL、HTTP method、payload、認証、dispatch transportを含めない。
これらは公式仕様と対象実機で確認されるまで追加しない。capabilityが未広告、古い、対象が
異なる、またはreadbackが欠損・低品質・古い場合は送信候補にしない。
readbackが正常でも予約program IDを確認できない場合は、開始可能とは判定せず
`scheduled_program_missing`として結果不明のまま止める。
開始可能なstatus codeも短命なcapability snapshotで実測済みの集合として渡す。集合が
未確認なら`startable_status_capability_missing`、現在statusが集合外なら
`status_not_startable`とし、program IDだけで開始可能とは判定しない。

## 予約済みプログラムの即時開始：操作準備のみ

`operation.py`には、開始予定のprogramを「今すぐ開始する」ための型付きrequestと
`MieleOperationGate`がある。ただしこれは操作Adapterではなく、通信しないdry-runである。
メーカーURL、HTTP method、payload、認証、writer、再試行は持たない。

共通の`ExecutionGate`へは、確認済みの開始capabilityだけを**Shadow Mode**で登録できる。
この接続でもportを登録しないため、`would_dispatch`は「第4層の共通条件を満たした」という
意味だけで、家電への送信や受付を意味しない。実Writerを追加するには、別途のread-only
適格性確認、個別承認、専用transport、結果確認の実機試験が必要である。

将来の結果確認は、次の二つを独立して満たす契約にする。

1. 実Writerが対象機器から受領したことを、確認済みの意味で`accepted`と判定できること。
2. 直後にread-onlyで再取得した状態が、対象API・対象機器で実測済みの「開始済みstatus」集合に一致すること。

この二つのどちらかが未確認、古い、欠損、低品質なら`indeterminate`で停止する。post-state
だけで「開始成功」とは扱わない。実際の開始済みstatus、受付responseの意味、URL、payload、
rate limit、remote enable条件は未確認であり、現時点では`pending`である。

匿名fixture `scheduled_program_start_contract_v1.json` は契約を検証するための架空値であり、
実Raw、機器ID、API response、認証情報を含まない。これは実機のstatus mappingを主張しない。

正式なオフラインReader契約は`src/hedp/adapters/miele/`へ置く。REST snapshotとSSE stateを
同じ状態modelへ正規化し、status、program、phase、残時間、経過時間、予約時刻、温度、
回転数、乾燥段階へ個別の品質を付ける。欠損や`-32768`を0へ変換しない。target aliasを
除く実機ID、localized text、未知fieldは正規化結果へ出さない。

SSE parserはPING、IDENT、ACTIONを含む有限transcriptを扱い、event byte数とdata行数へ
上限を持つ。payloadはreprへ出さない。Reader自身は再接続loopを持たず、外側の運用部品が
総時間・回数・backoff上限を管理する。再接続後はREST snapshotで現在値を回復する。

ReaderはPython 3.11以上のOS非依存コードであり、Keychain、launchd、固定パスへ依存しない。
実OAuth transport、単一SSE接続、poll fallbackは、秘密情報の再発行と実機read-only検証後に
追加する。

`MieleReadOnlyCollector`はREST snapshotと有限SSE eventを同じ安全なObservation形式へ
まとめる。保存対象はallowlist済みのstatus、program、phase、残時間、経過時間、予約時刻、
温度、回転数、乾燥段階と各値の品質・理由だけである。実device ID、名称、localized text、
account、token、未知field、API response原文は保存せず、応答のSHA-256 fingerprintだけを
証拠として残す。

SSE収集は一回に処理するevent数と接続timeoutへ必ず上限を設け、transportは一接続を
その両方の早い方で終了し、再接続しない。PINGを状態として保存しない。同一状態が
連続した場合は時刻を除いた正規化状態で重複判定し、一件だけ残す。ReaderやCollectorは
再接続loopを持たない。切断後の再接続回数、総時間、backoff、RESTによる状態回復は、
rate limitと実機挙動を確認してから外側の運用部品へ実装する。

SSE eventはpayload内のdevice IDが設定済み`source_device_id`と完全一致し、かつtype 24
である場合だけ採用する。直接stateだけのeventや別機器のtype-24 stateは帰属不能として
破棄する。接続timeoutはsocket inactivityだけでなく単調時計による総wall-clock期限として
各受信lineでも検査するため、heartbeatだけが続いても期限を延長しない。

Reader、GET専用HTTP transport、SSE parser、Collectorは匿名fixtureによるオフライン試験済みで、
macOS固有APIへ依存しないためLinuxでも利用できる。OAuth token取得・更新、実SSE長時間接続、認証失効、
429/5xx、現役DB保存、定期実行は未確認であり、本番稼働済みとは扱わない。

実通信設定は`SUMICORE_MIELE_DEVICES_URL`、`SUMICORE_MIELE_EVENTS_URL`、
`SUMICORE_MIELE_ACCESS_TOKEN`、`SUMICORE_MIELE_DEVICE_ID`を必須とする。任意設定は
`SUMICORE_MIELE_TARGET_REF`、`SUMICORE_MIELE_REST_TIMEOUT_SECONDS`、
`SUMICORE_MIELE_SSE_TIMEOUT_SECONDS`、`SUMICORE_MIELE_MAXIMUM_EVENTS`である。
移行期間中は同名の`HEDP_`接頭辞も受け付ける。URL、token、device IDはfixture、文書、
ログへ値を保存しない。

HTTP transportはdevices/events URLのorigin完全一致を要求し、既定では
`https://api.mcs3.miele.com`だけを許可する。匿名fixture試験ではconstructorへ明示した
test originだけを追加できる。環境変数のURLだけでBearer tokenの送信先allowlistを
拡張することはできない。

## 秘密

Client Secretは過去のチャットで露出した可能性があるため、本番前に再発行する。旧`.env`は
移動・内容表示せず、正式secret storeへ利用者が再設定する。実Rawからdevice ID、account、
token等を除去した最小fixtureだけを残す。

## 保存

状態変化、program/phase、完了、異常、通信品質を残す。連続する同一SSE/REST responseは
重複保存しない。代表的な正常、欠損、unknown field、認証失効、切断のfixtureを作る。

## 再確認条件

Miele API/OAuth版、SSE schema、region、対象家電firmware、token scope、rate limit、
再接続挙動が変わったとき。
