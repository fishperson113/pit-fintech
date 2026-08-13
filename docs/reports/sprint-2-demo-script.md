# Sprint 2 — Script demo 5 phút

Mục tiêu: 3 slide làm khung, **Grafana dashboard là chính**. Timing ~5 phút. Chữ *(cue)* là thao tác, chữ thường là lời nói.

---

## 0:00–0:30 · Mở đầu — Slide 1 (Đã xong)

*(Mở slide 1)*

"Sprint 2 mình làm nền tảng feature PIT-correct cho fraud scoring — mục tiêu là không rò rỉ dữ liệu tương lai, và vector lúc train phải trùng vector lúc serving. Tin chính: **phần hạ tầng nặng đã xong**. Cụ thể ba thứ: đường ghi online hoàn chỉnh, load được champion model khi chạy và so precision/recall rõ ràng, và toàn bộ offline→online pipeline."

## 0:30–2:45 · Demo Grafana (phần chính)

*(Chuyển sang Grafana dashboard "PIT Fintech Observability")*

"Mình bật dashboard live để thấy hệ thống thật chứ không phải slide."

**Panel Online scoring / Worker write** *(trỏ vào)*
"Mỗi transaction đi vào: FastAPI đọc lịch sử từ Redis **trước** thời điểm quyết định, chấm điểm, rồi mới cập nhật. `feature_provider` là `pit-online-worker` — đúng đường write event-based. Đây là chỗ đảm bảo score-before-update, không nhìn lén tương lai."

**Panel Backfill** *(trỏ vào)*
"Backfill offline: mình chạy lại cùng một range hai lần, nó **không** tạo bản mới, không nhân đôi — idempotent. Và full rebuild toàn bộ [1,743], `future_read_violations = 0`. Đây là bằng chứng tái lập được."

**Panel Materialization / Redis recovery** *(trỏ vào)*
"Materialize Gold xuống Redis cho ~2.7 triệu entity. Recovery: reset sạch rồi dựng lại — **5,444,725 trên 5,444,726 record giống hệt bit-for-bit**. Đúng một entity lệch do một event live ghi song song lúc đang chạy, không phải lỗi logic."

**Panel Parity** *(trỏ vào)*
"Và đây là cái quan trọng nhất về correctness: parity offline↔online — `field_mismatches = 0`. Vector online khớp vector offline. Đây là lời hứa cốt lõi của cả dự án."

**Panel Served-event candidate** *(trỏ vào, nếu có)*
"Event serving được đẩy ngược thành Silver rồi Gold candidate, nhưng luôn `label_status = unlabeled` — không bao giờ tự bịa nhãn fraud."

## 2:45–3:30 · Kết quả model — quay lại Slide 1

*(Có thể mở MLflow hoặc nói trên slide)*

"Về model: mình load champion `paysim-fraud-lightgbm` và chạy ma trận E1–E4 trên Gold, log đầy đủ PR-AUC, ROC-AUC, precision, recall. PR-AUC là metric chính vì fraud cực hiếm. Số liệu có, so sánh rõ ràng — nhưng đây cũng dẫn sang phần chưa xong."

## 3:30–4:15 · Chưa xong — Slide 2 (phần model)

*(Chuyển slide 2)*

"Thành thật: **nút thắt còn lại là chất lượng model, không phải pipeline.** Ba điểm: một, class imbalance chưa xử lý bài bản — fraud quá hiếm nên model mới ở mức baseline. Hai, quan hệ giữa các feature chưa kiểm chứng — mình chưa khai thác sâu những thứ như amount giao dịch hay tương tác giữa các feature, chưa biết feature nào thực sự có ích. Ba, chưa tuning, chưa ablation."

## 4:15–5:00 · Bước tiếp — Slide 3 (Sprint 3)

*(Chuyển slide 3)*

"Nên Sprint 3, việc **chính** là làm model cho chỉnh chu — xử lý imbalance, feature engineering quanh amount và quan hệ feature, chạy ablation E1–E4 để biết feature nào đáng giữ, rồi tuning. Phần còn lại là **optional để củng cố**: review code AI-gen kèm mutation test các module correctness — PIT oracle, online_state, build_offline — để chứng minh bộ test thật sự bắt lỗi chứ không chỉ chạy xanh; property-based test cho invariant PIT; chaos/crash như kill worker giữa batch hay restart Redis; và dựng Locust cho các kịch bản late-arrival, out-of-order, burst cùng fault injection. Xa hơn nữa mới tới serving cloud smoke và báo cáo cuối."

"Tóm lại: Sprint 2 đã dựng xong bộ khung nặng và chứng minh được tính đúng đắn PIT; Sprint 3 dồn sức vào chất lượng model và soát code. Cảm ơn mọi người — mình nhận câu hỏi."

---

## Ghi chú nhanh khi Q&A

- **"Sao PR-AUC/recall thấp?"** → PaySim recipient-history thưa, `AMBER_CORRECTNESS_ONLY`; metric giảm sau khi bỏ leakage là kết quả *hợp lệ*, không tune để giấu.
- **"Recover lệch 1 record là lỗi à?"** → Không; 5,444,725/5,444,726 giống hệt, 1 record do worker ghi live đồng thời; chạy trên store tĩnh sẽ về 0.
- **"Sao không dùng Spark/Kafka?"** → Ngoài scope MVP; cả nền chạy local-first trên 1 CPU theo thiết kế.
- **Số chốt:** Gold pre v10 / post v9, source Silver v7, 2,722,362 entity, parity 0 mismatch, 110 unit test pass.
