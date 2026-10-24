"""Tìm TÊN ứng viên trong CV (kể cả khi phía trên có chữ khác như "CURRICULUM VITAE", chức danh, slogan, hoặc khi CV là bản OCR).

Dùng ở hai nơi: hiển thị tên cho HR (facts.py) và tìm đúng dòng chứa tên để ẩn khi chấm (anonymize.py).

Cách làm: thử theo thứ tự tin cậy giảm dần
  1. dòng có nhãn: "Họ và tên: ...", "Full name: ...";
  2. trong 15 dòng đầu, dòng/đoạn trông giống tên người nhất (chấm điểm: họ Việt phổ biến, viết hoa đúng kiểu, nằm gần đầu,
     trùng với phần trước @ của email...). Bỏ qua tiêu đề chung (CV, Resume...), chức danh, tên mục, địa danh, dòng có số/email/link;
  3. tên trong tên file ("nguyen-hoang-nam.pdf");
  4. tên suy ra từ email ("quan.le.demo@..." -> "Quan Le").
Với CV bản OCR, tên đọc từ chữ hay sai ("Men Minhn Quaneer") nên chỉ tin khi có dấu hiệu xác nhận (họ Việt, trùng email/tên file);
nếu không thì ưu tiên tên file/email và báo `source` để HR kiểm tra.
"""
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from .textutil import clean_text

_SURNAMES = """nguyễn trần lê phạm hoàng huỳnh phan vũ võ đặng bùi đỗ hồ ngô dương lý đinh đoàn lâm mai trịnh tô tạ châu cao hà
lương kiều thái quách tăng từ trương la diệp phùng chu giang khúc lại lục mạc nghiêm ninh ông quản tiêu tôn văn vương xa
nguyen tran le pham hoang huynh phan vu vo dang bui do ho ngo duong ly dinh doan lam mai trinh to ta chau cao ha
luong kieu thai quach tang tu truong la diep phung chu giang khuc lai luc mac nghiem ninh ong quan tieu ton van vuong""".split()

# Từ ĐƠN (tiếng Anh) khiến một cụm chữ KHÔNG phải tên người: tiêu đề chung, tên mục, chức danh, tổ chức.
# Cụm tiếng Việt nằm ở _NOT_NAME_PHRASES (khớp theo cả cụm), vì khi bỏ dấu nhiều âm tiết trùng tên người ("học vấn" ~ "Văn", "quận" ~ "Quân").
_NOT_NAME_WORDS = """curriculum vitae resume cv profile contact summary objective experience education skills projects project languages
language certifications certificate certificates interests hobbies references awards activities personal information details
about me work history employment professional technical core key strengths achievements publications volunteer training courses
engineer developer designer manager analyst intern internship executive specialist consultant officer assistant director lead senior junior
fresher scientist architect administrator accountant marketing sales student graduate technician tester programmer
machine learning data science artificial intelligence software backend frontend fullstack mobile web cloud devops
university college school institute academy company corporation jsc ltd inc co bank group
ai ml it hr qa ui ux bi ceo cto cfo coo hcm tp
hanoi saigon city vietnam danang""".split()
_NOT_NAME_PHRASES = tuple(
    " ".join(p.split()) for p in """sơ yếu lý lịch|hồ sơ xin việc|hồ sơ ứng tuyển|hồ sơ cá nhân|thông tin cá nhân|liên hệ|mục tiêu nghề nghiệp|mục tiêu
kinh nghiệm|học vấn|kỹ năng|dự án|chứng chỉ|sở thích|giới thiệu bản thân|tóm tắt|kỹ sư|lập trình viên|nhân viên|chuyên viên|giám đốc
trưởng phòng|thực tập sinh|sinh viên|đại học|cao đẳng|trường đại học|công ty|tập đoàn|ngân hàng|thành phố""".replace("\n", "|").split("|"))
# Địa danh nhiều từ: không thể liệt kê từng từ vì "Minh", "Nam", "Hà" cũng là tên người; khớp theo cả cụm
_PLACE_PHRASES = ("ho chi minh", "ha noi", "da nang", "can tho", "hai phong", "binh duong", "dong nai", "viet nam", "ba ria",
                  "vung tau", "nha trang", "bac ninh", "thua thien", "quang ninh", "tp hcm", "tp ho chi minh")
_BOILERPLATE_PREFIX = re.compile(
    r"^(?:curriculum\s+vitae|resume|c\.?v\.?|sơ\s+yếu\s+lý\s+lịch|hồ\s+sơ\s+(?:xin\s+việc|ứng\s+tuyển|cá\s+nhân)|"
    r"personal\s+(?:information|details|profile)|profile|application|đơn\s+xin\s+việc)\s*(?:of|for|của|[:\-–—|])\s*", re.I)
_LABELED = re.compile(
    r"^[ \t]*(?:họ\s*(?:và|&)?\s*tên(?:\s*ứng\s*viên)?|tên(?:\s*ứng\s*viên)?|full\s*name|candidate(?:\s*name)?|name)[ \t]*[:：][ \t]*(.+)$",
    re.I | re.M)
_SEPARATORS = re.compile(r"\s*[|•·●▪◆►»/\\]\s*|\s+[–—-]\s+")
_WORD = re.compile(r"^[^\W\d_](?:[^\W\d_]|['’.-])*$")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_FILE_NOISE = {"cv", "resume", "final", "new", "copy", "docx", "pdf", "fresher", "intern", "dev", "developer", "engineer", "ai", "hoso"}
_FILE_PHRASES = re.compile(r"(?:ho[\s_\-]*so|hồ[\s_\-]*sơ|ung[\s_\-]*vien|ứng[\s_\-]*viên|curriculum[\s_\-]*vitae)", re.I)
_EMAIL_NOISE = {"demo", "mail", "gmail", "email", "cv", "hr", "work", "job", "dev", "test", "info", "contact", "admin", "hotmail",
                "outlook", "yahoo", "student", "official", "vn", "com"}


@lru_cache(maxsize=1 << 16)
def fold(s: str) -> str:
    """Chữ thường, bỏ dấu tiếng Việt. Được gọi hàng trăm nghìn lần cho mỗi lô CV với vài nghìn từ khác nhau nên được nhớ lại."""
    s = unicodedata.normalize("NFD", unicodedata.normalize("NFC", s).lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn").replace("đ", "d")


_NOT_NAME = {fold(w) for w in _NOT_NAME_WORDS}
_SURNAME_SET = {fold(w) for w in _SURNAMES}


# Âm tiết thường gặp trong họ/tên đệm/tên Việt (không dấu), dùng để tách chữ OCR bị dính: "NGUYENHOANGNAM" -> Nguyen Hoang Nam
_GIVEN = """van thi minh quoc bao hai thanh tuan anh huy khoa nam lan huong linh phuong trang thuy thu hoa hanh yen ngoc kim mai nhi
nhung diem diep duc dung dat dang duy gia hieu hoang hung hien hien hoai khanh khang kiet lam long loc luan manh nghia nguyen nhan
phat phuc phong quan quang quyen quynh son tai tam tan thai thang thao thien thinh tien toan trinh trung truong tu tung uyen vinh
vu xuan yen an binh chi cuong cong dinh dong giang ha hanh hieu hoan hue hung kha khoi lien loan my nga nghi ngan nhat oanh phi
sang sinh tho thuc tri trieu viet vien bich cam chau dao dieu dinh gam hang hoai huyen khue kieu lieu nguyet nhu oanh phuoc thi thy
trinh tuyet vy xuyen yen""".split()
_COMMON_SYLLABLES = set(_GIVEN)


def _split_glued(token: str) -> Optional[list[str]]:
    """Tách một chuỗi chữ dính liền thành 2-5 âm tiết tên Việt (không dấu) nếu có cách tách hợp lý, bắt đầu bằng một họ."""
    from .nlp import is_vn_syllable_ascii
    s = fold(token)
    if not s.isalpha() or not 6 <= len(s) <= 24:
        return None
    common = _COMMON_SYLLABLES | _SURNAME_SET
    best: list[Optional[tuple[float, list[str]]]] = [None] * (len(s) + 1)
    best[0] = (0.0, [])
    for i in range(1, len(s) + 1):
        for j in range(max(0, i - 7), i - 1):                # âm tiết 2-7 chữ cái
            if best[j] is None:
                continue
            syl = s[j:i]
            if syl in common:
                w = 0.9 * len(syl)                           # tỉ lệ theo độ dài: "tuan" thắng "tu"+"an"
            elif is_vn_syllable_ascii(syl):
                w = 0.3 * len(syl)
            else:
                continue
            cand = (best[j][0] + w - 1.0, best[j][1] + [syl])
            if best[i] is None or cand[0] > best[i][0]:
                best[i] = cand
    if best[-1] is None:
        return None
    parts = best[-1][1]
    if not 2 <= len(parts) <= 5 or parts[0] not in _SURNAME_SET:
        return None
    if sum(p in common for p in parts) < len(parts) - 1:     # nhiều âm tiết lạ: có lẽ không phải tên người
        return None
    return parts


@dataclass(frozen=True)          # bất biến: find_name được nhớ lại, nên nhiều nơi dùng chung cùng một đối tượng
class Name:
    value: str = ""
    line: Optional[int] = None        # chỉ số dòng (theo splitlines của văn bản gốc) nếu tên nằm trong CV
    source: str = ""                  # label | cv | file | email | ocr (đọc từ OCR, chưa xác nhận)
    confident: bool = False

    def __bool__(self) -> bool:
        return bool(self.value)


def _title_case(words: list[str]) -> str:
    out = []
    for w in words:
        w = w.strip(".,;:")
        out.append(w if not w.isupper() or len(w) == 1 else w[:1] + w[1:].lower())
    return " ".join(out)


def _email_tokens(text: str) -> list[str]:
    m = _EMAIL.search(text)
    if not m:
        return []
    local = re.sub(r"\d+", " ", m.group(0).split("@")[0])
    return [t for t in re.split(r"[._\-+\s]+", fold(local)) if len(t) >= 2 and t not in _EMAIL_NOISE]


_TITLE_PREFIX = re.compile(r"^(?:mr|mrs|ms|miss|dr|prof|ths|th\.s|ts|pgs|gs|eng)\.?\s+", re.I)      # danh xưng/học hàm, không phải một phần của tên


def _plausible_words(segment: str) -> Optional[list[str]]:
    """Các từ của đoạn nếu nó có hình dạng của tên người (2-5 từ chữ cái, viết hoa đồng nhất, không chứa từ không phải tên)."""
    seg = _TITLE_PREFIX.sub("", _BOILERPLATE_PREFIX.sub("", segment.strip()))
    if not seg or re.search(r"[\d@:/]|www\.|http", seg) or len(seg) > 45:
        return None
    words = seg.split()
    if not 2 <= len(words) <= 5 or not all(_WORD.match(w) for w in words):
        return None
    if any(fold(w).strip(".") in _NOT_NAME for w in words):
        return None
    joined = " ".join(fold(w).strip(".") for w in words)
    if any(p in joined for p in _PLACE_PHRASES):
        return None
    lowered = " ".join(unicodedata.normalize("NFC", w).lower().strip(".") for w in words)
    if any(re.search(rf"(?<!\w){re.escape(p)}(?!\w)", lowered) for p in _NOT_NAME_PHRASES):
        return None
    letters = [w for w in words if len(w.strip(".")) > 1]
    if all(w.isupper() for w in letters):
        return words                                         # NGUYỄN HOÀNG TUẤN
    if all(w[0].isupper() for w in words):
        return words                                         # Nguyễn Hoàng Tuấn
    return None


def _score(words: list[str], line_no: int, email_tokens: list[str]) -> int:
    folded = [fold(w).strip(".") for w in words]
    score = 1
    if folded[0] in _SURNAME_SET or folded[-1] in _SURNAME_SET:
        score += 3                                           # họ Việt phổ biến
    if any(t in folded for t in email_tokens):
        score += 3                                           # trùng phần trước @ của email
    if line_no <= 2:
        score += 2
    elif line_no <= 5:
        score += 1
    if len(words) == 2 and score == 1:
        score -= 1                                           # hai từ Title Case không có dấu hiệu nào khác: dễ là cụm danh từ
    return score


def _from_filename(filename: str) -> str:
    stem = re.sub(r"\.[A-Za-z0-9]{2,4}$", "", filename or "")
    stem = _FILE_PHRASES.sub(" ", stem)                       # "ho-so" = hồ sơ, không phải họ Hồ
    stem = re.sub(r"(?<=[a-zà-ỹ])(?=[A-ZÀ-Ỹ])", " ", stem)    # CamelCase: "CV_TranMinhKhoa_JavaBackend" -> "Tran Minh Khoa Java Backend"
    words = [w for w in re.split(r"[\s_\-.()+]+", stem) if w and not w.isdigit() and w.isalpha()]
    words = [w for w in words if fold(w) not in _FILE_NOISE]
    # tên người = đoạn từ liền nhau ở đầu (trước khi gặp chức danh/công nghệ như Java, Backend, Developer)
    run = []
    for w in words:
        f = fold(w)
        if f in _NOT_NAME or f in _TECH_WORDS:
            if run:
                break
            continue
        run.append(w)
    if 2 <= len(run) <= 5:
        return _title_case([w.capitalize() for w in run])
    return ""


def _from_email(text: str) -> str:
    toks = _email_tokens(text)
    local = _EMAIL.search(text)
    if local and len(toks) >= 2:
        return _title_case([t.capitalize() for t in toks[:4]])
    return ""


def _expand_glued(seg: str) -> str:
    """OCR hay làm dính chữ và mất dấu: "NGUYENHOANGNAM" -> "Nguyen Hoang Nam"."""
    out = []
    for tok in seg.split():
        parts = _split_glued(tok) if len(tok) >= 6 and tok.isalpha() else None
        out += [p.capitalize() for p in parts] if parts else [tok]
    return " ".join(out)


_FILLER = {"of", "the", "at", "and", "in", "for", "to", "a", "an", "-", "&"}
_TECH_WORDS = {"java", "python", "javascript", "typescript", "net", "php", "react", "reactjs", "node", "nodejs", "golang", "go", "mobile", "ios",
               "android", "tester", "qa", "be", "fe", "ba", "pm", "analyst", "devops", "spring", "angular", "vue", "sql", "ml", "nlp", "ui", "ux"}


def _windows(seg: str, ocr: bool):
    """Nhiều CV (nhất là OCR) để tên cùng dòng với chức danh: "NGUYỄN HOÀNG TUẤN AI Engineer". Thử các cụm 2-4 từ liên tiếp,
    CHỈ khi mọi từ còn lại trên dòng đều là chức danh/viết tắt/từ nối (nếu không, "Industrial University Of Ho Chi" sẽ cho ra "Ho Chi")."""
    if ocr:
        seg = re.sub(r"(?<=[a-zà-ỹ])(?=[A-ZÀ-Ỹ])", " ", seg)          # OCR dính chữ: "NguyenVanAn"
    words = seg.split()
    for size in (4, 3, 2):
        for i in range(0, len(words) - size + 1):
            others = words[:i] + words[i + size:]
            if all(fold(w).strip(".") in _NOT_NAME or fold(w).strip(".") in _FILLER or fold(w).strip(".") in _TECH_WORDS for w in others):
                yield words[i:i + size]


@lru_cache(maxsize=32)           # mỗi CV được hỏi tên 2-3 lần (hiển thị, ẩn danh khi chấm, thử lại với OCR): chỉ tính một lần
def find_name(text: str, filename: str = "", ocr: bool = False, max_lines: int = 25) -> Name:
    """Tìm tên ứng viên. `text` là văn bản CV GỐC (chưa ẩn danh). Trả về Name rỗng nếu không tìm được."""
    lines = clean_text(text).splitlines()
    m = _LABELED.search("\n".join(lines[:60]))
    if m:
        words = [w for w in re.split(r"\s+", re.split(r"[|•(,]", m.group(1))[0].strip()) if w]
        if 1 <= len(words) <= 6 and not re.search(r"\d|@", " ".join(words)):
            for idx, ln in enumerate(lines):
                if ln.strip() == m.group(0).strip():
                    return Name(_title_case(words), idx, "label", True)
            return Name(_title_case(words), None, "label", True)

    email_tokens = _email_tokens(text)
    best: Optional[tuple[int, int, str]] = None             # (điểm, -thứ tự, tên) và chỉ số dòng
    best_line = None
    seen_nonempty = 0
    for idx, raw in enumerate(lines):
        if not raw.strip():
            continue
        seen_nonempty += 1
        if seen_nonempty > max_lines:
            break
        segments = [_expand_glued(s) if ocr else s for s in _SEPARATORS.split(raw) if s.strip()]
        for seg in segments:
            candidates = []
            words = _plausible_words(seg)
            if words:
                candidates.append(words)
            elif any(fold(w).strip(".") in _NOT_NAME for w in seg.split()):
                # tên nằm lẫn với chức danh/viết tắt trên cùng dòng ("NGUYỄN HOÀNG TUẤN AI Engineer"): thử các cụm con, chỉ nhận khi có dấu hiệu rõ.
                # Không thử với tiêu đề/địa danh thuần tiếng Việt ("Sơ yếu lý lịch", "Hồ Chí Minh"), vì cụm con của chúng giống tên người.
                for win in _windows(seg, ocr):
                    w = _plausible_words(" ".join(win))
                    if w and _score(w, 99, email_tokens) >= 4:
                        candidates.append(w)
            for words in candidates:
                sc = _score(words, seen_nonempty, email_tokens)
                key = (sc, -seen_nonempty)
                if best is None or key > best[:2]:
                    best, best_line = (sc, -seen_nonempty, _title_case(words)), idx

    file_name = _from_filename(filename)
    email_name = _from_email(text)
    if best is not None:
        score, _, value = best
        confirmed = score >= 4                               # có họ Việt / trùng email / nằm ngay đầu CV
        if not ocr:
            return Name(value, best_line, "cv", confirmed)
        known = set(email_tokens) | set(fold(file_name).split()) | set(fold(email_name).split())
        if confirmed:
            agrees = bool(known) and all(fold(w) in known for w in value.split())     # trùng tên file/email: tin được
            return Name(value, best_line, "cv" if agrees else "ocr", True)
        # CV OCR mà tên không được xác nhận: tên file hoặc email đáng tin hơn chữ OCR
        if file_name:
            return Name(file_name, None, "file", False)
        if email_name:
            return Name(email_name, None, "email", False)
        return Name(value, best_line, "ocr", False)
    if file_name:
        return Name(file_name, None, "file", False)
    if email_name:
        return Name(email_name, None, "email", False)
    return Name()
