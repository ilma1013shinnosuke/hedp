# 日産サクラ連携

- knowledge_status: `research`
- reviewed_at: 2026-07-25
- official_service: NissanConnect / MyNISSAN
- implementation_status: 正式Adapter保留

## 確認済み

公式サービスでは、battery残量、航続距離、充電完了時間、充電開始、乗る前エアコン、
温度設定、施錠状態、遠隔施錠等が提供される。遠隔解錠は提供されない。

日本向けサクラで安定利用できる公式開発者APIは確認できていない。旧Leaf/Carwingsや
欧州向け第三者実装を流用しない。非公開API解析は規約上の懸念があり初期対象外とする。

## 現在の判断

ADBと公式アプリUIを使うoffline bridge試作はあるが、selector、ログイン維持、端末互換、
規約、車両wake、12V battery負荷が未確認である。そのまま正式Adapterへ移植しない。

公式API、公式App Intent、許容されたUI automationのいずれかが確定するまで、正式codeは
作らず知識と匿名UI fixture候補だけを残す。

## 将来のreader

battery、range、charging、plug、door lock、cabin temperature、climate、alerts、
メーカー最終更新時刻を扱う。staleを0%や未施錠へ変換しない。取得頻度は車両wakeと
12V batteryへの影響を実測して決める。

## 操作

充電、空調、温度、施錠を別能力にする。施錠は高リスクで単発送信とread-backを必須とする。
解錠能力は作らない。SumiCore停止時は車両と純正サービスの標準動作を維持する。

## 再確認条件

MyNISSAN版、NissanConnect世代、公式API/App Intent提供、利用規約、端末要件、session、
車両firmware、wake制限が変わったとき。
