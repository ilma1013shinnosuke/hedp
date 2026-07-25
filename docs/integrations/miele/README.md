# Miele@home連携

- knowledge_status: `research`
- reviewed_at: 2026-07-25
- primary_transport: Miele cloud OAuth REST + SSE候補
- initial_scope: read-only

## 現在の知見

洗濯乾燥機の状態、program、phase、残時間、EcoFeedback等をcloudから取得する候補実装と
実Rawがある。候補実装はSumiCoreの正式Adapterではなく、実SSEの長時間確認、offline test、
lintの最終証明が不足している。

既存候補には無制限の再接続loopがあり、そのまま移植しない。現時点では正式なtransport、
SSE framing、resume、認証失効、429/5xxの契約がないため、推測で再接続policyを実装しない。
匿名化した有限transcriptで契約を確認した後に、再接続回数、wall clock、backoffへ上限を
設ける。queueやcircuit breakerはreaderの所有境界が決まるまで別課題とする。

## 初期Adapter

OAuth、REST、SSE接続をtransportに隔離し、readerだけを公開する。SSEが利用不能な場合の
低頻度poll fallbackは、API負荷とrate limitを確認してから採用する。家電操作executorは
作らない。

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
