// Sàng lọc CV: giao diện web cục bộ. Không dùng thư viện ngoài; mọi chữ từ CV/JD đều đi qua textContent (không chèn HTML).
const APP = document.getElementById("app");
const TOKEN = document.querySelector('meta[name="cv-token"]').content;

// ------------------------------------------------------------------ tiện ích
function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === false || v === null || v === undefined) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k in el && k !== "list") { try { el[k] = v; } catch (_) { el.setAttribute(k, v); } }
    else el.setAttribute(k, v === true ? "" : v);
  }
  const add = (kid) => {
    if (kid === null || kid === undefined || kid === false) return;
    if (Array.isArray(kid)) kid.forEach(add);
    else el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  };
  kids.forEach(add);
  return el;
}
// replaceChildren gốc biến null thành chữ "null": hàm này bỏ phần tử rỗng và làm phẳng mảng
function put(el, ...kids) {
  el.replaceChildren(...kids.flat(Infinity).filter((k) => k !== null && k !== undefined && k !== false));
  return el;
}
const fmtBytes = (n) => (n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(0)} KB` : `${(n / 1048576).toFixed(1)} MB`);
const fmtNum = (n) => String(Math.round(Number(n) * 10) / 10);
const stripAccents = (s) => String(s || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/đ/g, "d").replace(/Đ/g, "D").toLowerCase();
const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

async function api(method, path, body) {
  const opts = { method, headers: { "X-CV-Token": TOKEN } };
  if (body instanceof FormData) opts.body = body;
  else if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
  let res;
  try { res = await fetch(path, opts); } catch (_) { throw new Error("Không kết nối được tới ứng dụng. Hãy kiểm tra cửa sổ chạy ứng dụng còn mở."); }
  let data = {};
  try { data = await res.json(); } catch (_) { /* không phải JSON */ }
  if (!res.ok) throw new Error(data.error || `Lỗi ${res.status}`);
  return data;
}
const tokenUrl = (path) => `${path}${path.includes("?") ? "&" : "?"}token=${encodeURIComponent(TOKEN)}`;

// ------------------------------------------------------------------ hằng số
const FIT = "Phù hợp - Mời phỏng vấn", MAYBE = "Có thể mời phỏng vấn", RESERVE = "Dự phòng - Cân nhắc", REJECT = "Loại", ERROR = "LỖI";
const VERDICT = {
  [FIT]: { label: "Phù hợp", cls: "fit" }, [MAYBE]: { label: "Có thể mời", cls: "maybe" },
  [RESERVE]: { label: "Dự phòng", cls: "reserve" }, [REJECT]: { label: "Loại", cls: "reject" }, [ERROR]: { label: "Không đọc được", cls: "error" },
};
const TABS = [
  { key: "suitable", label: "Phù hợp", test: (r) => r.verdict === FIT || r.verdict === MAYBE },
  { key: "reserve", label: "Dự phòng", test: (r) => r.verdict === RESERVE },
  { key: "reject", label: "Loại", test: (r) => r.verdict === REJECT },
  { key: "error", label: "Không đọc được", test: (r) => r.verdict === ERROR, hideIfEmpty: true },
  { key: "all", label: "Tất cả", test: () => true },
];
const DECISIONS = [
  { key: "Mời phỏng vấn", label: "Mời", cls: "yes" }, { key: "Giữ lại", label: "Giữ", cls: "hold" }, { key: "Từ chối", label: "Bỏ", cls: "no" },
];
const PRESETS = [
  { name: "Nghiêm ngặt", hint: "Chỉ mời người đáp ứng từ 80% yêu cầu bắt buộc" },
  { name: "Cân bằng", hint: "Từ 70% (khuyến nghị)" },
  { name: "Rộng rãi", hint: "Từ 60%: nhiều người vào danh sách hơn" },
];
const MARK = { met: ["✓", "ok", "Đạt"], strong: ["✓", "ok", "Tốt"], partial: ["◐", "mid", "Một phần"], weak: ["!", "low", "Yếu"],
  missing: ["✗", "bad", "Không thấy"], failed: ["✗", "bad", "Không đạt"], unclear: ["?", "unk", "Chưa rõ"] };
const KIND_TITLE = { hard: "Điều kiện bắt buộc", required: "Kỹ năng bắt buộc", preferred: "Điểm cộng" };
const SUPPORTED_RE = /\.(pdf|docx|txt|md)$/i;
const PAGE = 100;                                  // số thẻ hiện mỗi lần: danh sách vài nghìn CV vẫn mượt

// ------------------------------------------------------------------ trạng thái
const saved = (() => { try { return JSON.parse(localStorage.getItem("cv-screening") || "{}"); } catch (_) { return {}; } })();
const S = {
  boot: null, screen: "setup",                      // setup | running | results
  jdText: saved.jdText || "", jdState: "empty", jd: null, jdError: "",
  files: [], preset: PRESETS.some((p) => p.name === saved.preset) ? saved.preset : "Cân bằng",
  job: null, run: null, tab: "suitable", q: "", onlyReview: false, open: null, limit: PAGE,
};
const persist = () => { try { localStorage.setItem("cv-screening", JSON.stringify({ jdText: S.jdText, preset: S.preset })); } catch (_) { /* bỏ qua */ } };
const els = {};
const presetValues = (name = S.preset) => (S.boot && S.boot.presets && S.boot.presets[name]) || { fit: 70, maybe: 50, reject: 30 };

// ------------------------------------------------------------------ thông báo, hộp thoại, menu
function toast(msg, kind = "info", ms = 3500) {
  const t = h("div", { class: `toast ${kind}`, role: "status" }, msg);
  els.toasts.append(t);
  setTimeout(() => t.remove(), ms);
}
let lastExportWarning = "";
function warnExport(msg) { if (msg && msg !== lastExportWarning) toast(msg, "error", 9000); lastExportWarning = msg || ""; }

let modalEl = null;
function closeModal() { if (modalEl) { modalEl.remove(); modalEl = null; } }
function openModal(title, body, footer) {
  closeModal();
  modalEl = h("div", { class: "backdrop", onclick: (e) => { if (e.target === modalEl) closeModal(); } },
    h("div", { class: "modal", role: "dialog", "aria-modal": "true", "aria-label": title },
      h("div", { class: "modal-head" }, h("h2", {}, title), h("button", { class: "x", "aria-label": "Đóng", onclick: closeModal }, "×")),
      h("div", { class: "modal-body" }, body),
      footer ? h("div", { class: "modal-foot" }, footer) : null));
  document.body.append(modalEl);
}

let menuEl = null;
function closeMenu() { if (menuEl) { menuEl.remove(); menuEl = null; } }
function openMenu(anchor, items) {
  if (menuEl) { closeMenu(); return; }
  menuEl = h("div", { class: "menu", role: "menu" }, items.map((it) => {
    if (it === "-") return h("hr");
    if (it.href) return h("a", { href: tokenUrl(it.href), target: it.blank ? "_blank" : null, rel: "noopener", download: it.blank ? null : "", onclick: closeMenu }, it.label);
    return h("button", { disabled: it.disabled, onclick: () => { closeMenu(); it.onclick(); } }, it.label);
  }));
  anchor.parentElement.append(menuEl);
  setTimeout(() => document.addEventListener("click", function once(e) { if (menuEl && !menuEl.contains(e.target)) closeMenu(); document.removeEventListener("click", once); }), 0);
}
document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeModal(); closeMenu(); } });

// ------------------------------------------------------------------ khung trang
function buildShell() {
  els.main = h("div");
  els.toasts = h("div", { class: "toasts", "aria-live": "polite" });
  put(APP,
    h("header", { class: "topbar" },
      h("div", { class: "brand" }, h("span", { class: "brand-logo" }, "CV"), "Sàng lọc CV"),
      h("div", { class: "spacer" }),
      h("button", { class: "btn small", onclick: openHistory }, "Các lần đã lưu")),
    els.main, h("div", { class: "foot" }, `Chạy trên máy bạn, CV không gửi đi đâu · v${APP.dataset.version || ""}`), els.toasts);
}
function render() {
  closeMenu();
  if (S.screen === "results" && !S.run) S.screen = "setup";
  const changed = S.shown !== S.screen;
  if (S.screen === "running") showRunning();
  else if (S.screen === "results") showResults();
  else { put(els.main, els.setup); refreshSetup(); }
  if (changed) window.scrollTo(0, 0);                       // sang màn hình khác thì về đầu trang
  S.shown = S.screen;
}

// ================================================================== MÀN HÌNH 1: THIẾT LẬP
function card(n, title, ...kids) {
  return h("section", { class: "card" }, h("div", { class: "card-head" }, h("span", { class: "num" }, n), h("h2", {}, title)), ...kids);
}

function buildSetup() {
  // ---- 1. JD
  els.jdArea = h("textarea", { class: "input", rows: 9, spellcheck: false, value: S.jdText,
    placeholder: "Dán mô tả công việc (JD) vào đây.\n\nVí dụ:\nKỹ sư AI\nYêu cầu:\n- Python, PyTorch\n- Tốt nghiệp ĐH chuyên ngành CNTT\n- Có ít nhất 2 năm kinh nghiệm",
    oninput: (e) => { S.jdText = e.target.value; onJdChange(); } });
  const jdFile = h("input", { type: "file", accept: ".txt,.md,.docx,.pdf", class: "hidden", onchange: async (e) => {
    const f = e.target.files[0]; e.target.value = "";
    if (!f) return;
    try {
      const fd = new FormData(); fd.append("file", f, f.name);
      const r = await api("POST", "/api/jd/upload", fd);
      S.jdText = r.text; els.jdArea.value = r.text; onJdChange();
    } catch (err) { toast(err.message, "error"); }
  } });
  els.jdNote = h("div");
  const step1 = card(1, "Mô tả công việc (JD)", els.jdArea,
    h("div", { class: "row" }, h("button", { class: "link", onclick: () => jdFile.click() }, "Tải file JD"), S.boot && S.boot.sample ? h("button", { class: "link", onclick: useSample }, "Dùng dữ liệu mẫu") : null, jdFile),
    els.jdNote);

  // ---- 2. CV
  els.fileInput = h("input", { type: "file", multiple: true, accept: ".pdf,.docx,.txt,.md", class: "hidden", onchange: (e) => { uploadFiles([...e.target.files]); e.target.value = ""; } });
  els.drop = h("div", { class: "drop", tabIndex: 0, role: "button", "aria-label": "Chọn hoặc kéo thả file CV",
    onclick: () => els.fileInput.click(), onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); els.fileInput.click(); } } },
  h("b", {}, "Kéo thả CV hoặc cả thư mục vào đây"), h("span", { class: "muted" }, "hoặc bấm để chọn file (PDF, DOCX, TXT)"), els.fileInput);
  ["dragenter", "dragover"].forEach((ev) => els.drop.addEventListener(ev, (e) => { e.preventDefault(); els.drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => els.drop.addEventListener(ev, (e) => { e.preventDefault(); els.drop.classList.remove("over"); }));
  els.drop.addEventListener("drop", async (e) => uploadFiles(await collectDropped(e.dataTransfer)));
  els.folder = h("input", { class: "input", placeholder: "D:\\TuyenDung\\CV", onkeydown: (e) => { if (e.key === "Enter") scanFolder(); } });
  els.recursive = h("input", { type: "checkbox" });
  els.filesBox = h("div");
  const step2 = card(2, "CV của ứng viên", els.drop,
    h("details", {}, h("summary", {}, "Hoặc đọc từ một thư mục trên máy này"),
      h("div", { class: "row", style: { marginTop: "10px" } }, h("div", { style: { flex: "1", minWidth: "220px" } }, els.folder), h("button", { class: "btn", onclick: scanFolder }, "Thêm"),
        h("label", { class: "check" }, els.recursive, "Gồm cả thư mục con"))),
    els.filesBox);

  // ---- 3. mức chọn lọc
  els.choices = h("div", { class: "choices" });
  const step3 = card(3, "Mức chọn lọc", els.choices);

  els.runBtn = h("button", { class: "btn primary big", onclick: startRun }, "Bắt đầu sàng lọc");
  els.runHint = h("div", { class: "run-hint" });
  els.lastNote = h("div", { class: "note-line" });
  els.setup = h("div", { class: "page" }, els.lastNote, step1, step2, step3, els.runBtn, els.runHint);
}

function refreshSetup() { refreshJd(); refreshFiles(); refreshChoices(); refreshRun(); refreshLast(); }

function refreshLast() {
  put(els.lastNote, S.run ? [h("span", { class: "muted" }, "Đang có kết quả của lần sàng lọc vừa xong."), h("button", { class: "link", onclick: () => { S.screen = "results"; render(); } }, "Xem lại kết quả")] : null);
}

// ---- JD: tự đọc sau khi dán, không cần bấm nút
let jdTimer = null, jdSeq = 0;
function onJdChange() {
  persist(); clearTimeout(jdTimer); jdSeq++;
  S.jd = null; S.jdError = "";
  S.jdState = S.jdText.trim() ? "wait" : "empty";
  refreshJd(); refreshRun();
  if (S.jdState === "wait") jdTimer = setTimeout(analyzeJd, 600);
}
async function analyzeJd() {
  const seq = ++jdSeq;
  try {
    const r = await api("POST", "/api/jd/filter", { text: S.jdText });
    if (seq !== jdSeq) return;
    S.jd = r.rubric; S.jdState = "ok";
  } catch (err) { if (seq !== jdSeq) return; S.jdState = "error"; S.jdError = err.message; }
  refreshJd(); refreshRun();
}
function refreshJd() {
  const st = S.jdState, rb = S.jd;
  if (st === "empty") { put(els.jdNote); return; }
  if (st === "wait") { put(els.jdNote, h("div", { class: "note-line wait" }, "Đang đọc JD…")); return; }
  if (st === "error") { put(els.jdNote, h("div", { class: "note-line bad" }, "✗ ", S.jdError)); return; }
  const list = (title, items) => items.length ? h("div", {}, h("h3", {}, title), h("ul", {}, items.map((x) => h("li", {}, x.text)))) : null;
  put(els.jdNote,
    h("div", { class: "note-line ok" }, "✓ Đã hiểu JD: ", `${rb.hard.length} điều kiện bắt buộc · ${rb.required.length} kỹ năng bắt buộc · ${rb.preferred.length} điểm cộng`),
    h("details", {}, h("summary", {}, "Xem hệ thống hiểu những gì"),
      h("div", { class: "jd-detail" }, list("Điều kiện bắt buộc (không đạt là bị loại)", rb.hard), list("Kỹ năng bắt buộc", rb.required), list("Điểm cộng", rb.preferred),
        rb.notes.length ? h("div", {}, h("h3", {}, "Đã bỏ qua"), h("ul", {}, rb.notes.map((n) => h("li", {}, n)))) : null)));
}

async function useSample() {
  try {
    const r = await api("POST", "/api/sample");
    S.jdText = r.jd_text; els.jdArea.value = r.jd_text; S.files = r.files; refreshFiles(); onJdChange();
    toast(`Đã nạp JD mẫu và ${r.files.length} CV mẫu`, "ok");
  } catch (err) { toast(err.message, "error"); }
}

// ---- file CV
async function walkEntry(entry, out) {
  if (entry.isFile) out.push(await new Promise((res, rej) => entry.file(res, rej)));
  else if (entry.isDirectory) {
    const reader = entry.createReader();
    let batch;
    do { batch = await new Promise((res, rej) => reader.readEntries(res, rej)); for (const e of batch) await walkEntry(e, out); } while (batch.length);
  }
}
async function collectDropped(dt) {
  const out = [];
  const entries = [...(dt.items || [])].map((i) => (i.webkitGetAsEntry ? i.webkitGetAsEntry() : null)).filter(Boolean);
  try { if (entries.length) for (const e of entries) await walkEntry(e, out); else out.push(...dt.files); } catch (_) { out.push(...dt.files); }
  return out;
}
async function uploadFiles(list) {
  const ok = list.filter((f) => SUPPORTED_RE.test(f.name)), skipped = list.length - ok.length;
  if (!ok.length) { toast(list.length ? "Không có file CV hợp lệ (dùng PDF, DOCX, TXT)." : "Chưa chọn file nào.", "error"); return; }
  els.drop.classList.add("busy");
  let done = 0;
  try {
    for (let i = 0; i < ok.length; i += 12) {
      const fd = new FormData();
      ok.slice(i, i + 12).forEach((f) => fd.append("files", f, f.name));
      const r = await api("POST", "/api/files", fd);
      S.files.push(...r.files); done += r.files.length;
      refreshFiles(`Đang tải… ${done}/${ok.length}`); refreshRun();
    }
    toast(`Đã thêm ${done} CV` + (skipped ? ` (bỏ qua ${skipped} file không hỗ trợ)` : ""), "ok");
  } catch (err) { toast(err.message, "error"); }
  finally { els.drop.classList.remove("busy"); refreshFiles(); }
}
async function scanFolder() {
  const path = els.folder.value.trim();
  if (!path) { toast("Hãy nhập đường dẫn thư mục.", "error"); return; }
  try {
    const r = await api("POST", "/api/folder", { path, recursive: els.recursive.checked });
    S.files.push(...r.files); refreshFiles(); refreshRun();
    toast(r.files.length ? `Đã thêm ${r.files.length} CV từ thư mục` : "Các CV trong thư mục này đã được thêm trước đó", r.files.length ? "ok" : "info");
  } catch (err) { toast(err.message, "error"); }
}
async function removeFile(id) { S.files = S.files.filter((f) => f.id !== id); refreshFiles(); refreshRun(); try { await api("DELETE", `/api/files/${id}`); } catch (_) { /* bỏ qua */ } }
async function clearFiles() { S.files = []; refreshFiles(); refreshRun(); try { await api("DELETE", "/api/files"); } catch (_) { /* bỏ qua */ } }
function refreshFiles(busyText) {
  if (!S.files.length) { put(els.filesBox, busyText ? h("div", { class: "muted" }, busyText) : null); return; }
  const total = S.files.reduce((a, f) => a + f.size, 0);
  put(els.filesBox,
    h("div", { class: "files-line" }, h("b", {}, `${S.files.length} CV đã thêm`), h("span", { class: "muted small" }, fmtBytes(total)), busyText ? h("span", { class: "muted small" }, busyText) : null,
      h("button", { class: "link", onclick: clearFiles }, "Xóa tất cả")),
    h("details", {}, h("summary", {}, "Xem danh sách"),
      h("ul", { class: "file-list" }, S.files.map((f) => h("li", {}, h("span", { class: "fname", title: f.name }, f.name), h("span", { class: "muted small" }, fmtBytes(f.size)),
        h("button", { class: "x", "aria-label": `Bỏ ${f.name}`, onclick: () => removeFile(f.id) }, "×"))))));
}

// ---- mức chọn lọc
function refreshChoices() {
  put(els.choices, PRESETS.map((p) => h("button", { class: `choice ${S.preset === p.name ? "on" : ""}`, "aria-pressed": String(S.preset === p.name),
    onclick: () => { S.preset = p.name; persist(); refreshChoices(); } }, h("b", {}, p.name), h("span", {}, p.hint))));
}
function refreshRun() {
  const ready = S.jdState === "ok" && S.files.length > 0;
  els.runBtn.disabled = !ready;
  els.runBtn.textContent = S.files.length ? `Bắt đầu sàng lọc ${S.files.length} CV` : "Bắt đầu sàng lọc";
  put(els.runHint, ready ? null : S.jdState === "error" ? "Hãy sửa JD ở bước 1." : !S.jdText.trim() ? "Cần dán JD (bước 1) và thêm CV (bước 2)." : S.jdState === "wait" ? "Đang đọc JD…" : "Cần thêm ít nhất một CV (bước 2).");
}

// ================================================================== MÀN HÌNH 2: ĐANG CHẠY
async function startRun() {
  try {
    const { job_id } = await api("POST", "/api/screen", { jd_text: S.jdText, file_ids: S.files.map((f) => f.id), ...presetValues() });
    S.job = { id: job_id, status: "running", done: 0, total: S.files.length, current: "" };
    S.screen = "running"; render(); pollJob();
  } catch (err) { toast(err.message, "error", 5000); }
}
function showRunning() {
  els.bar = h("i"); els.progressText = h("div", { class: "muted" }); els.progressName = h("div", { class: "muted small" });
  put(els.main, h("div", { class: "page" }, h("section", { class: "card running" },
    h("h2", {}, "Đang sàng lọc CV…"), h("div", { class: "bar" }, els.bar), els.progressText, els.progressName,
    h("div", { class: "muted small" }, "CV dạng ảnh (OCR) có thể mất vài chục giây mỗi trang."),
    h("button", { class: "btn", onclick: cancelRun }, "Dừng"))));
  updateProgress();
}
function updateProgress() {
  const j = S.job; if (!j || !els.bar) return;
  const pct = j.total ? Math.round((j.done / j.total) * 100) : 0;
  els.bar.style.width = `${pct}%`;
  els.progressText.textContent = `${j.done}/${j.total} CV · ${pct}%`;
  els.progressName.textContent = j.current === "Đang dừng…" ? j.current : j.current ? `Vừa xong: ${j.current}` : "";
}
async function pollJob() {
  const id = S.job.id;
  while (S.job && S.job.id === id && S.job.status === "running") {
    await new Promise((r) => setTimeout(r, 400));
    try { S.job = { ...S.job, ...(await api("GET", `/api/jobs/${id}`)) }; } catch (err) { S.job.status = "error"; S.job.error = err.message; }
    if (S.job.status === "running") updateProgress();
  }
  const job = S.job; S.job = null;
  if (job.status === "done") {
    try { await openRun(job.run_id); toast(`Xong ${S.run.rows.length} CV trong ${fmtNum(job.elapsed)} giây`, "ok"); return; }
    catch (err) { toast(err.message, "error"); }
  } else if (job.status === "cancelled") toast("Đã dừng. Chưa có kết quả nào được lưu.", "info", 4500);
  else toast(job.error || "Có lỗi khi sàng lọc", "error", 6000);
  S.screen = "setup"; render();
}
async function cancelRun() {
  if (!S.job || S.job.status !== "running") return;
  try { await api("POST", `/api/jobs/${S.job.id}/cancel`); S.job.current = "Đang dừng…"; updateProgress(); } catch (err) { toast(err.message, "error"); }
}

// ================================================================== MÀN HÌNH 3: KẾT QUẢ
async function openRun(id) {
  const data = await api("GET", `/api/runs/${id}`);
  S.run = data; S.q = ""; S.onlyReview = false; S.open = null; S.limit = PAGE;
  S.tab = data.rows.some(TABS[0].test) ? "suitable" : "all";
  S.screen = "results"; render(); warnExport(data.export_error);
}

function showResults() {
  const run = S.run, title = run.rubric && run.rubric.title && !run.rubric.title.startsWith("(") ? ` · ${run.rubric.title}` : "";
  els.moreBtn = h("button", { class: "btn", onclick: () => openMenu(els.moreBtn, moreItems()) }, "Thêm ▾");
  els.search = h("input", { class: "input", type: "search", placeholder: "Tìm theo tên, kỹ năng, nội dung CV…", value: S.q, "aria-label": "Tìm kiếm",
    oninput: debounce((e) => { S.q = e.target.value; S.limit = PAGE; renderList(); }, 150) });
  els.tabs = h("div", { class: "tabs", role: "tablist" });
  els.list = h("div", { class: "list" });
  put(els.main, h("div", { class: "page" },
    h("div", { class: "head" }, h("button", { class: "btn small", onclick: () => { S.screen = "setup"; render(); } }, "← Sàng lọc mới"),
      h("div", { style: { flex: "1" } }, h("h1", {}, "Kết quả sàng lọc"), h("div", { class: "muted small" }, `${run.rows.length} CV${title}`)),
      h("a", { class: "btn primary", href: tokenUrl(`/api/runs/${run.id}/export/xlsx`), download: "" }, "Tải Excel"),
      h("div", { class: "menu-wrap" }, els.moreBtn)),
    els.tabs,
    h("div", { class: "tools" }, els.search,
      h("label", { class: "check" }, h("input", { type: "checkbox", checked: S.onlyReview, onchange: (e) => { S.onlyReview = e.target.checked; S.limit = PAGE; renderList(); } }), "Chỉ CV cần xem lại")),
    els.list));
  renderTabs(); renderList();
}

function moreItems() {
  const id = S.run.id;
  return [
    { label: S.run.can_rejudge ? "Đổi mức chọn lọc…" : "Đổi mức chọn lọc (lần chạy cũ, không dùng được)", disabled: !S.run.can_rejudge, onclick: openRejudge },
    { label: "Chấp nhận đề xuất cho các CV đang xem…", onclick: acceptVisible },
    { label: "Sao chép email người được mời…", onclick: showEmails },
    "-",
    { label: "Tải bảng CSV", href: `/api/runs/${id}/export/csv` },
    { label: "In báo cáo: danh sách phù hợp", href: `/api/runs/${id}/report?scope=suitable`, blank: true },
    { label: "In báo cáo: tất cả CV", href: `/api/runs/${id}/report?scope=all`, blank: true },
  ];
}

function renderTabs() {
  const rows = S.run.rows;
  put(els.tabs, TABS.map((t) => {
    const n = rows.filter(t.test).length;
    if (t.hideIfEmpty && !n && S.tab !== t.key) return null;
    return h("button", { class: `tab ${S.tab === t.key ? "on" : ""}`, role: "tab", "aria-selected": String(S.tab === t.key),
      onclick: () => { S.tab = t.key; S.open = null; S.limit = PAGE; renderTabs(); renderList(); } }, t.label, h("em", {}, n));
  }));
}

// Tìm kiếm toàn văn (không phân biệt dấu): chuẩn hoá một lần cho mỗi dòng để gõ phím vẫn mượt với vài trăm CV
const HAYSTACKS = new WeakMap();
function haystack(r) {
  let s = HAYSTACKS.get(r);
  if (s === undefined) { s = stripAccents([r.candidate_name, r.email, r.phone, r.file, r.strengths, r.gaps, r.english, r.github, r.cv_text].join(" ")); HAYSTACKS.set(r, s); }
  return s;
}
function visibleRows() {
  const tab = TABS.find((t) => t.key === S.tab) || TABS[4];
  let rows = S.run.rows.filter(tab.test);
  if (S.onlyReview) rows = rows.filter((r) => r.needs_human_review === "CÓ");
  if (S.q.trim()) {
    const terms = stripAccents(S.q.trim()).split(/\s+/);                       // nhiều từ: CV phải chứa tất cả
    rows = rows.filter((r) => { const text = haystack(r), note = stripAccents(r.hr_note || ""); return terms.every((t) => text.includes(t) || note.includes(t)); });
  }
  return rows;
}
function renderList() {
  els.visible = visibleRows();
  if (!els.visible.length) {
    put(els.list, h("div", { class: "empty" }, S.q || S.onlyReview ? "Không có CV nào khớp bộ lọc." : "Chưa có CV nào trong nhóm này."));
    return;
  }
  const shown = els.visible.slice(0, S.limit);
  put(els.list, shown.map(candidate), els.visible.length > shown.length
    ? h("button", { class: "btn", onclick: () => { S.limit += PAGE; renderList(); } }, `Hiện thêm ${Math.min(PAGE, els.visible.length - shown.length)} CV (còn ${els.visible.length - shown.length})`) : null);
}

// ---- thẻ ứng viên
function candidate(r) {
  const v = VERDICT[r.verdict] || VERDICT[ERROR], open = S.open === r.index, review = r.review_items || [];
  const unsure = r.name_source && !["cv", "label"].includes(r.name_source);
  const toggle = () => { S.open = open ? null : r.index; renderList(); };
  return h("article", { class: `cand ${v.cls}` },
    h("div", { class: "cand-main", role: "button", tabIndex: 0, "aria-expanded": String(open), onclick: toggle, onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } } },
      h("span", { class: "rank" }, r.rank),
      h("div", { class: "who" },
        h("div", { class: "name" }, r.candidate_name, unsure ? h("span", { class: "q", title: "Tên suy ra từ tên file/email/OCR, cần xác nhận" }, "(tên cần xác nhận)") : null),
        h("div", { class: "contact" }, [r.email, r.phone].filter(Boolean).join(" · ") || r.file)),
      r.verdict === ERROR ? null : h("div", { class: "pct" }, h("b", {}, `${fmtNum(r.required_score)}%`), h("small", {}, "yêu cầu bắt buộc"))),
    h("div", { class: "cand-why" }, h("span", { class: `badge ${v.cls}` }, v.label), r.suggestion ? h("b", {}, r.suggestion + ".") : null, h("span", { class: "reason" }, r.verdict_reason)),
    review.length ? h("div", { class: "cand-warn" }, `⚠ ${review.length} điểm cần xem lại`) : null,
    h("div", { class: "cand-bottom" }, decisionButtons(r), h("span", { style: { flex: "1" } }), h("button", { class: "link", onclick: toggle }, open ? "Thu gọn ▴" : "Chi tiết ▾")),
    open ? detail(r, review) : null);
}
function decisionButtons(r) {
  return h("div", { class: "dec" }, DECISIONS.map((d) => h("button", { class: `${d.cls} ${r.hr_decision === d.key ? "on" : ""}`, title: d.key, "aria-pressed": String(r.hr_decision === d.key),
    onclick: () => setDecision(r, d.key) }, d.label)));
}
function detail(r, review) {
  const facts = [];
  if (r.total_years !== "" && r.total_years != null) facts.push(`Kinh nghiệm: ${r.total_years} năm`);
  if (r.gpa) facts.push(`GPA ${r.gpa}`);
  if (r.english) facts.push(r.english);
  if (r.github) facts.push(r.github);
  facts.push(`File: ${r.file}`);
  if (r.source && r.source.includes("ocr")) facts.push("Đọc bằng OCR");
  const groups = ["hard", "required", "preferred"].map((kind) => {
    const items = (r.checklist || []).filter((c) => c.kind === kind);
    return items.length ? h("div", {}, h("h3", {}, KIND_TITLE[kind]), items.map(checkItem)) : null;
  });
  const note = h("textarea", { class: "input", rows: 2, placeholder: "Ghi chú của bạn về ứng viên này (tự lưu)", value: r.hr_note || "",
    oninput: debounce(() => saveNote(r, note.value), 500), onblur: () => saveNote(r, note.value) });
  return h("div", { class: "detail" },
    h("div", { class: "facts" }, facts.map((f) => h("span", {}, f))),
    review.length ? h("div", {}, h("h3", {}, "Cần xem lại"), h("ul", { class: "todo" }, review.map((x) => h("li", {}, x)))) : null,
    groups,
    h("div", {}, h("h3", {}, "Ghi chú"), note),
    r.cv_text ? h("details", {}, h("summary", {}, "Xem văn bản máy đọc được từ CV"), h("pre", { class: "cv" }, r.cv_text)) : null);
}
function checkItem(c) {
  const [mark, cls, text] = MARK[c.status] || MARK.unclear;
  const sub = c.note && ["failed", "unclear", "missing"].includes(c.status) ? c.note : (c.evidence && c.evidence[0]) ? c.evidence[0] : "";
  return h("div", { class: "chk" }, h("span", { class: `mark ${cls}`, title: text }, mark),
    h("div", { class: "body" }, h("div", {}, c.label), sub ? h("div", { class: `sub ${c.note && sub === c.note ? "" : "quote"}` }, sub) : null));
}

// ---- quyết định của HR
async function setDecision(r, decision) {
  const prev = r.hr_decision || "", next = prev === decision ? "" : decision;
  r.hr_decision = next; renderList();
  try { const res = await api("POST", `/api/runs/${S.run.id}/decision`, { index: r.index, decision: next }); warnExport(res.export_error); }
  catch (err) { r.hr_decision = prev; renderList(); toast(err.message, "error"); }
}
async function saveNote(r, text) {
  if ((r.hr_note || "") === text) return;
  r.hr_note = text;
  try { await api("POST", `/api/runs/${S.run.id}/decision`, { index: r.index, note: text }); } catch (err) { toast(err.message, "error"); }
}
function acceptVisible() {
  const rows = (els.visible || []).filter((r) => r.verdict !== ERROR);
  if (!rows.length) { toast("Không có CV nào để áp dụng.", "info"); return; }
  openModal("Chấp nhận đề xuất",
    [h("p", {}, `Đặt quyết định theo đề xuất của hệ thống cho ${rows.length} CV đang xem?`),
      h("ul", {}, h("li", {}, "Phù hợp → Mời phỏng vấn"), h("li", {}, "Có thể mời, Dự phòng → Giữ lại"), h("li", {}, "Loại → Từ chối")),
      h("p", { class: "muted small" }, "Bạn vẫn đổi được từng CV sau đó.")],
    [h("button", { class: "btn", onclick: closeModal }, "Hủy"), h("button", { class: "btn primary", onclick: () => bulkAccept(rows) }, `Áp dụng cho ${rows.length} CV`)]);
}
async function bulkAccept(rows) {
  closeModal();
  try {
    const r = await api("POST", `/api/runs/${S.run.id}/bulk`, { indices: rows.map((x) => x.index), decision: "accept" });
    const data = await api("GET", `/api/runs/${S.run.id}`); S.run.rows = data.rows; warnExport(data.export_error);
    renderList(); toast(r.changed ? `Đã cập nhật ${r.changed} ứng viên` : "Không có thay đổi", r.changed ? "ok" : "info");
  } catch (err) { toast(err.message, "error"); }
}
async function showEmails() {
  try {
    const r = await api("GET", `/api/runs/${S.run.id}/emails`);
    const text = r.emails.join("; ");
    openModal("Email ứng viên",
      [h("p", {}, `${r.count} email của ${r.label}` + (r.missing ? ` (${r.missing} người không có email)` : "") + "."),
        h("textarea", { class: "input", rows: 5, readOnly: true, value: text, onfocus: (e) => e.target.select() }),
        h("p", { class: "muted small" }, "Dán vào ô Đến hoặc Bcc của email. Bấm “Mời” ở ứng viên để chỉ lấy đúng những người bạn đã chọn.")],
      [h("button", { class: "btn", onclick: closeModal }, "Đóng"), h("button", { class: "btn primary", disabled: !r.count, onclick: () => copyText(text, `Đã sao chép ${r.count} email`) }, "Sao chép")]);
  } catch (err) { toast(err.message, "error"); }
}
async function copyText(text, okMsg) {
  try { await navigator.clipboard.writeText(text); toast(okMsg, "ok"); }
  catch (_) {
    const ta = h("textarea", { value: text, style: { position: "fixed", opacity: "0" } });
    document.body.append(ta); ta.select();
    try { document.execCommand("copy"); toast(okMsg, "ok"); } catch (__) { toast("Không sao chép được, hãy chọn và sao chép thủ công", "error"); }
    ta.remove();
  }
}

// ---- đổi mức chọn lọc trên kết quả đã có (không đọc lại CV)
function openRejudge() {
  const m = S.run.meta || {};
  let pick = (PRESETS.find((p) => { const v = presetValues(p.name); return v.fit === m.fit && v.maybe === m.maybe && v.reject === m.reject; }) || {}).name || null;
  const box = h("div", { class: "choices", style: { gridTemplateColumns: "1fr" } });
  const apply = h("button", { class: "btn primary", disabled: true }, "Áp dụng");
  const draw = () => {
    put(box, PRESETS.map((p) => h("button", { class: `choice ${pick === p.name ? "on" : ""}`, onclick: () => { pick = p.name; draw(); } }, h("b", {}, p.name), h("span", {}, p.hint))));
    apply.disabled = !pick;
  };
  apply.onclick = async () => {
    try {
      S.run = await api("POST", `/api/runs/${S.run.id}/rejudge`, presetValues(pick));
      S.preset = pick; persist(); S.open = null; closeModal(); render(); toast("Đã tính lại kết luận và xếp hạng", "ok");
    } catch (err) { toast(err.message, "error", 5000); }
  };
  draw();
  openModal("Đổi mức chọn lọc", [h("p", { class: "muted" }, "Kết luận và xếp hạng được tính lại ngay, không phải đọc lại CV. Quyết định của bạn được giữ nguyên."), box],
    [h("button", { class: "btn", onclick: closeModal }, "Hủy"), apply]);
}

// ---- các lần đã lưu
async function openHistory() {
  try {
    const { runs } = await api("GET", "/api/runs");
    const list = runs.length ? h("ul", { class: "history" }, runs.map((run) => h("li", {},
      h("span", { class: "lbl" }, run.label),
      h("button", { class: "btn small", onclick: async () => { try { closeModal(); await openRun(run.id); } catch (e) { toast(e.message, "error"); } } }, "Mở"),
      h("button", { class: "x", "aria-label": "Xóa lần chạy này", title: "Xóa", onclick: async () => {
        if (!confirm("Xóa lần sàng lọc này khỏi máy? Không khôi phục được.")) return;
        try { await api("DELETE", `/api/runs/${run.id}`); if (S.run && S.run.id === run.id) { S.run = null; S.screen = "setup"; render(); } openHistory(); } catch (e) { toast(e.message, "error"); }
      } }, "🗑")))) : h("p", { class: "muted" }, "Chưa có lần sàng lọc nào được lưu.");
    openModal("Các lần sàng lọc đã lưu", list);
  } catch (err) { toast(err.message, "error"); }
}

// ================================================================== khởi động
async function init() {
  buildShell();
  try { S.boot = await api("GET", "/api/bootstrap"); S.files = S.boot.files || []; }
  catch (err) { put(els.main, h("div", { class: "page" }, h("section", { class: "card" }, h("h2", {}, "Không kết nối được"), h("p", {}, err.message)))); return; }
  buildSetup();
  if (S.jdText.trim()) { S.jdState = "wait"; analyzeJd(); }
  if (S.boot.job) { S.job = S.boot.job; S.screen = "running"; render(); pollJob(); return; }       // tải lại trang giữa lúc đang chạy: nối lại tiến độ
  render();
}
init();
