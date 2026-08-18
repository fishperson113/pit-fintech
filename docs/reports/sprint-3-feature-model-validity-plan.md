# Sprint 3 — Kế hoạch modeling: kiểm chứng tính đúng đắn Data → Feature → Model

Ngày lập: 2026-08-17
Phạm vi: tuần 5 (≈3–4 ngày làm việc thực), solo, người mới mảng modeling.
Trạng thái: **planned** (chưa có code cho các milestone bên dưới).

> Tài liệu này là plan cho phần **model quality** của Sprint 3, khởi động từ frozen Gold
> `pre_v10`/`post_v9` (báo cáo `sprint-2-completion-report.md`). Nó KHÔNG phải báo cáo kết quả —
> mọi con số PR-AUC/ablation sẽ được điền sau khi owner chạy gate.

## 1. Trục xuyên suốt (đừng đọc phần nào khác trước khi nắm cái này)

Mục tiêu tuần này **không** phải "train ra một con số đẹp hơn". Mục tiêu là **kiểm chứng tính
đúng đắn của data → feature → model**, không dừng ở "chạy được là xong".

Bộ **12 historical feature** ta tự viết cho bài toán serving PIT (`paysim-fraud-recipient-v2`:
3 request-time + count/sum/has_history × window 1h/24h/168h) là *nhân vật chính*. Tuần này ta
chứng minh chúng **thật sự đúng và có ích**, chứ không chỉ "có mặt trong vector".

Ba câu hỏi tuần này phải trả lời được, có bằng chứng máy-đọc:

1. **Data validity** — phân phối, degenerate feature, tương quan có hợp lý với thiết kế không?
2. **Feature validity** — feature nào thật sự tải tín hiệu, feature nào redundant? (tương quan
   *đoán* → ablation *xác nhận*)
3. **Model validity** — model đọc được tín hiệu tới đâu so với một "sàn" thấp, và imbalance ảnh
   hưởng thế nào? Metric giảm sau khi loại leakage/đổi setup là **kết quả hợp lệ**, không được
   tune để giấu (CLAUDE.md hard rule #5).

### Phát hiện được dự báo trước (đặt làm mục tiêu Ngày 1)

12 feature có **redundancy cài sẵn theo thiết kế**:

- `recipient_has_history_Xh` chỉ là bản nhị-phân-hóa của `pit_prior_count_Xh` → gần collinear.
- Ba window lồng nhau (1h ⊂ 24h ⊂ 168h) → count/amount tương quan cao giữa các window.

Hiểu *tại sao* chúng tương quan dạy về feature design nhiều hơn bất kỳ thuật toán nào. Đây là lý
do correlation (Ngày 1) và ablation (Ngày 3) được thiết kế nối thành một mạch.

## 2. Ràng buộc định hình plan (bất biến, không mở lại trong tuần này)

| Ràng buộc | Hệ quả cho plan |
|---|---|
| FeatureSpec `paysim-fraud-recipient-v2` **đóng băng** | Thêm/bỏ **stored feature** = ADR + v3 + backfill Gold + re-materialize + re-verify parity. **KHÔNG làm tuần này.** Chỉ *học* xem nên bỏ gì. |
| LightGBM là model family đã khóa (ADR-003) | RF / Logistic chỉ là **learning baseline không-promotable** (đúng vai như E2 control). Không cần ADR vì không promote. |
| PR-AUC primary, cấm accuracy (AGENTS.md §9) | Mọi so sánh đọc theo PR-AUC; accuracy chỉ để minh họa "tại sao nó vô nghĩa". |
| Local CPU, single node, không HPO lớn (AGENTS.md §5, §6) | Chỉ candidate/config matrix nhỏ deterministic. Không Optuna/Ray Tune. |
| Cấm label-derived / post-outcome / 4 balance column | Không feature nào chạm các cột này (đã enforce trong contract). |
| Correctness > metric | Không tune để che correctness failure. Metric xấu mà trung thực > metric đẹp mà mờ ám. |
| Notebook chỉ EDA, logic vào `src/` (hard rule #4) | Correlation/EDA để notebook; harness baseline/ablation vào `src/pit_fintech/training/`. |

**Ranh giới an toàn với codebase (không làm vỡ flow đã có):**

- Tất cả code mới nằm trong `src/pit_fintech/training/` + một notebook EDA. **Không** đụng
  `features/paysim_specs.py`, **không** đụng Gold schema, **không** backfill.
- **Không** sửa `models/paysim_training.py` (Silver baseline Sprint 1) — giữ nguyên làm frozen
  evidence.
- Baseline mới đọc lại đúng Gold E4 matrix qua `training/dataset.py` đã có.

## 3. Baseline ladder (RF đóng vai gì)

Chạy **cả 3 bậc trên cùng Gold E4 matrix** (12 PIT feature, temporal split đã khóa
train ≤520 / val 521–631 / test 632–743):

| Bậc | Model | Promotable? | Học được gì |
|---|---|---|---|
| 0 | Trivial (đoán theo prevalence) + LogisticRegression (có scaling) | Không | PR-AUC "sàn"; tại sao accuracy vô nghĩa; linear đọc feature tương quan khác tree |
| 1 | RandomForest (`class_weight='balanced'`, `n_estimators=100`, `n_jobs=-1`) | Không | Bagging; imbalance qua reweight; `feature_importances_` dùng cho ablation |
| 2 | LightGBM (đang có, thêm `scale_pos_weight`) | Có (champion path) | Boosting; so với bậc 0/1 để thấy thêm được bao nhiêu |

RF **không** để thắng metric — nó là điểm tham chiếu bagging-vs-boosting và một nguồn feature
importance độc lập. Sàn thấp (bậc 0) dạy nhiều hơn cả RF cho người mới: cho biết mọi con số phía
trên "hơn được cái gì".

## 4. Kế hoạch 4 ngày

Mỗi ngày = 1 milestone, cập nhật đủ 3 file changelog khi commit (hook enforce). Trạng thái phân
biệt planned / implemented / **verified** (chỉ verified khi owner chạy gate).

### Ngày 1 — Kiểm chứng data & feature + sàn thấp

- Correlation matrix 12 feature bằng **Spearman** (không Pearson mù quáng — amount/count lệch
  nặng, heavy tail) + tương quan từng feature với target (rare binary → AUC-đơn-feature + mean
  theo lớp, không phải Pearson với target).
- Soi redundancy cài sẵn (has_history vs count; window lồng nhau), degenerate feature
  (variance ≈ 0?), phân phối/heavy tail, missingness.
- Nối với invariant: future-read = 0 đã có → gắn data validity với tính đúng PIT.
- Dựng **bậc 0**: trivial + LogisticRegression (scaling), lấy PR-AUC sàn.
- **Deliverable:** notebook EDA correlation (output-free trong git) + harness bậc 0 trong
  `training/` + bảng correlation lưu artifact.
- **Học:** PR-AUC vs accuracy, tương quan, redundancy, sàn ở đâu.

### Ngày 2 — Imbalance + baseline ladder (RF + LightGBM)

- Thêm RF vào harness (`class_weight='balanced'`, bound `n_estimators` cho nhanh trên CPU).
- Bật imbalance cho LightGBM: `scale_pos_weight = n_neg/n_pos` (đưa vào `TrainingConfig.parameters`,
  không đổi chữ ký hàm public).
- So ladder: sàn → RF → LightGBM, có/không xử lý imbalance; log mỗi run vào MLflow.
- **Deliverable:** bảng so sánh ladder (PR-AUC/ROC-AUC/recall@FPR) + các MLflow run.
- **Học:** imbalance reweight đổi gì; bagging vs boosting; tree "nuốt" collinearity mượt còn
  logistic thì không (nối Ngày 1). **Metric không tăng vẫn là kết quả đúng.**

### Ngày 3 — Ablation trên 12 feature (dùng kết quả correlation Ngày 1)

- Leave-one-group-out theo window (bỏ 1h / bỏ 24h / bỏ 168h) + thử bỏ `has_history` (feature bị
  nghi thừa). Correlation *đoán* thừa → ablation *chứng minh*.
- Feature importance từ RF + LightGBM, đối chiếu chéo với correlation. 3 nguồn cùng chỉ vào 1
  feature = tin được.
- Chạy như matrix nhỏ deterministic qua `run_candidate_matrix` (đã có sẵn).
- **Deliverable:** bảng ablation + kết luận "giữ/nghi-bỏ" từng feature (chưa bỏ thật — bỏ thật là
  ADR + v3).
- **Học:** feature nào thật sự tải tín hiệu; bộ PIT feature ta viết ra có xứng đáng không.

### Ngày 4 — Sliced metrics + report tính đúng đắn

- Điền `SlicedMetrics` đang rỗng: `population / cash_out_warm / cash_out_cold / transfer_cold`
  (ADR-002 consequence 3) — chỗ dataset thành thật nhất; population number đang che nó.
- Đóng băng toàn bộ tuần thành experiment manifest (theo pattern `SilverTrainingManifest`).
- Viết report kết quả `docs/reports/sprint-3-feature-model-validity.md`: câu chuyện correctness
  của data → feature → model, metric trung thực, kết luận 12 PIT feature đóng góp gì / cái nào
  redundant, và *tại sao* metric ở mức đó (imbalance, PaySim AMBER, TRANSFER cold-start).
- **Deliverable:** sliced metrics + experiment manifest + report kết quả.

## 5. Ngoài phạm vi tuần này (defer)

- ❌ **Track B — thêm stored feature** (velocity, distinct-source-count, time-since-last) → cần
  ADR + FeatureSpec **v3** + backfill Gold full + re-materialize + re-verify parity/future-read.
  Nặng, đụng cả platform. Chỉ mở nếu ablation cho thấy 12 field là trần **và** còn buffer.
- ❌ **Derived interaction trong preprocessing** (amount/count ratio áp identical offline/online):
  contract-safe nhưng để tuần sau nếu Track A còn thời gian.
- ❌ Tuning grid lớn / Optuna / calibration nâng cao.
- ❌ Implement `training/lifecycle.py` (promote/rollback đang là skeleton) — dev-debt, không phải
  bài học modeling tuần này.
- ❌ SHAP nếu ngại thêm dependency → dùng `feature_importances_` + permutation importance là đủ.

## 6. Milestone mapping & governance

| Ngày | Milestone (dự kiến) | Gate xác minh |
|---|---|---|
| 1 | Data/feature validity + sàn thấp | `test-unit` + owner chạy harness bậc 0; correlation artifact sinh ra |
| 2 | Imbalance + baseline ladder | owner chạy ladder; MLflow có đủ run; `lint` clean |
| 3 | Feature ablation | owner chạy ablation matrix; bảng ablation khớp feature importance |
| 4 | Slices + validity report | `SlicedMetrics` được điền; report + manifest hoàn tất |

Mỗi milestone cập nhật `PROJECT_STATUS.md`, `CHANGELOG.md` và một log
`artifacts/changelog/milestones/M0NN-<slug>.md` trong cùng commit (AGENTS.md §13, hook enforce).
Owner chạy mọi command; agent viết code + đọc lại output owner dán (hard rule #1). Không tuyên bố
"verified" nếu chưa có kết quả gate từ owner.

## 7. Định nghĩa "đủ tốt" cho tuần này

Tuần này **thành công** nếu — bất kể PR-AUC lên hay xuống — ta trả lời được, có bằng chứng:

- Data/feature có đúng như thiết kế không (phân phối, tương quan, redundancy).
- Feature nào thật sự có ích, cái nào thừa (correlation + ablation + importance đồng thuận).
- Model đọc tín hiệu tới đâu so với sàn, và imbalance ảnh hưởng ra sao.
- Câu chuyện được viết trung thực trong report, không có con số nào bị tune để che khuyết điểm.
