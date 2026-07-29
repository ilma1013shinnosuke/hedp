# HESTIA v1.0 release candidate 最終承認要約

更新日: 2026-07-30

## 保証対象

- macOS上のFusionSolar / SmartLogger既知Modbusレジスタread-only収集
- 単発、短時間、欠損許容24時間試験に合格
- 全Executorは既定`shadow`。設備、照明、給湯、鍵、家電、車両への実送信は対象外
- その他のReader、Linux/Windows、KURA接続は次版以降へ延期

## 安全・rollback

- 欠損、古い値、未知値を正常値や0へ補完しない
- 通信断、DB利用不能、Schema変更、停止・再起動を確認済み
- 新旧launchd jobの競合を解消し、新jobだけで現在値の再観測を確認済み
- 切替失敗時はlegacy jobへ復元する隔離試験に合格
- 緊急時は新規自動処理を止め、確認済みread-only構成へ戻す

## 利用者が受容した既知制限

- 外部backupはv1.0必須条件から延期した
- Macの故障、盗難、火災等で現役DBと同一障害領域backupを同時喪失し得る
- 30日容量評価は延期し、匿名容量probeで継続監視する

## 最終品質結果

- Mac・sanctum別鍵による同一SOPS暗号化正本の復旧: 合格
- 全自動テスト: 1078件合格、1件skip
- Ruff、compile、差分形式、Philip秘密検査: 合格
- Philip秘密検査: Critical 0、Warning 0

## 利用者承認

2026-07-30、利用者が本要約の保証範囲、延期項目、既知制限、rollback、
最終品質結果を確認し、HESTIA v1.0 release candidateを最終承認した。

外部backupと30日容量評価は利用者がリスク受容して延期済み。旧`.env`、現役job、
現役DB、実機は変更していない。承認後もcommit、push、公開release、deploymentは
別の明示指示まで実施しない。

## sanctum配備追補

`v1.0.0-rc.1`の成果物配置、SOPS復旧、host preflight、rollbackは合格した。
sanctumからSmartLoggerへのtransportは到達不能で、上限1回・データ0件・再試行なしで
安全停止した。macOSの承認済みread-only運用証拠には影響しないが、Linux/sanctumは
保証対象外・永続jobなしを維持する。

追加の匿名経路診断ではsanctumから対象TCP portまで到達したが、Modbus collectorは
応答待ちで安全停止した。SmartLoggerの許可接続元が既存Macに限定されている可能性が
主候補である。実機設定変更は行わず、sanctumのlive observationはblockedを維持する。
