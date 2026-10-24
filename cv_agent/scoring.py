"""Engine LLM (TÙY CHỌN, tắt mặc định): Claude chấm từng tiêu chí, code kiểm chứng bằng chứng rồi dùng chung `aggregate`
với engine luật. Hệ thống chạy đầy đủ mà không cần file này."""
import re
from typing import Iterable

from .aggregate import FIT_THRESHOLD, MAYBE_THRESHOLD, aggregate
from .anonymize import anonymize
from .llm import call_structured
from .prompts import SCORING_PROMPT
from .schemas import Rubric, ScoringResult
from .textutil import norm, quote_in

__all__ = ["score_cv", "verify_evidence", "aggregate", "FIT_THRESHOLD", "MAYBE_THRESHOLD"]   # re-export để import cũ vẫn chạy


def verify_evidence(result: ScoringResult, cv_text: str) -> tuple[ScoringResult, dict]:
    """Evidence không có thật trong CV thì bị loại và điểm bị hạ."""
    cv_norm = norm(cv_text)
    total = dropped = 0

    for hc in result.hard_checks:
        if hc.evidence:
            total += 1
            if not quote_in(hc.evidence, cv_norm):
                dropped += 1
                hc.evidence = ""
                if hc.status == "met":
                    hc.status = "unclear"
                    hc.note += " [bằng chứng không khớp CV]"
        elif hc.status == "met":
            hc.status = "unclear"
            hc.note += " [không có bằng chứng]"

    for cs in result.criterion_scores:
        valid = [e for e in cs.evidence if quote_in(e, cv_norm)]
        total += len(cs.evidence)
        dropped += len(cs.evidence) - len(valid)
        cs.evidence = valid
        if cs.score >= 2 and not valid:
            cs.score = 1
            cs.reasoning += " [hạ điểm: không kiểm chứng được evidence]"
    return result, {"evidence_total": total, "evidence_dropped": dropped}


def score_cv(rubric: Rubric, cv_raw: str, names: Iterable[str] = ()) -> dict:
    cv_text = anonymize(cv_raw, names)
    prompt = SCORING_PROMPT.format(
        rubric_json=rubric.model_dump_json(indent=2, exclude={"jd_analysis"}),
        cv_text=re.sub(r"</?\s*(?:cv|rubric)\s*>", "", cv_text, flags=re.I),     # CV không được tự đóng thẻ <cv> để thoát khỏi vùng dữ liệu
    )
    result = call_structured(ScoringResult, prompt, max_tokens=5000)
    result, stats = verify_evidence(result, cv_text)
    return {"detail": result, "summary": aggregate(rubric, result), "stats": stats}
