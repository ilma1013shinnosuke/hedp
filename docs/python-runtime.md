# Python実行環境

## 採用条件

HEDPはPython 3.11以上とOpenSSL 1.1.1以上を使用する。macOS付属のPython 3.9は
LibreSSL 2.8.3へ接続されており、urllib3 2系の対応条件を満たさないため、新しい
仮想環境には使用しない。目標はPython 3.12または3.13の安定版とする。

`scripts/check_python_runtime.py`は、バージョンとTLSライブラリだけを読み取り検査する。
認証情報や通信は使用しない。

## 安全な切替

1. 新しいPythonを公式インストーラー等の信頼できる配布元から導入する。
2. 現行`.venv`とは別の`.venv-next`を作り、依存関係を入れる。
3. `.venv-next/bin/python scripts/check_python_runtime.py`を実行する。
4. `.venv-next`で全テスト、ruff、wheel作成を確認する。
5. launchdを停止してから、現行`.venv`を退避し`.venv-next`を`.venv`へ切り替える。
6. 1回だけ手動収集を行い、終了コードとログを確認してlaunchdを再開する。
7. 十分な正常運転確認後に旧仮想環境を削除する。

この切替ではDB、RawData、バックアップを移動・複製しない。新Pythonの取得とlaunchd
停止・再開は、ネット接続と実運用への影響確認ができるときに行う。
