# Smart LEDZ Base 2.0.4連携

- knowledge_status: `observation`
- reviewed_at: 2026-07-25
- observed_versions: Smart LEDZ Base 2.0.4、同型Gateway複数台
- primary_transport: LAN SSDP + local TCP

## 確認済み

Gateway discovery、TCP portへの接続、short frame、JSON request/response、request ID相関、
`ErrorCode=0`の受付判定を実機で確認している。Group、Scene、Schedule、Device、Sensorの
read-only要求と、限定的なScene、照明、Schedule操作の実績がある。

command直後は旧状態を返すことがあり、数秒後に反映するeventual consistencyがある。
受付成功と状態変化を分け、bounded read-backを行う。

## 初期Adapter

readerはGateway、Group、Scene、Schedule、Device、Sensor、現在の運転・予約を取得する。
transportはframingとJSON相関だけを担当する。executorはreader完成後に別経路で追加し、
Collectionからimportできないようにする。

現時点のオフラインreader部品は、すでにJSONへ復号・相関済みのGroup、Scene、Schedule、
Device、Sensor応答だけを受け取る。実機で確認済みの`ErrorCode=0`は受付済みとして表し、
未確認のネストschemaや値は解釈しない。未知fieldは値を複製せず最上位field名だけで検出し、
名称、ID、認証、ネットワーク、設定に関わるfield名はreader境界でredactする。

Scene/Scheduleの定義、active、現在選択、実行中状態は同じ意味にしない。完全なpush event、
fragmented frame実機値、MQTT、認証token lifecycle、Sensor luxは未確認である。

## 公開しない能力

backup、restore、OTA、Wi-Fi、cloud、Gateway初期化、機器kickout/import、認証変更を
通常Adapterへ入れない。Room/Scene/Scheduleの編集や全消灯は、read-only完成後も
能力単位の別承認とする。

## 保存

正常時は正規化現在値と変化を中心にし、Rawは初回schema、未知field、異常、操作検証へ
限定する。UDN、IP、MAC、serial、名称、auth、設定blobは通常Rawへ入れない。匿名fixtureには
short/fragmented frame、最小Group/Scene/Schedule/Device/Sensor responseだけを残す。

## 再確認条件

Baseアプリ、Gateway firmware、frame/schema、認証方式、Gateway交換、複数Gateway構成、
未知command/error、応答遅延の変化を検出したとき。旧・新fixtureを併存させる。
