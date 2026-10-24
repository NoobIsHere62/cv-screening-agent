"""Dòng lệnh (mặc định chạy bằng luật, không cần LLM, không cần internet).

  python run.py rubric jd.txt -o rubrics/jd.json                       JD -> rubric + JD đã lọc (rubrics/jd.core.txt)
  python run.py score rubrics/jd.json cvs/ -o ranking.csv --excel kq.xlsx
  python run.py score rubrics/jd.json cv1.pdf cv2.docx "cvs/*.txt"     thư mục, file, hoặc mẫu glob
Tùy chọn hay dùng: --fit 70 --maybe 50 --reject 30 (ngưỡng điểm), --workers 4, --recursive, --no-ocr
(muốn dùng engine LLM tùy chọn: đặt CV_AGENT_ENABLE_LLM=1 và ANTHROPIC_API_KEY rồi thêm --engine llm)
"""
import argparse
import glob
import sys
from pathlib import Path

from cv_agent.config import FIT_THRESHOLD, MAYBE_THRESHOLD, REJECT_THRESHOLD
from cv_agent.io_utils import SUPPORTED, read_text
from cv_agent.jd_filter import core_jd_text
from cv_agent.pipeline import DEFAULT_WORKERS, build_rubric, get_scorer, list_cv_files, screen
from cv_agent.report import count_by_verdict, suitable, write_csv, write_excel
from cv_agent.schemas import Rubric
from cv_agent.textutil import safe_console
from cv_agent.verdict import ALL, ERROR


def collect(paths, recursive=False):
    """Gộp thư mục, file và mẫu glob (cmd/PowerShell trên Windows không tự mở rộng `*`)."""
    files = []
    for p in paths:
        matches = glob.glob(p) or [p]
        for m in matches:
            mp = Path(m)
            if mp.is_dir():
                files += list_cv_files(mp, recursive)
            elif mp.suffix.lower() in SUPPORTED:
                files.append(mp)
            else:
                print(f"[BỎ QUA] {m}: không phải file CV hợp lệ ({', '.join(sorted(SUPPORTED))})", file=sys.stderr)
    seen, out = set(), []
    for f in files:                                  # bỏ trùng đường dẫn
        key = f.resolve()
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


def cmd_rubric(args):
    rubric = build_rubric(read_text(args.jd), args.engine)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rubric.model_dump_json(indent=2), encoding="utf-8")
    print(f"Đã lưu rubric: {out}  ({len(rubric.criteria)} tiêu chí, {len(rubric.hard_requirements)} điều kiện cứng)")
    core = out.with_suffix(".core.txt")
    core.write_text(core_jd_text(rubric), encoding="utf-8")
    print(f"JD đã lọc (chỉ điều kiện + kỹ năng cần thiết): {core}")
    for note in rubric.jd_analysis.ambiguities:
        print("  -", note)
    print("Hãy đọc lại JD đã lọc / rubric trước khi chấm CV, và sửa tay nếu cần.")


def cmd_score(args):
    rubric = Rubric.model_validate_json(Path(args.rubric).read_text(encoding="utf-8"))
    files = collect(args.cvs, args.recursive)
    if not files:
        sys.exit("Không tìm thấy CV nào (hỗ trợ .txt .md .pdf .docx).")
    scorer = get_scorer(args.engine, args.matcher, args.emb_model)

    def progress(done, total, name):
        print(f"[{done}/{total}] {name}")

    rows = screen(rubric, [(f.name, f) for f in files], scorer=scorer, fit=args.fit, maybe=args.maybe,
                  reject=args.reject, workers=args.workers, ocr=not args.no_ocr, on_progress=progress)

    write_csv(rows, args.output)
    print(f"\nĐã lưu bảng xếp hạng: {args.output}")
    if args.excel:
        write_excel(rows, args.excel)
        print(f"Đã lưu Excel: {args.excel}")
    counts = count_by_verdict(rows)
    print("Tổng kết: " + ", ".join(f"{v} {counts[v]}" for v in ALL + [ERROR] if counts[v]))
    ok = suitable(rows)
    print(f"\nDanh sách phù hợp ({len(ok)}/{len(rows)} CV):")
    for r in ok:
        flag = "  (cần xem lại)" if r["needs_human_review"] == "CÓ" else ""
        print(f"  #{r['rank']} {r['candidate_name']} [{r['file']}]: {r['overall_score']} - {r['verdict']}{flag}")


def add_engine_args(p):
    p.add_argument("--engine", choices=["baseline", "llm"], default="baseline",
                   help="baseline = luật, không cần LLM (mặc định). llm = tùy chọn, phải bật CV_AGENT_ENABLE_LLM=1")
    p.add_argument("--matcher", choices=["keyword", "embedding"], default="keyword",
                   help="chỉ cho baseline; embedding cần sentence-transformers và chưa được kiểm chứng")
    p.add_argument("--emb-model", default=None)


def main():
    safe_console()
    ap = argparse.ArgumentParser(description="Sàng lọc CV theo JD")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("rubric", help="JD -> rubric JSON + JD đã lọc")
    a.add_argument("jd")
    a.add_argument("-o", "--output", required=True)
    add_engine_args(a)
    a.set_defaults(fn=cmd_rubric)

    b = sub.add_parser("score", help="chấm nhiều CV theo rubric")
    b.add_argument("rubric")
    b.add_argument("cvs", nargs="+", help="thư mục, file hoặc mẫu glob")
    b.add_argument("-o", "--output", default="ranking.csv")
    b.add_argument("--excel", default=None, help="xuất thêm file .xlsx có tô màu theo kết luận")
    b.add_argument("--fit", type=float, default=FIT_THRESHOLD, help="từ mức này (và đủ điều kiện): Phù hợp - Mời phỏng vấn")
    b.add_argument("--maybe", type=float, default=MAYBE_THRESHOLD, help="từ mức này: Có thể mời phỏng vấn")
    b.add_argument("--reject", type=float, default=REJECT_THRESHOLD, help="dưới mức này: Loại")
    b.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="số luồng (chấm CV bị GIL khoá nên hơn 2 hiếm khi nhanh hơn)")
    b.add_argument("--recursive", action="store_true", help="lấy cả thư mục con")
    b.add_argument("--no-ocr", action="store_true", help="không OCR PDF scan (CV scan sẽ báo lỗi)")
    add_engine_args(b)
    b.set_defaults(fn=cmd_score)

    args = ap.parse_args()
    try:
        args.fn(args)
    except (ValueError, RuntimeError, OSError) as e:               # lỗi người dùng (file đang mở trong Excel, thư mục không có...): in gọn
        sys.exit(f"Lỗi: {e}")


if __name__ == "__main__":
    main()
