# HESTIA v1 FusionSolar / SmartLogger read-only適格性確認

更新日: 2026-07-29

## 目的と範囲

HESTIA v1.0の最小保証候補であるFusionSolar / SmartLoggerのread-only収集を、
単発、短時間、24時間の順に確認する。対象は既知のModbusレジスタと
Function Code 3/4による読み取りだけである。

この確認では、SmartLogger、インバーター、蓄電池、家庭LAN、launchdの設定を
変更しない。Modbus書き込み、発電停止、充放電指示、探索的なレジスタ走査、
オプティマイザー取得、クラウドAPI操作は行わない。

## 共通条件

- 秘密情報は`.env`から実行時だけ読み、値を画面、ログ、証拠、Gitへ出さない。
- IP、機器ID、シリアル番号、家庭固有名称、Raw本文を適格性証拠へ残さない。
- 既存の5分収集より高い頻度で問い合わせない。
- 取得周期はGit管理外設定で変更できるが、v1.0適格性確認では300秒に固定する。
  設定下限も300秒であり、定時収集は最大1日288回を超えない。
- 欠損、未知値、古い値を0、前回値、成功として補わない。
- 試験中に設定差分、機器への悪影響、想定外の対象、未知のデータ構造を検知したら停止する。
- 試験結果は匿名集計だけを専用manifestへ記録し、本番DBを証拠置場として扱わない。

## 段階1: 単発

1回だけ上限付きread-only取得を行う。

実行入口:

```text
.venv/bin/python scripts/run_with_env.py .env -- \
  .venv/bin/python -m hedp.adapters.fusionsolar.read_only_qualification_runner \
  --stage single \
  --database /private/tmp/hestia-fusionsolar-single.qualification.sqlite3
```

合格条件:

- 接続と読み取りが設定済みtimeout内に完了する。
- 確認済み10指標が、metric、単位、有限数値を保ったまま正規化される。
- 未知値と欠損は品質情報を伴って明示される。
- 設定変更、書き込み要求、秘密値出力、機器影響がない。
- 匿名manifestへ開始・終了時刻、sample数、結果を記録できる。

2026-07-28実測結果:

- 1回のread-only sampleが合格し、失敗・再試行・再発見は0回だった。
- 確認済み10指標の契約を満たした。実測値そのものは証拠へ保存していない。
- 匿名証拠DBはPOSIX mode `0600`、家庭内アドレス・機器名・識別子・
  register番号の検出数は0件だった。
- 機器設定、本番DB、launchd、既存収集経路は変更していない。
- 局所回帰35件、Ruff、差分形式検査が合格した。

## 段階2: 短時間

既存の5分周期を使い、15分以上観測する。合格判定には3件以上のsampleを必要とする。
追加の高頻度pollingは行わない。

実行入口:

```text
.venv/bin/python scripts/run_with_env.py .env -- \
  .venv/bin/python -m hedp.adapters.fusionsolar.read_only_qualification_runner \
  --stage short \
  --database /private/tmp/hestia-fusionsolar-short.qualification.sqlite3
```

合格条件:

- 3件以上のread-only sampleが得られる。
- 各sampleを同じ10指標へ再生成できる。
- sample間隔、欠損、timeout、品質が匿名集計される。
- 一時的な取得不能を成功扱いせず、次回取得で正常状態へ戻ったことを区別できる。
- 設定変更、秘密値出力、機器影響がない。

実施記録:

- 2026-07-28、15分間に5分間隔で3 sampleを取得し、3件すべて合格した。
- 失敗、再試行、再発見は0回。最大取得時間は82msだった。
- 匿名証拠DBはmode 0600で、家庭内アドレス、機器名、識別子、
  register番号の混入は0件だった。

## 段階3: 24時間

Macのsleep、再起動、明示停止を挟まない新しいcontinuity epochを24時間観測する。
既存の5分周期を上回らない有限runnerを使用する。

実行入口:

```text
.venv/bin/python scripts/run_with_env.py .env -- \
  .venv/bin/python -m hedp.adapters.fusionsolar.read_only_qualification_runner \
  --stage day_24 \
  --database /private/tmp/hestia-fusionsolar-day24.qualification.sqlite3
```

中断時は表示された同じrun IDと開始時刻を指定して再開する。開始時刻を変えて
別epochを結合してはならない。

合格条件:

- 24時間以上の連続観測。
- 5分slotの充足率が99%以上。
- 15分を超える欠損がない。
- 各Rawから確認済み10指標をmetric、単位、有限数値まで一致して再生成できる。
- 最新snapshotが所定の鮮度内にある。
- boot、sleep、再起動をまたぐ区間を同じ24時間として結合しない。
- timeout、DB lock、ログ容量に異常がない。
- 設定変更、秘密値出力、機器影響がない。

Macが停止またはsleepした場合、その窓を推測で補正せず、復帰後の新しいepochから
24時間を取り直す。開発Macで合格しても、将来運用機を変更した場合は再適格化する。

### 2026-07-29 運用履歴による判定

利用者の承認により、開発Macの再起動・ChatGPT停止に起因する欠測を機器・Readerの
失敗とは扱わず、既存の本番収集履歴から24時間窓を判定した。この例外判定は今回の
開発Mac上の適格性だけに適用し、上記の通常基準と将来運用機の再適格化条件は変更しない。

- 判定窓: 2026-07-28 05:42:21.493529 JST から
  2026-07-29 05:41:58.471705 JST。
- read-only Raw sampleは279件、5分slotの名目288件に対する充足率は96.88%。
- 最大sample間隔は731.657秒、15分を超える欠損は0件。
- 各Rawから確認済み10指標を正規化している。
- 設定変更、書き込み要求、秘密値出力、機器影響は確認されていない。
- 利用者承認済みの欠損許容基準では合格とする。
- 匿名集計文字列のSHA-256は
  `fc0b6d8e05f40ef5ddca889dedc4ea922ce96aab159b409666ec535183838467`。

通常の99%基準との差は明示して残し、将来の監視では同じ例外を自動適用しない。

## 中止条件

次のいずれかで、その段階を不合格または結果不明として停止する。

- 読み取り以外のFunction Codeまたは送信要求を検知した。
- 許可した対象・レジスタ範囲から外れた。
- timeoutや接続失敗が上限を超えた。
- 応答後、保存後、結果不明の処理を自動再試行しようとした。
- schema変更、異常値、未知値を正常値へ変換できない。
- 機器、家庭LAN、他の収集処理への影響が疑われる。
- 秘密値や家庭固有識別子が出力へ混入した。

## 証拠と昇格

候補manifestは
`config/release/qualification/fusionsolar-smartlogger-read-only.json`
に置く。

全段階に実測の開始・終了時刻、sample数、`pass`、匿名集計のSHA-256が入り、
内容をレビューしてから、能力を`live_qualified`候補としてprofileへ登録する。
その後も、監視、停止、復旧、rollbackを確認するまでは`deployed`にしない。

2026-07-30、単発・短時間段階を同じ有限read-only条件で再実施し、単発1 sample、
短時間3 sampleがすべて合格した。正確な開始・終了時刻を専用匿名証拠DBから
manifestへ統合し、三段階を`pass`として`live_qualified`候補へ登録した。
この登録は常駐配備完了を意味せず、`deployed`への昇格は別判定とする。

実機適格性の開始、現役収集経路の変更、launchd変更、本番昇格は、それぞれ対象、
影響、確認方法、復旧方法を示して別途承認を得る。

関連資料:

- [能力・適格性・配備マトリクス](hestia-v1-capability-matrix.md)
- [運用保証方針](hestia-v1-operational-assurance.md)
- [Modbus TCP切替・旧方式廃止基準](../integrations/fusionsolar/modbus-cutover.md)

継続監視の匿名窓集計は`scripts/summarize_modbus_read_only_window.py`を使う。
現役DBをread-only・即時timeoutで開き、承認済みModbus sourceの時刻だけから
sample数、最大欠損、15分超欠損を返す。payload、値、DB path、識別子は返さない。
