# Sprint 2 closure — owner gate checklist

Ngày: 2026-08-13. Owner (Dương) chạy **mọi** lệnh (hard rule #1); Claude chỉ đọc kết quả dán lại,
đối chiếu kỳ vọng, rồi cập nhật `PROJECT_STATUS.md` / `CHANGELOG.md` / milestone log.

Nguyên tắc: nếu bất kỳ lane nào fail → ghi root cause, để Sprint 2 = **blocked** thay vì overclaim.
Chạy tuần tự; dán output từng lane trước khi qua lane sau.

## 0 · Hạ tầng (một lần)

```powershell
.\make.ps1 redis-up
.\make.ps1 worker-up
.\make.ps1 serve-otel
.\make.ps1 status        # docker compose ps — xác nhận redis + worker + mlflow up
```

- [ ] Redis, `pit-online-worker`, API đều `up`; `PIT_OTEL_ENDPOINT` trỏ đúng VPS.

## Lane 1 — OTel worker/parity arrival (M063 / M069)

```powershell
docker compose up -d --build --force-recreate api pit-online-worker
.\make.ps1 demo-score
```

- [ ] Grafana/Loki nhận log worker + `online_write` span (không chỉ Docker logs).
- [ ] `demo-score` trả `feature_provider: pit-online-worker`.
- **Kỳ vọng:** hết cảnh báo `otel_enabled=True but ... packages are not installed`.

## Lane 2 — Range backfill idempotency (M071)

> Backfill range **phải day-aligned** (M035): 1 event_day = 24 step. Ví dụ day 30 = steps [697, 720].

```powershell
.\make.ps1 backfill -BackfillMode range -Start 697 -End 720
.\make.ps1 backfill -BackfillMode range -Start 697 -End 720   # chạy lại lần 2
```

- [ ] Hai lần cho **cùng** idempotency key; lần 2 short-circuit (không rebuild, không tạo Delta version mới, không duplicate) và trỏ về run_id đã commit của lần 1.
- **Kỳ vọng:** `future_read_violations=0`; source Silver version + committed Gold version khớp nhau giữa 2 lần.

## Lane 3 — Full / incremental backfill (M071)

```powershell
.\make.ps1 backfill -BackfillMode full
# hoặc:
.\make.ps1 backfill -BackfillMode incremental -Start 744 -End 745
```

- [ ] `offline.backfill.completed` với mode/range/idempotency key/Gold version, manifest bất biến.

## Lane 4 — Redis reset & rematerialize (M071)

> ⚠️ `materialize-recover` **xoá scoped Redis namespace** trước khi rebuild — chạy đúng Redis/Gold version chủ đích.

```powershell
.\make.ps1 materialize-recover -Watermark 743 -GoldPostVersion 7
```

- [ ] `offline.recovery.completed` với **0 record khác** và watermark khôi phục về 743.
- **Kỳ vọng:** command fail nếu records/watermark lệch (đây là gate thật, không phải no-op).

## Lane 5 — Async parity checkpoint (M068)

```powershell
.\make.ps1 parity-reconcile
```

- [ ] `offline.parity.reconcile.completed checked_entities=... field_mismatches=0 passed=True`.
- **Kỳ vọng:** online Redis/winlog khớp DuckDB offline reference, 0 mismatch.

## Lane 6 — Served-event Bronze → Silver → Gold candidate (M070)

```powershell
.\make.ps1 ingest-event-history
```

- [ ] `served_events_silver` + `served_events_gold_candidate` được tạo/cập nhật idempotent.
- [ ] Grafana panel candidate (dashboard v7) có dữ liệu; mọi row `label_status=unlabeled`.

## ✓ Regression + chốt

```powershell
.\make.ps1 lint
.\make.ps1 test-unit
```

- [ ] `ruff check`/`format` sạch; unit 110 passed.
- [ ] Cập nhật `PROJECT_STATUS.md` + `CHANGELOG.md` + milestone log M072 (Sprint 2 closure).
- [ ] Viết `docs/reports/sprint-2-completion-report.md` với bảng gate + evidence.
- [ ] Tag Sprint 2 = **verified** (hoặc **blocked** nếu có lane fail), rồi commit (không bypass hook).

---

### Ghi chú tham số

- Mặc định make.ps1: `Watermark=743`, `GoldPostVersion=7`, `GoldPreVersion=8`, `GoldRoot=data/lakehouse/paysim1/16910f90577b0d98`.
- Chỉnh `-Start` / `-End` khớp range Gold thực tế trước khi chạy backfill.
- T9 E2E rộng vẫn skipped; MVP closure dùng 6 invariant lane trên thay cho việc claim toàn bộ T9 suite.
