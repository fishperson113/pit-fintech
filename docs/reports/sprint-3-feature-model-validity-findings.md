# Sprint 3 — Kết quả kiểm chứng Data → Feature → Model (notebook nb09–nb13)

Ngày: 2026-08-18
Phạm vi: các notebook thăm dò (exploratory) nb09–nb13, chạy owner-side, log MLflow experiment
`pit-fintech-notebook-exploration`.
Trạng thái: **implemented (exploratory, non-promotable)** — đây là bằng chứng học tập/định hướng,
KHÔNG phải gate promote. Bản chốt contract phải chạy `src/pit_fintech/training/` với manifest + đa
seed (AGENTS §5/§6). Đi kèm plan: [`sprint-3-feature-model-validity-plan.md`](sprint-3-feature-model-validity-plan.md).

> **Đọc trước:** mọi con số dưới đây là bằng chứng thăm dò trên PaySim (đánh giá `AMBER` — tín hiệu
> fraud thật nằm ở 4 cột balance mà contract **cấm** dùng). PR-AUC là metric chính; accuracy bị cấm
> (AGENTS §9). Không có con số nào bị tune để che khuyết điểm (hard rule #5).

---

## 1. Tóm tắt (một phút)

- **Model LightGBM hiện tại (7 feature PIT-safe, tuned):** test **PR-AUC ≈ 0.38**, cross-validation
  **0.38 ± 0.11** qua các giai đoạn thời gian. Với ngân sách review **top 1%**, bắt được **~23%**
  fraud; **top 0.5%** đạt **precision 100%** bắt **15%** fraud.
- **Trần chất lượng do FEATURE + DATA quyết định, không phải thuật toán hay tham số.** Bằng chứng:
  (a) LightGBM ≈ XGBoost khi so công bằng; (b) tuning Optuna cải thiện val +0.011 nhưng **không**
  chuyển sang test (+0.0006).
- **Điểm yếu thật = cold-start.** Model mạnh ổn định trên recipient có lịch sử (warm, PR-AUC 0.41)
  nhưng yếu & dao động trên recipient mới (cold, 0.35) — vì cold không có lịch sử để feature PIT
  tổng hợp. Đây là chỗ đáng đầu tư tiếp (Track B, cần ADR + v3).
- **12 feature PIT lịch sử tự viết ra là hợp lệ và có ích** — chúng tải tín hiệu đúng nơi có dữ
  liệu (warm). Đã rút gọn xuống **7 feature deployable** để *feed* model (bỏ `event_step` overfit +
  3 cờ has_history thừa + `pit_prior_count_168h`). *Lưu ý:* 12 field vẫn **đóng băng** trong
  FeatureSpec `paysim-fraud-recipient-v2`; đây là lựa chọn *feed model*, không phải xoá stored
  feature (xoá cần ADR + v3 + backfill).

---

## 2. Phương pháp & cấu hình

| Notebook | Vai trò | Cấu hình đánh giá |
|---|---|---|
| **nb09** ablation | feature nào tải tín hiệu (tương đối) | **natural prevalence**, không imbalance weight → PR-AUC nhỏ (0.04–0.09), chỉ đọc *delta* trong nb |
| **nb10** LGB vs XGB | so 2 booster công bằng | temporal 3-way, `scale_pos_weight=√(neg/pos)`, `reg_lambda=1` |
| **nb11** tuning | Optuna 30 trial | chọn theo **val** PR-AUC; `scale_pos_weight` cố định √ |
| **nb12** final + SHAP | test một lần + giải thích | tham số tuned; ngưỡng chọn ở val (FPR=1%) |
| **nb13** walk-forward CV | tổng quát hóa | 5 fold thời gian + embargo + warm/cold |

**Split cố định (nb10–12):** train `step ≤ 520` / val `521–631` / test `≥ 632`. Temporal, không
random (random = rò rỉ tương lai).

**Về sự khác thang PR-AUC:** nb09 chạy natural prevalence để so *đóng góp tương đối* giữa các
feature trên cùng mặt bằng → số tuyệt đối (~0.045) **không so được** với nb10–13 (~0.38, có
`scale_pos_weight` + config shippable). Chỉ đọc *thứ hạng/delta* trong mỗi notebook.

---

## 3. Data validity — tín hiệu thật ở đâu?

- Dataset: PaySim pre-decision Gold **2,770,409 dòng**, **8,213 fraud (~0.30%)** — cực mất cân bằng.
- **Arm LEAKAGE control** (7 feature phái sinh từ cột balance, chỉ để đối chứng): **PR-AUC 0.8827,
  ROC-AUC 0.980**. → Xác nhận **tín hiệu fraud thật của PaySim nằm ở các cột balance bị cấm**. Vì ta
  cố ý bỏ chúng, trần PR-AUC thấp (~0.38) là **đúng và trung thực**, không phải model kém.

---

## 4. Feature validity — ablation (nb09)

### 4.1 `event_step` là overfitting (loại bỏ)
- Train có `event_step ∈ [1, 520]`, test `∈ [632, 743]` → **overlap = 0**: giá trị test **chưa từng
  thấy** khi train → model buộc phải ngoại suy.
- Bỏ `event_step`: PR-AUC (nb09) **0.045 → 0.092** (≈ gấp đôi). `gain_share` của nó = **0.298** (cao
  thứ nhì) → model dựa nặng vào một trục thời gian tuyệt đối vô nghĩa ngoài giai đoạn train.
- **Kết luận:** `event_step`/`knowledge_step` là **toạ độ để platform đảm bảo tính đúng thời gian**,
  KHÔNG phải feature cho model học.

### 4.2 Feature nào tải tín hiệu
- **`current_amount`** — mạnh nhất, `gain_share` **0.431**; bỏ nó tụt PR-AUC nhiều nhất trong nhóm
  hợp lệ (−0.011).
- **`pit_prior_amount_24h/168h`** — mang tín hiệu; bỏ window 24h/168h đều hại.
- **3 cờ `recipient_has_history_{1h,24h,168h}`** — `gain ≈ 0`, **thừa** (nhị-phân-hoá của count); bỏ
  1h/168h cho delta = 0.
- **`pit_prior_count_168h`** — bỏ còn giúp nhẹ (+0.003) trong ablation.

### 4.3 Bộ 12 → 7 deployable (feed model)
| Feed model (7) | Bỏ khỏi feed (5) |
|---|---|
| `current_amount` | `event_step` (overfit) |
| `transaction_type_transfer` | `pit_prior_count_168h` |
| `pit_prior_amount_1h/24h/168h` | `recipient_has_history_1h/24h/168h` (thừa) |
| `pit_prior_count_1h/24h` | |

→ **12 field vẫn frozen trong FeatureSpec** (stored). Đây là lựa chọn *feed model*, có thể đảo
ngược; xoá stored feature mới cần ADR + v3 + backfill.

---

## 5. Model validity — LightGBM hiện tại

### 5.1 LightGBM vs XGBoost (nb10, fair, tái lập ×2)
| Metric (test) | **LightGBM** | XGBoost |
|---|---|---|
| **PR-AUC** | **0.3762** | 0.3652 |
| ROC-AUC | 0.826 | 0.823 |
| log_loss | 0.171 | 0.169 |
| precision / recall @thr | 0.474 / 0.312 | 0.450 / 0.299 |

- Hai model **ngang nhau** (~3% tương đối). "Gap 5×" ở lần chạy đầu là **ảo giác do config lệch**
  (`scale_pos_weight` full ratio ~458 làm bão hoà xác suất → log_loss 9.39). Sửa bằng `√(neg/pos)`
  ≈ 20.5 → log_loss về 0.17.
- **LightGBM (champion đã khoá ADR-003) được validate** — không thua XGBoost, không có lý do đổi.

### 5.2 Tuning (nb11, Optuna 30 trial)
- val PR-AUC: baseline **0.30006** → best **0.31117** (**+0.011**). Top-5 trial dồn cụm 0.309–0.311.
- Best params: `n_estimators=500, learning_rate=0.023, num_leaves=38, max_depth=6,
  min_child_samples=100, subsample=0.687, colsample_bytree=0.768, reg_lambda=5.30`.

### 5.3 Đánh giá test cuối (nb12, tuned)
| | Giá trị |
|---|---|
| **test PR-AUC** | **0.3768** (untuned 0.3762 → **+0.0006**) |
| ROC-AUC / log_loss / Brier | 0.826 / 0.169 / 0.049 |
| @thr 0.595 | TP 396 · FP 472 · FN 856 · precision 0.456 · recall 0.316 · F1 0.374 |
| top 0.5% budget | precision **1.00** · recall 15.1% |
| top 1% budget | precision 0.749 · recall 22.7% |

- **Tuning gain KHÔNG chuyển sang test** (+0.0006) → khẳng định **trần do feature/data**, phần gain
  trên val chủ yếu là overfit nhẹ vào val.
- **SHAP** (TreeSHAP native của LightGBM): `current_amount` + `pit_prior_amount_*` dẫn đầu; nhất
  quán qua 3 nguồn (SHAP / gain / permutation).

---

## 6. Tổng quát hóa (nb13 — walk-forward CV)

### 6.1 Biến thiên qua thời gian (5 fold)
- E=0: **mean PR-AUC 0.379 ± 0.107** (dải **0.28 → 0.51**); E=168: 0.367 ± 0.111.
- **std ≈ 28% mean** → **một split đơn lẻ không đáng tin**; phải báo cáo **mean ± std + min (~0.28)**.
- Phần lớn dao động do **prevalence đổi theo giai đoạn** (sàn PR-AUC = prevalence) → đọc kèm lift,
  không so tuyệt đối giữa các fold.

### 6.2 Phụ thuộc kề-thời-gian (embargo)
- **Δ PR-AUC(E=168 − 0) = −0.0125** (nhỏ, luôn âm nhẹ) → model **không** dựa nhiều vào overlap sát
  ranh giới → số production-realistic (E=0) không bị thổi phồng. (Chứng minh không-future-leakage là
  việc của hợp đồng PIT + `tests/temporal`, không phải CV.)

### 6.3 Phụ thuộc trùng-entity (warm/cold)
| Segment | PR-AUC | Ổn định | Lift so prevalence |
|---|---|---|---|
| **warm** (recipient có lịch sử) | **0.408 ± 0.043** | rất ổn định | cao (14–456×) |
| **cold** (recipient mới, history=0) | **0.350 ± 0.124** | dao động mạnh | thấp hơn 2–18× ở **mọi** fold |

- Cold có prevalence **cao hơn** warm mà PR-AUC vẫn thấp/ngang → trên **lift**, warm vượt trội **mọi
  fold**. Nguyên nhân: cold không lịch sử → toàn bộ `pit_prior_*` = 0 → model chỉ còn
  `current_amount` + type.
- → **Feature PIT lịch sử phát huy đúng nơi có dữ liệu (warm); cold-start là điểm yếu nhất.** Phương
  sai của Phần 6.1 phần lớn đến từ khúc cold.

---

## 7. Thực trạng model & giới hạn (trung thực)

**Model đang có:** LightGBM, 7 feature PIT-safe, tuned; test PR-AUC ~0.38; CV 0.38 ± 0.11
(warm 0.41 / cold 0.35); champion family ADR-003 được validate.

**Vì sao PR-AUC ở mức ~0.38, không cao hơn:**
1. **Imbalance ~0.30%** → sàn rất thấp, đọc mọi số tương đối với prevalence.
2. **PaySim AMBER** — tín hiệu thật ở 4 cột balance bị cấm (arm leakage 0.88 chứng minh).
3. **Cold-start** — recipient mới không có lịch sử để feature PIT tổng hợp.

**Đòn bẩy tăng chất lượng (theo thứ tự ưu tiên):**
1. **Feature cold-start** (velocity, distinct-source-count, time-since-last) — Track B, cần ADR +
   FeatureSpec v3 + backfill. **Đây là lever thật**, không phải tuning.
2. Không phải: đổi thuật toán (LGB≈XGB), tuning thêm (không headroom).

**Bẫy đã tránh:** không dùng balance/label-derived/post-outcome feature; không tune để giấu; không
tin một split (đã chuyển sang CV); không nhầm `event_step` là feature.

---

## 8. Việc tiếp theo (phiên sau)

- [ ] (Tuỳ chọn) Log warm/cold + fold chi tiết lên MLflow (hiện display-only trong nb13).
- [ ] Điền `SlicedMetrics`: `population / cash_out_warm / cash_out_cold / transfer_cold` (ADR-002) —
      warm/cold ở nb13 là bước đầu.
- [ ] **Quyết định Track B**: có mở feature cold-start không (ADR + v3 + backfill) — lever chính.
- [ ] Chuyển harness baseline/ablation từ notebook vào `src/pit_fintech/training/` (notebook chỉ
      EDA — hard rule #4) + experiment manifest deterministic + **đa seed** để chốt ±std.
- [ ] Trước khi commit: **clear output tất cả notebook** (nb output-free trong git — hard rule #4).

---

## 9. Governance

- Notebook nb09–nb13 là surface **exploratory / non-promotable**; MLflow run gắn tag
  `manifest_backed=false`, experiment riêng `pit-fintech-notebook-exploration`.
- FeatureSpec `paysim-fraud-recipient-v2` **đóng băng** (12 field) — mọi thay đổi stored feature =
  ADR + v3 + backfill.
- Bản chốt promotable phải qua `training/` + gate + đa seed; không tuyên bố "verified" cho bất kỳ số
  nào ở đây chỉ vì notebook chạy được.
- Milestone: **M073** (xem `artifacts/changelog/milestones/M073-*.md`).
