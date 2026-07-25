# 解析成果の統合監査 2026-07-25

## 目的

別作業で得た解析成果を丸ごと複製せず、SumiCoreで長期保守する価値のある知識、
メーカー固有実装、匿名fixture、テストだけへ凝縮する。元ファイルの削除は本監査では
行わない。

## 監査対象

| 連携 | 台帳上の規模 | 主な容量 | 判断 |
|---|---:|---|---|
| Miele@home | 90 files / 約389 KiB | 実Raw約279 KiB | 小型。候補実装を選択移植 |
| エコキュート | 91 files / 約748 KiB | 別管理AVD約2.85 GiB | ECHONET知識だけを正式化 |
| MTRL-RK-901SI | 正式文書2件 | 大容量物なし | IR実測前なので文書のみ |
| SwitchBot | 約29,857 files / 約711 MiB | `node_modules`等約709 MiB | 既存Adapterへ差分統合 |
| 日産サクラ | 16 files / 約40 KiB | 別用途AVDは対象外 | 規約確認まで実装保留 |
| Smart LEDZ | 全スコープ約14.60 GiB | 大半が共有SDK/AVD | 専用知識・codeだけを選択 |
| WAREMA | 297 files / 約9.42 MiB | cacheと利用者画像 | 画像を通常移管しない |
| Qrio | 12,452 files / 実割当約7.41 GiB | 専用AVD約7.40 GiB | reader知識を先に統合 |
| BRAVIA | 124 files / 約470 KiB | cache約162 KiB | 共通災害試作を移植しない |

Smart LEDZの14.60 GiBにはQrio・エコキュートのAVD、Android SDK、emulator、
system imageなどの共有環境が含まれる。Smart LEDZ固有データ量として扱わない。

## SumiCoreとの主な重複

試作側の次の機能は、SumiCoreの共通機能と重複するため移植しない。

- ExecutionGate、Intent、operation state、共通retryとidempotency
- Raw envelope、品質区分、保持・圧縮・削除
- secret redaction、家庭固有IDのalias化
- 災害情報の取得、訂正、取消、freshness、判断state machine
- 共通health、circuit breaker、監査UI

各連携から移すのは、メーカー固有transport、protocol codec、reader、normalizer、
capability、error mapping、匿名fixture、失敗知見である。executorは読み取り完成後、
価値と結果確認方法が確定した能力だけに追加する。

## 連携別の結論

### SwitchBot

既存Adapter、現役DB、過去取込が正本である。別試作はOpenAPI署名、照明read-back、
人感・在室の候補、BLE知見、障害fixtureを参考にする。現在の収集と専用保存の密結合、
30秒固定HTTP timeout、機種固有normalization、成功Raw保存をレビューする。

機器は今後も増えるため、transportとmodel profileを分ける。同型機器を追加してもcodeを
複製しない。環境センサーの既存実装と、今回の照明・人感解析を混同しない。

### Smart LEDZ

SSDP、TCP framing、JSON command、Group/Scene/Schedule/Device/Sensorの知識は価値が高い。
共通Execution設計は移植せず、local readerとcodecを先に作る。Gateway設定、backup、
restore、OTA、Wi-Fi、cloud、認証変更は公開しない。

### Qrio

cloud reader、履歴、battery、firmware、Hub状態、operation jobの知識を正式化する。
非公開APIの規約確認が必要である。解錠は高リスクで、結果不明時の再送を禁止する。
専用AVDは正式Adapterに不要だが、削除は秘密状態の確認と利用者承認を別途行う。

### エコキュート

公開標準ECHONET Liteを主経路にする。実機property mapで確認した項目だけを能力化し、
Set能力はreaderと分離する。クラウドアプリ解析は補助であり、初期Adapterの依存にしない。

### Miele@home

OAuth REST/SSEのreader候補はあるが、無制限再接続loop、実SSE smoke test不足、
secret再発行が未解決である。正式化前にbounded reconnect、offline test、
read-only実測が必要である。

### WAREMA

125000 baudのUSB serial、公開protocol、位置・角度、network credential取込み知識を残す。
Stickと所有remoteの実機互換、方向、角度、技適、safety conditionが未確認である。
実物なしでexecutorを正式化しない。

### BRAVIA

Sony REST/IRCC/WoLの能力候補と仮想試験は有用である。試作内の災害判断はSumiCore共通層と
重複するため移植しない。実機のmethod/version、認証方式、standby到達性をread-onlyで
確認してからreaderを完成させる。

### 日産サクラ

公式機能は確認できたが、安定した公式開発者APIが確認できず、UI automationには規約、
端末、12V負荷、session維持の課題がある。試作bridgeを本番Adapterへ移さず、公式経路または
許容された自動化手段を確認するまで`research`とする。

### MTRL-RK-901SI

38 kHz NEC形式と操作候補は確認できたが、ボタン別codeとread-back経路がない。総当たりを
行わず、所有remoteの波形実測後に匿名fixtureを作る。トグル命令は結果不明時に再送しない。

## 実装優先度と次の合格条件

運用中の収集経路と、新しく作るreaderを同じ待ち行列へ入れない。FusionSolarとSwitchBotは
現行機能の安定化を優先し、新規連携は読み取りを完成させてから操作経路を別に審査する。

| 区分 | 優先度 | 連携 | 次の合格条件 | 操作経路 |
|---|---:|---|---|---|
| 既存運用 | 1 | FusionSolar | Modbusが連続24時間、99%以上、15分超の欠損なしを満たす | Modbus writeは作らない |
| 既存運用 | 1 | SwitchBot | 到着機器の実測schemaを確認し、機種profileと保存上限を追加する | 照明操作はcollectorへ入れない |
| 新規reader | 1 | Smart LEDZ | local transport、主要reader、normalizer、capabilityを匿名fixtureで固定する | reader完成後に能力単位で別審査 |
| 新規reader | 2 | エコキュート | 実機property mapをread-onlyで取得し、実装EPCだけを能力化する | ECHONET Setを初期公開しない |
| 新規reader | 3 | BRAVIA | allowlistした単一hostへのREST capability queryをread-onlyで確認する | WoLとIRCCを別executorにする |
| 条件待ち | 4 | Qrio | 非公開APIの利用許容性を確認し、status readerだけを固定する | 解錠は別process・単発・直前承認 |
| 条件待ち | 5 | Miele@home | credential再発行、SSEの有界再接続、offline testを完了する | 初期段階では作らない |
| 実物待ち | 6 | WAREMA | Stickとremoteの互換、passive受信、state readを確認する | 方向・角度・安全条件の確認後 |
| 実測待ち | 7 | MTRL-RK-901SI | 所有remoteの波形、ボタンcode、read-back可否を確認する | IR送信経路と能力を分離する |
| 経路待ち | 8 | 日産サクラ | 公式又は明示的に許容された通信経路を確定する | UI bridgeを正式経路にしない |

この順序は製品価値だけでなく、確認済み知識、標準protocol、結果確認の可否、誤操作時の
影響を合わせたものである。条件待ちの連携を推測で完成扱いせず、その間は次の独立した
reader又は運用改善へ進む。

## 移管・削除ゲート

各連携で次が揃うまで、元解析資産を削除しない。

1. 正式知識文書に確認済み事実、失敗、未確認、再確認条件がある。
2. 必要なメーカー固有codeをSumiCoreの契約へ差分移植した。
3. 実値を含まない最小fixtureと正常・欠損・異常・timeout testがある。
4. 版、件数、容量、可能な場合はSHA-256を移管前後で照合した。
5. secret、家庭固有ID、実Raw、認証済み画面がGitへ入っていない。
6. 公式資料URL、公開sourceのcommit/license、再調査手順が残る。
7. 利用者が削除対象、削減量、復旧可能性を確認して承認した。

削除候補はcache、build、`node_modules`、pyc、公開clone、再生成可能な逆コンパイル物、
重複APK展開物、統合済み試作、不要になった専用AVDである。.env、Keychain、実DB、
backup、現役launchdはこの削除作業へ含めない。

## 今回の安全な統合結果

2026-07-25時点で、元解析資産を移動・削除せず、次をSumiCore側へ正式化した。

- 9連携の版付き知識、根拠区分、未確認事項、再確認条件
- Smart LEDZのTCP framingとJSON message相関
- WAREMAの公開protocolに基づくframe codec
- Miele@homeのwasher-dryer状態正規化
- エコキュートのECHONET Lite frame解析
- BRAVIAのpower、volume、contentのread-only正規化とerror分類
- SwitchBotの機種profile、有界read-only retry、保存漏れ修正、正常Raw重複抑止
- 秘密や家庭固有値を含まない最小fixture
- 可逆gzip archiveの非圧縮サイズ検証

ネットワーク、認証、実API、実機操作、現役DB、backup、launchdには触れていない。
全体test 300件、Ruff、`git diff --check`は成功した。元資産の処分は
`artifact-disposition-20260725.md`の削除前ゲートと利用者の明示承認を満たすまで行わない。
