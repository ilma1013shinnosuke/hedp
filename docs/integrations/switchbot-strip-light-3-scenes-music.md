# SwitchBot テープライト3：シーンとミュージック

## 結論

SwitchBotで「シーン」と呼ばれるものには、別の2種類がある。

1. アカウント全体の手動オートメーション（OpenAPIのScenes API）
2. テープライト本体の動的な発光エフェクト（アプリのScene画面）

前者を実行しても、後者のプリセットを直接選択したことにはならない。HESTIAでは
`automation_scene`と`device_effect`を別の能力・別の実行意図として扱う。

公開されているStrip Light 3用OpenAPIの機器コマンドは、電源、明るさ、RGB、色温度である。
内蔵エフェクトやミュージックを直接選ぶ機器コマンドは公開されていない。

## 現時点の根拠

### 公式

- Strip Light 3製品情報はRGB+CCT、2700〜6500K、1〜100%、シーン、
  音楽同期を機能として説明している。
- OpenAPIのStrip Light 3仕様は、状態として電源、明るさ、RGB、色温度を返し、
  操作として電源、明るさ、RGB、色温度だけを定義している。
- アカウントレベルのScenes APIは一覧取得と実行を提供する。
- 公開BLE状態仕様のモード値は、色、シーン、ミュージック、コントローラー、
  色温度を区別できる。ただし公開資料だけでは内蔵エフェクトの選択命令や、
  選択中の正確なプリセット名までは確認できない。

### 第三者実装（正式仕様ではない）

現行pySwitchbotは暗号化BLE経路でStrip Light 3を扱い、複数のエフェクト別名を
動的に列挙して設定する実装を持つ。これは有力な実装参考だが、HESTIAの公開API
transportへ非公開byte列を複製しない。採用する場合は、pySwitchbot等を任意のBLE
backendとして隔離し、対応effect一覧をbackendから取得する。

## HESTIAの境界

- OpenAPI機器transportへ、根拠のない`setEffect`や`music`命令を追加しない。
- アカウントの手動オートメーションと内蔵エフェクトを同じ`scene`型にしない。
- BLE広告から`device_effect`または`music`という一般モードは確認できても、
  正確なエフェクト名を観測したとはみなさない。
- HESTIAが選択を送った場合も、正確なエフェクトのread-backがない限り、
  「送信した意図」と「観測した一般モード」を別々に記録する。
- BLE backendは任意依存とし、macOS、Linux、Windowsの本体コードから分離する。
- live送信は共通ExecutionGate、機器別直列化、timeout、結果確認、安全停止を通す。
- 今回追加した`light_modes.py`はdry-run契約だけで、実機送信を行わない。
- 匿名fixture
  `tests/fixtures/switchbot/strip_light_3_modes_anonymous.json`は、一般モード値と
  Music能力の既知／未確認境界だけを固定し、家庭固有IDや実通信Rawを含めない。

## Musicの未確認事項

公式製品情報と説明書から、ミュージックは製品の内蔵マイクで周囲の音を拾い、アプリで
感度を調節でき、本体コントローラーの専用ボタンからも開始できることを確認した。
スマートフォンの音楽データをHESTIAがテープライトへ転送する機能ではない。

一方、マイクの物理位置、感度・配色・開始・終了のBLE符号化、これらの現在値read-back、
電源再投入後の保持は未確認である。公開OpenAPIにはミュージック操作も動作中状態もない。
このためHESTIAでは「製品能力は確認済み、アプリ／本体操作は利用可能、HESTIAの外部
実行能力は未適格」とする。

専用アプリを確認するときは、秘密値や家庭固有情報を写さず、次だけを記録する。

- Scene一覧の表示名、分類、選べる設定項目
- Music画面の音源、感度、パターン、開始・終了操作
- 画面遷移だけで点灯状態が変わるか
- 選択内容を状態画面から再確認できるか

## 参照

- https://www.switch-bot.com/products/switchbot-led-strip-light-3
- https://www.switchbot.jp/products/switchbot-strip-light3
- https://cdn.shopify.com/s/files/1/0522/2458/9999/files/Strip_3-SMS-JP-2502-Q_1_a8c50865-7306-4755-b6ee-90f1bb763331.pdf?v=1747655040
- https://github.com/OpenWonderLabs/SwitchBotAPI
- https://github.com/OpenWonderLabs/SwitchBotAPI-BLE
- https://github.com/sblibs/pySwitchbot
