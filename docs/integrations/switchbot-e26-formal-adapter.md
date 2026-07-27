# SwitchBot スマート電球 E26 正式操作アダプター

## 境界

E26は専用モジュールに閉じ込め、テープライト3とは機器固有payloadと能力を共有しない。
共通化するのはExecutionIntent、ExecutionGate、OperationOutcome、秘密非表示などの
安全契約だけである。

正式対応は電源、1〜100%の明るさ、RGB、2700〜6500Kの色温度。タイマーは
HESTIAのスケジューラー責任であり、アプリ固有シーン・エフェクトは確認済みの
公開read-back契約がないため未対応とする。

## 低遅延経路

```text
準備済みIntent/Evidence/Authorization
  → ローカルExecutionGate
  → 直ちに1回だけOpenAPI POST
  → accepted
  → 別フェーズで1回だけ状態再取得
  → OperationOutcome
```

有効な操作を受けてから送信するまでに、機器一覧取得・状態取得・DBアクセスを
挟まない。`last_fast_execute_ms`もGateとPOSTだけを測り、read-back待ちを含めない。
スライダーは既存`FastLightControlSession`で未送信値をまとめ、最新値だけを送る。

## 安全規則

- 操作POSTの自動再試行は禁止。timeoutは成功扱いせず`result_unknown`で停止する。
- timeout、通信断、read-back不能、不一致では安全停止し、別操作を続けない。
- 消灯中の明るさ・RGB・色温度指定は暗黙点灯を避けるため拒否する。
- 明るさ0は消灯と混同しないため拒否し、消灯は明示的な電源命令にする。
- 同一の未送信スライダー値は最新値優先、短時間の同一送信は抑止する。
- Readerは1回の上限付きGET、Writerは1回のPOSTで、公開interfaceも実行経路も分離する。
- 実装は純粋PythonでOS固有機能に依存しない。
