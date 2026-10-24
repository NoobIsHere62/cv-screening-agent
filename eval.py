"""Đánh giá agent trên dữ liệu có nhãn của người.

  python eval.py --data data_heldout            (engine luật, mặc định, không cần LLM)
  python eval.py --data samples
  python eval.py --engine llm --data samples    (tùy chọn; cần CV_AGENT_ENABLE_LLM=1, ANTHROPIC_API_KEY và <data>/rubrics/<jd_id>.json)

Dữ liệu: <data>/jds/<jd_id>.txt, <data>/cvs/<cv_id>.txt, <data>/labels.csv (jd_id,cv_id,human_decision,human_score,note)
Hai thước đo:
  1. kết luận 3 mức (Phù hợp / Cân nhắc / Không phù hợp) so với nhãn của người;
  2. kết luận 4 mức mà HR thực sự thấy: danh sách phù hợp có chứa người đáng mời không, có lọt người không đáng mời không,
     và có loại nhầm người đáng mời không (lỗi nặng nhất).
"""
import argparse
import json
import sys
from pathlib import Path

try:
    import pandas as pd
    from scipy.stats import spearmanr
except ImportError:
    sys.exit("Thiếu thư viện đo độ chính xác. Chạy:  python -m pip install -r requirements-eval.txt")

from cv_agent.io_utils import read_text
from cv_agent.schemas import Rubric
from cv_agent.verdict import REJECT, SUITABLE, verdict

N_RUNS = 3                                   # engine LLM không tất định nên chạy nhiều lần; engine luật chỉ 1 lần
PROMPT_VERSION = "v1"                        # đổi khi sửa prompt/ngưỡng để không dùng nhầm cache (engine LLM)
ORDER = {"Không phù hợp": 0, "Cân nhắc": 1, "Phù hợp": 2}
OUT_DIR = Path("outputs")


def run_one(args, jd_id, cv_id, i, cache):
    cv_text = read_text(f"{args.data}/cvs/{cv_id}.txt")
    if args.engine == "baseline":
        from cv_agent.baseline import build_rubric_rules, make_embedder, score_cv_baseline
        if jd_id not in cache:
            cache[jd_id] = build_rubric_rules(read_text(f"{args.data}/jds/{jd_id}.txt"))
        if args.matcher == "embedding" and "emb" not in cache:
            cache["emb"] = make_embedder(args.emb_model)
        out = score_cv_baseline(cache[jd_id], cv_text, embedder=cache.get("emb"))
        return {"summary": out["summary"], "stats": out["stats"]}
    from cv_agent.config import LLM_ENABLED
    if not LLM_ENABLED:
        sys.exit("Engine LLM đang tắt: đặt CV_AGENT_ENABLE_LLM=1 (và ANTHROPIC_API_KEY), hoặc dùng --engine baseline.")
    from cv_agent.scoring import score_cv
    OUT_DIR.mkdir(exist_ok=True)
    cache_dir = OUT_DIR / "eval_cache"
    cache_dir.mkdir(exist_ok=True)
    f = cache_dir / f"{PROMPT_VERSION}__{args.data.replace('/', '_').replace(chr(92), '_')}__{jd_id}__{cv_id}__{i}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    rubric = Rubric.model_validate_json(Path(f"{args.data}/rubrics/{jd_id}.json").read_text(encoding="utf-8"))
    out = score_cv(rubric, cv_text)
    rec = {"summary": out["summary"], "stats": out["stats"]}
    f.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=["baseline", "llm"], default="baseline")
    ap.add_argument("--matcher", choices=["keyword", "embedding"], default="keyword")
    ap.add_argument("--emb-model", default=None)
    ap.add_argument("--data", default="data", help="thư mục dữ liệu có nhãn")
    args = ap.parse_args()
    n_runs = 1 if args.engine == "baseline" else N_RUNS

    labels_path = Path(args.data) / "labels.csv"
    if not labels_path.exists():
        sys.exit(f"Không có {labels_path}. Cần file nhãn: jd_id,cv_id,human_decision,human_score,note "
                 "(ví dụ dùng --data samples hoặc --data data_heldout).")
    labels = pd.read_csv(labels_path)
    rows, cache = [], {}
    for r in labels.itertuples():
        runs = [run_one(args, r.jd_id, r.cv_id, i, cache) for i in range(n_runs)]
        scores = [x["summary"]["overall_score"] for x in runs]
        decs = [x["summary"]["decision"] for x in runs]
        verdicts = [verdict(x["summary"]) for x in runs]
        pred = max(set(decs), key=decs.count)
        rows.append({
            "jd_id": r.jd_id, "cv_id": r.cv_id, "human": r.human_decision,
            "human_score": getattr(r, "human_score", None),
            "pred": pred, "verdict": max(set(verdicts), key=verdicts.count),
            "mean_score": sum(scores) / n_runs,
            "score_std": pd.Series(scores).std(ddof=0),
            "agree": decs.count(pred) / n_runs,
            "ev_total": sum(x["stats"]["evidence_total"] for x in runs),
            "ev_drop": sum(x["stats"]["evidence_dropped"] for x in runs),
        })
    df = pd.DataFrame(rows)

    acc = (df.human == df.pred).mean()
    severe = (((df.human == "Phù hợp") & (df.pred == "Không phù hợp")) |
              ((df.human == "Không phù hợp") & (df.pred == "Phù hợp"))).mean()
    print(f"[{len(df)} CV, {df.jd_id.nunique()} JD, engine {args.engine}]")
    print(f"Accuracy 3 mức:        {acc:.0%}")
    print(f"Lỗi nghiêm trọng:      {severe:.0%}  (Phù hợp <-> Không phù hợp)")
    print("\nConfusion matrix (hàng = người, cột = agent):")
    print(pd.crosstab(df.human, df.pred))

    good, bad = df[df.human == "Phù hợp"], df[df.human == "Không phù hợp"]
    print("\nThước đo trên kết luận 4 mức mà HR thấy:")
    if len(good):
        print(f"  Người 'Phù hợp' nằm trong danh sách phù hợp: {good.verdict.isin(SUITABLE).mean():.0%}  ({len(good)} CV)")
        print(f"  Người 'Phù hợp' bị xếp 'Loại' nhầm:          {(good.verdict == REJECT).mean():.0%}   <- lỗi nặng nhất")
    if len(bad):
        print(f"  Người 'Không phù hợp' lọt vào danh sách:      {bad.verdict.isin(SUITABLE).mean():.0%}  ({len(bad)} CV)")
    print("\n" + pd.crosstab(df.human, df.verdict).to_string())

    cors = []
    for jd, g in df.groupby("jd_id"):
        truth = g.human_score if g.human_score.notna().all() else g.human.map(ORDER)
        if len(g) >= 4 and truth.nunique() > 1:
            c, _ = spearmanr(g.mean_score, truth)
            cors.append(c)
            print(f"  Spearman {jd}: {c:.2f}")
    if cors:
        print(f"Spearman trung bình:   {sum(cors) / len(cors):.2f}")

    print(f"\nĐộ lệch chuẩn điểm giữa {n_runs} lần: {df.score_std.mean():.1f} điểm")
    print(f"Quyết định nhất quán:  {df.agree.mean():.0%}")
    print(f"Evidence bị loại:      {df.ev_drop.sum() / max(df.ev_total.sum(), 1):.0%}")

    wrong = df[df.human != df.pred][["jd_id", "cv_id", "human", "pred", "verdict", "mean_score"]]
    print("\nCác ca sai:")
    print(wrong.to_string(index=False))
    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / f"eval_results_{args.engine}_{Path(args.data).name}.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\nĐã lưu: {out}")


if __name__ == "__main__":
    main()
