# Sprint 3 — Track B: kế hoạch triển khai FeatureSpec v3 (cold-start) + chiến lược backfill

Ngày lập: 2026-08-19
Trạng thái: **planned** (chưa có code cho các milestone bên dưới; đây là plan + backfill strategy).
ADR: [`docs/adr/011-cold-start-featurespec-v3.md`](../adr/011-cold-start-featurespec-v3.md) (proposed).
Đầu vào: [`sprint-3-feature-model-validity-findings.md`](sprint-3-feature-model-validity-findings.md)
(M073). Milestone: **M074**.

> Đây là Track B trong findings — đã được defer ở đó và nay owner cho phép mở. Nó **đổi schema Gold**
> nên **bắt buộc backfill full-range** + re-verify parity + train champion mới. Mọi con số PR-AUC v2
> KHÔNG carry sang v3 (hard rule #5: metric giảm sau khi đổi feature vì correctness là kết quả hợp lệ).

## 1. Quyết định đã chốt (không mở lại trong milestone này)

| Câu hỏi | Chốt |
|---|---|
| Bộ feature cold-start | **Fan-in + recency**: `pit_distinct_senders_24h/168h` + `pit_steps_since_last_event` |
| Track A (dọn feed thừa) | **Gộp vào v3**: bỏ `event_step`, `pit_prior_count_168h`, `recipient_has_history_1h/24h/168h` |
| Entity | Giữ nguyên `destination_entity_id` (không mở entity thứ 2 — đó là v4 nếu cần) |
| Backfill | **Full rebuild** cả 2 bảng Gold dưới v3 (schema đổi ⇒ `mode=FULL`) |

v3 = **10 field** (2 request + 8 history), thứ tự trong ADR-011 §"model feature order". Bỏ 5 field v2
không tải tín hiệu, thêm 3 field cold-start.

## 2. Ràng buộc định hình plan (bất biến)

- **User chạy mọi command** (hard rule #1). Agent viết code + đọc output owner dán. Không tuyên bố
  "verified" cho tới khi owner chạy gate.
- **Đổi frozen contract = ADR + version bump + backfill + parity + model run mới** (ADR-003 change
  policy). ADR-011 là cái ADR đó.
- **Hai engine độc lập** cho mọi field: DuckDB (`paysim_recipient.py` / `build_offline.py`) và oracle
  Python (`paysim_reference.py`). Đồng thuận mới là bằng chứng (Trap 1, M029).
- **Import-time guard sẽ đỏ toàn bộ suite** cho tới khi mọi consumer đổi đồng bộ. ⇒ v3 land như MỘT
  change set phối hợp, không commit từng phần nửa vời. Đây là tripwire cố ý.
- **PR-AUC primary; cấm accuracy** (AGENTS §9). Đọc kết quả v3 trên slice warm/cold, không so headline.
- Scope guard AGENTS §11 giữ nguyên: không Spark/Kafka/K8s/Ray/GPU; không HPO lớn.

## 3. Blast radius — file-by-file (để review đủ khi land)

| Lớp | File | Việc |
|---|---|---|
| **Contract (nguồn sự thật)** | `features/paysim_specs.py` | `PAYSIM_FEATURE_DEFINITION_VERSION`→v3, service→v3; `PAYSIM_STATIC_FEATURE_NAMES` bỏ `event_step`; `PAYSIM_HISTORY_FEATURE_NAMES` (8 field mới); `PAYSIM_MODEL_FEATURE_ORDER`; thêm 3 `FeatureSpec`; hằng `PAYSIM_RECENCY_SENTINEL_STEPS = 999`; giữ `forbidden_model_inputs` |
| **PIT engine (pre)** | `features/paysim_recipient.py` | `_pre_decision_history_columns` emit 8 field mới (không đều theo window); `paysim_pre_decision_feature_sql` thêm `COUNT(DISTINCT origin_entity_id)` + `c.step - MAX(s.step)` + sentinel; thêm `origin_entity_id` vào `PAYSIM_PRE_DECISION_SOURCE_COLUMNS`; cập nhật guard so-khớp contract |
| **Oracle Python** | `features/paysim_reference.py` | Tính độc lập 3 field mới (distinct set senders, max prior step, sentinel), đúng thứ tự contract; import-time contract check |
| **PIT engine (post) + Gold schema** | `features/build_offline.py` | `PRE_DECISION_FEATURE_SCHEMA` (10 field + identity); `POST_EVENT_STATE_SCHEMA` thêm post-sibling + `origin_entity_id` (như `amount` M057); `POST_EVENT_STATE_FIELD_NAMES` + `POST_EVENT_TO_CONTRACT_FIELD`; `GOLD_FEAST_SOURCE_COLUMNS`; `_assert_contract_alignment` (slice mới); `paysim_post_event_state_sql` distinct/recency inclusive-of-current; đọc `origin_entity_id` từ Silver |
| **E-matrix** | `models/paysim_gold.py` | `POST_HISTORY_FEATURE_NAMES` + join columns theo v3; E1 feature set (request 2 field); E4 = 10 field v3 |
| **Fixture** | `data/paysim_fixture.py` | Rebuild committed fixture + expected vectors dưới v3 (hand-derived cho ≥1 cutoff có distinct-senders>1 và recency hữu hạn/ sentinel) |
| **Feast** | `feature_repo/definitions.py`, `feature_repo/feature_specs.py` | 10 field, service v3, checksum mới |
| **Online write-path + parity** | `serving/online_state.py` | `LoggedEvent` thêm `origin_entity_id`; bump winlog serialization; `compute_window_features` emit set v3 (không đều); `_events_to_duckdb_rows` project sender; `recompute_pre_decision_features`; `count_parity_mismatches` tự cover field mới |
| **Materialization / serving** | `materialization/*`, `serving/{feature_provider,scoring,schemas,app}.py` | contract defaults (sentinel cho recency!), online record shape, `/score` vector 10 field |
| **Training** | `training/dataset.py`, `training/pipeline.py` | đọc 10 field v3; champion mới bound checksum v3 |
| **Tests** | `tests/temporal|unit|integration/*` | oracle/SQL parity 3 field mới + boundary (recency đúng sentinel, distinct-senders đếm đúng theo origin), fixture, feast checksum, online write-path, Gold schema |
| **Governance** | `CLAUDE.md`, `AGENTS.md`, `README` | cập nhật "Frozen contracts" sang v3 sau khi verified |

**Điểm dễ sai nhất (ghi rõ để không quên):**
1. `pit_steps_since_last_event` **default = 999**, KHÔNG phải 0 — 0 nghĩa "vừa có event", ngược hướng.
   Kiểm `_contract_defaults()` và mọi cold-path trả sentinel, không trả 0.
2. `distinct_senders` cần `origin_entity_id` ở **cả** offline pool (Silver có sẵn) **và** winlog online
   (hiện KHÔNG có ⇒ phải thêm + warm-start seed từ Gold post-event → Gold post-event phải mang
   `origin_entity_id` per-event).
3. Winlog serialization đổi ⇒ **không** đọc được winlog v2 cũ ⇒ rollout phải reset winlog namespace và
   re-warm-start từ Gold v3.

## 4. Kế hoạch milestone (mỗi milestone = 1 commit, đủ 3 file changelog)

| MS | Nội dung | Gate xác minh (owner chạy) |
|---|---|---|
| **M074** | ADR-011 (proposed) + plan này + changelog | review; `changelog-check` |
| **M075** | Contract v3 trong `paysim_specs.py` + oracle `paysim_reference.py` + 2 engine SQL (pre/post) + guard | `test-temporal` (oracle/SQL parity 3 field mới, boundary), `lint` |
| **M076** | Gold schema v3 (`build_offline.py`, `paysim_gold.py`) + fixture rebuild + Feast defs/checksum | `test-unit`, `test-lakehouse`, Feast G1 lane; ADR-011 → **accepted** |
| **M077** | Backfill v3 full-range (chiến lược §5) + re-verify parity offline | owner chạy §5 runbook; `future_read_violations=0`; rerun checksum khớp |
| **M078** | Online write-path v3 (winlog+sender, `compute_window_features`, materialize warm-start) + reset/re-warm-start | `test-unit` (write-path), live `materialize`+`demo-score`+`parity-reconcile` = 0 mismatch |
| **M079** | Champion v3 (train E1/E4 v3 + `SlicedMetrics` warm/cold) bound checksum v3; report kết quả | owner chạy `train`; MLflow run + manifest; report `sprint-3-track-b-results.md` |

Trạng thái phân biệt planned/implemented/**verified** — chỉ verified khi owner dán output gate.

## 5. Chiến lược backfill v3 (runbook)

Máy backfill đã có sẵn: `backfill/state_machine.py` (`plan_backfill`/`execute_backfill`, modes
FULL/RANGE/INCREMENTAL, idempotency key theo `(dataset, entity_def, feature_def, range)`, atomic
staging→promote qua `build_offline.py`). **Không cần viết lại máy** — v3 chỉ đổi schema; strategy là
cách vận hành nó cho một schema migration.

### 5.1 Tại sao BẮT BUỘC `mode=FULL`

Đổi schema (12→10 field pre; +sibling+`origin_entity_id` post) ⇒ số cột đổi. `_write_gold_table` chỉ
overwrite schema khi promote **toàn partition** (`schema_mode="overwrite"`); một incremental promote
đè lên Gold v2 cũ sẽ chết `SchemaMismatchError` (đúng như M057 đã gặp 18-vs-17). Vì `feature_def`
version nằm trong idempotency key, backfill v3 có key **mới** ⇒ không đụng/không reuse run v2 ⇒ Gold v2
cũ vẫn còn (time-travel/rollback được).

### 5.2 Trình tự (owner chạy, mỗi bước chờ kết quả)

```powershell
# 0) Tiền đề: M075+M076 đã land (contract v3 + Gold schema v3 + fixture xanh).

# 1) BẮT BUỘC TRƯỚC BACKFILL: rebuild Silver lakehouse để đóng dấu manifest sang v3.
#    Silver DATA không đổi (origin_entity_id đã có sẵn), nhưng idempotency key của backfill lấy
#    feature_definition_version TỪ MANIFEST SILVER (state_machine plan_backfill L263). Nếu manifest
#    còn v2, backfill sẽ tính ra key v2 và short-circuit về run v2 cũ → Gold KHÔNG rebuild.
.\make.ps1 build-lakehouse -Dataset paysim
#    Kỳ vọng: manifest mới feature_definition_version=paysim-fraud-recipient-v3,
#    feature_contract_checksum=33e8a839…, Silver version mới (vd v8).

# 2) FULL backfill v3 — dựng lại cả 2 bảng Gold [1,743] dưới feature_def=v3, promote atomic.
.\make.ps1 backfill -BackfillMode full -Start 1 -End 743
#    (-BackfillMode, KHÔNG phải -Mode: -Mode trùng tiền tố -ModelSeed/-ModelNonfraudSample → ambiguous)
#    Kỳ vọng: idempotency_key MỚI (≠ key v2 38e8f854…), state=committed, future_read_violations=0,
#    Gold pre/post version MỚI — GHI LẠI 2 số này cho gold-evaluate. Build thật ~20-30 phút (không
#    còn short-circuit); có log tiến độ [gold +Ns]/[promote +Ns].

# 3) Idempotency/determinism — chạy LẠI đúng range, phải short-circuit hoặc ra checksum y hệt (G2).
.\make.ps1 backfill -BackfillMode full -Start 1 -End 743
#    Kỳ vọng: NOOP_ALREADY_COMMITTED (cùng source checksum) HOẶC compare_reruns passed=True.

# 4) Re-verify PIT offline — oracle/SQL parity + future-read trên Gold v3 mới.
.\make.ps1 test-temporal
#    Kỳ vọng: 3 field mới parity 0 mismatch; boundary recency-sentinel & distinct-senders xanh.
```

### 5.3 Rollout online (sau khi Gold v3 committed — thuộc M078)

```powershell
# 5) Online store (Redis) phải đang chạy trước khi materialize.
docker compose up -d redis

# 6) Warm-start winlog v3 từ Gold v3 post-event. KHÔNG cần reset/recover winlog v2: key Redis được
#    namespace theo feature_service_version (v3), nên winlog v3 ghi sang namespace RIÊNG, không đụng
#    winlog v2 cũ (nằm im, orphan vô hại). `materialize recover` chỉ dùng khi restore một version
#    Gold post PIN CỨNG (bằng chứng G8/G10), không phải rollout thường.
.\make.ps1 materialize
#    Kỳ vọng: gold_post_event_version = post-version v3 mới; warm-start seed winlog CÓ origin_entity_id
#    cho mọi entity; watermark = 743.

# 7) Parity online/offline trên schema v3.
.\make.ps1 parity-reconcile
#    Kỳ vọng: field_mismatches=0, passed=True (đã cover 3 field mới, distinct-senders exact).
```

### 5.4 Backfill sửa lỗi cục bộ (INCREMENTAL/RANGE) — dùng khi cần, không phải bước migration

Sau khi v3 là baseline, mọi sửa (ví dụ late-arrival) đi qua đúng path cũ: `mode=RANGE` cho một dải
tròn `event_day`, `mode=INCREMENTAL` cho lookback tối thiểu (`GOLD_LOOKBACK_STEPS=168`). Fault-injection
late-arrival (`inject_late_arrival_correction`) chỉ chạy trên `data_root` test cô lập (ADR-005 §7),
không chạm Gold thật. Guard `validate_gold_cutoff_range` (căn biên `event_day`) và idempotency giữ
nguyên hiệu lực dưới v3.

### 5.5 Rollback

Gold v2 vẫn nằm nguyên (key backfill khác, Delta version cũ còn trong `_delta_log`). Nếu v3 hỏng:
serving trỏ lại champion v2 + Gold v2 qua time-travel; không mất dữ liệu. Champion v3 chỉ promote sau
khi M078 parity xanh (M079).

## 6. Định nghĩa "đủ tốt" cho Track B

Track B **thành công** nếu — bất kể PR-AUC lên hay xuống — ta có bằng chứng máy-đọc:
- Gold v3 build full-range, `future_read_violations=0`, rerun checksum khớp (G2/G3 giữ).
- Oracle/SQL parity xanh cho 3 field mới; online/offline parity 0 mismatch dưới v3.
- Champion v3 train xong, bound checksum v3, có `SlicedMetrics` warm/cold để **trả lời trực tiếp** giả
  thuyết cold-start (fan-in/recency có nâng lift khúc cold không), không phải một headline PR-AUC.
- Không con số nào bị tune để che (hard rule #5); metric v2 không bị restate cho v3.
