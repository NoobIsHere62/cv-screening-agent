"""Thông tin nhanh trích từ CV GỐC cho HR (tên, liên hệ, GPA, ngoại ngữ, GitHub, số năm kinh nghiệm).

Chỉ dùng để HIỂN THỊ trong báo cáo, không bao giờ đưa vào bước chấm điểm (bước chấm dùng văn bản đã ẩn danh).
"""
import re

from .anonymize import EMAIL, PHONE
from .cv_parse import effective_months, normalize_dates, parse_blocks, split_cv
from .identity import find_name
from .lang_check import best_certificate
from .textutil import clean_text

_GPA = re.compile(r"(?:\bc?gpa\b|[đd](?:iể|ie)m\s*trung\s*b[ìi]nh|\b[đd]tb\b|\b[đd]tbtl\b)[^\d\n]{0,15}(\d{1,3}(?:[.,]\d{1,2})?)\s*(?:/\s*(\d{1,3}(?:[.,]\d)?))?",
                  re.I)
_GITHUB = re.compile(r"(?:https?://)?(?:www\.)?github\.com/[\w.\-]+", re.I)


def _gpa(raw: str) -> str:
    m = _GPA.search(raw)
    if not m:
        return ""
    value = float(m.group(1).replace(",", "."))
    scale = float(m.group(2).replace(",", ".")) if m.group(2) else (4.0 if value <= 4.3 else 10.0)
    if not 0 < value <= scale or scale not in (4.0, 10.0, 5.0, 100.0):
        return ""
    return f"{value:g}/{scale:g}"


def _fix_ocr_email(addr: str) -> str:
    """OCR hay đọc nhầm số 0 / chữ o ở đuôi email: "example.c0m" -> "example.com"."""
    return re.sub(r"\.c[0O]m$", ".com", re.sub(r"\.c[0O]\.vn$", ".co.vn", addr, flags=re.I), flags=re.I)


def extract_facts(raw: str, filename: str = "", ocr: bool = False) -> dict:
    raw = clean_text(raw)
    name = find_name(raw, filename, ocr)
    email = EMAIL.search(raw)
    phone = PHONE.search(raw)
    github = max(_GITHUB.finditer(raw), key=lambda m: len(m.group(0)), default=None)     # link đầy đủ trong PDF dài hơn bản bị ngắt dòng
    cert, _ = best_certificate(raw)
    try:
        blocks = parse_blocks(split_cv(normalize_dates(raw)))
        years = round(effective_months(blocks) / 12.0, 1) if blocks else None
    except Exception:                                    # thông tin phụ, lỗi ở đây không được làm hỏng việc chấm
        years = None
    return {
        "candidate_name": name.value,
        "name_source": name.source,                     # label/cv: đọc từ CV; file/email/ocr: suy ra hoặc OCR, cần xác nhận
        "email": _fix_ocr_email(email.group(0)) if email and ocr else (email.group(0) if email else ""),
        "phone": re.sub(r"\s+", " ", phone.group(0)).strip() if phone else "",
        "gpa": _gpa(raw),
        "english": cert,
        "github": github.group(0) if github else "",
        "total_years": years,
    }
