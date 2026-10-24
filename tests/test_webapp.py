"""Kiểm thử giao diện web mới: máy chủ HTTP thật chạy trên cổng tạm, gọi bằng urllib (không cần trình duyệt)."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["CV_AGENT_AS_OF"] = "2026-10"

from webapp.multipart import MultipartError, parse_multipart  # noqa: E402
from webapp.server import App, STATIC, _host_ok  # noqa: E402
from webapp.service import Service, ServiceError  # noqa: E402

CVS = ROOT / "samples" / "cvs"
JD = (ROOT / "samples" / "jds" / "ai01.txt").read_text(encoding="utf-8")


def multipart(files: list[tuple[str, str, bytes]]):
    boundary = "----cvtest" + uuid.uuid4().hex
    body = b""
    for field, name, data in files:
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{name}\"\r\n"
                 f"Content-Type: application/octet-stream\r\n\r\n").encode("utf-8") + data + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    return f"multipart/form-data; boundary={boundary}", body


class MultipartTests(unittest.TestCase):
    def test_binary_and_unicode_names(self):
        payload = bytes(range(256)) + b"\r\n--not-a-boundary\r\n"
        ctype, body = multipart([("files", "Nguyễn Văn A.pdf", payload), ("files", "b.txt", "Tiếng Việt".encode())])
        parts = parse_multipart(ctype, body)
        self.assertEqual([p[1] for p in parts], ["Nguyễn Văn A.pdf", "b.txt"])
        self.assertEqual(parts[0][2], payload)
        self.assertEqual(parts[1][2].decode(), "Tiếng Việt")

    def test_rejects_garbage(self):
        with self.assertRaises(MultipartError):
            parse_multipart("application/json", b"{}")
        with self.assertRaises(MultipartError):
            parse_multipart("multipart/form-data", b"x")


class HostGuardTests(unittest.TestCase):
    def test_only_local_hosts_pass(self):
        for ok in ("localhost:8765", "127.0.0.1:1", "http://localhost:8765", "http://127.0.0.1:8765/", "[::1]:80", None, ""):
            self.assertTrue(_host_ok(ok), ok)
        for bad in ("evil.com", "http://evil.com", "localhost.evil.com", "127.0.0.1.evil.com:80", "null", "http://192.168.1.5:8765"):
            self.assertFalse(_host_ok(bad), bad)


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.service = Service(Path(cls._tmp.name))
        cls.app = App(("127.0.0.1", 0), cls.service)
        cls.port = cls.app.server_address[1]
        threading.Thread(target=cls.app.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.app.shutdown()
        cls.app.server_close()
        cls.service.close()
        cls._tmp.cleanup()

    # ---- tiện ích gọi HTTP
    def call(self, method, path, body=None, headers=None, token=True, raw=False):
        url = f"http://127.0.0.1:{self.port}{path}"
        data, hdrs = None, dict(headers or {})
        if token:
            hdrs.setdefault("X-CV-Token", self.app.token)
        if isinstance(body, tuple):                                    # (content_type, bytes)
            hdrs["Content-Type"], data = body
        elif body is not None:
            hdrs["Content-Type"], data = "application/json", json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                content = r.read()
                return r.status, (content if raw else json.loads(content.decode("utf-8"))), r.headers
        except urllib.error.HTTPError as e:
            content = e.read()
            return e.code, (content if raw else json.loads(content.decode("utf-8"))), e.headers

    def wait_job(self, job_id, timeout=90):
        end = time.time() + timeout
        while time.time() < end:
            _, job, _ = self.call("GET", f"/api/jobs/{job_id}")
            if job["status"] != "running":
                return job
            time.sleep(0.2)
        self.fail("tác vụ không kết thúc")

    # ---- bảo mật và tệp tĩnh
    def test_index_has_token_and_security_headers(self):
        status, html, headers = self.call("GET", "/", token=False, raw=True)
        self.assertEqual(status, 200)
        self.assertIn(self.app.token.encode(), html)
        self.assertNotIn(b"{{TOKEN}}", html)
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_api_requires_token_and_local_origin(self):
        self.assertEqual(self.call("GET", "/api/bootstrap", token=False)[0], 403)
        self.assertEqual(self.call("GET", "/api/bootstrap", headers={"X-CV-Token": "sai"}, token=False)[0], 403)
        self.assertEqual(self.call("GET", "/api/bootstrap", headers={"Origin": "http://evil.com"})[0], 403)
        self.assertEqual(self.call("GET", "/api/bootstrap", headers={"Host": "evil.com"})[0], 403)
        self.assertEqual(self.call("GET", "/api/bootstrap")[0], 200)

    def test_static_files_and_path_traversal(self):
        self.assertEqual(self.call("GET", "/style.css", token=False, raw=True)[0], 200)
        self.assertEqual(self.call("GET", "/app.js", token=False, raw=True)[0], 200)
        self.assertEqual(self.call("GET", "/%2e%2e/server.py", token=False, raw=True)[0], 404)
        self.assertEqual(self.call("GET", "/../../README.md", token=False, raw=True)[0], 404)
        self.assertTrue((STATIC / "index.html").exists())

    # ---- JD
    def test_filter_jd(self):
        status, data, _ = self.call("POST", "/api/jd/filter", {"text": JD})
        self.assertEqual(status, 200)
        self.assertEqual(len(data["rubric"]["hard"]), 3)
        self.assertIn("Yêu cầu:", data["core_jd"])
        status, data, _ = self.call("POST", "/api/jd/filter", {"text": "   "})
        self.assertEqual(status, 400)
        self.assertIn("Chưa có nội dung JD", data["error"])

    def test_jd_upload(self):
        ctype, body = multipart([("file", "jd.txt", JD.encode("utf-8"))])
        status, data, _ = self.call("POST", "/api/jd/upload", (ctype, body))
        self.assertEqual(status, 200)
        self.assertIn("Required skills", data["text"])
        ctype, body = multipart([("file", "jd.exe", b"x")])
        self.assertEqual(self.call("POST", "/api/jd/upload", (ctype, body))[0], 400)

    # ---- file CV
    def test_upload_remove_and_reject(self):
        self.service.clear_files()
        ctype, body = multipart([("files", "a.txt", b"Python"), ("files", "b.pdf", b"%PDF"), ("files", "evil.exe", b"MZ")])
        status, data, _ = self.call("POST", "/api/files", (ctype, body))
        self.assertEqual(status, 200)
        self.assertEqual(sorted(f["name"] for f in data["files"]), ["a.txt", "b.pdf"])
        self.assertEqual(data["rejected"], ["evil.exe"])
        self.assertNotIn("path", data["files"][0])                       # không lộ đường dẫn trên máy ra giao diện
        fid = data["files"][0]["id"]
        self.assertEqual(self.call("DELETE", f"/api/files/{fid}")[0], 200)
        self.assertEqual(len(self.call("GET", "/api/bootstrap")[1]["files"]), 1)
        self.service.clear_files()
        self.assertEqual(self.call("POST", "/api/files", multipart([("files", "x.exe", b"MZ")]))[0], 400)

    def test_same_name_uploads_do_not_overwrite(self):
        self.service.clear_files()
        ctype, body = multipart([("files", "cv.txt", b"AAA"), ("files", "cv.txt", b"BBB")])
        _, data, _ = self.call("POST", "/api/files", (ctype, body))
        paths = {Path(f["path"]).read_text() for f in self.service.files.values()}
        self.assertEqual(paths, {"AAA", "BBB"})
        self.assertEqual(len(data["files"]), 2)
        self.service.clear_files()

    def test_folder_scan_errors(self):
        self.assertEqual(self.call("POST", "/api/folder", {"path": str(ROOT / "khong_ton_tai")})[0], 400)
        with tempfile.TemporaryDirectory() as empty:
            self.assertEqual(self.call("POST", "/api/folder", {"path": empty})[0], 400)
        self.service.clear_files()
        status, data, _ = self.call("POST", "/api/folder", {"path": str(CVS)})
        self.assertEqual((status, len(data["files"])), (200, 9))
        self.assertEqual(len(self.call("POST", "/api/folder", {"path": str(CVS)})[1]["files"]), 0)      # quét lại: không thêm trùng
        self.service.clear_files()

    # ---- luồng đầy đủ
    def test_full_flow_screen_decide_export(self):
        self.service.clear_files()
        _, folder, _ = self.call("POST", "/api/folder", {"path": str(CVS)})
        ids = [f["id"] for f in folder["files"]]
        status, started, _ = self.call("POST", "/api/screen", {"jd_text": JD, "core_jd": "", "file_ids": ids, "fit": 70, "maybe": 50, "reject": 30})
        self.assertEqual(status, 200)
        job = self.wait_job(started["job_id"])
        self.assertEqual(job["status"], "done", job.get("error"))
        self.assertEqual((job["done"], job["total"]), (9, 9))
        run_id = job["run_id"]

        _, run, _ = self.call("GET", f"/api/runs/{run_id}")
        rows = run["rows"]
        self.assertEqual(len(rows), 9)
        self.assertEqual(rows[0]["rank"], 1)
        self.assertEqual(rows[0]["candidate_name"], "Lê Minh Quân")
        self.assertTrue(rows[0]["checklist"])
        self.assertIn("điều kiện bắt buộc", rows[0]["checklist_summary"])
        self.assertEqual(run["rubric"]["hard"][0]["type"], "education")

        # quyết định của HR được lưu xuống đĩa
        _, d, _ = self.call("POST", f"/api/runs/{run_id}/decision", {"index": 0, "decision": "Mời phỏng vấn", "note": "Gọi thứ Hai"})
        self.assertEqual(d["hr_decision"], "Mời phỏng vấn")
        saved = json.loads((Path(self._tmp.name) / run_id / "rows.json").read_text(encoding="utf-8"))
        self.assertEqual(saved[0]["hr_decision"], "Mời phỏng vấn")
        self.assertEqual(saved[0]["hr_note"], "Gọi thứ Hai")
        self.assertEqual(self.call("POST", f"/api/runs/{run_id}/decision", {"index": 0, "decision": "Tuỳ ý"})[0], 400)
        self.assertEqual(self.call("POST", f"/api/runs/{run_id}/decision", {"index": 99, "decision": "Giữ lại"})[0], 400)

        # chấp nhận đề xuất hàng loạt
        _, bulk, _ = self.call("POST", f"/api/runs/{run_id}/bulk", {"indices": list(range(9)), "decision": "accept"})
        self.assertGreater(bulk["changed"], 0)
        _, run, _ = self.call("GET", f"/api/runs/{run_id}")
        by_verdict = {r["verdict"]: r["hr_decision"] for r in run["rows"]}
        self.assertEqual(by_verdict["Loại"], "Từ chối")
        self.assertEqual(by_verdict["Phù hợp - Mời phỏng vấn"], "Mời phỏng vấn")

        # email: ưu tiên người HR đã chọn "Mời phỏng vấn"
        _, em, _ = self.call("GET", f"/api/runs/{run_id}/emails")
        self.assertGreater(em["count"], 0)
        self.assertTrue(all("@" in e for e in em["emails"]))

        # xuất file (tải bằng token trong URL như nút tải của trình duyệt)
        status, xlsx, headers = self.call("GET", f"/api/runs/{run_id}/export/xlsx?token={self.app.token}", token=False, raw=True)
        self.assertEqual(status, 200)
        self.assertTrue(xlsx.startswith(b"PK"))
        self.assertIn("attachment", headers["Content-Disposition"])
        status, csv, _ = self.call("GET", f"/api/runs/{run_id}/export/csv", raw=True)
        self.assertIn("Lê Minh Quân".encode("utf-8"), csv)
        self.assertEqual(self.call("GET", f"/api/runs/{run_id}/export/pdf")[0], 400)

        # lịch sử và xóa
        self.assertIn(run_id, [r["id"] for r in self.call("GET", "/api/runs")[1]["runs"]])
        self.assertEqual(self.call("DELETE", f"/api/runs/{run_id}")[0], 200)
        self.assertEqual(self.call("GET", f"/api/runs/{run_id}")[0], 400)

    def test_screen_validation(self):
        self.service.clear_files()
        self.assertEqual(self.call("POST", "/api/screen", {"jd_text": JD, "file_ids": [], "fit": 70, "maybe": 50, "reject": 30})[0], 400)
        _, folder, _ = self.call("POST", "/api/folder", {"path": str(CVS)})
        ids = [f["id"] for f in folder["files"]][:1]
        self.assertEqual(self.call("POST", "/api/screen", {"jd_text": JD, "file_ids": ids, "fit": 40, "maybe": 50, "reject": 30})[0], 400)
        self.assertEqual(self.call("POST", "/api/screen", {"jd_text": "", "file_ids": ids, "fit": 70, "maybe": 50, "reject": 30})[0], 400)
        self.assertEqual(self.call("POST", "/api/screen", {"jd_text": JD, "file_ids": ids, "fit": "abc", "maybe": 50, "reject": 30})[0], 400)
        self.service.clear_files()

    def test_bad_run_ids_are_rejected(self):
        for bad in ("..", "..%2F..", "a%20b", "x%3By"):
            self.assertEqual(self.call("GET", f"/api/runs/{bad}")[0], 400 if "%2F" not in bad else 404, bad)

    def test_broken_cv_does_not_break_job(self):
        self.service.clear_files()
        ctype, body = multipart([("files", "good.txt", (CVS / "ai_cv1.txt").read_bytes()), ("files", "broken.pdf", b"%PDF-1.4 broken"), ("files", "empty.txt", b"")])
        _, data, _ = self.call("POST", "/api/files", (ctype, body))
        ids = [f["id"] for f in data["files"]]
        _, started, _ = self.call("POST", "/api/screen", {"jd_text": JD, "file_ids": ids, "fit": 70, "maybe": 50, "reject": 30})
        job = self.wait_job(started["job_id"])
        self.assertEqual(job["status"], "done")
        _, run, _ = self.call("GET", f"/api/runs/{job['run_id']}")
        verdicts = {r["file"]: r["verdict"] for r in run["rows"]}
        self.assertEqual(verdicts["broken.pdf"], "LỖI")
        self.assertEqual(verdicts["empty.txt"], "LỖI")
        self.assertNotEqual(verdicts["good.txt"], "LỖI")
        self.service.clear_files()
        self.call("DELETE", f"/api/runs/{job['run_id']}")

    def test_sample_loads(self):
        status, data, _ = self.call("POST", "/api/sample")
        self.assertEqual(status, 200)
        self.assertEqual(len(data["files"]), 9)
        self.assertIn("Required skills", data["jd_text"])
        self.service.clear_files()

    def _run_samples(self, fit=70, maybe=50, reject=30):
        self.service.clear_files()
        _, folder, _ = self.call("POST", "/api/folder", {"path": str(CVS)})
        ids = [f["id"] for f in folder["files"]]
        _, started, _ = self.call("POST", "/api/screen", {"jd_text": JD, "file_ids": ids, "fit": fit, "maybe": maybe, "reject": reject})
        job = self.wait_job(started["job_id"])
        self.assertEqual(job["status"], "done", job.get("error"))
        self.service.clear_files()
        return job["run_id"]

    def test_rejudge_matches_a_fresh_run_and_keeps_hr_decisions(self):
        run_id = self._run_samples(70, 50, 30)
        self.call("POST", f"/api/runs/{run_id}/decision", {"index": 0, "decision": "Giữ lại", "note": "xem lại"})
        name_first = self.call("GET", f"/api/runs/{run_id}")[1]["rows"][0]["file"]

        status, changed, _ = self.call("POST", f"/api/runs/{run_id}/rejudge", {"fit": 85, "maybe": 65, "reject": 45})
        self.assertEqual(status, 200)
        self.assertTrue(changed["can_rejudge"])
        self.assertEqual((changed["meta"]["fit"], changed["meta"]["maybe"], changed["meta"]["reject"]), (85, 65, 45))

        fresh_id = self._run_samples(85, 65, 45)
        fresh = self.call("GET", f"/api/runs/{fresh_id}")[1]["rows"]
        got = [(r["file"], r["verdict"], r["suggestion"], r["verdict_reason"], r["rank"]) for r in changed["rows"]]
        want = [(r["file"], r["verdict"], r["suggestion"], r["verdict_reason"], r["rank"]) for r in fresh]
        self.assertEqual(got, want)                                                 # đổi mức tại chỗ = chạy lại từ đầu với mức đó

        kept = next(r for r in changed["rows"] if r["file"] == name_first)
        self.assertEqual((kept["hr_decision"], kept["hr_note"]), ("Giữ lại", "xem lại"))   # quyết định của HR không mất
        saved = json.loads((Path(self._tmp.name) / run_id / "rows.json").read_text(encoding="utf-8"))
        self.assertEqual([r["verdict"] for r in saved], [r["verdict"] for r in changed["rows"]])   # đã ghi xuống đĩa
        for rid in (run_id, fresh_id):
            self.call("DELETE", f"/api/runs/{rid}")

    def test_rejudge_validates_input_and_old_runs(self):
        run_id = self._run_samples()
        self.assertEqual(self.call("POST", f"/api/runs/{run_id}/rejudge", {"fit": 40, "maybe": 50, "reject": 30})[0], 400)
        self.assertEqual(self.call("POST", f"/api/runs/{run_id}/rejudge", {"fit": "x", "maybe": 50, "reject": 30})[0], 400)
        self.assertEqual(self.call("POST", f"/api/runs/{run_id}/rejudge", {"maybe": 50, "reject": 30})[0], 400)
        for r in self.service.runs[run_id]["rows"]:                                   # giả lập lần chạy lưu bằng phiên bản cũ
            r.pop("verdict_inputs", None)
        status, err, _ = self.call("POST", f"/api/runs/{run_id}/rejudge", {"fit": 70, "maybe": 50, "reject": 30})
        self.assertEqual(status, 400)
        self.assertIn("phiên bản cũ", err["error"])
        self.assertFalse(self.call("GET", f"/api/runs/{run_id}")[1]["can_rejudge"])
        self.call("DELETE", f"/api/runs/{run_id}")

    def test_printable_report(self):
        run_id = self._run_samples()
        self.service.runs[run_id]["rows"][0]["candidate_name"] = '<script>alert(1)</script>'
        self.service.runs[run_id]["rows"][0]["hr_note"] = '"><img src=x onerror=alert(2)>'
        self.service.runs[run_id]["rows"][0]["hr_decision"] = "Mời phỏng vấn"
        status, page, headers = self.call("GET", f"/api/runs/{run_id}/report?scope=all&token={self.app.token}", token=False, raw=True)
        html = page.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/html"))
        self.assertNotIn("<script>alert", html)                                      # tên ứng viên từ CV luôn được escape
        self.assertNotIn("<img src=x", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("Báo cáo sàng lọc CV", html)
        self.assertEqual(html.count('class="card"'), 9)
        invited = self.call("GET", f"/api/runs/{run_id}/report?scope=invited", raw=True)[1].decode("utf-8")
        self.assertEqual(invited.count('class="card"'), 1)
        suit = self.call("GET", f"/api/runs/{run_id}/report", raw=True)[1].decode("utf-8")
        self.assertLess(suit.count('class="card"'), 9)
        self.assertEqual(self.call("GET", f"/api/runs/{run_id}/report", token=False, raw=True)[0], 403)
        self.call("DELETE", f"/api/runs/{run_id}")

    def test_page_reload_during_a_job_can_reattach_to_it(self):
        from unittest import mock
        from cv_agent.pipeline import Cancelled

        def slow_screen(rubric, items, *, cancel=None, **kw):
            for _ in range(200):
                if cancel.is_set():
                    raise Cancelled()
                time.sleep(0.02)
            return []

        self.service.clear_files()
        _, folder, _ = self.call("POST", "/api/folder", {"path": str(CVS)})
        with mock.patch("webapp.service.screen", slow_screen):
            _, started, _ = self.call("POST", "/api/screen", {"jd_text": JD, "file_ids": [f["id"] for f in folder["files"]], "fit": 70, "maybe": 50, "reject": 30})
            boot = self.call("GET", "/api/bootstrap")[1]
            self.assertEqual(boot["job"]["id"], started["job_id"])                  # trang mở lại thấy tác vụ đang chạy
            self.call("POST", f"/api/jobs/{started['job_id']}/cancel")
            self.wait_job(started["job_id"], timeout=10)
        self.assertIsNone(self.call("GET", "/api/bootstrap")[1]["job"])              # xong rồi thì không còn
        self.service.clear_files()

    def test_cancel_running_job(self):
        from unittest import mock
        from cv_agent.pipeline import Cancelled

        def slow_screen(rubric, items, *, cancel=None, **kw):
            for _ in range(200):
                if cancel.is_set():
                    raise Cancelled()
                time.sleep(0.02)
            return []

        self.service.clear_files()
        _, folder, _ = self.call("POST", "/api/folder", {"path": str(CVS)})
        ids = [f["id"] for f in folder["files"]]
        with mock.patch("webapp.service.screen", slow_screen):
            _, started, _ = self.call("POST", "/api/screen", {"jd_text": JD, "file_ids": ids, "fit": 70, "maybe": 50, "reject": 30})
            job_id = started["job_id"]
            self.assertEqual(self.call("GET", f"/api/jobs/{job_id}")[1]["status"], "running")
            status, after, _ = self.call("POST", f"/api/jobs/{job_id}/cancel")
            self.assertEqual(status, 200)
            job = self.wait_job(job_id, timeout=10)
        self.assertEqual(job["status"], "cancelled")
        self.assertIsNone(job["run_id"])
        self.assertEqual(self.call("POST", "/api/jobs/khong-co/cancel")[0], 400)
        self.service.clear_files()

    def test_unknown_route_and_method(self):
        self.assertEqual(self.call("GET", "/api/nope")[0], 404)
        self.assertEqual(self.call("POST", "/api/bootstrap", {})[0], 404)


    def test_wrong_typed_json_gives_400_never_500(self):
        """Fuzz API phát hiện 15 lỗi 500 khi gửi số/danh sách/đối tượng thay cho chữ."""
        run_id = self._run_samples()
        weird = [None, True, 0, -1, 1.5, "", "abc", [], [1], {}, {"a": 1}, 10 ** 20, [None]]
        calls = [("POST", "/api/jd/filter", lambda v: {"text": v}), ("POST", "/api/folder", lambda v: {"path": v}),
                 ("POST", "/api/screen", lambda v: {"jd_text": v, "file_ids": v, "fit": v, "maybe": v, "reject": v, "workers": v}),
                 ("POST", f"/api/runs/{run_id}/decision", lambda v: {"index": v, "decision": v, "note": v}),
                 ("POST", f"/api/runs/{run_id}/bulk", lambda v: {"indices": v, "decision": v}),
                 ("POST", f"/api/runs/{run_id}/rejudge", lambda v: {"fit": v, "maybe": v, "reject": v})]
        for method, path, make in calls:
            for value in weird:
                status, _, _ = self.call(method, path, make(value))
                self.assertLess(status, 500, (path, value))
        self.assertEqual(self.call("PUT", "/api/runs")[0], 404)                 # phương thức lạ: JSON gọn, không phải trang lỗi HTML
        self.call("DELETE", f"/api/runs/{run_id}")

    def test_negative_row_index_does_not_edit_the_last_row(self):
        run_id = self._run_samples()
        self.assertEqual(self.call("POST", f"/api/runs/{run_id}/decision", {"index": -1, "decision": "Giữ lại"})[0], 400)
        self.assertEqual(self.call("POST", f"/api/runs/{run_id}/bulk", {"indices": [-1], "decision": "Từ chối"})[1]["changed"], 0)
        rows = self.call("GET", f"/api/runs/{run_id}")[1]["rows"]
        self.assertEqual([r.get("hr_decision", "") for r in rows], [""] * len(rows))
        self.call("DELETE", f"/api/runs/{run_id}")

    def test_odd_tokens_and_paths_give_403_or_404_never_500(self):
        for token in ("ü", "tôi", "\x7f", "a" * 5000):
            status, _, _ = self.call("GET", "/api/bootstrap", headers={"X-CV-Token": token.encode("latin-1", "replace").decode("latin-1")}, token=False)
            self.assertEqual(status, 403, token[:10])
        self.assertEqual(self.call("GET", "/api/bootstrap?token=%C3%BC", token=False)[0], 403)         # ký tự ngoài ASCII trong query
        for path in ("/%00", "/app.js%00", "/..%5c..%5cserver.py", "/%2e%2e/%2e%2e/README.md", "/static%5c..", "/CON", "/a:b", "/" + "x" * 3000):
            self.assertIn(self.call("GET", path, token=False, raw=True)[0], (404, 400), path)

    def test_sibling_folder_with_the_same_prefix_is_not_served(self):
        """Trước đây kiểm tra bằng tiền tố chuỗi: thư mục "static_x" cạnh "static" cũng bắt đầu bằng "static"."""
        sibling = STATIC.parent / "static_private_test"
        sibling.mkdir(exist_ok=True)
        try:
            (sibling / "secret.txt").write_text("bi mat", encoding="utf-8")
            self.assertEqual(self.call("GET", "/..%2Fstatic_private_test%2Fsecret.txt", token=False, raw=True)[0], 404)
            self.assertEqual(self.call("GET", "/../static_private_test/secret.txt", token=False, raw=True)[0], 404)
        finally:
            (sibling / "secret.txt").unlink(missing_ok=True)
            sibling.rmdir()

    def test_negative_content_length_is_rejected_instead_of_hanging(self):
        import socket
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as s:
            s.sendall(f"POST /api/jd/filter HTTP/1.1\r\nHost: localhost\r\nX-CV-Token: {self.app.token}\r\nContent-Length: -5\r\n\r\n".encode())
            reply = s.recv(4096)
        self.assertTrue(reply.startswith(b"HTTP/1.1 400"), reply[:60])

    def test_upload_with_hostile_file_names_does_not_crash(self):
        self.service.clear_files()
        names = ["CON.txt", "a:b*c?.txt", "..\\..\\evil.txt", "x" * 400 + ".txt", " .txt", "NUL", "ok.TXT", "../up.txt"]
        ctype, body = multipart([("files", n, b"Python Git") for n in names])
        status, data, _ = self.call("POST", "/api/files", (ctype, body))
        self.assertEqual(status, 200, data)
        self.assertEqual(data["rejected"], ["_NUL"])                     # tên thiết bị được đổi tên; không có đuôi hợp lệ nên bị từ chối
        self.assertEqual(len(data["files"]), len(names) - 1)
        for ref in self.service.files.values():
            self.assertTrue(Path(ref["path"]).is_file())
            self.assertEqual(Path(ref["path"]).parent.parent, self.service._tmp)          # không thoát khỏi thư mục tạm
            self.assertLessEqual(len(ref["name"]), 120)
        self.service.clear_files()

    def test_folder_with_too_many_files_is_refused(self):
        from unittest import mock
        import cv_agent.pipeline as pl
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(5):
                (Path(tmp) / f"c{i}.txt").write_text("x")
            with mock.patch.object(pl, "MAX_FOLDER_FILES", 3):
                status, err, _ = self.call("POST", "/api/folder", {"path": tmp})
        self.assertEqual(status, 400)
        self.assertIn("hơn 3", err["error"])
        self.service.clear_files()


class ServiceUnitTests(unittest.TestCase):
    def test_decision_value_is_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            svc = Service(Path(tmp))
            with self.assertRaises(ServiceError):
                svc.set_decision("khong..co", 0, "Giữ lại")
            svc.close()

    def _service_with_run(self, tmp):
        from cv_agent import storage
        from cv_agent.pipeline import build_rubric, screen
        svc = Service(Path(tmp))
        rubric = build_rubric("Yêu cầu:\n- Biết Python\n")
        cvs = []
        for i in range(3):
            p = Path(tmp) / f"c{i}.txt"
            p.write_text(f"Nguyễn Văn {'ABC'[i]}\nSKILLS\nPython\nEXPERIENCE\nDev - X (2020 - 2024)\n- Python " + "services " * 30 + str(i), encoding="utf-8")
            cvs.append((p.name, p))
        rows = screen(rubric, cvs)
        folder = storage.save_run(rows, rubric, "core", {"fit": 70, "maybe": 50, "reject": 30}, base=Path(tmp) / "out")
        svc.output_dir = Path(tmp) / "out"
        return svc, folder.name

    def test_decisions_are_saved_at_once_but_excel_is_written_later_in_one_go(self):
        import time
        from unittest import mock
        import webapp.service as svc_mod
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(svc_mod, "EXPORT_DELAY", 0.2):
            svc, run_id = self._service_with_run(tmp)
            xlsx = Path(tmp) / "out" / run_id / "ketqua.xlsx"
            before = xlsx.stat().st_mtime_ns
            writes = []
            real = svc_mod.storage.write_exports
            with mock.patch.object(svc_mod.storage, "write_exports", lambda *a: (writes.append(1), real(*a))):
                for i in range(3):                                           # ba lần bấm liên tiếp
                    svc.set_decision(run_id, i, "Mời phỏng vấn", "ghi chú")
                saved = json.loads((Path(tmp) / "out" / run_id / "rows.json").read_text(encoding="utf-8"))
                self.assertEqual([r["hr_decision"] for r in saved], ["Mời phỏng vấn"] * 3)      # rows.json đã có ngay
                self.assertEqual(xlsx.stat().st_mtime_ns, before)                                # Excel chưa bị ghi lại
                time.sleep(0.8)
                self.assertEqual(len(writes), 1)                                                 # sau khi ngừng bấm: ghi đúng một lần
            self.assertGreater(xlsx.stat().st_mtime_ns, before)
            svc.close()

    def test_close_flushes_pending_exports(self):
        from unittest import mock
        import webapp.service as svc_mod
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(svc_mod, "EXPORT_DELAY", 60):
            svc, run_id = self._service_with_run(tmp)
            xlsx = Path(tmp) / "out" / run_id / "ketqua.xlsx"
            before = xlsx.stat().st_mtime_ns
            svc.set_decision(run_id, 0, "Giữ lại")
            svc.close()                                                                         # tắt ứng dụng trước khi hết hạn chờ
            self.assertGreater(xlsx.stat().st_mtime_ns, before)

    def test_excel_open_in_another_program_does_not_break_hr_actions(self):
        import time
        from unittest import mock
        import webapp.service as svc_mod
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(svc_mod, "EXPORT_DELAY", 0.1):
            svc, run_id = self._service_with_run(tmp)
            with mock.patch.object(svc_mod.storage, "write_exports", side_effect=PermissionError("locked")):
                result = svc.set_decision(run_id, 0, "Mời phỏng vấn")
                self.assertEqual(result["hr_decision"], "Mời phỏng vấn")                         # thao tác vẫn thành công
                time.sleep(0.5)
            self.assertIn("ketqua.xlsx", svc.get_run(run_id)["export_error"])                    # nhưng HR được báo
            saved = json.loads((Path(tmp) / "out" / run_id / "rows.json").read_text(encoding="utf-8"))
            self.assertEqual(saved[0]["hr_decision"], "Mời phỏng vấn")
            svc.set_decision(run_id, 1, "Giữ lại")
            time.sleep(0.5)                                                                      # lần sau ghi được thì hết cảnh báo
            self.assertEqual(svc.get_run(run_id)["export_error"], "")
            svc.close()

    def test_deleting_a_run_cancels_its_pending_export(self):
        import time
        from unittest import mock
        import webapp.service as svc_mod
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(svc_mod, "EXPORT_DELAY", 0.2):
            svc, run_id = self._service_with_run(tmp)
            svc.set_decision(run_id, 0, "Giữ lại")
            svc.delete_run(run_id)
            time.sleep(0.6)
            self.assertFalse((Path(tmp) / "out" / run_id).exists())                              # thư mục không bị tạo lại
            svc.close()

    def test_old_upload_folders_from_a_crashed_session_are_removed_at_start(self):
        import os
        import tempfile as tf
        from webapp.service import UPLOAD_PREFIX
        stale = Path(tf.mkdtemp(prefix=UPLOAD_PREFIX))
        fresh = Path(tf.mkdtemp(prefix=UPLOAD_PREFIX))
        old = time.time() - 3 * 24 * 3600
        os.utime(stale, (old, old))
        with tempfile.TemporaryDirectory() as tmp:
            svc = Service(Path(tmp))
            try:
                self.assertFalse(stale.exists())                                  # quá 24 giờ: bị dọn
                self.assertTrue(fresh.exists())                                   # còn mới (có thể của một cửa sổ khác đang chạy): giữ
            finally:
                svc.close()
                import shutil
                shutil.rmtree(fresh, ignore_errors=True)

    def test_only_a_few_runs_are_kept_in_memory(self):
        import webapp.service as svc_mod
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(svc_mod, "MAX_CACHED_RUNS", 3):
            svc, first = self._service_with_run(tmp)
            from cv_agent import storage
            others = [storage.save_run([], svc._run(first)["rubric"], "x", base=Path(tmp) / "out").name for _ in range(5)]
            svc.runs.clear()
            for run_id in others:
                svc._run(run_id)
            self.assertLessEqual(len(svc.runs), 3)
            self.assertEqual(svc.get_run(first)["id"], first)                    # lần chạy đã bị bỏ khỏi bộ nhớ vẫn mở lại được từ đĩa
            svc.close()

    def test_unwritable_output_folder_is_reported_before_screening_starts(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocker = Path(tmp) / "la_mot_file"
            blocker.write_text("x", encoding="utf-8")
            svc = Service(blocker / "out")                                           # thư mục kết quả nằm "bên trong" một file: không tạo được
            svc.add_folder(str(CVS))
            with self.assertRaisesRegex(ServiceError, "Không ghi được vào thư mục lưu kết quả"):
                svc.start_screen(JD, "", list(svc.files), 70, 50, 30)
            svc.close()

    def test_safe_filename(self):
        from webapp.service import safe_filename
        self.assertEqual(safe_filename("a:b*c?.pdf"), "a_b_c_.pdf")
        self.assertEqual(safe_filename("..\\..\\evil.txt"), "evil.txt")
        self.assertEqual(safe_filename("CON.pdf"), "_CON.pdf")
        self.assertEqual(safe_filename(".pdf"), "cv.pdf")
        self.assertEqual(safe_filename("báo cáo (1).docx"), "báo cáo (1).docx")
        self.assertEqual(len(safe_filename("x" * 500 + ".pdf")), 120)
        self.assertTrue(safe_filename("x" * 500 + ".pdf").endswith(".pdf"))


if __name__ == "__main__":
    unittest.main()
