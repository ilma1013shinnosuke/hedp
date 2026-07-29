# HESTIA v1 sanctum受入・復旧準備

## 範囲

sanctumをアプリ実行・実機検証機として利用する前に、秘密値や現役データを移さず確認できる
要件をまとめる。今夜の準備ではsanctumを変更せず、配置物、実行条件、合格手順だけを固定する。

## 配置するGit管理物

- HESTIA repositoryの承認済みrelease candidate
- `scripts/check_sanctum_release_host.py`
- `scripts/check_release_readiness.py`
- `docs/secret-management.md`
- `docs/backup-capacity-recovery.md`
- `docs/release/hestia-v1-operations-runbook.md`

`.env`、age秘密鍵、restic password、cloud credential、現役DB、backup、log、launchd plistは
repositoryや通常のファイル転送へ含めない。

## 秘密なしpreflight

Python 3.9以上と、公式配布物のchecksumを確認した`age`、`age-keygen`、`sops`、`restic`を
PATHへ配置した後、次を実行する。

```text
.venv/bin/python scripts/check_sanctum_release_host.py
```

出力はplatform、Python version、tool version、失敗したcheck名だけである。秘密ファイル、
環境変数値、repository URL、鍵、credentialの存在や内容は検査しない。

## 秘密復旧の実行要件

1. runtime用age秘密鍵はsanctumだけが読めるGit管理外のmode 0600 fileへ置く。
   MacのKeychain項目や秘密鍵をコピーせず、HESTIA実行専用の別鍵を生成する。
2. offline recovery鍵はsanctumと同じ端末・同じdisk・同じbackupへ置かない。
3. SOPS暗号化正本はMac runtime recipientとsanctum runtime recipientで復号できる。
   将来offline recovery recipientを追加しても各runtime鍵と混在させない。
4. 復号平文をrepository、通常log、process引数、恒久一時fileへ出さない。
5. runtime鍵による復号とoffline鍵による隔離復号を別々に確認する。
6. 復号後の最小read-only接続だけを確認し、設定変更やExecutor送信を行わない。
7. 旧`.env`とplist内の既存秘密は、新方式の安定確認と個別承認まで削除しない。

## 外部backup復旧の実行要件

1. 承認済みbackend、地域、費用上限、Object Lock、最小権限credentialを用意する。
2. restic repository passwordはcommand引数へ置かず、専用commandから注入する。
3. 完成・検証済みの`.db.gz`だけをsnapshot対象にし、現役DBとpartialを送らない。
4. 初回snapshot後もlocal backupを削除しない。
5. sanctum上の隔離directoryへrestoreし、`gzip -t`、展開checksum、SQLite
   `quick_check`、HESTIA read-only確認を行う。
6. receiptには合否、snapshotの匿名参照、検証日時だけを残す。
7. upload権限とremote削除・prune権限を分離する。

## 合格と停止

preflight、二つのage鍵による復旧、最小read-only接続、外部snapshot、隔離restoreがすべて
成功した場合だけ`R8-03`と`R3-07`を完了候補にする。一つでも失敗、不明、秘密露出、
既存jobとの競合があれば停止し、旧経路を維持する。sanctumへの実配置、鍵生成、credential作成、
upload、現役job切替は、それぞれ別の明示承認後に行う。

## 2026-07-30 sanctum専用鍵の予備receipt

Mac鍵をコピーせず、`hestia-sanctum-runtime-v1`専用鍵をsanctumへ作成した。
秘密鍵はGit、共有folder、log、CLI引数へ出さず、公開recipientだけを共有台帳へ登録した。
mode 0600と非秘密SOPS probeは合格した。匿名receiptは
`config/release/receipts/hestia-sanctum-runtime-key.json`を正本とする。

その後、既存`.env`を変更せず両recipient向け`secrets/runtime.sops.env`を作成した。
Macとsanctumは同一SHA-256の正本を平文非出力で復旧し、sanctum側はtransport hash、
mode 0600、`/dev/null`復号に合格した。匿名receiptは
`config/release/receipts/hestia-sanctum-sops-recovery.json`を正本とする。
旧`.env`、現役job、既存秘密値は変更していない。

## v1.0.0-rc.1 配備結果

承認tag `v1.0.0-rc.1`をsanctumへハッシュ照合して配置し、専用runtime、
SOPS復旧、host preflight、rollbackは合格した。Linuxはv1.0の保証対象外であるため、
永続service、timer、cronは登録していない。

上限1回のFusionSolar / SmartLogger read-only試験は、Executorを呼ばず、
transport到達不能で安全停止した。観測追加は0件、再試行なし。機器設定、家庭LAN、
認証、旧秘密は変更していない。sanctum上のlive observationは未適格のままとする。

匿名receipt:
`config/release/receipts/hestia-sanctum-v1.0.0-rc.1-deployment.json`

## SmartLogger経路診断

匿名read-only診断では、対象設定、default route、Wi-Fi interface、同一subnet、
route選択、neighbor解決、ICMP、TCP handshakeがすべて成立した。host firewallの
ruleset全体は非対話権限では確認できなかったが、対象TCP接続の送信拒否は実効上ない。

続く上限1回のcollectorはModbus応答待ちで`transport_unavailable`となり、隔離DB追加0件、
Executor・writeなし、平文保存なし、永続jobなしで安全停止した。追加試行は行っていない。

既存Mac成功証拠とSmartLoggerの接続元制限から、sanctumがModbus許可接続元に含まれない
可能性を主候補とする。必要変更候補は既存Mac許可を維持したままsanctumの安定した接続元を
追加すること。影響はsanctumからのread-only Modbus許可、rollbackは追加許可だけの除去。
複数接続元対応と正規UI手順が未確認で実機設定変更に当たるため、変更せずblockedとする。

匿名receipt:
`config/release/receipts/hestia-sanctum-smartlogger-path-diagnosis.json`、
`config/release/receipts/hestia-sanctum-v1.0.0-rc.1-read-only.json`
