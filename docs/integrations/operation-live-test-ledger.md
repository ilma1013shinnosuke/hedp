# 操作用Adapter 実機試験台帳

## 位置付け

本書は[操作用Adapter 適格性確認計画](operation-qualification-plan.md)に従い、
機器・能力ごとの現在段階と、次に承認を得る単発試験だけを管理する台帳である。
共通Execution契約は[Execution層 共通契約](../execution-contract.md)を正本とし、
本書を実機操作、常駐化、設定変更の包括承認には使用しない。

実機へ送信する前に、試験ごとに次の5項目を利用者へ提示し、その試験だけの明示承認を得る。

1. 対象
2. 送信する正確な命令
3. 物理的・運用上の影響
4. 結果の確認方法
5. 原状復帰方法

原状復帰も別の書き込み操作である。前進操作の成功を読み戻しで確認できた場合だけ、
事前に承認された復元命令を送る。結果不明時は逆命令を自動送信せず、読み取りと利用者確認へ戻る。

## 現在の共通判定

- Stage 0の匿名fixture・dry-run・Shadow Modeは継続可能。
- 現在、実機へ接続済みの共通Execution経路はない。全能力を実機試験前として扱う。
- Readerが未合格、状態が`stale`、`missing`、`invalid`、`unknown`、対象能力が未確認の場合は送信しない。
- 一Intentにつき書き込みは最大一回。timeout、通信断、結果不明を理由に再送しない。
- 実機設定、登録、firmware、network、認証、保守設定は本台帳の対象外とする。

## 試験順と現在段階

| 順位 | 対象・能力 | 現在段階 | 最初の単発命令候補 | 影響と事前条件 | 結果確認・原状復帰 | 中止条件 |
|---:|---|---|---|---|---|---|
| 0 | 全機器 | Stage 0 | dry-run／Shadowのみ | 物理影響なし | `would_dispatch`、`would_block`、`indeterminate`を確認 | 意図しないtransport呼出し |
| 1 | SwitchBot E26／テープライト3 | Stage 0 | `SET_BRIGHTNESS`の絶対値 | 小さな明るさ変化。deviceType、電源、明るさがfresh/good | 状態を読み戻し、確認済みの元の絶対値へ戻す | 未知deviceType、stale、状態不一致、結果不明 |
| 2 | BRAVIA | Stage 0 | `MUTE`の明示値 | 消音切替。TV稼働中で視聴を妨げない時間 | mute状態を読み戻し、元の明示値へ戻す | live transport未接続、状態取得不能 |
| 3 | Smart LEDZ | Stage 0 | 一室の`scene_run` | 一室の照明シーン変更。元シーンを事前取得 | 上限付き待機後にsceneを読み戻し、元シーンへ戻す | `schedule_select`、元シーン不明、不一致、unknown |
| 4 | SwitchBot掃除機 | Stage 0 | `DOCK` | 走行を伴う。床面・充電台・現在状態を確認 | working/charging/task状態を読み戻す | 機種不明、障害物、状態不一致 |
| 5 | BRAVIA | Stage 0 | 音量、入力、channel、app、power、Wake-on-LANを一能力ずつ | 音・画面・電源の変化 | 各状態を読み戻し、以前の絶対状態へ戻す | 能力未確認、live transport未接続 |
| 6 | 日産サクラ空調 | Stage 0 | 空調開始または温度指定を一能力ずつ | 駐車中の空調と電池消費。停止・無人・電池余裕が必要 | 空調状態・設定温度を読み戻し、元状態へ戻す | 車両状態不明、結果不明、復旧経路不明 |
| 7 | Miele | Stage 0 | `START_SCHEDULED_PROGRAM` | 水・電気・熱・機械動作を開始 | program IDと運転状態を読み戻す | 停止・取消経路と安全な試験条件が未確認の間は禁止 |
| 8 | エコキュート許可設定 | Stage 0 | `DAYTIME_BOOST_ALLOW`または`DENY` | 沸き上げ許可状態の変更 | 最新property map、対応EPC、事前値を確認し読み戻す | 凍結・衛生・安全制御への影響、map不一致 |
| 9 | エコキュート沸き増し | Stage 0 | `BOOST_START`または`BOOST_STOP`を別試験で | 加熱と電力消費 | 対応EPCと実際の沸き上げ状態を確認 | typed live dispatch未接続、結果不明 |
| 10 | エコキュート風呂自動 | Stage 0 | `BATH_AUTO_ON`または`OFF`を別試験で | 浴槽への給湯、水量、温度へ影響 | 対応EPCと浴槽を物理確認 | 利用者不在、property map未確認 |
| 11 | 日産サクラ充電・施錠 | Stage 0 | `START_CHARGING`または`LOCK`を別試験で | 充電または車両securityへ作用 | 充電・施錠状態を読み戻す | 充電停止経路不明、`UNLOCK`は未対応 |
| 12 | Qrio | Stage 0 | `LOCK`または`UNLOCK`を毎回別承認 | 住居securityへ直接作用。利用者が扉前で物理鍵を保持 | vendor job完了と鍵状態を分けて確認し、最後に物理確認 | timeout時再送禁止、対象・最新状態不明 |
| 13 | FusionSolar／SmartLogger | Stage 0 | 発電停止、充電、放電をそれぞれ別試験で | 発電・蓄電池へ高影響 | 発電状態、蓄電池mode、電力値を読み戻す | 再開・終了条件、電力・時間上限が未定義の間は禁止 |

## Adapter別の既知の境界

- SwitchBot照明・掃除機、FusionSolarはfixture明示のないoperation transportを拒否する。
- Smart LEDZ、BRAVIA、Miele、日産サクラはlive dispatchを公開していない。
- Smart LEDZのschedule選択は未検証であり、実機試験候補にしない。
- 日産サクラの解錠は未対応であり、実機試験候補にしない。
- Mieleは開始後の停止・取消経路が未定義のため、単発試験へ進めない。
- エコキュートの低水準Setを直接呼ばず、typed requestと共通Executionを経由させる。
- Qrioのwrite portは、永続registryと共通Executionへの接続完了まで実機へ使わない。

## 結果の記録方法

実機試験を行う場合は、秘密値と家庭固有情報を除き、次だけを追記する。

- 日時、匿名対象、能力、試験段階
- 承認された命令の意味と期限
- 事前状態の品質・鮮度
- Gate判定、送信受付、読み戻し、最終outcome
- 反映時間、確認回数、結果不明の有無
- 原状復帰結果または手動復旧結果
- 中止理由、次回へ持ち越す未確認事項

認証header、endpoint、IP、MAC、機器ID、車両識別子、入退室履歴、実通信Rawは記録しない。
