# HESTIA v1 残存release blocker

更新日: 2026-07-30

## 現在のblocker

0件。2026-07-30に利用者がv1.0 release candidateを最終承認し、
R8-10と集約Gate R8-08を完了した。

## 利用者がリスク受容して延期した項目

### `R3-07` 別障害領域backup

2026-07-30、利用者が外部backupなしの残存リスクを受容し、v1.0の必須Gateから外した。
Macの故障、盗難、火災等による現役DBと同一障害領域backupの同時喪失は保証対象外とし、
運用改善へ延期する。

## 運用上の停止点

sanctum、cloud、外部媒体、秘密、credential、現役backupには変更を加えていない。
準備済みのhost preflightと受入手順は
`docs/release/hestia-v1-sanctum-readiness.md`を正本とする。
