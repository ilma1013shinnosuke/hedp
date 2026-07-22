# 家庭固有設定

## 分け方

認証情報と単純な実行値はGit管理外の`.env`に置く。SwitchBotの機器ID、部屋、用途、
有効期間のような繰り返し構造は、Git管理外の`config/local/`にJSONで置き、その絶対パスを
`HEDP_SWITCHBOT_HOUSEHOLD_CONFIG_PATH`で渡す。両方とも権限0600にする。

共有できる構造だけを`config/examples/`へ架空IDで置く。実機ID、部屋の履歴、認証情報を
見本、テスト、文書、ログ、Gitへ入れない。

## FusionSolar

次の値にはソースコードの既定値を設けず、実行環境で必須にする。

- `HEDP_FUSIONSOLAR_STATION_DN`
- `HEDP_FUSIONSOLAR_DEVICE_DNS`
- `HEDP_FUSIONSOLAR_BATTERY_DN`
- `HEDP_FUSIONSOLAR_BATTERY_SIGIDS`

5分収集と03:10の収集はlaunchd plistに必要値を保持するため、設定変更後は
`install_macos_device_realtime_launchd.sh`と`install_macos_equipment_launchd.sh`を
再実行する。再実行前に、対象ラベル、現在の収集状況、DBロックを確認する。

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
