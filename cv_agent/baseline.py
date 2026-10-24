"""Baseline KHÔNG dùng LLM: luật + khớp từ khoá (tuỳ chọn thêm embedding).

  jd_rules.py : JD -> rubric        cv_parse.py : tách mục CV, mốc thời gian, điều kiện cứng
  nlp.py      : đơn vị so khớp, độ phủ      lexicon.py : từ điển viết tay (mở rộng bằng lexicon_user.json)

Điểm và kết luận do cùng hàm `aggregate` của bản LLM tính, nên so sánh được công bằng.

Giới hạn đã biết (đây là lý do cần LLM): không hiểu "tương đương" ngoài từ điển; khớp từ khoá nên có thể khớp
nhầm khi CV nhắc từ khoá ngoài ngữ cảnh; bỏ qua yêu cầu về tính cách vì không kiểm chứng được từ CV.
"""
import re
from typing import Iterable, Optional

from .aggregate import aggregate
from .anonymize import anonymize
from .config import SCORE_CUTS, SECTION_FACTOR
from .cv_parse import (check_education, check_experience, employment_gaps, invalid_date_ranges, normalize_dates,
                       parse_blocks, split_cv)
from .jd_rules import build_rubric_rules, parse_min_years
from .lang_check import best_certificate, check_language
from .nlp import coverage, index_line, looks_accentless, query_units
from .schemas import CriterionScore, HardCheck, Rubric, ScoringResult
from .textutil import clean_text

__all__ = ["build_rubric_rules", "score_cv_baseline", "make_embedder", "SCORE_CUTS", "SECTION_FACTOR"]

# Khoảng cosine map về [0,1]. ĐÂY LÀ SỐ ƯỚC LƯỢNG, chưa kiểm chứng: hãy in thử vài cặp câu rồi chỉnh.
EMB_RANGES = {"intfloat/multilingual-e5-small": (0.75, 0.90), "BAAI/bge-m3": (0.35, 0.75)}
DEFAULT_EMB_MODEL = "intfloat/multilingual-e5-small"

INJECTION = re.compile(r"bỏ qua (?:mọi |tất cả )?hướng dẫn|ignore (?:all |previous |the above )|điểm tối đa|"
                       r"hệ thống chấm|system prompt|bộ chấm", re.I)


def to_score(v: float) -> int:
    return sum(v >= c for c in SCORE_CUTS)


def _short(text: str, n: int = 40) -> str:
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + "…"


def make_embedder(model_name: Optional[str] = None):
    """Hàm (query, text) -> độ tương đồng đã map về [0,1]. Cần: pip install sentence-transformers"""
    from sentence_transformers import SentenceTransformer
    name = model_name or DEFAULT_EMB_MODEL
    lo, hi = EMB_RANGES.get(name, (0.3, 0.8))
    model = SentenceTransformer(name)
    cache: dict = {}
    e5 = "e5" in name.lower()

    def enc(t: str, prefix: str):
        key = prefix + t
        if key not in cache:
            cache[key] = model.encode(key, normalize_embeddings=True)
        return cache[key]

    def sim(q: str, t: str) -> float:
        import numpy as np
        c = float(np.dot(enc(q, "query: " if e5 else ""), enc(t, "passage: " if e5 else "")))
        return min(1.0, max(0.0, (c - lo) / (hi - lo)))
    return sim


def _windows(content: list[dict], size: int = 3):
    """Cửa sổ tối đa `size` dòng liên tiếp cùng mục (chỉ dùng cho độ tương đồng embedding)."""
    for a in range(len(content)):
        for k in range(1, size + 1):
            win = content[a:a + k]
            if len(win) == k and len({l["section"] for l in win}) == 1:
                yield win


def score_criterion(query: str, content: list[dict], index: list, accentless: bool, embedder=None):
    """-> (độ phủ có hệ số mục, dòng bằng chứng, độ phủ riêng ở kinh nghiệm, cờ 'chỉ thấy ở danh sách kỹ năng').
    Độ phủ tính theo từng cụm từ trên toàn CV: mỗi cụm lấy dòng khớp tốt nhất (hệ số mục của dòng đó),
    nên bằng chứng nằm ở nhiều mục (MISA ở kinh nghiệm, Excel ở kỹ năng) vẫn được cộng lại."""
    units = query_units(query, accentless)
    pairs = [(index[i], SECTION_FACTOR.get(l["section"], 0.7)) for i, l in enumerate(content)]
    c = coverage(units, pairs)
    val = c.value
    if embedder is not None and content:
        emb = max(embedder(query, " ".join(l["text"] for l in w)) for w in _windows(content))
        val = 0.5 * val + 0.5 * emb
    evidence = [content[i]["text"] for i in c.contrib]
    exp_pairs = [(index[i], 1.0) for i, l in enumerate(content) if l["section"] in ("exp", "other", "project")]
    cov_exp = coverage(units, exp_pairs).value if exp_pairs else 0.0
    has_tool = any(u["kind"] == "latin" for u in units)
    skills_only = bool(has_tool and c.contrib and all(content[i]["section"] == "skills" for i in c.contrib))
    return val, evidence or ([content[0]["text"]] if content else []), cov_exp, skills_only


def score_cv_baseline(rubric: Rubric, cv_raw: str, names: Iterable[str] = (), embedder=None, uncertain: bool = False) -> dict:
    """uncertain=True: văn bản đến từ OCR. Chữ/số OCR có thể sai (TOEIC 850 thành 550), nên KHÔNG tự động loại vì trượt điều kiện cứng:
    chuyển thành "chưa xác minh" để HR kiểm tra."""
    anon = anonymize(clean_text(cv_raw), names)
    cv_text = normalize_dates(anon)
    accentless = looks_accentless(cv_text)
    lines = split_cv(cv_text)
    content = [l for l in lines if l["section"] != "head"]
    index = [index_line(l["text"], accentless) for l in content]
    blocks = parse_blocks(lines)

    claimed = None
    if not blocks:                                      # không đọc được mốc thời gian: chỉ còn lời tự khai, chưa kiểm chứng
        claimed = parse_min_years(cv_text)

    hard_checks, yrs_info = [], None
    for h in rubric.hard_requirements:
        if h.type == "education":
            hc = check_education(h.source_quote, lines, accentless, loose=uncertain)
        elif h.type == "experience_years":
            hc, yrs, titles = check_experience(h.source_quote, blocks, accentless)
            need = parse_min_years(h.source_quote) or 0.0
            if claimed:
                yrs = min(claimed, need * 0.99) if need else claimed
                hc.note = f"CV tự ghi ~{claimed:g} năm kinh nghiệm, không có mốc thời gian để kiểm chứng"
            yrs_info = (yrs, titles)
        elif h.type == "language":
            hc = check_language(h.source_quote, anon)       # anon: chưa đổi định dạng ngày, "TOEIC 790 (01/2026)" còn nguyên
        else:
            hc = HardCheck(requirement_id="", status="unclear", note="Baseline chưa kiểm tra loại điều kiện này")
        hc.requirement_id = h.id
        if uncertain and hc.status == "not_met":
            hc.status, hc.note = "unclear", f"{hc.note} (CV đọc bằng OCR, cần đối chiếu với file gốc trước khi loại)".strip()
        hard_checks.append(hc)

    cert_label, cert_eq = best_certificate(anon)
    cert_line = next((l.strip() for l in anon.splitlines() if cert_label and cert_label.split()[0].lower() in l.lower()), cert_label)
    crit_scores, strengths, gaps, flags = [], [], [], []
    for c in rubric.criteria:
        need = parse_min_years(c.source_quote)
        if need and yrs_info is not None and any(h.type == "experience_years" and h.source_quote == c.source_quote
                                                  for h in rubric.hard_requirements):
            ratio = yrs_info[0] / need
            sc = 0 if ratio < 0.25 else 1 if ratio < 0.5 else 2 if ratio < 1 else 3 if ratio < 1.5 else 4
            crit_scores.append(CriterionScore(criterion_id=c.id, score=sc, evidence=yrs_info[1][:2],
                                              reasoning=f"~{yrs_info[0]:.1f} năm kinh nghiệm liên quan / yêu cầu {need:g}"))
        else:
            cov, ev, cov_exp, skills_only = score_criterion(c.source_quote, content, index, accentless, embedder)
            sc = to_score(cov)
            note = ""
            if sc >= 2 and skills_only and cov_exp < 0.15:
                # đúng thang chấm: 1 = "chỉ nhắc đến, không có minh chứng". Kỹ năng chỉ liệt kê trong danh sách kỹ năng, không xuất hiện
                # trong kinh nghiệm/dự án, thì không thể được 2 điểm trở lên (chống nhồi từ khoá).
                sc, note = 1, " (chỉ thấy trong danh sách kỹ năng, chưa có minh chứng trong kinh nghiệm/dự án: tối đa 1 điểm)"
                flags.append(f"'{_short(c.name)}' chỉ thấy trong danh sách kỹ năng, không có minh chứng trong kinh nghiệm/dự án")
            if re.search(r"english|tiếng anh", c.source_quote, re.I) and cert_eq >= 550 and sc < (3 if cert_eq >= 650 else 2):
                # yêu cầu về tiếng Anh: chứng chỉ TOEIC/IELTS/TOEFL trong CV là bằng chứng mạnh hơn độ phủ từ khoá
                sc, ev = (3 if cert_eq >= 650 else 2), [cert_line] + ev
                note = f" (CV có chứng chỉ {cert_label})"
            crit_scores.append(CriterionScore(criterion_id=c.id, score=sc, evidence=ev[:3] if sc >= 1 else [],
                                              reasoning=f"Mức CV đáp ứng yêu cầu này (theo từ khoá): {cov:.0%}{note}"))
        s = crit_scores[-1].score
        if s >= 3:
            strengths.append(c.name)
        elif s <= 1:
            gaps.append(c.name)

    flags += employment_gaps(blocks)
    flags += [f"Khoảng thời gian không hợp lý, không được tính vào số năm kinh nghiệm: {d}" for d in invalid_date_ranges(lines)]
    if INJECTION.search(cv_text):
        flags.append("CV chứa câu có vẻ nhắm vào bộ chấm tự động (baseline không bị ảnh hưởng)")
    if accentless:
        flags.append("CV viết không dấu: baseline kém chính xác hơn, cần người xem lại")
    if not blocks:
        flags.append("Không đọc được mốc thời gian làm việc trong CV")

    result = ScoringResult(hard_checks=hard_checks, criterion_scores=crit_scores,
                           strengths=strengths, gaps=gaps, red_flags=flags)
    n_ev = sum(len(s.evidence) for s in crit_scores)
    return {"detail": result, "summary": aggregate(rubric, result),
            "stats": {"evidence_total": n_ev, "evidence_dropped": 0}}      # evidence luôn là dòng thật trong CV
