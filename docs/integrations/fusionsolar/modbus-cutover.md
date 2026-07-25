# FusionSolar Modbus TCP切替・旧方式廃止基準

## 方針

SmartLogger経由のModbus TCPを、太陽光・蓄電池の現在値収集の主経路とする。
インターネット、クラウド認証、CAPTCHAに依存しないため、家庭LAN内の常時収集に
適している。書き込み機能は実装せず、Function Code 3/4の読取りだけを許可する。

旧FusionSolarクラウド方式は直ちに削除しない。Modbusと並行運転し、下記の合格条件を
満たしてから、定期実行、コード、秘密情報の順に段階廃止する。

切替時は`SUMICORE_FUSIONSOLAR_REALTIME_MODE=modbus`を実行環境へ設定し、
`install_macos_device_realtime_launchd.sh`を再実行する。`parallel`はModbus取得後に
旧クラウドrealtimeも実行する監視期間専用である。未設定時は従来互換の`parallel`となり、
24時間確認前に自動で経路を変えない。

## Modbus本番合格条件

- 24時間以上の連続観測
- 5分周期の成功率が99%以上
- 15分を超える欠損がない
- Mac再起動、ネットワーク再接続後に自動復旧する
- RawData 1件から確認済み10指標を再生成できる
- 発電電力、当日発電量、蓄電池SOCをクラウド値または機器画面と比較し、
  単位・桁・時刻が整合する
- CAPTCHAやインターネット停止中もModbusだけは継続する
- DBロック、タイムアウト、ログ容量に異常がない

「連続観測」は、収集を実行するMacがsleep、再起動、明示停止していない24時間を指す。
Mac停止中の空白はModbus障害へ数えないが、その観測窓は合格判定に使わず、復帰後から
24時間を取り直す。開発Macでの合格は通信経路の検証であり、将来の常時起動機へ移した後も
同じ検査を再実施する。

`daily-health`はModbusを独立した5分ソースとして監視し、最新取得の遅延、15分以上の
取得間隔、確認期間内の各RawDataに対応する10個のRecord不足を警告する。クラウド認証が停止して
いても、Modbusの警告は独立して確認できる。

`parallel`ではModbus取得後にクラウド取得を行い、どちらかの失敗でrunner全体が失敗となる。
従って`device_realtime`の成功・失敗件数だけでModbus品質を判定しない。Modbus RawDataの
5分間隔、対応する10 Record、欠損値、15分超gapを独立集計し、クラウド側の失敗と分ける。

## 常時稼働性の改善

直近のread-only再判定では、取得値と10指標の正規化は正常だった一方、直近24時間の
5分枠充足は約75%で、15分超の空白もあった。このため**本番切替は不可**である。
空白にはOS更新後の再起動と開発Macのsleepが含まれるが、旧`parallel` runnerの失敗だけでは
クラウド失敗、共通DB lock、Mac停止、Modbus通信失敗を区別できなかった。

次の改善を追加した。`parallel`経路では次回収集から連続性証拠をRawData metadataへ追加する。
実機・ネットワーク設定は変更しない。`modbus`専用plistへの切替は、24時間合格と利用者承認まで
行わない。

- `modbus`専用modeは既存の共通DB lockを維持し、1回のjob全体を240秒以内に制限する。
  既存の`parallel` modeは収集内容・timeout・lockを変えず、判定用の匿名continuity metadata
  だけを追加する。
- 再試行はDNS・接続・socket timeoutのように、応答受領・DB保存前と確認できるtransport
  failureだけを最大3回に限定する。DB commit、decode、protocol、設定、wall-clock timeoutは
  結果不明として再試行しない。
- privateな0600 sentinelは、boot marker変化、5分周期を大きく超えたscheduling gap、
  boot marker取得不能を検知する。新しい非再利用continuity IDを次のRawDataへ付けるため、
  sleep・再起動・sentinel state消失の前後を同じ24時間へ結合しない。ID自体は出力しない。
- `hedp qualify-modbus`はread-onlyで、最新continuity IDの**直近24時間だけ**を評価する。
  99%の5分slot、15分超gapなし、Rawから再decodeした10 Recordのmetric/unit/有限数値一致、
  最新snapshotの鮮度、boot evidenceを集計だけで返す。旧RawDataにIDがない場合は、遡って
  合格にはしない。
- `modbus`専用modeで再登録したlaunchd jobだけに`RunAtLoad`を付ける。login/reboot後に
  次の5分周期まで待たず開始する。ただしsleep中の取得は保証しないため、復帰後は新しい
  24時間を測定する。

この改善はMacを常時起動機へ変えるものではない。開発Macでsleepを除外して合格にすることも
せず、将来の常時起動機へ移した後も同じqualificationを再実施する。

### 配備確認

検証済みwheelを現行仮想環境へ反映し、既存`parallel` launchd jobを同じplistで再開した。
再開後の1回目は終了コード0で、Modbus RawDataにcontinuity IDと固定語彙のreasonが付与された。
`qualify-modbus`は最新epochだけを読み取り、予想どおり`under_24h`として不合格を返した。
従って正式な24時間観測は開始済みだが、まだ本番切替条件を満たしていない。

## 段階的な廃止手順

1. Modbusを既存5分ジョブの先頭で収集する。
2. 24時間はクラウド現在値収集も残し、比較材料を蓄積する。
3. 合格後、クラウドのdevice-realtime、Battery DC、current alarm定期取得を停止する。
4. 日次履歴などModbusで代替できない機能は、必要性を個別判定する。
5. 旧Collectorの確認済みendpoint、request/response shape、失敗条件、CAPTCHA挙動を
   文書と匿名fixtureに残す。
6. 旧コードをGit履歴で復元できる状態にして削除する。
7. 不要になったクラウド認証情報をlaunchd plistから除去する。

## 削除しないもの

- 既に保存済みのクラウドRawDataとRecord
- DBバックアップ
- API調査結果、データ辞書、匿名fixture
- XLSXレポート取込など、Modbusで代替できない履歴機能

## 現在の確認済み範囲

- 対象機種: `SUN2000-4.95KTL-JPL1`
- 通信: SmartLoggerのEthernet1経由Modbus TCP
- 通信アドレス: `.env`の設定値を使用
- 取得: 機種、入力電力、有効電力、周波数、内部温度、運転状態、積算・当日発電量、
  蓄電池状態・電力・SOC
- 保存: `fusionsolar_modbus_tcp` RawDataと10個のRecord
- シリアル番号: 期待機器の照合用として`.env`だけに保存し、通常RawDataへ複製しない

## 2026-07-25 read-only判定

現役DBの`fusionsolar_modbus_tcp`だけをread-onlyで集計した。値、Raw本文、機器ID、
家庭固有時刻、秘密値は表示・保存していない。DB、実API、実機、launchd、`.env`は
変更していない。

| 項目 | 結果 | 判定 |
|---|---:|---|
| 観測範囲 | 31時間以上 | 24時間分の材料はある |
| 保存済みRawData | 293件 | 収集・保存経路は動作 |
| 正規化snapshot | 292回 | RawData 1件にRecordがなく、原因は別確認 |
| 10指標が揃ったsnapshot | 292/292 | 合格 |
| `null`のRecord | 0件 | 合格 |
| 通常間隔の中央値 | 約5.1分 | 合格 |
| 直近24時間の5分枠充足 | 約75% | 不合格 |
| 直近24時間の15分超gap | あり | 不合格 |
| 最長の連続区間 | 約7.4時間 | 24時間連続条件を未達 |
| 最長区間の概算充足率 | 約98.9% | 99%条件をわずかに未達 |

この期間にはmacOS更新後の再起動と、開発Macの停止・sleepが含まれる。従って空白の全てを
Modbus通信障害とは断定しない。一方、停止時間を推測で除外して合格扱いにもしない。
判定は**継続観測**とし、Mac復帰後の新しい24時間窓で再集計する。

また、匿名運用メトリクスは観測開始直後で、`device_realtime`の成功と失敗が混在している。
`parallel`全体の失敗にはクラウド認証・通信側だけの失敗も含まれ得るため、Modbus RawDataが
保存された回をModbus成功の根拠とし、runner全体の結果は補助証拠として扱う。

## 合格後に行う変更とrollback

合格しても自動切替はしない。次を利用者へ提示し、launchd変更の承認を得る。

1. `SUMICORE_FUSIONSOLAR_REALTIME_MODE=modbus`を実行環境へ設定する。
2. `install_macos_device_realtime_launchd.sh`を再実行し、5分jobからクラウド認証情報を外す。
3. plist構文、登録状態、一回のModbus収集、RawDataと10 Recordの増加を確認する。
4. 日次・equipmentに残るクラウド取得は、Modbusで代替できない項目のため当面維持する。
5. 24時間を再監視し、問題がなければ旧5分クラウド経路を廃止候補とする。

影響は5分ごとのdevice realtime、Battery DC、current alarmクラウドsnapshotが停止すること
である。既存データ、日次履歴、backupは変更しない。

rollbackは、旧plistの安全な退避物又はinstallerへ`parallel`を指定して再登録し、一回実行と
保存を確認する。Modbus-only登録に失敗した場合は新jobを停止し、旧設定を復元する。
rollback確認前に旧コード、旧plist、クラウド秘密を削除しない。

## 改善版を実運用へ反映する明示手順

コードのレビューと利用者承認後だけに実行する。旧plistやクラウド経路は先に削除しない。

1. 監視を継続する間は`parallel`のままinstallerを再実行せず、既存の比較条件を保つ。
2. `modbus`への切替を承認した時点で、modeを`modbus`にして
   `scripts/install_macos_device_realtime_launchd.sh`を再実行する。これはlaunchd plistの
   更新・再登録、cloud realtime用の環境値除去、`RunAtLoad`有効化を伴う。
3. plist構文、登録状態、1回のModbus収集、RawDataと10 Recordの増加を、秘密値を表示せず
   確認する。
4. その後24時間以上、Mac停止・sleep・明示停止を挟まずに稼働させ、
   `hedp qualify-modbus`が`qualified`を返すことを確認する。
5. この確認後も旧クラウド経路を自動削除しない。旧5分クラウド取得の停止は、影響とrollbackを
   改めて確認して承認する。
