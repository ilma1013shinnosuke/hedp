# FusionSolar Modbus TCP切替・旧方式廃止基準

## 方針

SmartLogger経由のModbus TCPを、太陽光・蓄電池の現在値収集の主経路とする。
インターネット、クラウド認証、CAPTCHAに依存しないため、家庭LAN内の常時収集に
適している。書き込み機能は実装せず、Function Code 3/4の読取りだけを許可する。

旧FusionSolarクラウド方式は直ちに削除しない。Modbusと並行運転し、下記の合格条件を
満たしてから、定期実行、コード、秘密情報の順に段階廃止する。

## Modbus本番合格条件

- 7日間以上の連続観測
- 5分周期の成功率が99%以上
- 15分を超える欠損がない
- Mac再起動、ネットワーク再接続後に自動復旧する
- RawData 1件から確認済み10指標を再生成できる
- 発電電力、当日発電量、蓄電池SOCをクラウド値または機器画面と比較し、
  単位・桁・時刻が整合する
- CAPTCHAやインターネット停止中もModbusだけは継続する
- DBロック、タイムアウト、ログ容量に異常がない

## 段階的な廃止手順

1. Modbusを既存5分ジョブの先頭で収集する。
2. 7日間はクラウド現在値収集も残し、比較材料を蓄積する。
3. 合格後、クラウドのdevice-realtime、Battery DC、current alarm定期取得を停止する。
4. 日次履歴などModbusで代替できない機能は、必要性を個別判定する。
5. 旧Collectorの確認済みendpoint、request/response shape、失敗条件、CAPTCHA挙動を
   文書と匿名fixtureに残す。
6. 旧コードをGit履歴で復元できる状態にして削除する。
7. 不要になったクラウド認証情報をlaunchd plistから除去する。

## 削除しないもの

- 既に保存済みのクラウドRawDataとRecord
- DBバックアップ
- API調査結果、データ辞書、匿名fixture
- XLSXレポート取込など、Modbusで代替できない履歴機能

## 現在の確認済み範囲

- 対象機種: `SUN2000-4.95KTL-JPL1`
- 通信: SmartLoggerのEthernet1経由Modbus TCP
- 通信アドレス: `.env`の設定値を使用
- 取得: 機種、入力電力、有効電力、周波数、内部温度、運転状態、積算・当日発電量、
  蓄電池状態・電力・SOC
- 保存: `fusionsolar_modbus_tcp` RawDataと10個のRecord
- シリアル番号: 期待機器の照合用として`.env`だけに保存し、通常RawDataへ複製しない
