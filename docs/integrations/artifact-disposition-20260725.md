# 解析成果物の移管・処分計画（2026-07-25）

## 目的

Miele@home、Panasonicエコキュート、MTRL-RK-901SI、SwitchBot、日産サクラ、
Smart LEDZ、WAREMA WMS、Qrio、BRAVIAの解析成果を、SumiCoreで長期保守できる
最小の正本へ凝縮する。解析はどれも継続中であり、アプリ、firmware、API、機器追加に
よって知識と実装が更新されることを前提とする。

本書は各`ARTIFACT_MANIFEST`の集計と分類を監査した処分計画である。元資産の内容表示、
コピー、移動、削除、上書き、SHA-256再計算は行っていない。容量は台帳記載値であり、
論理容量と実割当容量を混同しない。

## 最終的に残す正本

各連携で長期保存するものは、原則として次の四つに限定する。

1. `docs/integrations/<vendor>/`
   - 確認済み事実、根拠区分、対応版、能力、制約、失敗例、未確認事項、再確認条件
2. `src/hedp/adapters/<vendor>/`
   - SumiCoreの現行契約へ合わせて書き直した正式実装
3. `tests/fixtures/<vendor>/`
   - 秘密、家庭固有情報、実機識別子を除いた小さな版別fixture
4. `tests/`
   - 正常、欠損、未知field、timeout、版変更、安全停止を確認するテスト

解析元の候補コードは正本ではない。必要な処理と失敗知見だけを正式実装へ移し、元の
package構造、独自Storage、独自Execution、独自policy engineをそのまま持ち込まない。
実装を作らない連携も、確認済み知識と未確認事項は正式文書へ残す。

## 継続調査を前提にした更新方法

- 各文書へ対象model、アプリ・API・protocol・firmware版、確認日、根拠区分を記録する。
- 旧知識は上書きして消さず、適用版と失効理由を残す。
- fixtureは版別に最小件数を残し、旧版と新版の両方で回帰試験する。
- 未知版や未知fieldは既知版として操作せず、隔離観測へ戻す。
- 新しいSwitchBotセンサーや電球など、同じメーカーの機器追加は共通transportを複製せず、
  機種profile、能力、fixture、テストを追加する。
- 実Rawは正式fixtureではない。匿名fixtureを作った後も、再取得不能で未解明な証拠は
  保存価値を別に判断する。

## 9系統の処分判断

| 連携 | 台帳上の規模 | 正本へ残す知識・code・fixture | 移管必須候補 | 知識統合後の削除候補 | 台帳上の容量削減見込み |
|---|---:|---|---|---|---:|
| Miele@home | 90 files、397,872 B | OAuth/REST/SSE契約、状態正規化、有限再接続、認証失効・切断fixture、read-only test | 候補source/test、履歴・監査、代表Raw。全45重複Rawは不要 | cache 51,392 B、旧launcher/README、代表以外の同一Raw | 最大279,812 B |
| エコキュート | 91 files、765,726 B。別に専用AVD約2.85 GiB | ECHONET Lite property map、reader、normalizer、安全条件、匿名schema/fixture | 正式調査、protocol/transport/controller/test、匿名化済み解析結果 | UI scaffold、補助capture、`.vinext`等。秘密候補stateは別確認 | 最低196,428 B。AVDは含めない |
| MTRL-RK-901SI | 既存解析資産0、正式文書2件 | IR候補知識、受信実測手順、toggle/absolute未確定、結果不明規則 | 引き継ぎ書と台帳。実測前はcode/fixtureなし | 現時点なし | 0 B |
| SwitchBot | 約29,857 files、約711.3 MB | 既存Adapterを正本とし、機種profile、人感・在室event、照明reader/executor、9匿名fixture、障害testを差分追加 | handover、根拠・能力・安全文書、必要なoffline lab処理、匿名fixture | `node_modules`、build/cache、再取得可能な公開clone、統合済みprototype | 約709 MB |
| 日産サクラ | 16 files、40,520 B | 公式能力と制約、API/Intent未確定、ADB試作の失敗知見、匿名UI fixture候補 | source/test/READMEは参考用。正式Adapterはtransport確定まで保留 | `.pyc`、空work、統合済み暫定selector | 23,783 B |
| Smart LEDZ | 解析project約861.1 MiB、APK import 138.6 MB。共有環境込み14.60 GiB | LAN/TCP frame、相関、能力・error、reader、限定executor、版別frame/schema fixture、実機で確認したeventual consistency | findings/protocol/decision、正式code/test、版固定XAPKのhash・manifest。未解明なら原本packageを1組だけ保留 | `.tools`、decoded/JADX、APK import重複、render、IDE/cache。native抽出物はpackageから再生成可能か確認後 | 論理容量では大。実割当量を削除直前に再測定。共有AVD/SDKは含めない |
| WAREMA WMS | 297 files、9,876,517 B | serial codec、Mock、匿名fixture、段階試験、安全条件、公開実装の根拠とlicense | 正式文書、選定したcode/test/fixture。写真は型番知識だけで足りるか確認 | cache/build 2,675,370 B、公開clone 1,746,468 B、統合済み旧研究code | 4,421,838 B以上。写真5,341,505 Bは別承認 |
| Qrio | 12,452 files、論理9.44 GiB、実割当7.41 GiB | cloud reader、event重複抑止、高リスク操作契約、timeout/結果不明、版固定fixture、プライバシー方針 | 正式文書・codeと、継続解析に必要なら版固定APK一式。専用AVDは移管しない | build、JADX、SDK/tool/cache、派生解析物。稼働中試作の撤去は別作業 | AVD外は論理1.94 GiBだが実割当約2.84 MiB。AVD約7.40 GiBは別承認 |
| BRAVIA | 124 files、481,644 B | REST能力、read-only model、DisplayIntent境界、匿名TV/災害fixture、device検証手順 | 正式文書、必要なtransport/model/test。独自災害state machineは移植しない | `pyc`、metadata、統合済みprototypeの重複部分 | 165,602 B |

### 容量の読み方

- SwitchBotの約709 MBは、主に再取得可能な依存関係とbuildであり、現時点で最も明確な
  容量削減候補である。
- WAREMA、Miele、エコキュート、サクラ、BRAVIAの明示候補を合わせると、SwitchBot以外に
  約5.1 MB以上を削減できる。
- Smart LEDZの14.60 GiBにはQrio・エコキュートAVDと共有Android SDKが含まれる。
  Qrio、エコキュート、Smart LEDZの数字を合算してはいけない。
- Qrioの1.94 GiB削除候補は多くがローカル未割当であり、実際に増える空き容量は台帳時点で
  約2.84 MiBである。専用AVDの削除なら約7.40 GiBの実容量を解放できるが、認証状態や
  未回収知見があり得るため、この計画の通常削除には含めない。
- Smart LEDZの`.tools`、decoded/JADX、APK importには論理容量と実割当量の差があり得る。
  削除前に`du`と論理サイズを別々に確認し、解放容量を過大に見積もらない。

## 連携別の重要な保留条件

### Miele@home

正式Adapterはread-onlyとする。無制限再接続を廃止し、回数、総時間、backoff、queueへ
上限を設ける。実SSE、offline test、lintを確認するまで候補codeを本番扱いしない。
代表Rawを匿名fixtureへ変換した後、同一hashのRaw群は削除候補にできる。

### エコキュート

ECHONET Liteを主経路とし、クラウド試作とUIは正本にしない。reader完成前にSet能力を
公開しない。property map、未知EPC、decode失敗、操作read-back不一致の証拠を優先する。

### MTRL-RK-901SI

所有remoteを複数回受信してcode、timing、repeat、toggle/absoluteを確認するまでは、
正式Adapterもfixtureも作らない。第三者codeや総当たり結果を正本へ入れない。

### SwitchBot

`src/hedp/adapters/switchbot/`と現役DBを正本とし、別試作で置換しない。追加製品は機種profile
として増やす。温度、湿度、CO2の既存成果を別解析で上書きしない。照明操作はreaderから
分離し、ExecutionGate完成前に収集serviceへ追加しない。

### 日産サクラ

安定した許容transportが未確定である。公式API、公式App Intent、許容されたUI automationの
いずれかが確定するまで正式codeを作らない。暫定ADB selectorは知見としてのみ残す。

### Smart LEDZ

解析は継続中なので、確認済み知識へ凝縮した後も、現在版の再解析に必要な最小原本を
1組だけ残す。候補はXAPK/APK、split、manifest、hash一覧であり、decoded、JADX、APK import
は派生物として再生成可能にする。backup、restore、OTA、network、初期化、機器登録変更は
通常Adapterへ入れない。

### WAREMA WMS

公開実装は第三者根拠であり、所有Stickとremoteの実測ではない。URL、commit、license、
抽出したprotocol知識を残した後、公開cloneは再取得可能な削除候補にする。写真は型番知識が
正式文書へ残れば通常は不要だが、原本が再取得不能なので利用者承認まで削除しない。

### Qrio

住居の物理セキュリティを扱うため、初期統合はreader-onlyとする。版固定APKは非公開APIの
再検証根拠として保持価値がある。解錠executor、稼働中Qrio Local、専用AVDの撤去は別々の
高リスク作業とし、本計画から自動実行しない。

### BRAVIA

テレビ固有のtransport、capability、read-backだけを移す。試作内の災害情報取得、訂正、
取消、地域・期限判断はSumiCore共通層と重複するため移植しない。視聴内容は既定で
長期保存しない。

## 秘密情報・家庭固有情報

次は正式知識、code、fixtureへコピーしない。

- ID、password、token、cookie、session、API key、暗号鍵
- 家庭内address、SSID、MAC、実機serial、device ID、room名
- 認証済み画面、実通信Raw、入退室・視聴・車両位置などの高プライバシー情報

連携別の注意対象:

| 連携 | 注意対象 | 方針 |
|---|---|---|
| Miele@home | 旧`.env`、実Raw、過去に露出した可能性のあるcredential | 移動・表示しない。正式保管先へ再設定し、必要なcredentialを更新 |
| エコキュート | hosting/wrangler state、専用AVD | 正式Adapterへ移さない。削除は別確認 |
| SwitchBot | `.env.local`、wrangler state | 値を移さず正式secret storeへ再設定 |
| Smart LEDZ | Logcat、家庭固有finding、AVD、関連runtime cache | 必要性が確認された原本だけrestricted。通常Git禁止 |
| WAREMA | 利用者写真4件 | 内容を表示せず、知識で代替できるか利用者確認 |
| Qrio | `.env`、runtime log、専用AVD、認証状態 | 移動・hash・表示を行わない。削除も別承認 |
| 日産サクラ | 共有AVD、Keychain、認証済み公式アプリ | 調査成果物として移管しない |
| MTRL-RK-901SI | 現時点では該当なし | 将来fixtureへ実codeや機器IDを入れない |
| BRAVIA | 台帳上は該当なし | 移管時にも再監査し、認証値や家庭内addressを追加しない |

## AVD・Android SDK・共有tool

- Android SDK、emulator、system imageは共有開発環境であり、連携成果物ではない。
- AVDは仮想端末のuserdata、認証状態、token、KeyStore、snapshot、アプリDBを含み得る。
- AVDと共有SDKを`runtime/research`へコピーまたは移動しない。
- Qrio用AVDとエコキュート用AVDは、該当連携の未確認事項がAVDにしか残っていないかを
  確認し、必要な知識を正式化し、認証情報の失効・再設定方針を決めてから個別承認で削除する。
- SDK、emulator、system imageは再取得可能だが、他のAndroid解析が続く間は残す。
- 複数台帳が同じAVD/SDKを参照しているため、容量集計では一度だけ数える。

## 削除前ゲート

解析元、候補code、cache、AVDを削除する前に、対象ごとに次をすべて満たす。

1. 削除対象を絶対path、件数、論理容量、実割当容量で確定した。
2. 確認済み事実、失敗理由、未確認事項、対応版、再確認条件が正式文書へ残っている。
3. 必要な処理が正式Adapterへ選択統合され、読み取りと操作が分離されている。
4. 正常・欠損・未知版・timeout・安全停止を再現する最小匿名fixtureとテストがある。
5. fixtureとGit管理ファイルへ秘密、家庭固有情報、実Rawが混入していない。
6. 全test、静的検査、差分検査が成功し、候補codeだけに依存する知識が残っていない。
7. 継続解析に必要な版固定原本を一つだけ選び、派生物と区別した。
8. 再取得不能な原本は、削除する合理性と失われる検証能力を説明できる。
9. `.env`、Keychain、credentialは安全な正本へ再設定され、露出した可能性がある値は更新した。
10. 稼働中process、launchd、現役DB、現役Adapterが削除対象を参照していない。
11. 通常ファイルは移管前後の件数、容量、可能なSHA-256が一致した。秘密候補やAVDは
    内容読取りやhashをせず、別の確認方法を採用した。
12. 重要で再取得不能な原本には、必要なら暗号化した別障害領域の複製がある。
13. 削除後の回復方法と、再ダウンロード・再解析に必要な条件を記録した。
14. 利用者へ削除対象、影響、解放見込み容量、回復可否を提示し、明示承認を得た。

削除はcache、再取得可能物、派生解析物、再取得不能物、AVD、稼働中試作を混ぜず、
種類ごとに分けて実行する。完了後は、削除したpath、件数、実際に増えた空き容量、
残した正本、復元方法を小さな処分記録として残す。

## 実行順

1. 各連携の正式知識を現行READMEから必要に応じて`research.md`、`capabilities.md`へ分割する。
2. 未確認事項と再確認条件を版情報付きで確定する。
3. 実装可能な連携だけ、候補codeをSumiCore契約へ差分移植する。
4. 匿名fixtureとtestを作り、秘密非混入と回帰を確認する。
5. 継続解析に必要な版固定原本を選ぶ。
6. 移管必須候補と削除候補を絶対path単位の実行リストへ落とす。
7. 最初に再生成可能cacheを処分候補として提示する。
8. 次に依存関係、公開clone、decoded/JADX等を提示する。
9. 最後に実Raw、写真、版固定package、AVD、稼働中試作を個別判断する。

この順序では、容量を減らすために知識を先に失わず、同時に「解析資産を永久保存する」
ことも避けられる。
