# 読み取り専用Adapter 実機適格性確認計画

## 目的

Smart LEDZ、エコキュート、Qrio、Miele、FusionSolarのReaderを、実機や標準機能を
変更せずに確認し、
取得周期、通知欠落、負荷、再接続、データ品質を実測で決める。ここで扱うのは第1層の
観測だけであり、機器操作、設定変更、自動判断、常駐化は含めない。

## 共通原則

- eventで変化を早く受け、有限周期のsnapshotで現在状態の正しさを回復する。
- eventとsnapshotは同じObservation契約へ正規化し、発生時刻と受信時刻を分ける。
- eventは秒・ミリ秒精度を保持する。機器横断分析は第2層で1分bucketへ整列する。
- 取得周期と保存粒度を混同しない。current stateは更新し、同一値を無制限に追記しない。
- 欠損を0、空文字、前回値で埋めない。部分eventに含まれない項目は欠損にしない。
- AdapterはOS、scheduler、secret store、DBから独立させる。macOSとLinuxで同じReaderを使う。
- 再起動・再接続後は保存済み状態を機器へ適用せず、read-only snapshotから再同期する。
- タイムアウト、再試行、総経過時間、取得回数には必ず上限を設ける。
- 秘密値、家庭固有ID、名称、IP、MAC、SSIDをfixture、通常ログ、報告へ出さない。

## 導入段階

### 0. オフライン基準

全fixture test、全体test、lint、秘密検査、Linux非依存検査を成功させる。匿名fixtureから
同じ正規化結果を再生成できることを確認する。この段階では通信しない。

### 1. 単発read-only確認

利用者の明示承認後、対象と通信経路を一つずつ確認する。1回または有限回の取得だけを行い、
設定変更、操作command、機器探索のための登録・再登録を行わない。応答は秘密を除去した
集計結果だけ報告する。

### 2. 短時間観測

単発確認に成功した機器だけ、10〜30分の有限観測を行う。次を計測する。

- 応答時間の分布とtimeout率
- event到着遅延、同一eventの再送、順序逆転
- snapshotとeventの一致、不一致、回復時間
- 変化がないときの応答量と保存増加量
- 認証失効、切断、再接続時の挙動
- 機器標準機能、公式アプリ、家庭LANへの目視可能な影響

### 3. 24時間限定観測

短時間観測に問題がない機器だけ、開始・終了時刻と停止方法を決めて24時間観測する。
常時運用のlaunchdやsystemdはまだ登録しない。既存収集経路と並行する場合は、sourceを
分け、同じ事実を二重適用しない。

### 4. 取得周期の確定

24時間の成功率、鮮度、API負荷、データ量、機器への影響から、必要な鮮度を満たす最も低い
頻度を採用する。周期は設定値とし、Readerへ埋め込まない。

## 共通qualification harness

`src/hedp/adapters/read_only_qualification_harness.py`は、既存の
`ReadOnlyOfflineQualificationChecker`を各sampleへ適用する共通の有限runnerである。
このmodule自身はtransport、認証、機器探索、scheduler、現役DBを所有しない。呼出側が
`collect() -> RawData`だけのread-only probeを注入する。probeの実機利用はこのharnessの
実装とは別に、対象と時間を示した利用者承認を必要とする。

`QualificationPlan.single()`、`.short()`、`.day_24()`は同じ保存・要約契約を使う。

- singleは1 sample、最大5分で終了する。
- shortは10〜30分、intervalから算出した有限sample数で終了する。
- day_24は24時間ちょうど、最大2,000 sampleで終了する。
- 1 sampleのtimeoutは300秒以下かつsample間隔以下、sleep確認間隔は60秒以下とする。
- 失敗数、DB容量、要約に含める失敗証拠数にも上限を持つ。
- 未来の開始時刻は拒否し、timeoutしたprobeの完了を待たずに次のprobeを重ねない。
- 要約は成功率、応答時間のp50・p95・最大、連続失敗sample数を匿名集約して返す。
- singleとshortは全sample成功を要求する。day_24は99%以上かつ連続欠損15分以内を
  最低条件とし、planに設定した最大失敗数へ先に達した場合はさらに厳しくfail closedとする。

保存先は利用者が明示した`*.qualification.sqlite3`だけである。既存ファイルを再利用する
場合はtest-only marker、schema版、table列、foreign keyが一致しなければ開かない。新規作成は
排他的に行い、regular fileの同一性をSQLite接続の前後で確認してsymlink置換を拒否する。
POSIXでは新規DBを`0600`で作成し、再開時も保持descriptorが`0600`でなければ変更せず拒否する。
WindowsにはPOSIX modeの意味がないため、同じ排他作成と
file同一性確認を行い、保存directoryのWindows ACLを引き継ぐ。SQLite接続ごとに
`foreign_keys=ON`を確認する。`hedp.db`、環境設定のDB、
launchd/systemd、通常収集jobは参照しない。DBへ保存するのはsource、stage、予定・記録時刻、
固定reason code、payload byte数、evidence件数、処理時間だけで、Raw payload、metadata、
例外本文、target alias、IP、MAC、tokenは保存しない。checkerから未知reason codeが返っても
その文字列は保存・表示せず、固定の`qualification_reason_unrecognized`へ置き換える。

各sampleをcommitしてから次へ進む。明示中断は`interrupted`とし、同じplanとrun IDで再開
すると完了済みindexを再取得しない。停止中に過ぎたslotは即時catch-upせず`missed`として
匿名失敗証拠へ残す。planが変わった再開、期限超過、timeout、probe例外、source不一致、
qualification不合格、DB容量超過はfail closedとする。summaryは件数と固定reason codeだけを
返し、失敗Rawを表示しない。sample中に期限へ達した場合も、その結果を採用せず終了する。
DB容量はpathを再参照せず、接続中保持するguard file descriptorから判定する。

Python threadは安全に強制停止できない。harnessのtimeoutはrunをfail closedにして後続probeを
開始しないための上限であり、実行中の`collect()`を取り消す機構ではない。各probeは必ず自身の
transport timeoutをharnessのsample timeoutより短く設定し、有限時間で戻る必要がある。

テストでは注入clock、sleeper、匿名RawData、一時DBだけを使ってsingle、short、24時間相当を
即時再現する。これは実機24時間の合格を代替せず、runnerの時間・再開・保存契約だけを確認する。

## 初期周期候補

以下は実測開始用の候補であり、本番値ではない。

| 対象 | 主経路 | snapshot候補 | 低頻度情報 | 理由 |
|---|---|---:|---:|---|
| Smart LEDZ | local read | 活動時間中10〜15分、画面表示・操作・予約直後 | scene・予約は起動時、表示時、変更後、日次 | 就寝・不在中は機器scheduleを主とし、既知の予約境界だけ確認する |
| エコキュート | ECHONET INF候補 | 待機中15〜30分、画面表示・再接続時、操作中1分 | property mapは起動時、未知EPC・firmware変更時 | 通知を主経路候補とし、操作時だけbounded read-backを増やす |
| Qrio | cloud history/status | statusは画面表示・操作後、履歴は再接続時と日次 | 電池・firmware・Hubは日次 | 携帯pushは人への通知とし、履歴差分をSumiCoreの正本候補にする |
| Miele | SSE | 接続時と10分程度の照合候補 | 連携状態は60分、機器情報は起動時と日次 | SSEを主経路とし、RESTは再接続後の正しさ回復へ限定する |
| FusionSolar | local Modbus TCP | 既存の有限周期候補を24時間比較で確定 | 機器構成・firmwareは起動時と日次 | クラウド経路から独立した現在値を取り、IP変更時は安全な再発見だけ行う |

緊急性や安全性を取得頻度だけで代替しない。例えばQrioの防犯判断を数分pollだけへ依存させず、
公式機能と物理操作を主経路として維持する。

## 機器別の確認内容

### Smart LEDZ

- Gateway、Group、Scene、Schedule、Device、Sensorの宣言済みread requestだけを使う。
- 家庭固有IDは実行時aliasへ変換し、未解決対象を通常結果へ出さない。
- frame分割、request ID相関、未知schema、応答遅延を確認する。
- scene実行、照明操作、schedule編集、backup、OTA、Wi-Fi設定は行わない。

### エコキュート

- property mapとGetだけを使用し、INF通知を観測する。
- 当該機が返したEPCだけを能力として確定し、規格だけから実装を推測しない。
- 部分INFと後続Getの統合、未知EPC、値なしEDT、通知欠落を確認する。
- Set、沸き増し、風呂自動、追いだき、予約、休止は行わない。

### Qrio

- status、health、historyのGET相当だけを使用する。
- 利用規約、継続利用性、rate limitを先に確認し、tokenをログへ出さない。
- 履歴eventの重複、遅延、状態snapshotとの一致、Hub offline時の読み取りを確認する。
- 施錠、解錠、設定変更、共有権限変更、登録・再登録は行わない。

### Miele

- 本番前に、過去に露出した可能性があるClient Secretを利用者が再発行・再設定する。
- 最初にREST snapshotを1回取得し、その後SSEを有限時間だけ観測する。
- SSE切断後は上限付きで終了し、無制限再接続を行わない。再開時はRESTで再同期する。
- start、stop、program変更、予約変更などの家電操作は行わない。

### FusionSolar

- 通常レジスタのread-only Modbus TCPだけを本番候補として確認する。
- 単発確認ではインバーター、電力計、蓄電池の既知registerだけを有限回取得する。
- 到達不能時の再発見は同一LAN、既知機器署名、候補数と総時間に上限を設け、設定を変えない。
- 既存クラウド取得と比較する期間はsourceを分け、同一事実を二重適用しない。
- オプティマイザー取得は現在保留であり、24時間適格性確認へ含めない。
- register write、機器検索、firmware更新、設備追加・削除、運転parameter変更を行わない。

## 合格条件

- 24時間の予定slotに対して99%以上の取得またはevent継続性がある。
- 15分を超える説明不能な観測空白がない。
- event欠落や切断後、次のsnapshotで現在状態を回復できる。
- 重複eventを状態へ二重適用しない。
- 欠損、古い値、未知値、異常値が共通品質区分で区別される。
- 秘密値と家庭固有情報が通常ログ、fixture、報告へ出ない。
- 取得により機器設定、公式アプリ、機器標準制御へ悪影響が出ない。
- 同一テストがmacOSとLinuxで同じ正規化結果になる。

99%を満たしても、長い連続欠損、秘密漏えい、設定変化、機器影響が一つでもあれば不合格とする。

## 不合格時

自動で頻度を上げ続けない。対象機器だけを停止し、理由を`timeout`、`rate_limited`、
`auth_expired`、`schema_changed`、`event_gap`、`state_mismatch`等で記録する。第3層や第4層へ
不確かな状態を正常値として渡さない。回数、wall clock、backoff上限を変更するときは、
再度短時間観測から確認する。

## 本番常駐化の条件

5機器を一括で常駐化しない。機器ごとに適格性確認を終え、周期、停止方法、容量上限、
監視指標、Linux service定義を確認してから個別に導入する。常駐化、DB接続、既存job切替、
実API認証、実機通信は、それぞれ対象と影響を示して明示承認を得る。
