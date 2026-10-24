"""Giao diện: bảng màu và CSS. Không tải font hay tài nguyên từ internet (ứng dụng chạy cục bộ, riêng tư)."""
import streamlit as st

PRIMARY = "#4F46E5"
INK = "#1F2937"
MUTED = "#6B7280"
LINE = "#E5E7EB"
SOFT = "#F5F7FB"

# kết luận -> (màu chữ/viền, màu nền, biểu tượng)
VERDICT_STYLE = {
    "Phù hợp - Mời phỏng vấn": ("#15803D", "#DCFCE7", "✅"),
    "Có thể mời phỏng vấn": ("#1D4ED8", "#DBEAFE", "🔵"),
    "Dự phòng - Cân nhắc": ("#B45309", "#FEF3C7", "🟡"),
    "Loại": ("#B91C1C", "#FEE2E2", "⛔"),
    "LỖI": ("#4B5563", "#E5E7EB", "⚠️"),
}

CSS = f"""
<style>
:root {{ --primary: {PRIMARY}; --ink: {INK}; --muted: {MUTED}; --line: {LINE}; --soft: {SOFT}; }}
html, body, [class*="css"] {{ font-family: "Segoe UI", "Inter", system-ui, -apple-system, sans-serif; }}
.block-container {{ padding-top: 1.4rem; padding-bottom: 4rem; max-width: 1280px; }}
header[data-testid="stHeader"] {{ background: transparent; }}
#MainMenu, footer {{ visibility: hidden; }}

/* ---- tiêu đề trang */
.app-hero {{ display:flex; align-items:center; gap:16px; padding:18px 22px; border-radius:16px; margin-bottom:14px;
  background: linear-gradient(120deg, #4F46E5 0%, #7C3AED 100%); color:#fff; box-shadow: 0 6px 20px rgba(79,70,229,.25); }}
.app-hero .logo {{ font-size:34px; line-height:1; background:rgba(255,255,255,.18); border-radius:14px; padding:10px 12px; }}
.app-hero h1 {{ margin:0; font-size:1.55rem; font-weight:700; letter-spacing:-.01em; color:#fff; padding:0; }}
.app-hero p {{ margin:2px 0 0; opacity:.9; font-size:.93rem; }}
.app-hero .pill {{ margin-left:auto; background:rgba(255,255,255,.18); padding:6px 12px; border-radius:999px; font-size:.8rem; white-space:nowrap; }}

/* ---- thẻ chung */
.card {{ border:1px solid var(--line); border-radius:14px; padding:14px 16px; background:#fff; }}
.card.soft {{ background: var(--soft); }}
.card h4 {{ margin:0 0 6px; font-size:.95rem; color: var(--ink); }}
.muted {{ color: var(--muted); font-size:.85rem; }}
.section-title {{ font-weight:700; font-size:1.02rem; margin:14px 0 6px; color: var(--ink); }}

/* ---- thẻ chỉ số */
.kpi-row {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap:12px; margin:6px 0 14px; }}
.kpi {{ border-radius:14px; padding:12px 16px; border:1px solid var(--line); background:#fff; position:relative; overflow:hidden; }}
.kpi::before {{ content:""; position:absolute; left:0; top:0; bottom:0; width:5px; background: var(--c, {PRIMARY}); }}
.kpi .n {{ font-size:1.9rem; font-weight:800; line-height:1.1; color: var(--c, {INK}); }}
.kpi .l {{ font-size:.8rem; color: var(--muted); margin-top:2px; }}

/* ---- huy hiệu, chip */
.badge {{ display:inline-block; padding:3px 10px; border-radius:999px; font-size:.78rem; font-weight:600; }}
.chip {{ display:inline-block; padding:2px 9px; margin:2px 4px 2px 0; border-radius:8px; font-size:.78rem; background:#EEF2FF; color:#3730A3; }}
.chip.green {{ background:#DCFCE7; color:#166534; }}
.chip.red {{ background:#FEE2E2; color:#991B1B; }}
.chip.gray {{ background:#F3F4F6; color:#374151; }}
.chip.amber {{ background:#FEF3C7; color:#92400E; }}

/* ---- thanh điểm */
.scorebar {{ position:relative; height:10px; border-radius:6px; background:#EEF0F4; margin:6px 0 2px; }}
.scorebar > span.fill {{ position:absolute; left:0; top:0; bottom:0; border-radius:6px; }}
.scorebar > span.tick {{ position:absolute; top:-3px; bottom:-3px; width:2px; background:#9CA3AF; opacity:.7; }}
.scoretxt {{ font-size:1.25rem; font-weight:800; line-height:1; }}

/* ---- thẻ ứng viên */
.cand-rank {{ width:34px; height:34px; border-radius:50%; background:#EEF2FF; color:#3730A3; font-weight:800;
  display:flex; align-items:center; justify-content:center; }}
.cand-name {{ font-size:1.05rem; font-weight:700; color: var(--ink); margin:0; }}
.cand-meta {{ color: var(--muted); font-size:.82rem; margin-top:1px; }}
.callout {{ border-left:4px solid #F59E0B; background:#FFFBEB; border-radius:8px; padding:8px 12px; margin:6px 0; font-size:.86rem; color:#78350F; }}
.callout.red {{ border-color:#EF4444; background:#FEF2F2; color:#7F1D1D; }}
.callout.blue {{ border-color:#3B82F6; background:#EFF6FF; color:#1E3A8A; }}
.callout.gray {{ border-color:#9CA3AF; background:#F9FAFB; color:#374151; }}
.crit-row {{ display:grid; grid-template-columns: 1.3fr 90px 2fr; gap:10px; padding:6px 0; border-bottom:1px dashed var(--line); font-size:.85rem; }}
.dots span {{ display:inline-block; width:11px; height:11px; border-radius:50%; margin-right:3px; background:#E5E7EB; }}
.dots span.on {{ background: {PRIMARY}; }}
.quote {{ color:#6B7280; font-size:.78rem; font-style:italic; }}

/* ---- bước hướng dẫn */
.howto {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap:12px; margin:8px 0 6px; }}
.howto .step {{ border:1px dashed #C7D2FE; border-radius:14px; padding:14px 16px; background:#FAFAFF; }}
.howto .step b {{ color: {PRIMARY}; }}
.empty {{ text-align:center; padding:40px 16px; border:2px dashed var(--line); border-radius:16px; color: var(--muted); background:#FCFCFD; }}
.empty .big {{ font-size:2.4rem; }}

/* ---- thành phần của Streamlit */
div[data-testid="stTabs"] button[role="tab"] {{ font-weight:600; font-size:1rem; padding:10px 18px; }}
div[data-testid="stTabs"] button[aria-selected="true"] {{ color: var(--primary); }}
.stButton > button[kind="primary"], .stDownloadButton > button {{ border-radius:10px; font-weight:600; }}
.stButton > button {{ border-radius:10px; }}
section[data-testid="stSidebar"] {{ background: var(--soft); border-right:1px solid var(--line); }}
div[data-testid="stVerticalBlockBorderWrapper"] {{ border-radius:14px; }}
div[data-testid="stExpander"] {{ border-radius:12px; border-color: var(--line); }}
</style>
"""


def inject() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
