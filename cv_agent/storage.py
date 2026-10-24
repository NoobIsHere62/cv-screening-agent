"""Lưu và mở lại các lần sàng lọc (mỗi lần một thư mục trong outputs/), kèm quyết định của HR."""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from .report import write_csv, write_excel
from .schemas import Rubric

def default_dir() -> Path:
    """Thư mục lưu kết quả: biến môi trường CV_AGENT_OUTPUT_DIR, mặc định là outputs/ cạnh mã nguồn. Đọc lúc gọi để test thay được."""
    return Path(os.getenv("CV_AGENT_OUTPUT_DIR") or Path(__file__).resolve().parent.parent / "outputs")

HR_DECISIONS = ["", "Mời phỏng vấn", "Giữ lại", "Từ chối"]


def save_run(rows: list[dict], rubric: Rubric, core_text: str, meta: Optional[dict] = None, base: Optional[Path] = None) -> Path:
    """Tạo thư mục mới và ghi Excel, CSV, rows.json, rubric.json, JD đã lọc, meta.json. Trả về thư mục."""
    base = base or default_dir()
    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder, n = base / stamp, 1
    while folder.exists():                       # hai lần chạy trong cùng một giây
        n += 1
        folder = base / f"{stamp}_{n}"
    folder.mkdir()
    (folder / "rubric.json").write_text(rubric.model_dump_json(indent=2), encoding="utf-8")
    (folder / "jd_da_loc.txt").write_text(core_text, encoding="utf-8")
    info = {"created": datetime.now().isoformat(timespec="seconds"), "title": rubric.jd_analysis.job_title,
            "n_cv": len(rows), **(meta or {})}
    (folder / "meta.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    update_rows(folder, rows)
    return folder


def _write_atomic(path: Path, text: str) -> None:
    """Ghi ra file tạm rồi đổi tên: mất điện / tắt máy giữa chừng không làm hỏng dữ liệu đã lưu."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def write_rows(folder: Path, rows: list[dict]) -> None:
    """Ghi dữ liệu chính (rows.json): nhanh (vài chục ms kể cả vài trăm CV), nên làm ngay sau mỗi thay đổi của HR."""
    _write_atomic(folder / "rows.json", json.dumps(rows, ensure_ascii=False, default=list))


def write_exports(folder: Path, rows: list[dict]) -> None:
    """Ghi Excel và CSV tiện dụng. Excel chậm (~2,5 giây cho 600 CV) nên giao diện gọi hàm này sau khi HR ngừng thao tác
    một lúc, không gọi sau mỗi lần bấm. Ghi ra file tạm rồi đổi tên; nếu Excel đang mở file thì ném PermissionError cho người gọi xử lý."""
    for name, writer in (("ranking.csv", write_csv), ("ketqua.xlsx", write_excel)):
        target = folder / name
        tmp = folder / (name + ".tmp")
        try:
            writer(rows, tmp)
            os.replace(tmp, target)
        finally:
            tmp.unlink(missing_ok=True)


def update_rows(folder: Path, rows: list[dict]) -> None:
    """Ghi lại kết quả và các file xuất ngay (dùng khi lưu cả lần chạy)."""
    write_rows(folder, rows)
    write_exports(folder, rows)


def update_meta(folder: Path, **changes) -> dict:
    """Cập nhật meta.json (ví dụ ngưỡng sau khi đổi mức chọn lọc). Trả về meta mới."""
    meta_file = folder / "meta.json"
    meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
    meta.update(changes)
    _write_atomic(meta_file, json.dumps(meta, ensure_ascii=False, indent=2))
    return meta


def load_run(folder: Path):
    """-> (rows, rubric, meta)"""
    rows = json.loads((folder / "rows.json").read_text(encoding="utf-8"))
    for r in rows:
        r["criteria"] = [tuple(c) for c in r.get("criteria", [])]
    rubric = Rubric.model_validate_json((folder / "rubric.json").read_text(encoding="utf-8"))
    meta_file = folder / "meta.json"
    meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
    return rows, rubric, meta


def list_runs(base: Optional[Path] = None) -> list[Path]:
    """Các lần chạy đã lưu, mới nhất trước."""
    base = base or default_dir()
    if not base.exists():
        return []
    return sorted((p for p in base.iterdir() if (p / "rows.json").exists() and (p / "rubric.json").exists()), reverse=True)


def describe_run(folder: Path) -> str:
    """Nhãn dễ đọc cho danh sách: '20/10 20:25 · Kỹ sư AI · 9 CV'."""
    try:
        meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
        when = datetime.fromisoformat(meta["created"]).strftime("%d/%m %H:%M")
        title = meta.get("title") or "JD"
        if title.startswith("(") or title == "Vị trí tuyển dụng":
            title = "JD"
        return f"{when} · {title[:28]} · {meta.get('n_cv', '?')} CV"
    except (OSError, ValueError, KeyError):
        try:                                      # thư mục cũ không có meta.json: lấy giờ từ tên thư mục
            return datetime.strptime(folder.name[:15], "%Y%m%d_%H%M%S").strftime("%d/%m %H:%M") + " · lần chạy cũ"
        except ValueError:
            return folder.name
