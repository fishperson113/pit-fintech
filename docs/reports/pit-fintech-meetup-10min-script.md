# PIT Fintech — Kịch bản trình bày meetup 10 phút

Kịch bản này đi cùng deck `docs/reports/pit-fintech-proposal-slides.html`. Mục tiêu là giúp
mentor và người nghe hiểu chiều sâu của temporal correctness, thay vì nghe một danh sách công
nghệ MLOps.

Ngôi xưng mặc định là **em**. Có thể đổi thành **mình** nếu meetup mang tính ngang hàng.

## Phân bổ thời gian

| Phần | Thời lượng | Trọng tâm |
|---|---:|---|
| Slide 1 | 0:00–1:50 | Failure mode và ba invariant |
| Slide 2 | 1:50–3:50 | Hai execution path, một temporal contract |
| Slide 3 | 3:50–8:25 | Vòng đời một transaction và cách tạo evidence |
| Slide 4 | 8:25–10:00 | Engineering trước, research phát triển sau |

## Slide 1 — Vấn đề không phải model dự đoán tốt đến đâu

> Chào mentor và mọi người. Em muốn bắt đầu bằng một ví dụ rất đơn giản.
>
> Giả sử hệ thống phải chấm điểm một giao dịch lúc 10 giờ. Khi tạo training data vào cuối ngày,
> nếu feature “số giao dịch trong 24 giờ gần nhất” vô tình chứa cả giao dịch lúc 11 giờ, model sẽ
> có metric offline rất đẹp, nhưng đang dùng thông tin không tồn tại tại thời điểm ra quyết định.
>
> Vì vậy, bài toán của project này không chỉ là train fraud model. Câu hỏi chính là: **tại mỗi
> prediction cutoff, model thực sự được phép biết những gì?**

*Chỉ lần lượt vào ba invariant.*

> Project được thiết kế quanh ba invariant.
>
> Thứ nhất, không đọc tương lai. Một source event chỉ được đưa vào history nếu thứ tự của nó đứng
> trước transaction đang được score. Với các event cùng timestamp, em dùng deterministic
> tie-break để kết quả không phụ thuộc vào thứ tự file đầu vào.
>
> Ngoài event time, còn có knowledge time, hay `created_timestamp`. Ví dụ một giao dịch xảy ra lúc
> 9 giờ 50 nhưng hệ thống chỉ nhận được lúc 10 giờ 02. Khi score lúc 10 giờ, record đó vẫn phải bị
> loại, vì tại thời điểm ấy hệ thống chưa biết nó tồn tại.
>
> Thứ hai, offline và online phải tạo ra cùng feature semantics tại cùng cutoff. Điều này không có
> nghĩa hai bên dùng cùng database; nó có nghĩa cùng entity, window boundary, default value,
> tie-break và feature version.
>
> Thứ ba, backfill phải tái lập được. Cùng snapshot, version và range phải cho cùng schema, row
> count và canonical checksum.
>
> Do đó, đây không phải dự án chạy theo leaderboard. Thành công được đo bằng correctness evidence
> trước, model metric sau.

**Chuyển ý**

> Từ ba invariant này, em tách hệ thống thành hai execution path và một lớp kiểm chứng xuyên suốt.

## Slide 2 — Hai execution path, một temporal contract

> Slide này có ba khối, nhưng observability không phải một business pipeline thứ ba. Hai vấn đề
> thực thi chính là offline training và online serving; observability dùng để kiểm tra cả hai.
>
> Ở offline training, với mỗi giao dịch lịch sử, hệ thống phải dựng lại đúng feature vector mà
> model có thể nhìn thấy tại thời điểm giao dịch đó. Sau đó mới train với temporal split. Model
> family chưa được khóa trước dữ liệu; PaySim sẽ được EDA trước và LightGBM hiện chỉ là candidate
> baseline.
>
> Ở online serving, cùng một câu hỏi được trả lời tại request time.

*Chỉ vào Online Serving và nói chậm câu tiếp theo.*

> Với transaction `t`, thứ tự bắt buộc là: **đọc history trước `t` → tạo feature → score `t` → sau
> đó mới update state bằng `t`.**
>
> Request fields của transaction hiện tại, như amount hoặc transaction type, vẫn có thể được
> dùng. Điều bị cấm là để chính transaction đó đóng góp vào các historical aggregates trước khi
> score. Nếu update Redis trước, transaction có thể tự làm tăng `transaction_count` hoặc
> `amount_sum` của chính nó.
>
> Sau khi prediction hoàn tất, `t` mới được cập nhật vào Redis và append vào Event History. Replay
> cũng phải xử lý xong toàn bộ `t` rồi mới phát `t+1`.
>
> Observability sẽ theo dõi freshness, parity, latency, errors và version mismatch. Ví dụ model
> yêu cầu feature version `v2` nhưng provider đang phục vụ `v1`, hệ thống phải reject hoặc báo
> không ready, thay vì âm thầm dự đoán.
>
> Điểm nối cả ba khối là một versioned PIT feature contract. Stack vật lý có thể khác nhau, nhưng
> temporal semantics không được khác.

**Chuyển ý**

> Ở slide kiến trúc, em sẽ không đọc từng logo. Em sẽ đi theo vòng đời của đúng một transaction.

## Slide 3 — Một transaction, hai temporal views

*Bắt đầu từ Producer → FastAPI → Redis.*

> Transaction `t` bắt đầu từ một logical Replay Driver. Trong MVP, đây chỉ là một iterator hoặc
> in-memory queue có thứ tự xác định, không phải Kafka. Mục tiêu hiện tại là cô lập và chứng minh
> state transition, chưa phải chứng minh production throughput.
>
> FastAPI nhận `t`, đọc Redis state chỉ chứa history trước `t`, tạo online vector và score. Sau
> prediction, hệ thống mới update Redis, append event vào Event History, rồi mới xử lý `t+1`.
>
> Đây chính là online temporal view: **pre-decision state ngay trước event hiện tại**.

*Di chuyển theo Event History → DuckDB → Delta.*

> Sau khi event đã được ghi vào history, offline pipeline canonicalize dữ liệu. DuckDB sẽ tái dựng
> historical feature vector tại từng cutoff và ghi artifact versioned vào Delta Lake.
>
> Đây là temporal view thứ hai: **khả năng quay lại một thời điểm trong quá khứ và dựng lại model
> lúc đó có thể biết gì**.
>
> Lý do em chọn DuckDB không phải vì PIT chỉ có thể làm bằng DuckDB. Workload offline ở đây chủ
> yếu là quét nhiều event, window, join và aggregate trên Parquet/Delta — tức workload phân tích
> dạng OLAP. DuckDB chạy ngay trong process, xử lý theo cột và không cần dựng database server
> riêng, nên hợp với mục tiêu local CPU và pipeline chạy lại bằng CLI.
>
> PostgreSQL hoàn toàn là một phương án hợp lệ. Em có thể dùng window function, indexed join và
> materialized view để dựng features; nó hợp lý hơn nếu cần database trung tâm, nhiều client hoặc
> transactional writes đồng thời. Với offline path file-first, single-node và read-heavy hiện tại,
> DuckDB ít vận hành hơn. Đây là lựa chọn theo workload, không phải DuckDB đúng còn Postgres sai.
>
> Delta nằm sau DuckDB để lưu artifact có version và hỗ trợ time travel. Còn temporal predicate và
> tests mới chứng minh feature đúng theo thời gian.

*Chỉ vào Feast.*

> Feast cũng không phải thành phần bắt buộc về mặt kỹ thuật. Nếu bỏ Feast, em vẫn có thể dùng
> Delta hoặc Postgres làm feature table rồi tự viết `FeatureSpec`, historical retrieval, script
> đẩy state sang Redis, provider cho API và version gate. Cách đó chạy được, nhưng project phải tự
> sở hữu toàn bộ contract và code kết nối này.
>
> Em giữ Feast ở vai trò mỏng vì nó chuẩn hóa feature definitions/services, historical và online
> retrieval, cùng materialization. Nhờ vậy training và serving tham chiếu cùng contract, còn thời
> gian project tập trung vào PIT semantics và parity thay vì tự xây toàn bộ feature-store plumbing.
>
> Ranh giới là: DuckDB compute, Delta lưu offline, Redis giữ online state, Feast nối retrieval và
> materialization, còn independent oracle mới chứng minh correctness. Feast có thể được bỏ qua ADR,
> nhưng phải thay đủ contract, provider, version và parity gates tương đương.

*Chỉ đường Delta/Feast → Redis.*

> Hai temporal view sẽ được đối chiếu bằng chronological replay. Với mỗi transaction `t`, hệ
> thống lấy offline vector tại cutoff `t`, lấy online vector từ Redis trước khi update, rồi so
> sánh từng field.
>
> Integer và categorical phải khớp tuyệt đối. Float có tolerance khóa trước, hiện là `1e-6`. Chỉ
> so prediction cuối cùng là chưa đủ, vì hai vector khác nhau đôi khi vẫn tình cờ cho cùng output.

> Với backfill, em chỉ giữ một gate thực dụng trong phần trình bày: cùng snapshot, feature version
> và range phải tạo cùng schema, row count và checksum; job lỗi không được để output dở dang được
> coi là hợp lệ. Chi tiết state machine để dành cho implementation report.

*Chỉ vào observability.*

> Hình đang rút gọn phần observability. Luồng chính xác em dự kiến là application phát OTLP tới
> OTel Collector, Prometheus lưu metrics, và Grafana đọc từ Prometheus.
>
> Tuy nhiên, monitoring chỉ giúp phát hiện lỗi khi hệ thống chạy. Oracle, temporal tests và replay
> parity mới là bằng chứng correctness trước release.

**Chuyển ý**

> Vì vậy đầu ra gần nhất của project phải là một hệ thống có evidence chạy lại được, trước khi gọi
> nó là một nghiên cứu hoàn chỉnh.

## Slide 4 — Engineering trước, research phát triển từ evidence

> Giai đoạn đầu tập trung vào engineering và MLOps: pipeline có command contract rõ ràng, feature
> và model có version, replay đúng thứ tự, backfill có manifest, và mọi release gate có
> machine-readable evidence.
>
> Khi nền tảng này ổn định, chính codebase đó sẽ trở thành research platform.
>
> Trong model experiment, leaky full-history là positive control chứ không phải kết quả để
> deploy. So sánh E2 với E3 giúp tách ảnh hưởng của PIT join; so sánh E3 với E4 giúp tách ảnh
> hưởng của random split và temporal split.
>
> Trong pipeline experiment, comparison chính là Delta full recompute với Delta incremental. Hai
> bên giữ cùng storage format để so sánh công bằng.
>
> Em cũng muốn nói rõ trạng thái hiện tại. Phần đã verified gồm synthetic PIT oracle, 12 temporal
> tests với future-read violation bằng 0 trên fixture, cùng Bronze/Silver Delta sample và
> time-travel check.
>
> PaySim EDA, application entity contract, Gold features, Feast integration, backfill, Redis
> replay parity, FastAPI, model lifecycle và observability vẫn là target architecture của Sprint
> 2 và Sprint 3, chưa phải kết quả hoàn tất.
>
> Tóm lại, lộ trình của em là: **build system → prove correctness → sau đó mới đóng gói thành
> thesis E2E**.
>
> Hai điểm em muốn xin feedback sâu nhất là: temporal contract hiện tại đã đủ chặt cho late
> arrival và same-timestamp chưa; và protocol parity/backfill này đã đủ thuyết phục để trở thành
> research evidence chưa?

*Dừng và nhìn mentor; không cần đọc lại nội dung slide.*

## Các điểm phải đặc biệt lưu ý

1. Deck ghi PaySim EDA-first, nhưng ADR cũ vẫn còn nội dung provisional cho IEEE-CIS. Cách nói an
   toàn là: **synthetic temporal contract đã khóa; application dataset và entity key chưa khóa,
   phải chờ PaySim EDA**.
2. Slide 3 thiếu Prometheus. Khi nói, sửa bằng lời thành
   `Application → OTel Collector → Prometheus → Grafana`. Observability backend vẫn là optional
   Sprint 3.
3. “0 future reads” hiện chỉ được verify trên synthetic oracle, không phải trên PaySim hay
   production workload.
4. Không nói DuckDB, Feast hoặc Delta là lựa chọn bắt buộc hay tự bảo đảm correctness. Postgres
   cộng custom `FeatureSpec`/provider/materializer là workaround hợp lệ; stack hiện tại được chọn
   vì hợp workload local OLAP và giảm glue code. Correctness vẫn đến từ oracle, temporal predicate,
   replay ordering, version gates và tests.
5. “Offline = Online” là parity của feature vector tại cùng cutoff, không phải hai bên dùng cùng
   code hay cùng database.
6. Cụm “thesis E2E e-commerce prediction” trên slide 4 chỉ là chuẩn tham chiếu về độ hoàn chỉnh
   của thesis, không phải chuyển domain từ fraud sang e-commerce.

## Câu hỏi mentor dễ hỏi

### “Window SQL hoặc ASOF JOIN chưa đủ sao?”

Chưa đủ. Nó chưa tự giải quyết knowledge time, duplicate policy, same-timestamp tie-break, online
state transition, versioning và recovery.

### “Tại sao vừa dùng Feast vừa cần custom oracle?”

Feast là delivery contract; oracle là specification độc lập. Dùng cùng một implementation để vừa
tính vừa tự kiểm tra sẽ dễ giữ nguyên cùng một bug.

### “Tại sao chọn DuckDB thay vì PostgreSQL?”

Offline workload của project là scan, window, join và aggregate trên file, chạy local single-node.
DuckDB là in-process analytical engine nên ít vận hành hơn. PostgreSQL vẫn làm được và phù hợp hơn
nếu cần server trung tâm, nhiều client hoặc transactional concurrency; lựa chọn này là trade-off
theo workload, không phải correctness requirement.

### “Nếu Postgres và custom code làm được, tại sao vẫn cần Feast?”

Không bắt buộc phải có Feast. Không dùng Feast thì project phải tự sở hữu feature registry/spec,
historical và online retrieval, materialization, provider và version gates. Giữ Feast ở vai trò
mỏng giúp chuẩn hóa boundary đó; nếu bỏ thì phải thay đủ các contract tương đương.

### “Tại sao không dùng Kafka, Spark hoặc Kubernetes?”

Research question hiện tại là temporal correctness và reproducibility. Ordered local replay đủ
để chứng minh semantics; chỉ thêm distributed stack khi benchmark chỉ ra bottleneck thật.

### “Điểm mới của project là gì?”

Không phải thuật toán fraud mới. Điểm trọng tâm là biến PIT correctness, offline/online parity và
reproducible backfill thành contract cùng release gate có bằng chứng máy đọc được.

### “Parity là cùng prediction hay cùng feature?”

Gate chính là cùng feature vector tại cùng cutoff. Prediction giống nhau chưa chứng minh vector
giống nhau.

### “Model nào sẽ được dùng?”

Chưa khóa. PaySim được EDA trước; LightGBM chỉ là candidate. Sau EDA mới cố định một family và
configuration cho toàn bộ experiment matrix.
