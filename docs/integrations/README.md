# メーカー連携の正式知識

このディレクトリは、調査用ファイルを永久保存する場所ではない。メーカー連携を保守、
再調査、再実装するために必要な知識だけを、SumiCoreの現行設計に合わせて残す。

## 正本として残すもの

- 対象機種、確認したアプリ版・ファームウェア版・通信経路
- 確認済み事実、第三者情報、推測、未確認事項
- 読み取り項目、イベント、操作能力、安全条件
- 成功した方法だけでなく、失敗した方法と理由
- 保存対象、上限、保持期間、匿名fixture
- 更新時の再確認条件、廃止方法

調査用APK、AVD、逆コンパイル生成物、通信ログ、スクリーンショット、公開repositoryのclone、
cache、build生成物は正本にしない。必要な知識、実装、匿名fixture、テストへ凝縮した後、
照合と利用者承認を経て削除する。

## 版と根拠

すべての連携は途中であり、完成して固定されたものとはみなさない。解析、実機観測、
アプリやfirmwareの更新によって、知識、fixture、実装、運用条件は継続的に書き変わる。
各連携は、少なくとも次の情報を持つ。

- `knowledge_status`: `research`、`observation`、`read_only`、
  `limited_execution`、`production`、`degraded`、`deprecated`、`retired`
- `reviewed_at`: 最終監査日
- `observed_versions`: 実測した機種、アプリ、ファームウェア、protocol版
- `evidence`: 公式、実機、アプリ、通信、第三者実装、推測、未確認
- `recheck_triggers`: アプリ・firmware・API・認証・network経路・機器交換など

更新で挙動が変わった場合、古い事実を現在の事実として残さない。一方で削除して経緯を
失わず、「どの版まで有効だったか」を記録する。匿名fixtureは版ごとに分け、新旧両方を
回帰試験する。未確認版や未知schemaでは推測動作せず、`unknown`または`unsupported`で止める。

## 共通境界

- 読み取りと操作は、公開機能と実行経路を分ける。
- ①情報収集はreaderだけ、④操作・実行はexecutorだけを使う。
- ③情報利用・判断はメーカー固有commandを知らない。
- 共通Execution、保存、品質、秘密除去、災害判断をAdapterごとに複製しない。
- メーカー固有の通信、normalization、capability、errorだけをAdapterへ置く。
- SumiCore停止時も機器の安全機能、物理操作、純正アプリ、標準scheduleを残す。

詳細は[Adapterのライフサイクル](../adapter-lifecycle.md)、
[共通Execution契約](../execution-contract.md)、
[読み取り専用Adapter適格性確認](read-only-qualification-plan.md)、
[操作用Adapter適格性確認](operation-qualification-plan.md)、
[機器別の実機操作試験台帳](operation-live-test-ledger.md)、
[保存方針](../data-retention-policy.md)、
[秘密情報方針](../security-policy.md)を正とする。

## 現在の連携

| 連携 | 現在の知識状態 | 初期統合方針 |
|---|---|---|
| FusionSolar | observation / Modbus実観測中 | Modbus TCPを主経路候補として24時間の連続性を監視 |
| SwitchBot | observation、機種追加継続中 | 既存収集を保ち、機種profileを拡張 |
| Smart LEDZ | observation、Readerはオフライン検証済み | 実機read-only適格性確認を段階実施 |
| Qrio | observation、Reader/操作Adapterはオフライン検証済み | 実機適格性確認までは常駐・自動操作しない。指紋・暗証番号の自作連携は対象外 |
| エコキュート | observation、Reader/操作Adapterはオフライン検証済み | 実機property map確認と段階試験までは常駐・自動操作しない |
| Miele@home | observation、Readerはオフライン検証済み | 実OAuth/SSEを有限時間だけ適格性確認 |
| WAREMA | research | Stick到着後に段階検証 |
| BRAVIA | research | Sony REST能力照会から開始 |
| 日産サクラ | research | 規約と公式経路を確認するまで実装保留 |
| MTRL-RK-901SI | research | IR実測まで操作実装保留 |

この表は完成度ではなく、現在安全に言える段階を表す。`read_only`や`production`へ進んでも
解析が終了したことを意味せず、確認した版と能力だけがその状態になる。
