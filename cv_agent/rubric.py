import re

from .llm import call_structured
from .prompts import JD_ANALYSIS_PROMPT, RUBRIC_PROMPT
from .schemas import JDAnalysis, Rubric, RubricBody
from .textutil import norm, quote_in


def _clean_jd(jd_text: str) -> str:
    return re.sub(r"</?\s*(?:jd|analysis)\s*>", "", jd_text, flags=re.I)      # JD không được tự đóng thẻ <jd>


def analyze_jd(jd_text: str) -> JDAnalysis:
    """Bước 1: đọc hiểu JD, chưa tạo tiêu chí."""
    return call_structured(JDAnalysis, JD_ANALYSIS_PROMPT.format(jd_text=jd_text))


def verify_rubric(body: RubricBody, jd_text: str) -> list[str]:
    """Bước 3: kiểm tra bằng code. Mọi source_quote phải có thật trong JD."""
    jd_norm = norm(jd_text)
    problems = []
    for h in body.hard_requirements:
        if not quote_in(h.source_quote, jd_norm):
            problems.append(f"Điều kiện cứng {h.id}: source_quote không có trong JD: {h.source_quote!r}")
    for c in body.criteria:
        if c.importance != "implicit" and not quote_in(c.source_quote, jd_norm):
            problems.append(f"Tiêu chí {c.id} ({c.importance}): source_quote không có trong JD: {c.source_quote!r}")
    return problems


def build_rubric(jd_text: str, max_fix: int = 2) -> Rubric:
    """JD -> phân tích -> rubric -> kiểm tra quote. Quote giả thì gửi lỗi cho LLM sửa."""
    jd_text = _clean_jd(jd_text)
    analysis = analyze_jd(jd_text)
    feedback = ""
    problems: list[str] = []
    for _ in range(max_fix + 1):
        body = call_structured(
            RubricBody,
            RUBRIC_PROMPT.format(
                jd_text=jd_text,
                analysis_json=analysis.model_dump_json(indent=2),
                feedback=feedback,
            ),
            max_tokens=6000,
        )
        problems = verify_rubric(body, jd_text)
        if not problems:
            return Rubric(jd_analysis=analysis, **body.model_dump())
        feedback = "\nLần trước có lỗi, hãy sửa:\n- " + "\n- ".join(problems) + "\n"
    raise ValueError("Rubric vẫn còn quote không khớp JD sau khi sửa:\n- " + "\n- ".join(problems))
