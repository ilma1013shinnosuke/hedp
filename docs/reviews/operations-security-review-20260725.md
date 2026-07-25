# 運用・エラー処理・セキュリティ監査（2026-07-25）

## 範囲と方法

- 対象: Git管理中のコード・設定生成script・運用/統合文書。実機、API、DB、backup、
  launchd、`.env`、Keychain、Git履歴の内容および設定は変更・閲覧していない。
- つむ `homecore` の固定snapshot `10` を使用した。ops/security Context Pack
  `b426714e12cd4aa213b62fcfd9512f642777b330994b36db5315dac3cf52a97d` と検索で候補を
  絞り、重要箇所だけを確認した。再スキャンは183ファイル全件cache hitで、snapshotは不変である。
- したがって、現行端末のplist、log、backup、秘密値の実在・権限・稼働状態は本監査の結論に含めない。

## 結論

設計上の安全原則と一部のreader実装は良好である。一方で、本番運用を強くする前に、
**別障害領域への暗号化backup**、**launchdに展開する平文認証情報**、**クラウド遅延が共通lockを
占有する構造**を解消する必要がある。Qrio等の高リスク操作は、現状reader-onlyで隔離されており、
executorを有効化する根拠はまだない。

## 所見

| 優先度 | 所見 | 根拠・影響 | 推奨する次の作業 |
|---|---|---|---|
| P0 | backupは同一Macのgzip一世代で、暗号化・別障害領域への複製・定期restore検証が未完了 | `docs/security-review.md`、`docs/backup-capacity-recovery.md`。端末故障、盗難、ランサムウェア、誤削除で正本とbackupを同時に失い得る | 保存先と鍵管理を承認して決定し、認証付き暗号化、checksum、SQLite整合性、定期restore試験を実装・記録する。既存backupを削除しない |
| P0 | FusionSolar日次launchd installerは認証情報をplistの環境変数へ平文展開する | `scripts/install_macos_launchd.sh` は0600を設定するが、秘密を永続plistへ書く。設計文書自身もKeychain等への移行を未解決としている | Modbus切替完了後に不要なクラウド秘密を除去し、残る値はKeychain等から実行時に限定取得する。process引数・一時file・installer出力へ出さない回帰試験を追加する |
| P1 | 独立した収集/健全性確認が単一DB directory lockを共有し、遅いクラウド処理が他経路をskipさせる | `scripts/run_daily.sh`、`scripts/run_daily_health.sh`、`scripts/run_device_realtime.sh`。日次は収集・30日補完・品質・backupを同じlock中に直列実行する | まず実行時間・skip頻度を計測する。次に取得と短いDB反映transactionを分離するか、source別queue/lockへ移す。Modbusはクラウド経路と独立運用へ切替判定する |
| P1 | FusionSolar HTTP clientにリクエスト単位のtimeoutが見当たらず、日次の広いwall-clock timeoutへ依存する | `src/hedp/adapters/fusionsolar/client.py` のSession GET/POST。realtimeは240秒、日次の各commandは既定900秒で強制終了できるが、クラウド待ちがその間lockを占有し得る | connect/read timeout、認証再試行を含む総予算、retry対象を明示し、timeout・CAPTCHA・通信断で他sourceを妨げないテストを追加する |
| P1 | `daily-health` launchd経路にはwall-clock timeoutがない | `scripts/run_daily_health.sh` は`hedp daily-health --json`を直接実行する。DB不調等で停止した場合、次回jobや共通lockへの影響が上限化されない | realtime/dailyと同じtimeout runnerを適用し、timeout時の終了コード・次回復旧・通知方針をテストで固定する |
| P1 | FusionSolarの例外本文が一部の結果JSONへ入り得る | `src/hedp/application.py` はbattery/alarmの`str(error)`を結果へ組み込む。一方、ログは型名だけであり安全側。認証challenge側には外部応答messageを含む例外生成箇所がある | 結果JSONもerror type/分類/匿名コードのみへ正規化し、外部本文、URL、header、token、家庭IDを渡さないテストを追加する |
| P2 | 認証失効/CAPTCHAは失敗として停止し、GAS通知は6時間cooldownを持つが、Mac側の通知統合は確認できない | `src/hedp/adapters/fusionsolar/client.py`、`cloud/gas/fusionsolar/AuthHealth.gs`。GASは秘密を通知せず、recipient未設定/送信失敗も状態化する | Mac/Modbus/GASの責任境界を文書化し、認証失効の検知・再認証手順・復旧通知・通知先未設定を運用チェックにする。GAS配備前は実通知を前提にしない |
| P2 | 過去logとGit履歴の家庭固有情報は、設計文書で残存可能性が示されるが、今回内容確認はしていない | `docs/security-review.md`。新規logは5MiB×2世代、0600、redaction方針だが、旧logと過去commitは別扱い | 監視完了後に対象・復元不要性・保持要件を承認し、旧logを整理する。履歴改変はremote/clone影響を整理して別承認で実施する |

## 確認できた安全策

- 欠損・未知・無効値は成功値や0へ強制変換しない。BRAVIA normalizerはqualityを区別し、
  エラー分類は応答本文を保持しない（`src/hedp/adapters/bravia/normalizer.py`、`errors.py`）。
- SwitchBot readerは30秒timeout、有限回数、待機時間の検証、通信系だけのread-only retryを持つ。
  retryごとに署名を作り直す（`src/hedp/adapters/switchbot/client.py`）。
- Modbus clientはprivate/link-local宛てに限定し、Function Code 3/4以外を拒否するread-only実装で、
  timeoutは1〜30秒に制限される（`src/hedp/adapters/fusionsolar/modbus_tcp.py`）。
- 日次処理はlock、個別commandのwall-clock上限、途中backupの`.partial`、容量事前確認、
  正常backupの成功確認前に旧世代を消さない方針を持つ（`scripts/run_daily.sh`、
  `docs/backup-capacity-recovery.md`）。
- Qrio初期Adapterはreader-onlyであり、executorは別process/permissionの前提で未構築である。
  将来の解錠は実行直前承認、fresh state、対象照合、単発送信、job確認、read-backを必須とし、
  timeout/結果不明では自動再送しない（`docs/integrations/qrio/README.md`）。
- 共通Execution契約は、結果不明を成功にせず、再起動後の未完了操作を自動再送せず、
  stale/quality不足をgateで停止する。これは設計済みだが、現時点では実行DB schemaをまだ導入していない
  （`docs/execution-contract.md`）。

## security scanの判定

つむのsnapshot 10 scanは `critical=1, warning=6` を返した。criticalは
`src/hedp/adapters/fusionsolar/client.py` の暗号化用`password`変数である。値を表示せず周辺の
制御だけ確認した結果、これはコンストラクタから受けた値を公開鍵暗号化して認証requestへ渡す
処理であり、リテラル秘密の代入ではない。従って**このcriticalは誤検出**として扱う。

ただし、これは「実秘密が存在しない」ことの証明ではない。`.env`等のsensitive fileはつむが
読まず、本監査でも開いていない。scanのwarning（署名用token/secretの変数、環境変数参照など）は、
変数名・安全な参照だけでは秘密漏えいを確定しないため、上記の平文plistと例外本文の経路を
優先して対処する。

## 実施順

1. P0のbackup方式と秘密保管方式を、保存先・鍵の所有者・復旧責任者を含めて承認する。
2. Modbusの独立性と収集jobの実行時間/skipを測定し、P1のlock・timeoutを小さく修正する。
3. FusionSolar例外を安全な分類へ統一し、CAPTCHA/timeout/認証失効/結果不明の回帰試験を追加する。
4. Qrio等のexecutorは、ExecutionGate・追記型監査台帳・read-back・高リスク個別審査が揃うまで
   reader-onlyのままにする。
