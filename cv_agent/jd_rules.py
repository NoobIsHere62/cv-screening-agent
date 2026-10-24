"""JD -> Rubric bằng luật (không LLM)."""
import re
from typing import Optional

from .config import WEIGHT_PREFERRED, WEIGHT_REQUIRED, WEIGHT_YEARS
from .lang_check import LANG_CERT, parse_required
from .nlp import _known_tech, both, flat_tokens, fold, nfc, query_units
from .schemas import Criterion, HardRequirement, JDAnalysis, Rubric
from .textutil import clean_text


# ------------------------------------------------------------------ số năm kinh nghiệm
_NUM = r"(\d+(?:[.,]\d+)?)"
_UNIT = r"(năm|nam|years?|yrs?|tháng|thang|months?)"
_RANGE = rf"{_NUM}\s*(?:\+|(?:[-–—]|đến|tới|to)\s*{_NUM})?\s*{_UNIT}"
_EXP_FWD = re.compile(rf"{_RANGE}\s*(?:of\s*)?(?:kinh nghiệm|kinh nghiem|experience|exp\b)", re.I)
_EXP_BWD = re.compile(rf"(?:kinh nghiệm|kinh nghiem|experience(?: of)?)\s*(?:từ|tu|of)?\s*{_RANGE}", re.I)
NO_EXP = re.compile(r"(?:không|chưa|khong|chua)\s*(?:yêu cầu|cần|đòi hỏi|yeu cau|can)?\s*(?:có\s*)?kinh nghiệm|"
                    r"no experience|freshers? welcome|fresher|không đòi hỏi kinh nghiệm|"
                    r"(?:years? of experiences?|số năm kinh nghiệm|yoe)\s*:?\s*(?:no|none|n/a|không|0)\s*\.?$", re.I)
_EXP_YOE = re.compile(rf"(?:[>≥]=?\s*)?{_NUM}\s*\+?\s*yoe\b", re.I)               # ">2 YoE", "3+ YoE"
_EXP_CMP = re.compile(rf"[>≥]=?\s*{_NUM}\s*{_UNIT}", re.I)                      # ">2 years", "≥3 năm"
YEARS_LABEL = re.compile(r"^\s*(?:years? of experiences?|số năm kinh nghiệm|yoe)\b", re.I)


_YEARS_PHRASE = re.compile(r"\d+(?:[.,]\d+)?\s*\+?\s*(?:[-–—]\s*\d+\s*)?(?:năm|years?|yrs?|tháng|months?|yoe)", re.I)
_GENERIC_YEARS = re.compile(r"\b(?:years?|of|experiences?|yoe|kinh nghiệm|số năm|tối thiểu|ít nhất|minimum|at least|over|more than|"
                            r"trên|min)\b|[>≥:+]", re.I)


def years_topic(text: str) -> str:
    """Phần còn lại của câu yêu cầu sau khi bỏ cụm số năm: 'Có ít nhất 2 năm kinh nghiệm' -> 'Có ít nhất kinh nghiệm'."""
    return _YEARS_PHRASE.sub(" ", text)


def is_generic_years(text: str, accentless: bool = False) -> bool:
    """Yêu cầu số năm không nêu lĩnh vực nào ('Có ít nhất 2 năm kinh nghiệm', 'Years of experience: >2 YoE')."""
    return not query_units(_GENERIC_YEARS.sub(" ", years_topic(text)), accentless)


def parse_min_years(text: str) -> Optional[float]:
    """None: không nói về số năm kinh nghiệm. 0.0: nói rõ không yêu cầu. Còn lại: số năm tối thiểu."""
    if NO_EXP.search(text):
        return 0.0
    m = _EXP_YOE.search(text)
    if m:
        return float(m.group(1).replace(",", "."))
    m = _EXP_CMP.search(text)
    if m:
        v = float(m.group(1).replace(",", "."))
        return v / 12.0 if m.group(2).lower().startswith(("th", "mo")) else v
    hits = [m for m in (_EXP_FWD.search(text), _EXP_BWD.search(text)) if m]
    if not hits:
        return None
    m = min(hits, key=lambda x: x.start())
    n1, _, unit = m.group(1), m.group(2), m.group(3).lower()
    v = float(n1.replace(",", "."))
    return v / 12.0 if unit.startswith(("th", "mo")) else v


# ------------------------------------------------------------------ lọc / phân loại
DISCRIMINATORY = re.compile(
    r"giới tính|\bnam\s*/\s*nữ\b|\bnữ\s*/\s*nam\b|\bnam hoặc nữ\b|\b(?:nam|nữ)\s*,?\s*tuổi|ưu tiên\s+(?:nam|nữ)\b|"
    r"độ tuổi|tuổi đời|\btuổi\s*(?:từ|dưới|trên)?\s*\d|\d+\s*(?:-|–|đến)\s*\d+\s*tuổi|ngoại hình|ưa nhìn|"
    r"chiều cao|cân nặng|độc thân|hôn nhân|mang thai|\bgender\b|\bmale\b|\bfemale\b|years old|\bage\s*\d", re.I)
LOW_EDU = re.compile(r"thpt|trung học|phổ thông|trung cấp", re.I)
SOFT = re.compile(r"cẩn thận|trung thực|sáng tạo|chủ động|làm việc nhóm|chịu được áp lực|chịu áp lực|giao tiếp|"
                  r"nhiệt tình|năng động|teamwork|team player|communication|trách nhiệm|ham học hỏi|tư duy|"
                  r"kỹ năng mềm|chăm chỉ|linh hoạt|proactive|self-motivated|detail-oriented|đàm phán|thuyết trình|lãnh đạo|"
                  r"quản lý thời gian|giải quyết vấn đề|negotiation|presentation|leadership|problem[- ]solving|time management", re.I)
SOFT_EXCEPT = re.compile(r"excel|tiếng anh|english|phần mềm|software|\bsql\b|python", re.I)
PREFERRED = re.compile(r"ưu tiên|lợi thế|điểm cộng|nice to have|good to have|\bplus\b|preferred|a bonus", re.I)
DEGREE = re.compile(r"tốt nghiệp|đại học|cao đẳng|bachelor|degree|graduat|thạc sĩ|master's", re.I)

REQ_H = ["required skills", "required qualifications", "required", "key requirements", "technical requirements",
         "minimum qualifications", "basic qualifications", "kỹ năng cần có", "yêu cầu kỹ năng", "yêu cầu công việc", "yêu cầu ứng viên", "yêu cầu tuyển dụng", "yêu cầu", "requirements", "requirement",
         "qualifications", "qualification", "what you need", "what you'll need", "what you'll bring", "what you bring", "what we're looking for",
         "who you are", "about you", "your profile", "skills and experience", "skills & experience", "essential", "key skills", "must have", "must-have",
         "we are looking for", "ứng viên cần", "ứng viên", "điều kiện", "tiêu chuẩn", "kỹ năng yêu cầu"]
PREF_H = ["preferred qualifications", "desirable", "bonus points", "ưu tiên", "nice to have", "nice-to-have", "preferred", "bonus", "lợi thế", "điểm cộng", "good to have"]
OTHER_H = ["key responsibilities", "main responsibilities", "job description", "mô tả công việc", "mô tả", "trách nhiệm", "responsibilities", "responsibility", "what you'll do",
           "quyền lợi", "phúc lợi", "benefits", "benefit", "thông tin", "địa điểm", "thu nhập", "mức lương", "lương",
           "thời gian làm việc", "about us", "about the role", "giới thiệu", "cách thức ứng tuyển", "hồ sơ",
           "liên hệ", "how to apply", "công việc", "nhiệm vụ", "chế độ", "what we offer", "our offer", "perks", "why join us",
           "company overview", "about the company", "working hours", "work location", "salary", "môi trường làm việc"]


def _head_re(words):
    return re.compile(rf"^(?:{both(words)})\b(?P<rest>[^:：]*)(?:[:：]\s*(?P<content>.*))?$", re.I)


HEAD_PREF, HEAD_REQ, HEAD_OTHER = _head_re(PREF_H), _head_re(REQ_H), _head_re(OTHER_H)
BULLET = re.compile(r"^\s*(?:[-•*+–·▪●○■]|\d+[.)])\s+")


def _is_bullet(line: str) -> bool:
    return bool(BULLET.match(line))


def _strip_bullet(line: str) -> str:
    return BULLET.sub("", line).strip()


def classify_header(line: str) -> Optional[tuple[str, str]]:
    """Trả về (loại mục, nội dung cùng dòng) nếu dòng là tiêu đề mục, ngược lại None."""
    t = nfc(line).strip()
    if not t or _is_bullet(t):
        return None
    head_part = re.split(r"[:：]", t, maxsplit=1)[0]
    if len(head_part) > 50:                      # tiêu đề mục ngắn; nội dung sau dấu ':' thì không giới hạn
        return None
    for kind, rx in (("pref", HEAD_PREF), ("req", HEAD_REQ), ("other", HEAD_OTHER)):
        m = rx.match(t)
        if not m:
            continue
        rest = (m.group("rest") or "").strip()
        content = (m.group("content") or "").strip()
        has_colon = ":" in t or "：" in t
        short = len(re.findall(r"\w+", rest)) <= 3 and len(t) <= 50
        if has_colon and len(re.findall(r"\w+", rest)) <= 4:
            return kind, content
        if not has_colon and short and (t.isupper() or len(rest) == 0 or len(t.split()) <= 5):
            return kind, ""
    return None


def split_items(text: str) -> list[str]:
    """Tách một đoạn thành các yêu cầu theo ';' và ranh giới câu."""
    out = []
    for part in re.split(r";|(?<=[.!?])\s+(?=[A-ZÀ-Ỵ])", text):
        part = _strip_bullet(part).strip(" \t.;")
        # "Tốt nghiệp cao đẳng, ưu tiên chuyên ngành kinh tế": phần đầu bắt buộc, phần sau chỉ là ưu tiên
        sub = re.split(r",?\s*(?:trong đó|of which)\s+", part, maxsplit=1, flags=re.I)   # "2-3 năm kinh nghiệm, trong đó ít nhất 1 năm ..."
        if len(sub) == 2 and len(sub[0]) >= 8 and len(sub[1]) >= 8:
            out.extend(split_items(sub[0]) + split_items(sub[1]))
            continue
        m = re.search(r"[,;]\s*(?=(?:ưu tiên|nice to have|preferably|ideally)\b)", part, re.I)
        pieces = [part[:m.start()], part[m.end():]] if m and m.start() >= 8 else [part]
        out.extend(p.strip(" \t.;") for p in pieces if len(p.strip(" \t.;")) >= 4)
    return out


# Dòng/mục có dấu hiệu là YÊU CẦU ứng viên (dùng để đoán loại cho tiêu đề mục lạ như "What you'll bring:")
REQ_SIGNAL = re.compile(r"kinh nghiệm|experience|\bnăm\b|years?|thành thạo|thành thục|\bbiết\b|nắm vững|am hiểu|proficien|knowledge|"
                        r"familiar|skills?|degree|bachelor|tốt nghiệp|đại học|cao đẳng|toeic|ielts|chứng chỉ|certificat|"
                        r"sử dụng|understanding|ability to|hands-on|expertise|\bgiỏi\b", re.I)
_CLAUSE_SPLIT = re.compile(r",\s+(?=(?:sử dụng|biết|thành thạo|có|giao tiếp|am hiểu|nắm vững|ưu tiên|kỹ năng|tốt nghiệp|"
                           r"kinh nghiệm|ít nhất|tiếng anh|english|and|using|with|knowledge|experience|proficiency)\b)", re.I)


def _looks_like_title(line: str, n_lines: int) -> bool:
    """Dòng đầu là tên vị trí khi ngắn, không phải câu và JD còn các dòng khác; JD chỉ một đoạn văn thì không có tiêu đề."""
    t = line.strip()
    return n_lines > 1 and len(t) <= 100 and not t.endswith((".", ";")) and t.count(",") < 2 and not classify_header(t)


def _unknown_header(line: str) -> Optional[str]:
    """Tiêu đề mục lạ: dòng ngắn kết thúc bằng ':' hoặc viết IN HOA, không phải gạch đầu dòng."""
    t = nfc(line).strip()
    if not t or _is_bullet(t):
        return None
    m = re.fullmatch(r"([^:：]{2,50})[:：]\s*", t)
    if m:
        return m.group(1).strip()
    words = t.split()
    if t.isupper() and 1 <= len(words) <= 6 and len(re.findall(r"[^\W\d_]", t)) >= 4 and not re.search(r"\d", t):
        return t
    return None


def extract_jd_items(jd_text: str) -> tuple[str, list[tuple[str, str]], list[str]]:
    """-> (tiêu đề, [(văn bản, 'req'|'pref')], ghi chú)"""
    lines = [l.rstrip() for l in clean_text(jd_text).replace("’", "'").replace("‘", "'").splitlines()]
    non_empty = [l for l in lines if l.strip()]
    title = non_empty[0].strip() if non_empty else ""
    notes: list[str] = []
    blocks: list[dict] = []                   # mỗi mục: {"kind", "lines": [(text, is_bullet)]}
    cur = None
    first_seen = False
    if not _looks_like_title(title, len(non_empty)):   # dòng đầu là tiêu đề mục ("Key Responsibilities:") hoặc cả JD là một đoạn văn
        title, first_seen = "", True
    for l in lines:
        if not l.strip():
            continue
        if not first_seen:                     # dòng đầu là tiêu đề, không coi là tiêu đề mục
            first_seen = True
            continue
        h = classify_header(l)
        if h:
            cur = {"kind": h[0], "lines": []}
            blocks.append(cur)
            if h[1]:
                cur["lines"].append((h[1], False))
            continue
        name = _unknown_header(l)
        if name:                               # tiêu đề lạ: mở mục riêng, cuối cùng đoán loại theo nội dung
            cur = {"kind": "unknown", "name": name, "lines": []}
            blocks.append(cur)
            continue
        if cur is None:
            cur = {"kind": "none", "lines": []}
            blocks.append(cur)
        cur["lines"].append((l.strip(), _is_bullet(l)))

    def block_items(b) -> list[str]:
        ls = b["lines"]
        if any(isb for _, isb in ls):
            merged: list[str] = []
            for text, isb in ls:
                if isb:
                    merged.append(_strip_bullet(text))
                elif merged and (not re.search(r"[.;!?]$", merged[-1]) or text[:1].islower()):
                    merged[-1] += " " + text           # dòng bị ngắt, nối vào gạch đầu dòng trước
                else:
                    merged.append(text)
        else:
            merged = [t for t, _ in ls]
        items: list[str] = []
        for m in merged:
            items.extend(split_items(m))
        return items

    items: list[tuple[str, str]] = []
    for b in blocks:
        if b["kind"] in ("req", "pref"):
            items += [(t, b["kind"]) for t in block_items(b)]
        elif b["kind"] == "unknown":            # mục có tiêu đề lạ: chỉ nhận khi đa số dòng trông như yêu cầu ứng viên
            cand = block_items(b)
            if cand and sum(bool(REQ_SIGNAL.search(t)) for t in cand) >= 0.5 * len(cand):
                items += [(t, "req") for t in cand]
                notes.append(f"Mục «{b['name']}» có tiêu đề lạ, đã coi là yêu cầu ứng viên vì nội dung giống yêu cầu")
    if not any(k == "req" for _, k in items):   # không thấy mục "Yêu cầu": dùng các gạch đầu dòng ngoài mục mô tả/quyền lợi
        notes.append("Không tìm thấy mục 'Yêu cầu' rõ ràng; dùng các gạch đầu dòng ngoài mục mô tả/quyền lợi")
        for b in blocks:
            if b["kind"] == "none" and any(isb for _, isb in b["lines"]):
                items += [(t, "req") for t in block_items(b)]
    if not items:                               # JD viết thành đoạn văn: tách thành câu rồi thành mệnh đề yêu cầu
        kw = re.compile(r"yêu cầu|biết|thành thạo|kinh nghiệm|tốt nghiệp|nắm vững|ưu tiên|lợi thế|must|experience|proficien|knowledge|preferred",
                        re.I)
        for b in blocks:
            if b["kind"] in ("none", "req"):
                for t, _ in b["lines"]:
                    for sentence in split_items(t):
                        if kw.search(sentence):
                            items += [(c.strip(" ,.;"), "req") for c in _CLAUSE_SPLIT.split(sentence) if len(c.strip(" ,.;")) >= 6]
        if items:
            notes.append("JD viết thành đoạn văn, đã tách thành từng mệnh đề; nên đọc lại JD đã lọc")
    return title, items, notes


def _has_concrete_term(text: str) -> bool:
    """Có tên công cụ/thuật ngữ cụ thể (viết tắt IN HOA như CTR, SQL hoặc từ trong từ điển kỹ thuật) thì không phải kỹ năng mềm thuần tuý."""
    return bool(re.search(r"\b[A-Z][A-Z0-9]{1,}\b", text)) or bool(set(flat_tokens(text)) & _known_tech(False))


def _short(text: str, n: int = 70) -> str:
    if len(text) <= n:
        return text
    cut = text[:n].rsplit(" ", 1)[0]
    return cut + "…"


def guess_seniority(title: str, years: Optional[float]) -> str:
    t = fold(title)
    if re.search(r"thuc tap|intern", t):
        return "intern"
    if re.search(r"giam doc|manager|truong phong|head of|director", t):
        return "manager"
    if re.search(r"senior|lead|truong nhom|chuyen gia", t):
        return "senior"
    if re.search(r"junior|fresher", t):
        return "junior"
    if years is None:
        return "unclear"
    return "junior" if years <= 1 else "mid" if years < 5 else "senior"


def _dedupe_years(hard: list) -> list:
    """JD hay nêu số năm hai lần ("2+ years of experience in full-stack development" và "Years of experience: 2+ YoE"). Bỏ câu chung chung
    nếu đã có câu nêu lĩnh vực; nếu cả hai đều chung chung thì giữ mức cao nhất. Đánh số lại id để khớp với kết quả chấm."""
    years = [h for h in hard if h.type == "experience_years"]
    if len(years) < 2:
        return hard
    specific = [h for h in years if not is_generic_years(h.source_quote)]
    if specific:
        drop = {id(h) for h in years if h not in specific}
    else:
        keep = max(years, key=lambda h: parse_min_years(h.source_quote) or 0)
        drop = {id(h) for h in years if h is not keep}
    kept = [h for h in hard if id(h) not in drop]
    return [h.model_copy(update={"id": f"h{i}"}) for i, h in enumerate(kept, 1)]

def build_rubric_rules(jd_text: str) -> Rubric:
    title, items, notes = extract_jd_items(jd_text)
    if not items:
        raise ValueError("Không tách được yêu cầu nào từ JD. Hãy ghi các yêu cầu thành từng dòng, "
                         "ví dụ dưới mục 'Yêu cầu:' hoặc 'Requirements:'.")
    hard, crits, seen = [], [], set()
    min_years: Optional[float] = None

    def add_crit(text: str, kind: str, name: str, weight: float, imp: str, desc: str, hint: str):
        crits.append(Criterion(id=f"c{len(crits) + 1}", name=name, description=desc, weight=weight,
                               importance=imp, source_quote=text, cv_evidence_hint=hint))

    for text, kind in items:
        key = fold(text)
        if key in seen:
            continue
        seen.add(key)
        if DISCRIMINATORY.search(text):
            notes.append(f"Bỏ qua yêu cầu có thể gây phân biệt đối xử: '{_short(text, 60)}'")
            continue
        if LOW_EDU.search(text) and DEGREE.search(text):
            continue
        pref = kind == "pref" or bool(PREFERRED.search(text))
        if YEARS_LABEL.search(text) and not PREFERRED.search(text):
            pref = False                         # dòng "Years of experience: ..." là yêu cầu chung dù nằm dưới mục "Nice to have"
        yrs = parse_min_years(text)
        if yrs == 0.0:                           # "Không yêu cầu kinh nghiệm, biết Python": bỏ phần kinh nghiệm, giữ kỹ năng đi kèm
            rest = re.sub(r"\s+", " ", NO_EXP.sub(" ", text)).strip(" ,;.:/-–")
            if len(rest) < 4 or not (query_units(rest) or DEGREE.search(rest)):
                continue                         # chỉ còn "không yêu cầu kinh nghiệm": không có gì để chấm
            text, yrs = rest, None
        if LANG_CERT.search(text) and not pref and parse_required(text):
            hard.append(HardRequirement(id=f"h{len(hard) + 1}", description="Chứng chỉ ngoại ngữ",
                                        type="language", source_quote=text))
            continue
        has_deg = bool(DEGREE.search(text))
        if has_deg and (yrs is None or yrs > 0) and not pref:
            hard.append(HardRequirement(id=f"h{len(hard) + 1}", description="Bằng cấp / chuyên ngành",
                                        type="education", source_quote=text))
        if yrs is not None and yrs > 0 and not pref:
            min_years = yrs if min_years is None else max(min_years, yrs)
            hard.append(HardRequirement(id=f"h{len(hard) + 1}", description=f"Tối thiểu {yrs:g} năm kinh nghiệm liên quan",
                                        type="experience_years", source_quote=text))
            if is_generic_years(text):
                continue                         # "có ít nhất 2 năm kinh nghiệm" không nêu lĩnh vực: chỉ là cổng điều kiện cứng, không cộng điểm
            add_crit(text, kind, _short(text), WEIGHT_YEARS, "required",
                     "Số năm kinh nghiệm liên quan so với yêu cầu", "Các khối kinh nghiệm làm việc")
            continue
        if has_deg and not pref:
            continue
        if SOFT.search(text) and not SOFT_EXCEPT.search(text) and not _has_concrete_term(text):
            notes.append(f"Đã lọc bỏ kỹ năng mềm (không kiểm chứng được từ CV): '{_short(text, 60)}'")
            continue                             # yêu cầu tính cách (không có thuật ngữ cụ thể): baseline không đánh giá
        if not query_units(text):
            notes.append(f"Bỏ qua yêu cầu không có từ khoá chấm được: '{_short(text, 60)}'")
            continue
        add_crit(text, kind, _short(text), WEIGHT_PREFERRED if pref else WEIGHT_REQUIRED,
                 "preferred" if pref else "required", "Độ phủ từ khoá của yêu cầu trong CV", "Mục kinh nghiệm, dự án")

    hard = _dedupe_years(hard)
    if not crits:                                # JD chỉ có điều kiện cứng: dùng tên vị trí làm tiêu chí tối thiểu
        if not query_units(title):
            raise ValueError("JD chỉ có điều kiện chung (bằng cấp, số năm...) mà chưa có kỹ năng/công cụ cụ thể nào để chấm. "
                             "Hãy bổ sung ít nhất một kỹ năng, ví dụ: 'Thành thạo Excel' hoặc 'Biết Python'.")
        notes.append("JD không có yêu cầu kỹ năng cụ thể; dùng tên vị trí làm tiêu chí")
        add_crit(title, "req", _short(title), WEIGHT_REQUIRED, "required", "Mức liên quan tới tên vị trí", "Kinh nghiệm")
    analysis = JDAnalysis(job_title=title or "(JD không có tiêu đề)", industry_group="unknown", seniority=guess_seniority(title, min_years),
                          daily_responsibilities_summary="(baseline không phân tích mô tả công việc)",
                          explicit_requirements=[t for t, _ in items], implicit_requirements=[], ambiguities=notes)
    return Rubric(jd_analysis=analysis, hard_requirements=hard, criteria=crits)
