# Sprint 1 — Implementation Guide

## Temporal Contract và Feasibility (Tuần 1–2)

Mục tiêu Sprint 1 là loại bỏ rủi ro lớn nhất trước khi build platform: IEEE-CIS có thể được biểu diễn thành một event/entity history đủ tốt không, và ta có thể chứng minh PIT join không đọc tương lai không?

Không deploy cloud trong sprint này. Không dựng dashboard. Không tối ưu fraud model. Nếu temporal contract chưa khóa, mọi feature store phía sau chỉ tự động hóa một định nghĩa sai.

---

## 0. Bản đồ artifact

| ID | Artifact | Nội dung bắt buộc |
|---|---|---|
| S1-A1 | `docs/data-access.md` | Kaggle setup, license/rules, raw files, checksum |
| S1-A2 | `docs/reports/data-profile.html` hoặc `.md` | row count, schema, missingness, label/time/entity profile |
| S1-A3 | `docs/adr/001-temporal-entity-contract.md` | event time, tie-break, entity key, created time |
| S1-A4 | `data/fixtures/temporal_cases.parquet` | fixture có future, duplicate, tie, late-arrival cases |
| S1-A5 | `src/data/build_lakehouse.py` | raw CSV -> Bronze/Silver Delta tables |
| S1-A6 | `feature_repo/feature_specs.py` | 10–15 feature definitions và window semantics |
| S1-A7 | `tests/temporal/` | exhaustive PIT correctness tests trên fixture |
| S1-A8 | `docs/reports/leakage-prototype.md` | naive/leaky vs PIT comparison trên sample |
| S1-A9 | `docs/reports/model-baseline.md` | static baseline và PIT temporal baseline |
| S1-A10 | `docs/architecture-v1.md` | architecture, sequence, trust/data boundaries |
| S1-A11 | `docs/research-protocol.md` | RQ, H1–H4, E1–E5, P1–P5, metric definitions |
| S1-A12 | `Makefile`, lock file, CI skeleton | command contract và fast test path |

---

## 1. Các quyết định tạm khóa

- Full-data computation: local CPU.
- Canonical format: Parquet partitioned theo synthetic event date/range.
- Query engine: DuckDB.
- Primary model metric: PR-AUC.
- Primary data split: chronological split trong train set có label.
- Entity candidate mặc định: hash của `card1|card2|card3|card5` sau canonicalization.
- Event ordering: `TransactionDT`, sau đó `TransactionID`.
- Label-derived features: không dùng.
- Spark, Kafka, Kubernetes, cloud deployment: ngoài Sprint 1.

Các quyết định entity key và embargo chỉ được khóa chính thức sau EDA.

---

## 2. Repo skeleton

```text
feature_repo/                 Feast definitions/config (bắt đầu Sprint 1, hoàn thiện Sprint 2)
src/
  contracts/                  event, entity, feature, manifest schemas
  data/                       download, profile, canonicalization
  features/                   DuckDB SQL/templates và reference logic
  training/                   split, train, evaluate
  serving/                    để trống tới Sprint 2
tests/
  fixtures/
  temporal/
  unit/
data/
  raw/                        gitignored
  lakehouse/
    bronze/                   Delta tables, gitignored
    silver/                   Delta tables, gitignored
    gold/                     tạo ở Sprint 2, gitignored
  fixtures/                   synthetic data được commit
artifacts/                    gitignored immutable run outputs
docs/
  adr/
  feature-store/
  reports/
```

Chỉ scaffold directory cần dùng. Không tạo placeholder service cho Kafka/Kubernetes.

---

## 3. T1 — Environment và command contract

### 3.1. `make doctor`

Phải kiểm tra và báo rõ:

- Python version và virtual environment;
- Docker + Compose;
- disk trống;
- RAM khả dụng;
- DuckDB import;
- DuckDB `delta` extension và `deltalake` Python import;
- Kaggle credential có/không;
- port dành cho Redis, MLflow, API;
- Git commit hiện tại.

Không in secret/token ra log.

### 3.2. Dependency policy

- Pin Python minor range và exact direct dependencies bằng lock file.
- Tách `dev`, `training`, `serving` dependency nếu dependency graph lớn.
- Windows là host được hỗ trợ; command execution chính nên chạy qua WSL hoặc container để giảm sai lệch.

### 3.3. CI fast lane

CI chỉ dùng synthetic fixture và phải hoàn tất nhanh:

```text
lint -> unit -> temporal fixture -> sample feature build -> checksum
```

Không tải IEEE-CIS trong CI.

---

## 4. T2 — Data access và immutable raw layer

### 4.1. Access workflow

1. User accept competition rules trên Kaggle.
2. Cấu hình Kaggle token ngoài repo.
3. `make data` tải archive vào `data/raw/`.
4. Verify filename, byte size và SHA-256.
5. Không giải nén/ghi đè nếu manifest đã khớp.

Nếu ngày 2 vẫn chưa truy cập được, tiếp tục toàn sprint bằng synthetic fixture và một schema-compatible sample tự tạo. Không để credential chặn kiến trúc.

### 4.2. Raw invariant

- Raw files bất biến.
- Không chỉnh CSV bằng notebook.
- Mọi derived artifact nằm ngoài `data/raw/`.
- Dataset không commit hoặc republish.

### 4.3. Manifest

Manifest tối thiểu:

```json
{
  "dataset": "ieee-cis-fraud-detection",
  "source": "kaggle competition",
  "files": [{"path": "...", "bytes": 0, "sha256": "..."}],
  "downloaded_at": "...",
  "code_commit": "..."
}
```

---

## 5. T3 — EDA phục vụ contract, không phải EDA trang trí

EDA phải trả lời các câu hỏi quyết định kiến trúc:

1. Train row count, fraud rate và time span tương đối là gì?
2. Có bao nhiêu transaction trùng `TransactionDT`?
3. Candidate entity nào tạo history đủ dày mà không gom quá rộng?
4. Phân bố transaction/entity: median, p90, p99 là bao nhiêu?
5. Bao nhiêu entity chỉ có một event?
6. Identity table phủ bao nhiêu phần trăm transaction?
7. Feature nào có semantics request-time, history-time hoặc không rõ?
8. Window 1h/24h/7d tạo bao nhiêu non-null history?
9. Memory/disk sau khi project 20–40 columns là bao nhiêu?

### 5.1. Entity sensitivity

Ít nhất so sánh:

- C1: `card1|card2|card3|card5`;
- C2: C1 + `addr1`;
- C3: một candidate từ fraud benchmark literature nếu reproducible.

Metric:

- unique entity count;
- transactions/entity distribution;
- repeated entity coverage;
- collision/missing-key rate;
- temporal persistence.

Chọn candidate giúp đủ history nhưng không gộp entity phi lý. Quyết định và trade-off vào ADR-001.

### 5.2. Leakage inventory

Mỗi cột được tag một trong:

- `request_available`;
- `historical_only`;
- `label`;
- `unknown_semantics`;
- `identifier_not_feature`.

Cột `unknown_semantics` không vào MVP nếu không chứng minh availability tại decision time.

Đặc biệt, `C*`, `D*`, `V*` là anonymized/engineered fields: có thể profile hoặc chạy opaque-feature baseline, nhưng không đưa vào correctness claim chính khi upstream semantics không được công bố.

---

## 6. T4 — Temporal/entity contract

### 6.1. Canonical schema

```text
transaction_id: int64
event_timestamp: timestamp
ordered_event_timestamp: timestamp
created_timestamp: timestamp
card_entity_id: string
label_is_fraud: int8              # chỉ ở label table
request_*: typed columns
source_row_hash: string
dataset_snapshot_id: string
```

### 6.2. Deterministic time transform

- Chọn synthetic epoch duy nhất.
- Cộng `TransactionDT` seconds.
- Với rows cùng second, sort `TransactionID` và cộng offset microsecond theo rank.
- Assert resulting `ordered_event_timestamp` unique theo transaction.
- Không phụ thuộc thứ tự đọc file.

### 6.3. Canonical entity hashing

- Convert number-like categories sang canonical string, không để `123.0` và `123` thành hai key.
- Missing dùng sentinel có version, ví dụ `<NULL>`.
- Serialize tuple bằng JSON canonical hoặc delimiter được escape.
- Hash SHA-256 và có unit test golden values.

### 6.4. ADR-001 phải quyết định

- entity candidate cuối;
- synthetic epoch;
- tie-break;
- strict `<` hay `<=` semantics;
- created timestamp primary/synthetic fault injection;
- maximum feature window;
- temporal split và embargo.

---

## 7. T5 — Synthetic temporal fixture

Fixture phải nhỏ đủ để tính bằng tay và bao phủ:

1. entity chưa có history;
2. hai event khác thời điểm;
3. hai event cùng timestamp khác transaction ID;
4. future event có amount cực lớn;
5. duplicate transaction;
6. event đến trễ (`created_timestamp > event_timestamp`);
7. missing entity fields;
8. feature version thay đổi.

Mỗi row có expected feature vector được commit. Đây là oracle cho toàn dự án.

### 7.1. Property tests

- Thêm một future event không làm thay đổi feature vector của cutoff quá khứ.
- Shuffle input rows không đổi output.
- Chạy lại cùng input không đổi checksum.
- Duplicate event bị reject hoặc deduplicate theo contract.
- Offline reference và incremental reference cho cùng result.

---

## 8. T6 — Bronze/Silver lakehouse layers

`build_lakehouse` phải:

1. đọc CSV bằng DuckDB, chỉ project cột cần;
2. ghi Bronze Delta tables gần source nhất, kèm source hash/ingestion metadata;
3. join identity nếu feature được chọn cần nó;
4. tạo ordered time và entity key ở Silver;
5. tách Silver label table khỏi feature source;
6. validate schema/range/null contract;
7. ghi Delta transaction atomically và partition theo synthetic date;
8. tạo manifest chứa exact Bronze/Silver table versions;
9. không ghi đè snapshot hợp lệ nếu không có versioned operation rõ ràng.

Partition candidate:

```text
data/lakehouse/bronze/transactions/    # Delta table root + _delta_log
data/lakehouse/bronze/identity/        # Delta table root + _delta_log
data/lakehouse/silver/transactions/    # partitioned Delta table
data/lakehouse/silver/labels/          # separate Delta table
```

Vì date là synthetic, dùng nó như layout key, không diễn giải business calendar.

### 8.1. Snapshot/time-travel test

1. Build Silver version N.
2. Append một controlled fixture batch tạo version N+1.
3. Query latest và version N, xác nhận row counts/checksums khác đúng như expected.
4. Time travel về N và tái tạo artifact checksum ban đầu.
5. Không chạy `VACUUM` trong project window nếu version còn được run manifest tham chiếu.

### 8.2. Resource benchmark

Ghi:

- wall-clock time;
- peak RSS nếu đo được;
- raw bytes và Parquet bytes;
- rows/s;
- số partition;
- machine spec.

Kill switch: nếu full build vượt resource budget, giảm projected columns trước; không thêm Spark trong Sprint 1.

---

## 9. T7 — Feature specs và PIT reference

### 9.1. Feature spec fields

```text
name
entity
source
window
aggregation
event_time_column
availability
dtype
null/default semantics
version
owner
```

### 9.2. Reference computation

Reference implementation ưu tiên readability/correctness trên fixture. Optimized DuckDB query có thể khác implementation nhưng phải khớp reference output.

PIT guard audit phải lưu được `max_source_timestamp` cho sampled output để assert nó nhỏ hơn cutoff.

### 9.3. Feature list freeze

Kết thúc ngày 7, khóa MVP ở 10–15 history features. Mọi feature mới sau đó cần lý do liên quan tới RQ; “có thể tăng model score” chưa đủ.

---

## 10. T8 — Leakage prototype và baseline model

### 10.1. Bốn dataset tối thiểu

- static request features + temporal split;
- deliberately leaky full-history aggregates + random split;
- PIT history + random split;
- PIT history + temporal split.

### 10.2. Diễn giải bắt buộc

- Future leakage và random split optimism là hai hiện tượng khác nhau.
- Metric của pipeline leaky là negative-control evidence, không phải thành tích model.
- Nếu leaky pipeline không tăng metric, vẫn báo kết quả; xác nhận leakage bằng audit invariant chứ không chỉ metric gap.

### 10.3. MLflow tối thiểu

Mỗi run ghi:

- dataset/feature/entity version;
- split cutoff;
- model hyperparameters;
- PR-AUC/ROC-AUC/recall@FPR;
- feature list;
- code commit;
- training duration;
- artifact path.

---

## 11. T9 — Research protocol và architecture v1

### 11.1. Research protocol

Khóa trước khi chạy final benchmark:

- hypotheses;
- experiment matrix;
- primary/secondary metrics;
- sample/filter rules;
- float tolerance;
- repeated-run policy;
- failure/invalidation rules;
- cách ghi inconclusive result.

### 11.2. Architecture v1

Phải có:

- batch ingestion/backfill sequence;
- training retrieval sequence;
- online scoring/materialization sequence;
- lineage/version propagation;
- secret/data boundary;
- cloud path và local fallback;
- cái gì chưa build.

---

## 12. Go/No-Go cuối Sprint 1

| Gate | PASS khi |
|---|---|
| G1 Data access | full data tải được hoặc synthetic path đủ để không block |
| G2 Lakehouse | Bronze/Silver build deterministic; schema và time-travel fixture pass |
| G3 Entity viability | selected entity có repeated-history coverage chấp nhận được |
| G4 PIT correctness | 0 future-read violation trên exhaustive fixture |
| G5 Leakage control | label lineage bị chặn; leaky positive control được đánh dấu rõ |
| G6 Feature scope | 10–15 specs được version hóa và khóa |
| G7 Feasibility | DuckDB pipeline nằm trong RAM/disk/time budget |
| G8 Baseline | static + PIT temporal model chạy và log MLflow |
| G9 Protocol | RQ/metrics/ablation đã predefine |

No-Go không có nghĩa bỏ đề tài ngay:

- Entity không đủ history: thử candidate khác hoặc PaySim fallback.
- Full data quá nặng: giảm cột/window, dùng subset có protocol cố định.
- Feast chưa dùng trong Sprint 1 không phải blocker; Feast bắt đầu ở Sprint 2.

---

## 13. Lịch 10 ngày làm việc

| Ngày | Việc chính | Artifact |
|---|---|---|
| 1 | Scaffold, doctor, CI fixture lane | S1-A12 |
| 2 | Kaggle access, raw manifest, fallback fixture | S1-A1, S1-A4 |
| 3 | Schema/time/label EDA | S1-A2 |
| 4 | Entity sensitivity + leakage inventory | S1-A2 |
| 5 | ADR temporal/entity contract | S1-A3 |
| 6 | Bronze/Silver Delta builder + snapshot/resource benchmark | S1-A5 |
| 7 | Feature specs + reference PIT implementation | S1-A6 |
| 8 | Temporal/property tests | S1-A7 |
| 9 | Leakage prototype + baseline training | S1-A8, S1-A9 |
| 10 | Research protocol, architecture, Go/No-Go | S1-A10, S1-A11 |

---

## 14. Sprint 2 chỉ được nhận những input sau

- immutable raw manifest + exact Bronze/Silver Delta versions;
- locked entity and event-time contract;
- feature spec version `v1`;
- synthetic expected vectors;
- temporal tests pass;
- split cutoffs cố định;
- baseline MLflow run IDs;
- architecture v1 và open risks.

Nếu một trong các input này còn mơ hồ, không bắt đầu online store. Sửa contract rẻ hơn migrate dữ liệu và debug skew sau này.
