# SumiCore切替後24時間監視

## 安全境界

検査器は秘密値を含まない入力JSONだけを読み、DB、API、launchd、`.env`へ直接アクセスしない。
状態収集時も機器ID、認証情報、Raw本文、絶対パスをJSONへ入れない。

## 判定

- 24時間未満と観察途中の回数不足は`warn`
- 24時間後の回数不足、収集失敗、二重起動、秘密値混入、DB異常は`fail`
- `fail`時は旧環境を削除せず、安全切替手順の復旧判断へ進む

入力には、タイムゾーン付きの開始・確認時刻、DB整合性と開始・終了Raw件数、4つの安全条件、
各jobの期待・成功・失敗回数を記載する。`PYTHONPATH=src python scripts/check_post_cutover.py 状態.json`
で人向け表示、`--json`で機械向け表示にする。終了コードは合格・警告が0、失敗が1、入力不正が2。

明示的に確認した非秘密情報をJSONへまとめた後、mode 0600の監視入力を作成できる。

```console
PYTHONPATH=src python scripts/create_post_cutover_snapshot.py facts.json snapshot.json
PYTHONPATH=src python scripts/check_post_cutover.py snapshot.json --json
```

作成処理は値を推測しない。認証情報、機器ID、API応答、Raw本文、ログ本文を含めない。

## チェックリスト

- [ ] 切替直後：旧job停止、新job一回実行、開始件数を記録
- [ ] 15分後：5分系が連続成功し、二重実行がない
- [ ] 2時間後：SwitchBotを含む時間系収集が成功している
- [ ] 翌日04:10後：日次健全性確認が完了している
- [ ] 24時間後：状態JSONを作り、本検査が`PASS`になる
- [ ] 旧環境の削除は別承認まで行わない
