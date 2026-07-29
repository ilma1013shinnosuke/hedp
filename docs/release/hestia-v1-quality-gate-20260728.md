# HESTIA v1.0 品質Gate証跡 — 2026-07-28

## 対象

- release profile: `config/release/hestia-v1.json`
- source snapshot: Philip `homecore` snapshot `364`
- 実行環境: 開発用Macの隔離されたPython仮想環境
- 実機、家庭LAN、認証、現役DB、launchd、機器設定: 変更なし

## 結果

| 検査 | 結果 |
|---|---|
| 全自動テスト | 1011件合格 |
| Ruff静的検査 | 合格 |
| Python compile | 合格 |
| Git差分形式 | 合格 |
| Philip秘密情報検査 | 合格、Critical 0、Warning 2、Info 52 |
| HESTIA release判定 | 不合格を維持 |

秘密情報検査のWarning 2件は、SwitchBot診断script内の引数名と機密項目を除外する
処理に対する保守的な検出である。秘密値は検査結果へ出力されていない。

release判定は、保証範囲、実機適格性、復旧訓練、監視、rollbackなどの未完了Gateを
正しく拒否した。自動テストと秘密情報検査の合格だけで家庭向け正式版へ昇格しない。

実機適格性の証拠は、単なるファイルの存在では合格にしない。能力ID、read-only、
設定変更なし、秘密混入なし、機器影響なし、単発・短時間・24時間の全段階、
取得件数、開始・終了時刻、要約SHA-256を構造化JSONから検査する。

全自動テストのうちWeb画面試験1件は、隔離環境がローカル通信口の作成を拒否したため、
同じsourceを通常のMac環境で再実行して合格を確認した。製品コードの失敗ではない。

## 判定

- `R8-02`: 合格。通常の開発・release候補に対する秘密情報検査があり、今回も合格した。
- `R8-09`: 部分合格。現時点のsourceに対する品質検査は合格したが、release candidate
  確定後に同じ最終Gateを再実行する必要がある。
- 家庭向け正式運用: 不可。release checkerの残るblockerを解消するまで
  `disabled`または`shadow`を維持する。

## 再実行

release candidateのsourceを確定した後、全自動テスト、Ruff、compile、差分形式、
Philip秘密情報検査、`hestia-v1` release判定を同一snapshotに対して再実行する。
