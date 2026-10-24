"""Phân tích CV bằng luật: tách mục, đọc khoảng thời gian làm việc, kiểm tra điều kiện cứng."""
import os
import re
from datetime import date
from functools import lru_cache
from typing import Optional

from . import lexicon as L
from .config import INTERN_FACTOR, REL_THRESHOLD
from .jd_rules import _is_bullet, is_generic_years, parse_min_years, years_topic
from .nlp import both, coverage, flat_tokens, index_line, nfc, query_units
from .schemas import HardCheck


# ------------------------------------------------------------------ mốc "nay"
def as_of_date() -> tuple[int, int]:
    v = (os.getenv("CV_AGENT_AS_OF") or "").strip()      # YYYY-MM, để kết quả tái lập được
    m = re.fullmatch(r"(\d{4})-(\d{1,2})", v)
    if m and 1 <= int(m.group(2)) <= 12:
        return int(m.group(1)), int(m.group(2))
    t = date.today()                                     # biến môi trường trống hoặc sai định dạng: dùng ngày hôm nay
    return t.year, t.month


# ------------------------------------------------------------------ chuẩn hoá ngày tháng
MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
# Chỉ tên tháng đầy đủ hoặc viết tắt chuẩn; trước đây "[a-z]*" khiến "Marketing 2016", "Junior 2021" bị đọc thành ngày tháng
_MONTH_RE = re.compile(r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|"
                       r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b\.?,?\s+(\d{4})\b", re.I)
_VN_MONTH_RE = re.compile(r"\b(?:tháng|thang|th|t)\s*(\d{1,2})\s*[/,.]?\s*(\d{4})\b", re.I)
_DMY_RE = re.compile(r"\b\d{1,2}[/.\-](\d{1,2})[/.\-](\d{4})\b")
_MY_RE = re.compile(r"\b(0?[1-9]|1[0-2])[-.](\d{4})\b")


def normalize_dates(text: str) -> str:
    """dd/mm/yyyy, 'Jan 2021', 'Tháng 3/2021', '03-2021' -> 'mm/yyyy' để DATE_RE đọc được."""
    text = _DMY_RE.sub(lambda m: f"{int(m.group(1)):02d}/{m.group(2)}", text)
    text = _MONTH_RE.sub(lambda m: f"{MONTHS[m.group(1).lower()[:3]]:02d}/{m.group(2)}", text)
    text = _VN_MONTH_RE.sub(lambda m: f"{int(m.group(1)):02d}/{m.group(2)}", text)
    return _MY_RE.sub(lambda m: f"{int(m.group(1)):02d}/{m.group(2)}", text)


_SEP = rf"\s*(?:[-–—~]|(?:{both(['đến', 'tới', 'to', 'until', 'till'])})\b)\s*"
_NOW = both(["nay", "hiện tại", "hiện nay", "present", "current", "now", "ongoing"])
DATE_RE = re.compile(
    rf"(?:(?P<sm>\d{{1,2}})\s*/\s*)?(?P<sy>\d{{4}}){_SEP}"
    rf"(?:(?:(?P<em>\d{{1,2}})\s*/\s*)?(?P<ey>\d{{4}})|(?:(?:{both(['đến', 'until'])})\s*)?(?P<now>{_NOW})\b)", re.I)


def parse_interval(m: re.Match, as_of: tuple[int, int]) -> Optional[tuple[int, int]]:
    """Khoảng nửa mở [s, e) tính bằng tháng kể từ năm 0; None nếu không hợp lý."""
    ay, am = as_of
    sy, sm = int(m["sy"]), int(m["sm"]) if m["sm"] else None
    if sm is not None and not 1 <= sm <= 12:
        return None
    if not 1970 <= sy <= ay + 1:
        return None
    s = sy * 12 + (sm or 1)
    if m["now"]:
        e = ay * 12 + am + 1
    else:
        ey, em = int(m["ey"]), int(m["em"]) if m["em"] else None
        if (em is not None and not 1 <= em <= 12) or not sy <= ey <= ay + 1:
            return None
        if em is not None:
            e = ey * 12 + em + 1
        elif sm is not None:
            e = ey * 12 + sm                       # "03/2020 - 2022": hết tháng 3/2022
        else:
            e = s + max((ey - sy) * 12, 6)         # "2020 - 2022": hai năm, tối thiểu 6 tháng
    return (s, e) if e > s else None


# ------------------------------------------------------------------ tách mục
HEADERS = {
    "exp": ["kinh nghiệm làm việc", "kinh nghiệm", "work experience", "professional experience", "employment history",
            "work history", "experience", "quá trình làm việc", "quá trình công tác"],
    "edu": ["học vấn", "trình độ học vấn", "education", "academic background", "quá trình học tập", "bằng cấp"],
    "skills": ["kỹ năng chuyên môn", "kỹ năng", "skills", "technical skills", "core skills", "công cụ", "tools"],
    "project": ["dự án cá nhân", "dự án", "projects", "project", "personal projects"],
    "cert": ["chứng chỉ", "certificates", "certifications", "certification", "certificate", "giải thưởng", "awards"],
    "summary": ["mục tiêu nghề nghiệp", "mục tiêu", "career objective", "objective", "professional summary", "summary",
                "giới thiệu bản thân", "about me", "tóm tắt"],
    "other": ["links", "sở thích", "hobbies", "interests", "người tham chiếu", "references", "hoạt động", "activities",
              "thông tin cá nhân", "personal information", "contact", "liên hệ", "ngôn ngữ", "languages"],
}
_HEAD_RX = {k: re.compile(rf"^(?:{both(v)})\b(?P<rest>.*)$", re.I) for k, v in HEADERS.items()}
_INLINE_RX = {k: re.compile(rf"^(?:{both(HEADERS[k])})\s*[:：]\s*\S", re.I) for k in ("skills", "edu", "summary")}
# dòng bắt đầu bằng "Chứng chỉ ..." / "Dự án ..." thuộc mục đó dù có dấu ':' hay không
_LEAD_RX = {k: re.compile(rf"^(?:{both(HEADERS[k])})(?!\w)", re.I) for k in ("cert", "project")}


def header_kind(line: str) -> Optional[str]:
    raw = nfc(line).strip()
    if re.search(r"[:：]\s*\S", raw):                      # "Kỹ năng: Excel, Word" là dòng có nội dung, không phải tiêu đề
        return None
    t = raw.rstrip(":：").strip()
    if not t or len(t) > 45 or re.search(r"\d", t) or t.endswith(".") or _is_bullet(line):
        return None
    n_words = len(t.split())
    for k, rx in _HEAD_RX.items():
        m = rx.match(t)
        if m and len(m.group("rest").split()) <= 3 and n_words <= 6:
            return k
    letters = re.findall(r"[^\W\d_]", t)
    if t.isupper() and len(letters) >= 4 and n_words <= 6:
        return "other"                                    # tiêu đề viết hoa không có trong danh sách
    return None


def split_cv(cv_text: str) -> list[dict]:
    """Mỗi dòng: {text, section}; dòng tiêu đề có section 'head'."""
    out, sec = [], "other"
    for raw in cv_text.splitlines():
        t = raw.strip()
        if not t:
            continue
        k = header_kind(t)
        if k:
            sec = k
            out.append({"text": t, "section": "head"})
            continue
        s = sec
        for kk, rx in {**_INLINE_RX, **_LEAD_RX}.items():   # "Kỹ năng: Excel, MISA" chỉ đổi mục của riêng dòng này
            if rx.match(t):
                s = kk
                break
        out.append({"text": t, "section": s})
    return out


# ------------------------------------------------------------------ khối kinh nghiệm
_INTERN = re.compile(rf"\b(?:{both(['thực tập', 'intern', 'internship', 'trainee'])})\b", re.I)
COUNT_SECTIONS = ("exp", "other")


def _date_only(line: str, m: re.Match) -> bool:
    rest = (line[:m.start()] + " " + line[m.end():])
    return not re.search(r"[^\W\d_]", rest)


def parse_blocks(lines: list[dict], as_of: Optional[tuple[int, int]] = None) -> list[dict]:
    """Khối = dòng có khoảng thời gian (ngoài học vấn/kỹ năng/chứng chỉ) + các dòng liền sau.
    Khoảng thời gian nằm gọn trong khối trước (dự án con) không tạo khối mới."""
    as_of = as_of or as_of_date()
    blocks: list[dict] = []
    cur, buf = None, []
    for ln in lines:
        sec, text = ln["section"], ln["text"]
        if sec == "head" or sec not in COUNT_SECTIONS:
            cur, buf = None, []
            continue
        m = DATE_RE.search(text)
        iv = parse_interval(m, as_of) if m else None
        if iv and cur and iv[0] >= cur["s"] and iv[1] <= cur["e"]:
            cur["lines"].append(text)
            continue
        if iv:
            lines_new = [text]
            donor = cur["lines"] if cur else buf
            keep = 1 if cur else 0                         # không lấy mất dòng đầu của khối trước
            if _date_only(text, m):                       # ngày nằm riêng một dòng: tiêu đề công việc ở các dòng ngay trước
                steal = []
                while len(donor) > keep and len(steal) < 2 and not _is_bullet(donor[-1]) and len(donor[-1]) <= 80 \
                        and not donor[-1].endswith("."):
                    steal.insert(0, donor.pop())
                lines_new = steal + lines_new
            cur = {"title": next((t for t in lines_new if re.search(r"[^\W\d_]", DATE_RE.sub("", t))), text),
                   "lines": lines_new, "s": iv[0], "e": iv[1], "months": iv[1] - iv[0],
                   "intern": bool(_INTERN.search(" ".join(lines_new[:2])))}
            blocks.append(cur)
            buf = []
        elif cur is not None:
            cur["lines"].append(text)
        else:
            buf.append(text)
            buf = buf[-4:]
    return blocks


def invalid_date_ranges(lines: list[dict], as_of: Optional[tuple[int, int]] = None) -> list[str]:
    """Khoảng thời gian trong mục kinh nghiệm mà parse_interval bỏ qua (năm bắt đầu sau năm kết thúc, bắt đầu ở tương lai...).
    Trước đây chúng bị bỏ im lặng nên CV ghi sai ngày tháng được tính 0 năm mà không ai biết."""
    as_of = as_of or as_of_date()
    out = []
    for ln in lines:
        if ln["section"] not in COUNT_SECTIONS:
            continue
        m = DATE_RE.search(ln["text"])
        if m and parse_interval(m, as_of) is None:
            out.append(m.group(0).strip())
    return out


def _union(iv: list[tuple[int, int]]) -> float:
    total, cs, ce = 0, None, None
    for s, e in sorted(iv):
        if ce is None or s > ce:
            if ce is not None:
                total += ce - cs
            cs, ce = s, e
        else:
            ce = max(ce, e)
    return float(total + (ce - cs if ce is not None else 0))


def effective_months(blocks: list[dict]) -> float:
    """Hợp các khoảng (không đếm trùng); thực tập tính INTERN_FACTOR."""
    non = _union([(b["s"], b["e"]) for b in blocks if not b["intern"]])
    allm = _union([(b["s"], b["e"]) for b in blocks])
    return non + INTERN_FACTOR * (allm - non)


def relevant_years(topic: str, blocks: list[dict], accentless: bool = False) -> tuple[float, list[str]]:
    units = query_units(topic, accentless)
    rel = []
    for b in blocks:
        c = coverage(units, [(index_line(" ".join(b["lines"]), accentless), 1.0)])
        if c.value >= REL_THRESHOLD and c.latin_ok:
            rel.append(b)
    return effective_months(rel) / 12.0, [b["title"] for b in rel]


def employment_gaps(blocks: list[dict]) -> list[str]:
    iv = sorted((b["s"], b["e"]) for b in blocks)
    flags, ce = [], None
    for s, e in iv:
        if ce is not None and s - ce > 12:
            flags.append(f"Khoảng trống ~{s - ce} tháng giữa {ce // 12} và {s // 12}")
        ce = e if ce is None else max(ce, e)
    return flags


# ------------------------------------------------------------------ điều kiện cứng
LEVEL_UNIV = re.compile(rf"(?<!\w)(?:{both(['đại học', 'university', 'học viện', 'thạc sĩ', 'master', 'bachelor', 'bsc', 'b.sc', 'kỹ sư', 'engineer', 'cử nhân'])})(?!\w)", re.I)
LEVEL_ANY = re.compile(LEVEL_UNIV.pattern + rf"|(?<!\w)(?:{both(['cao đẳng', 'college', 'associate', 'diploma'])})(?!\w)", re.I)
# Văn bản OCR hay dính chữ ("Universityof Ho Chi Minhcity"): bản "lỏng" không đòi ranh giới từ sau tên cấp bậc (chỉ với các từ ít nhập nhằng)
LEVEL_UNIV_LOOSE = re.compile(LEVEL_UNIV.pattern + r"|(?<!\w)(?:university|bachelor|đại học|dai hoc|học viện)", re.I)
LEVEL_ANY_LOOSE = re.compile(LEVEL_ANY.pattern + r"|(?<!\w)(?:university|college|bachelor|đại học|dai hoc|cao đẳng|cao dang)", re.I)
_FIELD_RE = re.compile(r"(?:chuyên ngành|ngành|major(?:ing)? in|degree in|bachelor['’]?s?(?: degree)? in|\bin)\s+(.*)$", re.I)
_TRAIL = re.compile(r"\b(?:trở lên|tương đương|liên quan|khác|related fields?|related|or equivalent|equivalent|fields?)\b", re.I)


def _toks(text: str, accentless: bool) -> str:
    return " ".join(flat_tokens(text, accentless))


@lru_cache(maxsize=512)          # chỉ phụ thuộc vào yêu cầu của JD, không phụ thuộc CV: tính một lần cho cả lô
def _expand_field(term: str, accentless: bool) -> frozenset:
    t = _toks(term, accentless)
    out = {t}
    for g in L.FIELD_GROUPS:
        gt = [_toks(x, accentless) for x in g]
        if any(t == x or t in x or x in t for x in gt):
            out.update(gt)
    return frozenset(x for x in out if x)


def _contains(hay: str, needle: str) -> bool:
    return bool(re.search(rf"(?<!\S){re.escape(needle)}(?!\S)", hay))


_STUDENT_NOW = re.compile(r"expected|dự kiến|đang học|đang theo học|currently|năm\s*cuối|final[- ]year|(?:third|fourth|senior|junior)[- ]year|"
                          r"năm\s*(?:thứ\s*)?[2-5]\b|sinh viên|\bstudent\b|chưa tốt nghiệp|undergraduate", re.I)
_STUDENT_OK = re.compile(r"sinh viên|student|năm\s*cuối|final[- ]year|undergraduate|đang học|đang theo học", re.I)


def education_in_progress(edu: list[str], lines: list[dict], as_of: Optional[tuple[int, int]] = None) -> bool:
    """CV cho thấy ứng viên còn đang học, chưa tốt nghiệp: không có khoảng học nào đã kết thúc, và có khoảng kết thúc ở tương lai / "nay",
    hoặc ghi rõ sinh viên / năm cuối / dự kiến. Dùng để không coi "đang học" là "đã có bằng"."""
    ay, am = as_of or as_of_date()
    finished = ongoing = False
    for text in edu:
        for m in DATE_RE.finditer(text):
            if m["now"]:
                ongoing = True
                continue
            ey = int(m["ey"])
            em = int(m["em"]) if m["em"] else None
            if ey > ay or (ey == ay and em is not None and em > am):
                ongoing = True
            else:
                finished = True
        if _STUDENT_NOW.search(DATE_RE.sub(" ", text)):
            ongoing = True
    if finished:
        return False
    if ongoing:
        return True
    head = [l["text"] for l in lines if l["section"] != "head"][:12]            # không có ngày nào: xem lời giới thiệu đầu CV
    return bool(re.search(r"sinh viên\s*(?:năm|đang)|final[- ]year|(?:third|fourth)[- ]year|đang học|năm\s*cuối|\bstudent\b", " ".join(head), re.I))


def check_education(bullet: str, lines: list[dict], accentless: bool = False, loose: bool = False) -> HardCheck:
    """loose=True cho văn bản OCR (chữ dính liền: "Universityof")."""
    level_univ, level_any = (LEVEL_UNIV_LOOSE, LEVEL_ANY_LOOSE) if loose else (LEVEL_UNIV, LEVEL_ANY)
    edu = [l["text"] for l in lines if l["section"] == "edu"]
    edu = edu or [l["text"] for l in lines if l["section"] not in ("head", "skills") and level_any.search(l["text"])]
    if not edu:
        return HardCheck(requirement_id="", status="unclear", note="Không thấy thông tin học vấn trong CV")
    b = nfc(bullet).lower()
    need_univ = bool(re.search(r"đại học|bachelor|thạc sĩ|master|university", b)) and not re.search(r"cao đẳng|college|associate", b)
    terms: list[str] = []
    m = _FIELD_RE.search(b)
    if m:
        for part in re.split(r",|;|\bhoặc\b|\bvà\b|\bor\b|\band\b|/|&", m.group(1)):
            p = _TRAIL.sub("", part).strip(" .")
            if len(p) >= 2:
                terms.append(p)
    expanded: set[str] = set()
    for t in terms:
        expanded |= _expand_field(t, accentless)
    level_ok = any((level_univ if need_univ else level_any).search(e) for e in edu)
    hit = None
    if expanded:
        hit = next((e for e in edu if any(_contains(_toks(e, accentless), x) for x in expanded)), None)
    else:
        hit = edu[0]
    if level_ok and hit:
        if not _STUDENT_OK.search(b) and education_in_progress(edu, lines):
            return HardCheck(requirement_id="", status="unclear", evidence=hit,
                             note="Có vẻ đang học, chưa tốt nghiệp (ngày kết thúc ở tương lai hoặc ghi sinh viên/năm cuối): cần xác nhận")
        return HardCheck(requirement_id="", status="met", evidence=hit)
    if not level_ok and not hit:
        return HardCheck(requirement_id="", status="not_met", evidence=edu[0], note="Sai cấp bậc và ngành")
    note = "Ngành học không khớp danh sách từ khoá, cần người xem" if level_ok else "Cấp bậc thấp hơn yêu cầu"
    return HardCheck(requirement_id="", status="unclear", evidence=hit or edu[0], note=note)


def check_experience(bullet: str, blocks: list[dict], accentless: bool = False) -> tuple[HardCheck, float, list[str]]:
    need = parse_min_years(bullet) or 0.0
    topic = years_topic(bullet)
    if is_generic_years(bullet, accentless):
        # "Years of experience: >2 YoE": JD không nói lĩnh vực nào, tính tổng kinh nghiệm; lĩnh vực do các tiêu chí kỹ năng chấm
        yrs, titles = effective_months(blocks) / 12.0, [b["title"] for b in blocks]
        note_suffix = ", tính tổng kinh nghiệm vì JD không nêu lĩnh vực"
    else:
        yrs, titles = relevant_years(topic, blocks, accentless)
        note_suffix = ""
    if not blocks:
        return (HardCheck(requirement_id="", status="unclear",
                          note="Không đọc được mốc thời gian làm việc trong CV, cần người xem"), 0.0, [])
    st = "met" if yrs >= need else "unclear" if yrs >= 0.5 * need else "not_met"
    total = effective_months(blocks) / 12.0
    if st == "not_met" and total >= need:
        # Đủ số năm đi làm nhưng không thấy đúng lĩnh vực. Khớp từ khoá không đủ tin để LOẠI người đã có nhiều năm kinh nghiệm
        # (họ có thể mô tả công việc bằng từ khác, hoặc đang chuyển ngành): để người xem quyết định.
        st = "unclear"
        note_suffix = f"; tổng kinh nghiệm {total:.1f} năm nhưng không thấy rõ đúng lĩnh vực, cần người xem"
    return (HardCheck(requirement_id="", status=st, evidence=titles[0] if titles else "",
                      note=f"~{yrs:.1f} năm kinh nghiệm liên quan (cần {need:g}){note_suffix}"), yrs, titles)
