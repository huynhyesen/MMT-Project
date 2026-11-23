# MMT Project

MMT giúp phụ huynh quản lý thời gian sử dụng máy tính của trẻ trên Windows và Linux. Mỗi hồ sơ trẻ ghép với một máy. Phụ huynh đặt giới hạn và duyệt yêu cầu trên dashboard web, còn Agent trên máy con áp dụng các quy tắc.

## Chức năng

| Thành phần | Chức năng |
| --- | --- |
| Dashboard phụ huynh | Tạo hồ sơ và mã ghép nối, đặt hạn mức ngày và giờ giới nghiêm, quản lý quy tắc web và ứng dụng, duyệt hoặc từ chối yêu cầu, xem báo cáo và cảnh báo. |
| Góc Của Con | Đăng nhập bằng PIN, xem thời gian còn lại, mở web và gửi yêu cầu khi gặp giới hạn, xin thêm giờ hoặc xin mở web và ứng dụng, xem phản hồi và lịch sử yêu cầu. |
| Agent máy con | Đồng bộ quy tắc, ghi nhận hoạt động ứng dụng, chặn ứng dụng theo quy tắc và khóa màn hình khi đến giờ giới nghiêm hoặc hết hạn mức ngày. Khi máy con đang kết nối, phụ huynh có thể khóa, mở khóa hoặc gửi lời nhắn tới máy đã chọn. |
| Tiện ích Chrome/Edge | Duyệt web tự do có lọc, đếm giờ tab đang sử dụng, chặn và cảnh báo tên miền 18+ trong danh sách lọc. |
| Backend | Lưu hồ sơ, yêu cầu và dữ liệu sử dụng trong SQLite, tách báo cáo theo thiết bị và đặt lại bộ đếm khi sang ngày mới theo giờ của máy chủ. |

## Chuẩn bị

Cài **Python 3.11 trở lên** và Git trên hai máy. Trên Windows, kiểm tra lệnh `python --version` chạy được trong terminal. Trên Linux, cần có `python3`, mô-đun `venv` và quyền `sudo` trên máy con. Khi dùng trong gia đình, hai máy cần kết nối cùng mạng LAN để Agent có thể truy cập Backend.

Lấy nhánh `version1` trên cả hai máy.

```bash
git clone --branch version1 https://github.com/huynhyesen/MMT-Project.git
cd MMT-Project
```

## Cài đặt và sử dụng

### 1. Khởi động máy phụ huynh

Chạy launcher từ thư mục dự án.

| Hệ điều hành | Lệnh |
| --- | --- |
| Windows, Command Prompt | `KhoiDong_ChaMe.bat` |
| Linux | `bash KhoiDong_ChaMe.sh` |

Launcher tạo môi trường Python khi cần và hỏi mật khẩu nếu `MMT_PARENT_PASSWORD` chưa được đặt. Trên Windows, nhập mật khẩu ở cửa sổ **MMT Backend Server**.

Mở `http://localhost:8008/parent/` trên máy phụ huynh. Tên đăng nhập là **`parent`**. Dùng mật khẩu vừa nhập hoặc giá trị đã cấu hình trong `MMT_PARENT_PASSWORD`. Giữ Backend chạy trong lúc sử dụng app.

### 2. Tạo hồ sơ và ghép nối máy con

1. Trên dashboard phụ huynh, vào **Hồ sơ trẻ → Thêm hồ sơ bé**. Nhập tên trẻ, PIN 4 chữ số và hạn mức ngày. Bạn có thể đặt tên máy ngay trong biểu mẫu.
2. Sau khi lưu hồ sơ, dashboard hiện mã ghép nối dùng một lần, có hiệu lực **10 phút**.
3. Trên máy con, chạy `Chay_MayCon.bat` (Windows) hoặc `bash Chay_MayCon.sh` (Linux). Chấp nhận yêu cầu quyền quản trị rồi nhập mã ghép nối. Nếu Agent không tìm thấy Backend, nhập địa chỉ máy phụ huynh hiển thị trong launcher, ví dụ `http://192.168.1.10:8008`.
4. Sau khi ghép nối, giữ Agent chạy. Mở **Góc Của Con** từ Agent và nhập PIN của hồ sơ đã ghép.

Nếu mã hết hạn, mở thẻ hồ sơ và chọn **Mã ghép nối** để lấy mã mới. Để chuyển hồ sơ sang máy khác, chọn **Đổi máy**. Thao tác này thu hồi quyền truy cập của máy cũ. Nếu máy đích từng được ghép nối, chạy lại launcher với `--pair`. Trên Windows, chạy lệnh này từ Command Prompt đã mở bằng quyền quản trị.

```bat
Chay_MayCon.bat --pair
```

```bash
bash Chay_MayCon.sh --pair
```

### 3. Bật đếm giờ web và lọc 18+

Cài tiện ích trong hồ sơ Chrome hoặc Edge mà trẻ sử dụng trên máy con.

1. Mở `chrome://extensions` hoặc `edge://extensions`.
2. Bật **Chế độ dành cho nhà phát triển**, chọn **Tải tiện ích đã giải nén** (*Load unpacked*) và chọn thư mục `browser-extension` trong dự án.
3. Mở lại **Góc Của Con** từ Agent và đăng nhập PIN. Chờ dòng **Tiện ích MMT đang lọc web và đếm giờ trong hồ sơ trình duyệt này**. Sau khi khởi động lại trình duyệt, mở lại dashboard để kết nối phiên theo dõi.

Web thông thường và tên miền chưa phân loại được mở ngay. Trên dashboard phụ huynh, dùng **Quy tắc Web/App** để đặt riêng một tên miền:

| Quy tắc | Khi trẻ mở web |
| --- | --- |
| **Cho mở** | Mở được trong hạn mức đã lưu. Chọn **Không giới hạn** nếu không muốn giới hạn riêng trang đó. |
| **Cần xin phép** | Trang thông báo có nút **Xin phép**, điền sẵn tên miền vào yêu cầu. |
| **Chặn** | Tiện ích chặn tên miền và tên miền con theo quy tắc đã lưu. |
| **Hết giờ** | Tab đang sử dụng chuyển sang màn hình hết giờ và có nút **Xin thêm giờ**. |

Tiện ích đo thời gian khi tab được chọn và cửa sổ trình duyệt có tiêu điểm. Video đang phát có tiếng vẫn được tính trong tab hiển thị khi trẻ rời chuột và bàn phím. Báo cáo chỉ lưu tên miền và số giây. Trang chưa nhận diện được được xếp vào **Chưa phân loại**.

Tên miền 18+ thuộc bộ lọc bị chặn trước khi tải. Trang thông báo cho trẻ biết lý do và dashboard phụ huynh nhận cảnh báo có tên miền, hồ sơ và thời điểm. Các lần thử lại trên cùng tên miền trong vòng 5 phút được gộp. Tiện ích cần một phiên Góc Của Con đã đăng nhập để gửi cảnh báo. Bộ lọc áp dụng theo tên miền, nên nội dung 18+ bên trong một nền tảng thông thường có thể lọt qua.

Máy phụ huynh có thể đặt `MMT_ADULT_DOMAINS_FILE` trỏ tới một file UTF-8 với mỗi tên miền trên một dòng. Backend đọc lại file định kỳ và gửi danh sách bổ sung cho tiện ích. Có thể cập nhật file từ một nguồn đã kiểm duyệt mà không gửi lịch sử duyệt web ra ngoài MMT. File hỗ trợ tối đa 10.000 tên miền và dung lượng tối đa khoảng 1 MiB.

### 4. Đặt giờ giới nghiêm

Trong dashboard phụ huynh, mở **Giờ giới nghiêm**, nhập giờ bắt đầu, giờ kết thúc và múi giờ rồi bấm lưu. Ví dụ tại Việt Nam, chọn `Asia/Ho_Chi_Minh`. Nhập `00:55` cho 12 giờ 55 phút đêm. Khung `00:55–06:00` bắt đầu lúc 00:55 và kết thúc đúng lúc 06:00. Dashboard hiển thị giờ mà app dùng để kiểm tra.

Sau khi cập nhật từ phiên bản cũ, hãy lưu lại khung giờ một lần để ghi nhận múi giờ. Cấu hình cũ chưa có múi giờ sẽ tiếp tục dùng đồng hồ của máy chủ cho đến khi lưu.

## Cập nhật và khôi phục

- Khi cập nhật, tắt Backend và Agent rồi sao lưu `backend/app.db` trên máy phụ huynh. Trong thư mục dự án đang ở nhánh `version1`, chạy `git pull --ff-only origin version1` trên hai máy. Khởi động lại Backend và Agent, sau đó bấm **Tải lại** trên thẻ tiện ích Chrome/Edge.
- Nếu dùng bản clone mới và muốn giữ hồ sơ cũ, chép bản sao `backend/app.db` vào đúng đường dẫn ở bản clone mới trước lần chạy đầu tiên. Agent cũ chưa có thông tin xác thực của phiên bản này cần ghép lại qua **Hồ sơ trẻ → Đổi máy**.
- `GoChan_MayCon.bat` và `GoChan_MayCon.sh` dùng để khôi phục khi mục chặn MMT còn sót trong file `hosts` sau khi Agent đã tắt, chẳng hạn sau một lần tắt máy đột ngột. Agent tự dọn các mục này khi thoát bình thường. Việc chạy công cụ khôi phục chỉ tác động đến lớp chặn qua `hosts`.

## Phát triển và kiểm thử

Backend dùng FastAPI, Uvicorn, SQLAlchemy và SQLite. Hai dashboard dùng HTML, JavaScript, Tailwind CSS và Chart.js, với tài nguyên được phục vụ từ Backend. Agent dùng Python và WebSocket để đồng bộ, còn tiện ích trình duyệt nằm trong `browser-extension`.

Từ thư mục gốc, tạo môi trường ảo, cài phụ thuộc và chạy kiểm thử.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
python -m pytest -q
```

Trên Windows, có thể dùng `python -m venv .venv` rồi thay `python` trong hai lệnh cuối bằng `.venv\Scripts\python.exe`.

Để chạy Backend trực tiếp, có thể dùng `python -m backend.serve`. Lệnh hỏi mật khẩu nếu `MMT_PARENT_PASSWORD` chưa được đặt. Nếu gọi Uvicorn trực tiếp, đặt biến này trước khi chạy. Dùng HTTPS khi triển khai bên ngoài mạng LAN tin cậy để bảo vệ thông tin đăng nhập và ghép nối.

Khi thêm lớp Tailwind vào dashboard, dùng Tailwind CSS 3.4.19 để tạo lại `backend/app/assets/dashboard.css` từ HTML và JavaScript của hai dashboard, `backend/app/main.py` và `backend/app/services/classification.py`.

Chạy kiểm thử của tiện ích với Node.js 20 trở lên bằng lệnh `node --test browser-extension/tests/worker.test.cjs`.
