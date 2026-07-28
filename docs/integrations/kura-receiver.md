# KURA公開Raw受信境界

## 目的

HESTIAは、KURAの内部DB・サービス・Python実装へ依存せず、
`kura.delivery/1`のRawとDelivery Envelopeだけを受け取ります。KURAは任意の外部
記憶であり、停止してもHESTIAの既存Collector、閲覧、安全機能、操作機能は継続
します。

## 責任境界

- KURA正本は読み取り専用の契約参照先であり、HESTIAから変更しません。
- 受信対象は、事前に許可した公開Raw、目的、Source、Connector release、media type
  だけです。
- 秘密、認証情報、個人用Raw、非公開Rawはこの受信箱へ入れません。
- 既存Collectorは削除せず、同じRawを使ったShadow比較が合格するまで主経路として
  残します。
- ExecutionGate、安全制御、操作層はこの連携に依存しません。

## Durable InboxとACK

受信箱はHESTIA本体DBとは別の、名前が`.kura-inbox.sqlite3`で終わる専用SQLiteです。
トランザクションは`BEGIN IMMEDIATE`、`synchronous=FULL`で行い、Raw、Envelope、
束縛hash、受信属性、stableな`app_commit_id`、pending ACK outboxがatomicにcommit
された後だけACK準備を返します。

- 検証拒否: 保存なし、ACKなし
- 初回受領: durable commit後だけACK
- 完全に同じDelivery IDと束縛値: 再保存なし、再ACKなし
- 同じDelivery IDで束縛値が異なる: conflict拒否、保存なし、ACKなし
- commit失敗: 例外として明示し、ACKを生成しない

受信箱はKURAのDBを読みません。ACK送信層はpending outboxを列挙し、KURAが同じ
束縛値と`app_commit_id`のACK成功を返した後だけ明示的に完了記録します。送信前に
processが停止しても再起動後に同じintentを回収でき、送信失敗でRaw commitやpending
ACKを取り消しません。duplicate受領はRawを再保存せず、新しいACKも作りませんが、
初回commitのpending ACKはACK成功まで保持します。

## Shadow比較

既存CollectorとKURA経路を同じ取得条件で観測し、次を比較します。

- Raw byte数とSHA-256
- 取得時刻と確認時刻
- HESTIA自身が決定的に整形した結果のSHA-256
- 整形レコード数

`match`は二経路が一致した証拠であり、内容の業務的な正しさや既存Collectorを削除
してよいという判断ではありません。`mismatch`と`incomparable`は上書き修復せず、
人が原因を確認します。

## 検証

KURAの言語非依存fixtureは外部通信なしで実行します。

```text
KURA_RECEIVER_FIXTURE_ROOT=<KURA正本>/tests/fixtures/receiver-conformance/v1 \
  pytest -q tests/test_kura_receiver.py
```

通常のテストでは外部にあるfixture試験だけをskipし、同じ検証器のローカル回帰、
durable commit後ACK、重複・競合、commit失敗、既存Collector Shadow比較、KURA停止
試験に加え、再起動後のpending ACK回収、ACK完了の冪等性、異なるACK束縛値の拒否を
実行します。
