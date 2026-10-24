"""Kiểm thử lưu / mở lại các lần sàng lọc."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["CV_AGENT_AS_OF"] = "2026-10"

from cv_agent import storage  # noqa: E402
from cv_agent.pipeline import build_rubric, screen  # noqa: E402


class StorageTests(unittest.TestCase):
    def test_round_trip_and_decisions_are_persisted(self):
        rubric = build_rubric("Yêu cầu:\n- Biết Python\n- Biết Git\n")
        with tempfile.TemporaryDirectory() as tmp:
            cv = Path(tmp) / "a.txt"
            cv.write_text("Nguyễn Văn A\nSKILLS\nPython, Git\nEXPERIENCE\nDev – X (2020 - 2024)\n- Python, Git\n" + "services " * 30, encoding="utf-8")
            rows = screen(rubric, [("a.txt", cv)])
            base = Path(tmp) / "out"
            folder = storage.save_run(rows, rubric, "core", {"fit": 70}, base=base)
            self.assertEqual(storage.list_runs(base), [folder])
            rows[0]["hr_decision"] = "Mời phỏng vấn"
            storage.update_rows(folder, rows)
            loaded, rb, meta = storage.load_run(folder)
            self.assertEqual(loaded[0]["hr_decision"], "Mời phỏng vấn")
            self.assertEqual(meta["n_cv"], 1)
            self.assertTrue((folder / "ketqua.xlsx").exists() and (folder / "ranking.csv").exists())
            self.assertIn("1 CV", storage.describe_run(folder))

    def test_two_runs_in_the_same_second_do_not_collide(self):
        rubric = build_rubric("Yêu cầu:\n- Biết Python\n")
        with tempfile.TemporaryDirectory() as tmp:
            a = storage.save_run([], rubric, "x", base=Path(tmp))
            b = storage.save_run([], rubric, "x", base=Path(tmp))
            self.assertNotEqual(a, b)

    def test_rows_survive_a_save_load_cycle_with_criteria_tuples(self):
        rubric = build_rubric("Yêu cầu:\n- Biết Python\n")
        with tempfile.TemporaryDirectory() as tmp:
            cv = Path(tmp) / "a.txt"
            cv.write_text("Nguyễn Văn A\nSKILLS\nPython\nEXPERIENCE\nDev – X (2020 - 2024)\n- Python\n" + "services " * 30, encoding="utf-8")
            rows = screen(rubric, [("a.txt", cv)])
            folder = storage.save_run(rows, rubric, "core", base=Path(tmp) / "out")
            loaded, _, _ = storage.load_run(folder)
            self.assertIsInstance(loaded[0]["criteria"][0], tuple)
            self.assertEqual(loaded[0]["verdict_inputs"], rows[0]["verdict_inputs"])          # đủ để đổi mức chọn lọc sau khi mở lại


if __name__ == "__main__":
    unittest.main()
