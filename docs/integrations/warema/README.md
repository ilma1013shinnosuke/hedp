# WAREMA WMS連携

- knowledge_status: `research`
- reviewed_at: 2026-07-25
- primary_transport: WMS USB Stick / serial
- hardware_status: Stick到着後に実機確認

## 現在の知見

第三者公開実装から、USB serial 125000 baud / 8N1、ASCII frame、Stick metadata、network
parameter設定、機器scan、状態要求、位置・角度・STOPのprotocol候補を確認している。
既存remoteの学習操作からchannel、PAN、network keyを取得する実装も存在する。

所有remoteとStickの組合せ、Apple Silicon Macでの実serial、位置の開閉方向、角度の符号、
技適表示、風安全条件は未確認である。公開実装の値を実機確認済みとして扱わない。

## 初期Adapter

最初は実serialを開かないprotocol codecとMockだけを扱う。実物到着後、OS認識、port候補、
metadata、passive受信、credential取得、scan、state readの順に段階確認する。

network key、PAN、機器識別子は通常DB、ログ、fixtureへ入れない。reader完成前にexecutorを
正式経路へ置かない。

## 操作

STOP、position、tilt、open/closeを別能力にする。0/100方向と角度を校正するまで端点操作を
公開しない。単一対象、小差分、目視可能、retryなし、独立read-backから始める。
motor parameter、再登録、初期化、全体操作は初期対象外である。

## 保存

通常frame本文は保存せず、type、長さ、方向、受信時刻、品質を中心にする。unknown/decode
failureは秘密除去後に上限付きで保存する。位置・角度の変化、movement、weather、安全関連、
operation resultをevent化する。

## 再確認条件

Stick/remote/motorの機種・firmware、USB VID/PID、protocol type、weather field、network再登録、
機器追加、macOS/driver変更時。
