# 005 OS非依存Coreと交換可能なOS境界

- status: accepted
- decided_at: 2026-07-26

## 決定

SumiCoreは、合理的な範囲で収集・蓄積・判断・実行の本体、Reader、Collector、データ契約を
OS非依存に保つ。macOS、Linux、Windowsのいずれも将来の運用候補とし、Linuxを最終環境と
決め打ちしない。

OS固有機能が必要な場合は、無理な共通化で本体を複雑にせず、次の薄い交換部品へ隔離する。

- 常駐起動: launchd、systemd、Windows Service
- 秘密取得: 共通のsecret provider interfaceに対するOS別実装
- BLE、USB、OS通知、電源・sleep検知
- OS固有のpath、permission、service installer

SQLite schema、環境設定の論理名、品質区分、監査契約、HTTP/MQTT等の接続口は共通化する。
OS別部品は同一interfaceと共通contract testを満たす。OS依存コードをReader、Collector、
操作Adapter、第2層、第3層、第4層の共通Executionへ直接混在させない。

## 理由

現在はmacOSで開発し、将来Linuxへ移す可能性がある。一方、Windows専用の資産管理機能を
同じmini PCで動かすため、さらにWindowsへ移行する可能性もある。運用OSの変更で機器知識、
判断ロジック、DB形式を作り直さないため、この境界を恒久的な設計原則とする。

## 例外

OS非依存化が安全性、信頼性、保守性を明確に悪化させる場合はOS別実装を認める。ただし、
理由、影響、代替経路を文書化し、共通Coreから交換可能な境界を維持する。
