# 共通Observation契約

## 目的

メーカーや通信方式が異なっても、観測された事実を同じ意味で保存・比較できるようにする。
Adapterは取得とメーカー固有形式の変換を担当し、保存期間、集計、自動判断、操作を担当しない。

## イベントと定期照合

- 状態変化を通知できる機器は、eventを主経路として秒以下の発生時刻を保持する。
- すべての機器は、負荷に応じた有限周期のread-only取得で現在状態を照合する。
- event欠落、切断、再起動後は、定期または再接続直後のsnapshotで正しさを回復する。
- 通知されなかったfieldを`missing`にせず、部分更新として扱う。
- 定期取得の周期を機器間で無理に揃えない。必要な鮮度を満たす最も低い頻度を選ぶ。

## 時間粒度

- event ledger: 元の秒・ミリ秒精度を失わない。
- current state: 最新値を更新し、同一値の履歴を無制限に増やさない。
- cross-device series: 第2層で1分bucketへ整列する。
- long-term aggregate: 必要に応じて5分、1時間、1日へ集約する。
- Rawとeventから再生成できる集計値を、Rawと同じ保存期間で重複保持しない。

取得周期と分析粒度は別概念である。例えばSSE event、30秒poll、5分pollが混在しても、
第2層が1分bucketへ整列すれば機器横断の前後関係を比較できる。

## 必須field

- `value`: 取得値。欠損、異常、意味不明では`null`。
- `quality`: `good`, `stale`, `missing`, `invalid`, `estimated`, `unknown`。
- `reason`: good以外になった機械可読な理由。
- `observed_at`: 機器または提供元で事実が発生したtimezone付き時刻。
- `received_at`: SumiCoreが受信したtimezone付き時刻。
- `last_success_at`: 過去の正常値を示す必要がある場合だけ保持する。

`0`、空文字、前回値を欠損の代用にしない。提供元に発生時刻がないsnapshotでは、
取得時刻を`observed_at`として使い、その事実をsource contractへ明記する。

## 重複と順序

- 提供元event IDがある場合は、秘密・家庭固有値を出さないdedupe keyへ変換する。
- 同一eventの再受信は受信事実を監査できるが、状態変化を二重適用しない。
- 遅れて届いたeventを上書きせず、発生時刻と受信時刻の両方で順序を説明する。
- 訂正・取消・反対方向の変化は、新しい事実として保持する。

## Linux移行

Adapterと正規化はPython 3.11以上のOS非依存コードとする。Keychain、launchd、GUI、
固定ユーザーパス、OS固有通知へ依存しない。認証保管、scheduler、service managerは
Adapterの外側に置き、macOSではlaunchd、Linuxではsystemd等へ交換できるようにする。
