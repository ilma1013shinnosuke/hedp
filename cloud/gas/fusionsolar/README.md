# GAS版FusionSolar収集

## 現在の範囲

Macが停止していても前日の`energy-balance`と`station-kpi-list`の完全応答を取得し、
Google Driveの受け渡し用フォルダへRaw JSONとして置く。判断、正規化、機器操作、DB更新は
行わない。1取得は`source + 対象日 + payload hash`で識別し、完全一致を増やさず、異なる
応答も1日・sourceあたり最大3件に制限する。

Drive上のファイルは一時的な受け渡しキューであり、バックアップの正本ではない。ローカル
SQLiteへの監査付き取込と受領確認を実装するまでは、ファイルを自動削除しない。

## Script Properties

実値はコード、Git、シート、実行ログへ書かず、Apps ScriptのScript Propertiesへ保存する。

- `FUSIONSOLAR_BASE_URL`
- `FUSIONSOLAR_STATION_DN`
- `FUSIONSOLAR_COOKIE`
- `FUSIONSOLAR_CSRF_TOKEN`
- `SUMICORE_QUEUE_FOLDER_ID`

現在は、観測済みのCookieとCSRFを利用するセッション方式だけを実装している。旧GASの
RSA OAEP/SHA-384自動ログイン元コードが見つかっておらず、Apps Scriptで安全に再現できる
暗号乱数・鍵処理も未検証であるため、認証期限切れを推測で回避しない。401、403、redirect、
HTML応答は失敗として停止する。ユーザー名とパスワードをこのGASへまだ保存しない。

接続先はパスを含まないHTTPS originに限定し、1応答は10 MiBを上限とする。Script Lockで
手動実行とtriggerの重複を防ぐ。trigger更新時は新triggerの作成後に旧triggerを削除するため、
作成失敗だけで既存の日次実行を失わない。

## 導入前の確認

1. Apps Scriptプロジェクトと専用Driveフォルダを作成する。
2. OAuth権限が外部通信、Drive、triggerに限定されていることを確認する。
3. Script Propertiesを設定し、値をログへ出さない。
4. `collectFusionSolarPreviousDay`を手動で1回実行する。
5. 2つのJSONについてsource、対象日、hash、完全payloadを確認する。
6. 同日再実行で完全一致が`duplicate`になることを確認する。
7. 問題がなければ`installFusionSolarDailyTrigger`を1回実行する。

Apps Script triggerの04:30は厳密な分指定ではなく、その付近で実行される。実API、Drive、
triggerを変更する導入作業は、対象プロジェクトと影響を確認してから別途行う。
