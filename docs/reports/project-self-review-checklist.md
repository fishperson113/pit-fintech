# PIT Fintech — Project Self-Review Checklist

Checklist này dùng ở cuối mỗi sprint, trước demo và trước khi gọi project là
**engineering portfolio-ready** hoặc **thesis-ready**. Điểm số chỉ có ý nghĩa khi đi kèm evidence
có thể chạy lại; screenshot và mô tả kiến trúc không được tính là bằng chứng implementation.

Checklist này đánh giá implementation và evidence. Để kiểm tra người thực hiện có thật sự hiểu
sâu, tính tay được temporal cases, chẩn đoán được biến thể và bảo vệ trade-off, dùng thêm
[Knowledge Defense Checklist](knowledge-defense-checklist.md).

## 1. Review snapshot

Copy khối này cho mỗi lần review:

```text
Review date:
Reviewer:
Sprint / milestone:
Code commit:
Dependency lock hash:
Dataset snapshot ID:
Bronze / Silver / Gold versions:
Feature definition / service version:
Model version / MLflow run ID:
Previous score:
Current score:
Hard-gate result: PASS / FAIL
Top improvement since last review:
Largest unresolved risk:
Next evidence-producing action:
```

Trạng thái cho từng mục:

- `[ ]` chưa có hoặc mới planned;
- `[~]` đã implemented nhưng chưa verify đủ acceptance cases;
- `[x]` đã verified bằng command và artifact được link;
- `[!]` blocked; ghi nguyên nhân và điều kiện unblock.

## 2. Hard gates — bắt buộc pass

Nếu bất kỳ mục nào dưới đây fail, project chưa được gọi là portfolio-ready hoặc thesis-ready,
bất kể tổng điểm.

- [ ] Dataset, entity, event time, tie-break và created-time policy đã được khóa bằng EDA + ADR.
- [ ] Future-read violations bằng `0` trên synthetic temporal oracle.
- [ ] Label/post-outcome fields không xuất hiện trong feature lineage.
- [ ] Transaction `t` luôn được score trước khi state của chính `t` được ghi vào Redis/history.
- [ ] Offline/online parity: integer/categorical mismatch bằng `0`; float nằm trong tolerance đã khóa.
- [ ] Duplicate/replayed event không double-count.
- [ ] Cùng input/version/range tạo cùng schema, row count và canonical checksum.
- [ ] Exact Delta source versions tái tạo cùng training dataset checksum.
- [ ] Partial backfill không publish half-committed output; retry/resume an toàn.
- [ ] Model/feature version mismatch bị reject hoặc làm service `ready=false`.
- [ ] Raw → Silver → Gold reconciliation pass cho range được review.
- [ ] Clean clone chạy được synthetic E2E path bằng command đã document.
- [ ] Known injected faults được detect, xử lý và lưu recovery evidence đúng expected status.

**Hard-gate evidence:**

```text
Commands:
Artifacts:
Failures / deviations:
```

## 3. Weighted engineering scorecard

Chấm maturity cho từng nhóm từ `0` đến `4`, sau đó tính:

```text
weighted_score = group_weight × maturity / 4
```

| Maturity | Ý nghĩa |
|---:|---|
| 0 | Chưa có |
| 1 | Có design/plan nhưng chưa chạy |
| 2 | Happy path chạy được |
| 3 | Acceptance tests và edge cases chính pass |
| 4 | Clean-room, fault/change case và machine-readable evidence đều pass |

### A. Problem và data understanding — 10 điểm

- [ ] Problem statement phân biệt rõ fraud-model training, online serving và observability.
- [ ] PaySim được profile về temporal structure, entity history, imbalance và leakage risk.
- [ ] Grain, primary event key, entity key và deterministic ordering được giải thích.
- [ ] Availability time của mọi feature được phân loại; post-outcome fields bị loại.
- [ ] Quyết định PaySim/IEEE-CIS/Home Credit được ghi bằng ADR thay vì chọn theo cảm tính.
- [ ] Feature scope được khóa sau EDA; model family chỉ được khóa sau data evidence.

**Maturity:** `__/4` · **Weighted:** `__/10` · **Evidence:**

### B. Temporal và incremental correctness — 20 điểm

- [ ] Synthetic oracle bao phủ future row, duplicate, tie, late arrival, no-history và boundary.
- [ ] PIT implementation nằm trong `src/`; notebook không phải correctness authority.
- [ ] Full, range và incremental backfill có cùng contract và deterministic ordering.
- [ ] Watermark/checkpoint và idempotency key được lưu trong immutable manifest.
- [ ] Late event chỉ invalidate/rebuild range bị ảnh hưởng.
- [ ] Retry cùng logical input không tạo duplicate commit/output.
- [ ] Atomic publish và recovery sau interrupted run được test.
- [ ] P3 Delta full recompute và P4 Delta incremental dùng cùng storage format để so sánh công bằng.

**Maturity:** `__/4` · **Weighted:** `__/20` · **Evidence:**

### C. Storage, reconciliation và change handling — 15 điểm

- [ ] Bronze, Silver và Gold có grain, schema, partition và ownership rõ ràng.
- [ ] Raw archive immutable; mọi derived artifact truy ngược được source snapshot/version.
- [ ] Reconciliation tối thiểu có row count, distinct transaction count, amount totals và time range.
- [ ] Bad records được reject/quarantine có reason thay vì silently drop.
- [ ] Compatible schema evolution được test, ví dụ thêm nullable column.
- [ ] Breaking schema change bị chặn trước commit hoặc tạo explicit new contract version.
- [ ] Một change request thực tế được triển khai cùng migration/backfill/regression test.
- [ ] DuckDB/Delta layout decision dựa trên access pattern và measured evidence.

**Maturity:** `__/4` · **Weighted:** `__/15` · **Evidence:**

### D. Python, SQL và software engineering — 15 điểm

- [ ] Code được chia theo module/boundary; không có một script hoặc notebook làm toàn bộ hệ thống.
- [ ] Makefile/PowerShell command contract chạy cùng semantics ở local và CI.
- [ ] Config tách khỏi code; secret không commit và không xuất hiện trong log.
- [ ] Dependency lock, seed, exit code và error messages đủ để debug/reproduce.
- [ ] Unit, integration, temporal và E2E tests có vai trò tách biệt.
- [ ] CI chạy fixture lane nhanh và fail đúng khi invariant bị phá.
- [ ] SQL thể hiện ASOF/window/aggregation reasoning, không chỉ gọi library wrapper.
- [ ] Có `EXPLAIN`/profiling hoặc bytes/files/partitions scanned trước khi kết luận tối ưu.

**Maturity:** `__/4` · **Weighted:** `__/15` · **Evidence:**

### E. Training và model lifecycle — 10 điểm

- [ ] Model family/config được chọn sau PaySim EDA và giữ cố định cho E1–E5.
- [ ] Train/validation/test split theo thời gian; random split chỉ là controlled comparison.
- [ ] PR-AUC là primary metric; recall tại fixed FPR và ROC-AUC là secondary.
- [ ] MLflow run ghim dataset, Delta, feature, model, code và dependency versions.
- [ ] Candidate không được promote khi correctness/parity/schema gate fail.
- [ ] `candidate`, `champion`, `previous` có audit manifest và rollback command.
- [ ] Không tune model để che leakage hoặc correctness failure.

**Maturity:** `__/4` · **Weighted:** `__/10` · **Evidence:**

### F. Online serving và parity — 15 điểm

- [ ] `FeatureProvider` tách retrieval khỏi model scoring và có contract tests.
- [ ] Redis giữ latest post-event state; Gold training row không bị dùng sai làm online state.
- [ ] Replay xử lý xong event `t` trước khi phát `t+1`.
- [ ] API trả model/feature version, feature timestamp, watermark và freshness status.
- [ ] Missing entity, stale feature, schema mismatch và Redis timeout có explicit policy.
- [ ] Replay so sánh offline/online vector tại nhiều checkpoint và lưu mismatch taxonomy.
- [ ] Retrieval, inference và end-to-end latency được đo trên workload đã version.
- [ ] Redis reset rồi rematerialize tới watermark và parity phục hồi.

**Maturity:** `__/4` · **Weighted:** `__/15` · **Evidence:**

### G. Operations, observability và incident response — 10 điểm

- [ ] Structured logs có request/run ID, versions, status và latency; không log sensitive payload.
- [ ] Metric semantics cho freshness, parity, backfill, serving và version mismatch được document.
- [ ] OpenTelemetry instrumentation phát telemetry độc lập với việc Grafana có online hay không.
- [ ] Prometheus/Grafana dashboard hiển thị đúng evidence; dashboard không thay raw metrics/logs.
- [ ] Alert threshold xuất phát từ invariant/SLA thay vì chọn tùy ý.
- [ ] Fault matrix bao phủ duplicate, late event, schema drift, partial output, stale state và timeout.
- [ ] Có ít nhất một incident drill: scope → root cause → recovery → regression test.
- [ ] Incident có postmortem ngắn, owner và preventive action được verify ở review sau.

**Maturity:** `__/4` · **Weighted:** `__/10` · **Evidence:**

### H. Research, trade-off và scale reasoning — 5 điểm

- [ ] Mọi claim phân biệt rõ planned, implemented và verified.
- [ ] E1–E5/P1–P5 có frozen protocol, raw artifact và honest exclusions.
- [ ] Báo cáo nêu limitations/threats: synthetic time, proxy entity, single dataset và single-node.
- [ ] Có scale-up design exercise cho fraud `<5 phút` và reporting `T+1` ở workload lớn.
- [ ] Thiết kế giải thích khi nào mới cần Kafka/Flink/Spark/warehouse và invariant nào phải giữ.
- [ ] Có thể giải thích trade-off mà không dựa vào tên công nghệ hoặc architecture screenshot.

**Maturity:** `__/4` · **Weighted:** `__/5` · **Evidence:**

## 4. Tổng hợp kết quả

| Nhóm | Weight | Maturity 0–4 | Weighted score | Evidence link |
|---|---:|---:|---:|---|
| A. Problem/data understanding | 10 | | | |
| B. Temporal/incremental correctness | 20 | | | |
| C. Storage/reconciliation/change | 15 | | | |
| D. Python/SQL/software engineering | 15 | | | |
| E. Training/model lifecycle | 10 | | | |
| F. Online serving/parity | 15 | | | |
| G. Operations/observability/incident | 10 | | | |
| H. Research/design/scale | 5 | | | |
| **Total** | **100** | | **__/100** | |

Diễn giải điểm, chỉ áp dụng khi hard gates pass:

| Score | Cách gọi trung thực |
|---:|---|
| 0–39 | Concept/demo; phần lớn mới planned hoặc happy path |
| 40–59 | Engineering foundation đã hình thành |
| 60–74 | Verified local MVP |
| 75–89 | Engineering portfolio-ready |
| 90–100 | Thesis-ready candidate; vẫn không đồng nghĩa production-ready |

## 5. Retrospective bắt buộc

Trả lời ngắn, kèm evidence khi có thể:

1. Invariant nào có bằng chứng mạnh nhất? Invariant nào vẫn chỉ là assumption?
2. Fault/change case nào làm thiết kế thay đổi nhiều nhất?
3. Pipeline đang fail loudly ở đâu và có thể silently wrong ở đâu?
4. Một metric/dashboard hiện tại có dẫn tới action cụ thể hay chỉ để trình diễn?
5. Công nghệ nào đang giải quyết vấn đề thật? Công nghệ nào có thể bỏ mà outcome không đổi?
6. Nếu dữ liệu tăng 100×, bottleneck đầu tiên là compute, storage, state hay operations?
7. Điểm nào tốt hơn review trước nhờ feedback? Cùng một lỗi có lặp lại không?
8. Việc duy nhất nên làm tiếp theo để tăng evidence, không chỉ tăng feature, là gì?

## 6. Sources of truth

- [Project proposal](../feature-store/point-in-time-feature-store-proposal.md)
- [Sprint 1 guide](../feature-store/sprint-1-implementation-guide.md)
- [Sprint 2 guide](../feature-store/sprint-2-implementation-guide.md)
- [Sprint 3 guide](../feature-store/sprint-3-implementation-guide.md)
- [Current project status](../../artifacts/changelog/PROJECT_STATUS.md)
- [Cumulative changelog](../../artifacts/changelog/CHANGELOG.md)
- [Knowledge defense checklist](knowledge-defense-checklist.md)
