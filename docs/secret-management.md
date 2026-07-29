# 秘密情報のOS非依存管理方針

## 目的

開発環境がmacOS、将来の運用候補がUbuntu x86_64であっても、同じ秘密管理手順を
利用できるようにする。macOS Keychainなど、特定OSだけの保管機能はSumiCoreの
正本にしない。

## 現在の扱い

- 実行時の秘密はGit管理外・mode 0600の`.env`を使用する。
- 値を回答、ログ、screenshot、fixture、Git、引き継ぎ文書へ出さない。
- launchd plistに残る既存の平文秘密は移行対象であり、恒久方式とはしない。
- 現役`.env`、plist、認証情報は、移行方式と復旧試験が完成するまで削除しない。

## 値を持たない秘密・環境台帳

この台帳は名前と用途だけを正本化する。値、現在設定されているか、長さ、更新日時は
文書、回答、logへ出さない。`HEDP_`形式は互換aliasであり、installerと配備済みjobが
canonicalな`SUMICORE_`名を直接使うまで削除しない。

### 秘密

- `SUMICORE_FUSIONSOLAR_USERNAME`、`SUMICORE_FUSIONSOLAR_PASSWORD`
- `SWITCHBOT_TOKEN`、`SWITCHBOT_SECRET`
- `SWITCHBOT_E26_DEVICE_ID`（高速直送用の家庭固有機器ID）
- `SWITCHBOT_STRIP_LIGHT_3_DEVICE_ID`（高速直送用の家庭固有機器ID）
- GAS Script Propertiesの`FUSIONSOLAR_COOKIE`、`FUSIONSOLAR_CSRF_TOKEN`
- backup runtimeが将来利用する`RESTIC_PASSWORD_COMMAND`

### 家庭固有だが認証秘密ではないもの

- `SUMICORE_FUSIONSOLAR_STATION_DN`
- `SUMICORE_FUSIONSOLAR_DEVICE_DNS`
- `SUMICORE_FUSIONSOLAR_BATTERY_DN`、`SUMICORE_FUSIONSOLAR_BATTERY_SIGIDS`
- `SUMICORE_FUSIONSOLAR_MODBUS_HOST`、`SUMICORE_FUSIONSOLAR_MODBUS_UNIT_ID`
- `SUMICORE_FUSIONSOLAR_MODBUS_EXPECTED_SERIAL`
- `SUMICORE_SWITCHBOT_HOUSEHOLD_CONFIG_PATH`
- GASのqueue folder、通知先、およびGit管理外の機器対応表

### 移植可能な通常設定

- FusionSolar base URL、Modbus port、realtime mode
- database path、lock directory、backup retention
- daily、health、equipment、SwitchBot、Modbusのtimeout・再試行上限
- `XDG_STATE_HOME`

### runtime生成状態

- Modbus continuity ID・reason・state path
- operational metrics path
- `.env`読込済みmarker
- GASの認証状態、最終検出・通知・成功時刻

runtime生成状態を暗号化正本へ戻さない。別端末への移行時は新しいruntimeが再生成する。

## 将来の正本

OS非依存で、認証付き暗号化、改ざん検出、version固定、複数端末での復旧が可能な
暗号化ファイルを秘密情報の可搬な正本とする。小さな構造化秘密にはSOPSとage、
大容量DB・Raw archiveにはresticを候補とし、役割を混ぜない。採用は復号鍵の
保管場所、紛失時の復旧、保存先、Ubuntu移行先の確定後に決める。

暗号化ファイルと復号鍵を同じrepository、同じbackup、同じ端末だけに置かない。
暗号化済みであっても、保存先、共有範囲、履歴保持を承認してからGit又はcloudへ置く。

ageは端末ごとに別のruntime recipientを持たせる。Macのruntime復号鍵はKeychainで管理し、
sanctumにはMac鍵をコピーせずHESTIA実行専用鍵を別管理する。暗号化正本、
runtime復号鍵、将来のoffline復旧鍵、bulk backup repositoryは、同じ一台又は同じ
障害領域だけに置かない。Keychainはruntime保管手段であり、可搬な正本にはしない。

採用時の最小構成候補は、秘密だけの`runtime.sops.env`、家庭固有識別子と対応表の
`household.sops.json`、recipient policyの`.sops.yaml`である。実際の保存pathとGit利用は、
recipient、共有範囲、履歴保持を承認するまで作成しない。

## macOS KeychainによるHESTIA runtime鍵

安定識別子はservice `jp.sumicore.hestia.sops-age`、account
`runtime.mac.primary.v1`とする。他プロジェクト、sanctum、用途違いの鍵を同じ項目へ
保存しない。登録・更新は`security`自身の対話promptを使い、秘密鍵を引数、環境変数、
stdin、logへ渡さない。

```text
.venv/bin/python scripts/manage_hestia_age_keychain.py register
.venv/bin/python scripts/manage_hestia_age_keychain.py check
.venv/bin/python scripts/manage_hestia_age_keychain.py print-command
.venv/bin/python scripts/manage_hestia_age_keychain.py check-sops \
  secrets/runtime.sops.env
.venv/bin/python scripts/manage_hestia_age_keychain.py probe-sops \
  --recipient age1公開RECIPIENT
```

`register`ではKeychain promptへage秘密鍵を入力する。`check`は存在と形式だけを
`available`で報告し、値、長さ、fingerprintを表示しない。`print-command`の結果を
対話中のshellで`SOPS_AGE_KEY_CMD`へ設定し、SOPS起動時だけKeychainから取得する。
`emit-for-sops`はstdoutがterminalの場合に拒否する。`check-sops`は指定した暗号化fileを
`/dev/null`へ復号し、平文をfile、terminal、logへ出さず疎通だけを確認する。
`probe-sops`は非秘密の一時データだけを公開recipientで暗号化し、Keychain鍵で復号後、
一時領域を自動回収する。

削除は新方式の復旧確認と個別承認後に限り、対象serviceを再入力して行う。

```text
.venv/bin/python scripts/manage_hestia_age_keychain.py delete \
  --confirm-service jp.sumicore.hestia.sops-age
```

`.sops.yaml`へ記録できるのは公開recipientだけである。秘密鍵、Keychain dump、
秘密の有無、秘密値の更新日時を置かない。共有正本は
`config/security/age-recipient-registry.example.json`と同じ形で、公開recipient、
鍵ID、用途、更新日、復旧手順だけを持つ。placeholderを実運用に使わない。
`.sops.yaml.example`はMacとsanctumの公開recipientを登録するための雛形であり、
実recipient確定前は`.sops.yaml`へ複製しない。

## 実行時注入

- macOSではlaunchd、Ubuntuではsystemdを薄い起動層として扱う。
- plist、unit file、process引数へ秘密値を書かない。
- 起動時に復号し、対象processの環境へだけ渡す。
- resticのpasswordは、利用可能な場合は`RESTIC_PASSWORD_COMMAND`等の標準入力に近い
  受渡しを使い、CLI引数や恒久平文fileへ置かない。
- 平文の一時fileを原則作らず、必要な場合は専用directory 0700、file 0600、
  短い寿命、確実な終了時削除、異常終了時回収を必須とする。
- 標準出力、標準エラー、例外本文、diagnostic JSONへ秘密を含めない。

外部backupを書き込むcredentialと、remote snapshotを削除・pruneできる管理credentialを
分ける。通常jobに削除権限を持たせず、retention変更は別承認にする。

## 移行と復旧

1. 必要な秘密の名前、用途、再設定条件だけを台帳化する。
2. 値を表示せず、暗号化正本を作る。
3. 別端末の隔離環境で復号と最小のread-only接続を確認する。
4. 現行jobと新方式を同時に書込み実行せず、停止・復旧手順を確認する。
5. 新方式の安定確認後、plist等の旧平文を対象ごとに承認して撤去する。
6. 露出した可能性がある秘密は撤去だけで済ませず、発行元で更新する。

Modbus-only切替後も、日次・equipment・GASがクラウドを必要とする間はFusionSolarの
cloud設定を削除しない。まず5分cloud realtime用の不要項目を候補化し、その後、
日次・equipment・GASを個別に廃止できた場合だけ残りを撤去する。

## Ubuntu移行の位置付け

Ubuntu運用は将来要件であり、現時点ではsystemd配備を実装しない。Python、SQLite、
Adapter、暗号化秘密形式をOS非依存に保ち、実際のIntel MacとUbuntuの利用可否が
確定してからservice、timer、directory、USB/BLE権限を追加する。

## platform別installerの境界

SwitchBotの一度だけ行う`.env`紐付けhelperは、mode 0600とatomic replaceを保証できる
POSIX環境専用である。Reader、Writer、ExecutionGateなどの実行時中核はOS非依存だが、
Windowsでは同helperを流用せず、同等のACLとatomic updateを保証するplatform別installerを
用意する。それまではWindows上で秘密ファイルを自動更新せず、安全側に失敗させる。
