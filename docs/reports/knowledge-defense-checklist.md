# PIT Fintech — Knowledge Defense Checklist

Checklist này trả lời câu hỏi khác với
[project-self-review-checklist](project-self-review-checklist.md):

- checklist implementation hỏi **hệ thống và evidence đã làm được gì**;
- checklist này hỏi **người làm project thật sự hiểu gì và có tự bảo vệ được quyết định không**.

Không đánh dấu `[x]` chỉ vì đã viết code, chạy được command, nghe quen thuật ngữ hoặc có thể đọc
lại tài liệu. Chỉ đánh dấu khi có thể giải thích bằng lời của mình, xử lý một biến thể chưa học
thuộc và chỉ ra evidence trong repo dùng để bác bỏ một implementation sai.

## 1. Chuẩn “hiểu sâu” dùng cho toàn project

### 1.1. Thang độ sâu

| Mức | Năng lực quan sát được | Có được tính là hiểu không? |
|---:|---|---|
| D0 | Đã nghe thuật ngữ nhưng giải thích mơ hồ | Không |
| D1 | Nêu được định nghĩa hoặc vai trò công cụ | Chưa đủ |
| D2 | Tự cho ví dụ, phân biệt với khái niệm gần giống và giải thích vì sao project cần nó | Đủ cho khái niệm phụ |
| D3 | Tính tay/suy luận được case lạ, dự đoán failure mode và thiết kế test bắt lỗi | Chuẩn pass cho concept cốt lõi |
| D4 | Bảo vệ trade-off, liên kết code với invariant/evidence, nêu limitation và đổi thiết kế khi assumption thay đổi | Chuẩn cuối project |

Một concept cốt lõi chỉ được check khi đạt ít nhất D3. Cuối Sprint 3, các invariant chính phải
đạt D4.

### 1.2. Bài test bốn lớp cho mỗi concept

Với mỗi mục bên dưới, tự hỏi:

1. **Nói:** Tôi có giải thích trong 60–90 giây, không đọc note và không núp sau tên công nghệ?
2. **Vẽ/tính:** Tôi có vẽ timeline, grain, state transition hoặc tính tay expected output?
3. **Phá:** Tôi có đưa ra một implementation trông hợp lý nhưng sai và test để bắt nó?
4. **Chứng minh:** Tôi có chỉ đúng artifact, command, manifest hoặc metric chứng minh claim?

Thiếu lớp 2 hoặc 3 nghĩa là mới nhớ lý thuyết. Thiếu lớp 4 nghĩa là hiểu concept nhưng chưa chứng
minh được project của mình.

### 1.3. Cách tự review

- Làm closed-note trong 45–60 phút trước, sau đó mới mở code/docs để sửa.
- Nhờ reviewer đổi timestamp, đảo input order, thêm duplicate hoặc thay assumption; không chỉ
  hỏi lại đúng fixture đã thuộc.
- Với mỗi câu sai, ghi một trong bốn nguyên nhân: thiếu định nghĩa, sai mental model, không nối
  được với code, hoặc không biết evidence.
- Một câu chỉ pass khi trả lời đúng hai lần ở hai ngày khác nhau và ít nhất một lần có biến thể.
- AI và tài liệu được dùng để học; phần oral defense cuối cùng phải nói bằng lời của chính mình.

---

# 2. Sprint 1 — Temporal contract, data understanding và correctness

## Chuẩn đầu ra trong đầu

Sau Sprint 1, bạn chưa cần là chuyên gia distributed system. Nhưng bạn phải đạt D3 với temporal
semantics, leakage, grain/entity/order, oracle và test correctness. Bạn phải có thể nhìn một bảng
event nhỏ, tự tính feature vector tại cutoff, tìm future read và giải thích chính xác tại sao query
sai. Nếu còn lẫn `event time`, `created time`, `cutoff`, `window boundary`, PIT join và temporal
split thì Sprint 1 chưa thật sự xong dù tests đang xanh.

## 2.1. Problem framing và invariant

- [ ] Tôi giải thích được feature store này giải quyết hai bài toán khác nhau: dựng historical
  training vector và lấy pre-decision online vector.
- [ ] Tôi phát biểu được ba invariant mà không nhìn tài liệu: không đọc tương lai; offline/online
  parity; backfill atomic, idempotent và reproducible.
- [ ] Tôi giải thích được vì sao model metric cao không chứng minh feature pipeline đúng.
- [ ] Tôi phân biệt ground truth cho temporal correctness (synthetic oracle) với ground truth cho
  model evaluation (fraud label).
- [ ] Tôi giải thích được vì sao đây là paper-inspired adaptation, không phải reproduction của
  FeathrPO/Spark paper và không được claim speedup của paper.
- [ ] Tôi chỉ ra được phần nào hiện `planned`, `implemented`, `verified`; tôi không dùng sơ đồ
  target architecture như bằng chứng runtime.

**Câu hỏi biến thể phải trả lời được**

1. Nếu PR-AUC tăng 20% nhưng future-read violations > 0, có ship model không? Vì sao?
2. Nếu temporal tests pass trên PaySim nhưng synthetic oracle fail một boundary case, nguồn sự
   thật nào thắng?
3. Nếu bỏ Feast mà ba invariant vẫn được bảo đảm, đề tài còn hợp lệ không? Boundary nào phải tự
   thay thế?

## 2.2. Grain, key, entity và ordering

- [ ] Tôi nói được grain của raw event, canonical event, Gold feature row, online state và
  prediction record; tôi không gọi chung tất cả là “một transaction table”.
- [ ] Tôi phân biệt event key với entity key: event key nhận diện một sự kiện; entity key gom
  history dùng để tạo feature.
- [ ] Tôi giải thích được vì sao entity definition là một giả thuyết cần EDA, không chỉ là thao
  tác hash vài cột.
- [ ] Tôi đánh giá được entity candidate bằng repeated history, cardinality, collision/unknown
  rate và ý nghĩa nghiệp vụ.
- [ ] Tôi giải thích được canonicalization trước khi hash: dtype, missing sentinel, separator,
  version và numeric-like category phải ổn định.
- [ ] Tôi phân biệt primary key, deduplication key và deterministic sort/tie-break key.
- [ ] Tôi giải thích được tại sao same timestamp vẫn cần tie-break và tại sao input file order
  không được là tie-break ngầm.
- [ ] Tôi phân biệt exact duplicate với conflicting duplicate và nêu policy đúng cho từng loại.
- [ ] Tôi dự đoán được entity key quá rộng hoặc quá hẹp sẽ làm history feature sai/ít hữu dụng thế
  nào.

**Bài thực hành không nhìn code**

- Cho 8 rows có hai entity, một ID trùng và hai event cùng timestamp: viết lại canonical order,
  chỉ ra row deduplicate, row phải reject và grain sau mỗi bước.
- Đổi một thành phần entity từ integer `123` thành string `"123.0"`: giải thích khi nào chúng
  cùng identity, khi nào không, và contract version nào chịu trách nhiệm.

## 2.3. Temporal semantics — phần không được “ngơ ngơ”

- [ ] Tôi định nghĩa được `event time`: lúc sự kiện xảy ra trong domain.
- [ ] Tôi định nghĩa được `created/knowledge/availability time`: lúc hệ thống thực sự có thể biết
  record.
- [ ] Tôi định nghĩa được prediction cutoff như ranh giới thông tin được phép dùng khi ra quyết
  định, không chỉ là một timestamp filter.
- [ ] Tôi phân biệt processing time với event time và giải thích vì sao late arrival làm hai mốc
  này khác nhau.
- [ ] Tôi giải thích được temporal view là góc nhìn logic tại một thời điểm, không nhất thiết là
  SQL `VIEW`.
- [ ] Tôi viết được predicate PIT đầy đủ theo contract: entity khớp, event order strictly before
  cutoff, created time đã available, và row nằm trong window.
- [ ] Tôi giải thích được strict `<` ở upper bound và inclusive lower bound của window bằng một
  ví dụ tính tay.
- [ ] Tôi giải thích được lexicographic cutoff `(event_timestamp, transaction_id)` và tác dụng của
  tie-break.
- [ ] Tôi phân biệt future event với late-arriving past event: một cái xảy ra sau cutoff; cái kia
  xảy ra trước nhưng chưa được biết tại cutoff.
- [ ] Tôi giải thích được pre-decision feature và post-event state bằng transition:
  `state_before -> score(t) -> state_after`.
- [ ] Tôi chứng minh được tại sao transaction hiện tại có thể dùng request field như `amount`
  nhưng không được tự xuất hiện trong `count_1h_before`.
- [ ] Tôi giải thích được no-history/default policy là một phần feature contract, không phải chi
  tiết tùy tiện của code.
- [ ] Tôi biết window theo event count khác window theo elapsed time và không lẫn hai loại.

**Phân biệt bắt buộc**

| Cặp dễ lẫn | Câu trả lời phải nêu được |
|---|---|
| Event time vs created time | Xảy ra khi nào vs hệ thống biết khi nào |
| Cutoff vs watermark | Ranh giới của một decision vs mức online state đã cập nhật tới |
| PIT join vs temporal split | Correctness của từng feature row vs chronology giữa train/test |
| Future event vs late arrival | Xảy ra sau cutoff vs xảy ra trước nhưng đến sau |
| Current request field vs history feature | Field đang có trên request vs aggregate chỉ từ state trước request |
| Pre-decision vector vs post-event state | Input để score vs state sau khi commit event |
| Timestamp tie vs duplicate | Cùng thời gian không đồng nghĩa cùng event |
| Freshness vs parity | Mới/cũ so với cutoff vs hai implementation có khớp nhau không |

**Bài tính tay bắt buộc**

Với ít nhất sáu event gồm future row, duplicate, same-time tie, late arrival, no history và đúng
window boundary, bạn phải tự viết:

1. canonical event order;
2. rows được biết tại từng cutoff;
3. rows thuộc từng window;
4. expected `count`, `sum`, `mean`, `last` và default;
5. vector trước score và state sau update;
6. row nào một query leaky sẽ đọc nhầm.

Nếu không làm được trên giấy, không check bất kỳ mục temporal core nào.

## 2.4. Leakage và evaluation design

- [ ] Tôi phân biệt target leakage, future leakage, post-outcome field và training-serving skew.
- [ ] Tôi giải thích được tại sao balance columns hoặc policy output có thể nguy hiểm dù có mặt
  trong raw dataset.
- [ ] Tôi audit được feature availability: field tồn tại ở source không có nghĩa field available
  tại decision time.
- [ ] Tôi giải thích được random split có thể lạc quan trên temporal data nhưng không tự động biến
  mọi feature thành target leakage.
- [ ] Tôi giải thích được vì sao cần cả PIT-correct features và temporal split.
- [ ] Tôi hiểu E1–E4 như controlled comparisons: static/temporal, leaky/random, PIT/random,
  PIT/temporal.
- [ ] Tôi giải thích được positive control E2 dùng để kiểm tra experiment có nhìn thấy leakage,
  không phải baseline để deploy.
- [ ] Tôi giải thích được vì sao PR-AUC là primary metric trong fraud imbalance; accuracy,
  ROC-AUC và recall@fixed-FPR trả lời câu hỏi gì khác.
- [ ] Tôi không chọn model family trước EDA chỉ vì LightGBM phổ biến.

**Câu hỏi biến thể**

1. PIT features + random split có leakage không? Trả lời phải tách feature leakage khỏi
   evaluation optimism.
2. Temporal split + full-history aggregate có hợp lệ không? Giải thích tại sao split đúng không
   cứu được feature row sai.
3. Một field được ghi cùng transaction nhưng chỉ hoàn tất sau investigation ba ngày: event time
   và availability policy nên đặt thế nào?

## 2.5. Oracle, tests và evidence

- [ ] Tôi giải thích được oracle là implementation tham chiếu ưu tiên rõ ràng/correctness, không
  phải model và không nhất thiết tối ưu.
- [ ] Tôi giải thích được vì sao expected fixture phải tính tay hoặc độc lập với implementation
  đang test.
- [ ] Tôi phân biệt example-based test, invariant/property test và differential test.
- [ ] Tôi giải thích được metamorphic test “thêm future row không đổi past vector”.
- [ ] Tôi biết một test có thể xanh giả nếu expected và actual dùng chung helper sai.
- [ ] Tôi phân biệt test coverage dòng code với coverage của temporal state space.
- [ ] Tôi thiết kế được test cho future, duplicate, tie, late arrival, no history, lower boundary,
  score-before-update và conflicting duplicate.
- [ ] Tôi đọc failure diff để chỉ ra predicate nào sai thay vì sửa expected cho test xanh.
- [ ] Tôi liên kết được claim `future-read violations = 0` với exact command và fixture evidence,
  không với screenshot.

**Live challenge**

Reviewer sửa một trong bốn thứ: `<` thành `<=`, bỏ created-time predicate, bỏ tie-break, hoặc
update state trước score. Bạn phải:

1. dự đoán test nào fail trước khi chạy;
2. tạo minimal counterexample;
3. giải thích business impact;
4. sửa đúng layer, không hard-code fixture.

## 2.6. Storage, lakehouse và reproducibility foundation

- [ ] Tôi phân biệt CSV/JSONL/Parquet về schema, row/column access, compression và use case; không
  chỉ nói “Parquet nhanh hơn”.
- [ ] Tôi giải thích được columnar scan, projection/filter pushdown và partition pruning ở mức
  query plan.
- [ ] Tôi nêu grain, schema và trách nhiệm của Bronze, Silver, Gold; tôi biết medallion chỉ thuộc
  offline path.
- [ ] Tôi giải thích được raw immutable archive khác canonical Silver như thế nào.
- [ ] Tôi phân biệt Parquet file với Delta table: data files so với transaction log, snapshot,
  schema/commit semantics và time travel.
- [ ] Tôi hiểu DuckDB là compute/query engine; Delta là versioned offline storage contract. Không
  công cụ nào tự bảo đảm PIT correctness.
- [ ] Tôi giải thích được snapshot ID, table version, checksum và canonical checksum khác nhau.
- [ ] Tôi giải thích được vì sao hash raw Parquet bytes không luôn là logical data checksum.
- [ ] Tôi hiểu time travel chỉ ghim data version; muốn reproduce còn cần feature/code/dependency
  versions, ordering, seed và manifest.
- [ ] Tôi đọc được một `EXPLAIN` đơn giản và nhận ra full scan, filter, join, aggregation.

## 2.7. Python, SQL và engineering fundamentals

- [ ] Tôi lần theo được data từ CLI -> contract -> canonicalization -> oracle -> test, không xem
  notebook là pipeline executor.
- [ ] Tôi giải thích được tại sao pure function và typed contract giúp test temporal logic.
- [ ] Tôi biết validation nên xảy ra trước transformation/commit nào và bad record phải
  reject/quarantine ra sao.
- [ ] Tôi viết được SQL có filter, CTE, window/aggregate và deterministic ordering cho một feature
  nhỏ.
- [ ] Tôi nhận ra join làm tăng row count ngoài ý muốn do sai grain hoặc many-to-many.
- [ ] Tôi debug theo hướng input -> first divergent layer -> minimal reproduction -> regression
  test, không thử sửa ngẫu nhiên.
- [ ] Tôi phân biệt unit, temporal, integration và E2E tests cùng failure mà mỗi loại nên bắt.
- [ ] Tôi giải thích được dependency lock, config, seed, exit code và structured error giúp
  reproducibility/debug thế nào.

## 2.8. Gate kiến thức Sprint 1

Sprint 1 chỉ được gọi là **knowledge-pass** khi:

- [ ] Temporal core đạt D3; bài tính tay đúng 100% trên ít nhất hai fixture khác nhau.
- [ ] Trong 15 phút, tôi tìm được bug cho một unseen temporal mutation và viết test mô tả đúng
  failure.
- [ ] Tôi bảo vệ được ADR entity/time/tie/created-time policy và chỉ rõ phần nào còn provisional.
- [ ] Tôi giải thích được PaySim viability, leakage risk và limitation bằng EDA evidence, không
  nói theo cảm giác.
- [ ] Tôi trình bày được Sprint 1 trong 5 phút mà không biến phần nói thành danh sách công nghệ.
- [ ] Tôi trả lời đúng ít nhất 8/10 câu hỏi biến thể và không sai bất kỳ hard-invariant question
  nào.

---

# 3. Sprint 2 — Feature platform, backfill, parity và model lifecycle

## Chuẩn đầu ra trong đầu

Sau Sprint 2, bạn phải đạt D3 với contract, backfill, replay, parity, state, version gate và
recovery; đạt D4 với ba invariant. Bạn phải giải thích được một event đi qua offline và online
paths, biết state nằm ở đâu, commit nào là atomic boundary và hệ thống phục hồi từ manifest nào.

## 3.1. Feature contract và offline/online boundary

- [ ] Tôi mô tả được một FeatureSpec đầy đủ: name, dtype, entity, source, window, cutoff
  semantics, default, version và tolerance.
- [ ] Tôi giải thích được thay đổi nào compatible và thay đổi nào bắt buộc bump feature version.
- [ ] Tôi phân biệt feature definition, feature service, feature vector, Gold table và Redis
  online state.
- [ ] Tôi giải thích được Feast chỉ là contract/registry/retrieval/materialization mỏng; custom PIT
  oracle vẫn là correctness authority.
- [ ] Nếu bỏ Feast, tôi liệt kê được các trách nhiệm phải tự làm: versioned spec, provider,
  retrieval/materialization, lineage, namespace và compatibility gate.
- [ ] Tôi giải thích được `FeatureProvider` boundary giúp test, serving và store replacement thế
  nào.
- [ ] Tôi biết Gold historical row không đồng nghĩa Redis state và không copy mù một row training
  sang online.

## 3.2. Full/range/incremental backfill

- [ ] Tôi phân biệt full load, range backfill và incremental processing bằng input range, reused
  state và output contract.
- [ ] Tôi giải thích được watermark/checkpoint, idempotency key và run manifest; không dùng ba
  khái niệm thay nhau.
- [ ] Tôi phát biểu được identity của logical backfill:
  dataset snapshot + entity/feature version + cutoff range.
- [ ] Tôi phân biệt atomic, idempotent và reproducible bằng ba failure example khác nhau.
- [ ] Tôi chỉ ra staging, validation và publish/commit boundary bảo vệ khỏi half-output.
- [ ] Tôi mô tả được retry trước commit, sau commit nhưng trước acknowledgement, và recovery sau
  process crash.
- [ ] Tôi giải thích được late event invalidates range nào dựa trên feature windows và downstream
  dependency.
- [ ] Tôi hiểu incremental output phải được differential-check với full recompute reference.
- [ ] Tôi giải thích được why P3-vs-P4 giữ cùng Delta format để cô lập tác động của reuse.
- [ ] Tôi biết rerun “không duplicate” chưa đủ; còn phải so schema, row count, canonical checksum
  và lineage.
- [ ] Tôi phân biệt data snapshot rollback, feature version rollback và model rollback.

**Failure drill**

Job chết sau khi viết 70% files; source gửi lại batch; một late event nằm trước range start; schema
thêm nullable column. Với mỗi case, bạn phải chỉ ra:

1. trạng thái nào đã durable;
2. reader nhìn thấy gì;
3. retry chọn manifest/idempotency key nào;
4. range nào rebuild;
5. gate nào xác nhận recovery đúng.

## 3.3. Redis, chronological replay và parity

- [ ] Tôi mô tả chính xác vòng đời một event:
  receive -> validate -> read history strictly before `t` -> build vector -> score -> write
  post-event state -> append history -> advance.
- [ ] Tôi giải thích được tại sao replay chỉ cần một logical ordered producer cho MVP và invariant
  nào sẽ khó hơn khi có concurrency/partitioning.
- [ ] Tôi phân biệt ordered replay với production streaming; biết điều gì replay chứng minh và
  không chứng minh.
- [ ] Tôi thiết kế Redis key namespace theo environment, feature service/version và entity.
- [ ] Tôi biết online state nào cần giữ để window eviction, duplicate detection và recovery còn
  đúng.
- [ ] Tôi giải thích được watermark, freshness lag, stale policy và missing-entity policy.
- [ ] Tôi phân biệt parity mismatch, stale-but-equal, fresh-but-skewed và missing feature.
- [ ] Tôi biết parity gate so feature vector theo entity/cutoff/version, không chỉ so prediction.
- [ ] Tôi giải thích được float tolerance phải khóa trước experiment và vì sao integer/categorical
  không có tolerance.
- [ ] Tôi mô tả được reset Redis -> rematerialize tới watermark -> replay/checkpoint -> parity
  recovery.
- [ ] Tôi thiết kế được duplicate/replay protection mà không dựa vào “Redis chắc chỉ nhận một
  lần”.

## 3.4. Training, evaluation và MLflow

- [ ] Tôi giải thích được train/validation/test temporal cutoffs, embargo nếu có và cách tránh
  preprocessing fit trên future partition.
- [ ] Tôi biết class imbalance ảnh hưởng threshold, precision/recall và accuracy thế nào.
- [ ] Tôi giải thích được PR-AUC, ROC-AUC và recall@fixed-FPR bằng operational trade-off, không
  chỉ công thức.
- [ ] Tôi bảo vệ model-family choice bằng EDA/runtime/interpretability evidence và giữ config
  cố định cho E1–E5.
- [ ] Tôi phân biệt model artifact, model version, MLflow run, registry alias và immutable
  deployment manifest.
- [ ] Tôi liệt kê được lineage tối thiểu của training run: dataset snapshot, Delta versions,
  feature version, code commit, dependency lock, seed và run ID.
- [ ] Tôi giải thích được `candidate`, `champion`, `previous`; promotion và rollback thay đổi gì,
  không thay đổi gì.
- [ ] Tôi biết model metric pass không được override parity/schema/version gate.
- [ ] Tôi giải thích được model/feature compatibility check ở readiness và scoring boundary.

## 3.5. API, failure semantics và E2E

- [ ] Tôi phân biệt liveness, readiness và scoring success.
- [ ] Tôi biết response cần trả request ID, model/feature version, feature timestamp/watermark và
  freshness status để audit.
- [ ] Tôi nêu explicit policy cho unknown entity, stale feature, schema mismatch, Redis timeout
  và version mismatch.
- [ ] Tôi giải thích bounded retry chỉ dùng cho transient failure; validation/version mismatch
  phải fail fast.
- [ ] Tôi biết khi nào trả fallback prediction, explicit 4xx/5xx hoặc `ready=false`, và rủi ro
  silent default.
- [ ] Tôi lần theo được một `make test-e2e` từ raw/sample đến prediction và xác định artifact nào
  chứng minh từng gate.
- [ ] Tôi phân biệt exactly-once claim với effective-once outcome nhờ idempotency + durable
  commit; không hứa transport exactly-once mơ hồ.

## 3.6. Gate kiến thức Sprint 2

- [ ] Tôi vẽ được offline/training/online paths và tất cả state/version boundaries từ trí nhớ.
- [ ] Tôi xử lý đúng một crash/retry/late-event scenario chưa gặp trước đó.
- [ ] Tôi giải thích được ba invariant bằng actual manifest/checksum/parity evidence.
- [ ] Tôi tìm được root cause của một parity mismatch bằng cách so contract, cutoff, default,
  ordering, dtype và state update order.
- [ ] Tôi bảo vệ được Feast/DuckDB/Delta/Redis/FastAPI/MLflow role boundary mà không nói công cụ
  nào “tự bảo đảm correctness”.
- [ ] Tôi trả lời đúng ít nhất 8/10 câu biến thể và không sai atomicity, idempotency,
  reproducibility, score-before-update hoặc version-gate questions.

---

# 4. Sprint 3 — Evidence, operations, research và scale reasoning

## Chuẩn đầu ra trong đầu

Sau Sprint 3, bạn phải đạt D4 ở khả năng kết nối invariant -> experiment -> metric -> incident ->
recovery -> limitation. Bạn không chỉ vận hành demo; bạn phải đánh giá được claim nào dữ liệu cho
phép nói, claim nào chưa được chứng minh và hệ thống sẽ đổi ra sao khi scale/assumption đổi.

## 4.1. Experiment reasoning E1–E5 và P1–P5

- [ ] Tôi nêu independent variable, controls và câu hỏi của từng E1–E5.
- [ ] Tôi giải thích E2-vs-E3 tách PIT effect và E3-vs-E4 tách split effect ở mức nào, cùng
  confounder còn lại.
- [ ] Tôi giải thích được tại sao leaky model tốt hơn là kết quả hợp lệ nhưng không deployable.
- [ ] Tôi biết một result inconclusive khác result fail và không chọn lại experiment sau khi thấy
  số đẹp.
- [ ] Tôi nêu independent variable và fairness condition của P1–P5.
- [ ] Tôi giải thích bytes/files/partitions scanned, selectivity, cache, warm-up, repeated runs,
  median và dispersion.
- [ ] Tôi biết benchmark wall-clock một lần không đủ để claim optimization.
- [ ] Tôi giải thích break-even point: incremental overhead chỉ có lợi dưới range/selectivity nào.
- [ ] Tôi phân biệt correctness result, performance result và model-quality result.
- [ ] Tôi không ngoại suy single-node PaySim result thành distributed production speedup.

## 4.2. Manifest, lineage và reproducibility audit

- [ ] Tôi đọc một run manifest và tái dựng được input, versions, cutoff, code, environment,
  output và supersession chain.
- [ ] Tôi giải thích được reproducibility logical output khác byte-for-byte file identity.
- [ ] Tôi biết failed run vẫn là evidence và không được overwrite.
- [ ] Tôi mô tả clean-room reproduction khác rerun trong dirty workspace thế nào.
- [ ] Tôi biết exact Delta time travel vẫn chưa đủ nếu code/feature contract/dependency thay đổi.
- [ ] Tôi truy ngược prediction -> deployment manifest -> model run -> Gold feature -> Silver/
  Bronze source snapshot.
- [ ] Tôi giải thích được reconciliation phát hiện loại lỗi nào và không phát hiện semantic error
  nào.
- [ ] Tôi biết report phải sinh từ raw artifacts khi có thể, không sửa số evidence bằng tay.

## 4.3. Observability và incident response

- [ ] Tôi phân biệt logs, metrics và traces bằng câu hỏi vận hành mỗi signal trả lời.
- [ ] Tôi mô tả đúng flow: application instrumentation -> OTLP -> OTel Collector -> Prometheus
  metrics backend -> Grafana visualization.
- [ ] Tôi biết Grafana không nhận/lưu trực tiếp mọi telemetry và dashboard không phải correctness
  proof.
- [ ] Tôi định nghĩa metric semantics, unit, labels/cardinality và action trước khi vẽ dashboard.
- [ ] Tôi phân biệt freshness SLO, completeness, parity, availability và latency.
- [ ] Tôi chọn alert từ invariant/SLO, ví dụ parity mismatch > 0 trên golden sample hoặc watermark
  vượt freshness threshold.
- [ ] Tôi tránh high-cardinality labels như raw entity/transaction ID trong Prometheus.
- [ ] Tôi thực hiện incident loop: detect -> scope -> locate first divergent layer -> root cause
  -> recover/backfill -> reconcile -> regression test -> postmortem.
- [ ] Tôi phân biệt symptom, trigger, root cause, contributing factor và blast radius.
- [ ] Tôi giải thích được retry có thể làm incident nặng hơn khi lỗi không transient hoặc operation
  không idempotent.
- [ ] Tôi biết “pipeline success” nhưng mart thiếu 8% là observability/correctness failure nào và
  reconciliation nên chặn publish ở đâu.

## 4.4. Fault injection và recovery

- [ ] Với R1–R12, tôi dự đoán expected status, durable state, metric/log, recovery action và
  regression evidence.
- [ ] Tôi giải thích được fault injection kiểm tra detector/recovery path, không chỉ làm test đỏ.
- [ ] Tôi biết kill giữa write và publish khác kill sau atomic commit nhưng trước acknowledgement.
- [ ] Tôi phục hồi Redis reset mà không dùng Gold historical row sai nghĩa.
- [ ] Tôi rollback bad Delta snapshot và bad model alias như hai control plane khác nhau.
- [ ] Tôi biết version mismatch phải fail loudly trước silent prediction.
- [ ] Tôi đánh giá được fallback policy có thể duy trì availability nhưng làm giảm correctness/
  fraud protection thế nào.

## 4.5. Scale và system design transfer

- [ ] Với 1 tỷ transaction/ngày, tôi bắt đầu từ throughput, skew, state size, retention,
  freshness/completeness SLO và failure budget thay vì bắt đầu từ tên Kafka/Spark.
- [ ] Tôi tách fraud path `<5 phút` và finance reporting `T+1`; phần nào streaming, micro-batch
  hoặc batch và vì sao.
- [ ] Tôi chọn partition key bằng ordering/state locality/skew/replay trade-off.
- [ ] Tôi giải thích global order thường không cần thiết nhưng per-entity order/cutoff semantics
  phải giữ.
- [ ] Tôi thiết kế late-event policy: allowed lateness, watermark, correction/backfill và user/
  model impact.
- [ ] Tôi giải thích at-least-once delivery cần idempotent consumer/dedup state thế nào.
- [ ] Tôi nêu khi nào DuckDB/local Delta không còn phù hợp: concurrency, catalog governance,
  distributed compute, object-store consistency hoặc workload volume.
- [ ] Tôi chỉ thêm Kafka/Flink/Spark/warehouse khi đã chỉ ra bottleneck và invariant chúng phải
  giữ; tôi không dùng chúng như từ khóa kiến trúc.
- [ ] Tôi hiểu local replay chứng minh semantic logic nhưng không chứng minh HA, distributed
  ordering, autoscaling hoặc multi-writer safety.
- [ ] Tôi cân nhắc security/governance: secret, PII, access boundary, retention, audit và model/
  feature change approval.

## 4.6. Research honesty và communication

- [ ] Tôi phân biệt hypothesis, observation, interpretation, causal claim và limitation.
- [ ] Tôi nêu threats to validity: proxy entity, synthetic absolute/created time, static dataset,
  single-node/single dataset, non-SOTA model và optional curated cloud subset.
- [ ] Tôi giải thích được external validity hạn chế ra sao và experiment nào cần thêm để mở rộng.
- [ ] Tôi trình bày architecture-as-built, không chỉ target architecture; deviation có lý do.
- [ ] Tôi nói “chưa biết/chưa verify” đúng lúc và đề xuất experiment nhỏ nhất để biết.
- [ ] Tôi có thể bỏ tên công nghệ khỏi câu trả lời mà reasoning vẫn đứng vững.
- [ ] Tôi chuyển một incident hoặc reviewer challenge thành invariant/test mới, không chỉ patch
  happy path.

## 4.7. Gate kiến thức Sprint 3

- [ ] Tôi thực hiện được oral defense 30–45 phút, không sai ba invariant hoặc status claim.
- [ ] Tôi chẩn đoán được một incident unseen từ raw evidence đến first divergent layer và recovery
  plan.
- [ ] Tôi diễn giải E1–E5/P1–P5 mà không overclaim causality/performance.
- [ ] Tôi thiết kế scale-up variant và nêu ít nhất ba assumption thay đổi cùng ảnh hưởng đến
  correctness.
- [ ] Tôi truy lineage một prediction và reproduce một artifact từ manifest.
- [ ] Tôi nêu được ba limitation thật, mức ảnh hưởng và experiment tiếp theo; không dùng
  limitation như phần “cho có”.

---

# 5. Final closed-note oral defense

Random ít nhất 12 câu, bắt buộc có bốn câu temporal và hai câu incident/design. Mỗi câu chấm
0–4 theo thang D0–D4.

1. Vẽ timeline chứng minh score-before-update và tính tay vector trước/sau transaction `t`.
2. Tại sao `event_timestamp < cutoff` chưa đủ khi có late arrival?
3. Same timestamp xử lý thế nào và vì sao tie-break không phải dedup?
4. PIT join và temporal split ngăn hai failure khác nhau nào?
5. Thêm future row nhưng past vector đổi: bạn điều tra predicate/layer nào theo thứ tự?
6. Tại sao synthetic oracle đáng tin hơn optimized DuckDB query cho temporal correctness?
7. Parity bằng 0 có chứng minh freshness không? Cho bốn tổ hợp parity/freshness.
8. Backfill atomic nhưng không idempotent sẽ hỏng thế nào? Idempotent nhưng không reproducible thì
   sao?
9. Delta time travel cung cấp gì và còn thiếu gì để reproduce training dataset?
10. Một late event ảnh hưởng những Gold windows nào và tính invalidation range ra sao?
11. Redis mất toàn bộ state lúc watermark 10:00: recovery sequence và readiness policy là gì?
12. Vì sao compare P3-vs-P4 hợp lý hơn dùng CSV-vs-Delta để claim incremental speedup?
13. E2 metric cao nhất: kết luận hợp lệ và kết luận bị cấm là gì?
14. Model v2 gặp feature service v1: guard nằm đâu và response/status nên thế nào?
15. Pipeline báo success nhưng Gold thiếu 8% amount: scope và locate first divergence thế nào?
16. Retry sau timeout có thể double-count ở đâu? Idempotency key và commit acknowledgement giúp
    gì?
17. Nếu entity proxy làm 90% transaction thành singleton, history feature và research question bị
    ảnh hưởng thế nào?
18. Nếu feature definition đổi window 24h -> 12h, những artifact/version/range nào invalid?
19. Khi nào Redis/DuckDB/Delta/Feast không còn phù hợp? Trả lời bằng workload/requirement.
20. Scale lên 1 tỷ event/ngày nhưng giữ fraud <5 phút và finance T+1: tách path, state, ordering,
    replay và SLO thế nào?
21. Cho một claim trong report: chỉ ra raw evidence, assumption, confounder và limitation.
22. Nếu bỏ cloud, project còn chứng minh được gì? Nếu deploy cloud, điều gì vẫn chưa được chứng
    minh?
23. Một schema change thêm nullable column và một schema change đổi entity ID type khác nhau ra
    sao về compatibility/backfill/version?
24. Tại sao “exactly once” thường không nên được claim chỉ vì một event xuất hiện một lần trong
    demo?

**Điều kiện pass cuối project**

- Tổng tối thiểu `42/48` cho 12 câu.
- Không câu nào về future read, score-before-update, parity, backfill atomicity/idempotency,
  version mismatch hoặc status honesty dưới D3.
- Ít nhất ba câu đạt D4.
- Reviewer được quyền hỏi tiếp “tại sao?”, “evidence đâu?” và thay một assumption; trả lời thuộc
  lòng nhưng gãy ở follow-up không pass.

---

# 6. Red flags — dấu hiệu vẫn chỉ biết ở tầng triển khai

Không coi project đã “nằm trong đầu” nếu còn một trong các dấu hiệu sau:

- Nói “DuckDB/Feast/Delta bảo đảm PIT” nhưng không viết được temporal predicate.
- Không tính được vector trước/sau `t` trên giấy.
- Dùng event time, created time, processing time, cutoff và watermark thay nhau.
- Nghĩ temporal split có thể sửa một full-history feature bị leaky.
- So prediction giống nhau thay cho so feature vector parity.
- Gọi rerun không lỗi là idempotent hoặc reproducible mà không kiểm row/checksum/version.
- Nghĩ atomic = idempotent = exactly-once.
- Hash raw file và gọi đó là logical checksum mà không xét canonicalization.
- Gọi notebook, architecture image, Swagger hoặc Grafana screenshot là correctness evidence.
- Nói “pipeline pass” nhưng không chỉ được exact command/artifact/version.
- Thấy metric model cao là muốn promote dù leakage/parity/version gate fail.
- Gặp incident thì rerun toàn bộ trước khi scope và tìm first divergent layer.
- Đề xuất Kafka/Spark/Kubernetes trước khi định lượng workload, state, ordering và SLO.
- Không phân biệt phần đã verified với target Sprint 2/3.
- Không nêu được limitation hoặc nói limitation chung chung không ảnh hưởng claim nào.

# 7. Phiếu review ngắn để copy sau mỗi sprint

```text
Review date:
Sprint:
Reviewer:
Closed-note score:

Core concepts below D3:
Wrong mental models discovered:
Unseen case attempted:
First answer:
Corrected answer:

One timeline/vector calculated by hand:
One bug predicted before running tests:
One incident/change case diagnosed:
One trade-off defended with evidence:
One claim I must stop making:

Evidence opened only after closed-note attempt:
Code/test/doc to revisit:
Next review date:
```

## Sources of truth

- [Project handoff and scope](../../AGENTS.md)
- [Terminology catalog](catalog.md)
- [Implementation/evidence self-review](project-self-review-checklist.md)
- [Sprint 1 guide](../feature-store/sprint-1-implementation-guide.md)
- [Sprint 2 guide](../feature-store/sprint-2-implementation-guide.md)
- [Sprint 3 guide](../feature-store/sprint-3-implementation-guide.md)
- [Temporal/entity ADR](../adr/001-temporal-entity-contract.md)
- [Research protocol](../research-protocol.md)
- [Current project status](../../artifacts/changelog/PROJECT_STATUS.md)
