"""Gom điểm từng tiêu chí thành điểm tổng và kết luận 3 mức. KHÔNG phụ thuộc LLM nên cả hai engine dùng chung.

eval.py và calibrate.py đo trên kết luận 3 mức này; kết luận 4 mức cho HR nằm ở verdict.py.
"""
from .config import CORE_MIN_ITEMS, FIT_THRESHOLD, MAYBE_THRESHOLD
from .schemas import Rubric, ScoringResult

__all__ = ["aggregate", "FIT_THRESHOLD", "MAYBE_THRESHOLD"]


def aggregate(rubric: Rubric, result: ScoringResult, fit: float = None, maybe: float = None) -> dict:
    """Điểm và kết luận do code tính. fit/maybe cho phép ghi đè ngưỡng (vd khi hiệu chỉnh)."""
    fit = FIT_THRESHOLD if fit is None else fit
    maybe = MAYBE_THRESHOLD if maybe is None else maybe
    scores = {s.criterion_id: s for s in result.criterion_scores}
    missing = [c.id for c in rubric.criteria if c.id not in scores]       # tiêu chí không được chấm
    total = sum(c.weight * scores[c.id].score / 4 for c in rubric.criteria if c.id in scores)
    overall = round(total * 100, 1)                          # điểm xếp hạng: gồm cả kỹ năng ưu tiên (điểm cộng)
    req_all = [c for c in rubric.criteria if c.importance == "required" and c.id in scores]
    req_weight = sum(c.weight for c in req_all)
    # Mức đáp ứng YÊU CẦU BẮT BUỘC (không tính điểm cộng): đây mới là thước đo để quyết định mời hay không.
    # Điểm cộng chỉ nên giúp xếp hạng, không được làm ai đó "đủ điều kiện" hay "thiếu điều kiện".
    required_score = round(sum(c.weight * scores[c.id].score / 4 for c in req_all) / req_weight * 100, 1) if req_weight else overall

    hard = {h.requirement_id: h.status for h in result.hard_checks}
    failed = [r.id for r in rubric.hard_requirements if hard.get(r.id) == "not_met"]
    unclear = [r.id for r in rubric.hard_requirements if hard.get(r.id, "unclear") == "unclear"]
    required_zero = [
        c.id for c in rubric.criteria
        if c.importance == "required" and c.id in scores and scores[c.id].score == 0
    ]

    years_quotes = {h.source_quote for h in rubric.hard_requirements if h.type == "experience_years"}
    required = [c for c in rubric.criteria                    # kỹ năng cốt lõi: bỏ tiêu chí số năm (đã có điều kiện cứng lo)
                if c.importance == "required" and c.id in scores and c.source_quote not in years_quotes]
    core_ratio = sum(scores[c.id].score >= 2 for c in required) / len(required) if len(required) >= CORE_MIN_ITEMS else 1.0

    if failed:
        decision = "Không phù hợp"
    elif required_score >= fit:
        decision = "Cân nhắc" if (unclear or required_zero or missing) else "Phù hợp"
    elif required_score >= maybe:
        decision = "Cân nhắc"
    else:
        decision = "Không phù hợp"

    return {
        "overall_score": overall,
        "required_score": required_score,
        "decision": decision,
        "failed_hard": failed,
        "unclear_hard": unclear,
        "required_zero": required_zero,
        "core_ratio": round(core_ratio, 3),
        "missing_criteria": missing,
    }
