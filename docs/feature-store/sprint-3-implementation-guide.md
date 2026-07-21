# Sprint 3 — Implementation Guide

## Ablation, Monitoring và Cloud Demo (Tuần 5–6)

Sprint 3 chuyển hệ thống đã đúng thành bằng chứng có thể bảo vệ. Không thêm feature/model mới nếu không phục vụ trực tiếp experiment matrix. Ưu tiên theo thứ tự:

1. correctness evidence;
2. ablation có thể tái lập;
3. failure/skew detection;
4. cloud portability;
5. demo và tài liệu;
6. TypeScript serving experiment chỉ khi các mục trên không bị đe dọa.

---

## 0. Bản đồ artifact

| ID | Artifact | Nội dung bắt buộc |
|---|---|---|
| S3-A1 | `experiments/manifest.yaml` | E1–E5, P1–P5 config đã khóa |
| S3-A2 | `artifacts/experiments/<run_id>/` | raw metrics/log/timing/checksum |
| S3-A3 | `docs/reports/correctness-ablation.md` | leaky vs PIT, random vs temporal |
| S3-A4 | `docs/reports/backfill-performance.md` | CSV/Parquet/Delta/full/incremental/time travel |
| S3-A5 | `monitoring/` | freshness, parity, latency, error metrics/dashboard |
| S3-A6 | `docs/reports/reliability-and-skew.md` | injected failure matrix |
| S3-A7 | `deploy/modal_app.py` + config | optional hosted scoring path |
| S3-A8 | `docs/reports/cloud-cost.md` | quota, usage, zero-cost evidence |
| S3-A9 | `docs/architecture-final.md` | architecture as built + deviations |
| S3-A10 | `README.md`/project README section | quickstart, story, limitations |
| S3-A11 | `docs/final-report.md` | complete research/engineering report |
| S3-A12 | demo script/video | end-to-end + one injected failure |
| S3-A13 | `services/scoring-ts/` | optional Fastify + Redis + ONNX Runtime scorer |
| S3-A14 | `docs/reports/serving-runtime-comparison.md` | optional Python/TypeScript parity, latency và resource benchmark |

---

## 1. Input gates từ Sprint 2

Không chạy final experiments trước khi:

- synthetic temporal tests pass;
- offline/online parity pass;
- backfill checksum stable;
- model input/feature service version locked;
- split cutoffs locked;
- experiment protocol locked;
- API emits lineage and freshness metadata.

Nếu thay feature definition sau khi bắt đầu experiment, bump version và rerun tất cả affected experiments. Không trộn result giữa version.

---

## 2. T1 — Experiment runner

### 2.1. Run manifest

Mỗi run có:

```text
experiment_id
run_id
dataset_snapshot_id
entity_version
feature_version
model_config
split_policy
range/cutoffs
machine_spec
dependency_lock_hash
code_commit
started_at/finished_at
status
raw_artifact_paths
```

### 2.2. Immutability

- Run directory không được ghi đè.
- Retry tạo attempt/run ID mới và link `supersedes`.
- Summary report đọc raw JSON/Parquet; không nhập số bằng tay.
- Failed run vẫn giữ logs và config.

### 2.3. Repeated-run policy

Pipeline timings:

- một warm-up không tính;
- ít nhất ba measured runs;
- báo median, min/max hoặc IQR;
- machine/load conditions ghi trong manifest.

Model training:

- fixed seed;
- ít nhất ba seeds nếu thời gian cho phép;
- nếu chỉ một seed, ghi rõ limitation.

---

## 3. T2 — Correctness/model ablation E1–E5

### E1 — Static temporal baseline

- Request-time features only.
- Temporal split.
- Mục đích: model baseline không phụ thuộc feature history.

### E2 — Deliberately leaky positive control

- Full-history aggregate có future data.
- Random split.
- Audit phải xác nhận future reads > 0.
- Không bao giờ promote/deploy model này.

### E3 — PIT features + random split

- Đúng PIT join nhưng random split.
- Mục đích: tách effect của split khỏi feature computation.

### E4 — PIT features + temporal split

- Kết quả chính.
- Dùng production feature service version.

### E5 — Online skew/freshness injection

- Dùng E4 model.
- Mutate/drop/stale một số online feature records.
- Đo detection rate và impact lên prediction/output status.

### 3.1. Report table

| Run | Future violations | Split | PR-AUC | ROC-AUC | Recall@fixed FPR | Deployable |
|---|---:|---|---:|---:|---:|---|
| E1 | | temporal | | | | baseline |
| E2 | >0 expected | random | | | | no |
| E3 | 0 | random | | | | no |
| E4 | 0 | temporal | | | | yes if gates pass |
| E5 | 0 offline / injected skew online | replay | n/a | n/a | n/a | detector test |

### 3.2. Interpretation rules

- Metric cao không chứng minh pipeline đúng.
- Metric thấp hơn sau PIT correction có thể phản ánh loại bỏ information không có lúc serving.
- E2 là positive control; nếu metric không tăng, future-read audit vẫn chứng minh leakage.
- Random/temporal gap là distribution/evaluation issue, không tự động gọi là target leakage.

---

## 4. T3 — Pipeline ablation P1–P5

### P1 — CSV/full scan/full recompute

Reference performance baseline. Chỉ project cột cần nhưng không partition reuse.

### P2 — Partitioned Parquet/full recompute

Đo effect của:

- columnar compression;
- filter/projection pushdown;
- partition pruning;
- reduced bytes read.

### P3 — Partitioned Delta/full recompute

Đo overhead/benefit của Delta transaction log so với raw partitioned Parquet:

- runtime và bytes/files scanned;
- exact table version được tạo;
- schema enforcement;
- snapshot history và khả năng đọc version cũ.

### P4 — Delta incremental range, retry và time travel

Chọn ít nhất ba delta selectivity, ví dụ nhỏ/trung bình/lớn. Đo:

- runtime;
- partitions/bytes scanned;
- output checksum so với corresponding slice của full recompute;
- overhead manifest/validation.

Rerun cùng range/version. Expected:

- no recompute hoặc deterministic same output theo policy;
- checksum identical;
- no duplicate;
- manifest link rõ.

Sau commit mới, time travel về source/target versions của run cũ phải tạo lại cùng checksum.

### P5 — Feature version invalidation

Thay một controlled feature definition:

- bump feature version;
- tạo Gold Delta version/snapshot mới và ghi lineage;
- old online namespace không bị silent overwrite;
- affected backfill partitions được rebuild;
- model/feature mismatch bị API reject;
- rollback về old version vẫn thực hiện được.

### 4.1. Không claim quá paper

Kết quả chỉ có giá trị trên IEEE-CIS, single-node DuckDB và machine đã ghi. Không so sánh trực tiếp với speedup FeathrPO/Spark trong paper.

---

## 5. T4 — Monitoring

### 5.1. Metrics bắt buộc

**Freshness**

- `feature_materialization_watermark_seconds`;
- `feature_freshness_lag_seconds`;
- stale request count/rate.

**Lakehouse/version**

- current Bronze/Silver/Gold table versions;
- backfill run -> source/target version mapping;
- failed/aborted Delta commit count;
- schema rejection và time-travel reproduction status.

**Parity/skew**

- sampled parity mismatch count/rate;
- per-feature absolute difference;
- feature-version mismatch count;
- missing feature/entity count.

**Pipeline**

- backfill duration/rows/bytes/partitions;
- validation failure count;
- committed/failed run count;
- late-arrival impacted partitions.

**Serving**

- online retrieval latency;
- model inference latency;
- end-to-end latency;
- HTTP/error status;
- prediction score distribution.

### 5.2. Alert semantics

Alert nên thể hiện invariant, không chọn threshold tùy ý:

- parity mismatch > 0 trên golden sample;
- feature version mismatch > 0;
- watermark cũ hơn configured freshness SLA;
- backfill failed hoặc stuck;
- online store missing rate tăng;
- model input schema mismatch.

### 5.3. Dashboard tối thiểu

Một dashboard có bốn hàng:

1. current versions/watermark;
2. freshness/parity;
3. backfill health;
4. serving latency/errors và model promotion/rollback events.

Không dành thời gian làm UI đẹp trước khi metric semantics đúng.

---

## 6. T5 — Reliability và fault injection

### 6.1. Test matrix

| Case | Injection | Expected behavior |
|---|---|---|
| R1 Future row | thêm event tương lai vào source | historical past vector không đổi |
| R2 Duplicate | phát lại cùng transaction | no double-count/idempotent |
| R3 Same timestamp | đảo input order | tie-break giữ output ổn định |
| R4 Late arrival | created time trễ | impacted range được backfill, checksum khớp clean reference |
| R5 Schema drift | bỏ/đổi dtype cột | Delta schema enforcement/quarantine trước commit |
| R6 Partial output | kill backfill giữa chừng | không có half-committed Delta snapshot; resume an toàn |
| R7 Redis reset | xóa online state | rematerialize tới watermark và parity phục hồi |
| R8 Stale online | bỏ qua một materialization | stale flag/alert xuất hiện |
| R9 Version mismatch | deploy model v2 với features v1 | ready=false hoặc scoring reject |
| R10 Store timeout | block Redis | bounded retry rồi explicit 503 |
| R11 Snapshot rollback | commit bad controlled version | time travel về good version và reproduce old artifact |
| R12 Model rollback | promote controlled bad candidate | restore explicit previous version/manifest; feature contract vẫn tương thích |

### 6.2. Evidence

Mỗi case lưu:

- exact command;
- precondition;
- injected change;
- expected and observed behavior;
- logs/metrics/checksums;
- cleanup/recovery result.

Không chỉ chụp dashboard. Test phải assert machine-readable outcome.

---

## 7. T6 — Cloud deployment

### 7.1. Scope

Cloud path chỉ gồm:

- scoring API trên Modal CPU;
- model artifact;
- feature contract/registry snapshot;
- Upstash Redis chứa online features của curated evaluation entities;
- structured logs.

Raw/silver dataset, full backfill và MLflow history không cần upload.

### 7.2. Account gates

Trước khi tích hợp:

- Modal workspace hoạt động và hiển thị free credit;
- Upstash free Redis tạo được không cần nâng paid;
- region/URL/TLS connectivity pass;
- no payment/auto-upgrade path được bật ngoài ý muốn;
- quota đủ cho curated subset.

Không dành quá một ngày xử lý account. Fail thì dùng local Compose + optional tunnel.

### 7.3. Deployment artifact

`modal_app.py` phải:

- pin image/dependencies;
- load explicit model + feature versions;
- read secrets từ platform secret store;
- expose health/readiness/scoring;
- configure scale-to-zero;
- log request ID/version/latency, không log secret/raw sensitive fields.

### 7.4. Seed hosted online store

- Chọn curated entities từ một pinned Gold Delta version và temporal test range theo deterministic manifest.
- Estimate serialized size trước write.
- Namespace keys theo environment và feature service version.
- Verify sampled records sau seed.
- Có teardown script xóa đúng namespace, không flush toàn database mù quáng.

### 7.5. Hosted smoke test

1. `/health/ready` trả đúng versions.
2. Score known entity, freshness `fresh`.
3. Score unknown entity, defined fallback.
4. Inject one stale/mutated record, detector/report thấy nó.
5. Restore/rematerialize và parity pass.

---

## 8. T7 — Cost và resource report

### 8.1. Local resource

- machine CPU/RAM/disk;
- raw archive và Bronze/Silver/Gold Delta/artifact sizes;
- Delta log/checkpoint overhead và retained versions;
- peak memory và runtime từng stage;
- MLflow/Redis volume size.

### 8.2. Hosted resource

- Modal CPU-seconds/memory-seconds/cold starts;
- Upstash stored bytes/commands/bandwidth;
- usage so với free limits;
- actual billed amount;
- teardown date/path.

### 8.3. Zero-cost gate

Không viết “free” chỉ dựa trên pricing page. Phải có dashboard screenshot/export hoặc usage log chứng minh tháng thử nghiệm chưa phát sinh phí bắt buộc.

---

## 9. T8 — Reproducibility audit

### 9.1. Clean-room path

Trên clean clone hoặc fresh temp directory:

```text
make doctor
make bootstrap
make data-sample
make test-e2e
make report-sample
```

Expected:

- không cần Kaggle/cloud credential;
- expected checksums khớp;
- services healthy;
- prediction + lineage metadata xuất hiện;
- teardown không xóa source fixture.

### 9.2. Full-data path

Tài liệu phải nói rõ manual prerequisite accept Kaggle rules. Sau đó:

```text
make data
make build-lakehouse
make benchmark
make report
```

Không cam kết full data chạy trong CI.

### 9.3. Dependency/version audit

- exact lock hash;
- Docker image digest;
- Feast/DuckDB/delta-rs/LightGBM/MLflow versions;
- Bronze/Silver/Gold Delta table versions;
- model/feature/entity versions;
- OS/machine metadata.

---

## 10. T9 — Tài liệu cuối

### 10.1. Architecture final

Phải phản ánh cái đã build, gồm bảng:

| Planned | Built | Deviation reason |
|---|---|---|
| | | |

Thêm data lineage, version boundaries, online/offline state và failure recovery.

### 10.2. Final report

Cấu trúc:

1. Problem và research questions.
2. Dataset suitability/limitations.
3. Temporal/entity/feature contracts.
4. Lakehouse snapshots, architecture và implementation.
5. Experimental protocol.
6. Correctness/model ablation.
7. Pipeline performance ablation.
8. Online parity/freshness/skew.
9. Reliability và cloud portability.
10. Cost/resource.
11. Threats to validity.
12. Conclusion/future work.

### 10.3. Threats to validity bắt buộc

- Entity ID là proxy.
- Absolute event date không thật.
- Created/late-arrival timestamp là synthetic.
- Train split dùng historical dataset tĩnh, không phải live fraud stream.
- Single dataset và single-node compute.
- Model không phải SOTA.
- Cloud demo chỉ materialize curated subset.
- Lakehouse chạy single-writer/local filesystem trong MVP; không chứng minh multi-writer distributed catalog governance.
- Timing phụ thuộc machine/cache/layout.

---

## 11. T10 — TypeScript serving experiment (Nice-to-have)

Đây là experiment sau prototype, không phải acceptance path. Python FastAPI + native LightGBM scorer của Sprint 2 vẫn là reference implementation và fallback bắt buộc.

### 11.1. Entry gate

Chỉ bắt đầu khi:

- tất cả Sprint 2 gates pass;
- Python scoring contract, ordered feature vector và champion manifest đã khóa;
- Sprint 3 correctness/reliability artifacts không còn blocker;
- còn ít nhất hai ngày buffer hoặc cloud path đã bị kill-switch;
- ONNX conversion spike hoàn thành trong tối đa bốn giờ.

Nếu một gate không đạt, chuyển toàn bộ phần này sang post-project backlog mà không ảnh hưởng release.

### 11.2. Scope tối thiểu

```text
services/scoring-ts/
  Fastify + schema validation
  Redis FeatureProvider adapter
  ONNX Runtime Node session
  champion deployment manifest loader
  health/readiness/predict endpoints
```

Service phải dùng đúng request/response contract của Python scorer và trả cùng model/feature/freshness metadata. Không thêm NestJS, message broker, API gateway hoặc một frontend riêng.

Python promotion path tạo immutable deployment bundle:

```text
model.onnx
deployment-manifest.json
ordered-features.json
preprocessing-contract.json
golden-vectors.json
```

### 11.3. Cross-runtime parity gate

Trên ít nhất 1.000 pinned feature vectors:

- Python LightGBM và TypeScript ONNX dùng cùng model/preprocessing versions;
- class output phải giống nhau;
- probability difference nằm trong tolerance đã khóa trước khi chạy;
- categorical/missing/default/float dtype cases đều có golden tests;
- parity fail thì TypeScript service không được gắn alias deployable.

### 11.4. Benchmark protocol

So sánh trên cùng machine, Redis dataset, request set và process limits:

- warm-up rồi ít nhất ba repeated runs;
- batch size 1 là workload chính; thêm batch nhỏ chỉ để quan sát;
- p50/p95/p99 end-to-end latency;
- throughput tại nhiều concurrency levels;
- RSS/CPU, cold start và error rate;
- ghi cả feature retrieval time và inference time để tránh gán mọi chênh lệch cho runtime.

Fastify/TypeScript chỉ thay Python làm demo scorer nếu parity pass và đạt decision threshold đã pre-register. Kết quả ngang hoặc chậm hơn vẫn được báo cáo trung thực; không tuning benchmark để hợp thức hóa lựa chọn ngôn ngữ.

### 11.5. Kill switches

- ONNX conversion/parity spike quá bốn giờ: dừng.
- Sprint 3 core có blocker hoặc còn dưới hai ngày buffer: dừng.
- Preprocessing phải viết lại khác Python contract: dừng và giữ Python.
- Native dependency không build ổn định trong Linux container: dừng.

---

## 12. Demo script

Demo 7–10 phút:

1. Nêu failure mode: feature tương lai làm metric đẹp giả.
2. Mở một synthetic case và cho xem leaky vector sai.
3. Chạy PIT test, future violation bằng 0.
4. Chạy backfill/materialize và show Delta table history + watermark/version.
5. Score một transaction qua API, show lineage metadata.
6. Chạy parity check, mismatch bằng 0.
7. Inject stale/skew record, show detector/alert.
8. Rematerialize, parity phục hồi.
9. Mở experiment table E1–E5/P1–P5.
10. Kết luận trade-off và giới hạn.

Không dành phần lớn video cho Swagger UI hoặc Grafana animation. Bằng chứng correctness là câu chuyện chính.

---

## 13. Release gates

| Gate | Evidence |
|---|---|
| Future-read violation = 0 | temporal audit report + tests |
| Label absent from lineage | feature lineage artifact |
| Offline/online mismatch = 0 | replay parity raw result |
| Backfill reproducible | repeated checksums/manifests |
| Snapshot reproducible | time travel exact Delta versions -> same checksum |
| Injected skew detected | reliability report + alert |
| Version mismatch blocked | integration/fault test |
| Model promotion/rollback reproducible | aliases + deployment manifests + R12 evidence |
| E1–E5/P1–P5 completed | experiment manifest + reports |
| Clean sample reproduction | clean-room log |
| Full-data result traceable | dataset/feature/code/run IDs |
| Zero mandatory cost | usage/cost report |
| Cloud or fallback demo works | smoke-test evidence |
| Limitations documented | final report threats-to-validity |

Không release nếu correctness gate fail, dù cloud demo/model metric đẹp.

TypeScript artifacts S3-A13/A14 không nằm trong release gates. Nếu được build, chúng chỉ xuất hiện trong demo sau câu chuyện PIT correctness và phải kèm parity/benchmark evidence.

---

## 14. Lịch 10 ngày làm việc

| Ngày | Việc | Artifact |
|---|---|---|
| 1 | Freeze experiment manifest + runner | S3-A1, A2 |
| 2 | Run E1–E4 | S3-A2 |
| 3 | Analyze correctness/model ablation | S3-A3 |
| 4 | Run P1–P5 | S3-A2, A4 |
| 5 | Monitoring metrics/dashboard | S3-A5 |
| 6 | Fault/skew injection suite | S3-A6 |
| 7 | Modal/Upstash integration hoặc fallback | S3-A7 |
| 8 | Cloud smoke + cost/resource + clean-room | S3-A8 |
| 9 | Architecture final, README, demo recording | S3-A9, A10, A12 |
| 10 | Final report, release audit, tag | S3-A11 |

Conditional buffer: chỉ dùng ngày 8–9 cho S3-A13/A14 nếu cloud path đã hoàn tất hoặc bị kill-switch và core release evidence đã ổn. Không dời final report để cứu TypeScript prototype.

---

## 15. Điều đáng nói nhất khi bảo vệ

1. **PIT correctness là invariant, không phải một SQL trick.** Thêm future data không được thay đổi feature vector của quá khứ; test chứng minh điều đó.
2. **Training và serving được nối bằng versioned feature contract.** Mismatch được đo ở từng entity/cutoff, không chỉ nhìn model score.
3. **Backfill là một stateful, idempotent data product.** Cùng snapshot/version/range tạo cùng checksum; late event chỉ invalidate range bị ảnh hưởng.
4. **Leaky model có thể trông tốt hơn nhưng không deployable.** Đây là ví dụ Outcome over Output: metric đẹp không có giá trị nếu dữ liệu không tồn tại tại decision time.
5. **Cloud là deployment target, không phải bản chất đề tài.** Correctness chạy được local; hosted path chỉ chứng minh portability và online boundary.
