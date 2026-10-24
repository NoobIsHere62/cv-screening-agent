"""Kiểm thử các lỗi tìm ra khi chạy CV PDF thật (font icon, chữ vẽ thành đường nét, link bị cắt, tên dính chữ, JD nêu số năm hai lần...)
và các tính năng nâng cấp (huỷ tác vụ, đổi mức chọn lọc tại chỗ, ghi file an toàn)."""
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["CV_AGENT_AS_OF"] = "2026-10"

from cv_agent import io_utils, storage  # noqa: E402
from cv_agent.baseline import score_cv_baseline  # noqa: E402
from cv_agent.identity import find_name  # noqa: E402
from cv_agent.pipeline import Cancelled, build_rubric, screen  # noqa: E402
from cv_agent.report import build_checklist, can_rejudge, rejudge  # noqa: E402
from cv_agent.verdict import REJECT, RESERVE  # noqa: E402

SAMPLES = ROOT / "samples"
LONG_TEXT = " ".join(["Python PyTorch Docker Git experience building machine learning services"] * 40)


class Workdir(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write(self, name, text):
        p = self.dir / name
        p.write_text(text, encoding="utf-8")
        return p


class PdfReadingTests(Workdir):
    def _pdf(self, pages, links=()):
        """pages: danh sách trang; mỗi phần tử là chuỗi (trang có chữ) hoặc bytes PNG (trang chỉ có ảnh)."""
        import pymupdf
        pdf = pymupdf.open()
        for content in pages:
            page = pdf.new_page()
            if isinstance(content, bytes):
                page.insert_image(pymupdf.Rect(0, 0, 595, 842), stream=content)
            else:
                words, y = content.split(), 60
                for i in range(0, len(words), 12):
                    page.insert_text((40, y), " ".join(words[i:i + 12]), fontsize=9)
                    y += 13
        for uri in links:
            pdf[0].insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(40, 20, 200, 40), "uri": uri})
        path = self.dir / f"t{len(list(self.dir.iterdir()))}.pdf"
        pdf.save(str(path))
        return path

    @staticmethod
    def _png_page():
        import pymupdf
        src = pymupdf.open()
        src.new_page().insert_text((72, 100), "x")
        return src[0].get_pixmap(dpi=50).tobytes("png")

    def test_icon_glyphs_from_cv_templates_are_removed(self):
        cleaned = io_utils._clean_pdf_text("\uf095 0901 234 567\n\u2709 a@b.com \U0001f4cd Ha Noi\nPython")
        self.assertNotRegex(cleaned, "[\uf000-\uf8ff\u2709\U0001f4cd]")
        self.assertIn("0901 234 567", cleaned)
        self.assertIn("a@b.com", cleaned)

    def test_word_count_ignores_digits_and_symbols(self):
        self.assertEqual(io_utils.word_count("Python 2024 -- 3.5 !!! machine learning"), 3)
        self.assertEqual(io_utils.word_count("Tiếng Việt có dấu"), 4)

    def test_hyperlink_targets_are_appended_so_truncated_urls_are_recovered(self):
        path = self._pdf([LONG_TEXT], links=["https://github.com/someone/a-very-long-repository-name", "mailto:me@example.com"])
        text = io_utils.read_text(path)
        self.assertIn("github.com/someone/a-very-long-repository-name", text)
        self.assertIn("Email: me@example.com", text)

    def test_text_pdf_with_enough_words_never_triggers_ocr(self):
        path = self._pdf([LONG_TEXT, "Chu thich ngan"])
        with mock.patch.object(io_utils, "_ocr_tesseract") as tess, mock.patch.object(io_utils, "_ocr_rapid") as rapid:
            doc = io_utils.read_document(path)
        tess.assert_not_called()
        rapid.assert_not_called()
        self.assertEqual(doc.source, "pdf")
        self.assertFalse(doc.from_ocr)

    def test_hybrid_pdf_ocrs_only_the_image_pages_and_keeps_the_real_text(self):
        short = " ".join(["Python PyTorch Git"] * 25)                      # ~75 từ: đủ chữ cho trang 1 nhưng cả file < 250 từ
        path = self._pdf([short, self._png_page()])
        with mock.patch.object(io_utils, "_ocr_tesseract", return_value="Chung chi TOEIC 850 tu trang anh") as tess:
            doc = io_utils.read_document(path)
        self.assertEqual(len(tess.call_args[0][0]), 1)                      # chỉ trang ảnh được OCR, không phải cả file
        self.assertEqual(doc.source, "pdf+ocr:tesseract")
        self.assertTrue(doc.from_ocr)
        self.assertIn("TOEIC 850", doc.text)
        self.assertIn("PyTorch", doc.text)
        self.assertTrue(any("OCR" in w for w in doc.warnings))

    def test_merge_text_does_not_duplicate_lines(self):
        merged = io_utils._merge_text("Skills\nPython\nGit", "python\nDocker\nSkills")
        self.assertEqual(merged.splitlines().count("Skills"), 1)
        self.assertIn("Docker", merged)
        self.assertEqual(sum(1 for line in merged.splitlines() if line.lower() == "python"), 1)

    def test_unreadable_pdf_gives_a_clear_error_not_an_empty_cv(self):
        path = self._pdf([self._png_page()])
        with mock.patch.object(io_utils, "_ocr_tesseract", side_effect=ImportError), \
                mock.patch.object(io_utils, "_ocr_rapid", side_effect=ImportError):
            with self.assertRaises(ValueError):
                io_utils.read_document(path)


class FileSafetyTests(Workdir):
    def test_pdf_file_is_closed_after_reading_so_it_can_be_deleted(self):
        path = PdfReadingTests._pdf(self, [LONG_TEXT])
        io_utils.read_document(path)
        path.unlink()                                          # Windows từ chối xóa file còn đang mở
        self.assertFalse(path.exists())

    def test_zip_bomb_docx_is_refused_without_loading_it(self):
        import zipfile
        path = self.dir / "bomb.docx"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("word/document.xml", b"\0" * (io_utils.MAX_DOCX_UNZIPPED_MB + 5) * 1024 * 1024)
        self.assertLess(path.stat().st_size, 1024 * 1024)      # nén chỉ còn vài trăm KB
        with self.assertRaisesRegex(ValueError, "giải nén ra quá lớn"):
            io_utils.read_document(path)

    def test_truncated_pdf_and_binary_text_files_are_errors_not_empty_cvs(self):
        good = (SAMPLES / "cvs_pdf" / "ai_cv1.pdf").read_bytes()
        (self.dir / "cut.pdf").write_bytes(good[: len(good) // 2])
        (self.dir / "bin.txt").write_bytes(b"\x00\x01\x02" * 2000)
        for name, message in (("cut.pdf", "không có trang nào|không mở được PDF"), ("bin.txt", "không phải file văn bản")):
            with self.assertRaisesRegex(ValueError, message):
                io_utils.read_document(self.dir / name)
        self.assertEqual(io_utils.read_document(self.write("ok.txt", "Python và PyTorch")).text, "Python và PyTorch")      # văn bản thường vẫn đọc bình thường

    def test_corrupt_docx_gives_a_clear_error(self):
        (self.dir / "x.docx").write_bytes(b"not a zip at all")
        with self.assertRaisesRegex(ValueError, "không mở được DOCX"):
            io_utils.read_document(self.dir / "x.docx")

    def test_recursive_listing_skips_hidden_and_system_folders_and_has_a_cap(self):
        from cv_agent.pipeline import list_cv_files
        for sub in ("a", ".git", "node_modules", "b/c"):
            (self.dir / sub).mkdir(parents=True)
            (self.dir / sub / "cv.txt").write_text("x")
        (self.dir / "top.pdf").write_bytes(b"x")
        names = sorted(str(p.relative_to(self.dir)).replace("\\", "/") for p in list_cv_files(self.dir, recursive=True))
        self.assertEqual(names, ["a/cv.txt", "b/c/cv.txt", "top.pdf"])
        self.assertEqual(len(list_cv_files(self.dir, recursive=False)), 1)
        with self.assertRaisesRegex(ValueError, "hơn 2 file"):
            list_cv_files(self.dir, recursive=True, limit=2)


# `_pdf` dùng ở nhiều lớp test: gắn vào Workdir để tái sử dụng
Workdir._pdf = PdfReadingTests._pdf


class NameFromFilenameTests(unittest.TestCase):
    def test_camel_case_and_separators_in_filename(self):
        for filename, expected in (("DangNguyenVanAnh_CV.pdf", "Dang Nguyen Van Anh"), ("CV_NguyenHoangNam_AI.pdf", "Nguyen Hoang Nam"),
                                   ("Tran-Thi-Bich-2024.pdf", "Tran Thi Bich")):
            name = find_name("", filename)
            self.assertEqual(name.value, expected, filename)
            self.assertEqual(name.source, "file")
            self.assertFalse(name.confident)                              # lấy từ tên file: phải để HR xác nhận

    def test_generic_filename_gives_no_name(self):
        self.assertEqual(find_name("", "resume.pdf").value, "")

    def test_text_name_beats_filename(self):
        name = find_name("CURRICULUM VITAE\nAI ENGINEER\nLe Minh Chau\nEmail: x@y.com", "cv.pdf")
        self.assertEqual((name.value, name.source, name.confident), ("Le Minh Chau", "cv", True))


class JdAndScoringTests(unittest.TestCase):
    def test_years_requirement_stated_twice_becomes_one_condition(self):
        jd = ("Requirements:\n- 2+ years of experience in full-stack development\n- Years of experience: 2+ YoE\n"
              "- Strong Python skills\n- Bachelor's degree in Computer Science\n")
        years = [h for h in build_rubric(jd).hard_requirements if h.type == "experience_years"]
        self.assertEqual(len(years), 1)
        self.assertIn("full-stack", years[0].source_quote)                 # giữ câu nêu rõ lĩnh vực, bỏ câu chung chung

    def test_hard_requirement_ids_stay_contiguous_after_dedupe(self):
        jd = "Yêu cầu:\n- Có ít nhất 3 năm kinh nghiệm\n- Tối thiểu 3 năm kinh nghiệm\n- Tốt nghiệp đại học CNTT\n- Python\n"
        hard = build_rubric(jd).hard_requirements
        self.assertEqual([h.id for h in hard], [f"h{i}" for i in range(1, len(hard) + 1)])

    def test_checklist_shows_years_once_as_condition_not_again_as_skill(self):
        jd = "Yêu cầu:\n- Có ít nhất 2 năm kinh nghiệm\n- Biết Python\n"
        rubric = build_rubric(jd)
        out = score_cv_baseline(rubric, "Nguyen A\nEXPERIENCE\nEngineer - X (2021 - 2024)\n- Python services\nSKILLS\nPython\n")
        items = build_checklist(rubric, out["detail"])
        year_items = [i for i in items if "năm kinh nghiệm" in i["label"]]
        self.assertEqual([i["kind"] for i in year_items], ["hard"])

    def test_toeic_certificate_counts_as_evidence_for_english_requirement(self):
        rubric = build_rubric("Yêu cầu:\n- Giao tiếp tiếng Anh tốt\n- Biết Python\n")
        cv = "Nguyen A\nSKILLS\nPython\nEXPERIENCE\nEngineer - X (2021 - 2024)\n- Python services\nCERTIFICATES\nTOEIC 850\n"
        out = score_cv_baseline(rubric, cv)
        english = next(c for c in rubric.criteria if "anh" in c.source_quote.lower())
        score = next(s for s in out["detail"].criterion_scores if s.criterion_id == english.id)
        self.assertGreaterEqual(score.score, 3)
        self.assertIn("TOEIC", " ".join(score.evidence))

    def test_ocr_text_never_auto_rejects_on_a_hard_requirement(self):
        rubric = build_rubric("Yêu cầu:\n- Chứng chỉ TOEIC 700 trở lên\n- Biết Python\n")
        cv = "Nguyen A\nSKILLS\nPython\nEXPERIENCE\nEngineer - X (2021 - 2024)\n- Python services\nTOEIC 550\n"
        typed = score_cv_baseline(rubric, cv, uncertain=False)["summary"]
        scanned = score_cv_baseline(rubric, cv, uncertain=True)["summary"]
        self.assertTrue(typed["failed_hard"])                                # CV gõ chữ: 550 < 700 là trượt thật
        self.assertEqual(scanned["failed_hard"], [])                         # OCR có thể đọc nhầm 850 thành 550: đưa cho HR kiểm tra
        self.assertTrue(scanned["unclear_hard"])


class SameContentSameResultTests(unittest.TestCase):
    """Cùng một nội dung viết khác kiểu (dấu tiếng Việt rời, NBSP, xuống dòng kiểu cũ) phải cho cùng kết quả.
    Trước đây NFD đổi 7/21 kết quả, NBSP đổi 8/21: bản copy từ Word/Mac/web thường mang các ký tự này."""

    @staticmethod
    def _pairs():
        """(JD, CV) đúng cặp: mỗi CV chấm theo JD của bộ dữ liệu chứa nó (bộ data_heldout có 3 JD khác nhau)."""
        out = []
        for base in (SAMPLES, ROOT / "data_heldout"):
            jds = {p.stem: p.read_text(encoding="utf-8-sig") for p in (base / "jds").glob("*.txt")}
            for cv in sorted((base / "cvs").glob("*.txt")):
                jd = next((t for stem, t in jds.items() if cv.name.startswith(stem)), next(iter(jds.values())))
                out.append((jd, cv.read_text(encoding="utf-8-sig")))
        return out

    @staticmethod
    def key(rubric, cv):
        from cv_agent.facts import extract_facts
        s = score_cv_baseline(rubric, cv)["summary"]
        f = extract_facts(cv, "x.txt")
        return s["overall_score"], s["required_score"], tuple(s["failed_hard"]), tuple(s["unclear_hard"]), f["candidate_name"], f["email"]

    def check(self, transform):
        sig = lambda rb: ([(h.type, h.source_quote) for h in rb.hard_requirements], [(c.importance, c.source_quote) for c in rb.criteria])
        checked_jds: dict = {}                                                  # mỗi JD chỉ dựng rubric một lần
        for jd, cv in self._pairs():
            if jd not in checked_jds:
                rubric = checked_jds[jd] = build_rubric(jd)
                self.assertEqual(sig(build_rubric(transform(jd))), sig(rubric))      # JD dán từ web/Word cũng mang các ký tự này
            rubric = checked_jds[jd]
            self.assertEqual(self.key(rubric, transform(cv)), self.key(rubric, cv))

    def test_decomposed_vietnamese_diacritics(self):
        import unicodedata
        self.check(lambda t: unicodedata.normalize("NFD", t))

    def test_non_breaking_and_odd_spaces(self):
        self.check(lambda t: t.replace(" ", "\u00a0"))
        self.check(lambda t: t.replace(" ", "\u2009"))
        self.check(lambda t: t.replace(" ", "\u202f").replace("\t", "\u3000"))

    def test_old_mac_and_windows_line_endings(self):
        self.check(lambda t: t.replace("\n", "\r"))
        self.check(lambda t: t.replace("\n", "\r\n"))

    def test_clean_text_leaves_normal_text_alone(self):
        from cv_agent.textutil import clean_text
        text = "Nguyễn Văn A\n- Python (2020 - 2024)\tGit\n"
        self.assertEqual(clean_text(text), text)
        self.assertEqual(clean_text("a\u200bb\ufeffc\x00d"), "abcd")


class JdAndLanguageEdgeCaseTests(unittest.TestCase):
    def test_no_experience_phrase_does_not_drop_the_skills_on_the_same_line(self):
        rubric = build_rubric("Kỹ sư AI\nYêu cầu:\n- Không yêu cầu kinh nghiệm, biết Python và PyTorch\n- Biết Git\n")
        quotes = [c.source_quote for c in rubric.criteria]
        self.assertTrue(any("Python" in q for q in quotes), quotes)
        self.assertEqual(len(quotes), 2)

    def test_fresher_welcome_keeps_the_rest_of_the_requirement(self):
        rubric = build_rubric("AI Intern\nRequirements:\n- Fresher welcome, knowledge of Python\n- Familiar with Git\n")
        self.assertTrue(any("Python" in c.source_quote for c in rubric.criteria))

    def test_pure_no_experience_line_is_still_ignored(self):
        rubric = build_rubric("AI Intern\nRequirements:\n- Không yêu cầu kinh nghiệm\n- Biết Python\n")
        self.assertEqual([c.source_quote for c in rubric.criteria], ["Biết Python"])

    def test_no_experience_with_degree_keeps_the_degree_requirement(self):
        rubric = build_rubric("Kế toán\nYêu cầu:\n- Tốt nghiệp đại học chuyên ngành kế toán, không yêu cầu kinh nghiệm\n- Thành thạo Excel\n")
        self.assertEqual([h.type for h in rubric.hard_requirements], ["education"])

    def test_toeic_listening_reading_are_summed(self):
        from cv_agent.lang_check import best_certificate
        self.assertEqual(best_certificate("TOEIC Listening 450 Reading 400")[1], 850)
        self.assertEqual(best_certificate("TOEIC: 450 (L) + 400 (R) = 850")[0], "TOEIC 850")
        self.assertEqual(best_certificate("TOEIC 850/990")[1], 850)
        self.assertEqual(best_certificate("TOEIC (2023): 800")[1], 800)

    def test_garbled_language_requirement_does_not_crash(self):
        from cv_agent.lang_check import parse_required
        for text in ("TOEIC >, ", "IELTS ≥ .", "TOEFL > .", "TOEIC ≥"):
            self.assertIsNone(parse_required(text))

    def test_single_letter_name_does_not_erase_the_letter_a_everywhere(self):
        from cv_agent.anonymize import anonymize
        out = anonymize("Name: A\nA team of engineers built a model.\nSKILLS\nPython\n")
        self.assertIn("A team of engineers built a model", out)

    def test_bad_as_of_date_falls_back_to_today(self):
        from cv_agent.cv_parse import as_of_date
        with mock.patch.dict(os.environ, {"CV_AGENT_AS_OF": "không-phải-ngày"}):
            y, m = as_of_date()
        self.assertTrue(2020 <= y <= 2100 and 1 <= m <= 12)
        with mock.patch.dict(os.environ, {"CV_AGENT_AS_OF": "2026-13"}):
            self.assertNotEqual(as_of_date(), (2026, 13))


class GluedTextTests(unittest.TestCase):
    """Chữ dính liền do OCR/PDF mất khoảng trắng: từ khoá của JD vẫn phải tìm thấy được bên trong."""

    def test_keywords_are_found_inside_a_glued_run(self):
        rubric = build_rubric("Yêu cầu:\n- Kiến thức software engineering\n")
        cv = "Nguyen A\nSUMMARY\nSeeking an internship strengtheningsoftwareengineeringskills in practice\nSKILLS\nPython\n"
        glued = score_cv_baseline(rubric, cv)["detail"].criterion_scores[0].score
        clean = score_cv_baseline(rubric, cv.replace("strengtheningsoftwareengineeringskills", "strengthening software engineering skills"))["detail"].criterion_scores[0].score
        self.assertGreaterEqual(glued, 1)
        self.assertLessEqual(glued, clean)                         # dính liền không được tốt hơn viết đúng

    def test_short_keywords_do_not_match_inside_long_words(self):
        rubric = build_rubric("Yêu cầu:\n- Biết SQL\n")
        out = score_cv_baseline(rubric, "Nguyen A\nSKILLS\nxxxsqlxxxxxxxxxxxxxxxxx\n")
        self.assertEqual(out["detail"].criterion_scores[0].score, 0)

    def test_ocr_education_with_glued_university_is_not_flagged_as_lower_level(self):
        from cv_agent.cv_parse import check_education, split_cv
        lines = split_cv("EDUCATION\nIndustrial Universityof Ho Chi Minhcity\nMajor: Software Engineering\n2019 - 2023\n")
        req = "Tốt nghiệp đại học chuyên ngành Công nghệ thông tin"
        self.assertEqual(check_education(req, lines, loose=True).status, "met")
        self.assertNotIn("Cấp bậc thấp hơn", check_education(req, lines, loose=True).note)


class StudentEducationTests(unittest.TestCase):
    def test_future_or_ongoing_degree_is_not_a_finished_one(self):
        from cv_agent.cv_parse import education_in_progress, split_cv
        for edu in ("B.Sc. Computer Science (2021 - Present)", "ĐH Bách Khoa (2022 - 2027)", "University of X, expected graduation 2027",
                    "Đại học Y - sinh viên năm cuối"):
            lines = split_cv(f"EDUCATION\n{edu}\n")
            self.assertTrue(education_in_progress([l["text"] for l in lines if l["section"] == "edu"], lines), edu)

    def test_finished_degree_wins_over_a_current_course(self):
        from cv_agent.cv_parse import education_in_progress, split_cv
        lines = split_cv("EDUCATION\nB.Sc. Computer Science (2016 - 2020)\nMaster of AI (2024 - Present)\n")
        self.assertFalse(education_in_progress([l["text"] for l in lines if l["section"] == "edu"], lines))


class LexiconAliasTests(unittest.TestCase):
    """CV hay viết tắt / viết khác với JD: vẫn phải khớp, và cụm không liên quan thì không được khớp nhầm."""

    @staticmethod
    def score(requirement: str, cv_line: str) -> int:
        rubric = build_rubric(f"Yêu cầu:\n- {requirement}\n")
        cv = f"Nguyen A\nSKILLS\n{cv_line}\nEXPERIENCE\nEngineer - X (2021 - 2024)\n- {cv_line}\n- Wrote documentation for the team\n"
        out = score_cv_baseline(rubric, cv)
        return out["detail"].criterion_scores[0].score

    def test_common_abbreviations_match_the_full_name(self):
        for requirement, cv_line in (("Kinh nghiệm với Kubernetes", "Deployed services on k8s"),
                                     ("Kinh nghiệm với PostgreSQL", "Designed schemas in Postgres"),
                                     ("Thành thạo Microsoft Excel", "Built reports in MS Excel"),
                                     ("Kinh nghiệm scikit-learn", "Trained models with sklearn"),
                                     ("Kinh nghiệm với JavaScript", "Built dashboards in JS and TS")):
            self.assertGreaterEqual(self.score(requirement, cv_line), 2, (requirement, cv_line))

    def test_unrelated_skill_is_not_matched(self):
        self.assertLessEqual(self.score("Kinh nghiệm với Kubernetes", "Designed schemas in Postgres"), 1)
        self.assertLessEqual(self.score("Thành thạo Microsoft Excel", "Built web pages in JS"), 1)

    def test_llm_toolchain_implies_llm_skill(self):
        self.assertGreaterEqual(self.score("Kinh nghiệm làm việc với LLM", "Built chatbots with LangChain and OpenAI API"), 2)


class UserLexiconTests(Workdir):
    """lexicon_user.json do người dùng viết tay: file hỏng không được làm sập cả chương trình."""

    def load(self, content):
        import contextlib
        import io as _io
        from cv_agent import lexicon
        path = self.write("lexicon_user.json", content)
        before = (len(lexicon.IMPLIES), len(lexicon.FIELD_GROUPS), len(lexicon.TECH_ALIASES))
        err = _io.StringIO()
        with mock.patch.dict(os.environ, {"CV_AGENT_LEXICON": str(path)}), contextlib.redirect_stderr(err):
            lexicon._load_user()
        return before, (len(lexicon.IMPLIES), len(lexicon.FIELD_GROUPS), len(lexicon.TECH_ALIASES)), err.getvalue()

    def test_broken_files_are_skipped_with_a_warning(self):
        for content in ("{khong phai json", '{"implies": [1, 2]}', '{"tech_aliases": {"(": "x"}}', '{"field_groups": 5}', "[]", ""):
            before, after, warning = self.load(content)
            self.assertEqual(before, after, content)
            self.assertIn("Bỏ qua từ điển người dùng", warning, content)

    def test_valid_file_is_loaded_and_isolated_for_the_test(self):
        from cv_agent import lexicon
        snapshot = (dict(lexicon.IMPLIES), list(lexicon.FIELD_GROUPS), list(lexicon.TECH_ALIASES), set(lexicon.STOP), list(lexicon.STOP_PHRASES))
        try:
            before, after, warning = self.load('{"implies": {"Zalo Ads": "quảng cáo ads"}, "field_groups": [["điều dưỡng", "y tá"]]}')
            self.assertEqual(warning, "")
            self.assertEqual((after[0] - before[0], after[1] - before[1]), (1, 1))
            self.assertEqual(lexicon.IMPLIES["zalo ads"], "quảng cáo ads")
        finally:                                                         # trả từ điển về như cũ để không ảnh hưởng các test khác
            lexicon.IMPLIES.clear()
            lexicon.IMPLIES.update(snapshot[0])
            lexicon.FIELD_GROUPS[:] = snapshot[1]
            lexicon.TECH_ALIASES[:] = snapshot[2]
            lexicon.STOP.clear()
            lexicon.STOP.update(snapshot[3])
            lexicon.STOP_PHRASES[:] = snapshot[4]


class CachedAnalysisTests(unittest.TestCase):
    """Các bước được nhớ lại để chạy nhanh hơn không được làm đổi kết quả hay cho phép sửa nhầm dữ liệu dùng chung."""

    def test_query_units_are_immutable_and_cached(self):
        from cv_agent.nlp import query_units
        a = query_units("Thành thạo Python và PyTorch", False)
        self.assertIs(a, query_units("Thành thạo Python và PyTorch", False))
        self.assertIsInstance(a, tuple)

    def test_find_name_result_cannot_be_modified_by_a_caller(self):
        import dataclasses
        name = find_name("Nguyễn Văn An\nEngineer\n")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            name.value = "Người khác"
        self.assertEqual(find_name("Nguyễn Văn An\nEngineer\n").value, "Nguyễn Văn An")

    def test_second_cv_with_the_same_jd_gets_the_same_score_as_alone(self):
        rubric = build_rubric((SAMPLES / "jds" / "ai01.txt").read_text(encoding="utf-8-sig"))
        cvs = [p.read_text(encoding="utf-8-sig") for p in sorted((SAMPLES / "cvs").glob("*.txt"))]
        together = [score_cv_baseline(rubric, cv)["summary"]["overall_score"] for cv in cvs]
        again = [score_cv_baseline(rubric, cv)["summary"]["overall_score"] for cv in reversed(cvs)][::-1]
        self.assertEqual(together, again)                                 # thứ tự chấm không ảnh hưởng (bộ nhớ đệm không rò rỉ giữa các CV)


class NearDuplicateTests(Workdir):
    def test_slightly_edited_resubmission_is_flagged_but_different_people_are_not(self):
        texts = [p.read_text(encoding="utf-8-sig") for p in sorted((SAMPLES / "cvs").glob("*.txt"))]
        original = texts[0]
        edited = original.replace("Python", "Python 3", 1) + "\nSở thích: đọc sách\n"
        items = [(f"c{i}.txt", self.write(f"c{i}.txt", t)) for i, t in enumerate(texts)]
        items.append(("c0_v2.txt", self.write("c0_v2.txt", edited)))
        rows = screen(build_rubric((SAMPLES / "jds" / "ai01.txt").read_text(encoding="utf-8-sig")), items, workers=1)
        flagged = {r["file"]: r["review_reason"] for r in rows if "giống" in r["review_reason"]}
        self.assertEqual(list(flagged), ["c0_v2.txt"])                       # chỉ bản nộp lại, không phải 9 CV khác nhau
        self.assertIn("c0.txt", flagged["c0_v2.txt"])

    def test_similarity_search_is_stable_and_fast_on_thousands(self):
        import random
        import time
        from cv_agent.dedupe import find_near_duplicates
        rnd = random.Random(7)
        vocab = [f"w{i}" for i in range(4000)]
        docs = [" ".join(rnd.choice(vocab) for _ in range(300)) for _ in range(1200)]
        fingerprints = list(enumerate(docs)) + [(1200 + i, d.replace("w1 ", "x1 ", 3)) for i, d in enumerate(docs[:200])]
        start = time.time()
        found = find_near_duplicates(fingerprints)
        self.assertLess(time.time() - start, 15)
        self.assertEqual({later: earlier for later, (earlier, _) in found.items()}, {1200 + i: i for i in range(200)})

    def test_short_texts_and_exact_copies_are_left_to_the_exact_check(self):
        from cv_agent.dedupe import find_near_duplicates
        self.assertEqual(find_near_duplicates([(0, "a b c"), (1, "a b c")]), {})


class RejudgeTests(Workdir):
    def screen_samples(self, **th):
        rubric = build_rubric((SAMPLES / "jds" / "ai01.txt").read_text(encoding="utf-8"))
        items = [(p.name, p) for p in sorted((SAMPLES / "cvs").glob("*.txt"))]
        return rubric, items, screen(rubric, items, workers=2, **th)

    def test_rejudge_equals_a_fresh_screen_at_the_new_thresholds(self):
        rubric, items, rows = self.screen_samples(fit=70, maybe=50, reject=30)
        self.assertTrue(can_rejudge(rows))
        rejudge(rubric, rows, 85, 65, 45)
        fresh = screen(rubric, items, workers=2, fit=85, maybe=65, reject=45)
        key = lambda r: (r["file"], r["rank"], r["verdict"], r["suggestion"], r["verdict_reason"])
        self.assertEqual([key(r) for r in rows], [key(r) for r in fresh])

    def test_rejudge_changes_verdicts_but_not_scores_or_hr_decisions(self):
        rubric, items, rows = self.screen_samples()
        scores = {r["file"]: r["overall_score"] for r in rows}
        rows[0]["hr_decision"], rows[0]["hr_note"] = "Giữ lại", "gọi lại"
        marked = rows[0]["file"]
        before = [r["verdict"] for r in rows]
        rejudge(rubric, rows, 95, 90, 85)                                    # rất chặt: nhiều người tụt nhóm
        self.assertNotEqual(before, [r["verdict"] for r in rows])
        self.assertEqual(scores, {r["file"]: r["overall_score"] for r in rows})
        kept = next(r for r in rows if r["file"] == marked)
        self.assertEqual((kept["hr_decision"], kept["hr_note"]), ("Giữ lại", "gọi lại"))
        self.assertEqual([r["rank"] for r in rows], list(range(1, len(rows) + 1)))

    def test_rejudge_leaves_failed_hard_requirements_rejected_at_any_threshold(self):
        rubric, _, rows = self.screen_samples()
        failed = [r for r in rows if r["verdict_inputs"]["failed_hard"]]
        self.assertTrue(failed)
        rejudge(rubric, rows, 30, 20, 0)                                     # rất rộng
        for r in failed:
            self.assertEqual(r["verdict"], REJECT)
            self.assertIn("Trượt điều kiện", r["verdict_reason"])

    def test_error_rows_are_skipped_and_old_rows_are_detected(self):
        rows = [{"verdict": "LỖI", "file": "x.pdf"}, {"verdict": RESERVE, "file": "y.txt"}]
        self.assertFalse(can_rejudge(rows))                                  # dòng không lỗi mà thiếu verdict_inputs = lần chạy cũ
        self.assertTrue(can_rejudge([{"verdict": "LỖI", "file": "x.pdf"}]))


class CancelAndStorageTests(Workdir):
    def test_screen_stops_when_cancelled_and_does_not_run_the_rest(self):
        rubric = build_rubric("Yêu cầu:\n- Biết Python\n")
        cv = "Nguyễn Văn A\nSKILLS\nPython\nEXPERIENCE\nDev - X (2020 - 2024)\n- Python " + "services " * 30
        items = [(f"c{i}.txt", self.write(f"c{i}.txt", cv + str(i))) for i in range(8)]
        cancel, seen = threading.Event(), []

        def progress(done, total, name):
            seen.append(name)
            cancel.set()

        with self.assertRaises(Cancelled):
            screen(rubric, items, workers=1, on_progress=progress, cancel=cancel)
        self.assertLess(len(seen), len(items))

    def test_save_is_atomic_and_meta_can_be_updated(self):
        rubric = build_rubric("Yêu cầu:\n- Biết Python\n")
        folder = storage.save_run([], rubric, "core", {"fit": 70}, base=self.dir)
        meta = storage.update_meta(folder, fit=80, maybe=60)
        self.assertEqual((meta["fit"], meta["maybe"], meta["n_cv"]), (80, 60, 0))
        self.assertEqual(json.loads((folder / "meta.json").read_text(encoding="utf-8"))["fit"], 80)
        self.assertEqual([p.name for p in folder.iterdir() if p.name.endswith(".tmp")], [])      # không để file tạm


if __name__ == "__main__":
    unittest.main()
