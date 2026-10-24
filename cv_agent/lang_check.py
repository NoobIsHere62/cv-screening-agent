"""Điều kiện chứng chỉ ngoại ngữ (TOEIC / IELTS / TOEFL iBT): đọc yêu cầu từ JD, tìm chứng chỉ trong CV, so sánh.

Bảng quy đổi chỉ là ƯỚC LƯỢNG thô (các tổ chức công bố bảng khác nhau): quy hết về thang TOEIC rồi so sánh.
Không thấy chứng chỉ trong CV thì trả về `unclear` (cần người xem), không bị loại.
"""
import re
from typing import Optional

from .schemas import HardCheck

LANG_CERT = re.compile(r"toeic|ielts|toefl", re.I)

_IELTS_TOEIC = [(4.0, 400), (4.5, 550), (5.0, 600), (5.5, 700), (6.0, 800), (6.5, 850), (7.0, 900), (8.0, 950)]
_TOEFL_TOEIC = [(32, 450), (41, 550), (46, 600), (60, 700), (80, 800), (94, 900)]

_PAREN = r"\s*(?:\([^)\n]{0,20}\))?"                    # "TOEIC (2023): 800", "IELTS (Academic) 6.5"
_PATTERNS = {
    "toeic": re.compile(rf"toeic{_PAREN}[^0-9\n]{{0,25}}?(\d{{3}})(?![\d.])", re.I),
    "ielts": re.compile(rf"ielts{_PAREN}[^0-9\n]{{0,25}}?([4-9](?:[.,][05])?)(?![\d])", re.I),
    "toefl": re.compile(rf"toefl{_PAREN}[^0-9\n]{{0,25}}?(\d{{2,3}})(?![\d.])", re.I),
}
_NUMBER = r"([0-9]+(?:[.,][0-9]+)?)"
_TOEIC_PARTS = re.compile(r"listening|reading|\(\s*[lr]\s*\)|\bl\s*&\s*r\b|\bl/r\b", re.I)


def _toeic_total(line: str, first: str) -> str:
    """TOEIC ghi theo từng kỹ năng ("Listening 450 Reading 400", "450 (L) + 400 (R) = 850"): lấy tổng, không lấy điểm của một phần."""
    if not _TOEIC_PARTS.search(line):
        return first
    m = re.search(r"=\s*(\d{3})(?![\d.])", line)
    if m and 10 <= int(m.group(1)) <= 990:
        return m.group(1)
    nums = [int(n) for n in re.findall(r"(?<![\d.])(\d{2,3})(?![\d.])", line[re.search("toeic", line, re.I).start():])]
    parts = [n for n in nums if 5 <= n <= 495]
    if len(parts) == 2 and len(nums) == 2:
        return str(sum(parts))
    return first


def _to_toeic(kind: str, value: float) -> float:
    table = {"toeic": None, "ielts": _IELTS_TOEIC, "toefl": _TOEFL_TOEIC}[kind]
    if table is None:
        return value
    best = 0
    for threshold, toeic in table:
        if value >= threshold:
            best = toeic
    return float(best)


def _scores(line: str):
    """Các chứng chỉ trong một dòng -> (loại, chuỗi điểm như trong CV, điểm quy ra thang TOEIC)."""
    for kind, rx in _PATTERNS.items():
        for m in rx.finditer(line):
            raw = _toeic_total(line, m.group(1)) if kind == "toeic" else m.group(1)
            try:
                yield kind, raw.replace(",", "."), _to_toeic(kind, float(raw.replace(",", ".")))
            except ValueError:
                continue


def parse_required(text: str) -> Optional[tuple[str, float]]:
    """-> (loại, điểm) nhỏ nhất mà JD chấp nhận, quy ra thang TOEIC; None nếu JD không nêu điểm cụ thể."""
    found = []
    for kind, rx in _PATTERNS.items():
        m = rx.search(text) or re.search(rf"{kind}[^0-9\n]{{0,25}}?[≥>]=?\s*{_NUMBER}", text, re.I)
        if m:
            try:
                found.append(_to_toeic(kind, float(m.group(1).replace(",", "."))))
            except ValueError:                           # "TOEIC ≥ ." : không có điểm cụ thể
                continue
    return ("toeic", min(found)) if found else None


def best_certificate(cv_text: str) -> tuple[str, float]:
    """Chứng chỉ ngoại ngữ cao nhất trong CV -> ('TOEIC 790', điểm quy đổi TOEIC); ('', 0.0) nếu không thấy."""
    best = ("", 0.0)
    for line in cv_text.splitlines():
        for kind, raw, eq in _scores(line):
            if eq > best[1]:
                best = (f"{kind.upper()} {raw}", eq)
    return best


def check_language(requirement: str, cv_text: str) -> HardCheck:
    req = parse_required(requirement)
    if req is None:
        return HardCheck(requirement_id="", status="unclear", note="JD nêu chứng chỉ ngoại ngữ nhưng không có điểm cụ thể, cần người xem")
    need = req[1]
    best, evidence = None, ""
    for line in cv_text.splitlines():
        for _, _, v in _scores(line):
            if best is None or v > best:
                best, evidence = v, line.strip()
    if best is None:
        return HardCheck(requirement_id="", status="unclear",
                         note=f"Không thấy chứng chỉ TOEIC/IELTS/TOEFL trong CV (JD yêu cầu ~TOEIC {need:g}), cần người xem")
    if best >= need:
        return HardCheck(requirement_id="", status="met", evidence=evidence,
                         note=f"Chứng chỉ trong CV quy đổi ~TOEIC {best:g} (yêu cầu {need:g}; bảng quy đổi chỉ là ước lượng)")
    return HardCheck(requirement_id="", status="not_met", evidence=evidence,
                     note=f"Chứng chỉ trong CV quy đổi ~TOEIC {best:g}, thấp hơn yêu cầu {need:g}")
