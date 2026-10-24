"""Hiệu chỉnh ngưỡng quyết định (FIT/MAYBE) cho engine luật, có đánh giá chéo theo từng JD.

  python calibrate.py samples data_heldout

Mỗi thư mục có: jds/<jd_id>.txt, cvs/<cv_id>.txt, labels.csv (jd_id, cv_id, human_decision).
Với mỗi JD, ngưỡng được chọn trên CÁC JD CÒN LẠI rồi đo trên JD đó (leave-one-JD-out), nên con số cuối
phản ánh khả năng tổng quát hoá tốt hơn là chọn ngưỡng trên toàn bộ rồi đo lại trên chính nó.
Với ít dữ liệu, kết quả chỉ mang tính tham khảo; hãy dùng CV thật khi có.
"""
import sys
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    sys.exit("Thiếu thư viện pandas. Chạy:  python -m pip install -r requirements-eval.txt")

from cv_agent.aggregate import aggregate
from cv_agent.baseline import build_rubric_rules, score_cv_baseline
from cv_agent.config import FIT_THRESHOLD, MAYBE_THRESHOLD
from cv_agent.io_utils import read_text

FITS = [x / 2 for x in range(100, 181, 5)]          # 50 .. 90 bước 2.5
MAYBES = [x / 2 for x in range(30, 141, 5)]         # 15 .. 70


def collect(dirs):
    items = []
    for d in dirs:
        label_file = Path(d) / "labels.csv"
        if not label_file.exists():
            print(f"[BỎ QUA] {d}: không có labels.csv")
            continue
        labels = pd.read_csv(label_file)
        rubrics = {}
        for r in labels.itertuples():
            key = (d, r.jd_id)
            if key not in rubrics:
                rubrics[key] = build_rubric_rules(read_text(f"{d}/jds/{r.jd_id}.txt"))
            out = score_cv_baseline(rubrics[key], read_text(f"{d}/cvs/{r.cv_id}.txt"))
            items.append({"jd": f"{d}/{r.jd_id}", "human": r.human_decision, "rubric": rubrics[key], "result": out["detail"]})
    return items


def evaluate(items, fit, maybe):
    ok = severe = 0
    for it in items:
        pred = aggregate(it["rubric"], it["result"], fit, maybe)["decision"]
        ok += pred == it["human"]
        severe += {pred, it["human"]} == {"Phù hợp", "Không phù hợp"}
    return ok / len(items), severe / len(items)


def best_thresholds(items):
    best, best_key = None, None
    for fit in FITS:
        for maybe in MAYBES:
            if maybe >= fit - 5:
                continue
            acc, sev = evaluate(items, fit, maybe)
            key = (-acc, sev, abs(fit - FIT_THRESHOLD) + abs(maybe - MAYBE_THRESHOLD))   # chính xác nhất, ít lỗi nặng, gần mặc định
            if best_key is None or key < best_key:
                best, best_key = (fit, maybe), key
    return best


def main(dirs):
    items = collect(dirs)
    if not items:
        sys.exit("Không có dữ liệu có nhãn để hiệu chỉnh.")
    print(f"{len(items)} CV, {len({i['jd'] for i in items})} JD")
    acc0, sev0 = evaluate(items, FIT_THRESHOLD, MAYBE_THRESHOLD)
    print(f"\nNgưỡng mặc định ({FIT_THRESHOLD:g}/{MAYBE_THRESHOLD:g}): accuracy {acc0:.0%}, lỗi nghiêm trọng {sev0:.0%}")

    jds = sorted({i["jd"] for i in items})
    if len(jds) < 2:
        print("Chỉ có 1 JD nên không đánh giá chéo được; cần ít nhất 2 JD.")
        return
    tot_ok = tot_n = 0
    print("\nĐánh giá chéo theo JD (chọn ngưỡng trên các JD khác, đo trên JD này):")
    for jd in jds:
        train = [i for i in items if i["jd"] != jd]
        test = [i for i in items if i["jd"] == jd]
        fit, maybe = best_thresholds(train)
        acc, _ = evaluate(test, fit, maybe)
        base, _ = evaluate(test, FIT_THRESHOLD, MAYBE_THRESHOLD)
        tot_ok += acc * len(test)
        tot_n += len(test)
        print(f"  {jd:16} chọn {fit:g}/{maybe:g}  accuracy {acc:.0%}  (mặc định: {base:.0%})")
    print(f"  Trung bình có hiệu chỉnh: {tot_ok / tot_n:.0%}   mặc định: {acc0:.0%}")

    fit, maybe = best_thresholds(items)
    acc, sev = evaluate(items, fit, maybe)
    print(f"\nNgưỡng tốt nhất trên toàn bộ dữ liệu: FIT={fit:g}, MAYBE={maybe:g}  (accuracy {acc:.0%}, lỗi nghiêm trọng {sev:.0%})")
    print("Con số này lạc quan vì chọn và đo trên cùng dữ liệu; dùng số đánh giá chéo ở trên để ước lượng thực tế.")
    print("Để dùng: đặt FIT_THRESHOLD / MAYBE_THRESHOLD trong cv_agent/config.py.")


if __name__ == "__main__":
    main(sys.argv[1:] or ["samples", "data_heldout"])
