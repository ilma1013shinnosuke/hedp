# バックアップ容量不足時の対処

## 基本方針

容量不足でバックアップに失敗しても、以前の正常な圧縮バックアップは削除しない。
新しいバックアップは隠し`.partial`ファイルへ作られるため、正常完了するまで正式な
バックアップとして扱わない。DB本体、正常な`.db.gz`、用途不明のファイルは推測で
削除しない。

現行の日次backupは同じMac内に置く短期復旧用であり、端末故障、盗難、誤削除、
ランサムウェアに対する別障害領域のbackupではない。外部保存が完成するまで、
この一世代を削除してはならない。

## 確認手順

1. 日次処理を再実行せず、まずディスクの空き容量を確認する。

   ```bash
   df -h /System/Volumes/Data
   ```

2. バックアップの名前、容量、更新日時を確認する。

   ```bash
   ls -lah /Users/shinnosuke/hedp/backups
   ```

3. 次のように分類する。

   - `hedp-YYYYMMDD-HHMMSS.db.gz`: 正常な圧縮バックアップ候補
   - `hedp-YYYYMMDD-HHMMSS.db`: 正常終了前なら未圧縮または不完全の可能性がある
   - `.hedp-YYYYMMDD-HHMMSS.db.*.partial*`: SumiCoreが生成した途中ファイル
   - `*-journal`、`*-wal`、`*-shm`: SQLiteの付随ファイル。単独で判断して削除しない

4. 一時ファイルを使用中の処理がないか確認する。

   ```bash
   lsof +D /Users/shinnosuke/hedp/backups
   ```

5. 1時間以上古いSumiCore生成の`.partial`は、次の日次処理で自動除去される。
   急いで手動削除する必要はない。手動で削除する場合は、対象、更新日時、使用中でない
   こと、正常な旧世代が残っていることを確認し、削除の承認を得る。

## 再実行の条件

DB本体と安全余裕を置ける空き容量を確保してから再実行する。現在の実装は、
概ね「DB本体の容量 + DB容量の20%または512MiBの大きい方」を必要量として
開始前に判定する。条件を満たさない場合は、途中コピーを始めずに停止する。

空き容量を増やすときは、まず再生成可能なキャッシュや明確な不要物を候補にする。
正常なバックアップの削除、DB履歴の削除、Rawデータの削除は別作業として影響を
確認してから行う。

## 成功確認

再実行後は次を確認する。

- 新しい正式名のバックアップが作られた
- 圧縮後の拡張子が`.db.gz`になった
- ファイル権限が`0600`である
- 以前の正常世代が、新世代の成功確認前に失われていない
- `hedp daily-health --verbose`でバックアップ異常が報告されない

新世代が正常と確認できた後だけ、設定された保存世代数に従って古い世代を整理する。

## 圧縮処理の未解決事項

SQLite backup本体は隠しpartialへ作成し、完了後にatomic renameする。これに対し現行の
`run_daily.sh`は正式名の`.db`を`gzip -f`で直接圧縮し、`gzip -t`による完了性確認と
圧縮済みpartialからのatomic renameを行っていない。

`src/hedp/storage/compressed_backup.py`には、元ファイルを残して同一filesystemの
mode 0600 partialへgzipし、展開後のSHA-256と容量を照合してから正式名へ原子的に
切り替える安全部品を実装済みである。ただし、現役の日次jobにはまだ接続していない。
接続時は、圧縮成功後だけ元`.db`を削除する処理、保存世代整理、失敗時の運用metricを
含めて次の変更として扱う。

同じmoduleには、完成済み`.db.gz`を隔離directoryのmode 0600 partialへ展開し、
既存出力を上書きせず、SQLite `quick_check`に成功した場合だけ秘密非表示の固定形式receiptを
返す復元検査も実装済みである。将来resticを導入する場合は、resticが隔離directoryへ戻した
`.db.gz`をこの検査へ渡し、repository URL、credential、path、DB内容をreceiptへ含めない。

`scripts/compress_verified_backup.py`は日次jobから呼ぶための準備済みcommandである。同名
`.gz`が既にある場合は元`.db`と展開後のchecksum・容量が一致するときだけ再開成功とし、
不一致なら両方を保持して停止する。`--remove-source`でも検証成功後にだけ元`.db`を削除する。
このcommandも現役`run_daily.sh`へは未接続である。

次の実装変更は日次本番処理へ影響するため、対象script、次回実行への影響、rollbackを
提示して承認を得てから行う。

1. 元`.db`を消さず、同じfilesystemの隠しpartialへgzipする。
2. `gzip -t`に成功したpartialだけをmode 0600で正式名へatomic renameする。
3. 中断又は検証失敗時はpartialだけを残すか安全に回収し、旧正常世代を削除しない。
4. 新しい圧縮済み世代の成功後だけ、保存世代数に従って旧世代を整理する。

## 別障害領域backupの候補方式

大容量のDBと検証済みRaw archiveは、暗号化、改ざん検出、snapshot、restore、repository
検査を持つresticを候補とする。`.env`相当、restic repository password、保存先の認証情報
などの小さな秘密はSOPSとageで別管理する。bulk dataをSOPSへ入れず、秘密値をresticの
command引数、log、receiptへ書かない。

外部転送は日次収集と共通DB lockを持つ処理へ追加しない。独立jobが、完成して検証済みの
`.db.gz`、JSONL archive、manifestだけを転送する。稼働中の`hedp.db`、`.env`、plist、
log、partialは対象外とする。転送失敗は収集失敗と混同せず、local backupを削除しない。

初期方式は安全性を優先して完成済み`.db.gz`を送る。gzip済み世代間で得られるdedup率は
実測前に約束しない。転送量が問題になった場合だけ、atomic `.db`完成後にlockを解放して
restic snapshotを作り、その後local gzipを行う方式と比較する。

## 導入と復旧の合格条件

保存先を承認した後も、最初の外部copyが成功しただけでは導入完了としない。

1. 外部snapshotの存在とrepository整合性を確認する。
2. 隔離directoryへrestoreする。
3. `gzip -t`、展開、SQLite `quick_check`、SumiCoreのread-only確認を順に行う。
4. 秘密を含まないreceiptへ、結果、snapshot識別子、検証時刻だけを記録する。
5. 最初の外部copyとrestoreが両方成功するまで、現行local backupを削除しない。
6. 定期的なrepository checkと、分割したdata検査、隔離restoreを運用する。

remote retentionやpruneはbackup書込みと権限を分け、可能ならappend-only又は
immutabilityを利用する。remote削除を自動化する前に、保持期間、費用、RPO、RTOを
改めて承認する。

## 導入前に決める項目

- backend、地域、費用上限、容量上限
- append-only又はobject lockの利用可否
- restic repository passwordとage復旧鍵の保管先
- runtime用recipientとoffline recovery用recipientの所有者
- 復旧責任者、保持期間、RPO、RTO
- repository初期化、tool導入、credential作成、upload、pruneの承認単位

これらが決まるまで、toolの導入、repository初期化、cloud credential作成、upload、
remote pruneは行わない。

## 公式資料

- restic repository: https://restic.readthedocs.io/en/stable/030_preparing_a_new_repo.html
- restic backup: https://restic.readthedocs.io/en/stable/040_backup.html
- restic repository check: https://restic.readthedocs.io/en/stable/045_working_with_repos.html
- restic restore: https://restic.readthedocs.io/en/stable/050_restore.html
- restic retention: https://restic.readthedocs.io/en/stable/060_forget.html
- restic encryption: https://restic.readthedocs.io/en/stable/070_encryption.html
- SOPS: https://github.com/getsops/sops
- age: https://github.com/FiloSottile/age
