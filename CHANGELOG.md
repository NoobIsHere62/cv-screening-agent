# Nhật ký thay đổi

## 0.8.0
Rà soát toàn bộ cấu trúc, ổn định và tốc độ. Chi tiết: `docs/GIAI_THICH_THIET_KE.md` mục 3.19.

**Nhanh hơn (kết quả không đổi, đã đối chiếu 66 dòng)**
- Chấm CV 27 → 14 ms/CV; xuất Excel 600 dòng 3,2 → 2,0 s. Số luồng mặc định 4 → 2 (nhanh hơn và giao diện phản hồi tốt hơn).
- Danh sách kết quả hiện 100 thẻ mỗi lần (có nút "Hiện thêm").

**Ổn định**
- Tải lại trang giữa lúc đang sàng lọc: nối lại tiến độ thay vì mất theo dõi.
- Từ điển người dùng `lexicon_user.json` hỏng không còn làm sập chương trình.
- Máy chủ: token có chữ ngoài ASCII trả 403 (không phải 500); chặn thoát thư mục tĩnh bằng `is_relative_to`; đường dẫn có NUL trả 404; kết nối treo bị giải phóng sau 300 giây.
- In tiếng Việt ra console bảng mã cũ không còn gây `UnicodeEncodeError`.
- Báo ngay nếu thư mục lưu kết quả không ghi được (trước đây chỉ biết sau khi sàng lọc xong); dọn thư mục tải lên tạm của phiên bị tắt đột ngột; giữ tối đa 6 lần chạy trong bộ nhớ.
- PDF bị cắt cụt và file nhị phân đổi đuôi `.txt` báo lỗi rõ ràng thay vì CV rỗng.

**Dọn**
- Bỏ ký tự vô hình viết thẳng trong `textutil.py`; bỏ BOM ở file `.py`, `.yml`, CSV nhãn; file `.bat` dùng CRLF và kiểm tra Python/thư viện trước khi chạy.
- `.gitignore` thêm CV thật (`data/**/*.pdf`), `lexicon_user.json`, `*.egg-info`; `eval.py`/`calibrate.py` báo cách cài khi thiếu thư viện; bỏ hai lớp CSS không dùng.

## 0.7.0
Làm lại giao diện cho đơn giản và thêm một lượt tìm lỗi API. Chi tiết: `docs/GIAI_THICH_THIET_KE.md` mục 3.18.

**Đổi (giao diện)**
- Một cột, ba bước: dán JD → thêm CV → chọn mức chọn lọc. JD tự được đọc sau khi dán, không còn nút "Lọc JD".
- Kết quả có bốn tab (Phù hợp, Dự phòng, Loại, Tất cả), thẻ ứng viên gọn: tên, %, kết luận, lý do một câu, Mời / Giữ / Bỏ. Chi tiết mở ngay trong thẻ.
- "Tải Excel" là nút chính; phần còn lại (đổi mức chọn lọc, chấp nhận đề xuất, email, CSV, in báo cáo) gom vào "Thêm".
- Bỏ: sắp xếp, mật độ, chọn nhiều và so sánh, phím tắt, hộp hướng dẫn, dải ô màu, ô nhập ngưỡng tùy chỉnh, ô bật/tắt OCR, chỉnh JD đã lọc.

**Sửa**
- API: 15 lỗi 500 khi gửi sai kiểu dữ liệu (số / danh sách / đối tượng thay cho chữ) nay trả 400; chỉ số ứng viên âm không còn sửa nhầm ứng viên cuối; `PUT/PATCH` trả JSON.
- `run.py` không còn in traceback khi file đầu ra đang mở trong Excel.

**Dọn**
- Bỏ dữ liệu thừa trong `/api/bootstrap`, hàm `summary_counts` không dùng; chỉ giữ 10 tác vụ đã xong gần nhất trong bộ nhớ.

## 0.6.0
Tìm lỗi có hệ thống (fuzz, kiểm thử bất biến, đo ở quy mô 600 CV) rồi sửa; thêm phát hiện CV gần giống và tìm toàn văn. Chi tiết: `docs/GIAI_THICH_THIET_KE.md` mục 3.17.

**Sửa**
- Cùng nội dung viết khác kiểu (dấu tiếng Việt rời NFD, NBSP, xuống dòng `\r`) cho kết quả khác: nay chuẩn hoá ở mọi cửa vào (`textutil.clean_text`).
- JD: "Không yêu cầu kinh nghiệm, biết Python" không còn mất kỹ năng; "fresher" không làm mất cả yêu cầu; điều kiện bằng cấp đi kèm được giữ.
- TOEIC ghi theo kỹ năng (Listening + Reading) được cộng tổng; "TOEIC (2023): 800" đọc được; "TOEIC ≥ ." không còn gây lỗi.
- Ẩn danh: tên quá ngắn ("A") không còn xoá mọi chữ "a" trong CV.
- Sinh viên đang học không còn được coi là đã tốt nghiệp (cần HR xác nhận).
- Chữ dính liền (OCR/PDF mất khoảng trắng): tìm từ khoá bên trong; bằng cấp trong văn bản OCR nhận được "Universityof".
- Mỗi lần HR bấm Mời/Giữ/Bỏ không còn chờ ghi Excel (2,5 giây → 82 ms ở 600 CV); Excel đang mở không làm hỏng thao tác, HR được báo.
- Tải file: tên có ký tự cấm Windows, tên thiết bị (CON, NUL), tên quá dài; `Content-Length` âm; quét thư mục quá lớn (giới hạn 3.000 file, bỏ thư mục ẩn).
- PDF: đọc theo chỉ số trang, luôn đóng file; DOCX "zip bomb" bị từ chối.
- Excel: ký tự điều khiển và ô quá 32.767 ký tự không còn làm hỏng file.
- `CV_AGENT_AS_OF` sai định dạng dùng ngày hôm nay thay vì báo lỗi.

**Thêm**
- Phát hiện CV gần giống nhau (`cv_agent/dedupe.py`).
- Tìm toàn văn (cả nội dung CV) trong giao diện.

## 0.5.0
Chạy thử với CV PDF thật rồi sửa các lỗi lộ ra; thêm vài tính năng cho HR; dọn cấu trúc. Chi tiết và lý do: `docs/GIAI_THICH_THIET_KE.md` mục 3.16.

**Thêm**
- Nút **Mức chọn lọc**: đổi ngưỡng và xếp hạng lại ngay trên kết quả đã có, không đọc lại CV, giữ quyết định của HR (`report.rejudge`, `POST /api/runs/<id>/rejudge`).
- Nút **Dừng** khi đang sàng lọc (`POST /api/jobs/<id>/cancel`).
- **Báo cáo in được** (`GET /api/runs/<id>/report?scope=suitable|invited|all`) để lưu thành PDF.
- `pyproject.toml` (lệnh `cv-agent`, `cv-agent-web`), workflow CI (test + pyflakes), `CHANGELOG.md`.
- Từ điển: viết tắt (k8s, sklearn, js/ts, MS Excel, Postgres...) và công cụ AI/ML (LangChain, FAISS, spaCy, SageMaker, ONNX...).

**Sửa**
- PDF có chữ vẽ thành đường nét (Canva...) không còn bị đọc thành trống: đếm từ theo trang, chỉ OCR trang thiếu chữ.
- PDF: từ dính nhau (PyMuPDF làm chính), ký tự icon, link GitHub bị cắt (lấy từ chú thích link).
- CV quá ít chữ báo lỗi "cần xem thủ công" thay vì bị chấm 0 và loại.
- Tên ứng viên từ tên file CamelCase / gạch nối.
- JD nêu số năm hai lần chỉ còn một điều kiện; bảng đối chiếu không lặp số năm.
- Chứng chỉ TOEIC/IELTS tính là bằng chứng cho tiêu chí "giao tiếp tiếng Anh".
- CV đọc bằng OCR không bị loại vì điều kiện cứng (số OCR có thể sai): chuyển thành "chưa xác minh".
- Ghi `rows.json` / `meta.json` an toàn (file tạm + đổi tên).

**Đổi**
- Giao diện Streamlit cũ chuyển vào `legacy_streamlit/` (không còn phát triển, có test riêng).
- Dữ liệu mẫu dùng thư mục `samples/` (trước đây `data_ai/`).
- Test: 98 → xem `python -m unittest discover -s tests`.

## 0.4.0
Giao diện web mới (`webapp/`), mô hình quyết định theo mức đáp ứng yêu cầu bắt buộc, bảng đối chiếu yêu cầu, đọc tên ứng viên khi quét OCR.

## Trước đó
Xem `docs/GIAI_THICH_THIET_KE.md` mục 3.1–3.14.
