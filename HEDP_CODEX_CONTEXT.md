# HEDP Codex Context

更新日: 2026-07-22 (Asia/Tokyo)  
リポジトリ: `/Users/shinnosuke/hedp`  
基準コミット: `ac935f6 Compress and prune daily backups`

このファイルは、HEDPの開発と運用をCodexで継続するための単一の引き継ぎ資料である。
新しい作業では最初にこのファイルを読み、必要な場合だけ実装・テスト・SQLiteの実データを確認する。
値が衝突する場合の優先順位は、現在のコード、テスト、実データ、このファイル、旧文書の順とする。

## 1. プロジェクトの目的

HEDPは、家庭のエネルギーと設備データを10年以上蓄積・活用するための基盤である。
単一のHEMSアプリではなく、将来の可視化、分析、ルール開発、自動化、アプリ開発に使う。

開発段階は次の順序を守る。

1. データ収集と可視化
2. 分析とルール開発
3. シャドーモードと半自動化
4. 自動化
5. アプリケーション開発

HEDPは家庭設備を補助するが、安全機能やベンダー標準操作を置き換えない。
HEDP、Codex、ネットワークのいずれが停止しても、設備はベンダー機能または手動で利用できなければならない。
Codexは開発・調査支援であり、ランタイム依存ではない。

基本原則:

- 正確性、保守性、長期安定性を優先する。
- RawDataを不変のSource of Truthとして残す。
- 未確認のAPI、値、単位、符号、識別子を推測して実装しない。
- 欠損値をゼロや補間値で捏造しない。
- ベンダー固有処理をCollectorへ隔離する。
- コアはOS非依存とし、launchd処理は`scripts/`へ隔離する。
- データ互換性、再現性、冪等性を守る。
- 認証情報、Cookie、CSRF、セッション、DB、バックアップ、ログをGitへ入れない。

## 2. 現在の技術構成

- Python 3.9以上
- パッケージ名: `hedp`、バージョン: `0.1.0`
- CLIエントリポイント: `hedp = hedp.main:cli`
- 永続化: SQLite (`hedp.db`)
- 主依存: `requests>=2.31`, `cryptography>=42`
- 開発依存: `pytest>=8`, `ruff>=0.11`
- タイムゾーン: 保存は原則UTC、日付指定と表示は`Asia/Tokyo`
- macOS自動実行: launchd
- SwitchBot: Open API v1.1
- FusionSolar: Web内部API。公開APIではなく、互換性変更の可能性がある。

セットアップ:

```bash
cd /Users/shinnosuke/hedp
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

標準検証:

```bash
.venv/bin/pytest -q
.venv/bin/ruff check .
git diff --check
```

2026-07-22時点では170テストが成功している。
macOS標準PythonのLibreSSLに対するurllib3の警告は出るが、現在のテスト失敗ではない。

## 2.1 開発の判断基準

判断に迷った場合は、次の基準を上から順に適用する。

### 優先順位

1. 人と設備の安全、ベンダー標準制御の維持
2. RawDataと既存DBの保全
3. 実測・観測された事実への忠実さ
4. 再現性、冪等性、監査可能性
5. 後方互換性と長期保守性
6. 障害時の部分成功と回復可能性
7. 性能、容量、運用コスト
8. 実装の簡潔さと開発速度

短期的に便利でも、上位基準を損なう変更は採用しない。

### 証拠レベル

APIとデータ仕様は次の4段階で管理する。

- `candidate`: 名前や必要性だけが存在し、通信仕様は未観測
- `devtools-observed`: ブラウザでmethod/request/responseを観測したがPython未実装
- `implementation-confirmed`: Collectorと通信契約テストがある
- `live-confirmed`: 実サービス呼出しとRawData保存まで成功済み

実装判断:

- `candidate`のAPIは実装しない。
- `devtools-observed`は、秘密を除いたrequest/response shapeを記録してからCollector候補にする。
- Collector追加にはRawData保存と通信契約テストが必要。
- Record追加にはfieldの意味、単位、timestamp、欠損表現が確認済みであることが必要。
- 画面表示名、旧GAS名、推測した連番だけを証拠にしない。

### データ取得と正規化

- 取得可能な完全応答を最初にRawDataとして保存し、その後に正規化する。
- 保存前に不要fieldを削除したり、分析しやすいshapeへ変えたりしない。
- 外部応答に存在しない値を生成しない。
- 欠損、`"--"`, `-`, null、空配列は互いに異なる可能性があるためraw表現を保持する。
- 単位や意味が未確定でもRawData収集は可能だが、Record化は保留する。
- 集計値を作る場合、元データと変換規則から再現可能にする。
- historical sourceは解像度を落とさず保存し、時間単位集計などは派生tableへ置く。

### 変更の範囲

- 一つのvendor変更で他vendorやcoreの契約を崩さない。
- OS固有コードは`scripts/`またはinstallerに置き、domain/storageへ混ぜない。
- 新しい抽象層は、複数の実装で必要性が確認できるまで追加しない。
- Observation層、UUID、別DB、クラウド基盤を「将来必要そう」という理由だけで導入しない。
- schema変更は既存DBをそのまま開けることを優先し、migrationとrollbackを設計する。
- 既存の正しい挙動を変える場合は、先に回帰テストを追加する。

### 障害と部分成功

- device、module、date、pageが独立している場合、1件の失敗で取得済みデータを破棄しない。
- エラーを隠して成功扱いにせず、終了コードまたは診断結果へ反映する。
- 再実行は取得済み範囲を重複させず、欠損だけを回復できるようにする。
- RawData保存後にRecord生成が失敗しても、次回RawDataを再取得せずRecordだけ修復する。
- 認証失敗、DNS失敗、vendor response不正、DB容量不足を区別する。
- CAPTCHA、安全確認、未知の認証challengeを自動回避しない。

### 品質判定

- 「APIが返さなかった」と「Collectorが失敗した」と「値が0だった」を区別する。
- 実測された正常な空応答は、理由をテストと文書に残した上で正常扱いにできる。
- 警告を消すために値を補完しない。まず実データで時間帯、device、再現性を診断する。
- quality commandは問題を検出するだけで、原則としてデータを変更しない。
- 修復は明示的なbackfill/rebuild処理へ分離する。

### セキュリティと外部操作

- secretは値ではなく環境変数名だけを文書化する。
- Cookie、CSRF、password、token、session ID、完全header、Copy as cURL、HARを保存・共有しない。
- 実APIのread/collectionは依頼範囲内で実行し、設定変更、制御、削除は別途明示承認を得る。
- ブラウザでdownloadしたファイルはinspect/dry-run後に取り込み、競合0を確認する。
- DBの削除、置換、復元は対象pathとbackupを確認してから行う。

### 完了条件

コード変更は、原則として次を満たして完了とする。

1. 実装と関連テストがある。
2. 全pytest、ruff、`git diff --check`が成功する。
3. 実通信が必要な変更は、可能ならlive確認する。sandbox DNS失敗は機能失敗と分離する。
4. DB変更は件数、日付範囲、競合、冪等再実行を確認する。
5. 運用変更はtimeout、lock、部分失敗、disk容量、backup回復を確認する。
6. 新しく確定した知識と未解決事項をこのファイルへ反映する。
7. ユーザーがcommitを求めた作業は、無関係な変更を含めずcommit IDを報告する。

## 3. アーキテクチャとデータ契約

```text
Vendor API -> Collector -> RawData
RawData -> RecordBuilder -> Record
Application -> orchestration
Storage -> persistence
```

Observation層とUUIDは導入していない。

### RawData

- 完全なAPI応答を変換せず`payload`へ保存する。
- `timestamp`は取得時刻。
- `target_date`は日付対象APIだけで使う。
- `metadata`はdevice DN、module ID、ページ番号、元ファイル名、SHA-256など、応答外の要求文脈。
- 古いJSONに`metadata`がなくても読み取れる。
- 秘密情報は`payload`へ入れない。
- 通常は削除、更新、上書きをしない。
- 同一内容のリアルタイム応答でも取得時刻が異なれば別スナップショットとして保持する。

### Record

- 分析向け正規化データで、RawDataから再生成できる。
- フィールドは`source`, `timestamp`, `metric`, `value`, `unit`。
- 完全一致Recordは再生成しても増えない。
- 未確認単位は推定せず`unknown`のまま扱う。

### Storage

- `raw_data(data TEXT)`と`records(data TEXT)`はJSONを保持する。
- 既存DBとの後方互換性を維持する。
- 大規模JSONテーブルでの全Record重複走査は高コストである。
- 回復処理はRawDataがありRecordがない日だけRecordを再生成する。
- SwitchBotは別の正規化テーブル群を持つ。

## 4. 主要ファイル

| ファイル | 責務 |
|---|---|
| `src/hedp/main.py` | CLI定義と構成生成 |
| `src/hedp/application.py` | 収集、回復、品質確認のオーケストレーション |
| `src/hedp/storage.py` | SQLite、RawData/Record、バックアップ |
| `src/hedp/raw_data.py` | RawDataモデル |
| `src/hedp/record.py` | Recordモデル |
| `src/hedp/configuration.py` | 環境変数と確認済み既定値 |
| `src/hedp/fusionsolar_client.py` | FusionSolar認証、セッション、再ログイン |
| `src/hedp/fusionsolar_*collector.py` | API別Collector |
| `src/hedp/fusionsolar_*record_builder.py` | FusionSolar Record生成 |
| `src/hedp/fusionsolar_report_importer.py` | 発電所XLSXレポートの監査付き取込 |
| `src/hedp/daily_health.py` | 読み取り専用の日次健全性診断 |
| `src/hedp/switchbot_*.py` | SwitchBot API、保存、取込、CLI、サービス |
| `scripts/run_daily.sh` | 03:00の日次回復・品質・バックアップ |
| `scripts/run_with_timeout.py` | プロセスグループ単位のタイムアウト |
| `scripts/run_device_realtime.sh` | 5分ごとのFusionSolarスナップショット |
| `scripts/run_equipment_daily.sh` | 03:10のBattery DC独立取得 |
| `scripts/run_daily_health.sh` | 03:20の読み取り専用健全性確認 |
| `scripts/run_switchbot_hourly.sh` | 毎時05分のSwitchBot取得 |
| `tests/` | 通信を伴わない契約、CLI、運用スクリプトのテスト |

## 5. 環境変数と秘密情報

FusionSolar必須:

- `HEDP_FUSIONSOLAR_BASE_URL`
- `HEDP_FUSIONSOLAR_STATION_DN`
- `HEDP_FUSIONSOLAR_USERNAME`
- `HEDP_FUSIONSOLAR_PASSWORD`
- `HEDP_DATABASE_PATH`

リアルタイム取得:

- `HEDP_FUSIONSOLAR_DEVICE_DNS`: 順序付きカンマ区切り

Battery DC任意上書き:

- `HEDP_FUSIONSOLAR_BATTERY_DN`
- `HEDP_FUSIONSOLAR_BATTERY_SIGIDS`

日次運用調整:

- `HEDP_DAILY_COMMAND_TIMEOUT_SECONDS`: 既定900秒
- `HEDP_DAILY_BACKFILL_DAYS`: 既定30日
- `HEDP_BACKUP_RETENTION_COUNT`: 既定1世代

SwitchBot:

- `.env`に`SWITCHBOT_TOKEN`と`SWITCHBOT_SECRET`を保存する。
- `.env`はGit管理外、mode 0600を維持する。

FusionSolarのlaunchd plistは`~/Library/LaunchAgents/`にあり、必要な認証情報を含むためmode 0600で管理する。
秘密の値を端末出力、Codex回答、ログ、テストfixtureへ表示しない。

## 6. FusionSolar認証

現在のクライアントは次の実通信を実装済みである。

1. `GET /unisso/login.action`
2. `GET /unisso/pubkey`
3. 暗号化時は`POST /unisso/v3/validateUser.action`、非暗号化時はv2
4. 認証遷移URLとリダイレクトを最大12回追跡
5. `GET /unisess/v1/auth/session`から`csrfToken`を取得

暗号化パスワードはURL encode後、RSA OAEP/SHA-384で分割暗号化し、公開鍵versionを付加する。
CSRFは`roarand`ヘッダーへ設定する。Cookieは`requests.Session`が保持する。
401/403、ログインリダイレクト、HTML応答を認証失敗とみなし、再ログイン後に1回だけ再試行する。
CAPTCHAまたはverification code要求は解決せずエラーにする。

未確認事項:

- Cookie/CSRF寿命
- rate limit
- 同時セッション挙動
- CAPTCHA発生時の運用回復

## 7. 実装済みFusionSolar API

### station-kpi-list

- `POST /rest/pvms/web/report/v1/station/station-kpi-list`
- Collector: `FusionSolarCollector`
- 1日単位、時間別データ
- 主な値: `fmtCollectTimeStr`, `productPower`, `inverterPower`, `onGridPower`, 任意`buyPower`, `powerProfit`
- RawData source: `fusionsolar`
- Record化済み
- 過去日取得と範囲取得に対応
- 2026-07-22時点のRecord範囲: 2022-12-15頃から2026-07-22 JST相当

品質確認では4必須metric、単位、値、重複、60分間隔を検査する。
`buyPower`は任意である。
実データでは`productPower`と`inverterPower`が主にJST深夜1〜3時に省略される場合があり、30日窓で31時点のmissing metric警告が出た。
不正値や間隔異常ではないが、警告を正常扱いへ変更するかは未決定である。

### energy-balance

- `GET /rest/pvms/web/station/v1/overview/energy-balance`
- Collector: `FusionSolarEnergyBalanceCollector`
- RawData source: `fusionsolar_energy_balance`
- 日別は`timeDim=2`
- パラメータ: `stationDn`, `timeDim`, `queryTime`, `timeZone=9`, `timeZoneStr=Asia/Tokyo`, `dateStr`, `_`
- `xAxis`: 00:00から23:55まで5分間隔、288点
- 数値seriesはRecord化し、`"--"`とnullはRawDataに残してRecordから省く。
- 日次合計・比率も別Recordにする。
- 単位と一部keyの意味は未確定のため推定しない。

確認済みseries:

- `productPower`, `dieselProductPower`, `mainsUsePower`
- `onGridPower`, `disGridPower`, `usePower`, `selfUsePower`
- `chargePower`, `dischargePower`, `radiationDosePower`

確認済み合計・比率:

- `totalProductPower`, `totalSelfUsePower`, `totalOnGridPower`
- `totalBuyPower`, `totalUsePower`
- `selfProvide`, `onGridPowerRatio`
- `selfUsePowerRatioByProduct`, `buyPowerRatio`, `selfUsePowerRatioByUse`

2026-07-21の実検証で2026-06-21から2026-07-20の30日分を自動バックフィルした。
その後の品質結果はissues 0、RawData without Records 0である。
月別`timeDim=4`と年別`timeDim=5`はDevToolsで観測しただけで、Collector未実装。

### device-realtime-data

- `GET /rest/pvms/web/device/v1/device-realtime-data`
- `deviceDn`, `_`
- RawData source: `fusionsolar_device_realtime`
- 現在値のみ。履歴指定は未確認。
- 完全応答と要求device DNをmetadataへ保存する。
- 4つの設定済みdevice DNでlive-confirmed。
- Signalには`id`, `name`, `unit`, `value`, 任意`realValue`, 任意`latestTime`がある。
- 現状はRawDataのみでSignal Record化は未実装。

既知device DN:

| DN | 暫定分類 |
|---|---|
| `NE=33812827` | station |
| `NE=33812828` | 不明または通信機器候補 |
| `NE=33812829` | meter候補。Signal名はあるが観測値は`-` |
| `NE=33812830` | inverter / PCS |
| `NE=33812831` | battery |

自動device discoveryは未実装で、DNの連番推測は禁止。

### query-battery-dc

- `GET /rest/pvms/web/device/v1/query-battery-dc`
- `dn`, `sigids`, `moduleId`, `_`
- RawData source: `fusionsolar_battery_dc`
- 既定battery DN: `NE=33812831`
- module 1は50要素、module 2〜4は`success=true`, `data=[]`を確認済み。
- 空moduleは正常応答として保持する。
- 現在値のみで履歴モードは未確認。
- Record化は未実装。

### alarms

- `POST /rest/pvms/fm/v1/query`
- CURRENTとHISTORYを同一endpointで取得
- RawData sources: `fusionsolar_alarm_current`, `fusionsolar_alarm_history`
- body共通: `dataType`, `domainType=SOLAR`, `pageNo`, `pageSize`, `nativeMoDn`
- HISTORYは`occurUTC.begin/end`を追加
- HISTORYはAsia/Tokyoの日ごと、deviceごと、pageごとに完全応答を保存する。
- 1 deviceの失敗後も他deviceを継続する。
- 空/短いhits、`totalCount`, total page, offset/limitからpaginationを終了する。
- 同一応答反復と最大page超過は停止する。
- alarm IDと状態遷移の安定した意味は未確定。Record化や推測dedupはしない。

## 8. FusionSolar発電所レポート

`FusionSolarReportImporter`はXLSXをzip/XMLとして読み、日別Recordと監査RawDataを作る。

- source: `fusionsolar_station_report`
- 元ファイル名とSHA-256をmetadataへ保存
- dry-runで行数、無効行、追加値、完全重複、競合を表示
- 同一timestamp/metricで値またはunitが異なる場合は全体をblockedにし、書き込まない。
- 完全一致は冪等にskipする。
- 本取込前に必ず`--dry-run`を行う。

2024-01の欠損対応:

- 2026-07-21にChromeのログイン済みFusionSolarから月別レポートを再取得
- ファイル: `/Users/shinnosuke/Downloads/発電所レポート_2024-01.xlsx`
- 31日、492値、invalid 0、conflict 0
- SHA-256: `5931859aceb4427847f8ad931d7bd8a8b7222f839643688503aa03257b57cf2c`
- 本取込後の再dry-run: insert 0、duplicate 492、conflict 0
- DBに監査RawData 1件と31日分492 Recordsが存在する。

主な正規化metricにはinstalled capacity、irradiation、temperature、PV/PCS energy、import/export、load/self-consumption、charge/discharge、revenueなどがある。
正確なheader-to-metric対応は`fusionsolar_report_importer.py`の`METRICS`を正本とする。

## 9. SwitchBot

- FusionSolarから独立したvendor adapterである。
- Open API v1.1のinventoryとstatusを取得する。
- credentialやrequest headerをDBへ保存しない。
- complete response JSONを正規化値とともに保持する。
- 未知device/fieldもraw responseで保持できる。
- Plug Mini (JP): voltage V、electricCurrent mA、weight W、electricityOfDay minutes。
- 温度、湿度、batteryがすべて0なら、rawは変更せず温度/湿度をnull、batteryを0、statusを`battery_depleted_or_unavailable`にする。
- 非対応deviceのnull CO2、Hub/Remoteの正常な空bodyは異常扱いしない。

履歴import:

- CSV/XLSXをinspect、dry-run、本取込の順で扱う。
- naive timestampはAsia/TokyoとしてUTCへ正規化する。
- 秒精度のsource valueを間引かず保存する。
- exact duplicateはskipする。
- 同時刻の異なる値は保持してconflict auditを作る。
- 欠損を補間しない。
- absolute humidity、dew point、VPDはexport値をそのまま保持し再計算しない。
- 2026-07-21に利用可能な履歴を取込済み。再取込で追加0を確認済み。
- 元のhistorical exportはリポジトリに含まれない。

## 10. CLI早見表

FusionSolar station:

```bash
hedp collect
hedp collect --start YYYY-MM-DD --end YYYY-MM-DD
hedp missing --start YYYY-MM-DD --end YYYY-MM-DD
hedp backfill-missing --start YYYY-MM-DD --end YYYY-MM-DD
hedp quality --start YYYY-MM-DD --end YYYY-MM-DD
hedp quality-diagnose --start YYYY-MM-DD --end YYYY-MM-DD
```

Energy balance:

```bash
hedp collect-energy-balance --start YYYY-MM-DD --end YYYY-MM-DD
hedp backfill-energy-balance --start YYYY-MM-DD --end YYYY-MM-DD
hedp build-energy-balance-records --start YYYY-MM-DD --end YYYY-MM-DD
hedp quality-energy-balance --start YYYY-MM-DD --end YYYY-MM-DD
```

Realtime/equipment/alarm:

```bash
hedp collect-realtime
hedp collect-device-realtime
hedp diagnose-device-realtime
hedp collect-battery-dc
hedp quality-battery-dc
hedp diagnose-battery-dc
hedp collect-alarms-current
hedp collect-alarms-history --start YYYY-MM-DD --end YYYY-MM-DD
hedp quality-alarms
hedp diagnose-alarms
```

Report/health/backup:

```bash
hedp import-fusionsolar-reports PATH --inspect
hedp import-fusionsolar-reports PATH --dry-run
hedp import-fusionsolar-reports PATH
hedp daily-health --verbose
hedp daily-health --json
hedp backup
```

SwitchBot:

```bash
hedp switchbot devices refresh
hedp switchbot collect --dry-run
hedp switchbot collect
hedp switchbot import inspect PATH
hedp switchbot import run PATH --dry-run
hedp switchbot import report
hedp switchbot observations latest
hedp switchbot gaps
hedp switchbot hourly rebuild
```

品質コマンドは問題なしで0、問題ありで1を返す。診断コマンドは詳細を表示して通常0を返す。
`daily-health`はhealthy 0、warning 1、実行不能またはDB異常のcritical 2。

## 11. 自動運用

launchd installer:

```bash
scripts/install_macos_launchd.sh
scripts/install_macos_device_realtime_launchd.sh
scripts/install_macos_equipment_launchd.sh
scripts/install_macos_daily_health_launchd.sh
scripts/install_macos_switchbot_launchd.sh
```

schedule:

| 時刻/間隔 | ジョブ |
|---|---|
| 5分ごと | device realtime、Battery DC、current alarmを共有sessionで取得 |
| 毎時05分 | SwitchBot status |
| 03:00 | station、過去30日欠損回復、energy-balance回復、Record修復、品質、backup |
| 03:10 | Battery DC独立回復snapshot |
| 03:20 | read-only daily health |

日次ジョブ`run_daily.sh`:

- `${TMPDIR:-/tmp}/com.hedp.daily.lock`を`mkdir`して多重起動を防ぐ。
- 各コマンドを`run_with_timeout.py`経由で既定15分に制限する。
- 個別処理が失敗してもstatusを保持し、可能な後続品質確認とbackupを続行する。
- stationとenergy-balanceの過去30日欠損を自動検出する。
- RawDataのみ存在する日はRecordを再生成する。
- 既存backupを新規backup前に圧縮・世代整理する。
- 新規SQLite backupもgzip圧縮する。
- 既定では最新1世代だけを保持する。

ログ: `~/Library/Logs/hedp/`

- `collect.out.log`, `collect.err.log`
- realtime/equipment/daily-health/SwitchBot各ログ
- SwitchBotログは5MiB超過時に`.1`へrotateする。

## 12. バックアップと容量

2026-07-22時点:

- `hedp.db`: 約6.8GB
- backup: `backups/hedp-20260722-034543.db.gz`, 約1.1GB
- 保持世代: 1
- filesystem空き: 約12GB
- 2026-07-22 03時台の自動backupとgzip圧縮は成功済み。

過去に、既存6.8GB backupを残したまま追加backupを作ってdisk fullになった。
未完成backupとjournalは削除済みである。
現在は新規backup前に圧縮・pruneするため、同じ原因を回避する。

復元例:

```bash
gzip -t backups/hedp-YYYYMMDD-HHMMSS.db.gz
gzip -dc backups/hedp-YYYYMMDD-HHMMSS.db.gz > /安全な復元先/hedp.db
sqlite3 -readonly /安全な復元先/hedp.db 'PRAGMA quick_check;'
```

復元時は稼働中DBを直接上書きしない。別pathへ展開、検証、停止手順確認後に切り替える。

## 13. Daily health

読み取り専用で修復はしない。確認対象:

- 6つの現行FusionSolar RawData source
- configured deviceとbattery module coverage
- 5分取得の15分以上gap
- 前日station/energy-balanceとderived Records
- alarm history device coverage
- 48時間以内のbackup
- SQLite `integrity_check`
- SwitchBotの24時間coverage、2.5時間latest/gap、API失敗、inventory変更、battery 20%以下

Mac sleepによる欠損は隠さず報告する。
結果は新tableへ永続化せずlaunchd JSON logへ出す。

## 14. 2026-07-22現在の実データ状態

SQLite集計:

- RawData: 3,922
- Record: 208,095
- station RawData: 1,330
- energy-balance RawData: 30
- device realtime RawData: 863
- Battery DC RawData: 820
- current alarm RawData: 832
- alarm history RawData: 8
- station report RawData: 39
- station Record: 142,997
- energy-balance Record: 46,475
- station report Record: 18,623

この件数は運用で増えるため、固定仕様ではなく2026-07-22のsnapshotである。
最新値を述べる前にはSQLiteを再集計する。

実API検証結果:

- station current collection成功
- 過去30日のstation missing dateは0
- energy-balance 30日分を取得済み
- energy-balance quality issues 0
- energy-balance RawData without Records 0
- station duplicate 0、invalid 0、unexpected metric/unit 0、interval issue 0
- stationは夜間発電metric省略31時点だけwarning

## 15. 既知の障害と対処

### DNS/ネットワーク制限

Codex sandboxから`jp5.fusionsolar.huawei.com`が名前解決できない場合がある。
実API検証が必要なら、認証情報を表示せずnetwork許可付きで同じコマンドを再実行する。
DNS失敗を認証失敗と混同しない。

### Record再生成が遅い

過去にはenergy-balance回復後に30日全件のRecordを再保存し、7GB DBのJSON重複確認で長時間化した。
コミット`00c595c`でRawData dateとRecord dateの差分だけを再生成するよう修正済み。
全範囲再生成へ戻さない。

### 手動中断時の子プロセス

`run_with_timeout.py`をCtrl-Cで中断すると、子プロセスが残る可能性を実運用で確認した。
通常のtimeout時はprocess groupへTERM、10秒後KILLを送る。
手動中断後は秘密を表示せず`pgrep`/`ps`で対象を確認し、対象PIDだけをTERMする。
SIGINT処理改善は未実装の課題である。

### DB全体check

6.8GB DBへの`PRAGMA quick_check`/`integrity_check`は長時間かかる。
日常はdaily healthへ任せ、手動実行時は時間とI/O余裕を確保する。
途中中断はcheck失敗を意味しない。

## 16. 未実装・未確認事項

優先候補:

1. station夜間metric省略をwarningとして残すか正常扱いにするか決定
2. `run_with_timeout.py`のSIGINT時にも子process groupを確実に終了
3. backupコマンドが不要なFusionSolar認証情報を要求する構成依存を分離
4. authoritative device inventory/topology APIの観測
5. configuration APIとSignal/master APIの観測
6. alarm hitsをレビュー後、安定したRecord mappingを設計
7. monthly/yearly energy-balanceの完全request/responseを取得
8. realtime battery/inverter SignalsのRecord化は単位と意味確認後に行う
9. meterが`-`しか返さない原因の確認
10. persistent health historyが必要になった場合だけ新しい保存設計を追加

禁止事項:

- 未観測endpointを名前から推測して実装しない。
- meter値、module ID、device DN、charge/discharge符号を推測しない。
- `"--"`, `-`, null、欠測をゼロへ変換しない。
- API responseを正規化済みデータで上書きしない。
- AI依存をscheduled runtimeへ入れない。

## 17. 開発履歴の重要コミット

- `ac935f6` Compress and prune daily backups
- `00c595c` Limit recovery record rebuilds
- `e2405fa` Harden daily recovery workflow
- `6f8e102` Import FusionSolar station reports
- `252ba66` Normalize SwitchBot zero values during import
- `ad521e8` Support SwitchBot history export variants
- `d1474df` Add SwitchBot collection and health monitoring
- `548320b` Add HEDP daily health check

`.idea/`は未追跡で、HEDPの仕様・知識の正本ではない。Codex作業で依存しない。

## 18. Codexで次の作業を始める手順

1. `git status --short`と`git log -5 --oneline`を確認する。
2. このファイルと対象コード・テストの差異を確認する。
3. ユーザーの変更を実装し、関連テストと全テストを実行する。
4. 実APIやDB書込みは依頼範囲を確認し、秘密を出力せず実行する。
5. 実データで新事実が判明したら、コード・テスト・このファイルを同時に更新する。
6. `.idea/`, `.env`, `hedp.db`, `backups/`, logsをcommitしない。
7. 変更完了時は、実装、テスト、実API確認、未解決事項、commit IDを簡潔に報告する。
