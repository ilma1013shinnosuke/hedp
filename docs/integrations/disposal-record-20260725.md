# 解析資産の処分記録（2026-07-25）

## 承認

利用者から「約894MBの再生成可能物を削除してください」と明示承認を受け、
`deletion-candidates-20260725.md`の承認単位Aだけを処分した。

## 処分結果

- 固定対象: 21件
- SwitchBot研究内の`__pycache__`: 20 directories
- BRAVIA研究内の`__pycache__`: 16 directories
- 処分前の対象実割当計測: 915,412 KiB
- Data volume空き容量: 38,189,908 KiBから38,716,804 KiB
- 観測できた空き容量の純増: 526,896 KiB（約514.55 MiB）

対象はnpm依存、build/cache、公開repository clone、bytecode、Android Studio APK import、
apktool/JADX派生物、再生成可能なrenderである。詳細な絶対pathは
`deletion-candidates-20260725.md`の承認単位Aを正とする。

事前の実割当合計と空き容量の純増は一致しない。APFSの共有block、purgeable領域、
placeholder、処理中のOS書込みなどにより、`du`の合計は実際の空き容量増加を保証しない。
解放効果は前後の`df`差分を実績値とする。

## 残したもの

- Smart LEDZの版固定XAPK原本
- Qrioとエコキュートの専用AVD
- Mieleの実Raw/history/audit
- 利用者提供写真の変換物
- `.env`、Keychain、DB、backup、launchd
- Qrio Local本体と登録済みlaunchd job

これらの存在を処分後に確認した。Qrio Localのprocessは確認時点で常駐していなかったが、
launchd jobは登録済みであり、撤去対象にはしていない。

## 復旧

削除物はGitからの復元対象ではない。npm lockfile、公開repository、保存XAPK、解析tool、
build手順から再取得または再生成する。AVD、実Raw、認証状態、再取得不能資料は削除して
いない。
