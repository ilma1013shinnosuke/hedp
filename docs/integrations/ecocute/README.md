# Panasonic HE-WU46KQ エコキュート連携

- knowledge_status: `observation`
- reviewed_at: 2026-07-25
- primary_transport: ECHONET Lite
- cloud_app: 「スマホでおふろ」は補助調査

## 方針

非公開クラウドAPIより、公開標準ECHONET Liteの電気温水器classを優先する。実機から
property mapをread-onlyで取得し、実装項目を確定する。規格上存在するpropertyを、
当該機が実装していると推測しない。

実測では複数のGet/Set propertyが確認され、限定的な沸き増し開始・停止試験の記録がある。
正式統合はreaderを先に作り、Set能力は公開しない。

## 読み取り候補

動作状態、沸き上げ設定・状態、昼間沸き増し許可、給湯中は実装可能性が高い。残湯量、
タンク湯温・容量、給湯可能湯量、警報、設定温度、風呂状態は、当該機のproperty mapと
値の実測を根拠に能力化する。

## 操作

沸き増し、風呂自動、追いだき、予約、休止などを一括して「給湯操作」にしない。
各能力を分け、現在状態、機器予約、手動操作、受付、実状態を別に扱う。給湯・加熱に
関わるため、結果不明時の盲目的再送を禁止する。

## 保存

通常pollは正規化現在値と状態変化を中心にする。property map変更、decode失敗、未知EPC、
異常値、操作read-back不一致だけRaw価値を高くする。Android AVD、APK、認証済み画面は
正式Adapterに含めない。

## 再確認条件

本体・無線Adapterのfirmware、ECHONET property map、AIF仕様、アプリ版、AiSEG2構成、
未知EPC、値の範囲・単位変更を検出したとき。
