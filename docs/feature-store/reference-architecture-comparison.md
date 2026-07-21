# Reference Architecture Review

## Mục đích

Tài liệu này so sánh ba hướng triển khai:

1. thesis *A Unified Lakehouse Architecture Supporting Both Batch and Streaming Data for E-Commerce Analytics and Recommendations* của Le Hong Vu;
2. repository [bmd1905/Customer-Purchase-Prediction-ML-System](https://github.com/bmd1905/Customer-Purchase-Prediction-ML-System);
3. đề tài hiện tại: Point-in-Time Correct Feature Store trên Delta Lakehouse cho fraud scoring.

Mục tiêu không phải chọn stack có nhiều thành phần nhất. Quyết định được tối ưu cho một người, sáu tuần, CPU-only, chi phí bắt buộc bằng 0 và outcome chính là bằng chứng MLOps có thể kiểm tra.

---

## 1. Thesis thực sự làm gì?

Thesis là một **data-platform/lakehouse integration project có thêm một ML consumer**, không phải dashboard-only và cũng chưa phải MLOps lifecycle hoàn chỉnh.

Luồng chính:

```text
PostgreSQL batch + Kafka events
  -> Spark ingestion/Structured Streaming
  -> MinIO
  -> Bronze/Silver/Gold
  -> Iceberg + Nessie
  -> Dremio
  -> Superset analytics dashboard

Gold interactions
  -> Spark MLlib ALS
  -> MLflow metrics + artifacts
  -> batch candidates
  -> Redis recent activity
  -> priority-based reranking
  -> service consumer
```

Trọng tâm được chứng minh là các thành phần có thể tích hợp trên một local single-node Docker environment. Dashboard là một output của Gold analytical tables. Phần serving tồn tại dưới dạng load ALS artifacts, đọc recent activity từ Redis và rerank top-K; nó không phải một production serving platform có deployment promotion, automated reload, rollback và SLO.

### Điểm mạnh

- Câu chuyện batch + streaming + analytics + ML consumer nhất quán.
- Có medallion layers và shared datasets cho nhiều downstream workload.
- Có orchestration, table versioning, experiment tracking và local containerization.
- Báo cáo phân biệt functional validation với real-world model quality.
- Có phần limitations, risks, ethics và planned-vs-implemented narrative tốt để tham khảo cho final report.

### Điểm yếu đối với mục tiêu hiện tại

- Timeline của thesis là 20 tuần, không phải sáu tuần.
- Stack tích hợp nặng: Spark, Kafka, Airflow, Iceberg, Nessie, MinIO, Dremio, Superset, Redis và MLflow.
- Evaluation chủ yếu dựa trên pipeline execution và screenshots; throughput, fault tolerance và concurrent workload chưa được kiểm chứng ở quy mô production.
- Synthetic data khiến recommendation metrics chỉ chứng minh pipeline chạy được.
- MLOps lifecycle còn thiếu promotion policy, CI/CD evidence, rollback, drift/skew, feature lineage và offline/online correctness.

### Nguồn được thesis tham khảo

Thesis có tám nguồn chính, chia thành ba nhóm:

- Nền tảng data architecture: Inmon (1996) về data warehouse; Miloslavskaya & Tolstoy (2016) về data lake; El-Seoud et al. (2017) về big data/cloud.
- Lakehouse/table format: Armbrust et al. (2020) về Delta Lake; Apache Iceberg documentation; Harby & Zulkernine (2025) về survey và experimental comparison của lakehouse.
- Recommendation systems: Xia et al. (2024) về big-data recommendation systems; Zhang et al. (2020) về real-time movie recommendation.

Literature review phù hợp để biện minh cho lakehouse + recommendation integration, nhưng không đủ làm nền cho PIT feature correctness hoặc MLOps lifecycle. Đề tài hiện tại vẫn phải giữ paper PVLDB 2023 về feature-store pipelines và các nguồn trực tiếp về temporal joins, feature serving và reproducibility.

---

## 2. Audit repository MLOps tham khảo

Repository có scope rộng hơn thesis ở phần ML lifecycle:

- Kafka producer và PostgreSQL CDC qua Debezium;
- schema validation bằng Flink;
- MinIO data lake và PostgreSQL Bronze/Silver/Gold DWH;
- Feast với PostgreSQL offline store và Redis online store;
- Spark streaming dual-write feature path;
- Airflow data/training DAGs;
- Ray Tune/Train, MLflow registry và XGBoost;
- Ray Serve + FastAPI feature retrieval;
- OpenTelemetry/SigNoz và Prometheus/Grafana;
- NGINX proxy và Superset.

Đây là reference tốt về **component boundaries** và command-driven local infrastructure. Tuy nhiên, source audit cho thấy không nên xem README như production proof:

- 12 compose files định nghĩa tổng cộng 37 service instances nếu dựng toàn bộ profiles;
- không có test suite hoặc GitHub Actions workflow trong repository;
- README ghi rõ Elasticsearch alert chưa implement, MinIO path đang hardcode và model serving phải restart thủ công để load model mới;
- data-quality check của Gold layer đang comment;
- feature API trả cả `is_purchased`, dù serving layer sau đó lọc cột này trước prediction; đây là boundary nguy hiểm cần tránh bằng contract rõ ràng;
- Airflow data DAG có các decorated task nhưng cũng gọi trực tiếp ingestion/validation trong helper khi dựng DAG, làm execution boundary khó kiểm chứng;
- claim như 10k events/s không đi kèm benchmark harness và raw evidence có thể chạy lại trong repo.

Vì vậy repo được dùng để học pattern, không dùng làm blueprint để clone toàn bộ.

---

## 3. Feature mapping

| Concern | Lakehouse thesis | Customer Purchase repo | PIT fraud project |
|---|---|---|---|
| Domain | E-commerce | E-commerce | Fintech fraud |
| Câu hỏi trung tâm | Hợp nhất batch/streaming cho analytics + recommendations | Trình diễn full MLOps stack | Bảo đảm PIT correctness, parity và reproducible backfill |
| Lakehouse | Iceberg + Nessie + MinIO | MinIO data lake + PostgreSQL DWH; không có ACID lakehouse table format trong core | Delta Lake + exact snapshot versions |
| Compute | Spark batch/streaming | Flink + Spark + Ray | DuckDB + delta-rs, CPU single-node |
| Orchestration | Airflow | Airflow + Makefile | Python CLI + Makefile + CI |
| Feature store | Không có feature-store contract độc lập | Feast, PostgreSQL offline, Redis online | Feast interface + PIT oracle + Delta offline + Redis online |
| Model | ALS | XGBoost + Ray Tune | LightGBM baseline |
| Serving | Redis-assisted reranking | Ray Serve + FastAPI | FastAPI + versioned feature provider |
| Tracking/registry | MLflow metrics/artifacts | MLflow registry + `current` alias | MLflow runs + gated candidate/champion/previous aliases |
| Monitoring | Runtime output + dashboard | OTel/SigNoz + Prometheus/Grafana | Correctness, freshness, parity, latency và promotion audit |
| Main evidence | Functional integration/screenshots | Running services/screenshots | Machine-readable tests, checksums, ablation và fault injection |
| Local footprint | Nhiều distributed services | 37 compose service definitions | 3 core services; optional monitoring/MinIO profiles |
| Timeline | 20 tuần | Không khóa theo sáu tuần | 6 tuần/3 sprint |

---

## 4. Decision matrix

Thang điểm 1–10, điểm cao hơn là phù hợp hơn với mục tiêu của project hiện tại.

| Tiêu chí | Trọng số | Clone thesis | Clone repo | Giữ PIT và chọn lọc pattern |
|---|---:|---:|---:|---:|
| Trả lời research question rõ ràng | 20% | 5 | 4 | 10 |
| Chiều sâu MLOps có evidence | 20% | 4 | 7 | 9 |
| Khả thi solo trong 6 tuần | 20% | 3 | 2 | 9 |
| Chạy local CPU-only | 10% | 5 | 3 | 9 |
| Phù hợp fintech | 10% | 2 | 2 | 10 |
| Maintainability/dependency footprint | 10% | 4 | 3 | 9 |
| Testability/reproducibility | 10% | 4 | 4 | 10 |
| **Điểm trọng số** | **100%** | **3.9** | **3.8** | **9.4** |

Kết luận: không thay đề tài bằng thesis hoặc repository. Giữ PIT project và tái sử dụng một số pattern có leverage cao.

---

## 5. Pattern được nhận vào project

### 5.1. Nhận vào must-have

1. **Tách interface feature retrieval khỏi scoring logic**
   Tách ở code boundary (`FeatureProvider`/adapter), không tạo thêm microservice bắt buộc. Điều này cho phép đổi local Redis sang Upstash mà không đổi model-serving contract.

2. **Model lifecycle bằng alias có gate**
   MLflow dùng `candidate`, `champion` và `previous`; không đặt alias `current` ngay sau training. Promotion chỉ xảy ra sau temporal tests, lineage, parity và schema gates. Rollback phải là một command và tạo audit record.

3. **Deployment manifest xuyên suốt**
   Mỗi deployment ghim dataset snapshot, Delta versions, feature service version, training run, model version/alias, code commit và environment lock.

4. **Component lifecycle qua Makefile/Compose profiles**
   Có `make up-core`, `make status`, `make logs`, `make down` và profile optional cho monitoring/MinIO. Không yêu cầu user nhớ chuỗi lệnh riêng của từng tool.

5. **Dashboard là operational evidence**
   Dashboard hiển thị versions, watermark, parity, freshness, backfill health, serving latency/error và promotion events. Không xây business BI dashboard vì nó không trả lời research question.

### 5.2. Nhận vào should-have

- Trace/request/run ID xuyên API, feature retrieval và scoring.
- Manual scheduled retraining command hoặc GitHub Actions workflow; không cần Airflow.
- Cold-start/missing feature policy rõ ràng.
- Optional OpenTelemetry exporter nếu structured logs + Prometheus đã ổn.

### 5.2.1. Nice-to-have sau prototype

- TypeScript/Fastify serving adapter dùng Redis + ONNX Runtime Node.
- Python scorer giữ vai trò reference/fallback; TypeScript chỉ được nhận nếu cross-runtime parity pass.
- A/B benchmark cùng workload đo p50/p95/p99, throughput, CPU/RSS và cold start; không dùng benchmark framework “hello world” làm bằng chứng.

### 5.3. Không nhận vào core

- Kafka/Flink/CDC: replay harness đủ để kiểm chứng event ordering, late arrival và duplicate.
- Spark/Ray: dữ liệu và model fit CPU single-node; cluster local không chứng minh cloud scalability.
- Airflow: Makefile + CLI + CI đủ cho ba batch workflows và giảm integration risk.
- Dremio/Superset: DuckDB + Grafana/report tables đủ cho query/evidence.
- Nessie: Delta transaction log và pinned versions đủ cho single-writer MVP.
- SigNoz + NGINX: dependency footprint lớn hơn giá trị trong research scope.
- Business dashboard: dễ trở thành output đẹp nhưng không tăng correctness evidence.

---

## 6. Guardrail sáu tuần

Core local deployment chỉ có:

```text
Redis + MLflow + FastAPI
```

Delta/DuckDB/LightGBM chạy như batch processes, không phải long-running services. Prometheus/Grafana và MinIO chỉ bật bằng optional Compose profiles.

Streaming được mô phỏng bằng deterministic chronological replay. Chỉ thêm Redpanda/Kafka nếu tất cả Sprint 2 correctness gates đã pass và còn tối thiểu ba ngày buffer.

Definition of Done không phải số dashboard hoặc số container. Project pass khi:

- không có future-read violation;
- offline/online parity pass;
- backfill và snapshot reproduce được;
- model/feature version mismatch bị chặn;
- candidate được promote và rollback bằng manifest có audit trail;
- clean sample path chạy bằng một command;
- cloud account không khả dụng vẫn demo local đầy đủ.
