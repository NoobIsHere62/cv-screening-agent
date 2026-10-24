"""Phát hiện CV gần giống nhau (cùng một người nộp hai bản: bản PDF và bản DOCX, hoặc sửa vài dòng rồi nộp lại).

Trùng nguyên văn đã có `pipeline._fingerprint`; ở đây là trùng "gần": độ giống Jaccard của tập cụm 4 từ liên tiếp.
Để không phải so từng cặp khi có hàng nghìn CV: mỗi CV lấy 12 cụm có giá trị băm nhỏ nhất làm "dấu vân tay" (bottom-k MinHash);
hai CV giống nhau từ 65% sẽ chung ít nhất một cụm như vậy với xác suất > 99,9%. Chỉ các cặp chung dấu vân tay mới được so kỹ.
"""
import heapq
import zlib
from collections import defaultdict

SHINGLE = 4                 # độ dài cụm từ liên tiếp
THRESHOLD = 0.65            # độ giống Jaccard từ mức này trở lên là "gần như trùng" (sửa ~5% từ vẫn bắt được)
MIN_WORDS = 40              # CV quá ngắn thì độ giống không có ý nghĩa
SKETCH = 12                 # số cụm trong dấu vân tay mỗi CV
MAX_BUCKET = 40             # cụm xuất hiện ở quá nhiều CV là chữ mẫu chung (footer của mẫu CV...), bỏ qua


def _h(text: str) -> int:
    return zlib.crc32(text.encode("utf-8"))             # không dùng hash(): nó đổi giá trị giữa các lần chạy (PYTHONHASHSEED)


def shingles(fp: str) -> frozenset:
    words = fp.split()
    if len(words) < SHINGLE:
        return frozenset({_h(fp)})
    return frozenset(_h(" ".join(words[i:i + SHINGLE])) for i in range(len(words) - SHINGLE + 1))


def jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / (len(a) + len(b) - inter)


def find_near_duplicates(fingerprints: list[tuple[int, str]], threshold: float = THRESHOLD) -> dict[int, tuple[int, float]]:
    """fingerprints: [(chỉ số, văn bản đã chuẩn hoá)] theo thứ tự đầu vào. Trả về {chỉ số bản sau: (chỉ số bản gốc đứng trước, độ giống)}.
    Mỗi CV chỉ được gán về một bản gốc (bản giống nhất đứng trước nó)."""
    sets = {i: shingles(fp) for i, fp in fingerprints if len(fp.split()) >= MIN_WORDS}
    buckets: dict[int, list[int]] = defaultdict(list)
    for i, sh in sets.items():
        for value in heapq.nsmallest(SKETCH, sh):
            buckets[value].append(i)
    candidates: dict[int, set] = defaultdict(set)
    for members in buckets.values():
        if len(members) > MAX_BUCKET:
            continue
        for a in members:
            for b in members:
                if b < a:
                    candidates[a].add(b)
    out: dict[int, tuple[int, float]] = {}
    for later, earlier_set in candidates.items():
        best = max((jaccard(sets[later], sets[e]), e) for e in earlier_set)
        if best[0] >= threshold:
            out[later] = (best[1], round(best[0], 3))
    return out
