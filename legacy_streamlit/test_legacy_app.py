"""Kiểm thử giao diện Streamlit cũ (KHÔNG chạy trong bộ test chính):  python -m unittest legacy_streamlit.test_legacy_app
Cần: pip install -r legacy_streamlit/requirements.txt"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
os.environ["CV_AGENT_AS_OF"] = "2026-10"

from webui import components as ui  # noqa: E402


class ComponentTests(unittest.TestCase):
    EVIL = '<script>alert(1)</script><img src=x onerror=alert(2)> "quoted" & more'

    def test_esc_neutralises_html(self):
        out = ui.esc(self.EVIL)
        self.assertNotIn("<script", out)
        self.assertNotIn("<img", out)
        self.assertIn("&lt;script&gt;", out)

    def test_every_component_escapes_cv_text(self):
        pieces = [ui.chip(self.EVIL), ui.chips([self.EVIL]), ui.callout(self.EVIL, "", self.EVIL), ui.kpi(self.EVIL, self.EVIL),
                  ui.criteria_table([(self.EVIL, 3, self.EVIL, [self.EVIL])]), ui.empty_state("x", self.EVIL, self.EVIL),
                  ui.howto([(self.EVIL, self.EVIL)]), ui.hero(self.EVIL, self.EVIL, self.EVIL), ui.badge(self.EVIL)]
        for html_text in pieces:
            self.assertNotIn("<script", html_text)
            self.assertNotIn("<img", html_text)

    def test_score_bar_is_clamped(self):
        import re
        for score in (-5, 0, 55.5, 100, 250):
            width = float(re.search(r"width:([\d.]+)%", ui.score_bar(score, 70, 50, 30, "#000")).group(1))
            self.assertTrue(0 <= width <= 100)


class AppFlowTests(unittest.TestCase):
    """Chạy app.py thật (không trình duyệt) với JD mẫu và 9 CV mẫu."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        os.environ["CV_AGENT_OUTPUT_DIR"] = cls._tmp.name

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("CV_AGENT_OUTPUT_DIR", None)
        cls._tmp.cleanup()

    def _app(self):
        from streamlit.testing.v1 import AppTest
        return AppTest.from_file(str(HERE / "app.py"), default_timeout=120).run()

    def test_full_flow_filter_screen_and_hr_decision(self):
        at = self._app()
        self.assertEqual([e.value for e in at.exception], [])
        at.session_state["jd_text"] = (ROOT / "samples" / "jds" / "ai01.txt").read_text(encoding="utf-8")
        at.session_state["folder"] = str(ROOT / "samples" / "cvs")
        at.run()
        next(b for b in at.button if b.label.strip().endswith("Lọc JD")).click().run()
        next(b for b in at.button if "Bắt đầu sàng lọc" in b.label).click().run()
        self.assertEqual([e.value for e in at.exception], [])
        rows = at.session_state["rows"]
        self.assertEqual(len(rows), 9)
        saved = Path(at.session_state["saved_to"])
        decision_box = next(s for s in at.selectbox if s.key and s.key.startswith("dec_"))
        decision_box.set_value("Mời phỏng vấn").run()
        persisted = json.loads((saved / "rows.json").read_text(encoding="utf-8"))
        self.assertIn("Mời phỏng vấn", [r.get("hr_decision") for r in persisted])


if __name__ == "__main__":
    unittest.main()
