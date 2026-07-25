# 現在のファイルと役割

この文書は、現行コードと運用ファイルの役割を確認するための対応表である。
古いパスや終了した移行作業を現役情報として残さない。

## 共通部分

| 現在のファイル | 主な役割 | 将来の分類候補 |
|---|---|---|
| `application.py` | 収集、保存、品質確認の進行管理 | 責務を確認しながら各層へ分割 |
| `configuration.py` | 実行環境から設定を取得 | 共通設定とメーカー設定を分離 |
| `storage/raw_data.py` | 取得した事実の不変形式 | 移動済み |
| `storage/record.py` | 利用可能な正規化データ | 移動済み |
| `storage/database.py` | RawDataとRecordのSQLite保存 | 移動済み |
| `storage/jsonl_archive.py` | checksum付き可逆JSONL gzip archive | 実装済み・実データ未作成 |
| `daily_health.py` | 読み取り専用の運用点検 | 運用監視。新しい層は作らない |
| `main.py` | CLIと部品の組み立て | 最後まで薄い入口として維持 |

## FusionSolar（移動済み）

| 現在のファイル | 主な役割 | 状態 |
|---|---|---|
| `adapters/fusionsolar/client.py` | 認証とHTTP通信 | 移動済み |
| `adapters/fusionsolar/station_collector.py` | 発電所KPI取得 | 移動済み |
| `adapters/fusionsolar/energy_balance_collector.py` | 5分電力収支取得 | 移動済み |
| `adapters/fusionsolar/device_realtime_collector.py` | 機器現在値取得 | 移動済み |
| `adapters/fusionsolar/battery_dc_collector.py` | 蓄電池DC情報取得 | 移動済み |
| `adapters/fusionsolar/alarm_collector.py` | 現在・履歴アラーム取得 | 移動済み |
| `adapters/fusionsolar/record_builder.py` | KPIをRecordへ変換 | 移動済み |
| `adapters/fusionsolar/energy_balance_record_builder.py` | 電力収支をRecordへ変換 | 移動済み |
| `adapters/fusionsolar/report_importer.py` | 旧レポートの監査付き取込 | 移動済み |
| `adapters/fusionsolar/gas_queue_importer.py` | GAS受け渡しRaw JSONの検査・監査付き取込 | 実装済み・未配備 |
| `adapters/fusionsolar/modbus_tcp.py` | 読み取り専用Modbus TCP通信 | 実装済み・監視中 |
| `adapters/fusionsolar/modbus_collector.py` | Register範囲のRaw取得 | 実装済み・監視中 |
| `adapters/fusionsolar/modbus_profiles.py` | 機種別Register定義とdecode | 実装済み・監視中 |
| `adapters/fusionsolar/modbus_record_builder.py` | Modbus Rawを10指標へ変換 | 実装済み・監視中 |

現役の検証済みAPI知識は `docs/integrations/fusionsolar/README.md` に置く。
GAS版FusionSolarの未配備コードは `cloud/gas/fusionsolar/` に置く。前日分Rawを
Drive受け渡しキューへ保存し、ダウンロード後にMac側で検査・重複判定・監査付き取込を
行うコードまで実装済みである。認証期限切れの検知と任意メール通知も実装済みだが、
自動再認証、GAS・trigger配備、実データでの取込確認は未完了である。
実サービスへ配備するまではローカルlaunchd収集が正本である。
実環境への段階切替と復旧条件は`docs/cutover-runbook.md`を正本とする。

## SwitchBot（移動済み）

| 現在のファイル | 主な役割 | 状態 |
|---|---|---|
| `adapters/switchbot/client.py` | Open API通信と署名 | 移動済み |
| `adapters/switchbot/service.py` | 機器一覧と状態取得の進行管理 | 移動済み |
| `adapters/switchbot/importer.py` | CSV・XLSX履歴取込 | 移動済み |
| `adapters/switchbot/storage.py` | SwitchBot専用テーブル | 移動済み。統合は別途判断 |
| `adapters/switchbot/cli.py` | SwitchBot用CLI | 移動済み |

## 運用スクリプト

| スクリプト | 稼働内容 |
|---|---|
| `run_daily.sh` | 日次取得、欠損補完、品質確認、バックアップ |
| `run_device_realtime.sh` | 5分ごとの機器現在値・蓄電池・現在アラーム |
| `run_modbus_realtime.sh` | 切替後の5分Modbus専用取得。共通DB lock・上限付きtransport再試行・連続性証跡 |
| `run_equipment_daily.sh` | 日次の蓄電池復旧スナップショット |
| `run_switchbot_hourly.sh` | SwitchBotの1時間ごとの状態取得 |
| `run_daily_health.sh` | DBを変更しない日次健全性確認 |
| `check_post_cutover.py` | 保存済み状態JSONによる切替後24時間監視 |
| `archive_switchbot_observations.py` | 月単位の読取専用inspectと可逆archive作成 |
| `build_compact_database.py` | 検証済みarchiveを除いた別名小型DBの構築 |

`run_device_realtime.sh`は監視期間中の`parallel`と、切替後の`modbus`を明示選択する。
未設定時は従来互換の`parallel`であり、自動的には切り替わらない。

DBを使用する6つの実行スクリプトは `com.hedp.database.lock`を共有する。これにより、
別ジョブ同士が同じSQLiteを長時間読み書きすることを防ぐ。健全性確認は読み取り専用
だが、全体整合性検査中に書込みを妨げるため、このロックへ参加する。

## 現在の実データ

- `hedp.db`: RawData、Record、SwitchBotデータの現役SQLite。Git管理外。
- `backups/`: 圧縮済み世代バックアップ。Git管理外。
- `runtime/`: 取込・調査の実行時ファイル。Git管理外。
- `~/Library/Logs/hedp/`: launchdの運用ログ。Git管理外、権限0600。

これらはディレクトリ整理では移動・複製しない。
