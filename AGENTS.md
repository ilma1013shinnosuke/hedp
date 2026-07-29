# AI作業規則（HESTIA）

## 適用範囲
この文書は、HESTIAリポジトリ内で作業するAIの短い入口である。

## 作業前に読む文書
1. `PROJECT.md` — プロジェクトの目的と設計方針
2. `SPECIFICATION.md` — 維持すべき仕様
3. `governance/AI_DEVELOPMENT_PLAYBOOK.md` — 全プロジェクト共通の正式方針
4. `governance/AI_DEVELOPMENT_PLAYBOOK_COMPACT.md` — AI実行用の要約
5. `HEDP_CODEX_CONTEXT.md` — ローカル機密文書。外部AIへ送らない
6. ユーザーの明示指示と当該Task Contract

## 優先順位
1. 住宅・電気・設備・個人情報の安全、法令、本人の意思
2. その範囲内でのユーザーの明示指示
3. HESTIA固有の`HEDP_CODEX_CONTEXT.md`、`PROJECT.md`、`SPECIFICATION.md`
4. AI Development Playbook正式版
5. Compact版
6. 個別タスク上の推奨事項

矛盾がある場合は、安全側に停止して報告する。

## 必須動作
- 作業開始時にrepository root、branch、`git status --short`を確認する。
- 既存の未コミット・未追跡ファイルをユーザーの作業として保全する。
- `HEDP_CODEX_CONTEXT.md`はローカル機密文書として扱い、Geminiなど外部AIのcontextへ読み込ませない。外部AIには`PROJECT.md`、`SPECIFICATION.md`と匿名化した必要Evidenceだけを渡す。
- `.env`、秘密値、launchd内の認証情報を表示・複製・Git追加しない。
- `hedp.db`、backups、稼働中データ、実機、家庭LAN、外部APIへ、明示承認なしに書き込まない。
- 欠測、`null`、`--`、`-`、未観測値をゼロに変換しない。推測したendpoint、単位、device ID、符号を実装しない。
- 変更は小さく、検証可能で、rollback可能な単位に限定する。
- 住宅設備の制御、安全規則、DB、認証、外部通信、データ補正は高保証経路として扱う。
- scheduled runtimeへAI依存を持ち込まない。
- commit、push、release、deployment、外部書込み、実機操作は、明示的な承認がある場合だけ行う。
- 完了時は、変更、テスト、既存データ・安全への影響、残存リスク、rollbackを簡潔に報告する。
