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
5. launchdを停止して現行`.venv`を退避し、最終名`.venv`を新規作成して検証済みwheelを
   通常installする。`.venv-next`は絶対pathを持つためrenameしない。
6. 1回だけ手動収集を行い、終了コードとログを確認してlaunchdを再開する。
7. 十分な正常運転確認後に旧仮想環境を削除する。

この切替ではDB、RawData、バックアップを移動・複製しない。新Pythonの取得とlaunchd
停止・再開は、ネット接続と実運用への影響確認ができるときに行う。

## Python 3.13でのインストール方式

Python 3.13.14は先頭が`__`の隠し`.pth`を読み飛ばす。setuptoolsのeditable installが
`__editable__.*.pth`を生成する組み合わせでは、install成功後もpackageをimportできない。
SumiCoreは本番と検証の差を減らすため、`.venv-next`へ通常wheel形式で導入する。

```console
.venv-next/bin/python -m pip install .
.venv-next/bin/python -m pip install pytest ruff
```

ソース更新後は`.venv-next/bin/python -m pip install --no-deps .`でSumiCore本体だけを
再導入する。`hedp`と`sumicore`の両CLI、両package import、wheel内容を切替前に検査する。

```console
.venv-next/bin/python scripts/check_installed_package.py
```

この検査はリポジトリ外の一時ディレクトリからisolated modeでimportし、両packageが
`site-packages`の通常wheelから読み込まれること、editable markerがないこと、両CLIの
shebangが現在のPython絶対パスと一致すること、依存関係が満たされることを確認する。
