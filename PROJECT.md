# SumiCore Project

## Purpose

SumiCore（旧HEDP）は、家庭の設備・環境・エネルギーに関する事実を共有する基盤であり、
単一のHEMS applicationではない。10年以上の運用を想定し、AI serviceへ依存せずに
稼働する。保存したデータを将来の可視化、分析、rule開発、自動化、applicationへ利用する。

## Vision

SumiCoreが目指すのは、機器を多く自動化した家ではなく、住む人が仕組みに振り回されず、
安全で快適に暮らしながら、必要なときには家の状態と判断理由を理解し、自分で介入できる
家である。技術は生活の主役ではなく、気づかれない程度に負担を減らす裏方とする。

機能数、取得件数、自動化率を成功指標にしない。日常的な確認や復旧対応が減り、機器本来の
機能を損なわず、利用者が望んだ結果を小さな負担で得られることを価値とする。

## Value priorities

設計、判断、操作、保存量が競合した場合は、原則として次の順に優先する。

1. 人と住宅の安全、健康に対する重大な危険の回避
2. 機器自身の安全条件、メーカーの保護条件、SumiCore停止中も続く基本機能
3. 利用者の意思、物理操作、純正操作経路、手動解除の維持
4. 事実の正確性、欠損の明示、判断と操作の追跡可能性
5. 健康と最低限の快適性の維持
6. 日常の管理、通知、復旧、保守に必要な負担の削減
7. 経済性、追加の快適性、環境性の改善

下位の利益で上位の条件を相殺しない。例えば、電気料金の削減を理由に安全条件、利用者の
現在の指示、機器保護を破らない。複数の候補が上位条件を同程度に満たす場合に、経済性や
追加の快適性を比較する。

## Truth and explanation

SumiCoreは、取得した事実、そこから導いた推定、価値判断、送信した操作、確認できた結果を
区別する。欠損を0、空文字、古い値で埋めず、状態不明や結果不明を成功として扱わない。
自動化の高度さよりも、「何を知り、なぜ判断し、実際にどうなったか」を後から説明できる
ことを優先する。

RawDataは証拠であるが、すべてを永久に同じ粒度で残すこと自体を目的にしない。復元、
再解析、障害調査、将来価値に必要な証拠を、価値に応じた期間と粒度で保持する。集約や削除の
前には、可逆archive、checksum、復元確認、明示的な削除判断を要求する。

## Simplicity and change

将来必要そうという理由だけで共通基盤、抽象層、directory、永続tableを増やさない。
まず一つの具体的な用途を、匿名fixture、失敗条件、停止方法まで含めて完成させ、二つ以上の
実例で共通性が確認できた時点で抽象化する。メーカー固有差はAdapterへ隔離し、読み取りと
操作は公開機能と実行経路の両方で分離する。

変更は小さく、測定可能で、元へ戻せる順序で行う。新しい仕組みが安定したことを確認する
まで旧経路と復旧手段を消さず、移行完了後は知識と判断理由だけを正本へ統合し、再生成可能な
解析物や重複経路を残し続けない。

## Failure philosophy

失敗は完全に防げる前提にせず、範囲と時間を上限化し、他の機器・収集元・層へ波及させない。
timeout、再試行、待機、保持量には機器と通信方式に応じた上限を持たせる。読み取りは安全な
範囲で再試行できるが、解錠、給湯、電源投入などの操作を応答がないという理由だけで
盲目的に再送しない。

SumiCoreが判断できない場合は、推測で埋めて積極的に動くのではなく、既存状態の維持、
機器標準制御への復帰、提案だけの提示、安全な停止のいずれかを明示的に選ぶ。警告は人の
注意力を消費するため、対応方法のない反復通知を増やさない。

## System role

SumiCoreは家庭機器を支援・連携・拡張する非必須層であり、機器そのものを置き換える
必須制御装置ではない。SumiCore、実行端末、家庭LAN、インターネットのいずれかが
停止しても、機器自身の安全機能、自動制御、物理操作、標準スケジュールを継続できる
構成を原則とする。

### 機器自律の原則

これは通常時の設計判断に使う基本方針であり、SumiCoreによる制御やSumiCore依存機能を
一律に禁止する制限ではない。機器側に同等機能がない場合や、機器横断の最適化による
利益が大きい場合は、下記の条件を満たしてSumiCoreを管理主体にできる。

- 機器自身の安全機能をSumiCoreで置き換えたり、常時上書きしたりしない。
- 純正アプリ、物理スイッチ、リモコンなど、SumiCoreを通らない操作経路を残す。
- 機器にある基本スケジュールは、合理的な理由なくSumiCoreへ移さない。
- SumiCoreは外部イベント連携、機器横断操作、統合表示、音声操作、記録、分析、
  最適化を担当する。
- SumiCoreだけで実現する機能は依存関係を明示し、停止時の安全な代替動作または
  停止状態を定義する。

### SumiCore依存を認める条件

- SumiCoreを管理主体にする理由と得られる利益を記録する。
- SumiCore停止時、通信不能時、状態不明時の動作を定義する。
- 利用者が手動で解除、停止、操作できる経路を用意する。
- 制御の期限、対象、安全条件、結果確認方法を定義する。
- 安全機能をSumiCoreだけに依存させない。この条件は例外にしない。

### 再起動と再接続

SumiCoreは保存済みの古い状態や未完了の命令を、再起動後に盲目的に適用しない。
対象機器から現在状態を取得し、値の鮮度と品質を確認してから連携を再開する。
期限切れの操作意図は再送せず、状態を確認できない機器は操作対象から外す。

### 機能の管理主体

正式な操作機能には、機能ごとに「機器」「SumiCore」「利用者」のどれが管理主体かを
定義する。機器側とSumiCore側に同じスケジュールや制御規則を同時に持たせず、
競合、振動、繰り返し上書きを防ぐ。

## Development stages

1. Data collection and visualization
2. Analysis and rule development
3. Shadow mode and semi-automation
4. Automation
5. Application development

## Long-term principles

- Correctness
- Maintainability
- Long-term stability
- Data integrity and reproducibility
- Backward compatibility
- OS-independent core logic
- Isolation of vendor-specific behavior
- Minimal cloud dependency
- AI as a development and analysis aid, not a runtime dependency

## Data acquisition policy

SumiCore preserves the external information required to reproduce, verify, and
explain the system as RawData. Collection must not infer an unconfirmed
specification. RawData is immutable while retained, but not every obtainable
response is kept at full resolution forever. Retention, aggregation, lossless
cold archiving, and eventual deletion follow the documented value criteria and
an explicit deletion gate. Normalization and initial retention classification
belong after RawData has been captured.

## Scope

The intended scope includes solar generation, battery storage, grid power,
electric vehicles, air conditioning, ventilation, hot water, weather, indoor
conditions, and household equipment added in the future.

Vendor adapters, including SwitchBot, remain isolated from existing energy
collectors. High-resolution source history is retained without interpolation
for the period in which it is needed; derived summaries identify the source
evidence and retention class from which they were produced.

## Non-goals

- Replacing vendor control functions in full
- Requiring an AI service for runtime operation
- Making the core specific to one operating system
- Overwriting an API response with analysis-oriented transformed data
- Implementing an API from an unverified guess
- Maximizing automation, collected data, notifications, or supported devices
- Requiring daily system administration from the resident
- Hiding uncertainty or unsuccessful operations to make the system appear healthy

## Definition of success

SumiCoreは、利用者がシステム自体を管理する時間より、システムによって減る生活上の負担が
十分に大きいときに成功している。停止しても家の基本機能が続き、再起動後に古い判断を
押し付けず、普段は静かに働き、必要なときだけ根拠と選択肢を短く示すことを目標とする。

技術的には、事実から結果まで追跡でき、失敗が局所化され、保存量と実行時間に上限があり、
新しい機器を既存機能へ影響させず追加・停止・廃止できる状態を完成とみなす。
