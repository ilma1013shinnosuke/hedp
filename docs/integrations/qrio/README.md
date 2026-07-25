# Qrio Lock / Hub連携

- knowledge_status: `observation`
- reviewed_at: 2026-07-25
- primary_transport: Qrio cloud HTTPS
- risk: 住居の物理セキュリティ

## 確認済み

login/refresh、機器一覧、施錠状態、履歴、設定、電池、firmware、Hub登録状態を実環境で
確認している。施錠・解錠はoperation jobを発行し、terminal statusと状態再取得で確認する
方式が実測されている。Hub到達不能時のtimeoutも確認済みである。

これらは非公開API解析を含むため、正式運用前に利用規約と継続利用の可否を確認する。
model codeを市販型番へ推測変換しない。

## 初期Adapter

初期統合はreader-onlyとする。status、health、history、settingsを読み、event IDで重複を
抑止する。認証処理はtransportへ隔離し、tokenや家庭固有IDをRaw、通常ログ、fixtureへ
出さない。

正式なオフラインReader契約は`src/hedp/adapters/qrio/`へ置く。transport interfaceには
status、health、historyだけを公開し、lock/unlock/settings変更methodを持たせない。
正規化時に実Lock IDを実行時設定のaliasへ変換し、名称、Lock/Hub ID、履歴文言を捨てる。
履歴event IDはRaw値を保持せずSHA-256 dedupe keyへ変換する。

履歴の`logged_at`は秒以下の精度を保ち、定期statusは取得時刻をobserved/received時刻とする。
push/WebSocketは未確認なので、当面はstatusとhistoryの低負荷取得で変化を回復する。
AdapterはPython 3.11以上のOS非依存コードとし、Keychain、launchd、固定パスへ依存しない。
非公開cloud transportの正式実装と定期実行は、利用規約・継続利用性と実機read-only試験後に
外側へ追加する。

executorは別process/permissionでのみ構築する。施錠、解錠、設定変更は能力を分ける。
解錠は高リスクで、実行直前承認、fresh state、対象一致、単発送信、job確認、read-backを
必須とする。timeoutや結果不明では自動再送しない。

## 対象外

指紋や暗証番号を使う入口認証装置の自作、Qrioとの自作連携、SwitchBot純正製品との
採用比較は行わない。これらを将来タスクへ戻さない。既存のQrio reader知識や一般的な
高リスク操作契約は、この対象外判断とは分けて保持する。

## 保存

現在状態、電池、firmware、Hub、設定と、施解錠・auto-lock・operation terminal eventを
残す。住居の入退室履歴は高プライバシーであり、既定の10年保存対象にしない。正常status
Rawは短期、異常・job結果・read-back不一致を優先する。

## 再確認条件

Qrioアプリ/API版、token lifecycle、job status、機種/Hub交換、複数Lock、共有権限、
firmware、Hub offline挙動が変わったとき。BLE/LAN/pushは未解析で、別経路として扱う。
