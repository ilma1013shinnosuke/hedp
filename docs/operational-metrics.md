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
