# SumiCoreセキュリティレビュー

## 目的と範囲

秘密情報、家庭固有情報、生活履歴、実機操作を、開発・運用・backup・外部連携の全経路で
守る。現在のGit管理ファイル、Git履歴、非公開設定、DB、backup、launchd、log、
家庭LAN上のModbusを確認した。秘密値と家庭固有IDそのものは本書へ記録しない。

## 現在確認できた良い状態

- 現在の`.env`内にある認証値・主要な家庭固有値は、現行Git管理ファイルと一致しない。
- `.env`、private handover、DB、backup、現行plist、log、local設定の確認対象は、
  group・otherへ読取り権限を与えていない。
- `.env`はshellとして実行せず、modeを検査する安全なparserで子processへ渡す。
- 通常の収集logは家庭固有IDと例外本文を出さず、各5MiB・2世代を上限とする。
- Modbus clientはFunction Code 3/4だけを許可し、書込みfunctionを実装していない。
- SmartLogger側は許可したclient IPだけを受け入れる制限モードを使用する。
- Git管理外のprivate handoverに残っていた現行環境値は伏字化した。

## 最優先の未解決事項

### 別障害領域の暗号化backup

現行backupはgzipによる可逆圧縮であり、暗号化ではない。同じMacに一世代だけなので、
故障、盗難、ランサムウェア、誤削除を同時に受ける。

off-siteへ置く前に、端末とは別管理の復号鍵を使う認証付き暗号化を適用する。形式は
macOSとWindowsの両方で復号でき、改ざん検出、version固定、回復手順を持つものを選ぶ。
暗号化前後のchecksum、復号、SQLite整合性を定期試験する。稼働中SQLiteを同期folderへ
直接置かず、正常終了したbackupかarchiveだけを転送する。

### launchd plistの平文秘密

現行plistは0600だが、FusionSolarの認証情報を平文で保持する。Modbus-only切替後は
realtime plistからクラウド認証値を除去できる。日次クラウド処理に残る秘密は、
macOS Keychain等から実行時だけ取得する方式へ移す。installerの標準出力、process引数、
一時fileへ値を出さない。

### 過去Git履歴の家庭固有ID

現在の認証秘密はGit履歴に見つからなかった。一方、認証には使わない家庭固有IDが
2種類、過去commitに残っている。公開範囲を確認し、privacy上の削除が必要なら、
remote、branch、clone利用者への影響を整理して履歴を書き換える。値の変更や失効が
可能な場合は、履歴書換えより先に行う。これは別承認の破壊的作業とする。

## 高優先の未解決事項

### 既存log

新しいlogはredactionと上限を持つが、修正前のlogには家庭固有IDや詳細な例外本文が
含まれる可能性がある。24時間監視と障害調査が終わった後、必要な件数・時刻・error種別
だけを匿名監査記録へ残し、旧logの対象、容量、復元不要性を確認して削除する。

### LAN内通信

Modbus TCPとSmartLogger管理画面は家庭LAN内の平文通信である。WANからport開放しない。
IoT機器と一般clientのnetwork分離、router firewall、管理画面の強い固有password、
installer権限の限定を維持する。許可client IPを増やすたびに、端末、目的、期限を台帳へ
記録する。SumiCoreはModbus書込みを追加しない。

### DBとarchiveのprivacy

DB、Raw archive、操作履歴は在室・生活時間・設備状態を推測できる。mode 0600だけでなく、
Macのdisk encryption状態を確認する。長期archiveは保存クラスに応じて暗号化し、
復号後の一時fileを残さない。映像、解錠、在室は一般センサーより短い保存期間と厳しい
閲覧制御を別途定める。

### credential権限の分離

読み取りtokenと操作tokenを同じ権限で扱わない。可能ならread-only credentialを収集層、
操作credentialを第4層の限定processだけへ渡す。新規Adapterはtokenの最小権限、
失効方法、rotation、利用履歴を確認する。

## 実装上の規則

- secretと家庭固有IDをCLI引数へ渡さない。
- error logはtype、匿名target index、状態変化だけを記録する。
- Raw本文、HTTP header、Cookie、tokenを通常logへ出さない。
- fixtureは架空値で作り、単なる文字置換で実Rawを匿名化しない。
- operationはidempotency、期限、対象照合、ExecutionGate、結果確認を通す。
- 実行権限を持つcode pathを収集Adapterからimportしない。
- dependencyとOS更新はtest後に段階反映し、beta OSを本番収集機の前提にしない。
- security事故時は値の失効・再発行を先に行い、file削除だけで解決扱いにしない。

## 今後の確認項目

- Macのdisk encryptionが有効か
- GitHub repositoryとbranchの公開範囲
- off-site暗号化先、鍵の保管先、回復担当
- cloud credentialを使う日次機能の必要性
- routerのWAN port、IoT分離、管理者account
- screenshot、camera capture、download済みAPK等の家庭固有資料の保存期限
- SwitchBotその他vendor tokenの最小権限と失効手順
- 操作機能実装前のthreat modelと誤操作試験

## 完了条件

- Mac故障時に、別障害領域の暗号化backupから復元できる。
- 通常稼働processが不要な操作credentialを持たない。
- 現行Git、log、document、screenshotに秘密値が残らない。
- 家庭LAN外からSmartLoggerとローカル制御portへ到達できない。
- credential漏えい、端末紛失、誤操作、archive破損ごとの手順がある。
- security対応が利用者へ過剰な日常負担を生まない。
