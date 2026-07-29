# HESTIA v1 故障訓練

## 目的

停止、保存障害、通信断、想定外データ、再起動が発生しても、HESTIAが危険な
操作や古い操作の再生を行わず、機器標準機能と手動操作を妨げないことを確認する。

本書の自動訓練は匿名fixtureだけを使う。現役DB、家庭内ネットワーク、実機、
認証情報、launchdには接続しない。

## 自動訓練

正本は`tests/test_hestia_operational_failure_drills.py`とする。

| 訓練 | 合格条件 |
|---|---|
| HESTIA停止・再起動 | 停止時の未送信Intentを破棄し、新しいprocess相当のsessionで再生しない |
| DB・保存障害 | 即時処理は先に完了し、保存失敗は上限付き再試行後に明示的に終了する |
| 通信断 | 状態が欠損または古い場合、Adapterへ一度も送信しない |
| Schema変更・想定外値 | 値を推測・補正せず、ExecutionGateで閉じてAdapterへ送信しない |
| launchd切替失敗 | 新jobの起動失敗時に新jobを停止し、直前のlegacy jobを再登録・再開する |

実行方法:

```text
.venv/bin/python -m pytest -q tests/test_hestia_operational_failure_drills.py
.venv/bin/python -m pytest -q tests/test_operational_scripts.py \
  -k 'launchd_switcher'
```

launchd切替はfake commandと一時plistだけを使う隔離試験で、成功時に新jobを維持し、
新jobのbootstrap失敗時にlegacy jobをbootstrap、kickstartすることを確認する。
現役launchd job、家庭内network、実機、認証情報は操作しない。

## 実環境で未完了の訓練

自動訓練の成功だけでは、正式リリースの運用保証は完了しない。次を隔離した
試験環境で実施し、時刻、対象能力、結果、復旧、秘密を除いた証拠を台帳へ残す。

1. 常駐processを安全停止し、再起動後に現在状態を再観測してから再開する。
2. DBを利用不能にし、即時経路が停止または限定動作し、危険操作を出さない。
3. 対象Adapterの通信を遮断し、欠損・古い値・復旧を区別する。
4. 匿名の未知fieldと範囲外値を入力し、Raw保全と正規化失敗を明示する。
5. 復旧後も停止前の未完了Intentを再送しない。

## 判定

- 自動訓練のみ成功: `R8-04`は一部完了
- 実環境訓練も成功し、復旧手順を再現可能: `R8-04`を完了候補にできる
- 一件でも古いIntent再生、無制限再試行、欠損の推測補完がある: 不合格

隔離launchd rollbackの成功はrollback実装のオフライン証拠であり、
`rollback_verified`や`R8-07`の実環境確認を完了にはしない。

## 2026-07-30 read-only常駐job再起動

FusionSolar / SmartLogger read-only収集だけを対象に、既存jobを安全停止し、
同じ確認済みplistから再登録・再起動した。失敗時はlegacy jobを再登録するtrapを
有効にして実施し、新jobの登録、起動、launchd上の存在を確認した。

再起動前に同じrunnerを指す新旧jobが同時登録されていたため、共通DB lockによる
二重書込み防止を維持したままlegacy jobを停止した。再起動後は新jobだけが登録され、
10分以内の新しいModbus read-only観測が存在することを、payloadを読まずに確認した。
保存済みIntentの再投入やExecutor送信はなく、現役DB、機器設定、家庭LAN設定、
認証情報を変更していない。

この確認とfake launchctlによるbootstrap失敗時のlegacy復元試験を合わせ、
常駐jobの停止・再起動・rollback経路は確認済みとする。

同日、現役DBと家庭内networkを使わない隔離directoryで、Modbus接続先をIANAの
TEST-NET addressへ固定した通信断訓練と、DB pathをdirectoryへ向けたDB利用不能訓練を
実施した。通信断は書込み開始前の限定された終了コード、DB利用不能は非0終了となり、
どちらも現役DB、実機、launchdへ影響しなかった。Schema変更は匿名fixtureによる
未知metric、欠損、不正値の個別reason codeと送信停止試験を確認済みである。

以上により、v1.0対象のread-only能力について、停止、DB利用不能、通信断、
Schema変更、再起動の訓練を完了とする。将来Executorを本番対象へ加える場合は、
同じGateを操作能力ごとに再適格化する。
