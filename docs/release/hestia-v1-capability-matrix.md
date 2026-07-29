# HESTIA v1 能力・適格性・配備マトリクス

更新日: 2026-07-28

## 目的

この表は、各 Integration が「コードとしてある」ことと、「家庭の実機で安全に読める」ことと、「常時運用へ配備済み」であることを分けて示す機械的な棚卸しです。リリース範囲を決める文書ではありません。v1 の採否は、[ロードマップ](hestia-v1-roadmap.md) と [チェックリスト](hestia-v1-checklist.md) の証拠をそろえた上で、別途決定します。

ここでは、コード、匿名 fixture、単体テストだけでは `live_qualified` または `deployed` にしません。実機の単発、短時間、24 時間の read-only 記録と、必要に応じた配備記録が必要です。

## 状態の意味

| 状態 | 意味 | 昇格に必要なもの |
| --- | --- | --- |
| `implemented` | 型・契約・実装が存在する。動作範囲は別の証拠で判断する。 | 対象の単体・契約テスト |
| `fixture_only` | 匿名 fixture とオフライン試験で確認済み。実機通信は未確認。 | 上限付き実機 read-only 適格性試験 |
| `reader_only` | 読み取り用の実通信経路はあるが、操作経路は含めない。常時運用は未確認。 | 単発→短時間→24時間の適格性証拠 |
| `shadow_only` | 操作意図、Gate、dry-run、結果確認契約はあるが、実機への送信はしない。 | 個別承認された実機試験と復元確認 |
| `live_qualified` | 実機 read-only 適格性が、定めた段階で客観的に確認済み。 | 運用監視・障害時手順・配備判断 |
| `deployed` | 正式な運用経路で稼働し、監視と復元手順も確認済み。 | 継続監視と変更管理 |
| `deferred` | 調査、仕様、機材、承認、または安全設計が不足しており、実装・運用を保留。 | 不足項目の解消と再審査 |

`reader_only` は「操作できない」という安全境界であり、実機適格性や配備済みを意味しません。`shadow_only` は、外部機器へ命令を送らないことを保証するための状態です。

## Integration 別の現状

| Integration | 読み取り能力の状態 | 操作能力の状態 | 配備状態 | 静的に確認できる根拠 | 次に必要な客観的証拠 |
| --- | --- | --- | --- | --- | --- |
| FusionSolar / SmartLogger | `reader_only` | `shadow_only` | `deferred` | Modbus 読み取り経路、収集・品質契約、オフライン試験 | [単発→短時間→24時間のread-only適格性](hestia-v1-fusionsolar-qualification.md)。操作は別承認 |
| SwitchBot（人感・人感 Pro・E26・テープライト3を含む） | `fixture_only` | `shadow_only` | `deferred` | 機種別 normalizer、匿名 fixture、能力・Gate・read-back 契約 | 機種別 read-only 適格性。低リスク操作は個別の復元確認 |
| Smart LEDZ Base | `fixture_only` | `shadow_only` | `deferred` | Reader、状態・プラン・予約の正規化、匿名 fixture | 実機の読取対象・頻度・欠損を確認し、操作は別承認 |
| EcoCute / ECHONET Lite | `fixture_only` | `shadow_only` | `deferred` | Get 専用の読取設計、property map と操作 Gate のオフライン試験 | property map の read-only 確認。沸き上げ等の送信は別承認 |
| Qrio Lock | `fixture_only` | `shadow_only` | `deferred` | 読取モデル、イベント・電池品質、操作 dry-run 契約 | 状態・履歴の read-only 確認。施錠・解錠は別承認 |
| Miele@home | `fixture_only` | `shadow_only` | `deferred` | 読取・SSE 契約、予約済みプログラム開始の dry-run 契約 | OAuth/SSE の有限 read-only 適格性。開始操作は別承認 |
| BRAVIA | `fixture_only` | `deferred` | `deferred` | REST/IRCC のオフライン状態モデルと fixture | 電源・状態の read-only 確認。Wake/入力等は別承認 |
| 日産サクラ | `fixture_only` | `shadow_only` | `deferred` | 読取モデル、充電・空調・施錠操作の dry-run 契約 | 公式経路の read-only 適格性。車両操作は個別承認 |
| WAREMA WMS | `fixture_only` | `deferred` | `deferred` | USB/無線プロトコル調査、匿名の受信・送信契約 | Stick と対象機器の段階的な読取・登録検証 |
| MTRL-RK-901SI | `deferred` | `deferred` | `deferred` | 調査成果のみ | 接続方式、読取能力、保護条件の確定 |
| Eufy 天候・映像補助 | `fixture_only` | `deferred` | `deferred` | 匿名の天候・画像判断設計と fixture。実機未配備 | カメラ・取得経路・保存期間・電力上限の read-only 適格性 |
| 北陸電力料金情報 | `fixture_only` | `deferred` | `deferred` | 公式一次情報を対象にした parser・履歴・訂正設計と匿名 fixture | 公式公開データの定期取得適格性と変更検知 |

## 横断能力

| 横断能力 | 状態 | 境界 |
| --- | --- | --- |
| 正規化・品質区分・欠損表現 | `implemented` | 事実、品質、受信時刻を分離し、欠損を前回値で埋めない |
| ExecutionIntent → ExecutionGate → OperationOutcome | `implemented` | 第3層の判断と第4層の送信・確認を分離する |
| dry-run・結果不明・安全停止 | `implemented` | 外部送信なしで操作計画を検証できる |
| event delivery と非同期保存 | `implemented` | 即時経路と保存失敗の分離は、専用負荷・障害試験で継続検証中 |
| 常時運用の scheduler / service | `deferred` | OS 固有の scheduler と本番配備は core から分離し、別の配備証拠が必要 |

## v1 の判断へ戻す事項

1. `fixture_only` と `reader_only` のどの Integration を、単発→短時間→24時間の read-only 適格性確認へ進めるか。
2. 低リスク操作の最初の対象、可逆な命令、成功確認、復元、中止条件を承認パッケージとして決めること。
3. FusionSolar の既存収集経路を `live_qualified` または `deployed` と扱うための、匿名化済み運用証拠の保管方法を決めること。
4. Eufy 映像補助について、人物検知・映像保存とは分離した取得目的、保存粒度、電力上限を決めること。
5. v1.0の保証対象はmacOSとする。Linux/Windows 実行証拠と、OS 固有の
   service・秘密注入 port の適格性は、移行先確定後の再適格化として別に判定すること。

## v1.0 最小保証範囲（利用者承認済み）

2026-07-28の利用者承認により、次をv1.0の最小保証範囲とする。この承認は範囲だけを
確定するものであり、実機適格性、運用監視、rollback確認を代替しない。

| 区分 | v1.0案 |
| --- | --- |
| 保証対象OS | macOS |
| 本番候補能力 | FusionSolar / SmartLoggerの既知Modbusレジスタによるread-only収集 |
| 実行モード | 全能力を既定`shadow`。実機への書き込み操作は保証対象外 |
| 延期する読み取り | SwitchBot、Smart LEDZ、EcoCute、Qrio、Miele、BRAVIA、日産サクラ、WAREMA、MTRL-RK-901SI、Eufy、北陸電力料金情報 |
| 延期する操作 | 発電停止、蓄電池充放電、照明、給湯、鍵、家電、テレビ、車両を含む全実機操作 |
| 本番昇格条件 | 単発・短時間・24時間の匿名read-only証拠、容量上限、監視、停止、復旧、rollbackの確認 |

延期項目は削除せず、`fixture_only`、`reader_only`、`shadow_only`、`deferred`として開発を継続
できる。ただし、追加の能力をv1.0の正式保証へ含める場合は、その能力ごとの実機適格性と
個別承認を必須とする。

## 更新規則

- 状態を上げるときは、この表の該当行だけでなく、適格性確認計画・テスト・匿名化済み実行証拠を同時に更新します。
- 実機の読取結果、IP、機器 ID、認証値、Raw 本文はこの文書へ記載しません。
- コード追加、fixture 追加、テスト成功だけでは `live_qualified` や `deployed` へ上げません。
- 仕様未確定の能力は推測して `implemented` にせず、`deferred` または `shadow_only` とします。
