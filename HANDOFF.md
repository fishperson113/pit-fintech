# HANDOFF — Sprint 2 đang làm dở

> **File tạm.** Dựng để bàn giao giữa chừng cho agent khác hoặc cho Dương tự làm tiếp.
> Xoá khi Sprint 2 đóng.
>
> Cập nhật: **2026-08-05** · Người viết: Fisch (Claude Opus 5)

---

## 1. Đang ở đâu, một đoạn

T1 của Sprint 2 **đã đóng và đã commit** (`bd60b13`) — gate G1 pass cả ba tiêu chí, có test chạy
lại được.

T2 Gold **đã implement, commit và verify** trong `c5574f8`: build hai bảng Gold bằng DuckDB,
backfill range theo trọn `event_day`, staging atomic, promotion partition-safe, progress output,
và shift-relation validation đã được tối ưu theo entity index.

Vòng 0 của T3–T9 vẫn là scaffold/hợp đồng; phần kế tiếp là **vòng 2: implement T3 backfill, T4
training và T5 materialization**.

---

## 2. Trạng thái worktree ngay lúc bàn giao

```
?? HANDOFF.md         <- file tạm này, dùng cho bàn giao; không phải artifact sản phẩm
```

Latest commit:

```text
c5574f8 feat(gold): enforce day-aligned backfills and optimize DuckDB validation
```

Trạng thái theo từ khoá của `CLAUDE.md`: **T1/T2 implemented and verified; T3–T9 scaffolded or
planned**. Worktree chỉ còn `HANDOFF.md` untracked khi kiểm tra trước lần cập nhật này.

Audit trail M032–M038 đã được cập nhật và nằm trong commit `c5574f8`. File này là handoff tạm,
không cần thêm milestone riêng cho các lần cập nhật handoff sau.

---

## 3. Kế hoạch 5 vòng

Dương chốt: **không cắt scope**, làm hết T2–T9, mức **walking skeleton chạy được** — mỗi module có
logic tối thiểu thật, E2E chạy từ đầu đến cuối bằng một lệnh, số liệu có thể còn thô nhưng đường
ống phải thông.

| Vòng | Việc | Song song được | Trạng thái |
|---|---|---|---|
| 0 | Khung + 7 hợp đồng cho cả 8 task, `compose.yaml` | 1 | ✅ xong, đã commit trong `c5574f8` |
| 1 | **T2** — hai bảng Gold | 1 (không chia được) | ✅ implement + verified |
| 2 | **T3** backfill · **T4** training · **T5** materialization | 3 | ⏳ tiếp theo |
| 3 | **T6** replay/parity · **T7** serving | 2 | chưa |
| 4 | **T9** E2E một lệnh + Make target + changelog | 1 | chưa |

**T2 là gốc của mọi thứ.** T5 cần bảng `post_event_state_updates`; T6 cần cả T2 lẫn T5; T7 cần
online store của T5. Vòng 2 có ba nhánh thật sự độc lập nên chạy song song được; vòng 1 thì không,
vì T2 là một chuỗi suy luận liên tục.

T8 (`compose.yaml`) đã làm sớm ở vòng 0 vì nó độc lập hoàn toàn. T2 hiện đã đóng gate thực tế;
T3–T5 là nhánh tiếp theo.

### Triết lý triển khai hiện tại: smoke lane trước, full gate sau

Sprint 2 không triển khai theo kiểu phải đóng toàn bộ gate của task hiện tại rồi mới được chạm task
kế tiếp. Mỗi task đi theo hai lớp evidence:

1. **Smoke/integration lane trước:** kiểm tra seam giữa các module và contract tối thiểu bằng fixture
   hoặc temporary artifact. Nếu seam chạy đúng, task kế tiếp có thể bắt đầu.
2. **Full acceptance evidence sau:** chạy đủ rerun, recovery, late-arrival, parity, promotion và
   reproducibility evidence theo G2–G11 trước khi tuyên bố gate cuối cùng đã pass.

Lý do: T4 cần Gold/manifest contract của T2–T3, còn T5 cần post-event Gold và version lineage; chờ
mọi edge-case T3 trước khi bắt đầu T4/T5 làm pipeline bị block không cần thiết. Ngược lại, bỏ qua
hoàn toàn smoke lane sẽ khiến T4/T5 xây trên seam chưa được kiểm chứng. Vì vậy thứ tự hiện tại là:

```text
T3 smoke integration
  -> T4 dataset/training + MLflow
  -> T5 materialization
  -> hoàn thiện full T3 G2/G3 evidence
  -> T6/T7/T9
```

Các trạng thái phải ghi rõ, không gộp thành một chữ `done`:

- `implemented`: code đã có;
- `unit verified`: logic cô lập đã pass;
- `smoke verified`: seam module đã chạy bằng fixture/temporary artifact;
- `gate verified`: full acceptance evidence đã pass.

Không dùng smoke pass để tuyên bố G2/G3 pass. Không chạy lại real Gold lakehouse chỉ để tạo smoke
Evidence khi fixture đủ chứng minh seam; real PaySim build/promote chỉ chạy khi cần evidence full-scale
hoặc khi Dương yêu cầu.

### Status T3–T9 hiện tại

- T3 implementation/unit đã verify; smoke lane fixture đã pass cho `execute_backfill` và
  `compare_reruns`.
- Late-arrival smoke đã chứng minh guard từ chối an toàn future-known row (`future_read_violations`);
  correction-success path vẫn là full T3 follow-up, không coi expected refusal là G2/G3 pass.
- T4 dataset layer đã nối Gold exact-version + Silver labels → entity dataframe → retrieval assertions
  → frozen temporal split/checksum. T4 LightGBM/MLflow candidate contract đã pass trên temporary
  Parquet/SQLite MLflow fixture; full real-PaySim training chưa chạy.
- T5 materialization, T6 replay/parity, T7 serving, T8 operational services và T9 E2E chưa hoàn tất.
- Next priority: review T4 contract/results, sau đó chạy `train-gold-candidate` khi Dương muốn tạo candidate trên
  Gold thật; T5 tiếp theo. Full T3 G2/G3 evidence quay lại sau smoke/T4/T5.

---

## 4. Bảy hợp đồng đã chốt — đọc trước khi viết bất kỳ dòng nào

Đây là thứ giữ cho tám module ghép được với nhau. **Không tự đổi. Muốn đổi thì cập nhật file này
và báo Dương**, vì các module khác đã bind vào.

| # | Hợp đồng | Ở đâu |
|---|---|---|
| 1 | Hai bảng Gold: tên, đường dẫn, schema đầy đủ | `features/build_offline.py` |
| 2 | `OfflineFeatureBuildResult` — kiểu trả về của T2 | `features/build_offline.py` |
| 3 | `BackfillRunRecord` — ~30 field theo guide §5.1 | `backfill/records.py` |
| 4 | `backfill_idempotency_key()` — **đã implement thật** | `backfill/records.py` |
| 5 | `FeatureProvider` ABC + 4 adapter | `serving/feature_provider.py` |
| 6 | `ParityFieldResult` / `CheckpointResult` / `ParityRunReport` | `replay/parity.py` |
| 7 | `ScoreRequest` / `ScoreResponse` (pydantic) | `serving/schemas.py` |

Chi tiết nguyên văn từng hợp đồng nằm trong docstring của chính các file trên — chúng được viết để
đọc là hiểu, không cần tra guide.

### Ba thiết kế dễ bị vô hiệu hoá nếu không biết lý do

**Field post-event cố ý mang tên khác contract** (`post_count_1h`, không phải
`pit_prior_count_1h`). Đây là **leakage guard**: nếu bảng post-event mang đúng tên contract thì một
job training trỏ nhầm bảng sẽ âm thầm train trên aggregate current-inclusive — chính là E2, positive
control cố ý leaky (PR-AUC 0.915 so với E4 0.324). Đổi tên biến nhầm lẫn đó thành `KeyError` thay vì
một metric đẹp. `POST_EVENT_TO_CONTRACT_FIELD` là **chỗ duy nhất** hai từ vựng được phép gặp nhau.
Đừng "dọn dẹp" cho thống nhất tên.

**`integer_mismatches` tách khỏi `float_mismatches`** trong kết quả parity. `AGENTS.md §9` bắt
integer/categorical mismatch phải đúng `0`, còn float mới so với tolerance. Gộp lại là mở đường cho
việc lấy lý lẽ tolerance áp lên một sai khác integer.

**`ParityRunReport.passed` đòi cả hai điều kiện**: mọi checkpoint 0 mismatch **và**
`missing_checkpoints == ()`. Chạy 4 checkpoint hoàn hảo mà không chạm same-second tie thì **không**
phải G6 pass.

---

## 5. Bẫy — đọc kỹ, cả ba đều đã cắn thật

### 5.1 Bảng feature phải do SQL ENGINE tính, không bao giờ do oracle

`paysim_reference.py` là **kỳ vọng**, không bao giờ là **producer**. Dùng oracle sinh bảng rồi so
với chính oracle thì gate thành tautology — pass mà không chứng minh gì.

Hướng thẩm quyền khi lệch: **SQL sai cho đến khi chứng minh ngược lại**. Và **cấm sửa giá trị kỳ
vọng cho khớp output** — tính tay từ fixture trước, rồi mới kết luận bên nào sai.

### 5.2 Timestamp phải tính bằng PYTHON, không bằng SQL

`TIMESTAMPTZ` của DuckDB render theo **múi giờ của phiên làm việc**, nên tính trong SQL thì file
parquet đổi theo máy chạy. Với một dự án lấy tất định làm invariant thì đây là loại bug tệ nhất: im
lặng, chỉ lộ khi người khác chạy lại.

Dùng `paysim_step_to_timestamp` — ADR-006 quyết định 1.7 nói rõ chỉ có **một** implementation.
`EPOCH_0 = 2020-01-01T00:00:00Z`.

### 5.3 Cặp same-step chưa bao giờ chạm tầng Feast — và đây là điều kiện của G6

Bảng feature của T1 có **11 step phân biệt**, đã đo lại ở vòng 0: 11 dòng / 11 timestamp phân biệt
/ 0 cặp trùng. T2 hiện đã gọi `probe_same_step_ties()` trong Gold build để ghi nhận điều kiện
same-step trước khi tạo hai bảng Gold; việc kiểm tra tie ở T6 vẫn bắt buộc.

Guide §8.3 đòi **"ít nhất một same-second tie case"** trong required checkpoints của T6. Nên tie
không phải thứ tránh được — nó là điều kiện nghiệm thu.

**Việc bắt buộc khi làm T6:** đọc kết quả `same_step_ties` từ Gold/replay evidence. Nếu Gold
full-scale không có cặp same-step in-scope thì phải dựng tie nhân tạo **trước khi** vào T6. Không
được giả định là có.

Cơ chế đã dựng sẵn để không quên: `plan_checkpoints` nhận `same_step_tie_available` như **tham số**
chứ không tự dò, nên không thể lấy được plan tuyên bố có tie mà range thực sự không có.

---

## 6. Quyết định còn treo — cần người quyết, đừng quyết ngầm trong code

| # | Việc | Vì sao chưa quyết |
|---|---|---|
| 1 | **Feast đọc Gold bằng đường nào** | Gold là Delta có partition, `FileSource` **không đọc được Delta log**. Ba lựa chọn: export Parquet / Feast DuckDB offline-store view / giữ Feast ở cỡ fixture. Guide §4.0 không nói. Chỗ giữ câu trả lời: `export_feast_source_parquet()` |
| 2 | **Entity không có event ở step `s`** | Quan hệ shift `post_event_state(s) == pre_decision_history(s+1)` chỉ đúng ở khoảng cách 1 step. Entity im lặng thì đẩy record refresh hay phục vụ stale-kèm-cờ? Guide không nói. Default tạm `stale_after_steps = 1` |
| 3 | **Prefix trong idempotency key** | Vòng 0 thêm `backfill-idempotency-key-v1` vào payload băm → digest khác công thức 5 field của guide §5.2. Lý do: repo version-hoá mọi identity nó băm. **Sửa một dòng** nếu muốn đúng chữ guide |
| 4 | **Marker `e2e`** | Không thêm vào `pyproject.toml` vì ADR-004 liệt kê file đó trong **cả hai** boundary fingerprint → thêm sẽ đổi hai fingerprint và vô hiệu hoá việc tái dùng exact-Silver. Hiện dùng marker `integration`, chọn lane bằng path |
| 5 | **Hợp nhất `BackfillManifest`** | `contracts/manifests.py` có `BackfillManifest` 10 field, còn guide §5.1 đòi ~30. Vòng 0 khai mới ở `backfill/records.py`. Hợp nhất là việc **cỡ ADR**, không phải refactor — `manifests.py` nằm trong cả hai boundary fingerprint của ADR-004 |
| 6 | **12 field vs 9 field ở seam T1↔T7** | `feature_repo/definitions.py` khai cả 12 field như batch field; `FeatureProvider` định nghĩa 9 (ba field request-time suy từ chính request). Người implement T7 chọn: project xuống 9, hay thêm `OnDemandFeatureView`. **Ghi lại quyết định** |

⚠️ Với mục 2: nới `stale_after_steps` là **quyết định chính sách phải ghi lại**, không phải nút vặn
để làm im một parity failure.

---

## 7. Luật làm việc trong repo này

- **Agent sửa code, Dương chạy lệnh.** Agent soạn lệnh kèm kết quả mong đợi rồi chờ output.
  (Ngoại lệ đang áp: agent được chạy test/lint để tự kiểm.)
- **Không agent nào được commit.** Dương review rồi tự commit.
- **Phải dùng `uv run`** — system Python 3.14 thiếu `duckdb`/`deltalake`, chạy trực tiếp là 8 lỗi
  collection.
- **`uv sync --all-groups`**, không phải `uv sync --group X --group Y` — lệnh sau gỡ mất mọi group
  không được nêu (đã cắn một lần, mất `lightgbm`/`mlflow`/`scikit-learn`).
- **Không sửa `docs/adr/`** — ADR là quyết định đã đóng băng, muốn đổi thì ra ADR mới.
- **Không sửa Bronze/Silver.**
- Mỗi commit phải có milestone log, nếu không hook `changelog-check` chặn.

### Lệnh kiểm tra chuẩn

```powershell
UV_PROJECT_ENVIRONMENT=.venv uv run --frozen --all-groups ruff check src tests feature_repo notebooks scripts
UV_PROJECT_ENVIRONMENT=.venv uv run --frozen --all-groups ruff format --check src tests feature_repo notebooks scripts
UV_PROJECT_ENVIRONMENT=.venv uv run --frozen --all-groups python -m pytest tests/unit -q
UV_PROJECT_ENVIRONMENT=.venv uv run --frozen --all-groups python -m pytest tests/temporal -q
UV_PROJECT_ENVIRONMENT=.venv uv run --frozen --all-groups python -m pytest tests/integration -q
```

Mốc verified hiện tại: unit **87** · temporal **73** · integration **17** · Ruff check sạch · Ruff
format check **86 files already formatted**. Integration có một warning deprecation hiện hữu của
Ibis (`fetch_arrow_table()`), không có test fail.

---

## 8. Số liệu chốt của T1, để đối chiếu

| | Giá trị |
|---|---|
| Commit T1 | `bd60b13` |
| SHA-256 `data/fixtures/paysim_feature_table.parquet` | `A6E6B9B00FA62966E19397D9C0A7737FCB48D8C9C81A5C7300CCE047B3B997C5` |
| Feast definitions checksum | `d330edefbbc0d3a075b4b5f145a6d169e2aa910d39cfae33c70478289432f443` |
| Registry blob digest (đổi sau mỗi apply — **đúng thiết kế**) | `98fe137e…` → `fd09313e…` |
| Retrieval khớp oracle | 11 hàng × 12 field = **132/132** |

### T2 Gold evidence (verified 2026-08-05)

| | Giá trị |
|---|---|
| Commit | `c5574f8` |
| Build range | `step 25..48` → `event_day=2` |
| Silver read range | `step 1..48` (168-step lookback bị clamp ở 1) |
| Staged pre rows | `202,874` |
| Staged post rows | `455,238` |
| Promotion | `promoted=True`, `partition_overwrite` |
| Promotion predicate | `event_day IN (CAST(2 AS INT))` |
| Delta versions sau promote | pre `3`, post `3` |
| Gold head pre rows | `203,538` |
| Gold event days | `{1, 2}` |
| Gold steps | `{1, 25..48}` — `25` step phân biệt |
| Step 1 preservation | `203,538 - 202,874 = 664` rows còn lại |

T2 đã chứng minh partition là ngày còn range input là step: `[25,48]` là một `event_day=2`,
không phải ngày 25 đến ngày 48. Guard từ chối range không trọn ngày; các range hợp lệ gồm `[1,24]`,
`[25,48]`, và `[721,743]`.

### T2 implementation notes

- Gold đọc các cột Silver cần thiết, materialize một temp DuckDB relation dùng chung cho audits/query,
  và tính expected row count bằng SQL.
- CLI in phase progress với elapsed seconds; library caller mặc định không in progress.
- `verify_shift_relation()` group/index post rows theo entity trước khi so sánh, tránh O(entity ×
  post_rows) full-table rescan.
- Timestamp vẫn do Python tính; PIT/knowledge-step/future-read semantics không đổi.

Hai chuỗi version dễ nhầm, **phải khác nhau**:
`paysim-fraud-recipient-v2` là **definition**, `paysim-fraud-scoring-v2` là **service**.

Hai chỗ bấm checksum, cũng đừng nhầm: `paysim_feature_contract_checksum()` ở
`features/paysim_specs.py` bấm **hợp đồng feature**; `feast_definitions_checksum()` ở
`platform/feast_registry.py` bấm **definitions của Feast registry**.

---

## 9. Nếu bạn là người tiếp quản — làm gì trước

1. Đọc mục 4, 5, 6 của file này. Ba mục đó là toàn bộ thứ không suy ra được từ code.
2. Chạy các lệnh kiểm tra ở mục 7 nếu cần đối chiếu; mốc verified hiện tại là unit 87, temporal 73,
   integration 17.
3. Chạy T3 smoke integration cho `execute_backfill`, `compare_reruns` và late-arrival trên fixture.
4. Sau smoke pass, bắt đầu T4 dataset/training; tiếp theo T5 materialization.
5. Quay lại hoàn thiện full T3 G2/G3 evidence trước khi tuyên bố T3 gate pass.
6. Khi làm T6, dùng evidence `same_step_ties` của Gold/replay và bảo đảm required checkpoint có
   same-step tie; không tự coi zero tie là pass.
7. T2 đã có real build/promote evidence; không chạy lại Gold full/range nếu chỉ cần kiểm tra code.

Guide có mục **"Nhật ký hiệu chỉnh"** ghi những chỗ đã lỗi thời và đã sửa — đọc mục đó trước khi
tin bất kỳ đoạn nào trong guide, vì nó được viết trước ADR-002/003 và trước khi Feast được cài
thật.
