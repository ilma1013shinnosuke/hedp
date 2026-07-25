# FUJIOH MTRL-RK-901SI連携

- knowledge_status: `research`
- reviewed_at: 2026-07-25
- primary_transport_candidate: 38 kHz赤外線
- remote: RMC-08

## 現在の知見

公式資料から、運転停止、自動、弱、中、強、timer、照明のremote操作と、NEC形式38 kHzの
富士工業code体系を確認した。RMC-08のボタン別address/command、repeat、toggle/absoluteは
未確認である。

第三者にはSwitchBot Hubへ学習させた利用例があるが、家庭の機器での成功証拠ではない。
code総当たりは隠し命令や誤動作の危険があるため行わない。

## 初期Adapter

所有remoteを受信器で複数回測定し、同一性、timing、repeat、toggleを確認してから匿名fixture
を作る。それまではreader/executorを正式実装しない。SwitchBotを送信器に使う場合も、
SwitchBot Adapterの認証・通信とMTRLのIR能力を混ぜない。

赤外線は一方向であるため、送信完了を状態変化として保存しない。運転、風量、照明、
timerの実状態を確認できる外部観測がなければ`unknown`を維持する。

## 操作

風量の絶対指定候補と、停止・timer・照明のtoggle候補を分ける。toggleまたは結果不明操作を
自動再送しない。初回は単一button、目視可能、自動retryなしとする。

## 再確認条件

remote型番、受信code、Hub firmware、送信器、機器交換、buttonのtoggle/absolute判定、
外部状態観測経路が変わったとき。
