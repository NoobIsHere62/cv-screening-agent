"""Luồng sàng lọc dùng chung cho dòng lệnh và giao diện: đọc -> chấm -> báo cáo -> xếp hạng.

Một CV lỗi không làm hỏng cả lô; CV trùng nội dung được phát hiện; có thể chạy song song và báo tiến độ.
"""
import os
import re
import threading
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Optional

from .config import FIT_THRESHOLD, MAYBE_THRESHOLD, REJECT_THRESHOLD
from .dedupe import find_near_duplicates
from .facts import extract_facts
from .io_utils import SUPPORTED, read_document, word_count
from .jd_rules import build_rubric_rules
from .report import error_row, join_reasons, make_row, rank
from .schemas import Rubric
from .verdict import check_thresholds


# Số luồng mặc định. Chấm CV thuần Python (bị GIL khoá) nên thêm luồng KHÔNG nhanh hơn: đo 600 CV mất 10,8 s với 1 luồng, 8,5 s với 2, 10,3 s với 4,
# còn độ trễ của giao diện (hỏi tiến độ) tăng từ 21 ms lên 63 ms ở 4 luồng. 2 luồng đủ để việc đọc file/OCR chồng lên việc chấm.
DEFAULT_WORKERS = 2
MIN_CV_CHARS = 40
MIN_CV_WORDS = 30


MAX_FOLDER_FILES = 3000
_SKIP_DIRS = {"node_modules", "__pycache__", "site-packages", "$recycle.bin", "system volume information"}


def list_cv_files(path, recursive: bool = False, limit: Optional[int] = None) -> list[Path]:
    """Các file CV trong thư mục (bỏ file tạm của Word `~$...`, file ẩn, thư mục ẩn/hệ thống). Quá `limit` file thì báo lỗi:
    chọn nhầm thư mục gốc ổ đĩa kèm "gồm thư mục con" sẽ làm treo máy chủ cục bộ."""
    p = Path(path)
    limit = MAX_FOLDER_FILES if limit is None else limit
    found: list[Path] = []

    def walk():
        for root, dirs, files in os.walk(p):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d.lower() not in _SKIP_DIRS]     # os.walk bỏ qua thư mục bị loại
            yield Path(root), files

    for root, files in (walk() if recursive else [(p, [f.name for f in p.iterdir() if f.is_file()])]):
        for name in files:
            if Path(name).suffix.lower() in SUPPORTED and not name.startswith(("~$", ".")):
                found.append(root / name)
                if len(found) > limit:
                    raise ValueError(f"Thư mục có hơn {limit} file CV. Hãy chọn thư mục nhỏ hơn hoặc chia thành nhiều lượt.")
    return sorted(found)


def get_scorer(engine: str = "baseline", matcher: str = "keyword", emb_model: Optional[str] = None):
    """Hàm (rubric, text) -> kết quả. Engine luật là mặc định; engine LLM chỉ dùng khi được bật rõ ràng."""
    if engine == "baseline":
        from .baseline import make_embedder, score_cv_baseline
        emb = make_embedder(emb_model) if matcher == "embedding" else None
        return lambda rubric, text, ocr=False: score_cv_baseline(rubric, text, embedder=emb, uncertain=ocr)
    from .config import LLM_ENABLED
    if not LLM_ENABLED:
        raise RuntimeError("Engine LLM đang tắt. Đặt biến môi trường CV_AGENT_ENABLE_LLM=1 (và ANTHROPIC_API_KEY) để bật.")
    from .scoring import score_cv
    return lambda rubric, text, ocr=False: score_cv(rubric, text)


def build_rubric(jd_text: str, engine: str = "baseline") -> Rubric:
    if engine == "baseline":
        return build_rubric_rules(jd_text)
    from .config import LLM_ENABLED
    if not LLM_ENABLED:
        raise RuntimeError("Engine LLM đang tắt. Đặt biến môi trường CV_AGENT_ENABLE_LLM=1 để bật.")
    from .rubric import build_rubric as build_llm
    return build_llm(jd_text)


def _fingerprint(text: str) -> str:
    t = unicodedata.normalize("NFC", text).lower()
    return re.sub(r"[^\w]+", " ", t).strip()


def _process(rubric, scorer, name, path, fit, maybe, reject, ocr):
    try:
        doc = read_document(path, ocr=ocr)
        if len(doc.text.strip()) < MIN_CV_CHARS or word_count(doc.text) < MIN_CV_WORDS:
            raise ValueError(f"Chỉ đọc được {word_count(doc.text)} từ trong CV (file ảnh, font đặc biệt, hoặc nộp nhầm file): "
                             "không đủ để đánh giá, cần xem thủ công")
        facts = extract_facts(doc.text, name, ocr=doc.from_ocr)
        out = scorer(rubric, doc.text, doc.from_ocr)
        row = make_row(rubric, name, out, fit, maybe, reject, doc=doc, facts=facts)
        row["_fp"] = _fingerprint(doc.text)
        row["cv_text"] = doc.text[:8000]                  # để HR đối chiếu với văn bản máy đã đọc (nhất là CV OCR); không ghi vào Excel
        return row
    except Exception as e:                       # một CV lỗi không được làm hỏng cả lô
        return error_row(name, e)


def _flag(row: dict, message: str) -> None:
    row["review_items"].append(message)
    row["review_reason"] = join_reasons(row["review_items"])
    row["needs_human_review"] = "CÓ"


def _mark_duplicates(rows: list[dict]) -> None:
    """CV trùng nguyên văn, rồi CV gần giống (≥ 80% cụm 4 từ): bản đứng sau bị đánh dấu, bản đứng trước giữ nguyên."""
    seen: dict = {}
    pending: list[tuple[int, str]] = []
    for i, r in enumerate(rows):
        fp = r.pop("_fp", None)
        if not fp or "review_items" not in r:
            continue
        if fp in seen:
            _flag(r, f"Nội dung trùng với CV «{seen[fp]}», có thể là nộp trùng")
        else:
            seen[fp] = r["file"]
            pending.append((i, fp))                       # chỉ so các bản chưa trùng nguyên văn
    for later, (earlier, similarity) in find_near_duplicates(pending).items():
        _flag(rows[later], f"Nội dung giống {similarity:.0%} CV «{rows[earlier]['file']}», có thể là cùng một người nộp hai bản")


class Cancelled(Exception):
    """Người dùng huỷ lượt sàng lọc giữa chừng (các CV đang đọc dở được chạy nốt, CV chưa bắt đầu thì bỏ qua)."""


def screen(rubric: Rubric, items: list[tuple[str, Path]], *, engine: str = "baseline", scorer: Callable = None,
           fit: float = FIT_THRESHOLD, maybe: float = MAYBE_THRESHOLD, reject: float = REJECT_THRESHOLD,
           workers: int = DEFAULT_WORKERS, ocr: bool = True, on_progress: Callable[[int, int, str], None] = None,
           cancel: Optional[threading.Event] = None) -> list[dict]:
    """items: [(tên hiển thị, đường dẫn file)]. Trả về các dòng báo cáo đã xếp hạng. `cancel.set()` để dừng (raise Cancelled)."""
    check_thresholds(fit, maybe, reject)
    scorer = scorer or get_scorer(engine)
    rows: list = [None] * len(items)
    workers = max(1, min(workers, len(items) or 1))
    with ThreadPoolExecutor(workers) as pool:
        futures = {pool.submit(_process, rubric, scorer, n, p, fit, maybe, reject, ocr): i for i, (n, p) in enumerate(items)}
        try:
            for done, fut in enumerate(as_completed(futures), 1):
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                i = futures[fut]
                rows[i] = fut.result()
                if on_progress:
                    on_progress(done, len(items), items[i][0])
        except Cancelled:
            pool.shutdown(wait=False, cancel_futures=True)   # CV chưa bắt đầu thì bỏ, không chờ cả lô
            raise
    _mark_duplicates(rows)                       # theo thứ tự đầu vào để "bản gốc" là file đứng trước
    return rank(rows)
