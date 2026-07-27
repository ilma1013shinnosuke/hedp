# 北陸電力 家庭向け料金情報アダプター

## 目的

HESTIAが経済性を判断するときに使う料金根拠を、公式発表のまま追跡可能にする
オフライン取り込みアダプターです。料金単価をプログラムへ固定せず、原文、発表日、
適用期間、訂正・取消を履歴として残します。

これは電気契約の変更機能ではありません。北陸電力へのログイン、申込み、契約変更、
支払い、個人情報の取得は行いません。

## 公式情報源

- 北陸電力 家庭向け料金単価:
  <https://www.rikuden.co.jp/ryokin/minsei.html>
- 北陸電力 個人向け料金メニュー:
  <https://www.rikuden.co.jp/electricity_service/kojin_ryokin.html>
- 北陸電力 電気料金メニュー一覧:
  <https://www.rikuden.co.jp/ryokin_annai/>
- 北陸電力 料金関係プレスリリース:
  <https://www.rikuden.co.jp/press/ryokin.html>
- 北陸電力 約款・要綱:
  <https://www.rikuden.co.jp/yakkan/>
- 北陸電力 燃料費調整制度:
  <https://www.rikuden.co.jp/nencho/index.html>
- 北陸電力 燃料費調整単価の推移:
  <https://www.rikuden.co.jp/nencho/tanka.html>
- 北陸電力 くつろぎナイト12:
  <https://www.rikuden.co.jp/ryokinmenu/kutsuroginight.html>
- 資源エネルギー庁 電気・ガス料金支援:
  <https://www.enecho.meti.go.jp/category/gekihen_lp/>
- 資源エネルギー庁 再エネ賦課金:
  <https://www.enecho.meti.go.jp/category/saving_and_new/saiene/kaitori/surcharge.html>

第三者の比較サイト、検索結果の抜粋、報道記事は料金の正本にしません。

## 保存モデル

1. **Raw**: 取得したバイト列を変更せずBLOBで保存します。SHA-256、取得時刻、
   Content-Type、公式URLを付け、同一原文は重複保存しません。
2. **履歴**: plan、rate、documentの改訂を追記します。訂正・取消でも過去行を
   UPDATE/DELETEしません。
3. **現在値**: 指定した基準日に有効な最新改訂を履歴から選びます。
4. **将来公表分**: 適用開始前の改訂も保存しますが、開始日までは現在値にしません。

出典から項目が消えた場合は `omitted` として要確認にします。取消と推測せず、
明示された取消だけを `cancelled` として追記します。

## 対象項目

- 公開されている家庭向け料金プラン候補と適格条件
- 基本料金、段階別・時間帯別・季節別の電力量料金
- 燃料費調整
- 市場価格調整
- 再生可能エネルギー発電促進賦課金
- 政府の電気料金支援
- 発表日、適用開始・終了、将来公表分、訂正・取消
- 取得時刻、出典URL、品質、欠損理由

市場価格調整が家庭向け低圧へ適用されるかなど、公式資料で確定できないものは
`unknown` のまま保存します。欠損を0円へ変換しません。

公開一覧の匿名fixtureは、使っておとくライト、従量電灯ネクスト、節電とくとく
電灯、くつろぎナイト12、ecoシフトチェンジ、従量電灯、アクアECOプラン、
エルフナイト8、エルフナイト10、エルフナイト10プラス、深夜電力の11候補を
保持します。新規受付終了の旧メニューも、既契約者の履歴評価に必要なので候補から
消しません。

## 個人への適用判定

公開プランはすべて `public_candidate` として保存します。住所、契約容量、設備、
既契約、申込条件がなければ、特定家庭の `eligible` / `ineligible` を判定しません。
家庭設定は料金資料と別にし、未設定時は `household_contract_not_configured` です。

`eligibility_complete` は、プランの存在確認と適格条件の完全抽出を分離する印です。
`false` のとき、空の `eligibility` は「条件なし」ではなく「未抽出の条件が残る」
ことを意味します。公開一覧にプラン名があっても、この印が `false` のままなら
個人への適用を確定しません。

## 更新

既定の取得間隔候補は24時間、stale判定は48時間です。実スケジューラーやHTTP
実装はまだ接続していません。HTML/PDFの構造は公開APIとして保証されていないため、
レイアウトを推測するスクレイパーも実装していません。公式原文を保存し、抽出した
小さなJSON契約を厳格に解析する境界だけを実装しています。

## テスト専用DB

`OfflineTariffRepository` はファイル名が `.tariff-test.sqlite3` で終わるDBだけを
開きます。本番 `hedp.db` には接続できません。現在のmigrationはこの隔離DB専用です。

## fixture

`tests/fixtures/hokuriku_tariff/official_household_snapshot_anonymous.json` は構造検証用
です。`fixture_anonymized: true` であり、一部金額は意図的に匿名化されています。
実料金の計算や表示には使用できません。

## 未確認・今後

- 公式HTML/PDFごとの安定した抽出方法と改定時の検知方法
- 家庭向け低圧における市場価格調整の適用範囲
- 全公開プランの全適格条件・受付状態を1回の資料で確定できるか
- 再エネ賦課金の年度切替資料と検針月の対応
- 料金計算に必要な消費税、口座振替割引、契約容量単位、日割計算の規則
- 公式発表の訂正・取消を一意に関連づける識別子

これらは未確認のまま残し、推測で正式データを作りません。
