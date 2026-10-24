import re
import sys
import unicodedata

# Mã điểm Unicode viết bằng số (không viết thẳng ký tự vô hình vào mã nguồn: không nhìn thấy, khó sửa, dễ bị công cụ làm mất)
_ZERO_WIDTH = dict.fromkeys([0x200B, 0x200C, 0x200D, 0xFEFF, 0x2060, 0x00AD], None)     # rộng bằng 0, BOM, word joiner, soft hyphen
# Các loại khoảng trắng "lạ" hay gặp khi copy từ Word/web/PDF: NBSP, ogham, các khoảng en/em/mảnh, khoảng hẹp, khoảng toán, khoảng ideographic
_ODD_SPACES = dict.fromkeys([0x00A0, 0x1680, *range(0x2000, 0x200B), 0x202F, 0x205F, 0x3000], " ")
_LINE_BREAKS = dict.fromkeys([0x2028, 0x2029, 0x0B, 0x0C], "\n")                       # dấu ngắt dòng/đoạn Unicode, VT, FF
_CONTROL = re.compile(r"[\x00-\x08\x0e-\x1f\x7f]")                                    # ký tự điều khiển (giữ \t \n \r)


def safe_console() -> None:
    """Tiếng Việt in ra console/tệp dùng bảng mã cũ (cp1252, cp437) sẽ ném UnicodeEncodeError và làm sập chương trình giữa chừng.
    Chữ không in được thì thay bằng "?" thay vì lỗi."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):                 # luồng đã bị thay thế (IDE, test)
            pass


def norm(s: str) -> str:
    """Chuẩn hoá để so khớp trích dẫn: NFC, bỏ ký tự vô hình, bỏ dấu câu/bullet, thường hoá.
    Hai chuỗi chỉ khác dấu gạch đầu dòng, xuống dòng, kiểu gõ dấu tiếng Việt thì vẫn khớp."""
    s = unicodedata.normalize("NFC", s).translate(_ZERO_WIDTH).lower()
    s = re.sub(r"[^\w]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def clean_text(text: str) -> str:
    """Đưa văn bản CV/JD về dạng chuẩn trước khi phân tích, để cùng một nội dung luôn cho cùng một kết quả:
    NFC (dấu tiếng Việt rời "a" + dấu nặng thành "ạ"), khoảng trắng lạ (NBSP...) thành dấu cách, xuống dòng CRLF / CR thành LF,
    bỏ ký tự vô hình và ký tự điều khiển. Không đụng tới chữ hoa/thường hay dấu câu."""
    text = unicodedata.normalize("NFC", text).translate(_ZERO_WIDTH).translate(_ODD_SPACES)
    text = text.replace("\r\n", "\n").replace("\r", "\n").translate(_LINE_BREAKS)
    return _CONTROL.sub("", text)


def quote_in(quote: str, source_norm: str, min_len: int = 3) -> bool:
    q = norm(quote)
    return len(q) >= min_len and q in source_norm
