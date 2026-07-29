# 家庭固有設定

## 分け方

認証情報と単純な実行値はGit管理外の`.env`に置く。SwitchBotの機器ID、部屋、用途、
有効期間のような繰り返し構造は、Git管理外の`config/local/`にJSONで置き、その絶対パスを
`SUMICORE_SWITCHBOT_HOUSEHOLD_CONFIG_PATH`で渡す。両方とも権限0600にする。
移行期間中は従来の`HEDP_SWITCHBOT_HOUSEHOLD_CONFIG_PATH`も使用できる。

共有できる構造だけを`config/examples/`へ架空IDで置く。実機ID、部屋の履歴、認証情報を
見本、テスト、文書、ログ、Gitへ入れない。

## FusionSolar

次の値にはソースコードの既定値を設けず、実行環境で必須にする。

- `SUMICORE_FUSIONSOLAR_STATION_DN`
- `SUMICORE_FUSIONSOLAR_DEVICE_DNS`
- `SUMICORE_FUSIONSOLAR_BATTERY_DN`
- `SUMICORE_FUSIONSOLAR_BATTERY_SIGIDS`

`SUMICORE_`を優先し、未設定の場合だけ従来の`HEDP_`を使用する。移行中に両方へ
異なる値を設定しない。値を変更した場合は、切替前の項目名検査で競合がないことを確認する。

FusionSolar / SmartLoggerの定時収集と03:10の収集はlaunchd plistに必要値を保持するため、設定変更後は
`install_macos_device_realtime_launchd.sh`と`install_macos_equipment_launchd.sh`を
再実行する。再実行前に、対象ラベル、現在の収集状況、DBロックを確認する。

FusionSolar / SmartLoggerの取得周期はGit管理外の`.env`に
`SUMICORE_FUSIONSOLAR_COLLECTION_INTERVAL_SECONDS`として秒単位で置く。設定可能範囲は
300〜3600秒で、既定値は300秒である。下限を5分に固定することで、定時収集は最大でも
1日288回に制限される。収集処理は、応答受領前かつ保存開始前と確定できる通信失敗だけを
上限付きで再試行し、1回の定時起動で複数sampleを保存しない。

この値はprivateなlaunchd plistへ埋め込まれるため、変更を反映するには
`install_macos_device_realtime_launchd.sh`の再実行が必要である。installerを再実行する
前に、対象、影響、確認方法、復旧方法を確認する。

## SwitchBot

`config/examples/switchbot_household.example.json`を構造の見本にする。実値入りファイルは
`config/local/switchbot_household.json`などの名前で作る。主な項目は次のとおり。

- `filename_device_ids`: 履歴exportのファイル名接頭辞と機器IDの対応
- `location_history`: 機器ID、設置場所、用途、有効開始・終了
- `name_history`: 機器ID、過去名称、有効開始・終了

SwitchBot定期処理は毎回`.env`を読み込むため、JSONを作成して`.env`へパスを追加すれば
installerの再実行は不要である。設定ファイルが未指定でも現在値収集は継続するが、家庭固有
履歴の追加と履歴export取込の名前解決は行わない。

## 切替前チェック

この設計を稼働中リポジトリへ反映する前に、現在コードにある対応表からローカルJSONを
値を表示せず生成し、`.env`とJSONを0600にする。FusionSolarの必須値を新plistへ渡して
installerを再実行し、1回の手動収集と次回自動収集を確認してから、IDを除いたコードへ
切り替える。DBとRawDataは移動・複製しない。
