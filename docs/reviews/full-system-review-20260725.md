# SumiCore 全体レビューと改善ロードマップ（2026-07-25）

## 目的

SumiCoreを長期間運用しても、利用者、機器、Mac、家庭内ネットワークへ過度な負担を
かけず、安全に機能を増やせる状態へ整える。本書は設計、データ量、運用、
セキュリティ、新規Adapter追加手順の監査結果を一つの実行順序へまとめた正本である。

## 今回の確認範囲

- Git管理中の設計文書、コード、テスト、運用scriptを確認した。
- つむの固定snapshot 10を使い、候補を絞ってから必要なファイルだけを読んだ。
- DBはpayload、機器ID、名称、場所、時刻、秘密値を表示しないread-only統計だけを使用した。
- 実機、実API、家庭LAN、現役DB、backup、launchd、`.env`は変更していない。

## 総合評価

四層の責任分界、Rawを証拠として残す考え、欠損・品質の共通表現、機器自立性、
readerとexecutorの分離は一貫している。③は価値を判断し、④は許可済みIntentを検査、
実行、確認するという境界も明確である。現時点で③④は設計段階に留まり、
本番機器へ直接操作する危険な経路は確認されなかった。

したがって、全面的な作り直しは不要である。次に必要なのは、抽象化を増やすことではなく、
長期運用で顕在化する容量、backup、秘密保管、timeout、共通lockを測定可能にし、
小さな単位で改善することである。

## 優先課題

### P0: データを同じMacの故障から守る

現状のgzip一世代backupは可逆だが、正本と同じMacにある。同時故障、盗難、誤削除からは
守れない。保存先、暗号鍵の所有者、復旧責任者を利用者が決めた後、認証付き暗号化、
checksum、SQLite整合性確認、隔離環境での定期restore試験を導入する。

既存backupは、新しい複製と復元試験が成功するまで削除しない。

### P0: launchdから秘密値の永続平文をなくす

FusionSolarの既存installerはmode 0600でも、認証情報をplistへ展開する。Modbus TCPへの
切替結果を確認した後、不要になったクラウド秘密を撤去し、残る秘密はOS非依存の
暗号化正本から実行時だけ取得する。秘密をprocess引数、一時file、installer出力、
例外本文へ出さない。

### P1: 容量とbackup余裕を毎日測る

現役DBは6.85 GiBで、SwitchBot詳細観測約907万行が増加量の中心である。過去29か月を
単純外挿した10年値は約28 GiBだが、これは過去importを含む粗い値である。

まず30日間、table/source/月ごとの件数、payloadを読まないbyte合計、DB page数、
WAL/backup容量、次回atomic backupに必要な空き、archive有無だけを匿名メトリクスとして
保存する。実測後に保存期間と容量予測を更新する。

### P1: Rawと詳細履歴を可逆archiveで小さくする

既知で正常なSwitchBot API応答は、正規化できた場合にRaw本文を重複保存しない実装になった。
未知機種、未知field、形式異常、異常測定、空応答は診断証拠として残す。

過去詳細は、いきなり削除しない。まず1か月だけを対象に、元DBを変更しないinspect、
月別JSONL gzip、checksum、全行構文、件数、時刻範囲、隔離先での復元を検証する。
成功後、90日を現役DBへ残す原案とhourly summaryの検索性を評価する。compact DBは別名で
作り、元DBとの照合後に、切替と旧DB削除を別々に承認する。

### P1: 共通lockとtimeoutによる欠損を見えるようにする

外部I/Oを含む長い日次処理が共有DB lockを保持し、他jobがskipする可能性がある。
最初にlock保持時間、skip回数、取得元別欠損、DB transaction時間を匿名メトリクス化する。
skipを正常成功に見せず、原因と影響時間を日次healthで示す。

FusionSolarの各HTTP requestにはconnect/read timeoutと処理全体の予算を設ける。
`daily-health`にもwall-clock timeoutを設ける。実測で上限超過が確認された場合だけ、
外部取得と短いDB反映の分離、又はsource別queue/lockを導入する。

### P1: 外部エラーを安全な共通形式へ変換する

外部サービスの例外本文を結果JSONやlogへ渡さず、`error_type`、分類、匿名コード、
retry可否だけに正規化する。CAPTCHA、認証失効、timeout、通信断、解析不能を成功扱いせず、
秘密、URL、header、token、家庭固有IDが出ない回帰testを追加する。

### P1: 最初のExecution経路をShadow Modeで固定する

最初の低リスク・単一対象・絶対状態指定だけで、
`Intent → ExecutionGate → dispatch → read-back → audit`を通す。Shadow Modeでは実送信せず、
許可、期限、鮮度、品質、重複、能力、manual override、停止時動作を検査する。

鍵、火気、給湯、強い空調操作は、この経路と結果不明時の停止規則がtestで固定されるまで
reader-onlyのままにする。Adapterを直接呼ぶ本番自動化経路を禁止する。

### P2: 第3層は一つの判断から実装する

最初から汎用ルールエンジンを作らない。まず一つの情報表示又は提案を対象に、入力品質、
鮮度、判断しない条件、利用者指示、系列上限、説明文を匿名fixtureで固定する。
自動操作、複数機器最適化、学習、恒久的な好み推定は後段とする。

### P2: 大きな集約点と旧名称を段階的に整理する

`main.py`と`application.py`は、新機能に触れる時だけCLI parser、依存構築、workflowを
挙動変更なしで分離する。大規模な一括書換えはしない。

SumiCoreを新規の正名とし、`hedp`、`HEDP_`、旧CLI、旧launchd labelは互換理由、
観測方法、終了条件を一覧管理する。安定運用とrollback条件を満たすまで互換を消さない。

## 新規Adapterの標準経路

新しい機器は、`docs/adapter-onboarding-checklist.md`のGate 0〜8を順に通す。

1. 目的、価値、非目標、禁止事項を決める。
2. 公開資料を調べ、事実、第三者情報、推測を分ける。
3. 隔離したread-only観測で型、欠損、時刻、品質、頻度を確認する。
4. 匿名fixture、データ契約、timeout、retry上限、Raw保存条件を固定する。
5. readerを先に完成させ、executorを別公開機能・別実行経路にする。
6. 操作価値を審査し、必要な能力だけ個別の操作契約を作る。
7. fixture、Shadow、dry-run、低リスク実機の順で段階試験する。
8. 監視、rollback、仕様変更、廃止条件を定めて配備する。

調査成果は更新可能な知識として残す。APK、AVD、decoded tree、cache等の再生成物は
知識、匿名fixture、実装、testへ必要事項を移した後に削除候補とする。未確認事項が残る間は、
事実と推測を混ぜず、Adapterの完成を装わない。

## 実施順序と承認境界

| 順序 | 作業 | 自動実施 | 個別承認 |
|---:|---|:---:|:---:|
| 1 | 匿名容量、lock、skip、timeoutメトリクスの設計とtest | 可 | 不要 |
| 2 | 外部例外の安全な共通形式と回帰test | 可 | 不要 |
| 3 | `daily-health`とHTTPのtimeout改善 | 条件確認後可 | 本番設定変更前 |
| 4 | 1か月archiveのinspectと隔離復元計画 | 可 | 実archive作成前 |
| 5 | 暗号化backupの保存先・鍵・復旧責任決定 | 不可 | 必要 |
| 6 | OS非依存の秘密管理への移行とplist秘密撤去 | 不可 | launchd変更前 |
| 7 | 別名compact DBの作成・照合 | 不可 | DBコピー作成前 |
| 8 | DB切替、旧DB又は旧backup削除 | 不可 | 対象ごとに必要 |
| 9 | ③④のShadow Mode実装 | 可 | 実送信は別承認 |

## 2026-07-25 改善状況

- 匿名運用メトリクスの安全なデータ型とread-only DB容量probeを実装した。
  現役jobへの組込みと保存はまだ行っていない。
- FusionSolar HTTPにconnect/read timeoutと操作予算を追加した。実APIでは未検証である。
- `daily-health`にwall-clock timeoutを追加した。launchd plistの再生成は不要であり、
  現役jobの実行結果は次回運用確認の対象とする。
- 外部例外を固定分類へ変換し、外部本文、URL、家庭固有IDを結果とlogへ渡さない
  回帰testを追加した。
- Keychainを将来の正本候補から外し、`docs/secret-management.md`へOS非依存方針を定義した。
  暗号化方式とUbuntu配備は未決・未実装である。

## 完了条件

- 日次の実増加量、backup余裕、lock skip、timeoutが秘密なしで確認できる。
- Raw archiveは可逆で、checksum、件数、範囲、復元、SQLite整合性を検証済みである。
- 正本とbackupが別障害領域にあり、秘密値がplistへ永続平文保存されない。
- 取得元一つの遅延が、他の取得予定を無制限に妨げない。
- エラーと結果不明が成功として記録されず、外部本文や秘密を保存しない。
- 新規Adapterはreaderを先に完成させ、操作はExecutionGateを迂回できない。
- 第3層は判断しない条件を含めて説明可能で、第4層は価値判断を行わない。

## 関連文書

- `docs/reviews/system-architecture-review-20260725.md`
- `docs/reviews/data-load-review-20260725.md`
- `docs/reviews/operations-security-review-20260725.md`
- `docs/adapter-onboarding-checklist.md`
- `docs/adapter-lifecycle.md`
- `docs/data-retention-policy.md`
- `docs/execution-contract.md`
- `docs/03_intelligence.md`
- `docs/04_execution.md`
- `docs/secret-management.md`
- `docs/operational-metrics.md`
