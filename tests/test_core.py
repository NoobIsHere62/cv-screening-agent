"""Chạy:  python -m unittest discover -s tests -v   (không cần API key, không cần pytest)"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["CV_AGENT_AS_OF"] = "2026-10"

from cv_agent import io_utils
from cv_agent.anonymize import anonymize
from cv_agent.cv_parse import normalize_dates
from cv_agent.jd_filter import core_jd_text
from cv_agent.jd_rules import build_rubric_rules, parse_min_years
from cv_agent.lang_check import check_language, parse_required
from cv_agent.verdict import FIT, MAYBE, REJECT, RESERVE, verdict

AI_JD = """Key Responsibilities:

Design and implement machine learning models.
Monitor deployed AI systems.

Required skills/Experience:

Strong programming skills in Python (NumPy, Pandas, Scikit-learn).
Hands-on experience with deep learning frameworks (TensorFlow, PyTorch, Keras).
Experience with version control (Git).
Bachelor's degree in Computer Science, Data Science or a related field.
TOEIC score: >=650 or an equivalent level of English proficiency.
Nice to have:

Exposure to cloud platforms (AWS, GCP, Azure).

Years of experiences: >2 YoE
"""


class DateTests(unittest.TestCase):
    def test_words_starting_with_month_abbreviation_are_not_dates(self):
        for s in ("Marketing 2016 - 2020", "Junior 2021", "Decision 2020"):
            self.assertEqual(normalize_dates(s), s)

    def test_real_months(self):
        self.assertEqual(normalize_dates("Jan 2021 - Dec 2022"), "01/2021 - 12/2022")
        self.assertEqual(normalize_dates("Sept 2020"), "09/2020")


class YearsTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_min_years("Có ít nhất 2 năm kinh nghiệm"), 2)
        self.assertEqual(parse_min_years("Years of experiences: >2 YoE"), 2)
        self.assertEqual(parse_min_years("Years of experiences: No"), 0.0)
        self.assertEqual(parse_min_years("Không yêu cầu kinh nghiệm"), 0.0)
        self.assertAlmostEqual(parse_min_years("6 tháng kinh nghiệm"), 0.5)
        self.assertIsNone(parse_min_years("Thành thạo Excel"))


class LanguageTests(unittest.TestCase):
    REQ = "TOEIC score: ≥650 or an equivalent level of English proficiency"

    def test_required(self):
        self.assertEqual(parse_required(self.REQ), ("toeic", 650.0))

    def test_met_not_met_unclear(self):
        self.assertEqual(check_language(self.REQ, "English – TOEIC 790 (01/2026)").status, "met")
        self.assertEqual(check_language(self.REQ, "IELTS 6.5 (2023)").status, "met")
        self.assertEqual(check_language(self.REQ, "TOEIC 500").status, "not_met")
        self.assertEqual(check_language(self.REQ, "Tiếng Anh giao tiếp tốt").status, "unclear")

    def test_year_is_not_a_score(self):
        self.assertEqual(check_language(self.REQ, "TOEIC (2024)").status, "unclear")


class JdFilterTests(unittest.TestCase):
    def setUp(self):
        self.r = build_rubric_rules(AI_JD)

    def test_required_section_is_not_dropped(self):
        required = [c.source_quote for c in self.r.criteria if c.importance == "required"]
        self.assertTrue(any("Python" in q for q in required))
        self.assertTrue(any("version control" in q for q in required))

    def test_hard_requirements(self):
        self.assertEqual(sorted(h.type for h in self.r.hard_requirements), ["education", "experience_years", "language"])

    def test_years_line_under_nice_to_have_is_still_required(self):
        years = [h for h in self.r.hard_requirements if h.type == "experience_years"]
        self.assertEqual(len(years), 1)

    def test_core_text_round_trip(self):
        again = build_rubric_rules(core_jd_text(self.r))
        self.assertEqual(sorted(c.source_quote for c in self.r.criteria), sorted(c.source_quote for c in again.criteria))
        self.assertEqual(len(self.r.hard_requirements), len(again.hard_requirements))

    def test_responsibilities_and_discrimination_are_dropped(self):
        jd = "Nhân viên kinh doanh\nYêu cầu:\n- Nam/nữ, độ tuổi từ 23 đến 35\n- Thành thạo Excel\n- Kỹ năng đàm phán tốt\n"
        r = build_rubric_rules(jd)
        text = " ".join(c.source_quote for c in r.criteria)
        self.assertNotIn("tuổi", text)
        self.assertNotIn("đàm phán", text)
        self.assertEqual(len(r.jd_analysis.ambiguities), 2)


class VerdictTests(unittest.TestCase):
    def s(self, score, decision="Cân nhắc", failed=(), core=1.0, unclear=(), zero=(), missing=()):
        return {"overall_score": score, "decision": decision, "failed_hard": list(failed), "core_ratio": core,
                "unclear_hard": list(unclear), "required_zero": list(zero), "missing_criteria": list(missing)}

    def test_tiers(self):
        self.assertEqual(verdict(self.s(80, "Phù hợp")), FIT)
        self.assertEqual(verdict(self.s(60)), MAYBE)
        self.assertEqual(verdict(self.s(40)), RESERVE)
        self.assertEqual(verdict(self.s(29)), REJECT)

    def test_failed_hard_requirement_is_rejected_even_with_high_score(self):
        self.assertEqual(verdict(self.s(90, "Phù hợp", failed=["h1"])), REJECT)

    def test_fit_needs_full_verification(self):
        self.assertEqual(verdict(self.s(85, unclear=["h2"])), MAYBE)          # đủ điểm nhưng còn điều kiện chưa rõ
        self.assertEqual(verdict(self.s(85, zero=["c1"])), MAYBE)

    def test_thresholds_are_respected(self):
        self.assertEqual(verdict(self.s(60), fit=55), FIT)                    # kéo ngưỡng "phù hợp" xuống thì kết luận đổi theo
        self.assertEqual(verdict(self.s(60), maybe=65, reject=10), RESERVE)

    def test_threshold_validation(self):
        from cv_agent.verdict import check_thresholds
        check_thresholds(70, 50, 30)
        with self.assertRaises(ValueError):
            check_thresholds(50, 70, 30)
        with self.assertRaises(ValueError):
            check_thresholds(70, 50, 50)

    def test_low_core_skills_cap_at_reserve(self):
        self.assertEqual(verdict(self.s(80, "Phù hợp", core=0.4)), RESERVE)


class AnonymizeTests(unittest.TestCase):
    def test_contact_info_removed(self):
        out = anonymize("Nguyễn Văn A\nEmail: a@b.com | 0903 456 789\nGiới tính: Nam\nPython 2019 - 2022")
        for leaked in ("a@b.com", "0903", "Nam", "Nguyễn Văn A"):
            self.assertNotIn(leaked, out)
        self.assertIn("2019 - 2022", out)


class OcrRoutingTests(unittest.TestCase):
    def _scanned_pdf(self, path: Path):
        import pymupdf
        src = pymupdf.open()
        page = src.new_page()
        page.insert_text((72, 100), "Nguyen Van A - AI Engineer - Python PyTorch " * 3)
        png = page.get_pixmap(dpi=100).tobytes("png")
        out = pymupdf.open()
        out.new_page().insert_image(pymupdf.Rect(0, 0, 595, 842), stream=png)    # PDF chỉ có ảnh, không có lớp chữ
        out.save(str(path))

    def test_image_only_pdf_goes_to_ocr(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "scan.pdf"
            self._scanned_pdf(p)
            with mock.patch.object(io_utils, "_ocr_tesseract", return_value="Nguyen Van A\nPython PyTorch"):
                self.assertIn("PyTorch", io_utils.read_text(p))
            with self.assertRaises(ValueError):
                io_utils.read_text(p, ocr=False)

    def test_no_ocr_backend_gives_clear_error(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "scan.pdf"
            self._scanned_pdf(p)
            with mock.patch.object(io_utils, "_ocr_tesseract", side_effect=RuntimeError("no tesseract")), \
                    mock.patch.object(io_utils, "_ocr_rapid", side_effect=ImportError("no rapidocr")), \
                    mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
                with self.assertRaisesRegex(ValueError, "không OCR được"):
                    io_utils.read_text(p)


FRESHER_JD = """Fresher AI Engineer

Yêu cầu:
- Tốt nghiệp đại học chuyên ngành Trí tuệ nhân tạo, Khoa học máy tính hoặc liên quan.
- Không yêu cầu kinh nghiệm, ưu tiên ứng viên có dự án cá nhân hoặc thực tập về AI/ML.
- Lập trình Python tốt (NumPy, Pandas, scikit-learn).
- Biết một trong các framework deep learning: TensorFlow, PyTorch hoặc Keras.
- Biết sử dụng Git.
"""

FRESHER_CV = """Nguyễn Văn A
AI Engineer (Fresher)
Email: a@b.com • github.com/someone

EDUCATION
Nguyen Tat Thanh University – B.Sc. in Artificial Intelligence (2022 - Present)

PROJECTS
Traffic Law RAG Chatbot
- Python, Flask, scikit-learn, BM25; retrieval and validator pipeline.
Image Captioning (ViT + Transformer decoder)
- Python, PyTorch, TensorFlow, Hugging Face; trained on Flickr8k.

EXPERIENCE
AI Engineer Intern – Some Company (06/2025 - 12/2025)
- Built a RAG pipeline for document question answering with Python.

SKILLS
Python, PyTorch, TensorFlow, scikit-learn, Pandas, NumPy
"""

STUFFED_CV = """Trần Thị B
AI Engineer

EDUCATION
Some College – Diploma in Travel Management (2018 - 2021)

EXPERIENCE
Sales Associate – Fashion Store (2021 - 2025)
- Advised customers and counted stock.

SKILLS
Python, PyTorch, TensorFlow, Keras, scikit-learn, Pandas, NumPy, Git, Docker, Flask, deep learning, NLP
"""


class FresherScreeningTests(unittest.TestCase):
    """Góc nhìn nhà tuyển dụng fresher AI: dự án/thực tập có giá trị, nhồi từ khoá thì không."""

    def setUp(self):
        from cv_agent.baseline import score_cv_baseline
        self.rubric = build_rubric_rules(FRESHER_JD)
        self.score = lambda cv: score_cv_baseline(self.rubric, cv)

    def test_ai_major_matches_vietnamese_requirement(self):
        from cv_agent.cv_parse import check_education, split_cv
        graduated = FRESHER_CV.replace("(2022 - Present)", "(2018 - 2022)")
        hc = check_education(self.rubric.hard_requirements[0].source_quote, split_cv(graduated))
        self.assertEqual(hc.status, "met")

    def test_student_still_studying_does_not_count_as_graduated(self):
        """JD đòi "Tốt nghiệp đại học": CV ghi "(2022 - Present)" mới chỉ là đang học, nên cần HR xác nhận chứ không phải "đạt"."""
        from cv_agent.cv_parse import check_education, split_cv
        req = self.rubric.hard_requirements[0].source_quote
        hc = check_education(req, split_cv(FRESHER_CV))
        self.assertEqual(hc.status, "unclear")
        self.assertIn("đang học", hc.note)
        self.assertNotIn("Ngành học không khớp", hc.note)                      # ngành đã khớp; chỉ thiếu bằng chứng tốt nghiệp
        self.assertEqual(check_education("Sinh viên năm cuối chuyên ngành Khoa học máy tính", split_cv(FRESHER_CV)).status, "met")   # JD cho phép sinh viên

    def test_github_link_is_hidden_but_its_kind_is_kept(self):
        out = anonymize("Email: a@b.com • github.com/someone")
        self.assertIn("github", out)
        self.assertNotIn("someone", out)

    def test_good_fresher_is_suitable(self):
        out = self.score(FRESHER_CV.replace("(2022 - Present)", "(2018 - 2022)"))      # đã tốt nghiệp
        self.assertEqual(out["summary"]["failed_hard"], [])
        self.assertEqual(verdict(out["summary"]), FIT)

    def test_good_student_is_still_in_the_suitable_list_but_flagged_for_hr(self):
        out = self.score(FRESHER_CV)                                                    # còn đang học: chưa chắc đã tốt nghiệp
        self.assertEqual(out["summary"]["failed_hard"], [])
        self.assertEqual(out["summary"]["unclear_hard"], ["h1"])
        self.assertEqual(verdict(out["summary"]), MAYBE)

    def test_keyword_stuffing_is_not_suitable(self):
        out = self.score(STUFFED_CV)
        scores = {s.criterion_id: s.score for s in out["detail"].criterion_scores}
        self.assertTrue(all(v <= 1 for k, v in scores.items() if k != "c1"), scores)   # chỉ liệt kê trong kỹ năng thì tối đa 1 điểm
        self.assertIn(verdict(out["summary"]), (REJECT, RESERVE))


class JdFormatTests(unittest.TestCase):
    """Các kiểu viết JD thường gặp: trước đây một số kiểu bị mất cả mục yêu cầu hoặc báo lỗi."""

    def test_english_what_youll_bring_is_requirements(self):
        jd = ("Senior Backend Engineer\nWhat you'll do:\n* Build REST APIs\nWhat you'll bring:\n* 5+ years of experience in backend\n"
              "* Strong proficiency in Python or Go\n* Experience with PostgreSQL and Redis\nNice to have:\n* Kubernetes\nBenefits:\n* Remote\n")
        r = build_rubric_rules(jd)
        required = [c.source_quote for c in r.criteria if c.importance == "required"]
        self.assertTrue(any("Python or Go" in q for q in required), required)
        self.assertEqual([h.type for h in r.hard_requirements], ["experience_years"])
        self.assertFalse(any("Build REST" in c.source_quote for c in r.criteria))          # mô tả công việc không phải yêu cầu

    def test_curly_apostrophe_header(self):
        r = build_rubric_rules("Engineer\nWhat you’ll bring:\n* Strong proficiency in Python\n")
        self.assertTrue(any("Python" in c.source_quote for c in r.criteria))

    def test_unknown_header_is_classified_by_content(self):
        r = build_rubric_rules("Kỹ sư\nBạn sẽ làm gì:\n- Thiết kế bản vẽ\nBạn cần có:\n- Thành thạo AutoCAD\n- Tốt nghiệp đại học cơ khí\n")
        text = " ".join(c.source_quote for c in r.criteria)
        self.assertIn("AutoCAD", text)
        self.assertTrue(any("Mục «Bạn cần có»" in n for n in r.jd_analysis.ambiguities))

    def test_paragraph_jd_is_split_into_clauses(self):
        jd = ("Chúng tôi cần tuyển một nhân viên chăm sóc khách hàng có ít nhất 1 năm kinh nghiệm, sử dụng thành thạo CRM và Excel, "
              "giao tiếp tiếng Anh tốt. Ưu tiên ứng viên từng làm trong ngành thương mại điện tử.")
        r = build_rubric_rules(jd)
        quotes = [c.source_quote for c in r.criteria]
        self.assertTrue(any("CRM" in q for q in quotes), quotes)
        self.assertTrue(any(c.importance == "preferred" for c in r.criteria))

    def test_only_general_conditions(self):
        with self.assertRaisesRegex(ValueError, "bổ sung"):                              # không tiêu đề, không kỹ năng: báo lỗi hướng dẫn được
            build_rubric_rules("Yêu cầu:\n- Tốt nghiệp đại học\n- Có ít nhất 2 năm kinh nghiệm\n")
        r = build_rubric_rules("Kế toán tổng hợp\nYêu cầu:\n- Tốt nghiệp đại học\n")      # có tên vị trí: dùng làm tiêu chí và nói rõ
        self.assertTrue(any("tên vị trí" in n for n in r.jd_analysis.ambiguities))


class GenericYearsTests(unittest.TestCase):
    JD = "Lập trình viên\nYêu cầu:\n- Thành thạo Python\n- Biết Git\n- Có ít nhất 2 năm kinh nghiệm\n"
    DEV = "A B\nEXPERIENCE\nDeveloper – X (2019 - 2024)\n- Python and Git\n"
    OTHER = "A B\nEXPERIENCE\nAccountant – X (2019 - 2024)\n- Tax reports in Excel\n"

    def setUp(self):
        from cv_agent.baseline import score_cv_baseline
        self.rubric = build_rubric_rules(self.JD)
        self.score = lambda cv: score_cv_baseline(self.rubric, cv)

    def test_vietnamese_generic_years_counts_total_experience(self):
        out = self.score(self.DEV)
        self.assertEqual(out["detail"].hard_checks[0].status, "met")

    def test_generic_years_is_a_gate_not_free_points(self):
        self.assertEqual(len(self.rubric.criteria), 2)                      # chỉ Python và Git; số năm không phải tiêu chí cộng điểm
        self.assertEqual(self.score(self.OTHER)["summary"]["overall_score"], 0.0)

    def test_topic_specific_years_is_still_scored(self):
        r = build_rubric_rules("Marketing\nYêu cầu:\n- Có ít nhất 1 năm kinh nghiệm chạy Facebook Ads\n- Biết Google Analytics\n")
        self.assertEqual(len(r.criteria), 2)

    def test_enough_total_years_but_wrong_field_needs_human_not_auto_reject(self):
        from cv_agent.cv_parse import check_experience, parse_blocks, split_cv
        blocks = parse_blocks(split_cv("EXPERIENCE\nSenior Accountant – X (2018 - 2024)\n- Financial reports\n"))
        hc, _, _ = check_experience("Có ít nhất 2 năm kinh nghiệm phân tích dữ liệu", blocks)
        self.assertEqual(hc.status, "unclear")
        self.assertIn("cần người xem", hc.note)
        no_time = parse_blocks(split_cv("EXPERIENCE\nIntern – X (06/2025 - 07/2025)\n- Filing\n"))
        hc2, _, _ = check_experience("Có ít nhất 2 năm kinh nghiệm phân tích dữ liệu", no_time)
        self.assertEqual(hc2.status, "not_met")                                       # thật sự thiếu thời gian thì vẫn là not_met


class IdentityTests(unittest.TestCase):
    """Tên ứng viên phải đọc được dù phía trên có chữ khác (CURRICULUM VITAE, chức danh, slogan) hoặc CV là bản OCR."""

    def name(self, text, filename="", ocr=False):
        from cv_agent.identity import find_name
        return find_name(text, filename, ocr)

    def test_name_below_other_text(self):
        cases = {
            "CURRICULUM VITAE\nNguyễn Văn An\nSoftware Engineer\n0903 456 789": "Nguyễn Văn An",
            "RESUME\n\nLê Thị Hoa\nMarketing Executive": "Lê Thị Hoa",
            "SENIOR DATA SCIENTIST\nTrần Minh Khoa\nEmail: khoa@x.com": "Trần Minh Khoa",
            "Passionate about building AI products\nPhạm Quốc Bảo\nHà Nội": "Phạm Quốc Bảo",
            "SƠ YẾU LÝ LỊCH\nNGUYỄN THỊ LAN\nKế toán tổng hợp": "Nguyễn Thị Lan",
            "HỒ SƠ ỨNG TUYỂN\nThông tin cá nhân\nHọ và tên: Đặng Thùy Dương\nNgày sinh: 1/1/1995": "Đặng Thùy Dương",
            "Lâm Gia Huy | Backend Developer | huy@x.com": "Lâm Gia Huy",
            "CV - Võ Hoàng Nam\nQuản trị kinh doanh": "Võ Hoàng Nam",
            "NGUYỄN HOÀNG TUẤN AI Engineer\nBình Dương": "Nguyễn Hoàng Tuấn",
            "AI Engineer Trần Thu Hà\nHà Nội": "Trần Thu Hà",
        }
        for text, expected in cases.items():
            self.assertEqual(self.name(text).value, expected, text)

    def test_common_vietnamese_names_are_not_mistaken_for_headings_or_places(self):
        for text in ("Học vấn\nNguyễn Văn Minh", "Hồ Chí Minh\nHà Nội\nLê Văn Nam", "Quản lý dự án\nTrần Hoàng Nam"):
            self.assertIn(self.name(text).value.split()[-1], ("Minh", "Nam"), text)

    def test_places_and_headings_are_not_names(self):
        for text in ("Hồ Chí Minh\nHà Nội\nĐà Nẵng", "Machine Learning\nData Science\nProjects", "Học vấn\nĐại học Bách Khoa\nKỹ thuật phần mềm"):
            self.assertEqual(self.name(text).value, "", text)

    def test_ocr_glued_uppercase_name_below_title(self):
        n = self.name("CURRICULUMVITAE\nNGUYENHOANGNAM\nAl Engineer\nEmail:nam.nguyen@example.com", "scan.pdf", ocr=True)
        self.assertEqual((n.value, n.source), ("Nguyen Hoang Nam", "ocr"))
        for glued, expected in (("TRANVANMINH", "Tran Van Minh"), ("PHAMQUOCBAO", "Pham Quoc Bao"), ("NguyenVanAn", "Nguyen Van An")):
            self.assertEqual(self.name(f"CV\n{glued}\nEngineer", "x.pdf", ocr=True).value, expected)

    def test_ocr_garbled_name_falls_back_to_filename_then_email(self):
        text = "Men Minhn Quaneer\nHa Noi·quan.le.demo@example.com"
        self.assertEqual(self.name(text, "le-minh-quan.pdf", ocr=True).value, "Le Minh Quan")
        self.assertEqual(self.name(text, "scan1.pdf", ocr=True).value, "Quan Le")
        self.assertEqual(self.name(text, "scan1.pdf", ocr=True).source, "email")

    def test_ocr_name_agreeing_with_filename_is_trusted(self):
        n = self.name("CURRICULUMVITAE\nNGUYENHOANGNAM", "nguyen-hoang-nam.pdf", ocr=True)
        self.assertEqual((n.value, n.source), ("Nguyen Hoang Nam", "cv"))

    def test_filename_ho_so_is_not_a_surname(self):
        self.assertEqual(self.name("Kinh nghiệm\nABC", "ho-so-tran-van-minh.pdf").value, "Tran Van Minh")
        self.assertEqual(self.name("Học vấn\nX", "Ho_Van_Thanh_CV.pdf").value, "Ho Van Thanh")


class NameHidingTests(unittest.TestCase):
    def test_name_is_hidden_even_below_a_title_line(self):
        out = anonymize("CURRICULUM VITAE\nNGUYỄN HOÀNG TUẤN\nAI Engineer\nEmail: t@x.com\nReferee: Nguyễn Hoàng Tuấn said ok\nPython 2019 - 2022")
        self.assertNotIn("TUẤN", out.upper())
        self.assertIn("CURRICULUM VITAE", out)
        self.assertIn("Python 2019 - 2022", out)

    def test_glued_ocr_name_is_hidden(self):
        out = anonymize("CURRICULUMVITAE\nNGUYENHOANGNAM\nAl Engineer\nEmail:nam.nguyen@example.com")
        self.assertNotIn("NGUYENHOANGNAM", out)
        self.assertIn("[NAME]", out)


class DecisionModelTests(unittest.TestCase):
    """Quyết định dựa trên mức đáp ứng yêu cầu BẮT BUỘC; kỹ năng ưu tiên chỉ là điểm cộng khi xếp hạng."""
    JD = "Kỹ sư\nYêu cầu:\n- Thành thạo Python\n- Biết Docker\n- Biết Git\nƯu tiên:\n- Biết AWS\n- Biết Spark\n- Biết Kafka\n- Biết Airflow\n"
    STRONG = "A B\nEXPERIENCE\nDev – X (2020 - 2024)\n- Python, Docker and Git daily\nSKILLS\nPython, Docker, Git\n"
    BONUS_ONLY = "A B\nEXPERIENCE\nDev – X (2020 - 2024)\n- AWS, Spark, Kafka and Airflow pipelines\nSKILLS\nAWS, Spark, Kafka, Airflow\n"

    def setUp(self):
        from cv_agent.baseline import score_cv_baseline
        self.rubric = build_rubric_rules(self.JD)
        self.score = lambda cv: score_cv_baseline(self.rubric, cv)

    def test_required_score_is_reported_and_bonus_does_not_make_someone_eligible(self):
        strong, bonus = self.score(self.STRONG)["summary"], self.score(self.BONUS_ONLY)["summary"]
        self.assertGreaterEqual(strong["required_score"], 70)
        self.assertEqual(bonus["required_score"], 0.0)
        self.assertEqual(verdict(strong), FIT)
        self.assertIn(verdict(bonus), (REJECT, RESERVE))             # thạo hết phần ưu tiên mà thiếu toàn bộ phần bắt buộc: không được mời
        self.assertGreater(bonus["overall_score"], 0)                # nhưng điểm cộng vẫn có mặt trong điểm tổng để xếp hạng

    def test_row_has_checklist_and_suggestion(self):
        from cv_agent.report import make_row
        row = make_row(self.rubric, "a.txt", self.score(self.STRONG))
        kinds = [c["kind"] for c in row["checklist"]]
        self.assertEqual((kinds.count("required"), kinds.count("preferred")), (3, 4))
        self.assertEqual(row["suggestion"], "Mời phỏng vấn")
        self.assertEqual((row["req_met"], row["req_total"]), (3, 3))
        self.assertIn("3/3 kỹ năng bắt buộc", row["checklist_summary"])
        self.assertIn("Đáp ứng", row["verdict_reason"])

    def test_ranking_respects_verdict_tier_before_bonus_points(self):
        from cv_agent.report import make_row, rank
        a = make_row(self.rubric, "strong.txt", self.score(self.STRONG))
        b = make_row(self.rubric, "bonus.txt", self.score(self.BONUS_ONLY))
        b["overall_score"] = 99.0                                     # dù điểm tổng cao hơn, nhóm kết luận thấp hơn vẫn xếp sau
        self.assertEqual([r["file"] for r in rank([b, a])], ["strong.txt", "bonus.txt"])


class OcrNameEndToEndTests(unittest.TestCase):
    def test_scanned_cv_with_title_above_name_gets_a_name_and_a_review_note(self):
        import tempfile
        from pathlib import Path
        from unittest import mock

        import pymupdf

        from cv_agent import io_utils
        from cv_agent.pipeline import screen
        import cv_agent.pipeline as pl
        patcher = mock.patch.object(pl, "MIN_CV_WORDS", 0)
        patcher.start()
        self.addCleanup(patcher.stop)
        text = "CURRICULUMVITAE\nNGUYENHOANGNAM\nAl Engineer (Fresher)\nEmail:nam.nguyen@example.com\nEXPERIENCE\nAl Intern-Acme (06/2025-12/2025)\n-Built models with Python\n"
        with tempfile.TemporaryDirectory() as tmp:
            src = pymupdf.open()
            src.new_page().insert_text((72, 100), "x")
            png = src[0].get_pixmap(dpi=40).tobytes("png")
            out = pymupdf.open()
            out.new_page().insert_image(pymupdf.Rect(0, 0, 595, 842), stream=png)
            path = Path(tmp) / "scan_001.pdf"
            out.save(str(path))
            with mock.patch.object(io_utils, "_ocr_tesseract", side_effect=RuntimeError("không có")), \
                    mock.patch.object(io_utils, "_ocr_rapid", return_value=text):
                row = screen(build_rubric_rules("Yêu cầu:\n- Biết Python\n- Biết Git\n"), [("scan_001.pdf", path)])[0]
        self.assertEqual(row["candidate_name"], "Nguyen Hoang Nam")
        self.assertEqual(row["name_source"], "ocr")
        self.assertIn("OCR", row["review_reason"])
        self.assertEqual(row["email"], "nam.nguyen@example.com")


if __name__ == "__main__":
    unittest.main()
