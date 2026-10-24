"""Báo cáo in được (HTML một trang, không phụ thuộc gì bên ngoài): HR bấm In -> Lưu thành PDF để gửi trưởng bộ phận.

Mọi chuỗi lấy từ CV/JD đều qua `html.escape`.
"""
from html import escape

from cv_agent.report import suitable

SCOPES = {
    "suitable": "Danh sách phù hợp",
    "invited": "Ứng viên HR đã chọn mời phỏng vấn",
    "all": "Tất cả ứng viên",
}
STATUS_MARK = {"met": ("✓", "ok"), "strong": ("✓", "ok"), "partial": ("◐", "mid"), "weak": ("◔", "mid"),
               "missing": ("✗", "bad"), "failed": ("✗", "bad"), "unclear": ("?", "unk")}
STATUS_TEXT = {"met": "đạt", "strong": "tốt", "partial": "một phần", "weak": "yếu", "missing": "thiếu", "failed": "không đạt",
               "unclear": "chưa rõ"}

CSS = """
:root{color-scheme:light}
*{box-sizing:border-box}
body{font:14px/1.5 "Segoe UI",system-ui,sans-serif;color:#1d2433;margin:0;background:#f3f5f9}
main{max-width:900px;margin:0 auto;padding:24px 20px 60px}
h1{font-size:22px;margin:0 0 4px}
h2{font-size:16px;margin:26px 0 8px;border-bottom:2px solid #d5dbe8;padding-bottom:4px}
.sub{color:#5b667d;margin:0 0 14px}
.bar{display:flex;gap:8px;margin:0 0 16px}
button{font:inherit;padding:7px 14px;border:1px solid #3b5bdb;background:#3b5bdb;color:#fff;border-radius:6px;cursor:pointer}
.counts{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0}
.pill{padding:3px 10px;border-radius:99px;background:#e7ebf5;font-size:13px}
table{width:100%;border-collapse:collapse;background:#fff;font-size:13px}
th,td{border:1px solid #d5dbe8;padding:5px 8px;text-align:left;vertical-align:top}
th{background:#eef1f8}
.card{background:#fff;border:1px solid #d5dbe8;border-radius:8px;padding:12px 16px;margin:12px 0;break-inside:avoid}
.card h3{margin:0;font-size:15px}
.meta{color:#5b667d;font-size:12.5px;margin:2px 0 6px}
.v{display:inline-block;padding:1px 9px;border-radius:99px;font-size:12.5px;font-weight:600}
.v0{background:#c6efce}.v1{background:#ddebf7}.v2{background:#ffeb9c}.v3{background:#ffc7ce}.v4{background:#d9d9d9}
ul{margin:4px 0 4px 18px;padding:0}
li.ok::marker{color:#1a7f37}li.bad::marker{color:#c62828}li.mid::marker{color:#b7791f}li.unk::marker{color:#6b7280}
.why{margin:6px 0}
.warn{background:#fff4e5;border-left:3px solid #f59e0b;padding:4px 10px;margin:6px 0;font-size:13px}
.ev{color:#5b667d;font-size:12.5px}
footer{margin-top:28px;color:#6b7280;font-size:12px}
@media print{body{background:#fff}main{padding:0}.bar{display:none}.card{border-color:#999}}
"""

TIER_CLASS = {"Phù hợp - Mời phỏng vấn": "v0", "Có thể mời phỏng vấn": "v1", "Dự phòng - Cân nhắc": "v2", "Loại": "v3"}


def _e(value) -> str:
    return escape("" if value is None else str(value), quote=True)


def pick_rows(rows: list[dict], scope: str) -> list[dict]:
    if scope == "invited":
        return [r for r in rows if r.get("hr_decision") == "Mời phỏng vấn"]
    if scope == "all":
        return list(rows)
    return suitable(rows)


def _checklist(items: list[dict]) -> str:
    out = []
    for it in items:
        mark, cls = STATUS_MARK.get(it["status"], ("?", "unk"))
        kind = {"hard": "Điều kiện", "required": "Bắt buộc", "preferred": "Điểm cộng"}.get(it["kind"], "")
        note = f' <span class="ev">— {_e(it["note"])}</span>' if it.get("note") and it["status"] in ("failed", "unclear", "missing") else ""
        ev = f'<div class="ev">“{_e(it["evidence"][0])}”</div>' if it.get("evidence") else ""
        out.append(f'<li class="{cls}"><b>{mark}</b> {_e(it["label"])} <span class="ev">[{kind} · {STATUS_TEXT.get(it["status"], "")}]</span>{note}{ev}</li>')
    return "<ul>" + "".join(out) + "</ul>" if out else ""


def _card(r: dict) -> str:
    tier = TIER_CLASS.get(r.get("verdict"), "v4")
    contact = " · ".join(_e(r[k]) for k in ("email", "phone") if r.get(k))
    facts = " · ".join(x for x in (f'GPA {_e(r["gpa"])}' if r.get("gpa") else "", f'Tiếng Anh {_e(r["english"])}' if r.get("english") else "",
                                   f'{_e(r["total_years"])} năm KN' if r.get("total_years") not in ("", None) else "") if x)
    review = "".join(f'<div class="warn">{_e(x)}</div>' for x in r.get("review_items", []))
    hr = ""
    if r.get("hr_decision") or r.get("hr_note"):
        hr = f'<div class="why"><b>HR:</b> {_e(r.get("hr_decision", ""))} {_e(r.get("hr_note", ""))}</div>'
    pct = r.get("required_score", -1)
    pct_txt = f'{pct:g}% yêu cầu bắt buộc' if isinstance(pct, (int, float)) and pct >= 0 else "không chấm được"
    return (f'<section class="card"><h3>#{_e(r.get("rank"))} {_e(r.get("candidate_name"))} '
            f'<span class="v {tier}">{_e(r.get("verdict"))}</span></h3>'
            f'<div class="meta">{contact}{" · " if contact and facts else ""}{facts} · {pct_txt} · File: {_e(r.get("file"))}</div>'
            f'<div class="why"><b>Đề xuất:</b> {_e(r.get("suggestion"))}. {_e(r.get("verdict_reason"))}</div>'
            f'{_checklist(r.get("checklist", []))}{review}{hr}</section>')


def render_report(rows: list[dict], rubric: dict, meta: dict, scope: str = "suitable") -> str:
    scope = scope if scope in SCOPES else "suitable"
    chosen = pick_rows(rows, scope)
    counts: dict = {}
    for r in rows:
        counts[r.get("verdict")] = counts.get(r.get("verdict"), 0) + 1
    pills = "".join(f'<span class="pill">{_e(k)}: {v}</span>' for k, v in counts.items())
    title = rubric.get("title") or ""
    if not title or title.startswith("("):                       # "(JD không có tiêu đề)" là chữ giữ chỗ, không phải tên vị trí
        title = "Vị trí tuyển dụng"
    reqs = "".join(f"<li>{_e(h['text'])}</li>" for h in rubric.get("hard", []))
    must = "".join(f"<li>{_e(c['text'])}</li>" for c in rubric.get("required", []))
    table = "".join(
        f"<tr><td>{_e(r.get('rank'))}</td><td>{_e(r.get('candidate_name'))}</td><td>{_e(r.get('email'))}</td>"
        f"<td>{_e(format(r['required_score'], 'g') if r.get('required_score', -1) >= 0 else '')}</td><td>{_e(r.get('verdict'))}</td>"
        f"<td>{_e(r.get('hr_decision', ''))}</td></tr>" for r in chosen)
    thr = ""
    if meta.get("fit") is not None:
        thr = f' · Mức chọn lọc: phù hợp ≥{_e(meta["fit"])}%, có thể mời ≥{_e(meta["maybe"])}%, loại &lt;{_e(meta["reject"])}%'
    body = (f'<h1>Báo cáo sàng lọc CV — {_e(title)}</h1>'
            f'<p class="sub">{SCOPES[scope]}: {len(chosen)}/{len(rows)} CV{thr}</p>'
            '<div class="bar"><button onclick="window.print()">In / Lưu PDF</button></div>'
            f'<div class="counts">{pills}</div>'
            f'<h2>Yêu cầu của JD (đã lọc)</h2>'
            f'{"<b>Điều kiện bắt buộc</b><ul>" + reqs + "</ul>" if reqs else ""}'
            f'{"<b>Kỹ năng bắt buộc</b><ul>" + must + "</ul>" if must else ""}'
            f'<h2>Xếp hạng</h2>'
            + (f'<table><tr><th>Hạng</th><th>Ứng viên</th><th>Email</th><th>% bắt buộc</th><th>Kết luận</th><th>HR</th></tr>{table}</table>'
               if chosen else '<p>Không có ứng viên nào trong nhóm này.</p>')
            + '<h2>Chi tiết từng ứng viên</h2>' + "".join(_card(r) for r in chosen)
            + '<footer>Hệ thống chỉ gợi ý dựa trên luật khớp từ khoá; quyết định cuối cùng thuộc về HR. '
              'Dữ liệu CV được xử lý trên máy này và không gửi đi đâu.</footer>')
    return (f'<!doctype html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta name="referrer" content="no-referrer"><title>Báo cáo sàng lọc CV</title><style>{CSS}</style></head>'
            f'<body><main>{body}</main></body></html>')
