# 解析資産の削除候補（2026-07-25）

## 目的と制約

9系統の引き継ぎ台帳と
`docs/integrations/artifact-disposition-20260725.md`を根拠に、削除承認へ使える
単位で現存資産を再計測した。今回は存在確認、件数、論理容量、実割当容量、
稼働参照の有無だけを確認し、内容、秘密値、実Raw、認証済み状態、hashは読んでいない。
削除、移動、Git操作、実機/API/DB/backup/launchd変更は行っていない。

容量は2026-07-25時点の値である。論理容量はファイルの見かけ上の合計、
実割当容量は`du`またはallocated blocksによるMac上の解放見込みであり、
iCloud placeholderやsparse fileでは大きく異なる。

## 結論

- 再生成・再取得できる派生物だけなら、現在の実割当で最大
  **937,656,320 bytes（894.22 MiB）**が削除候補になる。
- 解析project原本まで知識統合後に削除する場合、重複を除いた実割当は最大
  **992,391,168 bytes（946.42 MiB）**である。これは上記894.22 MiBを含むため加算しない。
- Qrioとエコキュートの専用AVDは合計
  **11,004,018,688 bytes（約10.25 GiB）**の実割当があるが、認証状態や秘密候補を
  含み得るため通常削除候補には含めない。別の高リスク承認単位とする。
- まず再生成可能物だけを削除し、project原本、写真、実Raw、AVD、稼働中Qrio Localは
  混ぜないのが安全である。

## 承認単位A: 再生成・再取得可能物

この表は、正式知識と最小実装・testがHEDPへ統合済みであることを前提にした
最初の削除候補である。秘密候補を含む`.wrangler`は除外した。

| 絶対パスまたは厳密対象集合 | 種類 | files / dirs | 論理容量 | 実割当容量 | 復元・再取得 | 秘密候補 | 稼働参照 |
|---|---|---:|---:|---:|---|---|---|
| `/Users/shinnosuke/Documents/sumicore/node_modules` | npm依存 | 29,516 / 2,890 | 707,601,446 B | 761,671,680 B | lockfileから再取得可 | なし想定 | なし |
| `/Users/shinnosuke/Documents/sumicore/dist` | build出力 | 40 / 15 | 1,713,557 B | 1,818,624 B | buildで再生成可 | なし想定 | なし |
| `/Users/shinnosuke/Documents/sumicore/.vinext` | build cache | 13 / 4 | 150,771 B | 176,128 B | 自動再生成可 | なし想定 | なし |
| `/Users/shinnosuke/Documents/Codex/2026-07-22/s-2/work` | SwitchBot公開clone | 193 / 46 | 1,463,390 B | 1,503,232 B | 公開元から再取得可 | なし想定 | なし |
| `/Users/shinnosuke/Documents/Codex/2026-07-24/new-chat/work/sumicore-miele-adapter/.ruff_cache`、`/Users/shinnosuke/Documents/Codex/2026-07-24/new-chat/work/sumicore-miele-adapter/src/sumicore_miele_adapter/__pycache__`、`/Users/shinnosuke/Documents/Codex/2026-07-24/new-chat/work/sumicore-miele-adapter/tests/__pycache__`、同rootの`.DS_Store` | Miele cache | 16 files | 51,392 B | 86,016 B | 自動再生成可 | なし想定 | なし |
| `/Users/shinnosuke/Documents/Codex/2026-07-22/new-chat-8/ecocute-control-panel/.vinext` | build cache | 13 / 4 | 151,222 B | 176,128 B | 自動再生成可 | なし想定 | なし |
| `/Users/shinnosuke/Documents/Codex/warema-wms-research/.mypy_cache` | type-check cache | 18 / 2 | 2,552,032 B | 2,560,000 B | 自動再生成可 | なし想定 | なし |
| `/Users/shinnosuke/Documents/Codex/warema-wms-research/.ruff_cache` | lint cache | 4 / 2 | 2,558 B | 16,384 B | 自動再生成可 | なし想定 | なし |
| `/Users/shinnosuke/Documents/Codex/2026-07-22/new-chat-3/work/addon-warema-wms` | 公開clone | 52 / 25 | 416,345 B | 577,536 B | 公開元から再取得可 | なし想定 | なし |
| `/Users/shinnosuke/Documents/Codex/2026-07-22/new-chat-3/work/ha-warema-wms` | 公開clone | 66 / 28 | 919,510 B | 1,110,016 B | 公開元から再取得可 | なし想定 | なし |
| `/Users/shinnosuke/Documents/Codex/2026-07-22/new-chat-3/work/wms2mqtt` | 公開clone | 42 / 22 | 410,613 B | 548,864 B | 公開元から再取得可 | なし想定 | なし |
| `/Users/shinnosuke/Documents/Codex/2026-07-21/project-smartledz-reverse-engineering-brief-docx/.tools` | JDK/JADX/apktool等 | 469 / 103 | 693,041,535 B | 0 B | 再取得可 | なし想定 | なし |
| `/Users/shinnosuke/Documents/Codex/2026-07-21/project-smartledz-reverse-engineering-brief-docx/analysis/2.0.4/decoded` | apktool派生物 | 13,840 / 607 | 117,493,702 B | 90,112 B | 保存XAPKから再生成可 | vendor固定情報のみ | なし |
| `/Users/shinnosuke/Documents/Codex/2026-07-21/project-smartledz-reverse-engineering-brief-docx/analysis/2.0.4/jadx` | JADX派生物 | 6,200 / 606 | 52,754,762 B | 57,344 B | 保存XAPKから再生成可 | vendor固定情報のみ | なし |
| `/Users/shinnosuke/Documents/Codex/2026-07-21/project-smartledz-reverse-engineering-brief-docx/work/brief-render` | PDF/PNG render | 4 / 1 | 291,734 B | 61,440 B | 文書から再生成可 | 個人環境情報の可能性 | なし |
| `/Users/shinnosuke/ApkProjects/jp.co.endo_light.smartledzpersonal` | Android Studio APK import | 11,932 / 523 | 138,602,311 B | 166,891,520 B | 保存XAPKから再生成可 | workspace情報の可能性 | なし |
| `/Users/shinnosuke/Documents/Codex/2026-07-22/s-2`配下の全`__pycache__` | SwitchBot bytecode | 43 files | 129,757 B | 0 B | 自動再生成可 | なし想定 | なし |
| `/Users/shinnosuke/Documents/Codex/2026-07-24/new-chat-2/sakura_bridge/__pycache__`、`/Users/shinnosuke/Documents/Codex/2026-07-24/new-chat-2/tests/__pycache__` | サクラbytecode | 6 files | 23,783 B | 36,864 B | 自動再生成可 | なし想定 | なし |
| `/Users/shinnosuke/Documents/Codex/bravia-kj55x8500f-research`配下の全`__pycache__` | BRAVIA bytecode | 45 files | 165,602 B | 274,432 B | 自動再生成可 | なし想定 | なし |

Smart LEDZの`.tools`、decoded、JADXは論理容量が大きいが、現時点の実割当は
合計147,456 bytesだけである。これらを削除しても見かけ上の容量ほど空きは増えない。
容量効果の中心はSwitchBot `node_modules`とSmart LEDZ APK importである。

## 承認単位B: 知識統合後にproject単位で削除可能

下記は、HEDP側変更をGitへ保存し、継続解析に必要な最小原本を選び終えた後の候補である。
表の容量は各root全体であり、承認単位Aを含む。Aと重ねて合算しない。

| 連携 | 絶対パス | files / dirs | 論理容量 | 実割当容量 | 判断 |
|---|---|---:|---:|---:|---|
| Miele接続試作 | `/Users/shinnosuke/Documents/Codex/2026-07-23/new-chat/miele-monitor` | 11 / 1 | 26,216 B | 57,344 B | `.env`を除外し、安全な再設定後に要承認 |
| Miele候補Adapter | `/Users/shinnosuke/Documents/Codex/2026-07-24/new-chat/work/sumicore-miele-adapter` | 31 / 9 | 85,902 B | 155,648 B | 正式normalizer/test統合後 |
| エコキュート | `/Users/shinnosuke/Documents/Codex/2026-07-22/new-chat-8` | 93 / 36 | 812,356 B | 1,048,576 B | `.wrangler`を分離し、未確認解析の残存を確認後 |
| MTRL-RK-901SI | `/Users/shinnosuke/Documents/Codex/2026-07-21/new-chat-2` | 4 / 3 | 32,584 B | 40,960 B | 正式文書のGit保存後 |
| SwitchBot offline研究 | `/Users/shinnosuke/Documents/Codex/2026-07-22/s-2` | 303 / 90 | 1,683,321 B | 1,802,240 B | profile/fixture/test統合後 |
| SwitchBot画面prototype | `/Users/shinnosuke/Documents/sumicore` | 29,711 / 3,043 | 710,220,639 B | 764,891,136 B | 現在のCodex workspace。Git保存・workspace切替・秘密候補分離後 |
| 日産サクラ | `/Users/shinnosuke/Documents/Codex/2026-07-24/new-chat-2` | 18 / 7 | 80,747 B | 122,880 B | transport未確定の失敗知見を正式化後 |
| Smart LEDZ解析project | `/Users/shinnosuke/Documents/Codex/2026-07-21/project-smartledz-reverse-engineering-brief-docx` | 20,790 / 1,457 | 902,824,721 B | 39,284,736 B | XAPK正本1組とrestricted知見を先に選ぶ |
| Smart LEDZ APK import | `/Users/shinnosuke/ApkProjects/jp.co.endo_light.smartledzpersonal` | 11,932 / 523 | 138,602,311 B | 166,891,520 B | XAPK正本が残る場合に限る |
| WAREMA正式研究 | `/Users/shinnosuke/Documents/Codex/warema-wms-research` | 134 / 39 | 2,884,696 B | 3,215,360 B | 正式code/test/docsのGit保存後 |
| WAREMA公開clone群 | `/Users/shinnosuke/Documents/Codex/2026-07-22/new-chat-3/work/addon-warema-wms`、`/Users/shinnosuke/Documents/Codex/2026-07-22/new-chat-3/work/ha-warema-wms`、`/Users/shinnosuke/Documents/Codex/2026-07-22/new-chat-3/work/wms2mqtt` | 160 / 75 | 1,746,468 B | 2,236,416 B | URL、commit、licenseの記録後 |
| Qrio解析project | `/Users/shinnosuke/Documents/Codex/2026-07-21/q` | 12,412 / 1,441 | 2,126,235,591 B | 6,696,960 B | 稼働中Qrio Localと秘密候補を含むため通常削除禁止 |
| BRAVIA | `/Users/shinnosuke/Documents/Codex/bravia-kj55x8500f-research` | 118 / 40 | 301,951 B | 602,112 B | 正式normalizer/fixture/testのGit保存後 |

Mieleの実データ`/Users/shinnosuke/.miele-energy-monitor`は48 files、論理285,754 B、
実割当430,080 Bあるが、再取得不能な時点証拠と秘密候補を含み得るため、この表の
通常削除容量には含めない。

## 承認単位C: 再取得不能または秘密候補

| 絶対パス | 種類 | files / dirs | 論理容量 | 実割当容量 | 扱い |
|---|---|---:|---:|---:|---|
| `/Users/shinnosuke/Documents/sumicore/.wrangler` | runtime state/cache | 8 / 9 | 45,858 B | 69,632 B | 内容を読まず個別承認。通常cacheと混ぜない |
| `/Users/shinnosuke/Documents/Codex/2026-07-22/new-chat-8/ecocute-control-panel/.wrangler` | runtime state/cache | 4 / 9 | 45,206 B | 53,248 B | 内容を読まず個別承認 |
| `/Users/shinnosuke/.miele-energy-monitor` | 実Raw/history/audit | 48 / 3 | 285,754 B | 430,080 B | 代表証拠・履歴の保存方針決定まで残す |
| `/Users/shinnosuke/Documents/Codex/2026-07-22/new-chat-3/work/image-review` | 利用者提供写真の変換物 | 4 / 1 | 5,341,505 B | 5,345,280 B | 再取得不能。型番知識で十分か個別承認 |
| `/Users/shinnosuke/Documents/Codex/2026-07-21/project-smartledz-reverse-engineering-brief-docx/analysis/2.0.4/xapk` | 版固定アプリ原本 | 7 / 1 | 33,514,930 B | 33,533,952 B | 現在版の再解析用に1組残す候補 |
| `/Users/shinnosuke/.android/avd/Qrio_Android_15.avd`と`/Users/shinnosuke/.android/avd/Qrio_Android_15.ini` | Qrio専用AVD | 32 / 11 | 8,012,690,502 B | 7,948,595,200 B | 認証状態・秘密候補。別の明示承認なしに削除禁止 |
| `/Users/shinnosuke/.android/avd/SumiCore_Ecocute_Research_API35.avd`と`/Users/shinnosuke/.android/avd/SumiCore_Ecocute_Research_API35.ini` | エコキュート専用AVD | 24 / 9 | 3,119,338,496 B | 3,055,431,680 B | 認証状態・秘密候補。別の明示承認なしに削除禁止 |

`.env`、Keychain、認証済み画面、添付Logcat、Qrio LocalのHTTP storage/cacheは
内容未読のまま現状維持とし、この削除候補一覧には加えていない。

## 稼働参照監査

- 上記解析projectの絶対pathを参照する実行中processは確認されなかった。
- HEDPの`src/`、`scripts/`、`config/`、`cloud/`に、上記解析projectの絶対path参照は
  確認されなかった。
- Android Emulator processは0件だった。
- Qrio Local processは稼働中で、`com.shinnosuke.qrio-local`もlaunchctlへ登録されている。
  Qrio project、installed app、runtime、LaunchAgentの撤去は別作業とする。
- `/Users/shinnosuke/Documents/sumicore`は現在のCodex workspaceである。
  配下の再生成可能物以外は、HEDPへのGit保存とworkspace切替後に削除する。
- `com.sumicore.switchbot`と`com.hedp.switchbot`のlabelが存在するが、外部SwitchBot研究rootの
  絶対path参照はHEDP runtime codeにない。launchd plistは秘密を含み得るため内容未読であり、
  削除実行直前に安全な方法で参照先だけを再確認する。

## 推奨する削除順

1. HEDPの変更をcommitし、可能ならremoteへpushする。
2. 承認単位Aを種類別に再計測し、対象pathをもう一度提示して承認を得る。
3. `node_modules`、build/cache、公開clone、APK派生物の順に削除する。
4. 削除後に空き容量、残存正本、testを確認する。
5. 承認単位Bは連携ごとに別承認し、project rootを一括削除する。
6. 承認単位Cは通常削除と分離し、AVD、実Raw、写真、版固定XAPKを個別判断する。

削除時は、開始前後のfilesystem空き容量、削除したfiles/dirs、実際の解放量、
残した正本、再取得方法を処分記録へ残す。現在のData volume空きは
39,202,435,072 bytesであり、今回の棚卸し中に変化させていない。
