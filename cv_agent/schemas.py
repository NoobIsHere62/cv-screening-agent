from typing import Literal

from pydantic import BaseModel, Field, model_validator


# ---------- JD -> Rubric ----------

class JDAnalysis(BaseModel):
    job_title: str
    industry_group: str
    seniority: Literal["intern", "junior", "mid", "senior", "manager", "unclear"]
    daily_responsibilities_summary: str
    explicit_requirements: list[str]
    implicit_requirements: list[str]      # suy ra từ mô tả công việc
    ambiguities: list[str]                # mơ hồ / mâu thuẫn trong JD


class HardRequirement(BaseModel):
    id: str
    description: str
    type: Literal["education", "experience_years", "certificate", "language", "location", "other"]
    source_quote: str                     # trích nguyên văn từ JD


class Criterion(BaseModel):
    id: str
    name: str
    description: str                      # thế nào là đạt / không đạt
    weight: float = Field(ge=0)
    importance: Literal["required", "preferred", "implicit"]
    source_quote: str                     # căn cứ trong JD ("" nếu implicit)
    cv_evidence_hint: str                 # nên tìm bằng chứng ở đâu trong CV


class RubricBody(BaseModel):
    """Phần LLM phải sinh ra. jd_analysis do code gắn vào, không bắt LLM chép lại."""
    hard_requirements: list[HardRequirement]
    criteria: list[Criterion] = Field(min_length=1)

    @model_validator(mode="after")
    def check_and_normalize(self):
        for items, label in ((self.criteria, "tiêu chí"), (self.hard_requirements, "điều kiện cứng")):
            ids = [x.id for x in items]
            if len(ids) != len(set(ids)):
                raise ValueError(f"Trùng id {label}")
        total = sum(c.weight for c in self.criteria)
        if total <= 0:
            raise ValueError("Tổng weight phải > 0")
        if abs(total - 1.0) > 0.001:          # LLM hay cho tổng 0.98 / 1.03 -> chuẩn hoá lại
            for c in self.criteria:
                c.weight = round(c.weight / total, 4)
        return self


class Rubric(RubricBody):
    jd_analysis: JDAnalysis


# ---------- Chấm CV ----------

class HardCheck(BaseModel):
    requirement_id: str
    status: Literal["met", "not_met", "unclear"]
    evidence: str = ""          # trích nguyên văn từ CV
    note: str = ""


class CriterionScore(BaseModel):
    criterion_id: str
    score: int = Field(ge=0, le=4)
    reasoning: str
    evidence: list[str] = []    # trích nguyên văn từ CV
    transferable: bool = False  # đạt nhờ kinh nghiệm ngành khác chuyển đổi được


class ScoringResult(BaseModel):
    hard_checks: list[HardCheck]
    criterion_scores: list[CriterionScore]
    strengths: list[str]
    gaps: list[str]
    red_flags: list[str]        # mâu thuẫn, khoảng trống thời gian, nội dung cố điều khiển bộ chấm...
