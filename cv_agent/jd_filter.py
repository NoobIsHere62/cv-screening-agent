"""Lọc JD: giữ lại điều kiện + kỹ năng cần thiết, bỏ phần còn lại (mô tả công việc, quyền lợi, kỹ năng mềm,
yêu cầu phân biệt đối xử), rồi in lại thành một JD chuẩn để HR đọc/sửa trước khi chấm.

JD chuẩn dùng đúng cú pháp mà `build_rubric_rules` đọc được: sửa tay xong đưa lại vào là có rubric tương ứng.
"""
from .schemas import Rubric


def core_jd_text(rubric: Rubric) -> str:
    """Rubric -> JD rút gọn: 'Yêu cầu:' (điều kiện cứng + kỹ năng bắt buộc) và 'Ưu tiên:' (điểm cộng)."""
    title = rubric.jd_analysis.job_title
    req = [h.source_quote for h in rubric.hard_requirements]
    seen = set(req)
    req += [c.source_quote for c in rubric.criteria if c.importance == "required" and c.source_quote not in seen]
    pref = [c.source_quote for c in rubric.criteria if c.importance != "required" and c.source_quote]
    lines = [title if not title.startswith("(") else "Vị trí tuyển dụng", ""]
    lines += ["Yêu cầu:"] + [f"- {t}" for t in req]
    if pref:
        lines += ["", "Ưu tiên:"] + [f"- {t}" for t in pref]
    return "\n".join(lines) + "\n"


def dropped_notes(rubric: Rubric) -> list[str]:
    """Những gì đã bị lọc bỏ khỏi JD (để HR kiểm tra không bỏ sót yêu cầu quan trọng)."""
    return list(rubric.jd_analysis.ambiguities)
