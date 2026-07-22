# SumiCore安全切替手順

## 現在地点

- 稼働中の正本は`main`と`com.hedp.*`のlaunchd jobである。
- 移行コードは`codex/offline-modernization`だけにあり、稼働中のDBとRawDataへ未反映である。
- `.env`はGit管理外、権限0600で、家庭固有の実行設定を集約済みである。値は表示しない。
- 既存の5つのlaunchd plistは権限0600である。
- 家庭固有設定の安全な移行手順と検査コードは実装済みだが、現役plistの再生成は未実施である。
- 稼働中の仮想環境は編集可能installのため、`main`の変更は定期処理へ直ちに影響し得る。
- DB、RawData、backupは切替準備で移動、複製、削除しない。

## 承認単位

### A. Python導入

macOSへ公式Pythonを導入し、別の`.venv-next`を作る。`/Library/Frameworks`と
`/usr/local/bin`、リポジトリ内の仮想環境を変更する。DB、実API、launchdは変更しない。
署名検査が正常になるまでは実行しない。

### B. 家庭固有設定の移行

既存plistと確認済みコードから必要値を、値を表示せず`.env`、`config/local/`、新plistへ
移す。対象ファイルは0600とし、Gitへ追加しない。FusionSolar認証情報も新plistへ保存される。

### C. アプリケーション切替

旧launchd jobを停止し、移行ブランチを`main`へmerge commitとして統合する。仮想環境と
launchd labelをSumiCore版へ切り替え、実APIへの手動収集を1回実行する。この確認では
FusionSolarとSwitchBotへ通信し、正常応答は現役DBへ追加される。

### D. GAS配備

Apps Script、Script Properties、専用Driveフォルダ、日次triggerを作る。FusionSolarへ
2種類の実リクエストを行い、前日分のRaw JSONをDriveへ最大2件作成する。ローカルDBは
配備確認では変更しない。Mac側の取込コードは完成しているが、最初の実取込は別途DB変更の
対象と影響を確認してから行う。Driveファイルを自動削除しない。

### E. リポジトリとローカルパスの改名

GitHubリポジトリ名とローカルディレクトリを最後に変更し、remoteとlaunchdの絶対パスを
更新する。収集が安定するまで実施しない。

### F. DB・ログ名の改名

全収集停止中に同じディスク内で移動し、コピーしない。新旧名称の同時変更は行わず、
リポジトリ改名とは別日に実施する。

## 切替前検査

最初に、秘密値を出力せずGit・`.env`権限・設定項目名・空き容量・Python/TLSを確認する。

```console
PYTHONPATH=src python scripts/check_release_readiness.py cutover . --env .env
```

この検査はDB、実API、launchdを読み書きしない。failを解消してから以下へ進む。

1. 安定した電源とネット接続、9 GiB以上の空き容量を確認する。
2. `main`と移行ブランチがcleanで、リモートへ退避済みであることを確認する。
3. `.env`、`config/local/`、全plistが0600でGit管理外であることを確認する。
4. 必須設定の項目名だけを検査し、値を画面やログへ出さない。
5. `.venv-next`でPython/TLS検査、全pytest、ruff、shell、GAS構文、wheel内容を確認する。
6. 現役DBの件数、最新時刻、健全性結果を読み取り専用で記録する。
7. merge commitの直前commitと旧launchd plistの存在を確認する。

## 切替順序

1. DB共通lockが空いていることを確認し、旧launchd jobを停止する。
2. 旧jobが新たに起動しないことを確認する。
3. 家庭固有設定を移し、権限、必須項目、Git管理外を再確認する。
4. 移行ブランチを`main`へmerge commitとして統合する。
5. 旧`.venv`を一時退避し、Python 3.13で最終名`.venv`を新規作成して、検証済みwheelを
   通常installする。`.venv-next`の単純renameはCLI shebangに古い絶対パスを残すため行わない。
6. SumiCore plistを構文検査して登録する。登録・起動失敗時は共通処理で旧jobを復旧する。
7. 日次以外の各収集を1回だけ手動実行し、終了コードと秘密値不在のログを確認する。
8. DB件数とRaw増分が実行回数と一致することを読み取り確認する。
9. 次回の5分収集と1時間収集を確認し、その後に日次jobを有効化する。
10. 04:10健全性確認を通過後、24時間は旧環境と旧plistを削除しない。
11. 保存した状態JSONを`scripts/check_post_cutover.py`で確認し、24時間後にfailがないことを確認する。

## 失敗時の復旧

1. `com.sumicore.*`を停止する。
2. 切替済みjobだけでなく全`com.sumicore.*`が停止したことを確認する。個別切替の途中失敗で
   新旧jobを混在させない。
3. merge commitを`git revert -m 1`で取り消し、旧ソースへ戻す。
4. 新しい`.venv`を退避し、元の`.venv`を同一ディスク内で現役名へ戻す。
5. 全`com.hedp.*` plistを再登録し、各labelが読み込まれたことを確認する。
6. 1回収集と次回自動収集を確認する。DBへ追加済みの正常Rawは削除しない。
7. 重複や不完全データは別の監査タスクで扱い、復旧理由、失敗段階、終了コードを
   秘密値なしで記録する。

## 完了条件

- 全SumiCore jobが予定時刻で動き、旧jobとの二重実行がない。
- pytest、ruff、shell、GAS構文、日次健全性確認が合格する。
- DB件数とRaw増分が説明でき、秘密値がGit、通常ログ、回答へ出ていない。
- 24時間の正常運転後も旧環境削除は別承認とする。
