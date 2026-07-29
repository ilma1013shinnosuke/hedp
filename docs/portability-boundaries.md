# OS非依存境界の監査（R1-05〜R1-07）

更新日: 2026-07-28
対象: HESTIAのPython Core、Adapter、配備用のOS境界

## 結論

収集・蓄積・判断・実行の共通契約とメーカー別Adapterは、macOS固有の
`launchd`、Keychain、`osascript`、固定されたmacOS利用者パスへ依存しない。
この性質は匿名のソース一覧を入力とする静的境界テストで継続確認する。

これは「LinuxとWindowsで実機運用済み」を意味しない。Linux実機試験は未実施であり、
Windowsでの実行・常駐化も未確認である。R1-06、R1-07は本書だけでは完了にならない。

## 境界

| 責務 | 所属 | OS依存の扱い |
| --- | --- | --- |
| Core、Observation、Event、Storage、Intelligence | `src/hedp/` の共通モジュール | OS固有API・固定OSパスを持たない |
| Reader／Collector／Operation Adapter | `src/hedp/adapters/` | OS固有APIを持たず、HTTP・MQTT等の交換可能な通信契約だけに依存する |
| 秘密値の注入 | `hedp.environment` と環境変数名 | 値の保管手段は外部化する。Core／AdapterはKeychainを直接読まない |
| 常駐起動・サービス登録 | `scripts/` と将来のservice/scheduler port | launchd、systemd、Windows Serviceを交換可能な配備層として扱う |
| OS通知、BLE／USB、sleep・電源検知 | 将来のplatform port | Core／Adapterへ直接混在させず、共通interface越しに接続する |

`operations` は配備・運用の薄い層であり、CoreやAdapterとは分離する。現時点で
launchd用installerはPython Coreの外にある。OS別の秘密保管機能を採用する場合も、
環境変数名とSecret Provider interfaceを共通契約にし、Keychain、Secret Service、
Windows Credential Managerの具体実装をAdapterへ入れない。

## 機械的な監査

`tests/test_platform_boundaries.py` は匿名の相対パス一覧と禁止依存一覧を使い、次を検査する。

1. portable scope（Core、Adapter、Event、Storage、Intelligence）にmacOS／Windows固有の
   importがないこと。
2. 同scopeにlaunchd、Keychain、`osascript`、固定利用者パスやmacOS system pathが
   実行時文字列として埋め込まれていないこと。
3. 匿名fixtureで表したservice、scheduler、secret-injectionのport名がCore／Adapterの
   import graphへ漏れないこと。
4. 環境変数名による設定注入はOS固有の秘密保管アクセスではないこと。

静的検査は、OS実機での動作、BLEドライバ、サービス再起動、ファイル権限の差まで
保証しない。これらは移行候補OSごとの実機適格性確認で別に証明する。

## 次の適格性確認

### Linux（R1-06、未完了）

- Pythonの対応バージョンで匿名fixtureによる全テストを実行する。
- HTTP／MQTT Readerの単発・短時間read-only適格性確認を、専用のテストDBで行う。
- systemd等の常駐化はCoreの契約試験と分け、停止・再起動後の再観測を確認する。

### Windows（R1-07、未確認）

- Pythonの対応バージョンで匿名fixtureによる全テストを実行する。
- タイムゾーンデータ、パス、サービス起動、秘密注入を個別に確認する。
- Windows専用資産管理機能を導入する場合も、HESTIAのCoreやDBへ直接結合しない。

## 判定の扱い

本書と境界テストが示すのは「現行ソースにmacOS固有依存を混入させない」ことだけである。
Linux／Windowsの実機成功、常駐配備、実機Adapter適格性は、対象OS・時刻・テスト結果を
伴う別証拠が揃うまで `fixture_only` または `reader_only` とする。
