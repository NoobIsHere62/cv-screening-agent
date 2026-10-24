# CV Screening Agent

Sàng lọc CV theo JD của từng công ty (đa ngành), **chạy hoàn toàn bằng luật: không cần LLM, không cần internet, không gửi CV ra ngoài**.

Luồng: **JD → lọc JD (chỉ giữ điều kiện + kỹ năng cần thiết) → chấm từng CV → kết luận + lý do → xếp hạng → HR quyết định → Excel**.
Hệ thống chỉ gợi ý; mọi CV cần người xem đều được đánh dấu kèm lý do cụ thể.

## Chạy nhanh
```bash
pip install -r requirements.txt
python serve.py                # mở giao diện web tại http://localhost:8765  (Windows: bấm đúp start_app.bat)
```
Giao diện chỉ dùng thư viện chuẩn của Python (không cần Node, không cần Streamlit), một cột, ba bước:
1. **Dán JD** (hoặc tải file). Hệ thống tự đọc và cho biết hiểu được bao nhiêu điều kiện / kỹ năng; bấm "Xem hệ thống hiểu những gì" nếu muốn kiểm tra.
2. **Thêm CV**: kéo thả file hoặc cả thư mục (hoặc nhập đường dẫn thư mục trên máy).
3. **Chọn mức chọn lọc** (Nghiêm ngặt / Cân bằng / Rộng rãi) rồi **Bắt đầu sàng lọc**. Nút *Dùng dữ liệu mẫu* thử ngay không cần chuẩn bị gì.

Kết quả có bốn tab: **Phù hợp**, **Dự phòng**, **Loại**, **Tất cả** (thêm tab "Không đọc được" nếu có CV lỗi). Mỗi ứng viên là một thẻ:
- % đáp ứng yêu cầu bắt buộc, kết luận, **đề xuất** và **lý do** bằng một câu, số điểm cần xem lại; ba nút **Mời / Giữ / Bỏ** ngay trên thẻ (tự lưu, có trong Excel).
- **Chi tiết** mở ngay trong thẻ: đối chiếu từng điều kiện / kỹ năng của JD (✓ đạt, ! yếu, ✗ thiếu, ? chưa rõ) kèm bằng chứng trích từ CV, việc cần xem lại,
  ghi chú của bạn, và văn bản máy đọc được từ CV (để kiểm tra khi là bản OCR).
- Ô tìm kiếm toàn văn (tên, email, kỹ năng và cả nội dung CV; nhiều từ thì CV phải chứa tất cả; không phân biệt dấu) và "Chỉ CV cần xem lại".
- **Tải Excel** là nút chính. Nút **Thêm** gom phần còn lại: đổi mức chọn lọc (tính lại ngay, không đọc lại CV, giữ quyết định của bạn), chấp nhận đề xuất cho các CV đang xem,
  sao chép email người được mời, tải CSV, in báo cáo (lưu thành PDF). **Các lần đã lưu** ở góc trên để mở lại kết quả cũ. Có nút **Dừng** khi đang sàng lọc.

Dòng lệnh:
```bash
python run.py rubric jd.txt -o rubrics/jd.json                          # ghi thêm rubrics/jd.core.txt (JD đã lọc)
python run.py score rubrics/jd.json cvs/ -o ranking.csv --excel kq.xlsx  # thư mục, file hoặc mẫu glob
python run.py score rubrics/jd.json cvs/ --fit 75 --maybe 55 --reject 35 --recursive
```
Cài như một gói (tùy chọn): `pip install -e .` rồi dùng lệnh `cv-agent` (dòng lệnh) và `cv-agent-web` (giao diện); thêm `.[ocr]` để cài OCR.
Giao diện Streamlit cũ nằm ở `legacy_streamlit/` (không còn phát triển; xem `legacy_streamlit/app.py` để biết cách chạy).

## Cách hệ thống quyết định (`cv_agent/verdict.py`, `aggregate.py`)
Quyết định dựa trên **mức đáp ứng yêu cầu bắt buộc** (% tính theo trọng số các kỹ năng bắt buộc), không phải tổng điểm: kỹ năng *ưu tiên*
chỉ là điểm cộng để **xếp hạng**, không làm ai đủ hay thiếu điều kiện.

| Kết luận | Điều kiện (mặc định) | Đề xuất |
|---|---|---|
| **Loại** | trượt điều kiện bắt buộc đã xác minh được, hoặc đáp ứng < 30% yêu cầu bắt buộc | Không mời |
| **Dự phòng - Cân nhắc** | đáp ứng 30–49%, hoặc có bằng chứng cho < 60% kỹ năng bắt buộc (khi JD có ≥ 3 kỹ năng bắt buộc) | Giữ dự phòng |
| **Có thể mời phỏng vấn** | đáp ứng ≥ 50%; hoặc ≥ 70% nhưng còn điều kiện chưa xác minh được / kỹ năng bắt buộc chưa thấy bằng chứng | Cân nhắc mời |
| **Phù hợp - Mời phỏng vấn** | đáp ứng ≥ 70%, đạt đủ điều kiện cứng, không còn điểm chưa rõ | Mời phỏng vấn |

Giao diện có ba mức dựng sẵn: Nghiêm ngặt 80/60/40 · Cân bằng 70/50/30 · Rộng rãi 60/40/20 (phù hợp / có thể mời / loại). Muốn ngưỡng khác: `--fit --maybe --reject`
ở dòng lệnh, hoặc sửa `cv_agent/config.py`.
Xếp hạng: theo nhóm kết luận, trong nhóm theo điểm tổng (gồm điểm cộng). Điều kiện *không xác minh được* (ví dụ CV không ghi chứng chỉ) không bị loại: CV vào nhóm "cần xem lại".

## Đọc CV
- **Tên ứng viên** đọc được dù phía trên có "CURRICULUM VITAE", chức danh, slogan; chịu được OCR dính chữ / mất dấu ("NGUYENHOANGNAM" → Nguyen Hoang Nam);
  không chắc thì lấy từ tên file / email và đánh dấu để HR xác nhận (`cv_agent/identity.py`).
- **PDF**: đọc bằng PyMuPDF (đúng khoảng trắng và thứ tự khối chữ), tự chuyển sang pdfplumber + tách cột khi cần; hai cột được đọc hết cột trái rồi cột phải;
  bỏ ký tự icon của mẫu CV; lấy địa chỉ thật của link (GitHub, email) từ chú thích link. DOCX đọc cả bảng, đầu/chân trang, hộp văn bản.
- **Chữ nằm trong ảnh / vẽ thành đường nét** (CV scan, CV xuất từ Canva): đếm từ theo từng trang, **chỉ OCR trang thiếu chữ** rồi ghép với chữ đọc được, trên máy:
  Tesseract (cài chương trình + gói tiếng Việt + `pip install pytesseract`) → hoặc RapidOCR (`pip install rapidocr-onnxruntime`, mất dấu tiếng Việt, ~14 giây/trang).
  CV có chữ nhờ OCR luôn bị gắn cờ cần xem lại và **không bao giờ bị loại chỉ vì điều kiện cứng** (số OCR có thể sai): thành "chưa xác minh". Xem `requirements-ocr.txt`.
- CV đọc ra quá ít chữ (file ảnh, nộp nhầm) báo lỗi "cần xem thủ công", không bị chấm 0 rồi loại.
- **Cùng nội dung thì cùng kết quả**: mọi văn bản được chuẩn hoá trước khi phân tích (dấu tiếng Việt viết rời, khoảng trắng NBSP, xuống dòng kiểu Mac/Windows, ký tự vô hình).
- **CV gần giống nhau** (cùng người nộp hai bản, sửa vài dòng) được gắn cờ ở bản đứng sau, kèm độ giống và tên CV gốc.
- **Sinh viên đang học** (ngày kết thúc ở tương lai, "Present", "năm cuối") không được coi là đã tốt nghiệp khi JD đòi "Tốt nghiệp đại học": vào nhóm "Có thể mời" kèm ghi chú cần xác nhận.
- Bước chấm chỉ nhìn văn bản đã **ẩn danh** (tên, tuổi, giới tính, quê quán, link...). Tên/email/SĐT lấy từ CV gốc chỉ để hiển thị cho HR.

## Cấu trúc
```
serve.py                 mở giao diện web          run.py   dòng lệnh          eval.py, calibrate.py   đo độ chính xác
webapp/                  server.py (HTTP chuẩn, chỉ 127.0.0.1, có mã truy cập), service.py (nghiệp vụ), multipart.py, printable.py (báo cáo in được), static/ (index.html, style.css, app.js)
legacy_streamlit/        giao diện Streamlit cũ (không còn phát triển, có test riêng)
pyproject.toml, .github/workflows/tests.yml, CHANGELOG.md   đóng gói, CI (test + pyflakes), nhật ký thay đổi
cv_agent/
  config.py              MỌI hằng số chỉnh được (ngưỡng, hệ số, giới hạn file, cờ LLM)
  pipeline.py            đọc → chấm → báo cáo → xếp hạng; song song, chống trùng CV, một CV lỗi không hỏng cả lô
  io_utils.py            đọc txt/pdf/docx, bảng mã, PDF hai cột, OCR      identity.py   tìm tên ứng viên      facts.py   liên hệ, GPA, ngoại ngữ...
  jd_rules.py            JD → rubric (điều kiện cứng + tiêu chí)           jd_filter.py  in lại JD đã lọc cho HR
  cv_parse.py, lang_check.py, baseline.py, nlp.py, lexicon.py              chấm bằng độ phủ từ khoá + từ điển (mở rộng bằng lexicon_user.json)
  aggregate.py           điểm tổng + mức đáp ứng bắt buộc + kết luận 3 mức   verdict.py   kết luận 4 mức
  report.py              dòng báo cáo, bảng đối chiếu yêu cầu, Excel/CSV, rejudge (đổi ngưỡng không chấm lại)    storage.py   lưu (ghi an toàn) / mở lại các lần chạy, quyết định HR
  textutil.py            clean_text: chuẩn hoá văn bản đầu vào       dedupe.py   phát hiện CV gần giống nhau (MinHash)
  anonymize.py           ẩn thông tin cá nhân
  scoring.py, llm.py, prompts.py, rubric.py   engine LLM TÙY CHỌN (tắt mặc định: CV_AGENT_ENABLE_LLM=1)
tests/                   169 test:  python -m unittest discover -s tests   (hoặc run_tests.bat)
docs/                    GIAI_THICH_THIET_KE.md: giải thích từng phần và lý do sửa
samples/, data_heldout/  dữ liệu mẫu có nhãn (tự viết)
```

## Đo độ chính xác
```bash
pip install -r requirements-eval.txt
python eval.py --data data_heldout       # 12 CV, 3 JD
python eval.py --data samples            # 9 CV kỹ sư AI
python calibrate.py samples data_heldout # kiểm tra ngưỡng bằng đánh giá chéo theo JD
```
Kết quả hiện tại (engine luật): `data_heldout` đúng **83%** ở 3 mức, `samples` **67%**; 100% người "Phù hợp" nằm trong danh sách phù hợp, không người
"Không phù hợp" nào lọt vào danh sách. **Đây là dữ liệu tự viết** và `data_heldout` đã được dùng để tìm lỗi nên không còn hoàn toàn độc lập:
hãy đo lại bằng CV và JD thật trước khi tin các con số.

## Giới hạn
- Khớp từ khoá + từ điển viết tay: không hiểu "tương đương" ngoài từ điển (đã có AI/ML, kế toán, marketing, bán hàng, song ngữ Việt–Anh); bổ sung bằng `lexicon_user.json`.
- Các ngưỡng, quy tắc 60% kỹ năng cốt lõi và bảng quy đổi IELTS/TOEFL → TOEIC là điểm khởi đầu hợp lý, **chưa hiệu chỉnh bằng CV thật**.
- OCR: Tesseract chưa thử trên máy này; RapidOCR đã thử trên PDF thật nhưng chậm và mất dấu tiếng Việt. Chữ toàn chữ thường bị dính ("softwareengineering")
  chỉ được tìm *từ khoá của JD bên trong* chữ dính chứ chưa tách thành từng từ. PDF nhiều cột phức tạp, bảng, font lỗi có thể đọc sai thứ tự.
- Workflow CI (`.github/workflows/tests.yml`) chưa được chạy thật trên GitHub; test và pyflakes chạy được cục bộ.
- Giao diện dành cho một người dùng trên máy cục bộ (chỉ lắng nghe 127.0.0.1); chưa có đăng nhập. CV chứa dữ liệu cá nhân: cần tuân thủ quy định bảo vệ dữ liệu cá nhân.
- `CV_AGENT_AS_OF=YYYY-MM` cố định mốc "nay" để kết quả tái lập được; `CV_AGENT_OUTPUT_DIR` đổi thư mục lưu kết quả.

## Dữ liệu và quyền riêng tư
- Kho mã **chỉ chứa dữ liệu mẫu tự tạo** (`samples/`, `data/`, `data_ai/`, `data_heldout/`): tên, email, số điện thoại đều là giả (`@example.com`, `0900 000 xxx`).
- **Không commit CV thật.** `.gitignore` đã chặn `*.pdf`/`*.docx` trong `data/`, thư mục `outputs/` (kết quả sàng lọc), `.env` và `lexicon_user.json`.
- Mặc định mọi thứ chạy cục bộ, không gửi dữ liệu ra ngoài. Engine LLM là tùy chọn; nếu bật, đặt khóa qua biến môi trường (xem `.env.example`), không ghi khóa vào mã.
- Dùng với CV thật cần tuân thủ quy định bảo vệ dữ liệu cá nhân (xem phần Giới hạn).

## Giấy phép
MIT, xem `LICENSE`.
