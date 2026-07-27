# SwitchBot テープライト3 正式操作Adapter

## 結論

HESTIAが正式に公開するテープライト3の機器操作は、電源、明るさ1〜100%、RGB、
色温度2700〜6500Kに限定する。OpenAPIの機器statusにactive modeがないため、RGBと
色温度は排他的な操作として扱い、同じ値がstatusに残っている場合だけでは表示modeの
切替完了を断定しない。

内蔵エフェクト、ミュージック、アプリ固有effectはHESTIAでは`unsupported`である。
アカウントのAutomation Sceneは別domainであり、この機器Adapterのscene能力ではない。
非公開command、推測したBLE byte列、第三者実装由来のlive commandは使用しない。

正本実装は`src/hedp/adapters/switchbot/strip_light/operation.py`である。

## 能力表

| 能力 | HESTIA状態 | 値 | 読み戻し | 根拠と境界 |
|---|---|---|---|---|
| 電源 | formal | `on` / `off` | OpenAPI `power` | 公式OpenAPI、既存の受付確認 |
| 明るさ | formal | 1〜100整数 | OpenAPI `brightness` | commandは0も記載されるが、statusと製品仕様は1〜100。0は正式UIへ出さず消灯を使う |
| 色 | formal | RGB各0〜255 | OpenAPI `color` | HSVへ推測変換せず、公式表現のRGBだけ |
| 色温度 | formal | 2700〜6500K | OpenAPI `colorTemperature` | active mode fieldはない |
| 内蔵effect | unsupported | なし | exact effectを取得不能 | 純正アプリだけで利用 |
| ミュージック | unsupported | なし | OpenAPIで取得不能 | 純正アプリ／本体controllerだけで利用 |
| Automation Scene | unsupported | 別domain | 機器effectを証明しない | Scenes APIと機器commandを分離 |

## 実行契約

読み取りと操作を別の公開境界にする。

- `StripLight3OpenApiReader`はstatus GETを一回だけ行い、機器commandを送らない。
- `StripLight3OperationAdapter`は共通`ExecutionCoordinator`を継承し、既存の
  `FastLightControlSession`から同じGate経路で使用できる。
- 入力は匿名aliasの`Intent`、短期`Authorization`、fresh/goodな
  `StripLight3State` cacheである。秘密値と家庭固有機器IDはtransport内部から出さない。
- Gateは対象、能力、owner、値、期限、承認、状態品質、鮮度、手動介入、重複operation IDを
  送信前に検査する。消灯中の明るさ・色・色温度操作は、暗黙の点灯へ置換せず止める。
- live送信は一Intentにつき一回だけで、timeoutや通信断を再送しない。
- メーカー受付後は`pending_verification`で返す。物理確認は`verify`の一回のstatus GETとして
  分離し、一致なら`completed`、fresh/good不一致なら`failed`、確認不能なら`unknown`とする。
- `unknown`または受付後の確認失敗ではAdapterを安全停止し、fresh/goodな外部再同期と
  評価時刻を`resume_after_resynchronization`へ渡すまで次の送信を許可しない。
- dry-runは共通Executionの`SHADOW` modeで、GETもPOSTも行わない。

## 低遅延path

資格情報、対象binding、capability、alias、Reader、Writer、共通GateはUI起動時に準備する。
有効なIntentを受けた後は、freshなcacheをEvidenceにしてGateから一回のPOSTへ進み、
追加の事前GETを挟まない。`last_fast_execute_ms`はGate開始から受付結果までだけを計測し、
read-back時間を含めない。

スライダーは既存`FastLightControlSession`を使用する。50〜100ms程度のdebounce期間に届いた
古い未送信値を捨て、最新値だけを正式Adapterへ渡す。同じ値の短時間重複はAdapterでも抑止する。
スライダーcallbackはまず`pending_verification`を受け、状態表示の確定は別のReader更新または
明示的`verify`で行う。送信待ちにread-backを直列化しない。

## 未確認事項の分類

### 正式実装に必須

現時点で不足なし。次は公式OpenAPIと確認済みローカル知見で確定している。

- device typeの正確な値`Strip Light 3`
- statusの電源、明るさ、RGB、色温度
- `turnOn`、`turnOff`、`setBrightness`、`setColor`、
  `setColorTemperature`のcommand名と範囲
- 一回送信、timeout上限5秒、再試行禁止、受付と物理確認の分離

### 実機適格性試験で確認

- formal Adapter経由の電源、明るさ、RGB、色温度について、受付後のfresh read-backと
  実際の見た目が一致すること
- RGBまたは色温度の現在値と指定値が同じ場合、active modeをstatusだけで確認できない境界
- クラウドstatus反映遅延の実測分布と、UIが`pending`を表示する時間上限
- 通信断後に純正アプリまたは物理確認とReader再同期で安全停止を解除できること

実機適格性が終わるまで、上記は追加送信で推測せず、既存の確認記録だけを使用する。

### 将来拡張

- durableなoperation ID registryと再起動をまたぐidempotency
- active RGB/CCT modeを公式に取得できる将来仕様
- webhookを使う非同期verification
- ローカル経路。ただし公式仕様、結果確認、OS非依存性を満たす場合だけ

内蔵effect、ミュージック、RGBと白色LEDの同時混色は将来拡張候補にも自動採用しない。
利用者の要件変更と公式仕様の両方がある場合に再評価する。

## オフライン試験

匿名fixtureは
`tests/fixtures/switchbot/strip_light_3_adapter_anonymous.json`に置き、機器ID、token、
endpoint、家庭の実値を含めない。回帰試験は次を固定する。

- 公式status parserと能力表
- 電源、明るさ、RGB、色温度の一回送信と一回read-back
- 1/100、RGB各channel、2700/6500の境界
- 明るさ0、消灯中、stale、型不一致の送信前停止
- timeout、通信断、read-back不能の再送禁止と`unknown`安全停止
- operation IDと短時間同値の重複抑止
- dry-run無通信
- スライダーのlatest-value coalescing
- Gate＋送信latencyからread-backが除外されること
- safe summaryと例外に秘密値・家庭固有IDが出ないこと

## 次の実機適格性確認

追加試験は現在禁止されている。次回の明示承認後も、一回につき一能力だけを対象にする。
事前cacheがfresh/good、対象一致、点灯中であることを確認し、現在と異なる小さな絶対値を
一回送る。受付後の`verify`は一回だけ行う。結果不明、不一致、stale、通信断では再送せず、
安全停止を維持して利用者の目視と純正アプリで状態を確定する。

## 公式一次情報

- https://github.com/OpenWonderLabs/SwitchBotAPI/blob/main/devices/lighting/strip-light-3.md
- https://github.com/OpenWonderLabs/SwitchBotAPI/blob/main/README.md
- https://www.switch-bot.com/products/switchbot-led-strip-light-3
- https://www.switchbot.jp/products/switchbot-strip-light3
