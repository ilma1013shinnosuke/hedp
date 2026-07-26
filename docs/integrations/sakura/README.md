# 日産サクラ連携

- knowledge_status: `offline-contract-confirmed`
- reviewed_at: 2026-07-27
- official_service: NissanConnect / MyNISSAN
- implementation_status: read model・dry-run operation契約のみ

## 確認済み

公式サービスでは、battery残量、航続距離、充電完了時間、充電開始、乗る前エアコン、
温度設定、施錠状態、遠隔施錠等が提供される。遠隔解錠は提供されない。

日本向けサクラで安定利用できる公式開発者APIは確認できていない。旧Leaf/Carwingsや
欧州向け第三者実装を流用しない。非公開API解析は規約上の懸念があり初期対象外とする。

## 現在の判断

ADBと公式アプリUIを使うoffline bridge試作はあるが、selector、ログイン維持、端末互換、
規約、車両wake、12V battery負荷が未確認である。そのまま正式Adapterへ移植しない。

公式API、公式App Intent、許容されたUI automationのいずれかが確定するまで、通信・認証・
UI automation・実操作codeは作らない。OS非依存の型付きread modelと、短命なcapability
snapshotだけを使うdry-run operation契約は正式配置する。

## 将来のreader

battery、range、充電完了見込み、charging、plug、door lock、cabin temperature、climate、
設定温度、alerts、メーカー最終更新時刻を個別品質付きで扱う。staleを0%や未施錠へ
変換しない。VIN、位置、経路、account、session、Raw responseはmodelへ保持しない。取得頻度は車両wakeと
12V batteryへの影響を実測して決める。
charging、plug、door lock、climateは対応するEnum値だけを正常値として受け付ける。
battery、range、温度はNaN・Infinityを拒否し、alertは自由文ではなく安全なopaque code
だけを許可する。

## 操作

充電、空調、設定温度、施錠を別能力にし、request側で充電開始、空調開始・停止、設定値を
型付けする。現在は型付きrequestとdry-run
plannerだけであり、`would_dispatch`でも送信しない。温度はsnapshotで観測した範囲だけを
許可する。施錠は高リスクで、将来も単発送信とread-backを必須とする。
能力名は`charge`、`climate`、`temperature`、`lock`、操作名は
`start_charging`、`start_climate`、`stop_climate`、
`set_cabin_temperature`、`lock`として別Enumにする。開始と停止をEnum aliasへ畳み込まず、
operation名の文字列判定も操作Enumだけを正本とする。

解錠は明示的な非対応であり、operation enum、request型、planner経路のいずれにも作らない。
文字列`unlock`を変換して迂回する機能も持たない。SumiCore停止時は車両と純正サービスの
標準動作を維持する。

## 再確認条件

MyNISSAN版、NissanConnect世代、公式API/App Intent提供、利用規約、端末要件、session、
車両firmware、wake制限が変わったとき。
