"""Mọi hằng số chỉnh được của hệ thống nằm ở đây, để biết chỉnh ở đâu thay vì tìm rải rác trong nhiều file.

Các ngưỡng điểm là điểm khởi đầu hợp lý, CHƯA được hiệu chỉnh bằng CV thật của HR (xem calibrate.py).
"""
import os

# ---- Ngưỡng kết luận (thang 0-100)
FIT_THRESHOLD = 70       # từ mức này và đủ điều kiện -> "Phù hợp - Mời phỏng vấn"
MAYBE_THRESHOLD = 50     # từ mức này -> "Có thể mời phỏng vấn"
REJECT_THRESHOLD = 30    # dưới mức này -> "Loại"
CORE_MIN = 0.6           # đạt dưới 60% kỹ năng bắt buộc -> tối đa "Dự phòng", dù tổng điểm cao
CORE_MIN_ITEMS = 3       # chỉ áp quy tắc trên khi JD có từ 3 kỹ năng bắt buộc trở lên (1-2 mục thì tỉ lệ quá nhiễu)

# Mức độ chọn lọc dựng sẵn cho giao diện: (phù hợp, có thể mời, loại)
PRESETS = {"Nghiêm ngặt": (80, 60, 40), "Cân bằng": (FIT_THRESHOLD, MAYBE_THRESHOLD, REJECT_THRESHOLD), "Rộng rãi": (60, 40, 20)}

# ---- Chấm bằng luật (baseline)
SCORE_CUTS = (0.15, 0.35, 0.55, 0.75)    # độ phủ từ khoá -> điểm 0..4
SECTION_FACTOR = {"exp": 1.0, "project": 0.9, "cert": 0.9, "other": 0.7, "skills": 0.7, "edu": 0.6, "summary": 0.4}
WEIGHT_REQUIRED, WEIGHT_PREFERRED, WEIGHT_YEARS = 1.0, 0.4, 1.5
INTERN_FACTOR = 0.5       # thực tập chỉ tính một nửa thời gian
REL_THRESHOLD = 0.6       # khối kinh nghiệm được tính là "liên quan" khi độ phủ chủ đề >= ngưỡng này

# ---- Đọc file
MIN_PDF_CHARS = 100       # PDF có ít chữ hơn mức này coi là bản scan -> OCR
MAX_PDF_PAGES = 12        # CV hợp lệ hiếm khi dài hơn; tránh file khổng lồ làm treo
MAX_FILE_MB = 25
MAX_TEXT_CHARS = 150_000  # CV dài hơn mức này gần như chắc chắn là file lỗi; cắt bớt để không treo
MIN_WORDS_PER_PAGE = 60   # trang có ít từ hơn mức này bị coi là thiếu chữ (ảnh / chữ vẽ thành đường nét)
PDF_SPARSE_TOTAL_WORDS = 250  # chỉ OCR bổ sung khi cả file có ít từ hơn mức này
OCR_MAX_PAGES = 4
OCR_DPI = 150

# ---- LLM (TẮT mặc định; hệ thống chạy đầy đủ không cần LLM)
LLM_ENABLED = os.getenv("CV_AGENT_ENABLE_LLM", "").lower() in ("1", "true", "yes")
