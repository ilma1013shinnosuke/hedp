# データ量・保存・負荷監査（2026-07-25）

## 結論

現役SQLiteは **6.85 GiB**、うち SwitchBot 観測が **9,068,540件**で、容量と将来の
backup作成時間を支配している。直ちにDBを変更する必要はないが、現状のまま詳細行を
増やし続ける運用は、10年時点で現在Macの空き容量とatomic backupに必要な空き容量が
ほぼ拮抗する。優先順位は、(1) 観測の月別read-only集計、(2) 可逆archiveの小規模な
復元検証、(3) 明示承認後の別名compact DB作成、である。

この監査はread-onlyで実施した。DBのpayload、機器ID、名称、場所、時刻列の値、秘密値は
表示していない。DB、backup、launchd、`.env`、実API、Gitは変更していない。

## 根拠と現状

| 項目 | 実測/実装根拠 | 評価 |
|---|---:|---|
| `hedp.db` | 7,356,096,512 bytes = 6.85 GiB、SQLite 4 KiB page × 1,795,922、freelist 0 | 未使用ページによる即時縮小余地はない。 |
| 共通Raw | `raw_data` 10,195行 | FusionSolar等のRaw。JSON内訳は内容を読まない方針のため未集計。 |
| 共通Record | `records` 217,309行 | Rawから正規化した時系列。 |
| SwitchBot詳細 | `switchbot_observations` 9,068,540行 | DBの主な増分。canonical keyで完全重複を抑止。 |
| SwitchBot派生/運用表 | hourly summary 151,220、collection event 1,531、gap 184、import run 31、conflict 0行 | 集約表・運用表の行数は詳細表より小さい。 |
| コード/文書tree | 183 files / 808.7 KiB（つむ snapshot 10） | runtime DBやbackupはGit tree外であり、つむ storage reportの容量とは別に扱う。 |
| ログ | 各job・各streamは5 MiBを超えた時に現行+旧2世代へrotate | job数に比例して上限が増える。gzip圧縮はしない。 |
| backup | 日次、gzip後の世代数既定1 | DB全体gzipは災害復旧用で、検索可能なRaw archiveの代替ではない。 |

`data-retention-policy.md`には、過去取込が約29か月・約9.067M観測行だったとの記録が
あり、今回の件数と整合する。これは過去CSV取込を含むため、将来のライブ増加率そのもの
ではない。従って「日次増分」は未測定であり、次回read-only集計の対象にする。

## 保存モデルと重複

| 層 | 現在 | 重複・負荷の見立て | 対応 |
|---|---|---|---|
| RawData | `raw_data` に完全JSON | 正規化再構築には必要。ただしSQLite内は未圧縮。 | 未成熟Adapterは90日現役+月別可逆archiveを原案どおり適用。 |
| Record | `records` に正規化JSON | Rawと同じ事実の二層保存だが、再利用・検索目的が異なる。 | source別のRaw/Record件数・byte比をread-onlyで可視化してから対象を絞る。 |
| SwitchBot observation | 列正規化された詳細値 | 過去CSVでは詳細履歴が大半。既知・正常なAPI成功時の`raw_payload_json`複製は実装上抑制済み。 | 90日以降は月別archiveとhourly summaryを使う設計を検証する。 |
| event/quality | collection event、gap、conflict | 成功証跡は30日、異常証拠は90日という方針と、現行DBには明示的な期限実装がまだ分離している。 | retention jobを作る前に、event種別・保持先・archive要否をデータ辞書化。 |

SwitchBotでは `canonical_key` により同一の観測値を挿入しない。さらに正常に解釈できる
既知profileの成功API応答はRaw本文を二重保存せず、未知field、異常、空/不正bodyだけを
診断証拠として残す。このため、同Adapterの今後のAPI収集によるRaw重複は低減される。
一方、過去CSV由来の9M行は、詳細行自体が容量の中心である。

## 取得周期・処理負荷

- SwitchBotの既知profileは全て1時間周期。CSV import行には60秒期待周期があるため、
  過去履歴と現行pollingを同じ増加率と見なしてはいけない。
- FusionSolar realtime jobは5分周期（1日288点のseries、realtime responseも5分ごとに保存）。
  `parallel`監視期間は複数collectorが動き得るため、cutover完了前は同一事実の二重取得を
  監視する。
- 日次jobはcollect、最大30日backfill、品質確認、atomic backup、gzipを実行する。
  DBが大きくなるほどbackupとgzipのI/Oが日次処理の支配要因になる。
- 共通lockによりDB writerの同時実行は避ける。lock競合時はjobをskipするため、容量対策で
  長時間のarchive/compactを行う場合にも、収集欠損と競合を事前に評価する必要がある。

## 10年容量予測（概算）

基準は「6.85 GiB / 約29か月」である。29か月を約883日として平均化すると、DB全体の
粗い増加率は **約2.83 GiB/年（約7.9 MiB/日）**、10年では **約28.3 GiB** となる。
これは過去CSV取込、index、全Adapterを混ぜた上限寄りの外挿であり、将来のlive rateを
保証しない。詳細観測だけを直線外挿するなら約10,270行/日、約3.75M行/年である。

| シナリオ | 10年の現役DB概算 | 前提・不確実性 |
|---|---:|---|
| A: 現状の詳細保持を継続 | 約28 GiB | 過去29か月の総DB増加率を一定と仮定。新機器・Rawサイズ・index増加で上振れする。 |
| B: 詳細を90日だけ現役へ | 詳細部分の目安はAの約90/883 = 10.2% | 実際のDBはmetadata、集約、Raw、indexを含むため、DB全体を単純に10.2%にはできない。 |
| C: B + gzip cold archive | 未測定 | JSONL gzipの圧縮率は実データ標本を作らずには算出しない。設計上は可逆・checksum付き。 |

現在の空き容量は約34 GiB。backup作成は「DB本体 + max(512 MiB, DBの20%)」の空きを
開始前に要する。Aの約28 GiBでは必要空きが約33.6 GiBとなり、現状空きとほぼ同水準で、
他のファイルやfilesystemの変動を考慮すれば安全ではない。これは容量削除の指示ではなく、
90日現役化を先に検証すべき根拠である。

## 改善優先度

1. **P0: read-only日次容量メトリクスを追加する。** table/source/月ごとの件数、`length`合計、
   DB page数、WAL/backup容量、archive有無だけを出し、payloadや識別子を出力しない。最低30日
   実測後にlive増加率で予測を更新する。
2. **P1: SwitchBotの1か月をarchive前提でinspectし、隔離コピーで圧縮率・復元時間を測る。**
   既存の`archive_switchbot_observations.py --inspect`はread-only。実archive作成、別媒体複製、
   compact DB作成・切替は明示承認を分ける。
3. **P1: retention data dictionaryを実装前に確定する。** Adapter/sourceごとに最大payload、頻度、
   active日数、archive単位、集約、event保存年数、削除ゲートをlocal設定へ置く。
4. **P2: cold archive済み月を除外した別名compact DBを検証する。** 既存builderはarchive checksum、
   全table件数、schema、integrityを照合し、元DBを直接削除しない。切替・旧DB削除は別承認にする。
5. **P2: backup容量の運用閾値をdaily healthへ追加する。** 「次回atomic backup必要量」と空き容量の
   差を警告し、34 GiBのような境界状態を事前に通知する。

## SwitchBot代表月のread-only試算

2024年7月を完全月の代表として、`switchbot_csv_export`だけをSQLiteの`mode=ro`と
`query_only`でinspectした。DB、archive、compact DBは変更又は作成していない。

| 項目 | 結果 |
|---|---:|
| 観測件数 | 490,295件 |
| Raw本文の合計 | 89,721,700 bytes（約85.6 MiB） |
| 全列JSONLの未圧縮概算 | 約626 MiB |
| 可逆gzipの概算 | 約25〜45 MiB |
| inspect所要時間 | 約34秒 |

gzip概算は20,000件のメモリ内標本から得たもので、実archiveの作成結果ではない。
Raw本文合計と全列JSONL概算は対象が異なり、前者だけをarchive容量と見なさない。

現在のindexは`(device_id, observed_at_utc)`とcanonical key向けであり、
月次inspectの`(source, observed_at_utc)`条件には合わない。このため約900万行を走査する。
月次archiveを定常運用へ入れる前に、同条件の複合indexをschemaと新規DBで検証する。
現役DBへのindex追加は、作成時間、一時容量、writer停止時間を提示して別途承認を得る。

## 受入条件

- 実API、DB、backup、launchdを変更せず、30日分の匿名化された容量時系列を取得できる。
- 1か月分のarchiveでgzip整合性、全行JSON、件数、時刻範囲、checksum、隔離先での復元を確認する。
- compact DBで、archive対象+残存観測の件数一致、既知tableの件数一致、`integrity_check=ok`を満たす。
- backup必要空き容量に対して十分な安全余裕を定量化し、切替前に利用者が対象月・検索性能低下・
  復元手順を承認する。

## 調査記録

- つむ: project `homecore`、固定snapshot 10。`storage report`、context build、searchを使用。
  snapshotは183ファイルすべてcache hitで再利用され、候補12,490 token相当を1,792 token相当へ
  縮約したcontext packを用いた。
- DB統計はSQLite read-only接続でtable名、schema、行数、page統計のみを取得した。値やpayloadは
  取得・表示していない。
- 2026-07-25時点。数値の単位はGiB（2^30 bytes）。
