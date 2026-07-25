# Miele@home連携

- knowledge_status: `research`
- reviewed_at: 2026-07-25
- primary_transport: Miele cloud OAuth REST + SSE候補
- initial_scope: read-only

## 現在の知見

洗濯乾燥機の状態、program、phase、残時間、EcoFeedback等をcloudから取得する候補実装と
実Rawがある。候補実装はSumiCoreの正式Adapterではなく、実SSEの長時間確認、offline test、
lintの最終証明が不足している。

既存候補には無制限の再接続loopがあり、そのまま移植しない。再接続回数、wall clock、
backoff、queue、circuit breakerへ上限を設ける。

## 初期Adapter

OAuth、REST、SSE接続をtransportに隔離し、readerだけを公開する。SSEが利用不能な場合の
低頻度poll fallbackは、API負荷とrate limitを確認してから採用する。家電操作executorは
作らない。

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
