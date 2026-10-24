# Giải thích thiết kế và lý do từng thay đổi

Tài liệu này để người đọc nắm được: hệ thống chạy thế nào, **mỗi phần làm gì, đã sửa gì, vì sao sửa**, và cách tự kiểm chứng.
Mỗi mục theo cùng một khung: **Làm gì → Đã sửa/thêm gì → Vì sao → Cách kiểm tra.**

Chú thích nguồn gốc để khỏi nhầm khi trả lời phỏng vấn:
- **[Gốc]** là phần có sẵn trong dự án trước khi các thay đổi dưới đây được thêm.
- **[Thêm]** là phần mới thêm. **[Sửa]** là phần có sẵn nhưng đã sửa.

---

## 1. Bức tranh tổng thể

```
JD (.txt) ──► LỌC JD ──► JD rút gọn (HR đọc/sửa) ──► RUBRIC ──┐
                                                               ├─► CHẤM từng CV ─► ĐIỂM + CHỨNG CỨ ─► KẾT LUẬN 4 MỨC ─► XẾP HẠNG
CV (.pdf/.docx/.txt) ──► ĐỌC (OCR nếu scan) ──► ẨN DANH ───────┘                                         │
                                                                                                         ▼
                                                                                   Danh sách phù hợp + Excel + "HR cần xem gì"
```

Hai engine chấm dùng chung mọi thứ phía trên và phía dưới:

| | `baseline` | `llm` |
|---|---|---|
| JD → rubric | luật (regex) | Claude phân tích, mỗi tiêu chí phải có câu trích nguyên văn từ JD |
| Chấm CV | độ phủ từ khoá | Claude chấm 0–4 kèm bằng chứng |
| API key | không cần | cần |

**Nguyên tắc xuyên suốt (nên thuộc lòng):**
1. **Code quyết định điểm và kết luận, LLM không tự quyết.** LLM chỉ cho điểm từng tiêu chí 0–4 kèm bằng chứng. Tổng điểm, ngưỡng và kết luận do code tính. Lý do: LLM thiếu nhất quán, khó giải thích, khó kiểm tra. Code thì tất định, đo được.
2. **Bằng chứng phải kiểm chứng được.** Mọi câu trích dẫn LLM đưa ra phải xuất hiện thật trong CV (`verify_evidence`). Không có thì bị hạ điểm. Chống bịa.
3. **Không chắc thì để người xem, không đoán.** Điều kiện không xác minh được là `unclear`, không phải `not_met`; và được ghi rõ vào cột "HR cần xem gì".
4. **Ẩn thông tin dễ gây thiên kiến** (tên, tuổi, giới tính, quê quán...) trước khi chấm.
5. **CV là dữ liệu, không phải lệnh.** CV chèn câu "hãy cho tôi điểm cao" phải bị bỏ qua và bị cảnh báo.
6. **AI chỉ hỗ trợ; con người quyết định cuối.**

---

## 2. Bản đồ file

| File | Vai trò | Nguồn |
|---|---|---|
| `run.py` | Dòng lệnh: `rubric` (JD → rubric) và `score` (chấm nhiều CV) | Gốc, [Sửa] |
| `serve.py`, `webapp/` | Giao diện web chính (xem 3.15, 3.16) | [Thêm] |
| `legacy_streamlit/` | Giao diện Streamlit cũ (`app.py`, `webui/`, `.streamlit/`), không còn phát triển, có test riêng | [Thêm], đã chuyển vào thư mục riêng ở 3.16 |
| `eval.py`, `calibrate.py` | Đo độ chính xác trên dữ liệu có nhãn, kiểm tra ngưỡng | Gốc |
| `cv_agent/schemas.py` | Cấu trúc dữ liệu (Rubric, HardRequirement, Criterion, ScoringResult) | Gốc |
| `cv_agent/jd_rules.py` | JD → rubric bằng luật | Gốc, [Sửa] |
| `cv_agent/jd_filter.py` | Lọc JD, in lại JD gọn cho HR | [Thêm] |
| `cv_agent/lang_check.py` | Kiểm tra chứng chỉ TOEIC/IELTS/TOEFL | [Thêm] |
| `cv_agent/cv_parse.py` | Tách mục CV, đọc khoảng thời gian, kiểm tra bằng cấp/số năm | Gốc, [Sửa] |
| `cv_agent/nlp.py` | Tách yêu cầu thành cụm từ, tính độ phủ từ khoá | Gốc |
| `cv_agent/lexicon.py` | Từ điển viết tay (từ đồng nghĩa, nhóm ngành) | Gốc, [Sửa] |
| `cv_agent/baseline.py` | Engine chấm bằng luật | Gốc, [Sửa] |
| `cv_agent/scoring.py` | Engine LLM + `aggregate` (tính điểm/kết luận 3 mức) | Gốc, [Sửa] |
| `cv_agent/config.py` | Mọi hằng số chỉnh được (ngưỡng, hệ số, giới hạn file, cờ LLM) | [Thêm] |
| `cv_agent/aggregate.py` | Điểm tổng + kết luận 3 mức, tách khỏi engine LLM | [Thêm] (tách từ scoring.py) |
| `cv_agent/pipeline.py` | Luồng đọc → chấm → báo cáo → xếp hạng dùng chung cho CLI và giao diện | [Thêm] |
| `cv_agent/storage.py` | Lưu / mở lại các lần chạy, quyết định của HR | [Thêm] |
| `cv_agent/identity.py` | Tìm tên ứng viên (kể cả CV OCR, có chữ khác phía trên) | [Thêm] |
| `cv_agent/textutil.py` | `clean_text`: đưa văn bản về dạng chuẩn (NFC, NBSP, `\r`, ký tự điều khiển) để cùng nội dung cho cùng kết quả | [Thêm] (3.17) |
| `cv_agent/dedupe.py` | Phát hiện CV gần giống nhau (MinHash đáy-k + Jaccard) | [Thêm] (3.17) |
| `webapp/` (`server.py`, `service.py`, `multipart.py`, `printable.py`, `static/`) | Giao diện web: máy chủ HTTP chuẩn + trang HTML/CSS/JS, không cần Streamlit; `printable.py` dựng báo cáo in được | [Thêm] |
| `serve.py`, `start_app.bat` | Mở giao diện web | [Thêm] |
| `pyproject.toml`, `.github/workflows/tests.yml`, `CHANGELOG.md` | Đóng gói (`pip install -e .`), chạy test + pyflakes tự động, nhật ký thay đổi | [Thêm] (3.16) |
| `cv_agent/facts.py` | Tên, email, SĐT, GPA, ngoại ngữ, GitHub, số năm (chỉ để hiển thị) | [Thêm] |
| `cv_agent/verdict.py` | Kết luận 4 mức | [Thêm] |
| `cv_agent/report.py` | Gom kết quả thành dòng báo cáo, xuất Excel, lý do cần xem | [Thêm] |
| `cv_agent/io_utils.py` | Đọc txt/pdf/docx, OCR | Gốc, [Sửa] |
| `cv_agent/anonymize.py` | Ẩn thông tin cá nhân | Gốc |
| `cv_agent/llm.py`, `prompts.py`, `rubric.py` | Gọi Claude, prompt, dựng rubric bằng LLM | Gốc, [Sửa] nhỏ |
| `tests/` (`test_core`, `test_pipeline`, `test_realworld`, `test_webapp`, `test_storage`) | 119 test tự động | [Thêm] |
| `samples/`, `data_heldout/` | Dữ liệu mẫu có nhãn (JD kỹ sư AI + 9 CV txt/pdf; 3 JD khác) | xem mục 5 |

---

## 3. Từng phần: làm gì, sửa gì, vì sao

### 3.1 Đọc CV và OCR — `io_utils.py`
- **Làm gì:** đọc `.txt/.md/.pdf/.docx` thành văn bản.
- **Đã thêm:** PDF ít chữ (dưới 100 ký tự) hoặc font lỗi (`(cid:` xuất hiện nhiều) được coi là bản scan → OCR. Thứ tự: thử Tesseract trên máy (miễn phí, cần cài) → không có thì Claude vision (cần key) → không có cả hai thì báo lỗi kèm hướng dẫn. Giới hạn 5 trang đầu.
- **Vì sao:**
  - Trước đây PDF scan chỉ báo lỗi, HR phải đọc tay, trái mục tiêu tiết kiệm thời gian.
  - Chọn Tesseract trước vì không tốn tiền và CV không phải gửi ra ngoài. Claude vision chỉ là phương án dự phòng, dễ cài hơn nhưng gửi ảnh CV ra dịch vụ ngoài.
  - Ngưỡng 100 ký tự để PDF "có lớp chữ nhưng chỉ vài ký tự rác" cũng bị bắt.
  - Dùng `pymupdf` (không cần cài poppler như `pdf2image`), vốn dễ cài trên Windows.
- **Kiểm tra:** `tests/test_core.py::OcrRoutingTests` tạo PDF chỉ có ảnh rồi giả lập Tesseract để xác nhận luồng rẽ nhánh đúng. **Chưa thử trên PDF scan thật** (máy chưa cài Tesseract).

### 3.2 Lọc JD — `jd_rules.py` + `jd_filter.py`
- **Làm gì:** biến JD thành rubric (điều kiện cứng + tiêu chí có trọng số).
- **Vì sao phải lọc:** JD chứa nhiều thứ không dùng để chấm CV: mô tả công việc, quyền lợi, văn hoá, kỹ năng mềm khó kiểm chứng, yêu cầu về tuổi/giới tính. Nếu đưa hết vào chấm sẽ nhiễu và có thể phân biệt đối xử. Yêu cầu của người dùng cũng nói rõ: "chỉ lấy kỹ năng cần thiết".
- **Lỗi nghiêm trọng đã sửa (quan trọng nhất của đợt này):**
  - **Triệu chứng:** với JD kỹ sư AI, cả 9 CV đều điểm cực thấp (cao nhất 41,7; 8/9 bị loại), kể cả CV rất mạnh.
  - **Nguyên nhân:** JD có mục `Required skills/Experience:` nhưng danh sách tiêu đề mục chỉ có `requirements`, `qualifications`... nên mục này **không được nhận ra và bị bỏ hoàn toàn**. Hệ thống chỉ chấm các mục "Nice to have". Ngoài ra dòng `Years of experiences: >2 YoE` nằm dưới "Nice to have" nên bị coi là tiêu chí ưu tiên, và không có mẫu nào hiểu `>2 YoE`.
  - **Cách sửa:** thêm các tiêu đề `required`, `required skills`, `key requirements`...; nhận `YoE`, `>2 năm`; dòng nhãn "Years of experience" luôn là yêu cầu chung dù nằm dưới mục nào; `Years of experiences: No` nghĩa là không yêu cầu; dòng đầu là tiêu đề mục (không phải tên vị trí) thì không lấy làm tên vị trí.
  - **Kết quả:** JD đó từ 6 tiêu chí toàn "ưu tiên", 0 điều kiện cứng → 12 tiêu chí, 3 điều kiện cứng (bằng cấp, chứng chỉ ngoại ngữ, số năm).
- **Đã thêm:** ghi chú những gì đã lọc bỏ (kỹ năng mềm, yêu cầu phân biệt đối xử) vào `ambiguities`, để HR kiểm tra không bỏ sót yêu cầu quan trọng. Trước đây kỹ năng mềm bị bỏ âm thầm.
- **`jd_filter.py`:** in rubric ra lại thành "JD chuẩn" (`Yêu cầu:` / `Ưu tiên:`) để HR đọc và sửa. Thiết kế sao cho **đọc lại JD chuẩn thì ra đúng rubric cũ** (đã có test vòng tròn). Nhờ vậy HR sửa tay được mà không cần động đến code.
- **Kiểm tra:** `JdFilterTests` (5 test).

### 3.3 Chứng chỉ ngoại ngữ — `lang_check.py`
- **Làm gì:** đọc yêu cầu như "TOEIC ≥650 hoặc tương đương", tìm chứng chỉ trong CV, so sánh.
- **Vì sao:** trước đó TOEIC/IELTS bị chấm như từ khoá thường, hoặc điều kiện kiểu `language` luôn ở trạng thái "baseline chưa kiểm tra" khiến mọi CV bị gắn `unclear` và không bao giờ đạt "Phù hợp".
- **Quyết định thiết kế:**
  - Quy mọi chứng chỉ về thang TOEIC bằng bảng quy đổi. **Bảng này là ước lượng của người viết**, không phải số chính thức; ghi rõ trong ghi chú kết quả.
  - **Không thấy chứng chỉ → `unclear`, không phải `not_met`.** Ứng viên có thể có mà không ghi; loại họ vì thế là bất công. Họ vào danh sách "cần xem".
  - Chỉ nhận số hợp lệ (TOEIC 3 chữ số, IELTS 4.0–9.0) để "TOEIC (2024)" không bị đọc 2024 thành điểm. Có test riêng cho trường hợp này.
- **Kiểm tra:** `LanguageTests`.

### 3.4 Đọc CV bằng luật — `cv_parse.py`
- **Đã sửa 1 — số năm "chung chung":** dòng `Years of experiences: >2 YoE` không nói lĩnh vực nào. Cách cũ đòi khối kinh nghiệm phải khớp "chủ đề" của dòng này nên không khối nào khớp → 0 năm → trượt điều kiện cứng oan. Nay: nếu sau khi bỏ cụm số năm không còn từ nào mang nghĩa, tính **tổng kinh nghiệm**, và ghi chú "tính tổng vì JD không nêu lĩnh vực". Việc đúng lĩnh vực do các tiêu chí kỹ năng lo.
- **Đã sửa 2 — lỗi ngày tháng (phát hiện khi đánh giá lại code):**
  - **Triệu chứng:** "Marketing 2016 - 2020" trong mục học vấn bị biến thành "03/2016 - 2020", ngành học không khớp nên bị báo `unclear`.
  - **Nguyên nhân:** biểu thức nhận tên tháng viết là `(jan|feb|mar|...)[a-z]*`, tức **mọi từ bắt đầu bằng "mar"** đều được coi là tháng Ba. Tương tự "Junior 2021" → 06/2021, "Decision 2020" → 12/2020.
  - **Cách sửa:** chỉ nhận tên tháng đầy đủ hoặc viết tắt chuẩn (`jan`, `january`, `sept`...), có ranh giới từ.
  - **Vì sao quan trọng:** lỗi này làm sai số năm kinh nghiệm và sai ngành học trên CV thật, rất khó thấy bằng mắt. Có test hồi quy.
  - Trước khi tìm ra nguyên nhân gốc, các CV mẫu từng được viết với khoảng thời gian đặt trong ngoặc để né lỗi; sau khi sửa gốc thì cách viết nào cũng đúng.

### 3.5 Từ điển — `lexicon.py`
- **Làm gì:** nếu dòng CV có cụm bên trái thì coi như có các từ bên phải (ví dụ `docker` → `triển khai`).
- **Đã thêm:** nhóm AI/ML: `git → version control`, `pytorch/keras → deep learning`, `mlflow/airflow → mlops`, `spark → distributed systems`, `matplotlib → data visualization`...
- **Vì sao:** JD viết "Experience with version control (Git)", CV viết "Git". Máy so từ khoá không biết hai cái đó cùng nghĩa → CV có Git vẫn điểm 0 ở tiêu chí này. Đây là giới hạn đã biết của cách khớp từ khoá, vá bằng từ điển.
- **Lỗi đã sửa:** khi thêm mục mới, một số khoá bị khai báo hai lần trong cùng dict (Python lặng lẽ lấy giá trị sau). `pyflakes` phát hiện; đã gộp.
- **Đánh đổi cần biết:** từ điển viết tay → chỉ tốt cho ngành đã có. Muốn hiểu "tương đương" tổng quát thì phải dùng engine LLM. Có thể bổ sung không cần sửa code qua `lexicon_user.json`.

### 3.6 Engine baseline — `baseline.py`
- **Đã sửa:** xử lý điều kiện loại `language` (gọi `check_language`); kiểm tra chứng chỉ trên văn bản **chưa đổi định dạng ngày** (nếu đã chuẩn hoá, "01/2026" thành thứ khác và có thể gây nhầm).

### 3.7 Tính điểm — `scoring.py`
- **[Gốc] `aggregate`:** điểm = tổng (trọng số × điểm/4). Kết luận 3 mức: trượt điều kiện cứng → Không phù hợp; đủ điểm nhưng có điều kiện chưa rõ/thiếu tiêu chí bắt buộc → hạ xuống Cân nhắc. **Giữ nguyên** để `eval.py` và `calibrate.py` còn đo được trên cùng thước.
- **Đã thêm `core_ratio`:** tỉ lệ kỹ năng bắt buộc (không tính tiêu chí số năm) đạt từ 2/4 trở lên.
  - **Vì sao:** một CV backend Java có 4 năm kinh nghiệm, TOEIC đạt, có Git và Docker vẫn đạt điểm tổng ~52 dù **gần như không có gì về deep learning/ML**, vì các tiêu chí chung (số năm, API, Git) kéo điểm lên. Tổng có trọng số che mất việc thiếu kỹ năng cốt lõi.
  - Nên đặt ngưỡng: dưới 60% kỹ năng cốt lõi thì tối đa "Dự phòng" (xem `verdict.py`).
- **Đã thêm:** loại thẻ `</cv>`, `<rubric>` khỏi nội dung CV trước khi đưa vào prompt.
  - **Vì sao:** prompt bao CV trong thẻ `<cv>...</cv>`. CV tự viết `</cv>` rồi tiếp lệnh sẽ thoát ra khỏi vùng dữ liệu (prompt injection). Làm tương tự cho `<jd>` trong `rubric.py`.

### 3.8 Kết luận 4 mức — `verdict.py`
- **Quy tắc theo thứ tự:** trượt điều kiện cứng hoặc điểm < 30 → **Loại**; kỹ năng cốt lõi < 60% → tối đa **Dự phòng**; `aggregate` đã nói "Phù hợp" → **Phù hợp - Mời phỏng vấn**; điểm ≥ 50 → **Có thể mời phỏng vấn**; còn lại → **Dự phòng - Cân nhắc**.
- **Vì sao tách file riêng, không sửa `aggregate`:** `eval.py` và `calibrate.py` so với nhãn 3 mức của HR. Đổi `aggregate` sẽ làm mọi số đo cũ mất ý nghĩa. Thêm một lớp phía trên là cách đổi ít rủi ro nhất.
- **Vì sao 4 mức:** theo yêu cầu "dưới 30 điểm thì loại" và cần mức giữa để HR ưu tiên ai xem trước.
- **Cần biết:** ngưỡng 30 và 60% **chưa được hiệu chỉnh bằng dữ liệu thật**; chúng là điểm khởi đầu hợp lý, không phải kết quả đo.
- **Danh sách phù hợp** = hai mức đầu, xếp theo điểm.

### 3.9 Báo cáo và "HR cần xem gì" — `report.py`
- **Đã sửa:** cột "cần người xem lại" trước đây chỉ có dấu `x`, HR không biết xem cái gì. Nay có hai cột: "Cần người xem lại?" (CÓ/Không, tô màu) và "HR cần xem gì" (danh sách đánh số lý do cụ thể: điều kiện nào chưa xác minh, tiêu chí nào chưa chấm, bằng chứng nào không khớp, cảnh báo nào).
- **Vì sao:** một cờ không giải thích gì thì HR phải mở CV đọc lại từ đầu — mất đúng thời gian mà công cụ cần tiết kiệm.
- Excel có hai sheet: "Danh sách phù hợp" và "Tất cả CV". Lỗi đọc CV cũng được đánh dấu CÓ kèm lý do lỗi.

### 3.10 Giao diện — `app.py`
- **Luồng:** tải/dán JD → "Lọc JD" → xem/sửa JD đã lọc → kéo thả CV hoặc nhập thư mục → chạy → danh sách phù hợp, bảng đầy đủ, chi tiết từng ứng viên → tải Excel.
- **Quyết định đáng nhớ:**
  - Cho HR sửa JD đã lọc: máy lọc có thể sai, người xem mới yên tâm.
  - **Phát hiện JD đổi sau khi lọc** và dùng JD mới thay vì lặng lẽ dùng bản lọc cũ (lỗi tìm thấy khi đánh giá lại).
  - Mỗi CV kéo thả được ghi vào thư mục tạm riêng để hai CV trùng tên không ghi đè nhau.
  - Một CV lỗi không làm hỏng cả lô.
- **Hạn chế:** nhập đường dẫn thư mục chỉ chạy khi app và thư mục ở cùng máy; kết quả mất khi tải lại trang; API key đặt vào biến môi trường của cả tiến trình nên **không an toàn nếu nhiều người dùng chung một server**.

### 3.11 Dữ liệu mẫu và kiểm thử
- **`tests/` (hiện nay 169 test, xem 3.16-3.19):** dùng để biết chắc sửa chỗ này không làm hỏng chỗ khác. Chạy: `python -m unittest discover -s tests`. Không cần API key.
- **Đo hồi quy:** `python eval.py --engine baseline --data data_heldout` phải giữ Spearman 0,93 (đã kiểm tra: không đổi sau mọi thay đổi).
- **`data_ai/` (nay là `samples/`):** 9 CV ảo (txt + pdf) quanh JD kỹ sư AI, có người mạnh, vừa, yếu, sai ngành, và một CV chèn lệnh. Nhãn do người viết gán, **chủ quan**.
- **`data/` (cập nhật):** nay là tài liệu của chính người dùng: JD `jd01`, `jd02`, các CV `jd0X_cvY.txt` và vài CV PDF thật. Không có `labels.csv` nên `eval.py --data data` không chạy được; dữ liệu đo là `samples/` và `data_heldout/`. Các CV thật trong `data/cvs/` chỉ dùng để thử bằng tay, không đưa nội dung vào tài liệu.

### 3.12 Rà soát từ góc nhìn nhà tuyển dụng fresher AI (không dùng LLM)
Cách làm: viết một JD "Fresher AI Engineer" (không yêu cầu kinh nghiệm, ưu tiên dự án/thực tập) rồi chấm **CV PDF thật của một sinh viên AI** bằng engine baseline. Kết quả ban đầu: **46,1 điểm, "Dự phòng"**, trong khi một nhà tuyển dụng đọc sẽ thấy đây là hồ sơ tốt (2 dự án RAG/thị giác máy tính, 6 tháng thực tập, TOEIC 790). Truy từng điều kiện ra 4 lỗi:

1. **Ngành "Artificial Intelligence" không khớp "Trí tuệ nhân tạo".** Nhóm ngành tương đương chỉ có Khoa học máy tính, Công nghệ thông tin... chứ không có AI, nên điều kiện bằng cấp ở trạng thái "chưa rõ" và chặn kết luận "Phù hợp". **Sửa:** thêm AI/ML/Data Science (cả tiếng Việt lẫn Anh) vào nhóm ngành.
2. **Mất tín hiệu GitHub.** Bộ ẩn danh thay mọi đường link bằng `[LINK]`, nên "github.com/..." trong CV biến mất và tiêu chí "Biết sử dụng Git" được 0 điểm. Trong tuyển fresher, GitHub là bằng chứng nghề nghiệp quan trọng; thứ cần ẩn là tên tài khoản chứ không phải loại link. **Sửa:** ẩn đường link nhưng giữ nhãn loại (`[LINK github]`), và từ điển hiểu github → version control.
3. **JD tiếng Việt, CV tiếng Anh thì máy không hiểu nhau.** "dự án", "thực tập", "học máy", "thị giác máy tính", "xử lý ngôn ngữ tự nhiên", "lập trình" không khớp với project, intern, machine learning, computer vision, NLP, Python. **Sửa:** thêm các cặp từ song ngữ vào từ điển.
4. **Kỹ năng chỉ liệt kê trong danh sách "Skills" vẫn được 2–4 điểm.** Thang chấm của chính hệ thống định nghĩa 1 điểm là "chỉ nhắc đến, không có minh chứng", nhưng engine baseline lại cho tới 4 điểm. Một CV bán hàng nhồi 30 từ khoá AI vào mục kỹ năng được 56,9 điểm (chỉ bị loại vì trượt bằng cấp). **Sửa:** kỹ năng chỉ thấy trong danh sách kỹ năng, không xuất hiện trong kinh nghiệm hay dự án, bị chặn tối đa 1 điểm. Điểm của CV nhồi từ khoá tụt từ 56,9 xuống 35,8. Khi tìm bằng chứng "đã dùng thật", mục dự án cũng được tính (trước đó chỉ tính mục kinh nghiệm, thiệt cho fresher).

**Kết quả:** CV sinh viên AI thật từ 46,1 lên **88,5, "Phù hợp - Mời phỏng vấn"**. `data_heldout` giữ nguyên Spearman 0,93 và quyết định 3 mức không đổi; chỉ có hai CV biên ở bộ này bị trừ nhẹ điểm (39,6 → 34,9 và 59,4 → 50,0) do quy tắc chặn kỹ năng chỉ liệt kê. Đây là đánh đổi có chủ ý, cần dữ liệu thật để cân lại.

**Chưa sửa (chủ ý):** chưa đọc điểm GPA; chưa phân biệt dự án nhóm với dự án cá nhân; nhóm ngành vẫn là danh sách viết tay.
### 3.13 Nâng cấp cấu trúc và hoàn thiện (hệ thống chạy hoàn toàn không cần LLM)
Mục tiêu: một hệ thống rõ ràng, một chỗ để chỉnh, một luồng duy nhất, và không phụ thuộc dịch vụ ngoài. Kiểm tra toàn bộ cấu trúc thấy các vấn đề sau và đã xử lý:

**Cấu trúc**
1. **Hằng số rải rác trong 6 file** (ngưỡng ở `scoring.py`, `verdict.py`; hệ số ở `baseline.py`; trọng số ở `jd_rules.py`...). Nay gom về `cv_agent/config.py`; muốn chỉnh ngưỡng chỉ sửa một chỗ.
2. **Logic chấm trộn với LLM.** `aggregate` nằm trong `scoring.py` (file import SDK LLM), nên engine luật phải import "vòng" để dùng nó. Nay tách sang `aggregate.py` không phụ thuộc LLM; `scoring.py` chỉ giữ phần LLM và re-export tên cũ. Có test xác nhận các module lõi **không import `anthropic`**.
3. **Hai nơi lặp lại cùng một luồng** (`run.py` và `app.py` đều tự đọc file, chấm, bắt lỗi, xếp hạng). Nay gom vào `pipeline.screen()` dùng chung, nên sửa một lần là cả hai hưởng.
4. **LLM từng là mặc định** (`run.py`, `eval.py` mặc định engine llm; giao diện có ô nhập API key; OCR dự phòng gửi ảnh CV cho Claude). Nay mặc định là luật; LLM chỉ bật khi đặt `CV_AGENT_ENABLE_LLM=1`; không còn ô nhập khoá trong giao diện; OCR chạy trên máy.
5. **Ngưỡng của giao diện không khớp tính toán.** Thanh trượt chỉ chỉnh được ngưỡng "có thể mời", còn "phù hợp" cố định, nên kéo thanh trượt có thể ra kết luận mâu thuẫn. Nay `verdict()` là hàm thuần của (điểm, các cờ, 3 ngưỡng) và giao diện có đủ 3 thanh trượt, có kiểm tra thứ tự ngưỡng (`loại < có thể mời < phù hợp`).

**Lỗi và thiếu sót đã sửa**
6. **File `.txt` ANSI bị giải mã thành chữ Hán**: thử `utf-16` trước mà không cần BOM, file độ dài chẵn nào cũng "giải mã thành công". Nay chỉ thử utf-16 khi có BOM.
7. **PDF hai cột bị đọc xen kẽ từng dòng** (rất hay gặp ở mẫu CV đẹp), làm lẫn kinh nghiệm với kỹ năng. Nay phát hiện khe giữa hai cột và đọc hết cột trái rồi cột phải, giữ nguyên tiêu đề trải ngang. Đã kiểm tra không nhận nhầm trên 10 PDF một cột.
8. **CV rỗng/quá ngắn** từng ra "Loại 0 điểm" như một ứng viên thật. Nay báo LỖI, cần xem thủ công.
9. **Ngày tháng vô lý** ("2023 - 2019", bắt đầu ở tương lai) từng bị bỏ im lặng (tính 0 năm). Nay có cảnh báo.
10. **Loại nhầm người nhiều năm kinh nghiệm khác lĩnh vực**: yêu cầu "2 năm kinh nghiệm phân tích dữ liệu" mà CV là kế toán 5 năm bị `not_met` → Loại, chỉ vì từ khoá không khớp. Nay nếu tổng số năm đi làm đã đủ mà chỉ không thấy đúng lĩnh vực thì là `unclear` (người xem), không phải loại tự động.
11. **Quy tắc "kỹ năng cốt lõi ≥ 60%" vô nghĩa khi JD chỉ có 1–2 kỹ năng bắt buộc** (1 mục trượt là tỉ lệ 0%). Nay chỉ áp khi có ≥ 3 kỹ năng bắt buộc.
12. **File quá lớn/hỏng** (PDF hỏng, DOCX hỏng, `.doc`, file > 25 MB, văn bản > 150.000 ký tự) nay báo lỗi rõ ràng hoặc cắt bớt có cảnh báo thay vì treo hay văng traceback.
13. **DOCX bảng có ô gộp** bị lặp chữ; nay bỏ trùng ô gộp.
14. **Excel/CSV thiếu thứ HR cần nhất**: không có tên, email, SĐT (chỉ có tên file), không giải thích vì sao "Loại". Nay có tên, liên hệ (lấy từ CV gốc, không đưa vào bước chấm), GPA, ngoại ngữ, GitHub, số năm, cột "Vì sao kết luận vậy"; bằng điểm thì ai đạt nhiều kỹ năng bắt buộc hơn xếp trước.
15. **Phát hiện CV nộp trùng** (cùng nội dung); đánh dấu cần xem.
16. **Kết quả mất khi tải lại trang** nay tự lưu vào `outputs/` (Excel, CSV, rubric, JD đã lọc) và mở lại được từ thanh bên.
17. **OCR không có đường chạy cục bộ nếu thiếu Tesseract.** Thêm RapidOCR (cài bằng pip) làm phương án sau; kết quả mất dấu tiếng Việt nên luôn bị gắn cờ "cần xem lại". Đã chạy thật trên PDF chỉ có ảnh: đọc ra chữ, điểm tụt từ 76,9 xuống 64,8 và bị đánh dấu cần xem — đúng kỳ vọng của một phương án cuối.
18. **Chạy song song** (4 CV cùng lúc) có khóa riêng cho OCR vì OCR nặng và dùng chung model.
19. **`eval.py`** từng tự tạo thư mục cache dù không dùng LLM, mặc định engine LLM, và chỉ đo 3 mức. Nay mặc định engine luật, báo lỗi rõ khi thiếu file nhãn, và đo thêm trên kết luận 4 mức mà HR thấy: người đáng mời có vào danh sách không, người không đáng mời có lọt vào không, và có **loại nhầm** người đáng mời không (lỗi nặng nhất). **`calibrate.py`** hướng dẫn sai chỗ đặt ngưỡng nay đã sửa, và bỏ qua thư mục thiếu nhãn.
20. **Đóng gói:** `requirements.txt` tách thành lõi / OCR / LLM (lõi không còn kéo `anthropic`); thêm `.gitignore`, `start_app.bat`, `run_tests.bat`.

**Kết quả đo lại (engine luật):** `data_heldout` từ 67% lên **75%** đúng 3 mức, Spearman vẫn 0,93, 100% người "Phù hợp" nằm trong danh sách phù hợp (trước 75%), không người "Không phù hợp" nào lọt vào danh sách. `data_ai`: 100% người "Phù hợp" nằm trong danh sách, 0% lọt. Cảnh báo trung thực: hai sửa đổi số 10 và 11 được phát hiện nhờ chính `data_heldout`, nên bộ này không còn độc lập; cần CV thật để xác nhận.
### 3.14 Vòng rà soát thứ hai và làm lại giao diện
**Lỗi tìm thấy bằng cách thử nhiều kiểu JD / CV khác nhau** (chạy 49 CV × 7 JD = 343 lượt chấm, không còn lỗi):
1. **JD tiếng Anh "What you'll bring:" mất cả mục yêu cầu** (chỉ còn phần "Nice to have"), cùng lỗi với "Required skills" đã sửa trước đó. Gốc rễ: tiêu đề lạ bị gộp vào mục trước. Nay tiêu đề lạ mở mục riêng và được **đoán loại theo nội dung** (đa số dòng giống yêu cầu ứng viên thì coi là yêu cầu, và ghi chú để HR biết). Thêm nhiều tiêu đề phổ biến, nhận cả dấu nháy cong.
2. **JD viết một đoạn văn bị báo lỗi** vì cả đoạn bị coi là tiêu đề. Nay dòng đầu chỉ là tiêu đề khi ngắn, không phải câu và JD còn dòng khác; JD một đoạn được tách thành mệnh đề.
3. **"Có ít nhất 2 năm kinh nghiệm" (tiếng Việt, rất phổ biến) bị coi là yêu cầu theo lĩnh vực**: chữ "Có" còn sót lại nên không nhận ra là yêu cầu chung, kết quả là mọi CV đều "chưa rõ" số năm. Nay dùng chính bộ phân tích từ khoá để xác định.
4. **Số năm chung chung đang cộng điểm miễn phí**: ai có 5 năm làm kế toán cũng được ~33 điểm cho JD lập trình chỉ vì "đủ năm". Nay yêu cầu số năm không nêu lĩnh vực chỉ là **cổng điều kiện cứng**, không cộng điểm; yêu cầu theo lĩnh vực ("1 năm chạy Facebook Ads") vẫn được chấm. Hệ quả: điểm không còn phụ thuộc vào việc JD có dòng số năm hay không, nên so sánh giữa các JD công bằng hơn. Đổi lại thang điểm dịch xuống vài điểm: kết luận 3 mức trên `data_ai` giảm từ 67% xuống 44% (các CV biên rơi xuống dưới ngưỡng 50), trong khi thước đo HR thấy (danh sách phù hợp) giữ nguyên 100% / 0% lọt, Spearman 0,88 → 0,85. Cần CV thật để hiệu chỉnh lại ngưỡng.
5. **Ký hiệu gạch đầu dòng PDF bị trích thành "(cid:127)"** lẫn vào văn bản, bằng chứng và so khớp từ khoá. Nay chuyển thành "- " hoặc xoá.
6. **DOCX bỏ sót chữ trong đầu/chân trang và hộp văn bản**, nơi mẫu CV đẹp hay đặt tên, liên hệ, kỹ năng. Nay đọc từ XML theo thứ tự tài liệu (kể cả bảng hai cột, xuống dòng mềm trong ô).
7. **Bảo mật: "CSV/Excel injection".** Một CV có tên kiểu `=HYPERLINK(...)` sẽ trở thành công thức khi HR mở Excel/CSV. Nay ô văn bản từ CV không bao giờ là công thức (Excel: ép kiểu chuỗi; CSV: thêm dấu nháy đơn).
8. **Bảo mật giao diện:** mọi chuỗi từ CV chèn vào HTML đều đi qua `escape` (có test với `<script>`, `<img onerror>`).

**Giao diện mới** (`app.py` + `webui/`). Mục tiêu: HR làm được việc mà không cần đọc hướng dẫn.
- **Luồng 3 tab** (1) JD → (2) CV → (3) Kết quả, tự chuyển sang kết quả khi chạy xong; nút "Dùng dữ liệu mẫu" để thử ngay.
- **Lọc JD hiển thị rõ ràng**: số điều kiện bắt buộc / kỹ năng / ưu tiên / phần đã bỏ, từng mục là một thẻ màu; chỉnh được JD đã lọc.
- **Kết quả**: thẻ ứng viên có điểm và thanh ngưỡng, kết luận, "vì sao", "HR cần xem gì" (khung vàng), điểm mạnh / khoảng trống, chi tiết từng tiêu chí với bằng chứng; mặc định hiện **danh sách phù hợp**, lọc thêm Dự phòng / Loại, tìm theo tên/email/kỹ năng, chỉ CV cần xem lại, sắp xếp, phân trang.
- **Quy trình HR**: chọn *Mời phỏng vấn / Giữ lại / Từ chối* và ghi chú ngay trên thẻ, tự lưu và có trong Excel; **so sánh 2–4 ứng viên** theo từng tiêu chí (tô màu); biểu đồ điểm có vạch ngưỡng; **sao chép email** danh sách mời.
- **Tiện lợi**: mức chọn lọc dựng sẵn (Nghiêm ngặt / Cân bằng / Rộng rãi) thay vì bắt chỉnh 3 thanh trượt; mở lại các lần chạy trước (nhãn "20/10 20:40 · JD · 9 CV"); tiến độ theo từng CV; dùng được trên màn hình nhỏ.
- **Riêng tư**: không tải font/tài nguyên từ internet, tắt thống kê của Streamlit (`.streamlit/config.toml`), kết quả chỉ lưu trong thư mục `outputs/` trên máy.
- **Kiểm thử**: `AppTest` chạy app thật với dữ liệu mẫu (lọc JD, chấm, chọn quyết định HR, kiểm tra file lưu); phát hiện JD đổi sau khi lọc.
- Cách làm: dựng giao diện, chạy thật trong trình duyệt và chụp màn hình ở màn hình rộng và màn hình tablet để chỉnh (ví dụ chữ bị cắt, bảng trống, chuyển tab sau khi chạy).
### 3.15 Vòng ba: tên ứng viên khi quét OCR, mô hình quyết định, giao diện web mới
Phản hồi nhận được: giao diện xấu và chưa tối ưu, quyết định chưa ổn, và **không đọc được tên ứng viên khi quét OCR nếu phía trên có chữ khác**.

**A. Đọc tên ứng viên (`cv_agent/identity.py`)**
- *Triệu chứng:* tên chỉ được thử ở dòng đầu tiên của CV. Có "CURRICULUM VITAE", chức danh hay slogan ở trên thì không ra tên; bản OCR còn dính chữ và mất dấu ("NGUYENHOANGNAM"). Cùng lỗi làm bộ ẩn danh **không ẩn được tên** khi chấm.
- *Cách sửa:* quét 25 dòng đầu, chấm điểm từng dòng/đoạn theo "giống tên người" (họ Việt phổ biến, viết hoa đúng kiểu, nằm gần đầu, trùng phần trước @ của email), bỏ qua tiêu đề chung (CV, Resume, Sơ yếu lý lịch), tên mục, chức danh, địa danh, dòng có số/email/link. Tách được tên nằm cùng dòng với chức danh ("NGUYỄN HOÀNG TUẤN AI Engineer"), tên sau nhãn ("Họ và tên: ..."), tên VIẾT HOA.
- *Với OCR:* tách chữ dính bằng quy hoạch động trên âm tiết tên Việt ("NGUYENHOANGNAM" → Nguyen Hoang Nam; đã thử 20 tên). Tên đọc từ OCR mà không được xác nhận thì ưu tiên tên file, rồi email; HR luôn thấy dấu "?" và ghi chú "tên lấy từ ..., cần xác nhận".
- *Bẫy đã gặp và sửa trong lúc làm:* bỏ dấu làm "học vấn" trùng "Văn", "quận" trùng "Quân", và "Minh", "Nam", "Hà" vừa là địa danh vừa là tên người; nên cụm tiếng Việt được khớp theo cả cụm chứ không theo từ đơn; "ho-so" trong tên file là "hồ sơ", không phải họ Hồ.
- *Kiểm chứng:* chạy thật 5 bản scan (ảnh → RapidOCR) với tiêu đề CURRICULUM VITAE / RESUME / chức danh / slogan / tên cùng dòng chức danh: cả 5 đều ra đúng tên. Ba test lỗi bắt được trong lúc làm (cụm con "Hồ Chí", "Sơ Yếu Lý" bị nhận nhầm là tên) đã được sửa.

**B. Mô hình quyết định**
- *Vấn đề:* kết luận dựa vào **điểm tổng**, trong đó kỹ năng ưu tiên (nice-to-have) chiếm tới ~25%. Người đủ mọi yêu cầu bắt buộc nhưng thiếu điểm cộng chỉ được ~67 điểm và không đạt "Phù hợp"; ngược lại điểm cộng có thể che việc thiếu yêu cầu bắt buộc.
- *Cách sửa:* quyết định theo **mức đáp ứng yêu cầu bắt buộc** (`required_score`); điểm cộng chỉ để xếp hạng trong cùng nhóm kết luận. Không chỉnh ngưỡng (vẫn 70/50/30).
- *Kết quả đo:* `data_heldout` đúng 3 mức 75% → **83%**, `data_ai` 44% → **67%**; calibrate (đánh giá chéo theo JD) chọn lại đúng FIT = 70, xác nhận ngưỡng này ổn định. Tất cả người "Phù hợp" vẫn nằm trong danh sách và không người "Không phù hợp" nào lọt vào.
- *Giải thích được:* mỗi CV có **bảng đối chiếu** từng điều kiện cứng (đạt / không đạt / chưa rõ) và từng kỹ năng (tốt / một phần / yếu / không thấy) kèm bằng chứng, **đề xuất** (Mời / Cân nhắc mời / Giữ dự phòng / Không mời) và câu "vì sao" bằng số liệu thật ("Đáp ứng 75% yêu cầu bắt buộc (cần ≥70%) và đạt đủ điều kiện cứng"). HR quyết định theo danh sách, không theo một con số.
- *Quy trình HR:* ba nút **Mời / Giữ / Bỏ** + ghi chú ngay trên mỗi thẻ, "Chấp nhận đề xuất" hàng loạt, tự lưu và có trong Excel; email của người được mời.

**C. Giao diện web mới (`webapp/`)**
- *Vì sao bỏ Streamlit làm giao diện chính:* bố cục bị giới hạn (cả trang chạy lại sau mỗi thao tác, khó làm ngăn chi tiết, phím tắt, chọn nhiều dòng, kéo thả cả thư mục), và phải cài thêm nhiều thư viện. Giao diện mới là một trang HTML/CSS/JS thuần do máy chủ HTTP chuẩn của Python phục vụ; không cần Node, không tải gì từ internet. Giao diện Streamlit cũ vẫn còn (tùy chọn).
- *Bố cục:* cột trái là ba bước (JD → CV → mức chọn lọc) với nút chạy luôn ở chân; bên phải là kết quả. Thẻ ứng viên: avatar, tên, liên hệ, thanh % đáp ứng có vạch ngưỡng, kết luận + đề xuất + lý do, **dải ô màu đối chiếu yêu cầu** (nhìn một cái biết thiếu gì), nút Mời/Giữ/Bỏ. Bấm vào thẻ mở **ngăn chi tiết** bên phải (điều kiện, kỹ năng, bằng chứng, "HR cần xem", văn bản máy đọc được từ CV).
- *Thao tác nhanh:* lọc theo nhóm bằng các ô đếm màu, tìm kiếm không phân biệt dấu, sắp xếp, chỉ CV cần xem lại / chưa quyết định, chọn nhiều → so sánh 2–4 người, phím tắt (↑ ↓ Enter 1 2 3 A / ?), kéo thả cả **thư mục**, hiển thị tiến độ từng CV, mở lại / xóa các lần chạy cũ, giao diện gọn/thoáng, dùng được trên màn hình nhỏ.
- *An toàn:* chỉ lắng nghe 127.0.0.1; mọi lệnh gọi `/api` cần mã truy cập ngẫu nhiên tạo mỗi lần chạy và Host/Origin phải là localhost (chặn trang web khác gọi vào máy chủ cục bộ: CSRF / DNS rebinding); chặn `../` khi phục vụ file; toàn bộ chữ từ CV đi qua `textContent`, không bao giờ chèn HTML; không lộ đường dẫn trên máy ra giao diện.
- *Lỗi bắt được lúc làm:* chữ "null" hiện ra vì `replaceChildren(null)` của trình duyệt; máy chủ trả lỗi mà chưa đọc hết body làm trình duyệt thấy "connection reset" (đã sửa bằng cách luôn đọc hết body); kết quả ngẫu nhiên không ổn định phát hiện nhờ chạy lặp test 8 lần liên tiếp.
- *Kiểm thử:* 18 test chạy máy chủ thật trên cổng tạm (bảo mật, tải lên nhiều file có tên trùng, quét thư mục, luồng sàng lọc → quyết định → xuất → xóa, CV hỏng không làm hỏng cả lô) cộng thử thật trong trình duyệt ở màn hình rộng và 1000 px.

### 3.16 Vòng bốn: chạy thử với CV PDF thật và nâng cấp toàn hệ thống
Cách làm: chạy hệ thống với các CV PDF thật (xuất từ Canva và các mẫu CV khác) và một JD thật, thay vì CV tự dựng. Phần lớn lỗi dưới đây **chưa từng lộ ra** với dữ liệu tự viết.

**A. Đọc PDF thật (`io_utils.py`)**
- *Chữ bị vẽ thành đường nét* (Canva/Figma xuất ra): PDF không có lớp chữ nên đọc ra gần như trống, CV bị chấm 0 và loại oan. Trước đây chỉ đếm tổng ký tự nên không bắt được (một trang vẫn có chữ nên cả file "có chữ"). Nay đếm **số từ theo từng trang**: file đủ chữ thì không OCR; file thiếu chữ thì **chỉ OCR các trang thưa** rồi ghép với chữ đọc được (hai nguồn không bị lặp dòng), nguồn ghi là `pdf+ocr:<engine>` và bị gắn cờ cần xem lại.
- *Từ dính nhau* khi dùng pdfplumber ("Developmentofmachine..."): nay dùng **PyMuPDF làm chính** (giữ khoảng trắng và thứ tự khối chữ của file), chỉ chuyển sang pdfplumber + tách cột theo "khe giữa" khi PyMuPDF đọc xen kẽ hai cột hoặc cho chất lượng kém hơn rõ rệt.
- *Biểu tượng của mẫu CV* (biểu tượng phong bì, điện thoại... và ký tự font icon ở vùng Private Use) lẫn vào chữ: bị lọc.
- *Link GitHub bị cắt* (chữ hiển thị rút gọn "github.com/abc/..."): lấy **địa chỉ thật từ chú thích link** của PDF và ghép vào cuối văn bản (mục "Links").
- *CV chỉ có vài từ* (file ảnh, nộp nhầm): trước đây bị chấm 0 điểm rồi "Loại". Nay báo **lỗi "Chỉ đọc được N từ ... cần xem thủ công"**, không kết luận bừa.
- Tắt hàng trăm dòng cảnh báo "Could not get FontBBox" của pdfminer.

**B. Tên ứng viên (`identity.py`)**: tên file kiểu `DangNguyenVanAnh_CV.pdf`, `CV_NguyenHoangNam_AI.pdf` (CamelCase, gạch dưới, gạch nối) được tách đúng; cửa sổ tìm tên chặt hơn để không nhận nhầm cụm con như "Hồ Chí" (trong "Hồ Chí Minh") hay "Sơ Yếu Lý" làm tên. Tên lấy từ file/email/OCR vẫn bị gắn cờ "cần xác nhận".

**C. Chấm điểm**
- *JD nêu số năm hai lần* ("2+ years ... in full-stack development" và "Years of experience: 2+ YoE") tạo hai điều kiện cứng giống nhau: `_dedupe_years` giữ câu nêu lĩnh vực (nếu cả hai chung chung thì giữ mức cao nhất) và đánh số lại mã điều kiện.
- *Bảng đối chiếu không lặp số năm* ở phần kỹ năng (đã hiện ở điều kiện bắt buộc).
- *Chứng chỉ TOEIC/IELTS là bằng chứng cho "giao tiếp tiếng Anh tốt"*: trước đây tiêu chí này chấm theo từ khoá và có thể 0 điểm dù CV có TOEIC 850.
- *CV đọc bằng OCR không bao giờ bị loại vì điều kiện cứng*: số OCR có thể sai (TOEIC 850 thành 550). Điều kiện "không đạt" được hạ thành "chưa xác minh" kèm ghi chú để HR đối chiếu file gốc.
- *Từ điển*: thêm cách viết tắt/viết khác hay gặp (k8s, sklearn, js/ts, MS Excel, Postgres, YOLOv8, GPT-4, ...) và công cụ AI/ML (LangChain, FAISS, spaCy, SageMaker, ONNX, DVC...). Đo lại: không giảm độ chính xác (Spearman `samples` 0,85 → 0,87).

**D. Hệ thống và giao diện**
- **Đổi mức chọn lọc ngay trên kết quả** (nút "Mức chọn lọc"): mỗi dòng lưu thêm `verdict_inputs` (các điểm và cờ đầu vào của kết luận) nên `report.rejudge()` tính lại kết luận, đề xuất, lý do và xếp hạng **mà không đọc/chấm lại CV**; quyết định và ghi chú của HR được giữ. Có test chứng minh kết quả bằng đúng một lượt chạy mới ở mức đó. Lần chạy cũ (chưa có `verdict_inputs`) được nhận ra và nút bị khoá kèm giải thích.
- **Nút Dừng khi đang sàng lọc** (`threading.Event`): CV chưa bắt đầu bị bỏ, CV đang đọc dở chạy nốt; không lưu kết quả dở.
- **Báo cáo in được** (`webapp/printable.py`): một trang HTML (danh sách phù hợp / đã chọn mời / tất cả) gồm yêu cầu của JD, bảng xếp hạng, và từng ứng viên với bảng đối chiếu, bằng chứng, lý do, ghi chú HR; In → Lưu thành PDF để gửi trưởng bộ phận. Mọi chữ từ CV qua `html.escape` (có test với `<script>`, `<img onerror>`).
- **Ghi file an toàn**: `rows.json`/`meta.json` ghi ra file tạm rồi đổi tên, mất điện giữa chừng không làm hỏng kết quả đã lưu.
- **Dọn cấu trúc**: giao diện Streamlit cũ chuyển vào `legacy_streamlit/` (còn chạy được, có test riêng, không nằm trong bộ test chính); thêm `pyproject.toml` (`pip install -e .` có lệnh `cv-agent`, `cv-agent-web`), workflow CI (test + pyflakes), `CHANGELOG.md`; phiên bản 0.5.0.

**E. Kiểm chứng**
- Bộ test: 98 → **119** test, gồm các test mới cho từng lỗi ở trên. Mỗi tính năng mới được **phá thử** (tắt `_dedupe_years`, tắt lọc ký tự icon, tắt ghép link, tắt cộng chứng chỉ, cho `rejudge` không làm gì...) để chắc chắn test tương ứng chuyển đỏ, tránh test "xanh vô nghĩa".
- Đo lại: `data_heldout` đúng 3 mức 83%, Spearman 0,93; `samples` đúng 3 mức 67%, Spearman 0,87 (không đổi, riêng Spearman `samples` nhích lên).
- Chạy thật 3 CV PDF thật với JD thật: tên đúng, CV scan lai được đọc bằng RapidOCR (kèm cờ), hai CV thực tập (dưới 2 năm kinh nghiệm) đúng là "Loại" vì trượt điều kiện số năm.
- Trình duyệt thật: đổi mức chọn lọc (số liệu các ô đếm thay đổi đúng), nút Dừng (hiện thông báo, không lưu), trang báo cáo in được.

**F. Còn tồn tại (nói thẳng, đã được cập nhật ở 3.17)**: chữ **toàn chữ thường bị dính** ("strengtheningsoftwareengineeringskills") chưa tách được vì cần từ điển tiếng Anh đầy đủ; RapidOCR chậm (~14 giây/trang) và mất dấu tiếng Việt, Tesseract chưa thử trên máy này; workflow CI chưa được chạy thật trên GitHub; máy này không có Node nên mã JS chỉ được kiểm bằng cách chạy trong trình duyệt, không có kiểm tra cú pháp tự động.

### 3.17 Vòng năm: tìm lỗi có hệ thống thay vì chờ gặp lỗi
Các vòng trước sửa lỗi khi tình cờ gặp. Vòng này **chủ động tìm lỗi** bằng bốn cách, rồi sửa những gì tìm được.

**A. Bốn cách tìm lỗi**
1. **Fuzz**: làm hỏng ngẫu nhiên JD và CV (xóa đoạn, chèn rác như `99/9999`, `TOEIC ≥ .`, ký tự điều khiển, chuỗi 5.000 chữ, xáo dòng, đổi mã hóa...) rồi chạy cả đường chấm. hơn 2.400 JD và 7.200 CV bị làm hỏng: không có ngoại lệ nào, điểm luôn trong 0–100, kết luận luôn hợp lệ.
2. **Kiểm thử bất biến**: một biến đổi *không đổi nghĩa* của CV/JD thì kết quả phải y nguyên. Thử 12 kiểu (dấu tiếng Việt rời, NBSP, xuống dòng kiểu Mac/Windows, dòng trống xen kẽ, tab, BOM, bullet khác...) trên 21 cặp JD–CV. Đây là cách tìm ra lỗi 1 bên dưới.
3. **Thử theo họ giá trị**: 14 cách viết khoảng thời gian (`03/2021`, `Mar 2021`, `Tháng 3/2021`, `T3/2021`, `03.2021`, `~`, `đến`, `to`...) và 8 cách viết "đến nay" cho kết quả giống nhau; JD → JD đã lọc → rubric ổn định (8 JD, kể cả JD viết một đoạn văn).
4. **Đo ở quy mô thật**: 600 CV qua giao diện, bấm thật trong trình duyệt. Đây là cách tìm ra lỗi 8.

**B. Lỗi tìm được và đã sửa**
| # | Lỗi | Hậu quả thật | Cách sửa |
|---|---|---|---|
| 1 | Dấu tiếng Việt viết rời (NFD), khoảng trắng NBSP, xuống dòng `\r` làm đổi kết quả (7/21, 8/21 và 1/21 cặp) | CV copy từ Word/Mac/web bị chấm khác, thậm chí từ "Phù hợp" thành "Có thể mời", tên ứng viên đọc nhầm từ email | `textutil.clean_text` (NFC, khoảng trắng lạ → dấu cách, `\r`, ký tự vô hình/điều khiển) ở mọi cửa vào: đọc file, JD, chấm, trích thông tin, ẩn danh, tìm tên |
| 2 | JD "Không yêu cầu kinh nghiệm, biết Python và PyTorch" bị bỏ cả dòng; từ "fresher" làm mất cả yêu cầu chứa nó; "Tốt nghiệp đại học, không yêu cầu kinh nghiệm" mất điều kiện bằng cấp | Mất kỹ năng và điều kiện bắt buộc khỏi rubric mà không ai biết | Chỉ bỏ cụm "không yêu cầu kinh nghiệm", giữ phần còn lại; dòng chỉ có cụm đó vẫn bỏ |
| 3 | TOEIC ghi theo kỹ năng ("Listening 450 Reading 400") đọc thành 450; "TOEIC (2023): 800" bỏ sót; "TOEIC ≥ ." gây `ValueError` | Người 850 điểm bị coi 450 → "không đạt" → loại; JD lạ làm hỏng cả lần lọc JD | Cộng điểm hai kỹ năng / lấy tổng sau dấu `=`, cho phép ngoặc sau tên chứng chỉ, bỏ qua số không đọc được |
| 4 | Tên ứng viên 1 chữ ("Name: A") làm mọi chữ "a" trong CV bị ẩn thành `[NAME]` | Mất chữ trong CV trước khi chấm | Tên ngắn hơn 4 chữ chỉ ẩn ở dòng chứa nó |
| 5 | `CV_AGENT_AS_OF` sai định dạng làm cả chương trình lỗi | Không chạy được | Sai thì dùng ngày hôm nay |
| 6 | "(2022 - Present)" ở mục học vấn được coi là "đã có bằng" | JD đòi "Tốt nghiệp đại học" nhưng sinh viên chưa tốt nghiệp vẫn đạt điều kiện cứng | `education_in_progress`: ngày kết thúc ở tương lai/"nay", hoặc ghi sinh viên/năm cuối/dự kiến, mà không có khoảng học nào đã kết thúc → "chưa rõ, cần xác nhận". JD cho phép sinh viên thì không áp dụng. Người đã tốt nghiệp không bị ảnh hưởng. **Đổi hành vi:** sinh viên còn đang học nay thành "Có thể mời" (vẫn trong danh sách phù hợp) thay vì "Phù hợp" |
| 7 | Chữ dính liền (OCR/PDF mất khoảng trắng): "strengtheningsoftwareengineeringskills", "Universityof" | Kỹ năng không khớp; "Universityof" khiến học vấn bị báo "cấp bậc thấp hơn" | Không cần từ điển: tìm từ khoá của JD *bên trong* từ dài ≥ 14 chữ cái (điểm × 0,9, từ khoá ≥ 5 chữ cái); văn bản OCR dùng regex bằng cấp "lỏng" |
| 8 | Mỗi lần HR bấm Mời/Giữ/Bỏ phải ghi lại cả Excel: **2,5 giây** với 600 CV; nếu HR đang mở `ketqua.xlsx` trong Excel thì lỗi `PermissionError` làm thao tác báo lỗi | Giao diện đơ; quyết định có vẻ không lưu | `rows.json` ghi ngay (~80 ms với 600 CV), Excel/CSV gom lại ghi sau 1,5 giây khi HR ngừng thao tác (hoặc khi tắt), không giữ khóa khi ghi; không ghi được thì báo "đóng ketqua.xlsx lại" chứ không làm hỏng thao tác. Mỗi lần bấm: 2,5 s → **82 ms** |
| 9 | Tên file tải lên có `:` `*` `?`, tên thiết bị `CON`/`NUL`, hoặc dài 400 ký tự gây lỗi 500 trên Windows | Không tải được CV | `safe_filename` |
| 10 | `Content-Length: -5` làm luồng máy chủ chờ mãi | Treo một luồng | Trả 400 |
| 11 | Quét thư mục gốc ổ đĩa kèm "gồm thư mục con" | Máy chủ cục bộ treo | Giới hạn 3.000 file, bỏ thư mục ẩn/hệ thống (`.git`, `node_modules`...) |
| 12 | PDF vài nghìn trang bị nạp hết trước khi cắt 12 trang; file PDF không đóng (Windows không xóa được); DOCX "zip bomb" (vài trăm KB giải nén ra GB) | Hết bộ nhớ, file kẹt | Đọc theo chỉ số trang, `finally: close()`, kiểm tra tổng kích thước giải nén (100 MB) |
| 13 | Ký tự điều khiển trong chữ làm `openpyxl` ném `IllegalCharacterError`; ô trên 32.767 ký tự làm Excel báo file hỏng | Không xuất được Excel | Làm sạch và cắt ô |

**C. Nâng cấp**
- **Phát hiện CV gần giống nhau** (`cv_agent/dedupe.py`): cùng một người nộp bản PDF và DOCX, hoặc sửa vài dòng rồi nộp lại. Độ giống Jaccard của cụm 4 từ liên tiếp ≥ 65%; dùng MinHash đáy-k để chỉ so các cặp có chung "dấu vân tay" (3.000 CV trong ~2,5 giây). Đo: hai người khác nhau tối đa 5% (0 báo nhầm trên 21 CV mẫu), sửa 5% số từ vẫn bắt được (19/21), 1.500/1.500 bản sửa nhẹ trên bộ tổng hợp. Bản đứng sau bị gắn cờ "giống 91% CV «...»".
- **Tìm kiếm toàn văn** trong giao diện: không chỉ tên/email mà cả nội dung CV, nhiều từ thì CV phải chứa tất cả, không phân biệt dấu; chuẩn hoá một lần cho mỗi dòng nên gõ vẫn mượt (600 CV: dựng lại danh sách 123 ms).

**D. Kiểm chứng**
- Bộ test 119 → **157**. Mỗi sửa lỗi có test; các test bất biến được **phá thử** (tắt `clean_text` → test NFD, NBSP, xuống dòng đều chuyển đỏ). Lần phá thử đầu phát hiện test xuống dòng cũ "xanh vô nghĩa" vì dùng một JD cho mọi CV; đã sửa test để chấm CV theo đúng JD của bộ chứa nó.
- Đo lại: `data_heldout` 83%, `samples` 67% (không đổi); chạy thật 600 CV qua trình duyệt: 19,5 giây, không lỗi console.

**E. Còn tồn tại (cập nhật ở 3.18)**: chữ toàn chữ thường bị dính chỉ được tìm *từ khoá bên trong* chứ chưa được tách ra thành từng từ (hiển thị vẫn dính); "đang học" chỉ nhận ra qua mục học vấn hoặc lời giới thiệu đầu CV; độ giống CV gần trùng dựa trên văn bản nên hai CV cùng người nhưng viết lại hoàn toàn sẽ không bị bắt; vẫn chưa thử Tesseract và CI trên GitHub.

### 3.18 Vòng sáu: làm lại giao diện cho đơn giản, thêm một lượt tìm lỗi API
Phản hồi: giao diện thao tác rất khó, cần đơn giản và bỏ những phần thừa.

**A. Vì sao khó dùng.** Màn hình hai cột đưa ra cùng lúc khoảng 15 điều khiển: sáu ô đếm, sắp xếp, mật độ gọn/thoáng, hai ô bật tắt, chọn nhiều + thanh hàng loạt, so sánh, bốn mức chọn lọc kèm ba ô số, ngăn chi tiết trượt, phím tắt, hộp hướng dẫn, và **dải ô màu** đối chiếu mà người mới phải học mới hiểu. Người dùng chỉ muốn: dán JD, thả CV, biết ai nên mời.

**B. Nguyên tắc làm lại.** Một việc cho mỗi màn hình; việc ít dùng gom vào một nút "Thêm"; không có điều khiển nào đòi phải đọc hướng dẫn. Viết lại toàn bộ `app.js` (khoảng 880 → 566 dòng) và `style.css` (275 → 171 dòng), một cột, chữ 15 px, chạy tốt ở 375 px.

| Trước | Nay |
|---|---|
| Hai cột: thanh trái + kết quả | Một cột, ba màn hình: **Thiết lập → Đang chạy → Kết quả** |
| Nút "Lọc JD" riêng, ô chỉnh JD đã lọc, nút "Áp dụng" | JD **tự được đọc** sau khi dán; một dòng "Đã hiểu JD: 3 điều kiện · 6 kỹ năng · 5 điểm cộng", bấm để xem chi tiết. Bỏ phần chỉnh JD đã lọc (sửa thẳng JD gốc) |
| Bốn mức (kèm "Tùy chỉnh"), ba ô số, thanh màu | Ba nút, mỗi nút một dòng mô tả. Ngưỡng tùy ý chỉ còn ở dòng lệnh |
| Ô "Tự OCR PDF" | Bỏ: luôn tự OCR khi cần |
| Sáu ô đếm + thanh màu | Bốn tab: Phù hợp · Dự phòng · Loại · Tất cả (thêm "Không đọc được" chỉ khi có CV lỗi) |
| Sắp xếp, mật độ, "chưa quyết định", chọn nhiều, so sánh 2–4, phím tắt, hộp hướng dẫn | Bỏ. Xếp hạng là thứ tự duy nhất; không còn gì cần hướng dẫn |
| Dải ô màu | Một câu lý do ngay dưới tên; chi tiết có biểu tượng tròn (tích xanh = đạt, chấm than vàng = yếu, gạch chéo đỏ = thiếu, dấu hỏi xám = chưa rõ) |
| Ngăn chi tiết trượt từ bên phải | Mở ngay trong thẻ (dùng được trên điện thoại) |
| Ba nút ngang hàng (Mức chọn lọc, Chấp nhận đề xuất, Xuất file) cùng thanh công cụ nhiều ô | **Tải Excel** (nút chính) và **Thêm** (đổi mức chọn lọc, chấp nhận đề xuất, sao chép email, CSV, in báo cáo) |

**Giữ lại** vì HR dùng hằng ngày: Mời / Giữ / Bỏ và ghi chú trên từng thẻ, tìm toàn văn, "Chỉ CV cần xem lại", các lần đã lưu, đổi mức chọn lọc không đọc lại CV, nút Dừng, Excel / CSV / báo cáo in.

**C. Kiểm chứng.** Chạy thật trong trình duyệt: dán JD mẫu (tự đọc), thêm 9 CV, sàng lọc, mở chi tiết, bấm Mời, đổi tab, tìm kiếm, mở từng mục menu, đổi mức chọn lọc (số ở các tab đổi đúng), mở hộp "Chấp nhận đề xuất" và "Email", quay lại màn hình thiết lập; ở 375 px không tràn ngang. Không có lỗi console.

**D. Lượt tìm lỗi API** (gọi ngẫu nhiên 1.500 lần với số / danh sách / đối tượng / chuỗi 3.000 chữ thay cho giá trị đúng kiểu, thân JSON hỏng, multipart hỏng, phương thức lạ):
- **15 lỗi 500** khi trường chữ nhận kiểu khác (`{"text": [1]}`, `{"path": 5}`, `{"index": "<script>"}`, `workers: "abc"`...). Nay kiểm kiểu ở `server.py` (`_text`, `_number`, `_int`, `_list`) và trả 400 kèm thông báo; sau sửa 0 lỗi trên ba hạt giống ngẫu nhiên.
- **Chỉ số ứng viên âm** (`index: -1`) sửa nhầm *ứng viên cuối cùng* vì Python hiểu chỉ số âm là đếm từ cuối: nay bị từ chối.
- Phương thức `PUT/PATCH` trả trang lỗi HTML 501: nay là JSON gọn.
- Dọn: bỏ dữ liệu thừa khỏi `/api/bootstrap`, chỉ giữ 10 tác vụ đã xong gần nhất trong bộ nhớ, bỏ hàm `summary_counts` không ai dùng, `run.py` bắt thêm lỗi tệp (file đang mở trong Excel) thay vì in traceback.

**E. Còn tồn tại**: không có Node nên mã JS chỉ kiểm bằng cách chạy trong trình duyệt; nhiều ứng viên cần so sánh thì phải mở từng thẻ (đã bỏ chức năng so sánh cạnh nhau); thư mục `legacy_streamlit/` (giao diện cũ) vẫn nằm trong dự án và có thể xóa nếu không dùng.

### 3.19 Vòng bảy: rà soát toàn bộ cấu trúc, ổn định và tốc độ
Cách làm: không đọc lại từng dòng mà **viết công cụ quét** cho từng loại lỗi nhỏ (bảng mã, ký tự vô hình, cú pháp theo Python 3.10, mã chết, `except` nuốt lỗi, lời gọi đọc/ghi file thiếu bảng mã, tham chiếu trong tài liệu, lớp CSS/hàm JS không dùng), **đo hiệu năng bằng profiler**, và **thử tải** nhiều tác vụ chạy song song kèm thao tác của HR.

**A. Lỗi nhỏ tìm được và đã sửa**
| Lỗi | Hậu quả | Sửa |
|---|---|---|
| `textutil.py` chứa ký tự vô hình (NBSP, zero-width, U+2028...) viết thẳng vào mã | Không nhìn thấy, không sửa được, công cụ khác dễ làm mất | Viết bằng mã điểm Unicode (`0x00A0`...) |
| BOM ở 4 file `.py` và workflow CI `.yml` | YAML có BOM có thể bị từ chối | Bỏ BOM (file CSV nhãn cũng bỏ) |
| Mã `lexicon_user.json` sai JSON/sai kiểu/regex sai làm **sập cả chương trình** khi `import` | Một lỗi gõ trong từ điển cá nhân khiến không chạy được gì | Bỏ qua file hỏng kèm cảnh báo, không nạp dở dang; tìm thêm ở thư mục gốc dự án |
| Header `X-CV-Token` có chữ ngoài ASCII làm `compare_digest` ném `TypeError` | Trả 500 thay vì 403 | So sánh dạng bytes |
| Kiểm tra thoát thư mục tĩnh bằng **tiền tố chuỗi** (`static_x` cũng bắt đầu bằng `static`); đường dẫn có NUL làm `resolve()` lỗi | Lỗ hổng tiềm tàng đọc file ngoài `static/` nếu có thư mục anh em; lỗi 500 | `Path.is_relative_to`, bắt `ValueError` |
| Kết nối treo/ngắt giữa chừng giữ luồng mãi, in traceback | Rò rỉ luồng, nhiễu console | `timeout = 300`, đọc body bọc `OSError`, bỏ yêu cầu im lặng |
| In tiếng Việt ra console/tệp bảng mã cũ (cp1252, cp437) gây `UnicodeEncodeError` | Dòng lệnh sập giữa chừng | `safe_console()`: ký tự không in được thành `?` |
| Thư mục kết quả không ghi được chỉ bị phát hiện **sau** vài phút sàng lọc | Mất công cả lô | Thử ghi trước khi bắt đầu |
| Thư mục tải lên tạm của phiên bị tắt đột ngột không bao giờ được dọn | `%TEMP%` phình dần | Dọn thư mục quá 24 giờ khi khởi động |
| Mọi lần chạy đã mở đều ở lại bộ nhớ | Tăng dần | Giữ tối đa 6 lần chạy, còn lại đọc lại từ đĩa |
| PDF bị cắt cụt đọc ra "0 ký tự" không báo lỗi; file nhị phân đổi đuôi `.txt` đọc ra rác | CV rỗng không rõ vì sao | Báo lỗi nêu nguyên nhân |
| Tải lại trang giữa lúc đang sàng lọc mất theo dõi tiến độ | HR tưởng mất kết quả | `bootstrap` trả tác vụ đang chạy, giao diện nối lại |
| Danh sách vài nghìn CV dựng hết một lần | Đơ khi mở kết quả lớn | Hiện 100 thẻ mỗi lần, nút "Hiện thêm" |
| `start_app.bat` không báo gì khi thiếu Python/thư viện; file `.bat` dùng xuống dòng LF | Cửa sổ đóng ngay, khó biết lỗi | Kiểm tra Python và thư viện, báo cách khắc phục, chuyển CRLF |
| `.gitignore` thiếu CV thật (`data/**/*.pdf`), `lexicon_user.json`, `*.egg-info` | Dễ đưa dữ liệu cá nhân lên kho mã | Bổ sung |
| `eval.py`, `calibrate.py` văng `ModuleNotFoundError` khi thiếu pandas/scipy | Khó hiểu | Thông báo cách cài |
| Tài liệu nhắc `data/cvs_backup_original/`, "97 test" đã lỗi thời | Sai lệch | Cập nhật |

**B. Tốc độ (không đổi kết quả).** Đo bằng `cProfile` trên 200 CV: 60% thời gian là các lệnh `re.sub`/`search` lặp lại. Sửa bốn chỗ:
1. `protect_tech`: một biểu thức gộp kiểm tra trước, đa số dòng bỏ qua được 26 lần thay thế.
2. `_implies_compiled`: chỉ thử các luật có từ đầu xuất hiện trong dòng (trước: cả ~190 luật cho mỗi dòng); giữ đúng thứ tự từ điển.
3. Nhớ lại những thứ chỉ phụ thuộc vào JD (`query_units`, `_expand_field`), `fold`, và `find_name` (mỗi CV bị hỏi tên 2-3 lần).
4. `write_excel`: `ws.max_row` duyệt mọi ô mỗi lần gọi nên vòng lặp O(n²); đếm hàng tại chỗ, dùng chung một đối tượng kiểu.

Kết quả: 600 CV chấm từ **27 ms xuống 14 ms/CV**; xuất Excel 600 dòng 3,2 s → 2,0 s. **Chứng minh không đổi kết quả:** chụp điểm, kết luận, tên, liên hệ, bằng chứng, bảng đối chiếu của 66 dòng trước và sau: 0 khác biệt; đo độ chính xác giữ nguyên (83% / 67%).

**C. Số luồng mặc định 4 → 2.** Đo 600 CV: 1 luồng 10,8 s, 2 luồng 8,5 s, 4 luồng 10,3 s; độ trễ hỏi tiến độ của giao diện 21 ms, 32 ms, 63 ms. Chấm CV thuần Python bị GIL khoá nên thêm luồng không nhanh hơn mà làm giao diện chậm lại (PDF 180 CV cũng vậy: 2,5 s ở mọi mức). Dùng quy trình riêng cho từng CV sẽ nhanh hơn nhưng phức tạp và dễ lỗi trên Windows, chưa làm.

**D. Thử tải.** Ba tác vụ 150 CV song song (một cái bị dừng giữa chừng) + ba luồng HR liên tục (quyết định, đổi mức chọn lọc, chấp nhận hàng loạt, tải Excel/CSV/báo cáo): 161 lời gọi, **0 lỗi 5xx, 0 khoá chết, 0 luồng rò rỉ**, `rows.json` nguyên vẹn, không còn file `.tmp`, `ketqua.xlsx` mở được. Fuzz lõi (hơn 1.000 JD, 3.000 CV bị làm hỏng) và fuzz API: 0 lỗi. Đọc 23 loại file hỏng/lạ (rỗng, ngẫu nhiên, cắt cụt, mã hoá, 40 trang, trang 14.000 pt, DOCX bảng lồng 25 cấp, UTF-16, cp1258...): chỉ ra `Document` hoặc `ValueError` có thông điệp, không treo.

**E. Còn tồn tại.** Mã JS vẫn chỉ kiểm bằng trình duyệt (không có Node); chưa chạy CI trên GitHub và chưa thử Tesseract; kiểm tra tương thích Python 3.10 chỉ ở mức cú pháp (`ast`) vì máy chỉ có 3.12.
---

## 4. Nhật ký lỗi (nguyên nhân → sửa → bài học)

| # | Lỗi | Nguyên nhân gốc | Cách sửa | Bài học |
|---|---|---|---|---|
| 1 | CV mạnh vẫn điểm thấp trên JD AI | Mục `Required skills/Experience:` không nhận ra, bị bỏ | Thêm tiêu đề, nhận `YoE` | Khi kết quả "sai mà đều", nghi ngờ khâu đầu vào trước khi nghi mô hình |
| 2 | "Marketing 2016" thành 03/2016 | Regex tháng `mar[a-z]*` khớp mọi từ bắt đầu bằng "mar" | Chỉ nhận tên tháng chuẩn | Regex quá rộng sinh lỗi khó thấy; cần test hồi quy |
| 3 | CV Java vẫn vào danh sách phù hợp | Điểm trung bình có trọng số che việc thiếu kỹ năng cốt lõi | Thêm `core_ratio` và quy tắc trần "Dự phòng" | Tổng điểm không đủ, cần ràng buộc theo điều kiện bắt buộc |
| 4 | Mọi CV bị `unclear` ở điều kiện ngoại ngữ | Baseline chưa kiểm loại này | Viết `lang_check.py` | Điều kiện "chưa kiểm" thực chất chặn kết quả |
| 5 | Điều kiện số năm trượt oan với JD chung chung | Đòi khớp "chủ đề" khi JD không có chủ đề | Tính tổng kinh nghiệm + ghi chú | Cần phân biệt "yêu cầu chung" và "yêu cầu theo lĩnh vực" |
| 6 | Mục từ điển ghi đè nhau | Khoá trùng trong dict | Gộp; chạy `pyflakes` | Công cụ tĩnh bắt được thứ mắt không thấy |
| 7 | Dùng nhầm JD cũ sau khi JD đổi | Bản đã lọc lưu trong session, không gắn với JD gốc | Lưu JD gốc, so sánh | Trạng thái lưu cần gắn với nguồn tạo ra nó |
| 8 | CV có thể thoát khỏi thẻ `<cv>` | Nhúng nội dung không tin cậy vào prompt có thẻ | Loại thẻ đóng/mở | Dữ liệu người dùng luôn phải được làm sạch trước khi nhúng |
| 9 | Ngành AI không khớp yêu cầu "Trí tuệ nhân tạo" | Nhóm ngành tương đương thiếu AI | Thêm AI/ML/Data Science song ngữ | Thử bằng đúng loại hồ sơ mục tiêu, không chỉ dữ liệu tự dựng |
| 10 | Mất tín hiệu GitHub, Git được 0 điểm | Ẩn danh xoá cả loại link | Giữ nhãn loại link, ẩn tên tài khoản | Ẩn thông tin cá nhân không có nghĩa là ẩn mọi tín hiệu nghề nghiệp |
| 11 | JD Việt không khớp CV Anh | Từ điển thiếu cặp song ngữ | Thêm cặp từ Việt-Anh | Tuyển dụng thực tế trộn hai ngôn ngữ |
| 12 | CV nhồi từ khoá được ~57 điểm | Baseline cho tối đa 4 điểm, trái thang 1 = "chỉ nhắc đến" | Chặn tối đa 1 điểm khi chỉ ở danh sách kỹ năng | Code phải nhất quán với định nghĩa thang điểm của chính nó |
| 13 | CV Canva đọc ra gần như trống rồi bị "Loại" | Chữ vẽ thành đường nét; chỉ đếm tổng ký tự nên không thấy thiếu | Đếm từ theo trang, OCR riêng trang thiếu chữ, CV quá ít chữ báo lỗi thay vì chấm 0 | Thử bằng file thật; "đọc được ít chữ" phải thành lỗi, không phải điểm 0 |
| 14 | Từ dính nhau trong PDF thật | pdfplumber bỏ khoảng trắng ở một số font | PyMuPDF làm chính, pdfplumber chỉ làm phương án phụ | Công cụ đọc nào cũng có file làm nó hỏng; cần so sánh trên nhiều file |
| 15 | Link GitHub trong CV bị cụt | PDF hiển thị chữ rút gọn, địa chỉ thật nằm ở chú thích link | Đọc URI từ chú thích link, ghép vào mục "Links" | Thông tin có thể nằm ngoài lớp chữ |
| 16 | JD nêu số năm hai lần bị phạt đôi | Hai câu cùng nghĩa thành hai điều kiện cứng | `_dedupe_years` | Tách yêu cầu từ văn bản tự do luôn sinh trùng lặp |
| 17 | Có thể loại oan vì OCR đọc nhầm số | TOEIC 850 đọc thành 550 | Văn bản OCR không bao giờ gây "trượt điều kiện cứng", chỉ gây "chưa xác minh" | Khi đầu vào kém tin cậy, quyết định không thể đảo ngược phải nhường cho người |
| 18 | "Giao tiếp tiếng Anh tốt" 0 điểm dù CV có TOEIC 850 | Tiêu chí chấm bằng từ khoá, chứng chỉ không chứa từ khoá | Chứng chỉ quy đổi là bằng chứng cho tiêu chí tiếng Anh | Cùng một sự thật có thể nằm ở nhiều dạng; chấm một dạng là bỏ sót |
| 19 | Cùng một CV, chấm khác nhau tùy dấu tiếng Việt viết rời / NBSP | Mọi regex giả định một dạng ký tự; chỉ PDF được chuẩn hoá | `clean_text` ở mọi cửa vào | Hỏi "biến đổi nào không đổi nghĩa mà đổi kết quả?" tìm ra lỗi mà đọc code không thấy |
| 20 | Mỗi lần HR bấm nút mất 2,5 giây ở 600 CV | Ghi lại cả file Excel sau mỗi thao tác | Ghi dữ liệu chính ngay, Excel gom lại | Đo ở quy mô thật; thao tác nhỏ không được trả giá của thao tác lớn |
| 21 | Dòng JD "không yêu cầu kinh nghiệm, biết Python" mất kỹ năng | Phát hiện cụm "không yêu cầu kinh nghiệm" rồi bỏ cả dòng | Chỉ bỏ cụm, giữ phần còn lại | Loại bỏ theo cụm, không theo dòng |
| 22 | Sinh viên đang học được tính là "đã tốt nghiệp" | Chỉ xét có chữ "university" và ngành khớp, không xét thời gian | `education_in_progress` | Điều kiện cứng phải kiểm đúng điều kiện, không phải kiểm một từ gần giống |

---

## 5. Số liệu trước và sau (baseline)

| Thử nghiệm | Trước | Sau |
|---|---|---|
| JD AI, 9 CV `data_ai`: điểm cao nhất | 41,7 (8/9 bị loại) | 76,9 (CV mạnh nhất "Phù hợp") |
| JD fresher AI, CV sinh viên AI thật | 46,1 ("Dự phòng") | 88,5 ("Phù hợp") |
| `data_heldout`: người "Phù hợp" nằm trong danh sách phù hợp | 75% | 100% |
| CV bán hàng nhồi từ khoá AI | 56,9 | 35,8 |
| JD AI: số điều kiện cứng nhận ra | 0 | 3 |
| `data_heldout` Spearman trung bình | 0,93 | 0,93 (không đổi) |
| `data_heldout` đúng 3 mức | 67% | 75% (sau mục 3.13) |
| `data_heldout` đúng 3 mức (sau mục 3.15, 3.16) | 75% | 83% |
| `samples` (JD kỹ sư AI, 9 CV; trước đây là `data_ai`) đúng 3 mức | 44% | 67% (Spearman 0,87) |
| Số test tự động | 0 | 119 |

Lưu ý: toàn bộ số liệu là trên **dữ liệu tác giả tự viết** (khoảng 40 CV). Chưa thể kết luận độ chính xác với CV thật.

---

## 6. Giới hạn (hãy nói thẳng khi được hỏi)
1. **Engine LLM chưa chạy thật** vì chưa có API key: chưa biết `max_tokens`, độ ổn định, tốc độ, chi phí.
2. **Khớp từ khoá** nên dễ bị CV nhồi từ khoá (chỉ được cờ cảnh báo, chưa bị phạt điểm) và không hiểu "tương đương" ngoài từ điển.
3. **Các ngưỡng** (30 điểm, 60% kỹ năng cốt lõi, bảng quy đổi chứng chỉ) **chưa hiệu chỉnh bằng dữ liệu thật**.
4. Điều kiện cứng dùng heuristic có thể **loại nhầm**; nhóm "Loại" cũng nên được HR duyệt nhanh.
5. **OCR**: RapidOCR đã thử trên PDF thật nhưng chậm (~14 giây/trang) và mất dấu tiếng Việt; Tesseract (chính xác hơn với tiếng Việt) chưa thử trên máy này; đường Claude vision gửi ảnh CV ra ngoài nên tắt mặc định. Chữ toàn chữ thường bị dính chưa tách được.
6. Giao diện chưa sẵn sàng cho nhiều người dùng (khoá API dùng chung, mất kết quả khi tải lại, chưa đăng nhập).
7. CV chứa thông tin cá nhân: cần thông báo và có căn cứ pháp lý theo quy định bảo vệ dữ liệu cá nhân trước khi dùng thật.

---

## 7. Câu hỏi phỏng vấn dễ gặp và gợi ý trả lời

- **Vì sao để code tính điểm thay vì để LLM cho điểm tổng?** LLM không nhất quán và khó giải thích. Để LLM chấm từng tiêu chí 0–4 kèm bằng chứng, còn tổng hợp bằng công thức: kết quả tái lập được, kiểm tra được, đổi ngưỡng không cần gọi lại mô hình.
- **Làm sao chống LLM bịa bằng chứng?** Mỗi câu trích dẫn phải có thật trong CV (so khớp sau chuẩn hoá). Không có thì hạ điểm và gắn cờ.
- **CV chèn lệnh vào văn bản thì sao?** Prompt coi CV là dữ liệu; code loại thẻ đóng để CV không thoát vùng dữ liệu; baseline không dùng LLM nên không bị ảnh hưởng nhưng vẫn cảnh báo; CV đó bị đánh dấu cần xem.
- **Làm sao biết hệ thống đúng?** Có bộ đo với nhãn và một bộ giữ lại có định dạng khác. Nhưng đều do tác giả tự viết, nên cần dữ liệu thật của HR trước khi tin các con số.
- **Vì sao không loại ngay ứng viên thiếu chứng chỉ TOEIC?** Họ có thể có mà không ghi. Loại nhầm tệ hơn bắt người xem. Nên trạng thái là "chưa rõ".
- **Lỗi khó nhất đã gặp?** Lỗi regex tháng: im lặng, sai ở nhiều nơi, chỉ lộ ra khi soi từng điều kiện. Cách phát hiện là xem lại từng bước trung gian thay vì chỉ nhìn điểm cuối.
- **Điều gì cải thiện nhiều nhất nếu có thêm thời gian?** Thu CV thật đã ẩn danh kèm nhãn của HR để hiệu chỉnh; chạy engine LLM và so với baseline.

---

## 8. Cách chạy lại và tự kiểm chứng

```bash
pip install -r requirements.txt
python -m unittest discover -s tests            # 119 test
python eval.py --engine baseline --data data_heldout        # kỳ vọng đúng 3 mức 83%, Spearman 0.93
python run.py rubric samples/jds/ai01.txt -o rubrics/ai01.json --engine baseline
python run.py score rubrics/ai01.json samples/cvs_pdf -o ranking.csv --excel ketqua.xlsx --engine baseline
python serve.py                                  # giao diện web
```

Đặt `CV_AGENT_AS_OF=2026-10` để số năm kinh nghiệm tái lập được.
