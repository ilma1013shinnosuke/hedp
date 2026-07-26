# Adapter横断レビュー（2026-07-27）

## 結論

Adapter本体は概ねPython標準機能とHTTP/TCP/UDP/SQLiteで構成され、macOS固有APIへの
直接依存はない。一方、本番候補にする前に解消すべき境界上の課題がある。

1. 読み取り用package rootから操作APIを公開しない。
2. 操作は共通Execution Coordinatorだけを将来の入口とし、Adapterの直接実行を本番へ
   配線しない。
3. 取得周期と保存粒度を別の設定として扱う。
4. 同じ離散状態を観測のたびに履歴へ追記しない。
5. 実機read-only確認は、対象固定、総時間・要求数・応答量の上限、非保存、匿名集計を
   同時に満たす専用harnessからだけ実施する。

このレビューでは実API、実機、現役DB、launchd、家庭LAN、認証設定を変更していない。

## Adapter別の現状

| Adapter | 読み取り | 操作 | 主な未完了 |
|---|---|---|---|
| FusionSolar / SmartLogger | cloud Readerとread-only Modbus部品あり | fixture限定の操作契約 | Modbusの機器同一性照合、cloud Readerのendpoint allowlist、並行取得の終了期限、同一snapshot抑止 |
| SwitchBot | cloud取得とSQLite保存あり | 型付き操作契約あり | ReaderとDBの分離、poll無効化の実効性、同一状態の履歴抑止、共通Execution経由の強制 |
| Smart LEDZ | TCP Reader、正規化、通知契約あり | 別moduleの操作契約 | 対象固定、総要求数・応答byte上限を持つ実機適格性確認 |
| エコキュート | ECHONET Lite Get Readerあり | Set transportと操作Adapterは別module | 単一IP固定、全体deadline、実機property map確認。操作は本番未配線 |
| Qrio | cloud Reader、匿名正規化あり | 別moduleの操作Adapter | 非公開cloud仕様の継続性、実機read-only確認。操作は本番未配線 |
| Miele@home | HTTP/SSE Readerあり | dry-run gateのみ | OAuth/SSE実機read-only確認、共通Executionへの将来統合 |
| BRAVIA | 正規化とread modelあり | dry-run plannerのみ | allowlist済みread transport、実機能力確認 |
| 日産サクラ | 状態modelあり | dry-run plannerのみ | 正式Reader、利用規約と認証方式の確認 |
| WAREMA | protocol parserのみ | なし | 実Reader、対象同一性、取得・保存契約 |

## 読み取りと操作の境界

第1層はread-onlyのReader、Collector、Normalizerだけを利用する。第4層は操作専用moduleを
直接呼ばず、将来も次の経路だけを利用する。

```text
第3層のIntent
  -> ExecutionGate
  -> 単一対象・単一送信
  -> read-back
  -> Outcome
  -> 監査
```

Adapter側のGateは、メーカー固有能力や応答を型へ変換するための補助であり、共通
ExecutionGateを置き換えない。Adapterの公開rootはread側だけとし、操作型は
`hedp.adapters.<name>.operation`から明示的にimportする。これは互換性より安全な境界を
優先する、正式運用前のAPI整理である。

現段階の操作実装はfixtureまたはdry-runに限定する。永続的なoperation claim、再起動後の
未完了状態、共通監査、実機read-backが揃うまで本番transportを接続しない。

## 取得頻度と保存粒度

取得頻度は第1層の設定、保存粒度は第2層のdata dictionaryで決める。同じ数値へ統一しない。
実機適格性確認で負荷・変化頻度・欠損回復を測定した後、設定値を更新できる構造にする。

| 情報型 | 取得 | 長期保存 |
|---|---|---|
| 温湿度・電力など連続値 | 機器固有周期または有限poll | 短期詳細 + 時間・日集約。急変eventは秒精度 |
| 鍵・照明・運転状態など離散値 | event/push優先 + 低頻度照合 | 変化eventと状態区間。同一状態を毎回保存しない |
| scene、schedule、property map、能力定義 | 起動時、再接続時、変更検知時、低頻度照合 | version/hashが変化した時だけ正本を追加 |
| battery、firmware、接続health | 影響に応じた低頻度poll | 変化event、異常区間、日次または時間集約 |
| 解析不能・想定外Raw | 発生時 | byte・件数・期間上限付き隔離。本文を通常logへ出さない |

pushが存在しても、それだけを現在状態の唯一の根拠にしない。再接続後、画面表示時、低頻度
照合のいずれかでread-only snapshotを取得し、取りこぼしから回復する。

## OS非依存性

CoreとAdapterはPython 3.11以上でmacOS、Linux、Windowsのいずれでも動く構造を維持する。
scheduler、サービス管理、秘密注入、firewall設定は交換可能なOS境界とする。

- `launchd`は配備用実装であり、Adapterから参照しない。
- Linuxではsystemd等、WindowsではTask Scheduler等を別rendererとして扱う。
- hostnameやmDNSはOS差があるため、実機probeでは解決済みprivate IPを一回だけ固定する。
- ECHONET LiteのUDP応答はOS firewall差を適格性確認する。
- WindowsでIANA timezone databaseがない環境のため、`tzdata`を条件付き依存とする。
- POSIX modeだけを秘密保護の根拠にせず、OS別ACLまたは将来の暗号化正本を利用する。

## read-only実機確認の入口

既存の通常Collectorや定期jobを初回probeとして利用しない。専用入口は少なくとも次を
満たさなければならない。

- profileから一意な対象を解決し、IP、port、serial、機器IDを引数・標準出力へ出さない。
- private/link-localの単一IPへ固定し、discovery、broadcast、再解決を行わない。
- Adapter別の最大要求数、総wall-clock deadline、最大応答byteを同時に制限する。
- retryは0を既定とし、DB・fixture・logへRawを保存しない。
- 出力はAdapter名、成否、要求数、所要時間区分、quality件数、同一性照合結果だけにする。
- 例外は安全なreason codeへ変換し、接続先やpayloadを含めない。

現行コードのまま全条件を満たすCLIはない。このため、安全な専用入口が完成するまで
実通信を行わない判断が適切である。

## 優先修正

1. SwitchBotの非dry-run dispatchをfixture以外では拒否する。
2. 全package rootから操作APIを外し、横断回帰試験で境界を固定する。
3. 共通read-only qualification harnessを単発・短時間・24時間で共用する。
4. FusionSolar Modbusで、値を保存・表示せず期待機器identityを照合する。
5. SwitchBot ReaderからSQLite transactionを分離し、poll対象のenabled設定を実効化する。
6. SwitchBotとFusionSolarへstate interval、変化event、Raw上限、parallel終了期限を導入する。
7. LinuxとWindowsでoffline testを実行し、実LAN確認は各OSのfirewall条件を別に記録する。
