"""Phần nghiệp vụ của ứng dụng web (không phụ thuộc HTTP, nên test trực tiếp được).

Một người dùng, chạy cục bộ: giữ danh sách file đã thêm, các tác vụ sàng lọc đang chạy và các lần chạy đã lưu.
"""
import io
import re
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from cv_agent import storage
from cv_agent.config import PRESETS
from cv_agent.io_utils import SUPPORTED, read_text
from cv_agent.jd_filter import core_jd_text, dropped_notes
from cv_agent.pipeline import DEFAULT_WORKERS, Cancelled, build_rubric, list_cv_files, screen
from cv_agent.report import HR_FROM_SUGGESTION, can_rejudge, rejudge, suitable, write_csv, write_excel
from cv_agent.schemas import Rubric
from cv_agent.verdict import check_thresholds

from .printable import render_report

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_JD = ROOT / "samples" / "jds" / "ai01.txt"
SAMPLE_CVS = ROOT / "samples" / "cvs_pdf"
DECISIONS = {"", "Mời phỏng vấn", "Giữ lại", "Từ chối"}
RUN_ID = re.compile(r"^[0-9A-Za-z_\-]+$")
EXPORT_DELAY = 1.5          # giây: ghi Excel/CSV sau khi HR ngừng thao tác chừng này


class ServiceError(ValueError):
    """Lỗi người dùng (thông điệp tiếng Việt, hiển thị thẳng trên giao diện)."""


UPLOAD_PREFIX = "cvagent_uploads_"
MAX_CACHED_RUNS = 6         # số lần chạy giữ trong bộ nhớ (mỗi lần có thể vài chục MB văn bản CV); các lần khác đọc lại từ đĩa khi cần


def _remove_stale_uploads(max_age_hours: float = 24) -> None:
    """Thư mục tải lên tạm của các lần chạy trước bị tắt đột ngột (đóng cửa sổ, mất điện) không được dọn: xóa những thư mục quá cũ."""
    cutoff = time.time() - max_age_hours * 3600
    for old in Path(tempfile.gettempdir()).glob(UPLOAD_PREFIX + "*"):
        try:
            if old.is_dir() and old.stat().st_mtime < cutoff:
                shutil.rmtree(old, ignore_errors=True)
        except OSError:
            continue


_BAD_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = re.compile(r"^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])$", re.I)


def safe_filename(name: str, limit: int = 120) -> str:
    """Tên file người dùng gửi lên -> tên an toàn để ghi ra đĩa Windows/Linux: bỏ đường dẫn, ký tự cấm (: * ? ...), tên thiết bị
    (CON, NUL...), dấu chấm/cách ở cuối, và cắt độ dài. Đuôi file được giữ nguyên để nhận dạng định dạng."""
    base = re.split(r"[\\/]", str(name))[-1].strip()      # không dùng Path(): trên Windows "a:b.pdf" bị hiểu là ổ đĩa "a:"
    stem, dot, ext = base.rpartition(".") if "." in base else (base, "", "")
    if not stem and dot:                                  # ".pdf": không có tên
        stem, ext = "cv", base.lstrip(".")
    stem = _BAD_NAME_CHARS.sub("_", stem).strip(" .") or "cv"
    ext = _BAD_NAME_CHARS.sub("", ext).strip(" .")
    if _RESERVED.match(stem):
        stem = "_" + stem
    stem = stem[: max(1, limit - len(ext) - 1)]
    return f"{stem}.{ext}" if ext else stem


def rubric_summary(rb: Rubric) -> dict:
    return {
        "title": rb.jd_analysis.job_title,
        "hard": [{"type": h.type, "text": h.source_quote} for h in rb.hard_requirements],
        "required": [{"text": c.source_quote or c.name, "weight": round(c.weight, 3)} for c in rb.criteria if c.importance == "required"],
        "preferred": [{"text": c.source_quote or c.name, "weight": round(c.weight, 3)} for c in rb.criteria if c.importance != "required"],
        "notes": dropped_notes(rb),
    }


class Service:
    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = Path(output_dir) if output_dir else storage.default_dir()
        self._lock = threading.RLock()
        _remove_stale_uploads()
        self._tmp = Path(tempfile.mkdtemp(prefix=UPLOAD_PREFIX))
        self.files: dict[str, dict] = {}
        self.jobs: dict[str, dict] = {}
        self._cancel: dict[str, threading.Event] = {}
        self._export_timers: dict[Path, threading.Timer] = {}
        self.runs: dict[str, dict] = {}

    def close(self) -> None:
        self.flush_exports()
        shutil.rmtree(self._tmp, ignore_errors=True)

    # ------------------------------------------------------------ cấu hình ban đầu
    def bootstrap(self) -> dict:
        with self._lock:
            running = next((dict(job) for job in self.jobs.values() if job["status"] == "running"), None)
        return {
            "presets": {k: {"fit": v[0], "maybe": v[1], "reject": v[2]} for k, v in PRESETS.items()},
            "sample": SAMPLE_JD.exists() and SAMPLE_CVS.exists(),
            "job": running,                               # tác vụ đang chạy: tải lại trang giữa chừng vẫn nối lại được tiến độ
        }

    # ------------------------------------------------------------ JD
    def filter_jd(self, text: str) -> dict:
        if not (text or "").strip():
            raise ServiceError("Chưa có nội dung JD.")
        try:
            rb = build_rubric(text, "baseline")
        except ValueError as e:
            raise ServiceError(str(e)) from e
        return {"rubric": rubric_summary(rb), "core_jd": core_jd_text(rb)}

    def read_jd_file(self, name: str, data: bytes) -> str:
        suffix = Path(name).suffix.lower()
        if suffix not in {".txt", ".md", ".docx", ".pdf"}:
            raise ServiceError("JD chỉ hỗ trợ .txt, .docx, .pdf")
        path = self._tmp / f"jd_{uuid.uuid4().hex}{suffix}"
        path.write_bytes(data)
        try:
            return read_text(path)
        except ValueError as e:
            raise ServiceError(str(e)) from e
        finally:
            path.unlink(missing_ok=True)

    # ------------------------------------------------------------ file CV
    def _register(self, name: str, path: Path, source: str) -> dict:
        fid = uuid.uuid4().hex[:10]
        ref = {"id": fid, "name": name, "path": str(path), "size": path.stat().st_size, "source": source}
        self.files[fid] = ref
        return ref

    def public_files(self) -> list[dict]:
        return [{k: v for k, v in f.items() if k != "path"} for f in self.files.values()]

    def add_uploads(self, items: list[tuple[str, bytes]]) -> tuple[list[dict], list[str]]:
        """-> (file đã thêm, tên file bị từ chối vì sai định dạng)"""
        added, rejected = [], []
        with self._lock:
            for name, data in items:
                safe = safe_filename(name)
                if Path(safe).suffix.lower() not in SUPPORTED:
                    rejected.append(safe)
                    continue
                folder = self._tmp / uuid.uuid4().hex                 # thư mục riêng: hai CV trùng tên không ghi đè nhau
                folder.mkdir()
                path = folder / safe
                path.write_bytes(data)
                added.append(self._register(safe, path, "upload"))
        if rejected and not added:
            raise ServiceError("Định dạng không hỗ trợ: " + ", ".join(rejected[:5]) + ". Dùng PDF, DOCX hoặc TXT.")
        return [{k: v for k, v in f.items() if k != "path"} for f in added], rejected

    def add_folder(self, path: str, recursive: bool = False) -> list[dict]:
        p = Path((path or "").strip().strip('"'))
        if not str(p).strip() or not p.is_dir():
            raise ServiceError("Thư mục không tồn tại. Thư mục phải nằm trên máy đang chạy ứng dụng.")
        try:
            found = list_cv_files(p, recursive)
        except ValueError as e:
            raise ServiceError(str(e)) from e
        except OSError as e:                                     # không có quyền đọc thư mục, ổ đĩa ngắt kết nối...
            raise ServiceError(f"Không đọc được thư mục: {type(e).__name__}") from e
        if not found:
            raise ServiceError("Không có file CV (PDF, DOCX, TXT) nào trong thư mục này.")
        with self._lock:
            known = {f["path"] for f in self.files.values()}
            return [{k: v for k, v in self._register(f.name, f, "folder").items() if k != "path"} for f in found if str(f) not in known]

    def remove_file(self, fid: str) -> None:
        with self._lock:
            ref = self.files.pop(fid, None)
            if ref and ref["source"] == "upload":
                shutil.rmtree(Path(ref["path"]).parent, ignore_errors=True)

    def clear_files(self) -> None:
        with self._lock:
            for fid in list(self.files):
                self.remove_file(fid)

    def load_sample(self) -> dict:
        if not (SAMPLE_JD.exists() and SAMPLE_CVS.exists()):
            raise ServiceError("Không tìm thấy dữ liệu mẫu (thư mục samples).")
        self.clear_files()
        files = self.add_folder(str(SAMPLE_CVS))
        return {"jd_text": read_text(SAMPLE_JD), "files": files}

    # ------------------------------------------------------------ chạy sàng lọc
    def start_screen(self, jd_text: str, core_jd: str, file_ids: list[str], fit: float, maybe: float, reject: float,
                     ocr: bool = True, workers: int = DEFAULT_WORKERS) -> str:
        if not (jd_text or core_jd or "").strip():
            raise ServiceError("Chưa có JD.")
        try:
            check_thresholds(fit, maybe, reject)
        except ValueError as e:
            raise ServiceError(str(e)) from e
        with self._lock:
            refs = [self.files[i] for i in file_ids if i in self.files]
        if not refs:
            raise ServiceError("Chưa có CV nào để sàng lọc.")
        try:
            rubric = build_rubric((core_jd or jd_text).strip(), "baseline")
        except ValueError as e:
            raise ServiceError(f"Không phân tích được JD: {e}") from e
        try:                                                  # kiểm tra nơi lưu kết quả trước khi tốn vài phút sàng lọc rồi mới phát hiện không ghi được
            self.output_dir.mkdir(parents=True, exist_ok=True)
            probe = self.output_dir / f".write_test_{uuid.uuid4().hex[:6]}"
            probe.write_bytes(b"ok")
            probe.unlink()
        except OSError as e:
            raise ServiceError(f"Không ghi được vào thư mục lưu kết quả ({self.output_dir}): {type(e).__name__}. "
                               "Đặt biến môi trường CV_AGENT_OUTPUT_DIR sang thư mục khác.") from e
        job_id = uuid.uuid4().hex[:10]
        job = {"id": job_id, "status": "running", "done": 0, "total": len(refs), "current": "", "recent": [],
               "started": time.time(), "run_id": None, "error": ""}
        with self._lock:
            for old in [j for j, v in self.jobs.items() if v["status"] != "running"][:-10]:      # chỉ giữ 10 tác vụ đã xong gần nhất
                self.jobs.pop(old, None)
                self._cancel.pop(old, None)
            self.jobs[job_id] = job
            self._cancel[job_id] = threading.Event()
        threading.Thread(target=self._run_job, args=(job, rubric, refs, fit, maybe, reject, ocr, workers), daemon=True).start()
        return job_id

    def _run_job(self, job, rubric, refs, fit, maybe, reject, ocr, workers) -> None:
        def progress(done, total, name):
            job["done"], job["current"] = done, name
            job["recent"] = (job["recent"] + [name])[-6:]

        try:
            rows = screen(rubric, [(r["name"], Path(r["path"])) for r in refs], fit=fit, maybe=maybe, reject=reject,
                          workers=workers, ocr=ocr, on_progress=progress, cancel=self._cancel[job["id"]])
            elapsed = round(time.time() - job["started"], 1)
            meta = {"elapsed": elapsed, "fit": fit, "maybe": maybe, "reject": reject}
            folder = storage.save_run(rows, rubric, core_jd_text(rubric), meta, base=self.output_dir)
            with self._lock:
                self.runs[folder.name] = {"rows": rows, "rubric": rubric, "meta": {**meta, "n_cv": len(rows)}, "folder": folder}
            job["run_id"], job["status"] = folder.name, "done"
        except Cancelled:
            job["status"] = "cancelled"
        except Exception as e:                                     # tác vụ nền: mọi lỗi phải báo lại cho giao diện
            job["status"], job["error"] = "error", f"{type(e).__name__}: {e}"

    def job(self, job_id: str) -> dict:
        job = self.jobs.get(job_id)
        if not job:
            raise ServiceError("Không tìm thấy tác vụ.")
        return {**job, "elapsed": round(time.time() - job["started"], 1)}

    def cancel_job(self, job_id: str) -> dict:
        """Dừng lượt sàng lọc đang chạy. CV đang đọc dở được chạy nốt (OCR một trang có thể mất vài chục giây), CV chưa bắt đầu thì bỏ."""
        job = self.job(job_id)
        event = self._cancel.get(job_id)
        if job["status"] == "running" and event:
            event.set()
            self.jobs[job_id]["current"] = "Đang dừng…"
        return self.job(job_id)

    # ------------------------------------------------------------ các lần chạy
    def list_runs(self) -> list[dict]:
        return [{"id": p.name, "label": storage.describe_run(p)} for p in storage.list_runs(self.output_dir)]

    def _run(self, run_id: str) -> dict:
        if not RUN_ID.match(run_id or ""):
            raise ServiceError("Mã lần chạy không hợp lệ.")
        with self._lock:
            if run_id not in self.runs:
                folder = self.output_dir / run_id
                if not (folder / "rows.json").exists():
                    raise ServiceError("Không tìm thấy lần chạy này.")
                rows, rubric, meta = storage.load_run(folder)
                self._trim_run_cache()
                self.runs[run_id] = {"rows": rows, "rubric": rubric, "meta": meta, "folder": folder}
            return self.runs[run_id]

    def _trim_run_cache(self) -> None:
        """Bỏ các lần chạy cũ nhất khỏi bộ nhớ (trừ lần còn chờ ghi Excel): dữ liệu vẫn ở trên đĩa, mở lại sẽ đọc lại."""
        for run_id in list(self.runs):
            if len(self.runs) < MAX_CACHED_RUNS:
                break
            if self.runs[run_id]["folder"] not in self._export_timers:
                del self.runs[run_id]

    # Lưu kết quả sau mỗi thay đổi của HR: rows.json ghi ngay (nhanh); Excel/CSV chậm nên gom lại, ghi sau khi HR ngừng thao tác một lúc.
    def _persist(self, run: dict) -> None:
        storage.write_rows(run["folder"], run["rows"])
        folder = run["folder"]
        with self._lock:
            old = self._export_timers.pop(folder, None)
            if old:
                old.cancel()
            timer = threading.Timer(EXPORT_DELAY, self._flush_export, args=(run,))
            timer.daemon = True
            self._export_timers[folder] = timer
            timer.start()

    def _flush_export(self, run: dict) -> None:
        folder = run["folder"]
        with self._lock:
            self._export_timers.pop(folder, None)
            if self.runs.get(folder.name) is not run or not folder.is_dir():      # lần chạy đã bị xóa
                return
            snapshot = [dict(r) for r in run["rows"]]                           # sao chép nông: ghi file lâu nên không giữ khóa
        try:
            storage.write_exports(folder, snapshot)
            run["export_error"] = ""
        except OSError as e:                              # thường là Excel đang mở ketqua.xlsx: không được làm hỏng thao tác của HR
            run["export_error"] = f"Chưa ghi được file Excel/CSV vào {folder.name} ({type(e).__name__}); nếu đang mở ketqua.xlsx, hãy đóng lại."

    def flush_exports(self) -> None:
        """Ghi ngay các file Excel/CSV còn chờ (khi tắt ứng dụng)."""
        with self._lock:
            pending = list(self._export_timers.items())
        for folder, timer in pending:
            timer.cancel()
            run = self.runs.get(folder.name)
            if run is not None:
                self._flush_export(run)                    # tự gỡ timer khỏi danh sách

    def get_run(self, run_id: str) -> dict:
        run = self._run(run_id)
        with self._lock:
            rows = [{**r, "index": i} for i, r in enumerate(run["rows"])]
            return {"id": run_id, "meta": run["meta"], "rubric": rubric_summary(run["rubric"]), "rows": rows,
                    "can_rejudge": can_rejudge(run["rows"]), "export_error": run.get("export_error", "")}

    def rejudge_run(self, run_id: str, fit: float, maybe: float, reject: float) -> dict:
        """Đổi mức chọn lọc cho lần chạy đã có: tính lại kết luận và xếp hạng ngay, không phải đọc/chấm lại CV. Giữ quyết định của HR."""
        run = self._run(run_id)
        try:
            check_thresholds(fit, maybe, reject)
        except ValueError as e:
            raise ServiceError(str(e)) from e
        with self._lock:
            if not can_rejudge(run["rows"]):
                raise ServiceError("Lần chạy này lưu bằng phiên bản cũ nên không đổi mức được. Hãy sàng lọc lại.")
            rejudge(run["rubric"], run["rows"], fit, maybe, reject)
            run["meta"] = storage.update_meta(run["folder"], fit=fit, maybe=maybe, reject=reject)
            self._persist(run)
        return self.get_run(run_id)

    def delete_run(self, run_id: str) -> None:
        run = self._run(run_id)
        with self._lock:
            self.runs.pop(run_id, None)
            timer = self._export_timers.pop(run["folder"], None)
            if timer:
                timer.cancel()
        shutil.rmtree(run["folder"], ignore_errors=True)

    def set_decision(self, run_id: str, index: int, decision: Optional[str] = None, note: Optional[str] = None) -> dict:
        run = self._run(run_id)
        with self._lock:
            try:
                if int(index) < 0:                              # chỉ số âm của Python lấy từ cuối danh sách: không phải ứng viên cần sửa
                    raise IndexError
                row = run["rows"][int(index)]
            except (IndexError, ValueError, TypeError):
                raise ServiceError("Không tìm thấy ứng viên.") from None
            if decision is not None:
                if decision not in DECISIONS:
                    raise ServiceError("Quyết định không hợp lệ.")
                row["hr_decision"] = decision
            if note is not None:
                row["hr_note"] = str(note)[:2000]
            self._persist(run)
        return {"index": int(index), "hr_decision": row.get("hr_decision", ""), "hr_note": row.get("hr_note", ""),
                "export_error": run.get("export_error", "")}

    def bulk_decision(self, run_id: str, indices: list[int], decision: str) -> int:
        """decision = tên quyết định, hoặc 'accept' để chấp nhận đề xuất của hệ thống cho từng ứng viên."""
        run = self._run(run_id)
        if decision != "accept" and decision not in DECISIONS:
            raise ServiceError("Quyết định không hợp lệ.")
        changed = 0
        with self._lock:
            for i in indices:
                try:
                    if int(i) < 0:
                        continue
                    row = run["rows"][int(i)]
                except (IndexError, ValueError, TypeError):
                    continue
                new = HR_FROM_SUGGESTION.get(row["verdict"], "") if decision == "accept" else decision
                if new != row.get("hr_decision", ""):
                    row["hr_decision"] = new
                    changed += 1
            self._persist(run)
        return changed

    # ------------------------------------------------------------ xuất file
    def export(self, run_id: str, kind: str) -> tuple[bytes, str, str]:
        run = self._run(run_id)
        if kind not in ("xlsx", "csv"):
            raise ServiceError("Định dạng xuất không hỗ trợ.")
        with self._lock:
            rows = [dict(r) for r in run["rows"]]                     # sao chép nông: dựng file lâu nên không giữ khóa
        if kind == "xlsx":
            buf = io.BytesIO()
            write_excel(rows, buf)
            return buf.getvalue(), "ketqua_sangloc.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        tmp = self._tmp / f"export_{uuid.uuid4().hex}.csv"
        try:
            write_csv(rows, tmp)
            return tmp.read_bytes(), "ranking.csv", "text/csv; charset=utf-8"
        finally:
            tmp.unlink(missing_ok=True)

    def report_html(self, run_id: str, scope: str = "suitable") -> str:
        """Trang báo cáo in được (ứng viên phù hợp / đã chọn mời / tất cả)."""
        run = self._run(run_id)
        with self._lock:
            return render_report(run["rows"], rubric_summary(run["rubric"]), run["meta"], scope)

    def emails(self, run_id: str, scope: str = "auto") -> dict:
        run = self._run(run_id)
        rows = run["rows"]
        invited = [r for r in rows if r.get("hr_decision") == "Mời phỏng vấn"]
        if scope == "invited" or (scope == "auto" and invited):
            chosen, label = invited, "ứng viên HR đã chọn “Mời phỏng vấn”"
        else:
            chosen, label = suitable(rows), "ứng viên trong danh sách phù hợp"
        emails = [r["email"] for r in chosen if r.get("email")]
        return {"label": label, "count": len(emails), "emails": emails, "missing": len(chosen) - len(emails)}
