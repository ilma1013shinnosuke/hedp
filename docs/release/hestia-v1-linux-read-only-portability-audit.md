# v1.0.0-rc.1 Linux read-only portability監査

更新日: 2026-07-30

## 結論

Python Core、Adapter、read-only collectorはLinux上でimport・CLI起動まで成功した。
macOS固有依存はportable scopeへ混入していない。一方、v1.0の正式保証対象はmacOSであり、
Linux/sanctumはread-only validationに限定する。永続service、scheduler、実機適格性は
未保証である。

## 原典コードと既存試験

| 境界 | 原典 | 証拠 |
| --- | --- | --- |
| Core/AdapterのOS固有SDK禁止 | `src/hedp/` | `tests/test_platform_boundaries.py` |
| 固定macOS path・launchd・Keychain禁止 | portable scope | `tests/test_platform_boundaries.py` |
| macOS KeychainをCoreから分離 | `scripts/manage_hestia_age_keychain.py` | `tests/test_manage_hestia_age_keychain.py` |
| host tool/versionの秘密なし確認 | `scripts/check_sanctum_release_host.py` | `tests/test_sanctum_release_host.py` |
| 未認定操作をshadowに固定 | `config/release/hestia-v1.json` | `tests/test_hestia_release_assurance.py` |
| read-only register範囲 | `src/hedp/adapters/fusionsolar/` | FusionSolar adapter・qualification tests |

sanctum実測ではPython 3.14.4、package import、依存整合、CLIが合格した。SOPSは
sanctum専用鍵で平文fileを作らず復旧した。配置・rollbackも成功した。

## 残るportability gap

1. `supported_platforms`はmacOSのみで、Linuxは明示的にdeferred。
2. Linux向けsystemd service/timer installerと停止・再起動適格性がない。
3. runtime secret providerはsanctum専用鍵で実証したが、汎用Linux portとして
   interface・rotation・障害復旧を製品化していない。
4. SmartLogger read-only collectorはLinux上で起動したが、接続元制限候補により
   live observation 0件。Linux実機適格性は未成立。
5. Python 3.14.4で限定runtimeは合格したが、CI matrixとして継続保証していない。
6. filesystem、systemd user session、restart policy、log rotation、upgradeの
   Linux運用契約が未実装。

## v1.0.0-rc.1で許可する範囲

- release artifact、wheel、imports、CLI、SOPS、隔離DB、rollbackの検証
- 上限付き・単発・read-only collector
- 匿名receipt作成

## 禁止する範囲

- 永続service/timer/cron登録
- ExecutorまたはModbus write
- Linuxを正式supportedへ昇格
- live observation未成立のまま`deployed`へ昇格
- macOS鍵のコピー、平文秘密file、秘密を含むlog

## 昇格条件

秘密なし受入check、SmartLogger許可変更の個別承認、単発read-only成功、
短時間・24時間適格性、systemd停止・再起動・rollback試験、Linux運用契約、
最終release checkerを同一candidateで合格させる。それまでは
`linux_read_only_validation`を維持する。
