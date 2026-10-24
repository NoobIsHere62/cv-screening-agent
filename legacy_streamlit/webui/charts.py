"""Biểu đồ điểm các ứng viên (Altair có sẵn cùng Streamlit)."""
import altair as alt
import pandas as pd

from .theme import VERDICT_STYLE


def score_chart(rows: list[dict], fit: float, maybe: float, reject: float, max_rows: int = 40):
    """Thanh ngang điểm từng ứng viên, tô màu theo kết luận, kèm vạch ngưỡng."""
    data = [{"Ứng viên": f"#{r['rank']} {r['candidate_name']}", "Điểm": r["overall_score"], "Kết luận": r["verdict"],
             "Lý do": r.get("verdict_reason", "")}
            for r in rows if r["overall_score"] >= 0][:max_rows]
    if not data:
        return None
    df = pd.DataFrame(data)
    verdicts = list(VERDICT_STYLE)
    bars = alt.Chart(df).mark_bar(cornerRadiusEnd=4, height=18).encode(
        x=alt.X("Điểm:Q", scale=alt.Scale(domain=[0, 100]), title="Điểm (0–100)"),
        y=alt.Y("Ứng viên:N", sort=None, title=None, axis=alt.Axis(labelLimit=260)),
        color=alt.Color("Kết luận:N", scale=alt.Scale(domain=verdicts, range=[VERDICT_STYLE[v][0] for v in verdicts]),
                        legend=alt.Legend(orient="bottom", title=None)),
        tooltip=["Ứng viên", "Điểm", "Kết luận", "Lý do"])
    marks = pd.DataFrame({"x": [reject, maybe, fit], "nhãn": [f"Loại < {reject:g}", f"Có thể mời ≥ {maybe:g}", f"Phù hợp ≥ {fit:g}"]})
    rules = alt.Chart(marks).mark_rule(strokeDash=[5, 4], color="#6B7280").encode(x="x:Q")
    labels = alt.Chart(marks).mark_text(align="left", dx=3, dy=-4, baseline="bottom", fontSize=10, color="#6B7280").encode(
        x="x:Q", y=alt.value(0), text="nhãn:N")
    return (bars + rules + labels).properties(height=max(120, 28 * len(df) + 60))
