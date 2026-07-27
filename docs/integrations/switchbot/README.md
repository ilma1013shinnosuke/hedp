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
- collectorと`SwitchBotClient`には書き込みrouteを追加せず、profile追加だけで操作可能に
  ならない境界を維持した。

## 2026-07-27に反映したロボット状態・操作契約

- cleaner statusを型付き`RobotState`へ接続し、既存の生`working_status`を保ったまま、
  canonicalな`robot_working_status`、`charging_status`、`task_status`、
  `water_base_battery_percent`、`status_quality`を保存する。
- 未知のstatus値は正常値へ推測せず、成功Raw保持理由`unknown_status_values`として残す。
- 公式device type `Mini Robot Vacuum K10+`をK10+ command familyとして認識する。
- S10 `startClean`の`times`は証拠のある`1`だけを許可し、他の回数は新しいfixtureまたは
  公式根拠が得られるまで拒否する。
- 操作contractはcollectorとHTTP clientから分離する。read-backは送信試行以後かつ
  検証時刻以前で、qualityが`good`の状態だけを成功根拠にする。

## 2026-07-27 第二段階: 人感・在室・照明

到着・ローカル登録対象は、人感センサー、人感センサーPro、E26スマート電球、
テープライト3の4 familyである。vendorの正確な`deviceType`文字列は実際の一覧で確認するまで
推測しない。今回の正規化入口は、Git管理外の家庭設定に置く安全な`target_alias`、
明示family、登録状態であり、`deviceType`の部分一致ではない。

登録状態は`pending_registration`、`registered_unverified`、`observable`を区別する。
手動登録中のE26が一覧にまだ現れなくても、観測欠損や取得失敗にはしない。
`pending_registration`のまま保持し、値を補完せず、状態APIも呼ばない。

型付きObservationは次だけを扱う。環境センサーのCO2、温度、湿度の既存正本には変更を加えない。

- 人感: 検知、明暗
- 人感センサーPro: 検知、在室、検知継続、明暗
- E26／テープライト3: 電源、0〜100の明るさ、RGB色
- OpenAPI snapshotと将来のBLE partial eventのsourceを分離
- field単位の`good`、`missing`、`stale`、`invalid`、`unknown`
- BLE partial eventに含まれないfieldは`missing`へ変換せず、eventから省略
- 未知field／未知enum／不正型は正常値へ推測せずRaw保持理由にする

保存は`secondary_state_json`を再構築可能な型付き正本とし、匿名alias、family、source、全体qualityを
検索列へ持つ。OpenAPI snapshotの取得時刻は引き続き
`source_precision=collection_time_snapshot`であり、機器event発生時刻とは断定しない。

照明操作は、型付きdesired state、観測済みcapability、共通ExecutionGate用descriptor、
dry-run、匿名fixture transport、送信後のfresh/good read-backだけを実装する。
vendor endpoint、HTTP POST payload、本番Portは実装しない。fixtureでないTransportは構築時に
拒否し、将来の実操作は永続registryを備えた共通Executionだけを入口にする。

### E26の最終read-only確認

通常のService／inspect CLIはこの確認には使わない。専用probeは次を強制する。

- 一覧GETは未登録でも必ず1回だけ、状態GETは最大1回、retryなし、応答は最大1 MiB
- timeoutは1 request最大10秒、probe全体のwall-clock deadlineは最大20秒（既定12秒）
- 既知の登録IDとの差集合だけをin-memoryで作り、正確な`deviceType`別の匿名件数を返す
- E26 aliasへの候補紐付けは、差分が一意で呼び出し側が明示許可した場合だけ。永続化はしない
- 一覧件数とstatus field数にも上限を持つ
- DB、Raw、fileへ永続化しない
- safe summaryは匿名alias、観測した正確な`deviceType`、状態field名、品質、取得時刻、
  `persisted: false`だけ
- device ID、name、hub、状態値、認証値、Raw本文を表示しない
- 対象が未表示なら`pending_registration`とし、missing／failedにしない

probeのlive実行はコードレビュー後の明示された単発確認に限る。登録変更、削除、reset、
firmware更新、校正、Webhook登録、照明操作は行わない。

## 残る改善点

- テープライト3のシーン／ミュージック境界、公開APIで未対応の能力、
  任意BLE backendの採用条件は
  [専用文書](../switchbot-strip-light-3-scenes-music.md)を正本とする。

- `observed_at`不明時に収集時刻を機器発生時刻と断定しない。

OpenAPI status応答には、全機種共通で信頼できる機器発生時刻が確認できていない。そのため
API snapshotの既存`observed_at_utc`/`observed_at_local`列には取得時刻を格納するが、
`source_precision=collection_time_snapshot`を必須とし、機器event時刻とは解釈しない。
CSV等に明示時刻があるimportは従来どおりその時刻と精度を使う。将来、機器由来event時刻が
確認できた場合も、取得時刻を上書きせず`received_at`との分離をschema migrationとして
別途設計する。既存行の書換えは行わない。
- OpenAPI、BLE、手動importの由来と精度を分離する。
- 実測に基づいて機種ごとの取得周期を調整する。
- 新しいdeviceType／fieldは専用probeと匿名fixtureで確認してからprofileへ昇格する。
- 書き込みrouteは共通Executionとの接続、安全確認、匿名fixtureが揃うまで既存collectorや
  `SwitchBotClient`へ追加しない。

## 保存

現在値、状態変化、電池低下、通信異常、操作監査を残す。人感・在室eventは秒精度を保持する。
定常的な温湿度等は部屋別方針で間引く。正常Rawの無制限保存は行わず、schema変更、解析失敗、
異常、read-back不一致を優先する。

## 再確認条件

新機種追加、OpenAPI/BLE版変更、firmware更新、未知device type/field、取得周期変化、
Hub構成変更、認証方式変更、照明read-back不一致を検出したとき。
