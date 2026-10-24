"""Các đoạn HTML nhỏ dùng trong giao diện. MỌI chuỗi lấy từ CV/JD đều phải đi qua `esc()` trước khi chèn vào HTML,
vì tên, email, bằng chứng... do người nộp CV viết và không đáng tin."""
import html
from typing import Iterable

from .theme import VERDICT_STYLE


def esc(text) -> str:
    return html.escape("" if text is None else str(text), quote=True)


def md_esc(text) -> str:
    """Escape ký tự đặc biệt của Markdown (khi bắt buộc dùng st.markdown/st.caption với chuỗi từ CV)."""
    s = "" if text is None else str(text)
    for ch in "\\`*_{}[]()#+-.!|<>~$":
        s = s.replace(ch, "\\" + ch)
    return s


def badge(text: str) -> str:
    color, bg, icon = VERDICT_STYLE.get(text, ("#374151", "#F3F4F6", ""))
    return f'<span class="badge" style="color:{color};background:{bg}">{icon} {esc(text)}</span>'


def chip(text, kind: str = "") -> str:
    return f'<span class="chip {kind}">{esc(text)}</span>'


def chips(items: Iterable, kind: str = "", limit: int = 8) -> str:
    items = [i for i in items if i]
    shown = "".join(chip(i, kind) for i in items[:limit])
    return shown + (chip(f"+{len(items) - limit}", "gray") if len(items) > limit else "")


def kpi(label: str, value, color: str = "#4F46E5") -> str:
    return f'<div class="kpi" style="--c:{color}"><div class="n">{esc(value)}</div><div class="l">{esc(label)}</div></div>'


def kpi_row(cards: list[tuple]) -> str:
    return '<div class="kpi-row">' + "".join(kpi(*c) for c in cards) + "</div>"


def score_bar(score: float, fit: float, maybe: float, reject: float, color: str) -> str:
    """Thanh điểm 0-100 kèm vạch ngưỡng (loại / có thể mời / phù hợp)."""
    pct = max(0.0, min(100.0, float(score)))
    ticks = "".join(f'<span class="tick" style="left:{t:g}%"></span>' for t in (reject, maybe, fit))
    return (f'<div class="scoretxt" style="color:{color}">{pct:g}<span class="muted" style="font-weight:500"> / 100</span></div>'
            f'<div class="scorebar"><span class="fill" style="width:{pct}%;background:{color}"></span>{ticks}</div>')


def dots(score: int, total: int = 4) -> str:
    return '<span class="dots">' + "".join(f'<span class="{"on" if i < score else ""}"></span>' for i in range(total)) + "</span>"


def callout(text: str, kind: str = "", title: str = "") -> str:
    head = f"<b>{esc(title)}</b><br>" if title else ""
    body = "<br>".join(esc(line) for line in str(text).split("\n"))
    return f'<div class="callout {kind}">{head}{body}</div>'


def empty_state(icon: str, title: str, body: str) -> str:
    return f'<div class="empty"><div class="big">{icon}</div><h3>{esc(title)}</h3><div>{esc(body)}</div></div>'


def hero(title: str, subtitle: str, pill: str) -> str:
    return (f'<div class="app-hero"><div class="logo">📄</div><div><h1>{esc(title)}</h1><p>{esc(subtitle)}</p></div>'
            f'<div class="pill">{esc(pill)}</div></div>')


def howto(steps: list[tuple[str, str]]) -> str:
    return '<div class="howto">' + "".join(
        f'<div class="step"><b>{esc(t)}</b><div class="muted">{esc(d)}</div></div>' for t, d in steps) + "</div>"


def criteria_table(criteria: list) -> str:
    """criteria: [(tên tiêu chí, điểm 0-4, lý do, [bằng chứng])]"""
    out = []
    for name, score, reasoning, evidence in criteria:
        quotes = "".join(f'<div class="quote">“{esc(e)}”</div>' for e in (evidence or [])[:3])
        out.append(f'<div class="crit-row"><div><b>{esc(name)}</b></div><div>{dots(int(score))} <span class="muted">{int(score)}/4</span></div>'
                   f'<div>{esc(reasoning)}{quotes}</div></div>')
    return "".join(out)
