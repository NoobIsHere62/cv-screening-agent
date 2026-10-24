"""Kết luận 4 mức cho HR, tính hoàn toàn từ điểm và các cờ của `aggregate` (không đụng kết luận 3 mức dùng để đo eval).

Quy tắc theo thứ tự:
  1. trượt điều kiện cứng, hoặc điểm < reject                        -> Loại
  2. đạt dưới CORE_MIN kỹ năng bắt buộc                              -> tối đa Dự phòng (tổng điểm cao nhờ số năm/bằng cấp không đủ)
  3. điểm >= fit và không còn điều kiện chưa rõ / kỹ năng bắt buộc 0 -> Phù hợp - Mời phỏng vấn
  4. điểm >= maybe                                                   -> Có thể mời phỏng vấn
  5. còn lại                                                         -> Dự phòng - Cân nhắc
"""
from .config import CORE_MIN, FIT_THRESHOLD, MAYBE_THRESHOLD, REJECT_THRESHOLD

FIT = "Phù hợp - Mời phỏng vấn"
MAYBE = "Có thể mời phỏng vấn"
RESERVE = "Dự phòng - Cân nhắc"
REJECT = "Loại"
ERROR = "LỖI"
ALL = [FIT, MAYBE, RESERVE, REJECT]
SUITABLE = (FIT, MAYBE)    # "danh sách phù hợp" = hai mức đầu

COLORS = {FIT: "C6EFCE", MAYBE: "DDEBF7", RESERVE: "FFEB9C", REJECT: "FFC7CE", ERROR: "D9D9D9"}


def check_thresholds(fit: float, maybe: float, reject: float) -> None:
    if not 0 <= reject < maybe < fit <= 100:
        raise ValueError(f"Ngưỡng phải thỏa 0 <= loại ({reject:g}) < có thể mời ({maybe:g}) < phù hợp ({fit:g}) <= 100")


def verdict(summary: dict, fit: float = FIT_THRESHOLD, maybe: float = MAYBE_THRESHOLD,
            reject: float = REJECT_THRESHOLD) -> str:
    score = summary.get("required_score", summary["overall_score"])      # mức đáp ứng yêu cầu bắt buộc (không tính điểm cộng)
    if summary["failed_hard"] or score < reject:
        return REJECT
    if summary.get("core_ratio", 1.0) < CORE_MIN:
        return RESERVE
    fully_verified = not (summary["unclear_hard"] or summary["required_zero"] or summary["missing_criteria"])
    if score >= fit and fully_verified:
        return FIT
    if score >= maybe:
        return MAYBE
    return RESERVE
