# sanctum向けSmartLogger read-only許可変更案

更新日: 2026-07-30

## 現状

sanctumからSmartLoggerまでのroute、同一subnet、neighbor、ICMP、TCP handshakeは成立する。
一方、上限1回のModbus collectorは応答待ちで`transport_unavailable`となった。
既存Macからのread-only収集は成功しており、SmartLogger側の許可接続元がMacだけに
限定されている可能性を主候補とする。

## 公式仕様

Huawei公式SmartLogger資料では、Modbus TCPを`Enable(Limited)`にした場合、
Client 1からClient 5まで最大5台の第三者管理systemをpresetできる。設定経路は
機種・versionにより表記差があるが、SmartLogger WebUIの
`Settings > Comm. Param. > Modbus TCP`または同等のModbus TCP画面である。

原典:
<https://support.huawei.com/enterprise/en/doc/EDOC1100440661/2f455505/setting-smartlogger-parameters>

Modbus TCPには認証・暗号化がなく、運転dataだけでなく制御commandも伝送し得るため、
Huaweiもplant側のrisk低減を求めている。HESTIAではReader以外を起動せず、
全Executorを`shadow`のまま維持する。

## 変更候補

1. 現在のlink設定、既存Client slot、address mode、service portを値を公開せず記録する。
2. 空きClient slotがあり、既存Mac許可を変更せず追加できることを確認する。
3. sanctumの安定した接続元を空きClient slotへ一件だけ追加する。
4. 他のModbus TCP設定、address mode、SmartLogger address、port、電力制御設定は変更しない。
5. 保存後、上限1回・60秒・隔離DBのread-only collectorで確認する。
6. 成功しても永続jobは別承認まで登録しない。

## 在宅時5分runbook

### 0:00–1:00 変更前確認

1. SmartLogger正規WebUIへ現地の承認済み方法でログインする。
2. Modbus TCP画面で`Enable(Limited)`、既存Mac Client、空きClient slot、
   address mode、service portを画面上で確認する。
3. 空きslotなし、既存Mac不明、画面相違、sanctum接続元不安定なら保存せず終了する。

### 1:00–2:00 一項目だけ追加

1. 空きClient slotへsanctumの安定した接続元だけを追加する。
2. 既存Mac、link設定、address mode、SmartLogger address、port、電力制御を触らない。
3. 変更対象が一項目だけであることを再確認して保存する。

### 2:00–3:30 一回だけ確認

1. sanctumの秘密なし受入checkが合格していることを確認する。
2. 60秒上限、隔離DB、出力破棄、Executorなしでcollectorを1回だけ実行する。
3. 成功はread-only observation 1件以上、write 0、永続job 0で判定する。

### 3:30–5:00 終了またはrollback

- 成功: 追加slotを維持し、匿名receiptだけを保存する。永続jobは登録しない。
- 失敗・不明: 追加したsanctum用slotだけを削除する。再試行しない。
- rollback後: Mac収集継続、sanctum拒否、その他設定不変を確認する。

## 影響

- sanctumからSmartLoggerのModbus TCP interfaceへ接続可能になる。
- Modbus TCP自体に認証・暗号化がないため、sanctum侵害時の到達範囲が増える。
- HESTIA側はread-only限定だが、SmartLogger interface自体が制御commandを受け得る
  可能性は残る。

## 実行前Gate

- 対象機種・firmwareの正規WebUIでClient slotが複数存在する。
- 空きslotがあり、既存Mac許可を上書きしない。
- sanctumの接続元が固定または予約済みで、別端末へ再割当てされない。
- 変更前画面を秘密・IP非表示の匿名項目として記録できる。
- 現地の手動操作、安全機能、発電・蓄電池設定へ影響しない。

一つでも不明なら変更しない。

## Rollback

追加したsanctum用Client slotだけを削除し、既存Mac slotとその他設定を変更前のまま維持する。
削除後、sanctumからのTCP/Modbusが拒否され、Macの既存read-only収集が継続することを確認する。
factory reset、全Client削除、`Enable(Unlimited)`への変更はrollbackに使わない。

## 現在の判定

複数Client対応は公式仕様で確認できた。ただし対象実機の機種・firmware、空きslot、
sanctum接続元の安定性、WebUIの変更前状態は未確認である。実機設定変更は高riskのため、
利用者が在宅し、画面とrollback対象を確認できるまでblockedとする。
