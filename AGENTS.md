# Point-in-Time Feature Store — Project Handoff

> Cách dùng: copy file này vào thư mục gốc của project mới và đổi tên thành `AGENTS.md` trước khi mở session Codex mới. File này là context khởi động độc lập; không cần đọc lại lịch sử chat.

## 1. TL;DR

Xây dựng một **Point-in-Time Correct Feature Store trên local Delta Lakehouse cho fraud scoring**, tập trung vào Cloud/MLOps engineering nhưng phải chạy được CPU-only và không tốn phí bắt buộc.

Ba invariant quan trọng nhất:

1. Không feature nào được đọc dữ liệu xảy ra sau prediction cutoff.
2. Offline training vector và online serving vector phải parity.
3. Backfill phải atomic, idempotent và tái lập được từ exact data/version manifest.

Project kéo dài 6 tuần, solo, gồm 3 sprint. Cloud deployment và TypeScript serving là phần mở rộng; local reproducibility là acceptance path chính.

## 2. Trạng thái bàn giao

- Proposal và implementation guide đã được thiết kế chi tiết trong repo cũ.
- Chưa có implementation cho project PIT: chưa có dataset snapshot, code pipeline, Makefile, tests, Compose, model artifact hoặc experiment report.
- Project mới phải được xem là **greenfield implementation**.
- Không migrate source code VLM/FinChart cũ sang project này; chỉ copy tài liệu liên quan nếu cần.
- Sprint 1 được phép dùng JupyterLab để khám phá, nhưng correctness logic phải được extract vào `src/` và `tests/`.

Tài liệu nguồn trong workspace cũ: `C:/workspace/vlm-fintech/point-in-time-feature-store-proposal.md` và thư mục `C:/workspace/vlm-fintech/docs/feature-store/` (ba sprint guide cùng reference architecture comparison).

## 3. Câu hỏi nghiên cứu

Làm thế nào bảo đảm feature tại thời điểm training và serving nhất quán, không target/future leakage, đồng thời hỗ trợ backfill có thể tái lập trong một feature platform chạy được trên tài nguyên local?

Các câu hỏi con:

- PIT join có loại bỏ toàn bộ future reads trên các temporal edge case không?
- Offline/online parity có giữ được qua chronological replay không?
- Full/range/incremental backfill có tạo artifact ổn định khi input/version/cutoff không đổi không?
- Correctness, snapshotting và incremental reuse phải trả chi phí runtime/resource như thế nào?
- Freshness, skew và version mismatch có được phát hiện trước khi silent prediction không?

## 4. Framing nghiên cứu

Đây là **paper-inspired adaptation**, không phải reproduction 100%.

Paper nền:

- Rui Liu et al., *Optimizing Data Pipelines for Machine Learning in Feature Stores*, PVLDB 2023: <https://www.vldb.org/pvldb/vol16/p4230-camacho-rodriguez.pdf>

Paper dùng FeathrPO, Spark và các dataset TPCxAI/Favorita/eCommerce. Project này thay bằng Feast interface, DuckDB và Delta Lake single-node. Không được claim reproduce speedup 3x của paper. Chỉ adapt các ý tưởng:

- PIT semantics;
- reuse computation;
- layout/full/incremental comparison;
- versioned and reproducible materialization.

Đóng góp bổ sung của project là offline/online parity, replay, freshness/skew detection và model/feature version gates.

## 5. Giới hạn cứng

| Constraint | Quyết định |
|---|---|
| Thời gian | 6 tuần, 3 sprint, solo |
| Compute | Local CPU là mặc định; không phụ thuộc GPU |
| Chi phí | Bắt buộc bằng 0 trong thời gian experiment |
| Cloud | Optional; Modal + Upstash nếu đăng ký/quota dùng được |
| Cloud fallback | Local Docker Compose là acceptance path |
| Training | Chốt model family sau PaySim EDA; LightGBM chỉ là candidate baseline, không tối ưu model sâu |
| Training runtime | Python CLI local CPU; không Ray Train/Ray Tune trong MVP |
| IaC | Makefile + Compose + CI; không bắt buộc Terraform/OpenTofu |
| Distributed stack | Không Spark, Kafka, Kubernetes hoặc Airflow trong must-have |
| Event ingress | Một logical Transaction Producer/Replay Driver dùng ordered in-memory iterator/queue; không external broker trong MVP |
| Streaming | Deterministic chronological replay từng event thay cho live stream; xử lý xong `t` mới phát `t+1` |
| Serving runtime | FastAPI/Uvicorn reference; không Ray Serve trước khi có benchmark chứng minh nhu cầu scale |
| Dashboard | Chỉ phục vụ evidence; không phải outcome chính |
| TypeScript | Nice-to-have Sprint 3 sau khi Python reference pass |

Không thêm công nghệ chỉ để làm architecture trông lớn. Outcome được đánh giá bằng machine-readable evidence, không bằng số container hay screenshot.

## 6. Dataset strategy

### Bắt buộc: synthetic temporal oracle

Tạo fixture nhỏ có expected outputs tính trước, bao phủ:

- future record;
- duplicate event;
- same timestamp và deterministic tie-break;
- late arrival;
- entity không có history;
- window boundary;
- query/score trước rồi mới update online state.

Fixture này là **ground truth cho PIT correctness**. Fraud labels của dataset lớn chỉ là ground truth cho model evaluation.

### Dataset áp dụng

1. EDA-first path: PaySim; phải profile temporal structure, entity history, imbalance, leakage
   risk và feature cardinality trước khi khóa model family.
2. Candidate alternatives: IEEE-CIS Fraud Detection và Home Credit. Chỉ chuyển khi PaySim
   không đạt temporal/entity viability hoặc có ADR nêu rõ giá trị nghiên cứu bổ sung.
3. Không chạy full benchmark trên nhiều application dataset trong MVP; synthetic temporal
   oracle luôn là correctness ground truth độc lập.

IEEE-CIS entity candidate ban đầu: canonicalized hash của `card1|card2|card3|card5`; phải xác nhận bằng EDA trước khi khóa. Event ordering ban đầu: `TransactionDT`, sau đó `TransactionID`.

Home Credit chỉ được chọn nếu biến thể dataset có event time, repeated entity history và
pre-decision semantics đủ rõ cho PIT evaluation; static applicant snapshot không tự động phù
hợp với feature-store research question.

Nếu dùng PaySim, review leakage trước khi dùng các balance columns; ưu tiên `step`, transaction attributes và explicit origin/destination entity history.

## 7. Stack đã chốt

| Layer | Công nghệ |
|---|---|
| Notebook/EDA | JupyterLab |
| Language | Python cho reference implementation |
| Lakehouse | Delta Lake qua `delta-rs`/`deltalake`, dữ liệu Parquet |
| Offline compute | DuckDB |
| Feature contract | Feast ở vai trò registry/retrieval/materialization mỏng; custom PIT oracle vẫn là correctness source of truth |
| Online store | Local Redis; Upstash là hosted option |
| Validation | Pandera + custom temporal assertions + pytest |
| Model | TBD sau PaySim EDA; LightGBM là candidate baseline |
| Tracking/registry | MLflow local với alias `candidate`, `champion`, `previous` |
| Serving | FastAPI + versioned `FeatureProvider` boundary |
| Workflow | Python CLI + Makefile |
| Services | Docker Compose: Redis, MLflow, FastAPI |
| Monitoring | Structured JSON + OTel instrumentation; OTel Collector/Prometheus/Grafana trên VPS là optional Sprint 3, ngoài core Compose |
| CI | GitHub Actions fast fixture lane |
| Cloud | Modal CPU + Upstash, optional |
| TS experiment | Fastify + Redis + ONNX Runtime Node, optional Sprint 3 |

Core architecture:

```text
Offline/medallion:
  Raw archive -> Bronze Delta -> Silver canonical events
  -> DuckDB PIT computation -> Gold pre-decision features + post-event state
  -> Feast contract -> Redis materialization

Training:
  Gold/Feast historical retrieval -> Python training CLI (model TBD sau EDA) -> MLflow

Online/replay:
  one logical Replay Driver (ordered in-memory queue) -> FastAPI transaction t
  -> read Redis history strictly before t -> score t
  -> update Redis + append t to Event History only after scoring
```

Medallion là offline data architecture và phải chạy bằng Python CLI/Makefile; notebook chỉ dùng
để EDA/experiment. Bronze/Silver/Gold không nằm trên synchronous serving request path.

## 8. Sprint plan và Definition of Done

### Sprint 1 — Temporal contract and feasibility, tuần 1–2

JupyterLab được dùng cho EDA, entity sensitivity, temporal analysis và leakage prototype. Notebook không được là nơi duy nhất chứa PIT logic.

Must-have outcomes:

- data access/checksum và data profile;
- chốt event time, entity key, tie-break và created-time policy trong ADR;
- synthetic temporal fixture với expected vectors;
- raw CSV thành Bronze/Silver Delta sample;
- 10–15 feature specs có window semantics;
- naive/leaky versus PIT prototype;
- static/PIT baseline với temporal split; LightGBM là candidate, chỉ khóa sau PaySim EDA;
- PIT implementation trong `src/` và exhaustive temporal tests;
- Makefile, dependency lock và CI skeleton.

Go gate:

- synthetic future-read violations bằng 0;
- dataset/entity path được khóa hoặc đã chuyển PaySim;
- sample/full-data build nằm trong CPU/RAM budget;
- notebook experiments chạy lại được bằng non-notebook commands.

### Sprint 2 — Core feature platform, tuần 3–4

Must-have outcomes:

- Feast repository và versioned feature service ở vai trò contract mỏng;
- Gold Delta offline features được build qua Python CLI/Makefile, không phụ thuộc notebook;
- full/range/incremental backfill cùng immutable manifest;
- Redis materialization và watermark;
- temporal training dataset, model đã được khóa bằng EDA evidence và MLflow run; training local
  single-node, không Ray Train/Ray Tune;
- model promotion/rollback với deployment manifest;
- FastAPI/Uvicorn scoring và versioned feature-provider interface; không Ray Serve trong MVP;
- một logical Transaction Producer/Replay Driver với deterministic in-memory queue/iterator;
- chronological replay theo thứ tự `score t -> post-score Redis update -> append Event History`,
  hoàn tất `t` rồi mới phát `t+1`; không Kafka/RabbitMQ/Redis Streams service;
- integration tests cho parity, duplicates, idempotency và recovery;
- Compose + one-command local E2E.

Go gate:

- `make test-e2e` chạy từ sample/raw đến prediction;
- offline/online mismatch bằng 0 theo tolerance đã khóa;
- rerun backfill tạo cùng row count/schema/checksum và không duplicate;
- Redis reset rồi rematerialize được;
- model/feature version mismatch bị reject;
- promote/rollback có audit manifest.

### Sprint 3 — Evidence, monitoring and optional cloud, tuần 5–6

Must-have outcomes:

- frozen experiment manifest;
- correctness/model ablation;
- full versus incremental backfill comparison;
- freshness, parity, latency và failure metrics;
- injected stale/skew/version/recovery report;
- clean-room reproduction log;
- architecture-as-built, README, final report và demo.

Should-have:

- Modal + Upstash smoke deployment;
- OTel Collector + Prometheus + Grafana self-host trên VPS bằng deployment/ops boundary riêng;
  app repo chỉ giữ instrumentation, metric contract, dashboard JSON và config mẫu không secret;
- late-arrival correction experiment.

Nice-to-have, chỉ làm khi core release gates pass và còn buffer:

- TypeScript Fastify + Redis + ONNX scorer;
- cross-runtime prediction parity;
- Python versus TypeScript p50/p95/p99, throughput, CPU/RSS và cold-start benchmark.

## 9. Baseline và experiment matrix

### Correctness/model

| ID | Setup | Vai trò |
|---|---|---|
| E1 | Static request features + temporal split | Non-history baseline |
| E2 | Naive full-history features có future data + random split | Deliberately leaky positive control |
| E3 | PIT-correct history + random split | Tách ảnh hưởng join khỏi split |
| E4 | PIT-correct history + temporal split | Kết quả chính, deployable nếu pass gates |
| E5 | E4 model + stale/skew injection trong replay | Detection/reliability test |

Sau PaySim EDA, khóa một model family/configuration cho toàn bộ E1–E5 cùng feature version và
seed policy; LightGBM là candidate baseline chứ không phải quyết định trước dữ liệu. Primary
metric là PR-AUC; secondary là ROC-AUC và recall tại fixed FPR. Model không cần thắng leaky
baseline; metric giảm sau khi loại leakage là kết quả hợp lệ.

### Pipeline

| ID | Setup | Priority |
|---|---|---|
| P1 | CSV/full scan/full recompute | Should-have context baseline |
| P2 | Partitioned Parquet/full recompute | Should-have layout ablation |
| P3 | Partitioned Delta/full recompute | Must-have full-recompute baseline |
| P4 | Delta incremental range + retry/time travel | Must-have treatment |
| P5 | Feature-version invalidation + rollback | Must-have MLOps evidence |

P3 versus P4 là comparison chính vì giữ storage format giống nhau. Không đặt target speedup 3x; báo median, dispersion, data selectivity, hardware, bytes/files scanned và break-even point thực tế.

### Hard acceptance metrics

- Future-read violations: `0`.
- Integer/categorical parity mismatches: `0`.
- Float parity: `abs_diff <= 1e-6` hoặc tolerance được khóa trước experiment.
- Backfill cùng input/version/range: cùng schema, row count và canonical checksum.
- Duplicate event không double-count.
- Exact Delta source versions phải reproduce cùng training dataset checksum.
- Known injected faults phải được detector/guard xử lý theo expected status.
- Bắt buộc có `dataset_snapshot_id`, feature version, model version, code commit, dependency lock và run ID trong evidence.

## 10. Command contract mục tiêu

```text
doctor | bootstrap | lab | data-sample | data | profile | build-lakehouse
test-temporal | features | backfill | time-travel-check | materialize | train
promote | rollback | serve | replay | test-e2e | benchmark | report
deploy-cloud | export-onnx | serve-ts | benchmark-serving  # optional
```

## 11. Scope guards

- Không dựng Kafka/Kubernetes/Airflow/Spark, RabbitMQ, Redis Streams hoặc Debezium trong MVP.
- Chỉ dùng một logical replay producer; nhiều entity không đồng nghĩa cần nhiều producer.
- Không dùng Ray Train/Ray Tune/Ray Serve nếu chưa có benchmark chứng minh distributed
  training, large-scale HPO hoặc serving replicas là bottleneck thực tế.
- Feast là registry/retrieval/materialization contract mỏng, không compute feature và không thay
  thế independent PIT oracle. Chỉ bỏ Feast qua ADR và phải thay đủ versioned FeatureSpec,
  FeatureProvider, materialization manifest và parity gates.
- Medallion Bronze/Silver/Gold chỉ thuộc offline path và chạy bằng CLI/Makefile; notebook không
  phải pipeline executor, serving không đi xuyên medallion.
- Query/score online phải xảy ra trước khi event hiện tại update state.
- Không dùng accuracy làm metric chính cho fraud imbalance.
- Không dùng label-derived hoặc post-outcome fields làm model features.
- Không tune model để che correctness failure.
- Không coi cloud deployment là điều kiện nghiệm thu.
- Không triển khai TypeScript trước khi Python reference, replay parity và Sprint 2 gate pass.
- Không thêm Superset: report/Grafana đã đủ cho evidence, project không phải BI platform.
- Observability VPS là optional Sprint 3 và không nằm trong core Compose; Grafana phải đọc một
  telemetry backend như Prometheus, không nhận trực tiếp telemetry từ application.
- Không đánh đổi correctness evidence lấy dashboard hoặc architecture screenshot.

## 12. Việc phải làm trong session đầu tiên của project mới

1. Đọc file này và các guide nguồn nếu chúng vẫn truy cập được.
2. Inspect repo mới; không giả định đã có implementation.
3. Tạo project skeleton, dependency lock, `.gitignore`, `.env.example` và Makefile tối thiểu.
4. Thêm `make doctor`, `make lab`, `make data-sample` và `make test-temporal` trước.
5. Tạo synthetic temporal fixture và independent reference oracle.
6. Viết tests future/duplicate/tie/late-arrival/window-boundary trước khi tải full dataset.
7. Tạo ba notebook Sprint 1: data profile, entity/temporal analysis, leakage prototype.
8. Chạy PaySim EDA trước, rồi chốt PaySim/IEEE-CIS/Home Credit bằng go/no-go có ADR.
9. Chỉ sau khi temporal tests pass và EDA evidence đủ mới build lakehouse và khóa model baseline.
10. Cập nhật trạng thái artifact/gate trong repo; luôn phân biệt planned, implemented và verified.

## 13. Quy tắc bắt buộc về milestone changelog và project status

`artifacts/changelog/` là audit trail được commit và là nguồn sự thật về tiến độ triển khai.
Nó là ngoại lệ có chủ đích so với các runtime artifact khác trong `artifacts/` vốn vẫn bị
gitignore.

Mỗi khi bắt đầu triển khai, có thay đổi đáng kể, hoàn thiện hoặc verify một milestone, agent
bắt buộc cập nhật đồng thời:

1. `artifacts/changelog/PROJECT_STATUS.md`: trạng thái hiện tại của toàn project, phân biệt rõ
   `planned`, `implemented`, `verified` và `blocked` nếu có.
2. `artifacts/changelog/CHANGELOG.md`: entry theo thời gian, nêu milestone ID, thay đổi chính,
   gate/result và link tới log chi tiết.
3. `artifacts/changelog/milestones/<milestone-id>-<slug>.md`: implementation log chi tiết của
   milestone đang làm. Một milestone có thể được cập nhật nhiều lần; không tạo log rời thiếu
   liên kết.

Implementation log tối thiểu phải ghi:

- ngày giờ và trạng thái;
- scope và acceptance/gate liên quan;
- quyết định kỹ thuật và lý do;
- file/module/service đã thêm, sửa hoặc di chuyển;
- command đã chạy và kết quả test/checksum/version quan trọng;
- deviation so với kế hoạch;
- known gaps, rủi ro và next step.

Không được tuyên bố milestone đã hoàn thành hoặc verified trong trả lời cho user nếu ba artifact
trên chưa đồng bộ. Không được sửa số liệu evidence bằng tay nếu có thể sinh từ command hoặc raw
artifact; log phải trỏ tới evidence tương ứng.

Pre-commit hook `milestone-changelog` là guard bắt buộc. `make bootstrap` hoặc
`.\make.ps1 bootstrap` phải cài hook và không được nuốt lỗi cài đặt. Khi staged change chạm code,
tests, notebook, infrastructure, ADR hoặc report milestone, hook yêu cầu staged cùng
`PROJECT_STATUS.md`, `CHANGELOG.md` và ít nhất một milestone log. Không bypass hook trừ tình
huống khẩn cấp; nếu buộc phải bypass thì phải ghi lý do vào milestone log ở commit kế tiếp.

Tất cả report đọc bởi con người nằm trong `docs/reports/`. Raw run outputs, model artifacts,
Delta manifests và benchmark evidence tiếp tục nằm trong `artifacts/` theo layout/version của
từng pipeline; chỉ `artifacts/changelog/` được commit mặc định.
