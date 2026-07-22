# SumiCore Project

## Purpose

SumiCore（旧HEDP）は、家庭の設備・環境・エネルギーに関する事実を共有する基盤であり、
単一のHEMS applicationではない。10年以上の運用を想定し、AI serviceへ依存せずに
稼働する。保存したデータを将来の可視化、分析、rule開発、自動化、applicationへ利用する。

## System role

SumiCore assists household equipment; it does not replace it. If SumiCore stops, the
equipment must remain usable through its vendor-provided functions or manual
operation. Automation must be removable and must never replace equipment
safety functions.

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

SumiCore normally stores all obtainable external information as RawData, including
historical and current values, states, equipment information, configuration,
Signal definitions, alarms, and aggregates. Current-value APIs are collected
periodically to form snapshot time series. Collection must not discard
information or infer an unconfirmed specification. Normalization and selection
belong after RawData has been stored.

## Scope

The intended scope includes solar generation, battery storage, grid power,
electric vehicles, air conditioning, ventilation, hot water, weather, indoor
conditions, and household equipment added in the future.

Vendor adapters, including SwitchBot, remain isolated from existing energy
collectors. High-resolution source history is retained without interpolation;
derived summaries must remain reproducible from source observations.

## Non-goals

- Replacing vendor control functions in full
- Requiring an AI service for runtime operation
- Making the core specific to one operating system
- Overwriting an API response with analysis-oriented transformed data
- Implementing an API from an unverified guess
