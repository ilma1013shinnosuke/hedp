# SwitchBot E26 高速直送経路

利用者が明示した照明操作を低遅延で送るための、E26専用出力ポートである。
通常の送信時は機器一覧・現在状態・結果状態を取得せず、署名済みPOSTを1回だけ送る。

## 速度と安全の境界

- 目標はコマンド受付まで500ms以内。クラウドや家庭回線の遅延により保証はしない。
- 到達不能やタイムアウトを成功扱いしない。
- 操作命令は自動再試行しない。二重操作を避けるためである。
- 応答には匿名alias、命令種別、受付成否、受付時間、試行回数だけを残す。
- 秘密値、機器ID、Raw応答はログ・回答・Gitへ出さない。
- 正式UI・自動化は`FastLightExecutionPort`を共通`ExecutionCoordinator`の
  `LIVE` modeからだけ呼び、ExecutionGateの許可判断を送信前に完了させる。
- `fast_light_runner.py`は利用者が明示承認した診断・試験専用であり、共通Gateを
  通らない。本番UI・自動化からimportまたは起動しない。

## 一度だけ行う紐付け

`scripts/configure_switchbot_e26_fast_path.py`がOpenAPIの登録一覧を1回取得し、
`deviceType`が`Color Bulb`の機器が正確に1台の場合だけ、非公開の機器IDを
mode 0600の`.env`へ保存する。0台または複数台なら変更せず失敗する。

実行時は`SWITCHBOT_TOKEN`、`SWITCHBOT_SECRET`、
`SWITCHBOT_E26_DEVICE_ID`を使用する。値は表示しない。

## 対応命令

- 点灯・消灯
- 明るさ 1〜100%
- 色温度 2700〜6500K
- RGB各0〜255

タイマーやフェードはこの直送経路へ内蔵しない。必要な場合は判断層または実行計画が
複数の単発命令を明示的に生成し、中止条件を管理する。
