import re
from typing import Iterable

from .identity import find_name
from .textutil import clean_text

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
LINK = re.compile(r"(?:https?://|www\.)\S+|(?:linkedin|facebook|github|zalo|twitter|instagram)\.\S+", re.I)

_PORTFOLIO = re.compile(r"github|gitlab|bitbucket|kaggle|huggingface", re.I)


def _link_label(m: re.Match) -> str:
    """Ẩn đường link nhưng giữ lại LOẠI link: GitHub/Kaggle là bằng chứng nghề nghiệp, tên tài khoản mới là thứ cần ẩn."""
    p = _PORTFOLIO.search(m.group(0))
    return f"[LINK {p.group(0).lower()}]" if p else "[LINK]"


# SĐT Việt Nam: 0912 345 678, 0912345678, +84 912 345 678, (+84) 912-345-678
# Không bắt "2019 - 2022", "1.500.000.000" (trước đây bị thay nhầm thành [PHONE]).
PHONE = re.compile(
    r"(?<![\d.,/])(?:(?:\(?\+?84\)?[\s.\-]?(?:\(0\))?|0)[\s.\-]?\d{2,3}[\s.\-]?\d{3}[\s.\-]?\d{3,4}"      # di động, +84 (0)912...
    r"|0\d{1,2}[\s.\-]?\d{4}[\s.\-]?\d{4})(?![\d.,/])"                                                 # máy bàn: 024 3825 1234
)

# Thông tin dễ gây thiên kiến (và không liên quan năng lực): ẩn cả dòng khi nó mở đầu bằng khoá này
_KEYS = (r"họ\s*(?:và|&)?\s*tên|full\s*name|name|ngày\s*sinh|date\s*of\s*birth|dob|birthday|giới\s*tính|gender|sex|"
         r"tình\s*trạng\s*hôn\s*nhân|marital\s*status|tuổi|age|quê\s*quán|nơi\s*sinh|place\s*of\s*birth|"
         r"quốc\s*tịch|nationality|tôn\s*giáo|religion|chiều\s*cao|cân\s*nặng|height|weight|địa\s*chỉ|address")
PII_LINE = re.compile(rf"^[ \t]*(?:{_KEYS})[ \t]*[:：].*$", re.I | re.M)
# Cùng khoá nằm giữa dòng ("... | Giới tính: Nữ | ..."), bỏ "name" vì dễ trùng "Company name:"
_KEYS_INLINE = _KEYS.replace("|name|", "|").replace("full\\s*name|", "full\\s*name|")
PII_INLINE = re.compile(rf"(?<![\w])(?:{_KEYS_INLINE})[ \t]*[:：][ \t]*[^|;\n]{{1,60}}", re.I)

def _name_pattern(words: list[str]) -> re.Pattern:
    return re.compile(r"(?<!\w)" + r"\s+".join(re.escape(w) for w in words) + r"(?!\w)", re.I)


def _hide_name(text: str) -> str:
    """Ẩn tên ứng viên dù nó nằm dưới "CURRICULUM VITAE", chức danh hay chữ khác (trước đây chỉ xét dòng đầu tiên)."""
    name = find_name(text)
    if name.source not in ("cv", "label"):
        name = find_name(text, ocr=True)                    # bản OCR: tên bị dính chữ ("NGUYENHOANGNAM")
    if not name or name.source not in ("cv", "label", "ocr") or name.line is None:
        return text
    pat = _name_pattern(name.value.split())
    lines = text.split("\n")
    if name.line is not None and name.line < len(lines):
        lines[name.line] = pat.sub("[NAME]", lines[name.line])
        if "[NAME]" not in lines[name.line]:               # tên viết hoa/khác dấu so với bản chuẩn hoá: thay cả đoạn khớp chữ cái
            lines[name.line] = "[NAME]"
    if len(re.sub(r"\W", "", name.value)) < 4:             # tên quá ngắn ("A"): thay khắp CV sẽ ẩn nhầm mạo từ "a", chữ cái đơn...
        return "\n".join(lines)
    return pat.sub("[NAME]", "\n".join(lines))


def anonymize(text: str, names: Iterable[str] = ()) -> str:
    """Ẩn thông tin liên lạc và thông tin dễ gây thiên kiến trước khi chấm CV.

    names: tên ứng viên nếu đã biết (vd lấy từ tên file / form), thay bằng [NAME] ở mọi chỗ xuất hiện.
    Ngoài ra dòng đầu tiên trông giống họ tên cũng bị ẩn. Regex không đoán được hết mọi kiểu tên, nên nếu có
    tên chính xác, hãy truyền vào `names`.
    """
    text = _hide_name(clean_text(text))                     # trước khi ẩn email: email giúp xác nhận đúng dòng tên
    text = EMAIL.sub("[EMAIL]", text)
    text = LINK.sub(_link_label, text)
    text = PHONE.sub("[PHONE]", text)
    text = PII_LINE.sub("[REDACTED]", text)
    text = PII_INLINE.sub("[REDACTED]", text)
    for n in names:
        if n and n.strip():
            text = re.sub(re.escape(n.strip()), "[NAME]", text, flags=re.I)
    return text
