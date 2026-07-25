# 匿名運用メトリクス

## 目的

収集やbackupを止めずに、DB増加、空き容量、lock見送り、timeout、失敗を測る。
生活データ、機器情報、秘密、外部応答を運用メトリクスへ複製しない。

## 保存内容

操作メトリクスは次の固定語彙だけを持つ。

- 記録日: UTCの日付。正確な時刻は保存しない。
- job: `device_realtime`、`switchbot`、`equipment`、`daily_health`、`daily`
- outcome: `completed`、`skipped`、`timed_out`、`failed`
- duration: `under_1s`、`1_to_5s`、`5_to_30s`、`30s_or_more`
- failure_category: `none`、`lock_held`、`timeout`、`network`、
  `invalid_response`、`configuration`、`internal`、`unknown`

DB容量probeは、status、DB容量、filesystem空き容量、page数、free page数、
共通Raw・Recordの件数、粗い実行時間だけを持つ。SQLiteをread-only・即時timeoutで開き、
値、payload、識別子、時刻列、DB path、例外本文は返さない。

## 保存しないもの

- センサー値、電力値、在室・生活イベント
- device ID、家庭固有ID、IP、SSID、MAC
- DB path、repository path、利用者名
- request、response、URL、header、token、cookie、password
- 例外本文、command全文、process引数
- 秒・分を含む正確な実行時刻

## 保存先と上限

保存先は`XDG_STATE_HOME`配下、さらに未設定なら
`~/.local/state/sumicore/operational-metrics.jsonl`を使用する。

directoryは0700、fileは0600とし、symlinkを拒否する。ファイルは上限到達時にrotateし、
現行と旧2世代だけを残す。メトリクス記録の失敗によって、本来の収集、health check、
backupの終了結果を変更しない。

## 使い方

各定期jobは、開始からの経過秒を保存scriptへ渡す。保存scriptは粗いdurationへ変換し、
正確な値を残さない。

- lock取得失敗: `skipped / lock_held`
- wall-clock timeout: `timed_out / timeout`
- 正常完了: `completed / none`
- その他の異常終了: `failed / internal`

日次jobは終了時にread-only DB容量probeも1回記録する。これにより、現役DBへ新しいtableを
作らず、30日分の増加傾向とbackup余裕を確認できる。

## 判断への利用

最初の30日は削除やcompactの自動判断へ使わず、実測だけを行う。その後、次を確認する。

- 日次・月次のDB増加量
- 次回atomic backup必要量に対する空き余裕
- job別のlock見送り回数
- timeoutと失敗の回数
- 一つの取得元の遅延が他jobへ与える影響

保存期間、archive、DB分離、source別queue/lockは、この実測を確認してから決める。

## 集計

`scripts/summarize_operational_metrics.py`は現行ファイルと旧2世代をread-onlyで読み、
日付・job・outcome・failure_category・duration別の件数と、正常なDB容量観測の最初から最後までの
差分だけをJSONで出力する。不正行、未知語彙、余分な項目を持つ行は内容を表示せず件数化する。
警告や削除・compact判断は行わない。

通常の日次DB probeは、ファイル容量、filesystem空き容量、SQLiteのpage数とfree page数だけを
取得する。巨大tableの`count(*)`は負荷が読めないため実行しない。行数取得は、保守担当者が
影響を確認して明示的に指定する診断時だけに限る。

メトリクスはこのMac内のprivateなstate directoryだけへ保存し、外部送信しない。現行1 MiBと
旧2世代を上限とし、DB、Raw、機器識別子、家庭内address、payload、例外本文は保存しない。
日付単位のDB容量とjob結果は同じ日に観測された事実にすぎず、個々の実行との因果関係を
示すものではない。

現在のshell runnerが確実に分類できる失敗は`lock_held`、`timeout`、`internal`である。
`network`、`invalid_response`、`configuration`、`unknown`は将来Adapterが安全に判別できる
場合の予約語彙であり、例外本文から推測して分類しない。

SwitchBot収集は既定180秒（設定可能範囲1〜600秒）、equipment収集は既定300秒
（設定可能範囲1〜1800秒）のwall-clock上限を持つ。変更にはそれぞれ
`SUMICORE_SWITCHBOT_TIMEOUT_SECONDS`、`SUMICORE_EQUIPMENT_TIMEOUT_SECONDS`を使い、
旧`HEDP_...`名も移行期間だけ受理する。不正値を無制限実行へ読み替えず、実行前に失敗させる。

複数jobの同時記録では、appendとrotationを短時間のprivate lockで直列化する。0.5秒以内に
取得できなければメトリクス記録だけを諦め、収集job本体の終了結果は変更しない。古いlockは
所有processが確実に終了した場合、または作成途中の空directoryだけを回復対象とし、不明な
lockを推測で削除しない。

## 30日観測中の警告基準（原案）

この章は、収集そのものの成否と、運用者へ伝える注意度を分けるための基準である。初回の
30日間は**観測専用**とし、警告を理由に自動削除、DB compact、設定変更、job再実行、retry、
service再起動を行わない。通知先や表示方法も、この文書では決めない。

### 共通原則

- 単発の `skipped`、`timed_out`、`failed` は記録するだけで、警告に昇格しない。
- 閾値は、同じjobの予定回数に対する割合と、連続性の両方で評価する。異なるjobを足し合わせない。
- `unknown` は異常ではない。予定回数、記録期間、DB容量probeのいずれかが不足するときは、判定を保留する。
- `critical` は「次回backupを安全に開始できない」など、待つほど復旧余地を失う条件だけに限る。
- すべての段階で、初期動作は記録と人への提示だけである。自動修復は、別途設計・試験・承認後にしか追加しない。
- 判定はUTC日付と粗いdurationだけで行い、OS、service manager、実行パス、機器や家庭の識別子を前提にしない。

### サンプル充足度

| 対象 | `unknown` を解除する最小条件 | 備考 |
| --- | --- | --- |
| job別のskip/timeout/failed | 観測7日以上、かつ予定回数の80%以上が記録されている | 日次jobは5回以上、より頻繁なjobは20回以上も必要。予定回数を確定できない場合は常に`unknown`。 |
| DB増加 | 日次容量probeが14日以上連続している | 30日未満は暫定比較だけで、増加を異常確定しない。 |
| backup余裕 | 同日のDB容量とfilesystem空き容量が取得できる | probe失敗、または必要量が計算できない場合は`unknown`。 |

観測1〜6日は全項目を`unknown`、7〜13日はjob健全性だけを暫定評価、14〜29日はDB増加を
暫定評価、30日目以降に30日基準線との比較を開始する。欠測が多い期間は、日数が経過しても
基準線へ昇格させない。

### 段階評価

| 対象 | observe（記録のみ） | warning（要確認） | critical（早期確認） |
| --- | --- | --- | --- |
| lock skip | 単発、または充足前 | 同一jobで7日内3回以上、または7日比率5%以上 | 同一jobで連続3回、または充足後の24時間比率20%以上 |
| timeout | 単発、または充足前 | 同一jobで7日内2回以上、または7日比率3%以上 | 同一jobで連続3回、または直近24時間に正常完了がなくtimeoutが継続 |
| failed | 単発、または充足前 | 同一jobで7日内2回以上、または7日比率3%以上 | 同一jobで連続3回、または直近24時間に正常完了がなく失敗が継続 |
| backup余裕 | 必要量の120%以上を維持 | 必要量の100〜120%が2日連続 | 必要量を下回る、またはbackupの開始前容量確認が不足を報告 |
| DB増加 | 30日基準線の2倍未満 | 30日基準線の2倍超が3日連続 | 30日基準線の4倍超が3日連続、かつbackup余裕もwarning以上 |

比率は `該当outcome数 / 予定回数` とする。予定回数が不明な場合、件数だけでwarningや
criticalへ上げない。連続回数は「そのjobの連続する予定実行」で数え、Macのsleep、OS更新、
明示的な停止を記録から推測して障害扱いにしない。

backupの必要量は、現行の開始前判定と同じく概ね `DB容量 + max(DB容量の20%, 512 MiB)`
を用いる。「必要量の120%」は、この必要量に対するfilesystem空き容量である。容量不足は
backupを始める前に止める安全機構であり、`critical` になっても古いbackup、Raw、DBを
自動削除しない。

DB増加の30日基準線は、日次の正の増分の中央値を使う。初期import、手動保守、DB rebuild、
archive試験など、通常収集でない日が判明している場合は基準線から除外候補として運用者が
注記し、自動で除外しない。増加警告は保存期間変更の根拠を集めるためのものなので、単独では
保持削減やcompactの実行条件にしない。

### 30日後の見直し

30日終了時は、各jobについて予定回数、記録率、正常率、skip/timeout/failedの連続性、
DBの日次増分中央値、backup余裕の最小値だけを集計する。その集計をもとに、次のいずれかを
人が選ぶ。

1. 基準を維持してさらに30日観測する。
2. job別の閾値を、実測された予定回数に合わせて見直す。
3. lock分離、収集経路の分離、容量対策を別タスクとして設計する。

この見直しでも、実データ、例外本文、秘密、機器識別子を集計へ追加しない。自動削除・
compact・retryを提案する場合は、対象、可逆性、復旧手順、別途承認を明記した独立した
変更として扱う。
