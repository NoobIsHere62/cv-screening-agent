"""GIAO DIỆN STREAMLIT CŨ (không còn được phát triển; giao diện chính là `python serve.py` ở thư mục gốc).

Chạy:  pip install -r requirements.txt  rồi  streamlit run app.py   (hoặc bấm đúp start.bat), từ thư mục legacy_streamlit.
Mặc định chạy bằng luật, không cần LLM và không cần internet; CV không rời khỏi máy.
"""
import io
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))        # tìm thấy gói cv_agent ở thư mục gốc

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from cv_agent import __version__, storage
from cv_agent.config import FIT_THRESHOLD, LLM_ENABLED, MAYBE_THRESHOLD, PRESETS, REJECT_THRESHOLD
from cv_agent.io_utils import SUPPORTED, read_text
from cv_agent.jd_filter import core_jd_text, dropped_notes
from cv_agent.pipeline import build_rubric, list_cv_files, screen
from cv_agent.report import count_by_verdict, suitable, write_csv, write_excel
from cv_agent.verdict import ALL, ERROR, SUITABLE, check_thresholds
from webui import components as ui
from webui import theme
from webui.charts import score_chart
from webui.theme import VERDICT_STYLE

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_JD = ROOT / "samples" / "jds" / "ai01.txt"
SAMPLE_CVS = ROOT / "samples" / "cvs_pdf"
CV_TYPES = [e[1:] for e in sorted(SUPPORTED)]
TAB_NAMES = ["① Mô tả công việc", "② CV ứng viên", "③ Kết quả"]
PAGE_SIZE = 10
HARD_ICON = {"education": "🎓", "experience_years": "⏱️", "language": "🌐", "certificate": "📜", "location": "📍", "other": "📌"}

st.set_page_config(page_title="Sàng lọc CV", page_icon="📄", layout="wide", initial_sidebar_state="expanded")
theme.inject()
ss = st.session_state


# ---------------------------------------------------------------- trạng thái
def init_state() -> None:
    ss.setdefault("fit", FIT_THRESHOLD)
    ss.setdefault("maybe", MAYBE_THRESHOLD)
    ss.setdefault("reject", REJECT_THRESHOLD)
    ss.setdefault("preset", "Cân bằng")
    ss.setdefault("run_id", 0)
    ss.setdefault("jd_text", "")
    ss.setdefault("folder", "")


def apply_preset() -> None:
    if ss.preset in PRESETS:
        ss.fit, ss.maybe, ss.reject = PRESETS[ss.preset]


def mark_custom() -> None:
    ss.preset = "Tùy chỉnh"


def use_sample() -> None:
    if SAMPLE_JD.exists():
        ss.jd_text = read_text(SAMPLE_JD)
    if SAMPLE_CVS.exists():
        ss.folder = str(SAMPLE_CVS)
    ss.pop("core_jd", None)
    ss.pop("jd_rubric", None)


def open_run(folder: Path) -> None:
    rows, rubric, meta = storage.load_run(folder)
    ss.rows, ss.rubric, ss.run_meta, ss.saved_to = rows, rubric, meta, str(folder)
    ss.run_id += 1
    ss.goto_tab = TAB_NAMES[2]


def filter_jd() -> None:
    """Lọc JD -> rubric + JD rút gọn. Lỗi người dùng được báo gọn, không văng traceback."""
    try:
        rb = build_rubric(ss.jd_text, "baseline")
    except (ValueError, RuntimeError) as e:
        ss.jd_error = str(e)
        return
    ss.jd_error = ""
    ss.jd_rubric, ss.core_jd, ss.core_jd_src = rb, core_jd_text(rb), ss.jd_text


def apply_core_edit() -> None:
    try:
        ss.jd_rubric = build_rubric(ss.core_jd, "baseline")
        ss.jd_error = ""
    except (ValueError, RuntimeError) as e:
        ss.jd_error = f"JD đã chỉnh chưa hợp lệ: {e}"


init_state()

# ---------------------------------------------------------------- thanh bên
with st.sidebar:
    st.markdown("### ⚙️ Thiết lập")
    st.radio("Mức độ chọn lọc", ["Nghiêm ngặt", "Cân bằng", "Rộng rãi", "Tùy chỉnh"], key="preset", on_change=apply_preset,
             help="Quyết định điểm tối thiểu để vào từng nhóm. Cân bằng là mặc định; chưa hiệu chỉnh bằng CV thật của công ty.")
    with st.expander("Tùy chỉnh ngưỡng điểm", expanded=ss.preset == "Tùy chỉnh"):
        st.slider("Từ mức này → Phù hợp, mời phỏng vấn", 0, 100, key="fit", on_change=mark_custom)
        st.slider("Từ mức này → Có thể mời phỏng vấn", 0, 100, key="maybe", on_change=mark_custom)
        st.slider("Dưới mức này → Loại", 0, 100, key="reject", on_change=mark_custom)
        st.caption("Ai trượt điều kiện bắt buộc vẫn bị loại dù điểm cao; điều kiện chưa xác minh được sẽ đưa vào danh sách cần người xem.")
    thresholds_ok = True
    try:
        check_thresholds(ss.fit, ss.maybe, ss.reject)
    except ValueError as e:
        thresholds_ok = False
        st.error(str(e))
    with st.expander("Nâng cao"):
        workers = st.slider("Số CV xử lý song song", 1, 8, 4)
        ocr = st.checkbox("Tự OCR PDF dạng ảnh/scan", value=True,
                          help="Chạy trên máy (Tesseract hoặc RapidOCR). Kết quả OCR luôn được gắn cờ cần xem lại.")
    engine = "baseline"
    if LLM_ENABLED:
        engine = st.radio("Engine chấm", ["baseline", "llm"], format_func=lambda x: "Luật" if x == "baseline" else "LLM (tùy chọn)")

    runs = storage.list_runs()
    if runs:
        st.markdown("### 🕘 Kết quả đã lưu")
        labels = {storage.describe_run(p): p for p in runs}
        pick = st.selectbox("Mở lại lần chạy trước", ["—"] + list(labels), label_visibility="collapsed")
        if pick != "—":
            st.button("Mở kết quả này", on_click=open_run, args=(labels[pick],), use_container_width=True)
    st.divider()
    st.caption(f"🔒 Chạy hoàn toàn trên máy này, CV không gửi ra ngoài.\n\nv{__version__}")

# ---------------------------------------------------------------- tiêu đề
st.markdown(ui.hero("Sàng lọc CV theo JD", "Lọc JD → chấm CV → xếp hạng → danh sách mời phỏng vấn. AI chỉ hỗ trợ, HR quyết định.",
                    "Không cần LLM · Riêng tư"), unsafe_allow_html=True)

goto = ss.pop("goto_tab", None)
tab_jd, tab_cv, tab_res = st.tabs(TAB_NAMES)


def switch_tab(name: str) -> None:
    """Streamlit chưa cho chọn tab bằng mã; bấm tab bằng một đoạn JS nhỏ để chuyển sang kết quả sau khi chạy xong."""
    index = TAB_NAMES.index(name)
    script = (f"<script>/*{ss.run_id}-{time.time()}*/setTimeout(()=>{{const t=DOC.querySelectorAll('[role=tab]');"
              f"if(t.length>{index})t[{index}].click();}},250);</script>")
    try:
        st.html(script.replace("DOC", "document"), unsafe_allow_javascript=True)
    except TypeError:                                    # bản Streamlit cũ: dùng iframe của components
        components.html(script.replace("DOC", "window.parent.document"), height=0)

# ================================================================ ① JD
with tab_jd:
    if not ss.get("rows") and not ss.jd_text.strip():
        st.markdown(ui.howto([("① Dán JD", "Dán hoặc tải mô tả công việc. Bấm “Lọc JD” để chỉ giữ điều kiện và kỹ năng cần thiết."),
                              ("② Thêm CV", "Kéo thả nhiều CV (PDF, DOCX, TXT) hoặc chọn thư mục CV trên máy."),
                              ("③ Xem kết quả", "Danh sách xếp hạng, lý do từng kết luận, CV nào cần HR xem lại, tải Excel.")]),
                    unsafe_allow_html=True)
        if SAMPLE_JD.exists() and SAMPLE_CVS.exists():
            st.button("✨ Dùng dữ liệu mẫu (JD kỹ sư AI + 9 CV) để thử ngay", on_click=use_sample)

    left, right = st.columns([1.1, 1], gap="large")
    with left:
        st.markdown('<div class="section-title">Mô tả công việc (JD)</div>', unsafe_allow_html=True)
        jd_file = st.file_uploader("Tải file JD", type=["txt", "docx", "pdf"], key="jd_file", label_visibility="collapsed")
        if jd_file is not None and ss.get("_jd_sig") != (jd_file.name, jd_file.size):
            with tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp) / Path(jd_file.name).name
                p.write_bytes(jd_file.getvalue())
                try:
                    ss.jd_text = read_text(p)                  # tự dò bảng mã UTF-8 / UTF-16 / Windows
                    ss._jd_sig = (jd_file.name, jd_file.size)
                except ValueError as e:
                    st.error(str(e))
        st.text_area("Nội dung JD", key="jd_text", height=330, label_visibility="collapsed",
                     placeholder="Dán JD vào đây, ví dụ:\nKỹ sư AI\nYêu cầu:\n- Python, PyTorch\n- Tốt nghiệp ĐH chuyên ngành CNTT\n- Có ít nhất 2 năm kinh nghiệm\nQuyền lợi: ...")
        b1, b2 = st.columns([2, 1])
        b1.button("🔎 Lọc JD", type="primary", on_click=filter_jd,
                  disabled=not ss.jd_text.strip(), use_container_width=True)
        if SAMPLE_JD.exists() and SAMPLE_CVS.exists():
            b2.button("✨ Dùng mẫu", on_click=use_sample, use_container_width=True)
        if ss.get("jd_error"):
            st.error(ss.jd_error)

    jd_changed = "core_jd" in ss and ss.get("core_jd_src") != ss.jd_text
    with right:
        st.markdown('<div class="section-title">JD đã lọc</div>', unsafe_allow_html=True)
        rb = ss.get("jd_rubric")
        if rb is None:
            st.markdown('<div class="card soft"><h4>Lọc JD để làm gì?</h4><div class="muted">JD thường có cả mô tả công việc, quyền lợi, '
                        'kỹ năng mềm và đôi khi yêu cầu về tuổi/giới tính. Bước này chỉ giữ lại <b>điều kiện bắt buộc</b>, '
                        '<b>kỹ năng cần có</b> và <b>điểm ưu tiên</b>, bỏ phần còn lại và cho bạn xem trước khi chấm CV.</div></div>',
                        unsafe_allow_html=True)
        else:
            if jd_changed:
                st.warning("JD gốc đã đổi sau lần lọc trước: bản bên dưới là của JD cũ và sẽ KHÔNG được dùng. Bấm “Lọc JD” lại.")
            required = [c for c in rb.criteria if c.importance == "required"]
            preferred = [c for c in rb.criteria if c.importance != "required"]
            notes = dropped_notes(rb)
            st.markdown(ui.kpi_row([("Điều kiện bắt buộc", len(rb.hard_requirements), "#B91C1C"), ("Kỹ năng bắt buộc", len(required), "#4F46E5"),
                                    ("Ưu tiên", len(preferred), "#15803D"), ("Đã lọc bỏ / lưu ý", len(notes), "#B45309")]), unsafe_allow_html=True)
            if rb.hard_requirements:
                st.markdown("**Điều kiện bắt buộc** (không đạt là bị loại)")
                st.markdown("".join(ui.chip(f"{HARD_ICON.get(h.type, '📌')} {h.source_quote}", "red") for h in rb.hard_requirements),
                            unsafe_allow_html=True)
            if required:
                st.markdown("**Kỹ năng bắt buộc**")
                st.markdown("".join(ui.chip(c.source_quote or c.name) for c in required), unsafe_allow_html=True)
            if preferred:
                st.markdown("**Ưu tiên (điểm cộng)**")
                st.markdown("".join(ui.chip(c.source_quote or c.name, "green") for c in preferred), unsafe_allow_html=True)
            for n in notes:
                st.markdown(ui.callout(n, "gray"), unsafe_allow_html=True)
            with st.expander("✏️ Chỉnh sửa JD đã lọc"):
                st.text_area("JD đã lọc", key="core_jd", height=230, label_visibility="collapsed")
                st.button("Áp dụng chỉnh sửa", on_click=apply_core_edit)
                st.caption("CV sẽ được chấm theo bản này. Mỗi dòng bắt đầu bằng “- ”; mục “Ưu tiên:” là điểm cộng.")

# ================================================================ ② CV
with tab_cv:
    cl, cr = st.columns(2, gap="large")
    with cl:
        st.markdown('<div class="section-title">🖱️ Kéo thả file CV</div>', unsafe_allow_html=True)
        uploads = st.file_uploader("CV", type=CV_TYPES, accept_multiple_files=True, key="cv_files", label_visibility="collapsed",
                                   help="PDF, DOCX, TXT. PDF dạng ảnh sẽ được OCR trên máy.")
    with cr:
        st.markdown('<div class="section-title">📁 Hoặc đọc từ thư mục trên máy</div>', unsafe_allow_html=True)
        st.text_input("Đường dẫn thư mục", key="folder", placeholder=r"D:\TuyenDung\CV_KeToan", label_visibility="collapsed")
        sub = st.checkbox("Bao gồm thư mục con")
        dir_files: list[Path] = []
        if ss.folder.strip():
            fp = Path(ss.folder.strip().strip('"'))
            if fp.is_dir():
                dir_files = list_cv_files(fp, sub)
                st.success(f"Tìm thấy {len(dir_files)} CV trong thư mục.")
            else:
                st.error("Thư mục không tồn tại (thư mục phải nằm trên máy đang chạy ứng dụng).")

    files_overview = ([{"File": f.name, "Loại": f.suffix.lower()[1:].upper(), "Dung lượng (KB)": round(f.stat().st_size / 1024, 1), "Nguồn": "Thư mục"}
                       for f in dir_files] +
                      [{"File": u.name, "Loại": Path(u.name).suffix[1:].upper(), "Dung lượng (KB)": round(u.size / 1024, 1), "Nguồn": "Kéo thả"}
                       for u in (uploads or [])])
    n_cv = len(files_overview)
    if files_overview:
        with st.expander(f"Danh sách {n_cv} CV sẽ xử lý", expanded=n_cv <= 12):
            st.dataframe(pd.DataFrame(files_overview), hide_index=True, width="stretch")

    ready_jd, ready_cv = bool(ss.jd_text.strip()), n_cv > 0
    st.markdown(f'<div class="card soft" style="margin-top:10px">'
                f'{"✅" if ready_jd else "⬜"} JD &nbsp;·&nbsp; {"✅" if ready_cv else "⬜"} {n_cv} CV &nbsp;·&nbsp; '
                f'Ngưỡng: Phù hợp ≥ <b>{ss.fit}</b>, Có thể mời ≥ <b>{ss.maybe}</b>, Loại &lt; <b>{ss.reject}</b>'
                f' &nbsp;<span class="muted">(chỉnh ở thanh bên)</span></div>', unsafe_allow_html=True)
    go = st.button("🚀 Bắt đầu sàng lọc", type="primary", disabled=not (ready_jd and ready_cv and thresholds_ok), use_container_width=True)
    if not ready_jd:
        st.info("Chưa có JD: quay lại tab ① để dán JD.")

    if go:
        started = time.time()
        jd_for_rubric = ss.jd_text if jd_changed else (ss.get("core_jd") or ss.jd_text)   # ưu tiên bản đã lọc (HR có thể đã sửa)
        try:
            rubric = build_rubric(jd_for_rubric, engine)
        except (ValueError, RuntimeError) as e:
            st.error(f"Không phân tích được JD: {e}")
            st.stop()
        with tempfile.TemporaryDirectory() as tmp, st.status("Đang sàng lọc CV…", expanded=True) as status:
            items = [(f.name, f) for f in dir_files]
            for i, up in enumerate(uploads or []):
                p = Path(tmp) / str(i) / Path(up.name).name         # thư mục riêng để hai CV trùng tên không ghi đè nhau
                p.parent.mkdir()
                p.write_bytes(up.getvalue())
                items.append((up.name, p))
            bar = st.progress(0.0)
            rows = screen(rubric, items, engine=engine, fit=ss.fit, maybe=ss.maybe, reject=ss.reject, workers=workers, ocr=ocr,
                          on_progress=lambda d, t, name: bar.progress(d / t, text=f"Đã xử lý {d}/{t} CV · {name}"))
            elapsed = time.time() - started
            status.update(label=f"Xong: {len(rows)} CV trong {elapsed:.1f} giây", state="complete", expanded=False)
        meta = {"elapsed": round(elapsed, 1), "fit": ss.fit, "maybe": ss.maybe, "reject": ss.reject}
        ss.rows, ss.rubric, ss.run_meta, ss.run_id = rows, rubric, meta, ss.run_id + 1
        try:
            ss.saved_to = str(storage.save_run(rows, rubric, core_jd_text(rubric), meta))
        except OSError as e:
            ss.saved_to = ""
            st.warning(f"Không lưu được kết quả vào ổ đĩa ({e}); hãy tải Excel ở tab ③.")
        ss.goto_tab = TAB_NAMES[2]
        st.rerun()


# ================================================================ ③ Kết quả
def persist_decisions() -> None:
    folder = ss.get("saved_to")
    if folder:
        try:
            storage.update_rows(Path(folder), ss.rows)
        except OSError:
            pass


def on_decision(i: int, kind: str) -> None:
    key = f"{kind}_{ss.run_id}_{i}"
    ss.rows[i]["hr_decision" if kind == "dec" else "hr_note"] = ss.get(key, "")
    persist_decisions()


def candidate_card(i: int, r: dict, fit: float, maybe: float, reject: float) -> None:
    color = VERDICT_STYLE.get(r["verdict"], ("#374151",))[0]
    with st.container(border=True):
        c_rank, c_main, c_score, c_dec = st.columns([0.45, 3.4, 1.7, 1.9], vertical_alignment="center")
        c_rank.markdown(f'<div class="cand-rank">{r["rank"]}</div>', unsafe_allow_html=True)
        facts = []
        if r.get("total_years") not in ("", None):
            facts.append(ui.chip(f"⏱ {r['total_years']} năm KN", "gray"))
        for key, icon in (("gpa", "🎓 GPA"), ("english", "🌐"), ("github", "💻")):
            if r.get(key):
                facts.append(ui.chip(f"{icon} {r[key]}", "gray"))
        if r.get("source", "").startswith("ocr"):
            facts.append(ui.chip("OCR", "amber"))
        contact = " · ".join(ui.esc(x) for x in (r.get("email"), r.get("phone")) if x)
        c_main.markdown(f'<p class="cand-name">{ui.esc(r["candidate_name"])}</p>'
                        f'<div class="cand-meta">{contact or "—"} · {ui.esc(r["file"])}</div>{"".join(facts)}', unsafe_allow_html=True)
        if r["verdict"] == ERROR:
            c_score.markdown(ui.badge(ERROR), unsafe_allow_html=True)
        else:
            c_score.markdown(ui.score_bar(r["overall_score"], fit, maybe, reject, color) + ui.badge(r["verdict"]), unsafe_allow_html=True)
        dkey, nkey = f"dec_{ss.run_id}_{i}", f"note_{ss.run_id}_{i}"
        ss.setdefault(dkey, r.get("hr_decision", ""))
        ss.setdefault(nkey, r.get("hr_note", ""))
        c_dec.selectbox("Quyết định của HR", storage.HR_DECISIONS, key=dkey, label_visibility="collapsed",
                        format_func=lambda x: x or "— Quyết định của HR —", on_change=on_decision, args=(i, "dec"))
        c_dec.text_input("Ghi chú", key=nkey, label_visibility="collapsed", placeholder="Ghi chú của HR…",
                         on_change=on_decision, args=(i, "note"))

        st.markdown(f'<div class="muted">💡 {ui.esc(r.get("verdict_reason", ""))}</div>', unsafe_allow_html=True)
        if r.get("review_reason"):
            st.markdown(ui.callout(r["review_reason"], "", "HR cần xem:"), unsafe_allow_html=True)
        if r.get("failed_hard"):
            st.markdown(ui.callout(r["failed_hard"], "red", "Trượt điều kiện bắt buộc:"), unsafe_allow_html=True)
        if r["verdict"] != ERROR:
            cols = st.columns(2)
            if r.get("strengths"):
                cols[0].markdown("**Điểm mạnh**<br>" + ui.chips(r["strengths"].split(" | "), "green", 6), unsafe_allow_html=True)
            if r.get("gaps"):
                cols[1].markdown("**Khoảng trống**<br>" + ui.chips(r["gaps"].split(" | "), "red", 6), unsafe_allow_html=True)
            with st.expander("Chi tiết điểm từng tiêu chí"):
                st.markdown(ui.criteria_table(r.get("criteria", [])), unsafe_allow_html=True)


@st.fragment
def results_view() -> None:
    rows = ss.get("rows")
    if not rows:
        st.markdown(ui.empty_state("📊", "Chưa có kết quả", "Thêm JD ở tab ① và CV ở tab ②, rồi bấm “Bắt đầu sàng lọc”. "
                                   "Hoặc mở lại một lần chạy đã lưu ở thanh bên."), unsafe_allow_html=True)
        return
    meta = ss.get("run_meta") or {}
    fit, maybe, reject = meta.get("fit", ss.fit), meta.get("maybe", ss.maybe), meta.get("reject", ss.reject)
    counts = count_by_verdict(rows)
    ok = suitable(rows)
    review = sum(r["needs_human_review"] == "CÓ" for r in rows)
    cards = [("Tổng số CV", len(rows), "#4F46E5")] + [(v, counts[v], VERDICT_STYLE[v][0]) for v in ALL]
    st.markdown(ui.kpi_row(cards), unsafe_allow_html=True)
    sub = f"✅ **{len(ok)}/{len(rows)}** CV trong danh sách phù hợp · ⚠️ **{review}** CV cần HR xem lại"
    if meta.get("elapsed") is not None:
        sub += f" · ⏱ {meta['elapsed']} giây"
    st.markdown(sub)
    if counts[ERROR]:
        st.error(f"{counts[ERROR]} CV bị lỗi (xem lý do ở thẻ ứng viên): thường là PDF scan không OCR được, file hỏng hoặc có mật khẩu.")
    if ss.get("saved_to"):
        st.caption(f"Đã tự lưu tại: {ss.saved_to}")

    t_list, t_chart, t_cmp, t_export = st.tabs(["📋 Danh sách ứng viên", "📊 Biểu đồ", "⚖️ So sánh", "⬇️ Xuất file"])

    with t_list:
        f1, f2, f3, f4 = st.columns([2.2, 2.4, 1.6, 1.6])
        query = f1.text_input("Tìm", placeholder="🔍 Tìm theo tên, email, kỹ năng…", label_visibility="collapsed", key="q")
        present = [v for v in ALL + [ERROR] if counts.get(v)]
        chosen = f2.multiselect("Kết luận", present, default=[v for v in SUITABLE if counts.get(v)] or present,
                                label_visibility="collapsed", placeholder="Lọc theo kết luận", key=f"vf_{ss.run_id}")
        only_review = f3.toggle("Chỉ CV cần xem lại", key="only_review")
        order = f4.selectbox("Sắp xếp", ["Điểm cao → thấp", "Tên A → Z", "Cần xem lại trước"], label_visibility="collapsed", key="order")
        if set(chosen) == set(v for v in SUITABLE if counts.get(v)) and chosen:
            st.caption("Đang xem **danh sách phù hợp**. Thêm “Dự phòng” hoặc “Loại” ở ô lọc để xem các CV còn lại.")
        indexed = [(i, r) for i, r in enumerate(rows) if r["verdict"] in chosen]
        if query.strip():
            q = query.strip().lower()
            indexed = [(i, r) for i, r in indexed if q in " ".join(str(r.get(k, "")) for k in
                                                                    ("candidate_name", "email", "phone", "file", "strengths", "gaps", "english")).lower()]
        if only_review:
            indexed = [(i, r) for i, r in indexed if r["needs_human_review"] == "CÓ"]
        if order == "Tên A → Z":
            indexed.sort(key=lambda t: t[1]["candidate_name"].lower())
        elif order == "Cần xem lại trước":
            indexed.sort(key=lambda t: (t[1]["needs_human_review"] != "CÓ", t[1]["rank"]))
        pages = max(1, -(-len(indexed) // PAGE_SIZE))
        page = 1
        if pages > 1:
            page = st.number_input(f"Trang (có {len(indexed)} CV, {PAGE_SIZE} CV mỗi trang)", 1, pages, 1, key="page")
        if not indexed:
            st.info("Không có CV nào khớp bộ lọc.")
        for i, r in indexed[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]:
            candidate_card(i, r, fit, maybe, reject)

    with t_chart:
        chart = score_chart(rows, fit, maybe, reject)
        if chart is None:
            st.info("Không có CV nào chấm được để vẽ biểu đồ.")
        else:
            st.altair_chart(chart, width="stretch")
            st.caption("Vạch đứt: các ngưỡng điểm. Rê chuột vào thanh để xem lý do kết luận.")

    with t_cmp:
        usable = [(i, r) for i, r in enumerate(rows) if r["verdict"] != ERROR]
        labels = {f"#{r['rank']} {r['candidate_name']}": r for _, r in usable}
        default = list(labels)[:3]
        pick = st.multiselect("Chọn 2–4 ứng viên để so sánh", list(labels), default=default, max_selections=4, key=f"cmp_{ss.run_id}")
        if len(pick) >= 2:
            chosen_rows = [labels[p] for p in pick]
            summary = {"Điểm tổng": [str(r["overall_score"]) for r in chosen_rows], "Kết luận": [r["verdict"] for r in chosen_rows],
                       "Kinh nghiệm (năm)": [str(r.get("total_years", "")) for r in chosen_rows],
                       "GPA": [r.get("gpa", "") for r in chosen_rows], "Ngoại ngữ": [r.get("english", "") for r in chosen_rows]}
            st.dataframe(pd.DataFrame(summary, index=pick).T, width="stretch")
            crit_names = [f"{k + 1}. {c[0]}" for k, c in enumerate(chosen_rows[0]["criteria"])]
            scores = {name: [int(r["criteria"][k][1]) if k < len(r["criteria"]) else 0 for r in chosen_rows] for k, name in enumerate(crit_names)}
            heat = {0: "#FEE2E2", 1: "#FEF3C7", 2: "#FEF9C3", 3: "#DCFCE7", 4: "#BBF7D0"}
            st.dataframe(pd.DataFrame(scores, index=pick).T.style.map(lambda v: f"background-color: {heat.get(v, '#fff')}; color: #1F2937"),
                         width="stretch")
            st.caption("Điểm từng tiêu chí: 0 = không thấy bằng chứng … 4 = vượt yêu cầu.")
        else:
            st.info("Chọn ít nhất 2 ứng viên.")

    with t_export:
        xlsx = io.BytesIO()
        write_excel(rows, xlsx)
        e1, e2 = st.columns(2)
        e1.download_button("⬇️ Tải Excel (có sheet danh sách phù hợp)", xlsx.getvalue(), file_name="ketqua_sanglọc.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True, type="primary")
        with tempfile.TemporaryDirectory() as tmp:
            write_csv(rows, Path(tmp) / "r.csv")
            e2.download_button("⬇️ Tải CSV", (Path(tmp) / "r.csv").read_bytes(), file_name="ranking.csv", mime="text/csv", use_container_width=True)
        invited = [r for r in rows if r.get("hr_decision") == "Mời phỏng vấn"] or ok
        emails = [r["email"] for r in invited if r.get("email")]
        label = "đã chọn “Mời phỏng vấn”" if any(r.get("hr_decision") == "Mời phỏng vấn" for r in rows) else "trong danh sách phù hợp"
        st.markdown(f'<div class="section-title">✉️ Email của ứng viên {label} ({len(emails)})</div>', unsafe_allow_html=True)
        if emails:
            st.code("; ".join(emails), language=None)
            st.caption("Bấm biểu tượng sao chép ở góc phải rồi dán vào ô “Đến/Bcc” của email.")
        else:
            st.info("Chưa có email nào để liệt kê.")


with tab_res:
    results_view()

if goto:
    switch_tab(goto)
