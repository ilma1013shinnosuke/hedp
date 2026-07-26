# HESTIAインターフェース

## 現在の範囲

`hedp interface`で、同じMacのブラウザから
`http://127.0.0.1:8765`を開けます。

初版は画面設計を安全に確認するためのShadow表示です。匿名の模擬値だけを返し、
現役DB、実機Adapter、ExecutionGate、外部APIには接続しません。画面上の操作も
実機へ送信しません。

## デザイン原則

Apple Human Interface GuidelinesのDesign principles、Color、Icons、
Accessibilityを基準にします。

- 情報より操作面を手前に見せ、ガラス表現はナビゲーションへ重点的に使う
- 見慣れた簡潔なアイコンを優先し、曖昧な操作には短い文字を併記する
- アイコンだけのボタンにも、支援技術向けの名前とツールチップを付ける
- 色だけで状態を伝えず、記号または状態名を必ず併記する
- 操作面は原則44ポイント以上とし、キーボードのフォーカスを見えるようにする
- OSの明暗表示と「視差効果を減らす」設定を尊重する
- 家庭内の固有情報や秘密値を、画面、URL、通常ログへ出さない

参照:

- <https://developer.apple.com/design/human-interface-guidelines/design-principles>
- <https://developer.apple.com/design/human-interface-guidelines/color>
- <https://developer.apple.com/design/human-interface-guidelines/icons>
- <https://developer.apple.com/design/human-interface-guidelines/accessibility>

## カラーパレット

| 用途 | 色 | 意味 |
|---|---|---|
| Primary Accent | `#0A84FF` | 選択、リンク、主要操作 |
| Energy Orange | `#FF9F0A` | 太陽光、発電グラフ |
| HESTIA Mint | `#00A98F` | 蓄電、環境最適化 |
| Climate Cyan | `#32ADE6` | 温湿度、空気、水 |
| Success Green | `#248A3D` | 正常、快適、確認済み |
| Attention Orange | `#C93400` | 注意、対応候補 |
| Critical Red | `#D70015` | 危険、停止、失敗 |
| Ink | `#15171A` | 明表示の主文字 |
| Background | `#EEF1F5` | 明表示の背景 |

色は意味を補助するもので、成功・警告・異常などの判定そのものには使いません。

## 太陽光グラフ

ホーム画面には当日の発電電力推移、当日発電量、自家消費率を表示します。
初版は匿名の模擬時系列です。実データ接続時はFusionSolarまたはModbusの正規化済み
観測値を読み取り、欠損区間は線で補間せず、欠損として表示します。

## 次の接続順序

1. Shadow表示とレスポンシブ表示を確認
2. 読み取り専用の現在値・時系列取得口を定義
3. 匿名fixtureで欠損、古い値、異常値を検証
4. 現役DBの複製を使わず、読み取り専用接続を短時間試験
5. 実機操作は別工程でExecutionGateを経由して接続

