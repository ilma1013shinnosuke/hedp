# 新名称と安全な改名

## 名称の条件

新名称はエネルギーに限定せず、家庭の情報収集、蓄積、判断、操作を扱えることを表す。
日本語で読みやすく、短く入力でき、機器メーカー名を含まず、単一機能に見えないことを
必須条件とする。商標、主要ドメイン、GitHub、PyPI、アプリストア、既存HEMS製品との衝突は
ネット接続時に確認する。衝突確認前は名称を確定しない。

## 決定した名称

内部プロジェクト名は **SumiCore（スミコア）** とする。「住み」と「Core」を組み合わせ、
エネルギーだけでなく、住まいの事実、履歴、判断、操作を支える中核という意味を持たせる。
技術識別子は`sumicore`、環境変数prefixは将来`SUMICORE_`とする。

初期候補のHOMIは既存スマートホーム製品、HIOS/HomeOSは既存住宅OS、HIOPは既存データ
platform、LIOPは既存Python package・企業商標・software protocolとの衝突が確認された
ため採用しない。調査先には次を含む。

- https://www.homismart.com/
- https://www.homeos.com/
- https://www.hiop.io/
- https://pypi.org/project/liop/
- https://www.liop.com/

2026-07-22の一般Web・PyPI・npm検索では、SumiCoreと同一の主要smart-home softwareは
確認できなかった。ただし、これは法的な商標利用可能性を保証しない。外部販売、法人利用、
ドメイン取得、アプリ公開の前にはJ-PlatPat等で正式な類似商標調査を行う。

## 名前を二段階に分ける

画面・文書で使う製品名と、Python package、環境変数、launchd labelなどの技術識別子を
分ける。最初に製品名だけを変更し、技術識別子`hedp`と`HEDP_`には互換期間を設ける。
一度に全名称を変えて定期収集の復旧手段を失わない。

## 改名対象

| 区分 | 現在 | 移行方針 |
|---|---|---|
| 表示名 | HEDP | SumiCoreへ変更 |
| Gitリポジトリ | `hedp` | `sumicore`へGitHub確認後、最後に変更 |
| Python配布名・import | `hedp` | `sumicore` alias追加後に段階移行 |
| CLI | `hedp` | `sumicore`を追加し、新旧を一時併存 |
| 環境変数 | `HEDP_*` | `SUMICORE_*`優先、旧prefixをfallback |
| SQLite | `hedp.db` | 収集停止中に同一ディスク移動、コピーしない |
| backup名 | `hedp-*` | 旧名も健全性確認対象に残す |
| launchd | `com.hedp.*` | 新job確認後に旧jobを停止 |
| ログ | `~/Library/Logs/hedp` | 新旧読取期間を設ける |
| lock | `/tmp/com.hedp.*` | 全job同時切替で二重実行を防止 |
| ローカルパス | `/Users/shinnosuke/hedp` | GitHub・launchd切替後に変更 |

## 実施順序

1. 04:10健全性確認と収集再開が正常な基準状態を確定する。
2. 名称衝突を調査し、表示名と技術識別子を決定する。
3. 新CLI・新環境変数へ互換aliasを追加し、旧名で全テストを通す。
4. 新launchd plistを生成し、値を表示せず構文と権限を検査する。
5. 旧job停止、新job登録・起動・状態確認を連続して行う。
6. 新jobの登録または起動に失敗した場合は共通切替処理が旧jobを自動復旧する。
7. DBとログの名称変更は別日に行い、DBは複製せず同一ディスク内で移動する。
8. GitHubリポジトリとローカルパスを最後に変更し、remoteとlaunchdの絶対パスを更新する。
9. 互換期間終了後に旧CLI・環境変数を削除する。

各段階でpytest、ruff、shell構文、wheel内容、launchd状態、DB件数、Raw増分、ログの秘密値
不在を確認する。改名作業をGAS導入やDB schema変更と同時には実施しない。
