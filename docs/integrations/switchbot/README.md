# SwitchBot連携

- knowledge_status: `observation`
- reviewed_at: 2026-07-25
- scope: OpenAPI、将来のBLE、環境センサー、人感・在室、照明
- condition: 機器追加と仕様更新を前提とする継続中の連携

## 現在の正本

既存の`src/hedp/adapters/switchbot/`、現役DB、過去取込が運用上の正本である。別解析で得た
照明、人感、在室、BLEの試作を丸ごと置換しない。

OpenAPI v1.1の署名、device list、status取得は既存実装済みである。別解析ではStrip Light 3の
状態取得と限定brightness操作が実機確認された。Color Bulb、人感センサー、Presence Sensor
Proの項目は主に公式資料と第三者実装が根拠で、実機確認は継続中である。

環境センサーの温度、湿度、CO2は既存SumiCore側を正本とし、照明・人感の引き継ぎで
上書きしない。

## 拡張方針

SwitchBotは今後もセンサー、電球、テープライトなどが増える。共通transport、認証、
rate limitと、機種別profileを分ける。同型機器の追加は家庭固有台帳へ登録し、codeを
複製しない。

機種profileには次を持たせる。

- vendor device type、確認したmodel/firmware/API版
- 読み取りfield、単位、範囲、欠損、鮮度
- event化する変化、poll上限、Raw上限
- 操作能力、read-back、retry class、安全条件
- 匿名fixtureと再確認条件

センサーprofileは読み取り専用とし、照明profileはreaderとexecutorを分離する。

## 2026-07-25に反映した改善

- `SwitchBotClient`のtimeout、read-only retry回数、待機時間を有限かつ設定可能にした。
- retryごとに認証署名を作り直す。
- 機種横断field抽出をmodel profileへ分け、未知fieldを検出可能にした。
- `working_status`の保存漏れを修正した。
- 既知profileの正常成功応答はRaw本文を重複保存せず、未知・異常時だけ証拠を残す。
- profileへ取得周期と成功Raw方針を追加した。
- 操作APIは追加せず、profile追加だけで操作可能にならない境界を維持した。

## 残る改善点

- `observed_at`不明時に収集時刻を機器発生時刻と断定しない。

OpenAPI status応答には、全機種共通で信頼できる機器発生時刻が確認できていない。そのため
API snapshotの既存`observed_at_utc`/`observed_at_local`列には取得時刻を格納するが、
`source_precision=collection_time_snapshot`を必須とし、機器event時刻とは解釈しない。
CSV等に明示時刻があるimportは従来どおりその時刻と精度を使う。将来、機器由来event時刻が
確認できた場合も、取得時刻を上書きせず`received_at`との分離をschema migrationとして
別途設計する。既存行の書換えは行わない。
- OpenAPI、BLE、手動importの由来と精度を分離する。
- 実測に基づいて機種ごとの取得周期を調整する。
- 照明、人感、在室fieldは実機schema確認後に正式な保存項目へ昇格する。
- 操作APIは共通Execution実装前に既存collectorへ追加しない。

## 保存

現在値、状態変化、電池低下、通信異常、操作監査を残す。人感・在室eventは秒精度を保持する。
定常的な温湿度等は部屋別方針で間引く。正常Rawの無制限保存は行わず、schema変更、解析失敗、
異常、read-back不一致を優先する。

## 再確認条件

新機種追加、OpenAPI/BLE版変更、firmware更新、未知device type/field、取得周期変化、
Hub構成変更、認証方式変更、照明read-back不一致を検出したとき。
