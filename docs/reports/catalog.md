# Catalog thuật ngữ PIT Fintech — bản tiếng Việt dễ hiểu

Tài liệu này giải thích những keyword tiếng Anh xuất hiện trong slide và
`pit-fintech-meetup-10min-script.md`. Không cần học thuộc toàn bộ. Trước buổi meetup, hãy ưu tiên
đọc các mục có nhãn **Cốt lõi**.

## 1. Một ví dụ dùng xuyên suốt

Giả sử hệ thống cần chấm điểm giao dịch **T lúc 10:00**:

| Giao dịch | Xảy ra lúc | Hệ thống nhận lúc | T có được nhìn thấy không? | Lý do |
|---|---:|---:|---|---|
| A | 09:40 | 09:41 | Có | Đã xảy ra và hệ thống đã biết trước 10:00 |
| B | 09:50 | 10:05 | Không | Xảy ra sớm nhưng đến hệ thống muộn |
| T | 10:00 | 10:00 | Không nằm trong history | Đây là giao dịch đang được chấm điểm |
| C | 10:10 | 10:10 | Không | Xảy ra trong tương lai |

Current request fields của T, ví dụ số tiền hoặc loại giao dịch, vẫn có thể được dùng để score.
Điều bị cấm là cho T tự đóng góp vào các feature lịch sử như “số giao dịch trong một giờ qua”
trước khi score.

## 2. Nhóm cốt lõi về thời gian

### Point-in-Time, viết tắt là PIT — **Cốt lõi**

**Dịch dễ hiểu:** đúng theo thông tin tồn tại tại một thời điểm.

Một feature là PIT-correct nếu tại cutoff 10:00, nó chỉ dùng dữ liệu mà hệ thống thực sự có thể
biết lúc 10:00. Trong ví dụ trên, A được dùng; B, T và C không được nằm trong history.

PIT không chỉ là lọc `timestamp <= 10:00`. Nó còn cần xử lý event đến muộn, event cùng timestamp,
duplicate và thứ tự score-before-update.

**Câu nói khi trình bày:**

> PIT-correct nghĩa là em có thể đứng tại một thời điểm trong quá khứ và chỉ dùng đúng thông tin
> hệ thống đã biết khi đó.

### Prediction cutoff — **Cốt lõi**

**Dịch dễ hiểu:** ranh giới thông tin tại lúc ra quyết định.

Nếu transaction T được score lúc 10:00, cutoff của T xác định dữ liệu nào được đứng bên trái —
được phép dùng — và dữ liệu nào đứng bên phải — chưa được phép dùng.

Trong contract hiện tại, cutoff không chỉ có timestamp. Nó còn dùng deterministic tie-break cho
event cùng thời điểm và một knowledge-time cutoff cho late arrival.

**Câu nói khi trình bày:**

> Cutoff là đường biên: thông tin ở trước và đã được hệ thống biết thì được dùng; phần còn lại bị
> loại.

### Temporal

**Dịch dễ hiểu:** liên quan đến thời gian và thứ tự thời gian.

`Temporal correctness` là tính đúng đắn khi dữ liệu thay đổi theo thời gian. `Temporal test` là
test các trường hợp như future event, late arrival, same timestamp hoặc window boundary.

Từ này không có nghĩa đơn giản là “dữ liệu có một cột timestamp”. Quan trọng là hệ thống hiểu và
thi hành đúng thứ tự sự kiện.

### Temporal view — **Cốt lõi**

**Dịch dễ hiểu:** góc nhìn dữ liệu của hệ thống tại một mốc thời gian cụ thể.

`View` ở đây là cách nhìn dữ liệu, không nhất thiết là một SQL `VIEW`.

Project có hai temporal view chính:

1. **Offline historical view:** quay lại từng cutoff trong quá khứ và dựng lại feature mà model
   lúc đó được phép nhìn thấy.
2. **Online pre-decision view:** state trong Redis ngay trước khi transaction hiện tại được score.

Hai view dùng storage và cách tính khác nhau, nhưng tại cùng entity, cutoff và feature version,
chúng phải tạo cùng feature vector.

**Câu nói khi trình bày:**

> Temporal view là ảnh chụp logic của dữ liệu tại một mốc thời gian. Offline tái dựng ảnh chụp
> trong quá khứ; online giữ ảnh chụp ngay trước request hiện tại.

### Event time

**Dịch dễ hiểu:** thời điểm sự kiện thực sự xảy ra trong nghiệp vụ.

Trong ví dụ, event time của B là 09:50. Nó cho biết giao dịch thuộc vị trí nào trên business
timeline, nhưng chưa cho biết hệ thống đã nhận được nó hay chưa.

### Created time / knowledge time / availability time — **Cốt lõi**

**Dịch dễ hiểu:** thời điểm hệ thống biết record đó tồn tại và có thể sử dụng nó.

Trong ví dụ, B có event time 09:50 nhưng knowledge time 10:05. Vì vậy B không được xuất hiện trong
vector được tạo lúc 10:00.

Tên cột cụ thể có thể là `created_timestamp`, `ingested_at` hoặc `available_at`; ý nghĩa cần được
khóa rõ trong contract.

**Điểm dễ nhầm:** event time trả lời “chuyện xảy ra khi nào”; knowledge time trả lời “hệ thống biết
chuyện đó từ khi nào”.

### Pre-decision feature — **Cốt lõi**

**Dịch dễ hiểu:** feature được tạo ngay trước khi ra quyết định.

Với T lúc 10:00, pre-decision feature có thể chứa count và amount của A, nhưng chưa chứa T. Đây là
vector dùng cho cả training row và online scoring.

### Post-event state — **Cốt lõi**

**Dịch dễ hiểu:** trạng thái sau khi event hiện tại đã được xử lý xong.

Sau khi T được score, state mới có thể cộng T vào count, sum hoặc last-transaction timestamp để
phục vụ giao dịch tiếp theo.

Thứ tự bắt buộc là:

```text
đọc pre-decision state
→ score T
→ tạo post-event state có T
→ xử lý giao dịch kế tiếp
```

### Future read / future leakage — **Cốt lõi**

**Dịch dễ hiểu:** model đọc một thông tin mà tại thời điểm dự đoán chưa tồn tại hoặc chưa được hệ
thống biết.

Nếu feature của T lúc 10:00 chứa giao dịch C lúc 10:10, đó là future read rõ ràng. Nếu nó chứa B
vì chỉ nhìn event time 09:50 mà bỏ qua knowledge time 10:05, đó cũng là future leakage.

Hậu quả là metric offline có thể tốt giả tạo nhưng giảm mạnh khi deploy.

### Target leakage

**Dịch dễ hiểu:** feature vô tình tiết lộ label hoặc kết quả xảy ra sau quyết định.

Ví dụ, dùng cột được tạo sau khi fraud investigation kết thúc để dự đoán fraud là target leakage.
Nó khác future leakage về nguồn gốc, nhưng cả hai đều làm evaluation không trung thực.

### Temporal semantics — **Cốt lõi**

**Dịch dễ hiểu:** bộ quy tắc xác định dữ liệu được hiểu như thế nào theo thời gian.

Nó bao gồm:

- entity nào được gom history cùng nhau;
- event nào đứng trước event nào;
- cận cửa sổ có được tính hay không;
- late arrival được dùng từ lúc nào;
- duplicate được bỏ hay reject;
- transaction hiện tại được update vào state lúc nào.

Hai hệ thống có cùng tên feature nhưng khác một trong các quy tắc trên thì vẫn khác semantics.

### Window và window boundary

**Dịch dễ hiểu:** khoảng thời gian nhìn ngược từ cutoff và quy tắc tại ranh giới của khoảng đó.

Feature `txn_count_1h` tại 10:00 thường nhìn history từ 09:00 đến ngay trước 10:00. Project hiện
dùng cận dưới inclusive: event đúng 09:00 được tính; cận trên strict: transaction đang score lúc
10:00 không được tính vào history.

### Same timestamp và tie-break

**Dịch dễ hiểu:** khi hai event có cùng timestamp, cần thêm một khóa để quyết định thứ tự ổn định.

`Tie-break` là quy tắc phá hòa. Oracle hiện dùng `(event_timestamp, transaction_id)`. Tuy nhiên,
transaction ID chỉ là candidate tie-break; application dataset phải được EDA xác nhận trước khi
khóa bằng ADR.

### Deterministic

**Dịch dễ hiểu:** cùng logical input luôn tạo cùng kết quả, không phụ thuộc vào thứ tự đọc file hay
lần chạy.

Nếu shuffle input nhưng checksum của feature vector không đổi, computation có tính deterministic.

### Late arrival

**Dịch dễ hiểu:** event xảy ra sớm nhưng đến hệ thống muộn.

B trong ví dụ là late arrival. Đây là lý do chỉ dùng event timestamp chưa đủ để chứng minh
PIT correctness.

## 3. Feature, entity và contract

### Entity / entity key

**Dịch dễ hiểu:** đối tượng mà history và feature được gom theo.

Trong fraud scoring, entity có thể là account, card, customer hoặc một composite key. Chọn sai
entity có thể làm history quá thưa, trộn nhiều người hoặc vô tình đưa leakage vào feature.

### Feature

**Dịch dễ hiểu:** một tín hiệu đầu vào cho model.

Ví dụ: số giao dịch trong một giờ, tổng amount trong 24 giờ, thời gian từ giao dịch trước, hoặc tỷ
lệ amount hiện tại so với mean lịch sử.

### Feature vector

**Dịch dễ hiểu:** toàn bộ các feature của một transaction tại một cutoff, viết thành một hàng giá
trị đưa vào model.

`Offline/online parity` được kiểm tra trên feature vector, không chỉ trên prediction cuối cùng.

### Historical aggregate

**Dịch dễ hiểu:** feature được tổng hợp từ history, ví dụ count, sum, mean, max hoặc distinct
count trong một window.

Current request field khác historical aggregate. Amount của T có thể dùng trực tiếp; T không được
tự chui vào `amount_sum_24h` trước khi score.

### Feature contract / FeatureSpec

**Dịch dễ hiểu:** bản mô tả chính thức về cách một feature được tạo và phục vụ.

Một contract tốt ghi rõ tên, kiểu dữ liệu, entity, source, window, cutoff semantics, default,
version và tolerance. Contract giúp các implementation khác nhau nói cùng một “ngôn ngữ”.

### Feature version

**Dịch dễ hiểu:** phiên bản của định nghĩa feature.

Nếu thay window từ 24 giờ thành 12 giờ hoặc đổi cách xử lý missing value, đó phải là version mới.
Không được lặng lẽ sửa định nghĩa sau khi model đã train.

### FeatureProvider

**Dịch dễ hiểu:** lớp giao tiếp mà serving dùng để xin feature, không cần biết bên dưới là Redis,
fixture hay một implementation khác.

Boundary này giúp test parity và thay online store mà không trộn retrieval logic vào model code.

## 4. Offline, online và parity

### Offline

**Dịch dễ hiểu:** xử lý không nằm trên request scoring trực tiếp, thường dùng cho historical
build, backfill, training và experiment.

Trong project, DuckDB và Delta thuộc offline path.

### Online

**Dịch dễ hiểu:** xử lý tại thời điểm có request, ưu tiên retrieval và scoring nhanh.

Trong project, FastAPI và Redis thuộc online path.

`Online` ở đây không tự động có nghĩa production streaming hoặc high availability.

### Offline/online parity — **Cốt lõi**

**Dịch dễ hiểu:** offline và online tạo cùng feature vector cho cùng entity, cutoff và version.

Integer và categorical phải khớp tuyệt đối. Float được phép chênh trong tolerance khóa trước,
hiện là `1e-6`.

**Câu nói khi trình bày:**

> Parity không phải cùng prediction; gate chính là cùng feature vector tại cùng cutoff.

### Training-serving skew

**Dịch dễ hiểu:** dữ liệu hoặc cách tính feature khi train khác với khi serve.

Ví dụ offline dùng cận window inclusive nhưng online dùng exclusive. Model được train trên một
phân phối nhưng gặp một phân phối khác khi chạy thật.

### State và state transition

**Dịch dễ hiểu:** `state` là thông tin tóm tắt hệ thống đang giữ; `state transition` là cách state
thay đổi khi có event mới.

Ví dụ:

```text
state trước T: count_1h = 3
score T bằng count_1h = 3
state sau T: count_1h = 4
```

### Chronological replay / Replay Driver — **Cốt lõi**

**Dịch dễ hiểu:** phát lại event theo thứ tự thời gian để mô phỏng serving một cách kiểm soát được.

Replay Driver xử lý xong `t`, gồm score và post-score updates, rồi mới phát `t+1`. Nó giúp kiểm tra
ordering, duplicate, recovery và parity mà chưa cần Kafka.

### Materialization

**Dịch dễ hiểu:** đưa feature hoặc state đã chuẩn bị từ offline contract sang online store để
serving đọc nhanh.

Trong project, Feast sẽ đóng vai trò interface materialization vào Redis. Materialization không
đồng nghĩa compute feature và không tự bảo đảm PIT correctness.

### Watermark

**Dịch dễ hiểu:** mốc cho biết online state đã được cập nhật đầy đủ đến đâu.

Nếu watermark mới đến 09:55 nhưng request ở 10:00, system có thể đánh dấu feature stale hoặc từ
chối dự đoán theo policy.

### Freshness / stale feature

**Dịch dễ hiểu:** `freshness` đo feature còn mới đến đâu; `stale` nghĩa là cũ hơn mức cho phép.

Freshness khác parity: hai vector có thể giống nhau nhưng đều đang cũ, hoặc đủ mới nhưng tính khác
nhau.

## 5. Oracle và cách chứng minh đúng

### Oracle / reference oracle — **Cốt lõi**

**Dịch dễ hiểu:** implementation tham chiếu được viết ưu tiên dễ đọc và đúng, dùng làm chuẩn để
kiểm tra implementation tối ưu.

Oracle không phải AI model. Trong project, nó là Python code thể hiện trực tiếp temporal
predicate và expected behavior cho các edge case.

### Synthetic temporal oracle

**Dịch dễ hiểu:** bộ dữ liệu nhỏ được tự thiết kế, có đáp án feature tính tay và bao phủ các trường
hợp khó về thời gian.

Nó là ground truth cho temporal correctness. Fraud label của dataset lớn chỉ là ground truth cho
model evaluation.

### Differential test

**Dịch dễ hiểu:** cho hai implementation tính cùng input rồi so kết quả.

Sau này DuckDB/Feast path phải khớp với independent oracle. Cách này giảm nguy cơ optimized path
tự kiểm tra bằng chính logic có bug của nó.

### Evidence

**Dịch dễ hiểu:** bằng chứng có thể kiểm tra hoặc chạy lại, ví dụ test result, manifest, checksum,
version hoặc raw metric.

Sơ đồ kiến trúc và screenshot chỉ cho biết ý định thiết kế; chúng không chứng minh hệ thống đã
chạy đúng.

### Release gate / hard gate

**Dịch dễ hiểu:** điều kiện bắt buộc phải pass trước khi promote model hoặc gọi một milestone là
hoàn tất.

Ví dụ: future-read violations bằng 0, parity mismatch bằng 0 và model/feature version phải tương
thích.

## 6. Backfill và reproducibility

### Backfill — **Cốt lõi**

**Dịch dễ hiểu:** tính hoặc tính lại dữ liệu/feature cho một khoảng thời gian trong quá khứ.

Backfill cần khi thêm feature mới, sửa logic, xử lý source correction hoặc tái tạo training
dataset.

### Full / range / incremental backfill

- **Full:** tính lại toàn bộ dữ liệu.
- **Range:** chỉ tính lại một khoảng thời gian được chọn.
- **Incremental:** chỉ xử lý phần mới hoặc phần thực sự bị ảnh hưởng.

Comparison chính của project là Delta full recompute với Delta incremental để không trộn lợi ích
của storage format với lợi ích của incremental reuse.

### Atomic — **Cốt lõi**

**Dịch dễ hiểu:** hoặc publish toàn bộ output hoàn chỉnh, hoặc không publish gì.

Job lỗi giữa chừng không được để người đọc nhìn thấy một dataset nửa cũ, nửa mới.

### Idempotent — **Cốt lõi**

**Dịch dễ hiểu:** chạy lại cùng một công việc không làm dữ liệu bị cộng hoặc ghi trùng.

Retry một transaction hoặc backfill run không được double-count.

### Reproducible — **Cốt lõi**

**Dịch dễ hiểu:** khi ghim đúng input và các version liên quan, có thể tái tạo cùng logical output.

Reproducible mạnh hơn “lần này chạy không lỗi”. Nó yêu cầu biết chính xác đã dùng snapshot,
feature version, code và dependency nào.

### Snapshot

**Dịch dễ hiểu:** ảnh chụp của dataset tại một version hoặc trạng thái xác định.

Snapshot giúp một training run không âm thầm đọc dữ liệu mới xuất hiện sau experiment.

### Time travel

**Dịch dễ hiểu:** đọc lại một version cũ của Delta table.

Time travel giúp tìm đúng source snapshot, nhưng muốn reproduce kết quả vẫn cần feature contract,
code version, deterministic compute và manifest.

### Manifest — **Cốt lõi**

**Dịch dễ hiểu:** phiếu kê khai machine-readable của một run hoặc artifact.

Một backfill manifest nên ghi dataset snapshot ID, Delta source versions, entity/feature version,
cutoff range, code commit, dependency lock, checksums và run ID.

### Lineage

**Dịch dễ hiểu:** dấu vết cho biết output được tạo từ source, version và transformation nào.

Lineage giúp audit một feature có đọc nhầm future hoặc label-derived field hay không.

### Checksum / canonical checksum

**Dịch dễ hiểu:** dấu vân tay của dữ liệu dùng để phát hiện kết quả có thay đổi hay không.

`Canonical checksum` được tính sau khi chuẩn hóa thứ tự và cách biểu diễn logical data. Không nên
chỉ hash raw Parquet bytes vì encoding vật lý có thể khác dù dữ liệu logic giống nhau.

### Canonicalize

**Dịch dễ hiểu:** chuẩn hóa dữ liệu về một representation ổn định trước khi xử lý hoặc so sánh.

Ví dụ: thống nhất kiểu category, missing value, ordering và duplicate policy.

### Deduplicate / conflicting duplicate

**Dịch dễ hiểu:** loại record trùng hoàn toàn; nếu cùng ID nhưng nội dung khác nhau thì reject thay
vì âm thầm chọn một record.

## 7. Vai trò của từng công nghệ

| Công nghệ | Hiểu đơn giản | Vai trò trong project | Không nên nói |
|---|---|---|---|
| DuckDB | Database phân tích chạy local | Compute PIT features và SQL analytics | DuckDB tự bảo đảm PIT correctness |
| Delta Lake | Lớp bảng versioned trên Parquet | Offline artifacts, ACID commit, schema và time travel | Có Delta là backfill tự reproducible |
| Feast | Feature-store framework | Contract, registry, retrieval và materialization mỏng | Feast là correctness oracle hoặc compute engine |
| Redis | Kho key-value trong memory | Giữ online state để retrieval nhanh | Redis là historical ground truth |
| FastAPI/Uvicorn | Python API runtime | Boundary nhận transaction, lấy feature và score | Đây đã là production-scale serving |
| MLflow | Experiment tracking và model registry | Log run, quản lý candidate/champion/previous | MLflow tự kiểm tra feature correctness |
| JupyterLab | Môi trường notebook | EDA và experiment | Notebook là production pipeline executor |
| OpenTelemetry / OTel | Chuẩn instrumentation | Phát traces, metrics và logs theo contract | OTel là database lưu metric |
| OTLP | Giao thức truyền telemetry | Application gửi telemetry tới OTel Collector | OTLP là dashboard |
| Prometheus | Telemetry backend cho metrics | Lưu và query time-series metrics | Prometheus thay temporal tests |
| Grafana | Giao diện dashboard | Đọc Prometheus và trực quan hóa | Grafana nhận trực tiếp mọi telemetry hoặc chứng minh correctness |
| Makefile / CLI | Command boundary | Cho người và CI chạy cùng workflow | Nhiều command đồng nghĩa hệ thống đã verified |
| CI | Tự động chạy checks khi code thay đổi | Fast fixture lane và regression gate | CI thay thế clean-room reproduction |

## 8. Thuật ngữ experiment và research

### EDA — Exploratory Data Analysis

**Dịch dễ hiểu:** khám phá dữ liệu trước khi khóa quyết định.

PaySim EDA cần kiểm tra temporal structure, repeated entity history, imbalance, leakage risk và
cardinality trước khi chốt entity key, feature scope và model family.

### Random split

**Dịch dễ hiểu:** chia train/test ngẫu nhiên. Với dữ liệu theo thời gian, cách này có thể làm train
và test trộn lẫn chronology và tạo kết quả lạc quan.

### Temporal split — **Cốt lõi**

**Dịch dễ hiểu:** train bằng dữ liệu quá khứ và đánh giá trên giai đoạn tương lai.

PIT join bảo vệ từng feature vector; temporal split bảo vệ thứ tự train/test. Cần cả hai.

### Positive control

**Dịch dễ hiểu:** một setup cố ý có lỗi hoặc hiệu ứng đã biết để chứng minh experiment có khả năng
phát hiện nó.

E2 dùng leaky full-history và random split như positive control; nó không phải model được phép
deploy.

### Ablation

**Dịch dễ hiểu:** thay hoặc bỏ từng thành phần trong khi giữ các phần còn lại ổn định để đo tác
động riêng của thành phần đó.

E2 với E3 giúp tách ảnh hưởng PIT join; E3 với E4 giúp tách ảnh hưởng của split.

### PR-AUC

**Dịch dễ hiểu:** metric tập trung vào trade-off giữa precision và recall, phù hợp hơn accuracy khi
fraud rất hiếm.

### ROC-AUC

**Dịch dễ hiểu:** khả năng model xếp một positive sample cao hơn một negative sample trên nhiều
threshold. Với dữ liệu cực mất cân bằng, nó có thể nhìn đẹp hơn trải nghiệm thực tế nên chỉ là
secondary metric trong project.

### Recall at fixed FPR

**Dịch dễ hiểu:** khi giữ tỷ lệ báo động nhầm ở một mức cố định, model bắt được bao nhiêu fraud.

Metric này giúp diễn giải trade-off vận hành rõ hơn một con số accuracy tổng quát.

### Model family

**Dịch dễ hiểu:** nhóm thuật toán model, ví dụ logistic regression hoặc gradient-boosted trees.

Project chưa khóa model family; LightGBM chỉ là candidate cho đến khi PaySim EDA đủ evidence.

### Paper-inspired adaptation

**Dịch dễ hiểu:** học và áp dụng một số ý tưởng từ paper vào bối cảnh khác, không tuyên bố lặp lại
toàn bộ paper.

Project adapt PIT semantics, computation reuse và versioned materialization; không claim reproduce
speedup của paper trên Spark/FeathrPO.

### Target architecture

**Dịch dễ hiểu:** kiến trúc đích đang hướng tới, không đồng nghĩa tất cả component đã chạy.

Khi trình bày slide 2–3, dùng từ “sẽ”, “dự kiến” hoặc “target path” cho phần Sprint 2/3.

### Planned / implemented / verified — **Cốt lõi khi báo cáo trạng thái**

- **Planned:** có trong kế hoạch, chưa có code hoặc artifact chạy được.
- **Implemented:** đã có code/artifact nhưng gate liên quan chưa được verify đầy đủ.
- **Verified:** command và acceptance evidence đã pass trong workspace.

Hiện synthetic oracle và sample Bronze/Silver đã verified. Feast, Gold backfill, Redis replay
parity, FastAPI scoring, model lifecycle và observability vẫn là planned target.

## 9. Cheat sheet: thay keyword bằng câu tiếng Việt

| Keyword | Có thể nói đơn giản là |
|---|---|
| Temporal view | Góc nhìn dữ liệu tại một mốc thời gian |
| Prediction cutoff | Ranh giới thông tin lúc ra quyết định |
| PIT-correct | Chỉ dùng dữ liệu đã tồn tại và đã biết lúc đó |
| Knowledge time | Thời điểm hệ thống thực sự biết record |
| Pre-decision feature | Feature trước khi ghi transaction hiện tại vào history |
| Post-event state | State sau khi đã score và cập nhật event hiện tại |
| Parity | Offline và online khớp feature tại cùng cutoff |
| Training-serving skew | Train một kiểu nhưng serve lại tính kiểu khác |
| Replay | Phát lại event có thứ tự để mô phỏng serving |
| Backfill | Tính hoặc tính lại feature cho dữ liệu quá khứ |
| Atomic | Hoàn tất toàn bộ hoặc không publish |
| Idempotent | Chạy lại không tạo trùng |
| Reproducible | Ghim đúng version thì tái tạo cùng kết quả |
| Manifest | Phiếu kê khai input, version và output của một run |
| Oracle | Bản tham chiếu đơn giản dùng để kiểm tra bản tối ưu |
| Materialization | Đưa feature/state sang online store để phục vụ nhanh |
| Watermark | Mốc cho biết online state đã cập nhật tới đâu |
| Freshness | Feature còn mới hay đã quá cũ |
| Lineage | Dấu vết output được tạo từ nguồn nào |
| Release gate | Điều kiện bắt buộc phải pass trước khi phát hành |

## 10. Năm câu nên nhớ trước meetup

1. **PIT correctness trả lời model được phép biết gì tại đúng thời điểm ra quyết định.**
2. **Transaction hiện tại phải được score trước, sau đó mới update vào historical state.**
3. **Temporal view là góc nhìn dữ liệu tại một mốc; offline tái dựng quá khứ, online giữ state
   ngay trước request.**
4. **Feast giữ contract; DuckDB compute; Delta lưu offline; Redis giữ online state; oracle mới là
   correctness authority.**
5. **Cùng exact snapshot, version, range và code phải tái tạo cùng logical checksum.**
