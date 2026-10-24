"""Chuẩn hoá, tách yêu cầu thành đơn vị so khớp, và tính độ phủ từ khoá."""
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

from . import lexicon as L

_ZW_RE = re.compile("[" + "".join(map(chr, (0x200B, 0x200C, 0x200D, 0xFEFF))) + "]")          # r\u1ed9ng b\u1eb1ng 0 v\u00e0 BOM
BREAKS = set(",;:[]/&|•·\n")
TOKEN_RE = re.compile(r"[^\W_]+|[,;:()\[\]/&|•·\n]")


def stem(tok: str) -> str:
    """Từ tiếng Anh dài (≥7 chữ cái, không dấu) chỉ giữ 5 ký tự đầu để analyst/analysis/analytics, recruit/recruitment
    khớp nhau. Không rút gọn nếu phần đầu trùng một thuật ngữ kỹ thuật khác (excellent không được thành excel)."""
    if len(tok) >= 7 and tok.isascii() and tok.isalpha() and tok[:5] not in _RAW_TECH:
        return tok[:5]
    return tok


_RAW_TECH = frozenset(w for w in L.EXTRA_TECH if len(w) == 5) | {"react", "redis", "flask", "linux", "swift"}


def stem_all(tokens):
    return [stem(t) for t in tokens]


def nfc(s: str) -> str:
    s = unicodedata.normalize("NFC", s)
    return _ZW_RE.sub("", s) if _ZW_RE.search(s) else s          # đa số dòng không có ký tự vô hình: tránh translate() chậm


def fold(s: str) -> str:
    """Bỏ dấu tiếng Việt, chữ thường."""
    s = unicodedata.normalize("NFD", nfc(s).lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d")


def both(words) -> str:
    """Regex alternation chấp nhận cả dạng có dấu và không dấu."""
    ws = {w for w in words} | {fold(w) for w in words}
    return "|".join(re.escape(w) for w in sorted(ws, key=len, reverse=True))


def looks_accentless(text: str) -> bool:
    """CV viết không dấu: có các từ khoá không dấu thường gặp mà không có dạng có dấu."""
    t = nfc(text).lower()
    ascii_hits = sum(1 for w in ("kinh nghiem", "hoc van", "cong ty", "ky nang", "nhan vien", "ke toan", "du an") if w in t)
    accented = sum(1 for c in t if unicodedata.category(unicodedata.normalize("NFD", c)[1:2] or "L") == "Mn")
    return ascii_hits >= 2 and accented < 0.003 * max(len(t), 1)


def protect_tech(text: str) -> str:
    if not L.TECH_ANY.search(text):                      # đa số dòng không có cách viết nào cần đổi: bỏ qua các lần thay thế
        return text
    for rx, rep in L.TECH_ALIASES_C:
        text = rx.sub(f" {rep} ", text)
    return text


def tokenize(text: str, accentless: bool = False) -> list[str]:
    """Danh sách token; ký hiệu ngắt (dấu phẩy, ngoặc...) trở thành '|'."""
    t = protect_tech(nfc(text).lower())
    if accentless:
        t = fold(t)
    out = []
    for m in TOKEN_RE.findall(t):
        out.append("|" if m in BREAKS else m)
    return out


def flat_tokens(text: str, accentless: bool = False) -> list[str]:
    return [t for t in tokenize(text, accentless) if t not in ("|", "(", ")")]


@lru_cache(maxsize=4)
def _stop(accentless: bool) -> frozenset:
    return frozenset({fold(w) if accentless else w for w in L.STOP})


@lru_cache(maxsize=4)
def _stop_phrases(accentless: bool):
    ph = [tuple(flat_tokens(p, accentless)) for p in L.STOP_PHRASES]
    return sorted({p for p in ph if p}, key=len, reverse=True)


def mark_stop_phrases(toks: list[str], accentless: bool = False) -> list[str]:
    """Thay các cụm từ dừng (vd 'kỹ năng', 'kinh nghiệm') bằng '§' để chúng ngắt đơn vị mà không phá từ ghép khác."""
    out, i, n = list(toks), 0, len(toks)
    phrases = _stop_phrases(accentless)
    while i < n:
        for ph in phrases:
            if tuple(toks[i:i + len(ph)]) == ph:
                for j in range(i, i + len(ph)):
                    out[j] = "§"
                i += len(ph) - 1
                break
        i += 1
    return out


@lru_cache(maxsize=4)
def _or_words(accentless: bool) -> frozenset:
    return frozenset({fold(w) if accentless else w for w in L.OR_WORDS})


@lru_cache(maxsize=4)
def _known_tech(accentless: bool) -> frozenset:
    base = set(L.EXTRA_TECH)
    for k, v in L.IMPLIES.items():
        for tok in flat_tokens(k + " " + v):
            if re.fullmatch(r"[a-z][a-z0-9]{2,}", tok) and not is_vn_syllable_ascii(tok):
                base.add(tok)
    return frozenset(base)


_VN_NUCLEI = sorted(["a", "e", "i", "o", "u", "y", "ai", "ao", "au", "ay", "eo", "eu", "ia", "ie", "iu", "oa", "oe",
                     "oi", "ua", "ue", "ui", "uo", "uy", "ya", "ye", "oai", "oay", "uai", "uay", "uoi", "uye", "ieu",
                     "yeu", "uyu"], key=len, reverse=True)
_VN_SYL = re.compile(r"(?:ngh|ng|nh|ch|gh|gi|kh|ph|qu|th|tr|[bcdghklmnpqrstvx])?(?:%s)(?:ch|ng|nh|[cmnpt])?"
                     % "|".join(_VN_NUCLEI))


def is_vn_syllable_ascii(tok: str) -> bool:
    """Âm tiết tiếng Việt không có dấu thanh/dấu mũ (quy, nha, gia, khi...). Dựa trên cấu trúc âm tiết, không phải danh sách đoán."""
    return bool(_VN_SYL.fullmatch(tok))


def is_latin(tok: str, accentless: bool = False) -> bool:
    if tok in _stop(accentless):
        return False
    if tok in _known_tech(accentless):
        return True
    if accentless:                         # không phân biệt được tiếng Việt không dấu với tiếng Anh: chỉ tin từ điển
        return False
    if tok in L.SHORT_LATIN:
        return True
    return bool(re.fullmatch(r"[a-z][a-z0-9]{2,}", tok)) and not is_vn_syllable_ascii(tok)


# ---------------------------------------------------------------- đơn vị so khớp của một yêu cầu
@lru_cache(maxsize=1024)
def query_units(query: str, accentless: bool = False) -> tuple:
    """latin: cụm từ kỹ thuật liền nhau (facebook ads), trọng số 2/từ, được tính điểm một phần.
    vn: cụm âm tiết tiếng Việt, trọng số 1/âm tiết, chỉ tính khi hai âm tiết liền nhau xuất hiện cùng nhau.
    'hoặc/or' nối đơn vị liền trước và liền sau thành nhóm lựa chọn (chỉ cần một trong nhóm).
    Kết quả được nhớ lại (mỗi yêu cầu của JD được phân tích một lần thay vì một lần cho mỗi CV) nên là tuple, không được sửa."""
    toks = mark_stop_phrases(tokenize(query, accentless), accentless)
    stop, ors = _stop(accentless), _or_words(accentless)
    units: list[dict] = []
    st = {"lat": [], "vn": [], "pending_or": False, "last": None, "gid": 0, "depth": 0}

    def attach(u):
        if st["depth"] > 0:
            u["w"] *= 0.25                     # ví dụ trong ngoặc ("Excel (pivot table, VLOOKUP)") quan trọng ít hơn từ khoá chính
        if st["pending_or"] and st["last"] is not None:
            if st["last"]["g"] is None:
                st["gid"] += 1
                st["last"]["g"] = st["gid"]
            u["g"] = st["last"]["g"]
            st["pending_or"] = False
        units.append(u)
        st["last"] = u

    def flush():
        if st["lat"]:
            attach({"kind": "latin", "toks": st["lat"], "w": 2.0 * len(st["lat"]), "g": None})
            st["lat"] = []
        if st["vn"]:
            run = st["vn"]
            st["vn"] = []
            if not (len(run) == 1 and len(run[0]) < 3):
                attach({"kind": "vn", "syl": run, "w": float(len(run)), "g": None})

    for t in toks:
        if t == "|":
            flush()
        elif t in ("(", ")"):
            flush()
            st["depth"] = max(0, st["depth"] + (1 if t == "(" else -1))
        elif t in ors:
            flush()
            st["pending_or"] = True
        elif t == "§" or t in stop or t.isdigit():
            flush()
        elif is_latin(t, accentless):
            if st["vn"]:
                flush()
            st["lat"].append(stem(t))
        else:
            if st["lat"]:
                flush()
            st["vn"].append(stem(t))
    flush()
    return tuple(units)


# ---------------------------------------------------------------- dòng CV đã chuẩn hoá
GLUED_MIN = 14        # từ dài ≥ 14 chữ cái gần như chắc chắn là nhiều từ dính nhau (OCR/PDF mất khoảng trắng)


@dataclass
class LineIndex:
    toks: list
    tset: set
    bigrams: set
    glued: tuple = ()      # các "từ" dính liền dài bất thường, giữ nguyên dạng (không rút gọn) để tìm từ khoá nằm bên trong


@lru_cache(maxsize=8)
def _implies_compiled(accentless: bool) -> dict:
    """{từ đầu của cụm điều kiện: [(thứ tự trong từ điển, regex khớp cả cụm, các từ được suy ra)]}. Một dòng chỉ cần thử các luật có từ đầu
    xuất hiện trong dòng (trước đây thử cả ~190 luật cho mỗi dòng)."""
    out: dict = {}
    for order, (k, v) in enumerate(L.IMPLIES.items()):
        key_tokens = stem_all(flat_tokens(k, accentless))
        if key_tokens:
            rx = re.compile(rf"(?<!\S){re.escape(' '.join(key_tokens))}(?!\S)")
            out.setdefault(key_tokens[0], []).append((order, rx, stem_all(flat_tokens(v, accentless))))
    return out


def index_line(text: str, accentless: bool = False) -> LineIndex:
    raw = flat_tokens(text, accentless)
    toks = stem_all(raw)
    glued = tuple(t for t in raw if len(t) >= GLUED_MIN and t.isascii() and t.isalpha())
    joined = " ".join(toks)
    rules = _implies_compiled(accentless)
    candidates = sorted((rule for tok in set(toks) for rule in rules.get(tok, ())), key=lambda rule: rule[0])     # giữ đúng thứ tự từ điển
    extra = []
    for _, rx, vals in candidates:
        if rx.search(joined):
            extra.extend(vals)
    toks = toks + extra
    return LineIndex(toks, set(toks), set(zip(toks, toks[1:])), glued)


@dataclass
class Cov:
    value: float            # 0..1
    contrib: list           # chỉ số dòng đóng góp
    latin_ok: bool          # có ít nhất một cụm kỹ thuật khớp ≥50% (hoặc yêu cầu không có cụm kỹ thuật)


def coverage(units, lines: list[tuple[LineIndex, float]]) -> Cov:
    """lines: [(LineIndex, hệ số mục)]. Độ phủ có trọng số theo mục, tính theo từng đơn vị."""
    if not units:
        return Cov(0.0, [], True)
    contrib: set = set()
    f_unit = []
    for u in units:
        if u["kind"] == "latin":
            best_sum = 0.0
            for tok in u["toks"]:
                b, bi = 0.0, None
                for i, (li, f) in enumerate(lines):
                    if tok in li.tset:
                        g = f
                    elif li.glued and len(tok) >= 5 and any(tok in w for w in li.glued):
                        g = f * 0.9                       # từ khoá nằm trong chuỗi chữ dính ("strengtheningsoftwareengineeringskills")
                    else:
                        continue
                    if g > b:
                        b, bi = g, i
                best_sum += b
                if bi is not None:
                    contrib.add(bi)
            f_unit.append(best_sum / len(u["toks"]))
        else:
            s, best_sum = u["syl"], 0.0
            for k, syl in enumerate(s):
                b, bi = 0.0, None
                for i, (li, f) in enumerate(lines):
                    ok = (len(s) == 1 and syl in li.tset) or (k > 0 and (s[k - 1], syl) in li.bigrams) \
                        or (k < len(s) - 1 and (syl, s[k + 1]) in li.bigrams)
                    if ok and f > b:
                        b, bi = f, i
                best_sum += b
                if bi is not None:
                    contrib.add(bi)
            f_unit.append(best_sum / len(s))
    # nhóm lựa chọn: một lần, lấy đơn vị khớp tốt nhất, trọng số = lớn nhất trong nhóm
    slots: dict = {}
    for idx, (u, f) in enumerate(zip(units, f_unit)):
        key = ("g", u["g"]) if u["g"] is not None else ("u", idx)
        w0, f0 = slots.get(key, (0.0, 0.0))
        slots[key] = (max(w0, u["w"]), max(f0, f))
    total = sum(w for w, _ in slots.values())
    got = sum(w * f for w, f in slots.values())
    cov = got / total if total else 0.0
    lat = [f for u, f in zip(units, f_unit) if u["kind"] == "latin"]
    if lat and max(lat) == 0:
        cov = min(cov, 0.25)         # yêu cầu có từ kỹ thuật mà CV không có từ nào: tối đa điểm 1
    return Cov(cov, sorted(contrib), (not lat) or max(lat) >= 0.5)
