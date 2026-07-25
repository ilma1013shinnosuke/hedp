# SumiCore 全体レビューと改善ロードマップ（2026-07-25）

## 目的

SumiCoreを長期間運用しても、利用者、機器、Mac、家庭内ネットワークへ過度な負担を
かけず、安全に機能を増やせる状態へ整える。本書は設計、データ量、運用、
セキュリティ、新規Adapter追加手順の監査結果を一つの実行順序へまとめた正本である。

## 進捗更新

この文書の課題は、設計時の所見だけでなく実装状況も併記する。2026-07-25時点で、
外部エラーの固定語彙化、FusionSolarのconnect/read timeoutと操作全体予算、
`daily-health`を含む定期jobのwall-clock timeout、Modbus継続性の匿名判定、
第3層の最小判断、Execution Shadow Mode、検証付き原子的gzip部品まで実装・test済みである。

原子的gzip部品は現役日次jobへ未接続であり、別障害領域backup、秘密の暗号化正本、
Modbus-only切替、過去DBのarchive・compact・削除は未実施である。コード完成と本番配備を
混同せず、現役設定、DB、backup、秘密、外部保存先を変える作業は個別承認を維持する。

## 今回の確認範囲

- Git管理中の設計文書、コード、テスト、運用scriptを確認した。
- 初回監査ではつむの固定snapshot 10を使い、その後の差分監査ではv0.4の
  read-only snapshot 31と同一sessionを使って、候補を絞ってから必要なファイルだけを読んだ。
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

## 思想確定後の価値・負担レビュー

`PROJECT.md`で確定した「システムによって減る生活上の負担が、システムを管理する負担より
十分に大きいこと」を判定軸に、現役機能を再評価した。現時点の匿名運用メトリクスは
1日・28件だけであり、30日基準や削除判断には不足している。従って本節は、直ちに自動停止や
削除を行う指示ではなく、維持、計測、簡素化の順序を定めるものである。

| 機能 | 得ている価値 | 現在の負担・危険 | 方針 |
|---|---|---|---|
| FusionSolar Modbus 5分収集 | CAPTCHAやクラウド認証に依存せず、電力状態を家庭内で継続取得できる | SmartLogger、LAN、register profileの互換性確認が必要 | **維持・計測**。24時間の完全性と欠損を確認し、5分収集の主経路候補とする |
| FusionSolarクラウド5分収集 | Modbus切替中の比較、未対応項目の補完 | 認証、CAPTCHA、外部障害、秘密保管、二重取得の負担がある | **簡素化候補**。比較完了後は5分経路から外し、必要な日次項目だけへ限定する |
| FusionSolar日次・equipment | 発電・蓄電池の履歴補完、Modbusで取れない情報を残せる | backfill、品質検査、backupと同じ時間帯・共有lockで競合し得る | **維持・計測**。取得項目ごとにModbus代替可否を確認し、価値のない重複取得を止める |
| SwitchBot 1時間収集 | 室内環境、在室、設備状態の長期比較に使える | 詳細観測約907万行がDBとbackup負担の中心。全室・全項目の永久詳細保存は価値が均一でない | **収集は維持、保存は簡素化**。部屋・値・event別の保持規則と可逆archiveを先に検証する |
| daily health | 欠損、古さ、backup、品質の問題を実データ変更なしで発見できる | 警告をそのまま通知すると、同じ問題を毎日知らせる負担になる | **維持**。通知時は重複抑止、継続中表示、復旧通知、具体的な次の行動を必須にする |
| 日次backup | 誤操作やDB故障から復旧できる | DB全体のgzipに時間・空き容量を要し、同じMacの故障からは守れない | **必須だが再設計**。別障害領域の暗号化正本を作るまで現行1世代を残す |
| 匿名運用メトリクス | 容量、skip、timeoutを生活データなしで判断できる | 観測自体を複雑にすると保守対象が増える | **30日限定で維持**。固定語彙、最大3 MiB、日付粒度を広げず、30日後に継続価値を再審査する |
| 未配備Adapter・調査成果 | 将来の機器追加を速く、安全にする | 未検証コードを現役扱いすると更新・監視・秘密管理の負担だけが増える | **runtimeへ入れず保留**。知識、匿名fixture、reader testが必要になった時だけ更新する |
| 第3・第4層 | 将来の提案、自動化、機器横断操作に必要 | 汎用化や自動化を先行すると説明、通知、誤動作対応が急増する | **一つの低リスク用途まで保留**。価値を実測できる最小縦切りだけを作る |

現在のlaunchdは5本で、5分、1時間、日次3本の予定を持つ。全jobのログ合計は1 MiB未満で、
5 MiB・旧2世代の上限もあるため、現時点でログは容量問題の主因ではない。ただし
`device-realtime`の過去ログが大半を占め、匿名メトリクスの初期標本でも成功、失敗、
lock見送りが混在した。全serviceの直近終了状態は正常だが、標本が短いため「安定済み」とは
判定しない。失敗本文を通知へ転送せず、30日集計で連続性と予定回数比を確認する。

5分収集runnerは`modbus`を明示選択できる一方、未指定時は互換用`parallel`である。現在の
launchdには選択用環境変数がなく、長期的に併走し得る。比較期間を終えたら、次の順で
負担を減らす。

1. 保存済みの24時間監視結果だけをread-onlyで確認し、Modbusの項目完全性、欠損、遅延を確定する。
2. Modbusで代替できないクラウド項目を列挙し、5分・日次・復旧snapshotへ分類する。
3. 5分収集をModbusへ一本化する変更について、対象、影響、rollbackを提示して承認を得る。
4. 不要になったクラウド秘密をlaunchdから撤去する。日次に必要な秘密はOS非依存の暗号化正本へ移す。
5. 旧経路の知見とfixtureを残し、現役job、重複ログ、不要コードを段階的に廃止する。

この順序では、旧経路を先に削除しない。Modbusの結果が不明、欠損が多い、又は履歴項目を
代替できない場合は併走を期限付きで延長する。期限と終了条件のない恒久併走は禁止する。

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

**実装状況:** HTTP単位と操作全体のtimeout、`daily-health`を含むjobのwall-clock timeout、
Modbus continuity IDとread-only qualificationは実装・回帰test済みである。共有lockの
分割は、30日メトリクスで実害を確認してから判断するため未実施である。

### P1: 外部エラーを安全な共通形式へ変換する

外部サービスの例外本文を結果JSONやlogへ渡さず、`error_type`、分類、匿名コード、
retry可否だけに正規化する。CAPTCHA、認証失効、timeout、通信断、解析不能を成功扱いせず、
秘密、URL、header、token、家庭固有IDが出ない回帰testを追加する。

**実装状況:** 共通`ExternalErrorReport`、FusionSolarの主要collectorとapplication境界、
秘密非表示の回帰testを実装済みである。error type、category、code、retry可否は固定された
組合せだけを許可し、将来のAdapterが外部本文をcodeへ流用することも拒否する。

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
| 2 | 外部例外の安全な共通形式と回帰test（実装済み） | 可 | 不要 |
| 3 | `daily-health`とHTTPのtimeout改善（実装済み、設定変更なし） | 条件確認後可 | 本番設定変更前 |
| 4 | 1か月archiveのinspectと隔離復元計画 | 可 | 実archive作成前 |
| 5 | 暗号化backupの保存先・鍵・復旧責任決定 | 不可 | 必要 |
| 6 | OS非依存の秘密管理への移行とplist秘密撤去 | 不可 | launchd変更前 |
| 7 | 別名compact DBの作成・照合 | 不可 | DBコピー作成前 |
| 8 | DB切替、旧DB又は旧backup削除 | 不可 | 対象ごとに必要 |
| 9 | ③④のShadow Mode実装 | 可 | 実送信は別承認 |

### 承認待ちの扱い

承認が必要になっても、SumiCore全体の改善を止めない。対象、変更内容、影響、復旧方法、
承認後の次手順を承認待ち一覧へ記録し、その作業だけを停止する。同じ承認に依存しない
read-only調査、文書、匿名fixture、test、dry-run、設計は継続する。残る全作業が同じ承認に
依存するときだけ全体を停止する。

承認は記載した対象、操作、期間、回数だけに有効であり、別対象、追加操作、本番設定へ
流用しない。待機中に対象、前提、差分が変わった場合は承認を失効させ、影響を再提示する。
並行作業は元タスクのscope、禁止事項、容量・回数上限を維持し、承認対象の実施を
既成事実化しない。特に現役DB、実API、実機、launchd、外部サービス、secret、削除、
本番投入へ暗黙に範囲を広げない。

## 2026-07-25 改善状況

- 匿名運用メトリクスの安全なデータ型とread-only DB容量probeを実装し、現役jobへ組み込んだ。
  初期標本は1日・28件で、30日評価や保存削減判断にはまだ不足している。
- FusionSolar HTTPにconnect/read timeoutと操作予算を追加した。実APIでは未検証である。
- `daily-health`にwall-clock timeoutを追加した。launchd plistの再生成は不要であり、
  現役jobの実行結果は次回運用確認の対象とする。
- 外部例外を固定分類へ変換し、外部本文、URL、家庭固有IDを結果とlogへ渡さない
  回帰testを追加した。
- SwitchBotとequipmentのrunnerに設定可能なwall-clock上限を追加し、複数jobの匿名メトリクス
  記録とrotationを短時間lockで保護した。
- Keychainを将来の正本候補から外し、`docs/secret-management.md`へOS非依存方針を定義した。
  暗号化方式とUbuntu配備は未決・未実装である。
- `PROJECT.md`へ価値優先順位、生活負担を基準にした成功条件、非目標を明記し、新規Adapterの
  lifecycleとonboarding gateをこの上位方針へ揃えた。

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
