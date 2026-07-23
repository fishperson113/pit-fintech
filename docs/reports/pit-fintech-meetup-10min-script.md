# PIT Fintech — Kịch bản trình bày meetup 10 phút

Kịch bản đi cùng `docs/reports/pit-fintech-proposal-slides.html`. Phần nói chính được giữ trong
khoảng 8–9 phút để còn thời gian chuyển slide và dừng nhấn ý.

Ngôi xưng mặc định là **em**; có thể đổi thành **mình** nếu meetup mang tính ngang hàng.

## Phân bổ thời gian

| Phần | Thời lượng | Một ý cần người nghe nhớ |
|---|---:|---|
| Slide 1 | 0:00–1:40 | Model chỉ được biết dữ liệu có trước cutoff |
| Slide 2 | 1:40–3:30 | Offline và online phải tuân theo cùng temporal contract |
| Slide 3 | 3:30–7:30 | Score trước, update sau; correctness phải có evidence |
| Slide 4 | 7:30–9:20 | Đây là PIT research platform hẹp, không phải mini data platform |
| Buffer | 9:20–10:00 | Dừng nhấn ý hoặc xử lý chậm khi chuyển slide |

## Slide 1 — Vấn đề là model được phép biết gì

> Chào mentor và mọi người. Giả sử hệ thống phải chấm điểm một giao dịch lúc 10 giờ. Nếu feature
> “số giao dịch trong 24 giờ gần nhất” vô tình tính cả giao dịch lúc 11 giờ, metric offline có thể
> rất đẹp, nhưng model đã nhìn thấy tương lai.
>
> Vì vậy, project này không tập trung vào việc tìm một fraud model thật phức tạp. Câu hỏi chính
> là: **tại prediction cutoff, model thực sự được phép biết những gì?**
>
> Em dùng ba tiêu chí để trả lời. Một là không có future read. Hai là offline training và online
> serving phải tạo cùng feature vector tại cùng cutoff. Ba là khi backfill cùng snapshot, version
> và khoảng thời gian, hệ thống phải tạo lại cùng kết quả.
>
> Nói ngắn gọn, model metric chỉ đáng tin sau khi ba điều này được chứng minh.

**Câu chốt:** *Correctness của project bắt đầu từ cutoff, không bắt đầu từ model.*

## Slide 2 — Hai execution path, một temporal contract

> Hệ thống có hai đường chạy.
>
> Ở offline training, với mỗi giao dịch lịch sử, em phải dựng lại đúng feature vector mà model có
> thể biết tại thời điểm giao dịch đó; sau đó mới train và đánh giá bằng temporal split.
>
> Ở online serving, với transaction `t`, thứ tự bắt buộc là:
> **đọc history trước `t` → tạo feature → score `t` → sau đó mới update state bằng `t`.**
> Nếu update trước, giao dịch hiện tại sẽ tự làm tăng các feature lịch sử của chính nó.
>
> Hai bên không cần dùng cùng database, nhưng phải giống nhau về entity, window boundary, default
> value, tie-break và feature version. Observability theo dõi freshness, latency và version
> mismatch; còn temporal tests và parity test mới chứng minh dữ liệu đúng.

**Câu chốt:** *Offline và online có thể khác cách chạy, nhưng không được khác ý nghĩa feature.*

## Slide 3 — Đi theo vòng đời của một transaction

> Em sẽ không đọc từng logo mà đi theo một transaction `t`.
>
> Replay Driver gửi `t` vào FastAPI. API đọc Redis, lúc này Redis chỉ chứa history trước `t`, rồi
> tạo feature và score. Chỉ sau khi có prediction, hệ thống mới update Redis, ghi `t` vào Event
> History và chuyển sang `t+1`.
>
> Event History sau đó đi vào offline path. DuckDB làm phần tính toán nặng như scan, window, join
> và aggregate để dựng lại feature tại từng cutoff. Delta lưu các bảng và artifact có version để
> có thể time travel và tái lập đúng input cũ.
>
> Vì vậy DuckDB và Delta không trùng vai trò: **DuckDB là compute engine; Delta là storage và
> versioning layer.** PostgreSQL vẫn có thể làm cả phần này bằng SQL và custom versioning, nhưng
> với workload local, file-first và thiên về OLAP, DuckDB cộng Delta nhẹ vận hành hơn.
>
> Feast được giữ ở vai trò mỏng: chuẩn hóa feature contract, retrieval và materialization từ
> offline sang Redis. Feast không tự bảo đảm PIT correctness và cũng không bắt buộc; nếu bỏ Feast,
> em phải tự viết các contract, provider, materializer và version gate tương đương.
>
> Cuối cùng, em chứng minh hệ thống bằng chronological replay. Tại mỗi cutoff `t`, offline vector
> được so trực tiếp với online vector trước khi Redis nhận `t`. Integer và categorical phải khớp
> tuyệt đối; float dùng tolerance khóa trước. Backfill cùng input và version cũng phải cho cùng
> schema, row count và checksum.
>
> Đó mới là đầu ra chính: evidence cho thấy hệ thống không đọc tương lai, không bị offline/online
> skew và có thể dựng lại kết quả.

**Câu chốt:** *Stack chỉ thực thi contract; oracle, replay và tests mới chứng minh contract đúng.*

## Slide 4 — Engineering trước, research phát triển từ evidence

> Lộ trình của project là: **build system → prove correctness → sau đó mới đóng gói thành thesis
> E2E.**
>
> Về model experiment, em sẽ dùng một baseline cố tình leaky như positive control, rồi so với
> PIT-correct features và temporal split. Nếu metric giảm sau khi loại leakage thì đó vẫn là kết
> quả hợp lệ, vì con số mới phản ánh điều model thực sự biết khi deploy.
>
> Về pipeline experiment, comparison chính là Delta full recompute với Delta incremental trên
> cùng storage format, để đo đổi chác giữa runtime, reuse và khả năng tái lập.
>
> Hiện tại, phần đã verified là synthetic oracle, 12 temporal tests với 0 future read trên fixture,
> cùng Bronze/Silver Delta sample và time-travel check. PaySim EDA, Gold features, Feast,
> backfill, Redis parity, FastAPI và model lifecycle vẫn là phần phải triển khai tiếp.
>
> Vì vậy, scope hiện tại là một **PIT feature platform hẹp để trả lời research question**, không
> phải mini data platform và cũng chưa phải production real-time fraud system.
>
> Em muốn xin feedback ở hai điểm: temporal contract này đã đủ chặt cho late arrival và
> same-timestamp chưa; và bộ evidence parity/backfill đã đủ thuyết phục chưa?

**Câu chốt:** *Giá trị của project nằm ở bằng chứng correctness, không nằm ở số công nghệ.*

## Những điểm cần nhớ khi nói

1. “0 future read” hiện chỉ được verify trên synthetic fixture, chưa phải PaySim hay production.
2. Dataset application và entity key chưa khóa; phải chờ PaySim EDA.
3. Không nói DuckDB, Delta hoặc Feast tự bảo đảm correctness. Correctness đến từ temporal
   predicate, score-before-update, oracle, version gate và tests.
4. Luồng observability chính xác là
   `Application → OTel Collector → Prometheus → Grafana`; đây là optional Sprint 3.
5. Nếu sắp hết giờ, bỏ đoạn PostgreSQL và Feast workaround ở slide 3; không bỏ phần replay parity.

## Q&A dự phòng — không đọc trong phần trình bày

### “Window SQL hoặc ASOF JOIN chưa đủ sao?”

Chưa. Chúng không tự giải quyết late arrival, knowledge time, duplicate policy, same-timestamp
tie-break, online update ordering và versioning.

### “Tại sao cần cả DuckDB và Delta?”

DuckDB tính feature; Delta lưu dữ liệu và version của kết quả. Một bên là compute, một bên là
storage/versioning.

### “Tại sao không chỉ dùng PostgreSQL?”

PostgreSQL làm được. DuckDB được chọn vì workload hiện tại là local, file-first, read-heavy và
thiên về OLAP; PostgreSQL hợp hơn khi cần database server trung tâm và nhiều concurrent writer.

### “Tại sao cần Feast?”

Feast không bắt buộc và không phải correctness oracle. Nó giảm custom glue code bằng cách giữ
feature contract, retrieval và materialization nhất quán; bỏ Feast thì phải tự thay đủ các
boundary đó.

### “Tại sao không dùng Kafka, Spark hoặc Kubernetes?”

Research question hiện tại là temporal correctness và reproducibility. Ordered local replay đủ
để kiểm chứng semantics; distributed stack chỉ cần khi benchmark chứng minh có bottleneck.

### “Điểm mới của project là gì?”

Không phải fraud algorithm mới. Điểm chính là biến PIT correctness, offline/online parity và
reproducible backfill thành contract cùng release gate có evidence máy đọc được.
