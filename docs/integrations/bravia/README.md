# Sony BRAVIA KJ-55X8500F連携

- knowledge_status: `offline-contract-confirmed`
- reviewed_at: 2026-07-27
- primary_transport_candidate: Sony REST API
- supplemental_candidates: IRCC-IP、Wake-on-LAN、Google Cast

## 現在の知見

Sony公式資料と第三者実装から、電源、音量、消音、入力、再生内容、application等の
REST method候補、PSKまたはPIN/Cookie認証、IRCC-IP、Remote Start/WoLを確認した。
KJ-55X8500F実機のmethod/version、認証方式、standby到達性は未確認である。

瞬時消費電力を返す根拠はないため非対応とする。視聴内容は高プライバシーであり、現在の
安全な正規化境界は`tv`/`extInput`という入力種別だけを許可する。title、description、
content ID、URI、channel、未知fieldの値は保持しない。
power、audio、batch envelopeでも未知fieldのkey/valueは保持せず、値を含まないfield件数
だけをschema変化の証拠にする。取得前Rawを受ける`ReadBatch`と正規化結果の未知schema
metadataはreprから除外する。

## 読み取りAdapter

`BraviaReadOnlyCollector`は、単一allowlist hostへ接続する外部transportを境界に置き、
power、volume/mute、playing contentを各1回、合計3回だけ取得する。1回のtimeoutは30秒を
上限とし、再試行しない。通信実装は書き込みmethodを公開しない
`BraviaReadTransport`に限定する。Collector本体はOS固有APIを使用しない。

保存するのは入力種別、電源、音量、消音、品質、時刻、Raw応答のSHA-256だけである。
視聴情報、未知値、IP、識別子、認証情報、例外本文は保存しない。一部の取得に失敗しても
正常な兄弟応答は残し、失敗した項目だけを`missing`として扱う。無応答をstandbyと断定
しない。

現在は匿名fixtureによるオフラインCollectorまで正式化済み。実transportは対象テレビの
method/version、認証、standby到達性をread-only適格性試験で確認した後に追加する。
executorは初期配布しない。

power、volume、mute、input、channel、app、Wake-on-LANには型付きrequestと短命な
`BraviaCapabilitySnapshot`、副作用のないdry-run plannerを置く。volume範囲と
input/channel/appの候補はsnapshotで実際に観測された値だけを許可し、情報がなければ
`indeterminate`、未広告値なら`would_block`とする。`would_dispatch`も実機へは送らず、
成功を表さない。

この契約にはREST/IRCCのendpoint、method/version、IRCC code、PSK、Cookie、magic packet、
MAC address、実transportを含めない。対象実機で確認されるまで推測で足さない。

取得済みresponseの一部が壊れていても、正常な兄弟responseは独立して正規化する。
非object responseと非object volume rowは`invalid`とし、黙って成功扱いしない。

災害情報の取得、訂正、取消、地域・期限判断はSumiCore共通層が正本であり、BRAVIA試作の
災害state machineを移植しない。AdapterはDisplayIntentを受けた後のメーカー固有実行だけを
将来担当する。

## 操作

power on/off、volume、mute、input、channel、app、Wake-on-LANを別能力にする。IRCC keyは
実機のcodeと利用条件が未確認のため現在の型付き能力へ含めない。Wakeは1 event
1回、read-back付きとする。取消時に自動power offしない。手動操作を検知したら追加操作を
停止する。

## 保存

capabilityと現在値を中心にし、Rawは初回schema、未知field、異常、操作検証へ限定する。
PSK、Cookie、IP、serial、MAC、CID、認証headerを保存しない。視聴titleは既定で保存しない。
未知fieldへこれらが現れてもallowlistを迂回して保存・表示しない。

## 再確認条件

テレビfirmware、WebApiCore/REST generation、認証、Remote Start、network構成、Cast receiver、
未知method/error、standby時到達性が変わったとき。
