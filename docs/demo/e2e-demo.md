# Demo E2E: Gold -> Redis -> FastAPI scoring

Huong dan chay demo cho nguoi ngoai doc. Toan bo so lieu duoi day la so do that ghi nhan ngay
2026-08-06 tren may Windows local (Gold v6, Redis container, MLflow container).

## Yeu cau truoc

1. **Docker Desktop dang chay** (daemon san sang). Kiem tra: `docker version --format '{{.Server.Version}}'`
2. **Gold da build**: bang `gold.post_event_state_updates` v6 (6.362.620 dong, step 1..743,
   2.722.362 destination) da nam trong `data/lakehouse/paysim1/16910f90577b0d98/gold/`.
3. **MLflow tracking server co run training**: container MLflow (port 5000) phai chay va chua
   run FINISHED cua experiment `pit-fintech-gold-training` (demo dung run
   `8f9c709782704f1eba89cc9e3fde83c1`). Serving load model bang
   `mlflow.sklearn.load_model("runs:/<run_id>/model")` — khong co MLflow la khong score duoc.
4. Python env cua repo da sync day du: `UV_PROJECT_ENVIRONMENT=.venv uv run --frozen --all-groups python -c "import redis"`

## Chuoi lenh theo thu tu

```bash
# 1. Bat Redis + MLflow (uoc tinh ~30-60s, lan dau co the lau hon do pull image)
make up-core
# hoac chi Redis: make redis-up

# 2. Xac nhan ca hai healthy (~5s)
docker compose ps
#   pit-fintech-redis-1   Up ... (healthy)   127.0.0.1:6379->6379/tcp
#   pit-fintech-mlflow-1  Up ... (healthy)   127.0.0.1:5000->5000/tcp

# 3. (LAN DAU HOAC KHI RESET) Materialize Gold -> Redis, toi watermark 743 (~6,5 phut)
make materialize WATERMARK=743
#   cuoi ra: watermark step 743 written; 2.722.362 entity, 2.527.816 written / 194.546 noop

# 4. Chay demo day du: Redis check -> Gold check -> materialize -> serve -> score 3 case (~7-8 phut)
make demo
# hoac neu store DA o watermark 743 roi, chay nhanh, bo qua materialize (~42 giay):
UV_PROJECT_ENVIRONMENT=.venv uv run --frozen --all-groups python scripts/run_demo_e2e.py --skip-materialize
```

Cac lenh thao tac rieng:

```bash
# Chi chay API (khong demo): FastAPI tren 127.0.0.1:8000
make serve
#   POST /score          - cham diem 1 giao dich
#   GET  /health/live    - process song
#   GET  /health/ready   - san sang: model + online store + feature version da load
#   GET  /metrics        - dem so request/error, tong latency (plain text, trong process)

# Tra cuu watermark hien tai
UV_PROJECT_ENVIRONMENT=.venv uv run --frozen --all-groups pit materialize show

# Tat services (du lieu Redis nam trong volume redis-data, khong mat khi down)
make redis-down
# hoac: docker compose down   (khong xoa volume)
```

## Ket qua mong doi cua 3 case

Demo chon entity dong: dong co `step` lon nhat <= watermark trong Gold. Tren Gold v6 do la
`C1470998563` (feature_step = 743). Ba request deu la `TRANSFER`, amount 150.75:

| Case | Request | Ket qua mong doi |
|---|---|---|
| A - fresh | entity C1470998563, step 744 | `feature_status="fresh"`, `staleness=1` (744 - 743), `fraud_probability` ~ `2.2674930319146938e-05`, `decision_threshold` ~ `0.17100957808137637` |
| B - stale | cung entity, step 1243 | `feature_status="stale"`, `staleness=500` |
| C - missing | entity khong ton tai (`C0000000000`) | `feature_status="missing"`, 9 field history deu = 0 (count 0, amount 0.0, has_history 0) |

Ket qua lan chay that 2026-08-06 (`--skip-materialize`): **3/3 PASS, tong 41.95s**.

`fraud_probability`/`decision_threshold` chi dung neu API van load dung run
`8f9c709782704f1eba89cc9e3fde83c1`; neu co run FINISHED moi hon thi serving tu dong chon run do
(model_version = run id moi).

## Gioi han (chua lam — ghi that, khong hoa my)

- **T6 offline/online parity CHUA lam**: khong co parity report nao, demo khong so sanh vector
  online voi vector offline.
- **Khong co model registry that**: `model_version` = MLflow run id, `deployment_id=None`.
  Promotion/rollback (G11) chua dat. Serving chi chon "run FINISHED moi nhat", khong co alias
  champion/candidate.
- **Backend SQLite chua implement** (`OnlineStoreKind.SQLITE` -> NotImplementedError); chi Redis.
- **G8 recovery chua lam**: `rematerialize_after_reset()` va Feast `PushSource` van
  NotImplementedError.
- **tests/e2e van bi skip** (12 tests); G5/G7/G9 chua co lane test ghim tieu chi — demo nay la
  happy path, KHONG phai bang chung gate pass.
- **Materialize la full recompute**: moi lan chay lai doc toan bo Gold va MGET 2.7M key (~6,5
  phut); incremental backfill chua co.
- Redis phai duoc materialize truoc khi score: request vao entity chua co record tra `missing`
  (dung theo contract, khong phai loi).
