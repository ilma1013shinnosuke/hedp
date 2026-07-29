# HESTIA v1.0 リリース・チェックシート

## 使い方

本書は[正式リリース・ロードマップ](hestia-v1-roadmap.md)の実行記録である。
状態は次の四つだけを使う。

- `[x]` 証拠を確認して完了
- `[ ]` 未完了
- `[~]` 作業中または一部完了
- `[-]` v1.0対象外。理由と再検討条件を記載

各項目の`証拠`には、テスト名、文書、匿名レポート、実機試験台帳などを記載する。
秘密値、家庭固有ID、実データ、家庭内addressは記録しない。

## 0. 正本と範囲

- [x] `R0-01` HESTIAの思想と四層の責任境界が文書化されている
  証拠: `docs/system-philosophy.md`、`docs/01_collection.md`〜`docs/04_execution.md`
- [x] `R0-02` 機器標準機能を維持する非必須層である
  証拠: `docs/system-philosophy.md`
- [x] `R0-03` 全Integrationを実装、実機適格、配備状態に分けた能力表がある
  証拠: `docs/release/hestia-v1-capability-matrix.md`
- [x] `R0-04` v1.0必須・条件付き・延期の対象一覧を最終承認した
  証拠: 2026-07-28利用者承認。macOS上のFusionSolar / SmartLogger read-only収集だけを
  本番候補とし、他の読み取りと全実機操作をv1.0対象外とする
- [x] `R0-05` 指紋解錠の自作機能をv1.0対象から除外した
  証拠: 利用者決定。実装対象に追加しない

## 1. 共通契約とOS非依存

- [x] `R1-01` Observation、品質、欠損、鮮度の共通語彙がある
  証拠: `docs/observation-contract.md`
- [x] `R1-02` ReaderとExecutorの公開機能が分離されている
  証拠: `docs/adapter-public-api-boundaries.md`
- [x] `R1-03` timeoutとretryは機器別設定、上限と失敗記録は共通である
  証拠: `docs/adapter-lifecycle.md`、`docs/execution-contract.md`
- [x] `R1-04` 結果不明を成功扱いせず、危険操作を再送しない
  証拠: `docs/execution-contract.md`、契約テスト
- [x] `R1-05` macOS固有機能をcoreとAdapterから分離している
  証拠: `docs/portability-boundaries.md`、`tests/test_platform_boundaries.py`。
  Core・AdapterのOS固有import／固定パス／launchd／Keychain依存を静的検査し、18件の関連テストが成功
- [-] `R1-06` Linux環境で共通契約と主要fixtureテストが成功した
  理由: v1.0はmacOS運用版とする。Linux移行先が確定した時点で再適格化して対象へ戻す
- [-] `R1-07` Windowsで必要な範囲と未対応部分を明示した
  理由: v1.0はmacOS運用版とする。Windows移行が具体化した時点で対象範囲を確定する

## 2. 第1層・読み取り適格性

- [~] `R2-01` FusionSolar / SmartLogger Reader
  証拠: Modbus実装・監視あり。24時間結果とクラウド重複整理を要確認
- [-] `R2-02` SwitchBot Reader
  理由: v1.0対象外。実装とfixtureを維持し、実機適格性確認後の次版候補とする
- [-] `R2-03` Smart LEDZ Reader
  理由: v1.0対象外。実装とfixtureを維持し、実機適格性確認後の次版候補とする
- [-] `R2-04` エコキュート Reader
  理由: v1.0対象外。property map・INF・実機適格性確認後の次版候補とする
- [-] `R2-05` Qrio Reader
  理由: v1.0対象外。継続利用条件と実機適格性確認後の次版候補とする
- [-] `R2-06` Miele@home Reader
  理由: v1.0対象外。秘密再発行確認と実機適格性確認後の次版候補とする
- [-] `R2-07` BRAVIA Reader
  理由: v1.0対象外。fixture限定batch readerとして維持する
- [-] `R2-08` 日産サクラ Reader
  理由: v1.0対象外。実機能力、認証、継続性の適格性確認後の次版候補とする
- [-] `R2-09` 北陸電力料金情報Reader
  理由: v1.0対象外。KURAの公開情報による最小実証候補として別に扱う
- [x] `R2-10` 本番対象Readerごとに単発試験が合格した
  証拠: 2026-07-28、FusionSolar / SmartLoggerの有限read-only runnerで1 sampleが合格。
  失敗・再試行・再発見は0回。匿名証拠DBはmode 0600、家庭内アドレス・機器名・
  識別子・register番号の混入0件。局所回帰35件、Ruff、差分形式検査も合格。
  実測値、Raw、秘密値は証拠へ保存していない
- [x] `R2-11` 本番対象Readerごとに短時間試験が合格した
  証拠: 2026-07-28、FusionSolar / SmartLoggerの有限read-only runnerで
  15分間に5分間隔の3 sampleが全件合格。失敗・再試行・再発見は0回、
  最大取得時間82ms。匿名証拠DBはmode 0600、家庭内アドレス・機器名・
  識別子・register番号の混入0件
- [x] `R2-12` 本番対象Readerごとに24時間試験が合格した
  証拠: `docs/release/hestia-v1-fusionsolar-qualification.md`。既存収集履歴の
  24時間窓で279/288 sample（96.88%）、最大欠損731.657秒、15分超欠損0件。
  開発Mac停止由来の欠損を許容する利用者承認付き判定であり、通常の99%基準と
  将来運用機の再適格化条件は維持する
- [x] `R2-13` Schema変更、未知値、欠損、復旧を安全に区別できる
  証拠: `tests/test_fusionsolar_read_only_qualification_runner.py`、
  `tests/test_read_only_qualification_harness.py`。未知metric、欠損metric、不正値を
  個別reason codeで失敗させ、欠損後の最初の正常sampleを`recovered`として区別する
- [x] `R2-14` 取得周期がGit管理外設定で変更でき、日次容量上限がある
  証拠: `scripts/collection_schedule.sh`、`tests/test_operational_scripts.py`。
  Git管理外設定を300〜3600秒に制限し、定時収集を最大1日288回に抑える

## 3. 第2層・データ保存と復元

- [x] `R3-01` 保存価値を八基準と保存クラスで評価する
  証拠: `docs/data-retention-policy.md`
- [x] `R3-02` 離散状態、イベント、連続値、観測coverageを分ける
  証拠: `docs/data-retention-policy.md`
- [x] `R3-03` 想定外値を0、空文字、前回値で埋めない
  証拠: `docs/data-retention-policy.md`
- [x] `R3-04` checksum付き可逆JSONL gzip部品がある
  証拠: `src/hedp/storage/jsonl_archive.py`
- [~] `R3-05` Adapterごとの保存辞書が承認済みである
  証拠: schemaと例は存在。全本番sourceの承認が未完了
- [~] `R3-06` 原子的DBバックアップと容量不足時の保護がある
  証拠: 実装済み。別障害領域の正本と定期復元試験が未完了
- [-] `R3-07` 別障害領域へ暗号化複製し、隔離復元試験が成功した
  理由: 2026-07-30利用者が、外部backupなしで進める残存リスクを受容し、
  v1.0リリース条件から外して運用改善へ延期した。Macの故障、盗難、火災等で
  現役DBと同一障害領域のbackupを同時喪失し得ることを既知制限とする
- [-] `R3-08` 現役DBの日次増加量と10年容量を実測から更新した
  理由: 2026-07-30利用者承認により、30日観測の完了をv1.0リリース条件から外し、
  リリース後の運用改善へ延期する。匿名容量probeは継続し、容量不足時も自動削除、
  compact、保持期間短縮を行わない。問題を検出した場合は別の設計変更として審査する
- [x] `R3-09` 実データ削除前の七条件を満たす運用Gateがある
  証拠: `docs/data-retention-policy.md`、
  `scripts/validate_retention_dictionary.py`、`tests/test_retention_dictionary.py`。
  七条件を固定語彙で一対一に要求し、一条件でも欠ける辞書を拒否する。
  実削除は対象別の実証と利用者承認まで実行しない

## 4. 即時イベントと非同期処理

- [x] `R4-01` 即時経路と保存・集計・Raw転送を分離する契約がある
  証拠: `docs/event-delivery-contract.md`
- [~] `R4-02` 有界キュー、順序、重複排除、背圧、上限付き再送が実装されている
  証拠: `src/hedp/events/`と関連テスト。全Integration適用は未完了
- [~] `R4-03` SwitchBot人感→Smart LEDZのオフライン縦切りがある
  証拠: motion lighting実装と匿名fixture。実機送信は未実施
- [x] `R4-04` 保存遅延・失敗時にも即時経路が遅延しない負荷試験が合格した
  証拠: `tests/test_event_delivery.py`のslow persistence、queue backpressure、
  retry exhaustion試験。即時handler完了前に非同期保存を待たない
- [x] `R4-05` KURA停止が即時経路や安全停止へ波及しない契約試験が合格した
  証拠: `tests/test_event_delivery.py`のKURA failure、stall、backpressure隔離試験
- [-] `R4-06` 全操作が保存・集計・KURAを待たない共通即時実行sessionを利用する
  理由: 全実機操作をv1.0対象外とした。共通session実装は次版へ維持する

## 5. 第3層・判断

- [x] `R5-01` 第3層が価値判断、第4層が実行条件確認という境界がある
- [x] `R5-02` 最小の太陽光自家消費機会判断が匿名fixtureで再現できる
- [-] `R5-03` 利用者へ、入力品質、根拠、予測幅、判断しない理由を表示できる
  理由: 自動判断をv1.0対象外とした
- [-] `R5-04` 経済性、快適性、健康、安全、利用者指示の優先関係を実例で確認した
  理由: 自動判断をv1.0対象外とした
- [-] `R5-05` 判断頻度を増やしても、操作回数と状態振動が上限内である
  理由: 自動判断と実機操作をv1.0対象外とした
- [-] `R5-06` 3週間の観測等、家庭傾向の学習前に危険な最適化を開始しない
  理由: 自動最適化をv1.0対象外とした。観測は将来判断の証拠として継続できる

## 6. 第4層・操作適格性

- [x] `R6-01` 共通Intent、ExecutionGate、receipt、verification、outcomeがある
- [x] `R6-02` Shadowとオフラインfixture試験がある
- [~] `R6-03` Adapter直接呼出しを禁止する契約試験がある
  証拠: 共通Execution経路あり。本番入口を含む横断確認が必要
- [-] `R6-04` 操作能力ごとの復旧方法、停止条件、確認期限を確定した
  理由: 全実機操作をv1.0対象外とした
- [-] `R6-05` 低リスク能力の単発実機試験が合格した
  理由: 全実機操作をv1.0対象外とした
- [-] `R6-06` 操作後の短時間監視と手動介入優先が合格した
  理由: 全実機操作をv1.0対象外とした
- [-] `R6-07` Qrioの施解錠を初期既定で毎回承認にしている
  理由: Qrio操作をv1.0対象外とした。次版でも個別承認を維持する
- [-] `R6-08` エコキュートの凍結防止・衛生・安全制御を妨げない
  理由: エコキュート操作をv1.0対象外とした。次版の必須安全条件として維持する
- [-] `R6-09` 発電停止、蓄電池、車両、鍵等の高影響操作を個別審査した
  理由: 高影響操作をv1.0対象外とした。能力追加時に個別審査する
- [-] `R6-10` Smart LEDZの明るさ・色温度・所要時間を指定した段階変更がある
  理由: Smart LEDZ操作をv1.0対象外とした。匿名fixture実装は次版へ維持する
- [-] `R6-11` 全操作能力で指示受付から最初の送信試行までの遅延上限を定義・実測した
  理由: 全実機操作をv1.0対象外とした。能力追加時の必須条件として維持する

## 7. UI、通知、運用負担

- [~] `R7-01` ブラウザで状態を確認できる試作画面がある
- [x] `R7-02` 値、品質、更新時刻、取得不能を明確に区別して表示する
  証拠: `src/hedp/web/read_model.py`、`src/hedp/web/static/app.js`、
  `tests/test_web_interface.py`。値と観測時刻を分離し、`good`、`stale`、
  `invalid`、`missing`を異なる表示へ変換する
- [-] `R7-03` 操作依頼、受付、実状態、最終結果を時系列で表示する
  理由: 全実機操作をv1.0対象外とした
- [ ] `R7-04` 太陽光・蓄電池を期間変更可能なグラフで表示する
- [x] `R7-05` 警告の重複抑止、継続中、復旧、次の行動を表示する
  証拠: `src/hedp/web/static/app.js`、`tests/test_web_interface.py`。
  同一警告のtoastを再送せず、継続中、復旧、品質別の次の行動を表示する
- [x] `R7-06` 管理時間、警告数、手動復旧数を測定できる
  証拠: `src/hedp/operations/operational_metrics.py`、
  `scripts/record_operational_metric.py`、`tests/test_operational_metrics.py`。
  警告確認と手動復旧の件数、粗い対応時間を自由文なしで記録・集計できる
- [ ] `R7-07` タッチ画面とスマートフォンで主要表示を操作できる

## 8. セキュリティと正式リリース

- [x] `R8-01` 秘密情報・環境固有情報・個人データの分類がある
  証拠: `docs/security-policy.md`
- [x] `R8-02` 秘密をGit、fixture、通常ログへ出さない検査がある
  証拠: `docs/release/hestia-v1-quality-gate-20260728.md`。Philip snapshot 364の
  秘密情報検査はCritical 0で合格
- [x] `R8-03` OS非依存の暗号化秘密正本と復旧方法を確定した
  証拠: Mac Keychainの衝突しないstable名、対話登録、非表示確認、
  `SOPS_AGE_KEY_CMD`取得、限定削除、平文を捨てるSOPS疎通確認を
  `scripts/manage_hestia_age_keychain.py`と専用テストへ実装。
  Mac用鍵のKeychain登録、Mac・sanctumの公開recipient台帳化、各端末の
  非秘密SOPS実疎通probeを完了。既存`.env`を変更せず両recipient向け
  `secrets/runtime.sops.env`を作成し、Macとsanctumで同一SHA-256の正本を
  平文非出力で復旧した。匿名receipt:
  `config/release/receipts/hestia-sanctum-sops-recovery.json`
- [x] `R8-04` HESTIA停止、DB障害、通信断、Schema変更の訓練が合格した
  証拠: `tests/test_hestia_operational_failure_drills.py`、
  `tests/test_operational_scripts.py`のlaunchd switcher隔離試験、
  `docs/release/hestia-v1-failure-drills.md`。匿名fixture、新job起動失敗時の
  legacy復元、現役read-only job停止・再起動、隔離DB利用不能、TEST-NET通信断が合格
- [x] `R8-05` 再起動時に古い状態と未完了Intentを再生しないことを確認した
  証拠: 即時session、Shadow registry、人感timeout、段階照明の個別再生防止試験、
  `docs/release/hestia-v1-failure-drills.md`の2026-07-30常駐job再起動。
  read-only job再起動後は現在状態を新規取得し、保存済みIntentやExecutor送信はない
- [x] `R8-06` 本番対象の24時間監視と必要な長期監視が合格した
  証拠: FusionSolar / SmartLogger read-onlyの24時間窓は合格。
  2026-07-30利用者承認により30日容量評価はリリース後へ延期し、既存の匿名容量probeと
  日次監視を継続する。運用機変更時は24時間適格性を再実施する
- [x] `R8-07` 既知制限、rollback、保守手順、緊急停止をまとめた
  証拠: `docs/release/hestia-v1-operations-runbook.md`、
  `tests/test_operational_scripts.py`のlaunchd switcher隔離試験、
  `docs/release/hestia-v1-failure-drills.md`の2026-07-30常駐job停止・再起動。
  実環境では失敗時のlegacy復元を有効にして新jobを再起動し、現在観測への復旧を確認
- [x] `R8-08` 全release blockerが解消またはv1.0対象外として承認された
  証拠: `docs/release/hestia-v1-release-blockers.md`。R3-07とR3-08は利用者が
  リスク受容して延期し、R8-03とR8-09を証拠付きで完了後、R8-10で最終承認した
- [x] `R8-09` 最終の全テスト、lint、秘密検査、差分検査が成功した
  証拠: `docs/release/hestia-v1-quality-gate-20260730.md`。R8-03反映後の
  Philip snapshot 554で1078テスト、lint、compile、秘密検査、差分検査が合格
- [x] `R8-10` v1.0 release candidateを利用者が承認した
  証拠: 2026-07-30、利用者が`docs/release/hestia-v1-approval-summary.md`の
  保証範囲、延期項目、既知制限、rollback、最終品質結果を確認して承認

## 9. KURA接続準備

- [x] `K0-01` KURAをv1.0の必須経路にしない
- [x] `K0-02` HESTIAが正規化、判断、実行の責任を維持する
- [x] `K0-03` 即時イベント処理がKURA保存完了を待たない
- [ ] `K0-04` 取得依頼Schemaを確定した
- [ ] `K0-05` Raw配達envelopeと内容hash規則を確定した
- [ ] `K0-06` 受領確認と冪等性契約を確定した
- [ ] `K0-07` 非公開Rawの受領後消去と消去証跡を契約試験で確認した
- [ ] `K0-08` 秘密参照、許可domain、最小権限、親鍵分離を設計レビューした
- [ ] `K0-09` KURA停止、遅延、重複、順序逆転、容量超過を試験した
- [ ] `K0-10` 公開情報一件で最小実証を開始した
- [ ] `K0-11` 現行版とKURA版のRaw hash、時点、欠損、停止動作を比較した
- [ ] `K0-12` 正規化結果の同等性を確認した
- [ ] `K0-13` 既存Collector削除を、比較完了後の別承認にしている
- [ ] `K0-14` 実際の資格情報を初回実証で移動・複製していない

## 最終判定欄

| 項目 | 記録 |
|---|---|
| Release candidate | hestia-v1.0 |
| 判定日 | 2026-07-30 |
| 必須項目 | 完了 |
| 条件付き項目 | なし |
| 延期項目 | 外部backup、30日容量評価、保証対象外Reader・全実機操作 |
| 既知制限 | 同一障害領域のDB・backup同時喪失、長期容量実測未完了 |
| Rollback手順 | `docs/release/hestia-v1-operations-runbook.md` |
| 最終承認 | 2026-07-30 利用者承認済み |
