# SumiCore Project

## Purpose

SumiCore（旧HEDP）は、家庭の設備・環境・エネルギーに関する事実を共有する基盤であり、
単一のHEMS applicationではない。10年以上の運用を想定し、AI serviceへ依存せずに
稼働する。保存したデータを将来の可視化、分析、rule開発、自動化、applicationへ利用する。

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
