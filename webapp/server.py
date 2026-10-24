"""Máy chủ HTTP cục bộ cho giao diện web (chỉ dùng thư viện chuẩn).

Bảo mật: chỉ lắng nghe 127.0.0.1; mọi lệnh gọi /api cần mã thông báo ngẫu nhiên (tạo mỗi lần khởi động và chỉ nhúng vào trang chủ)
và Host/Origin phải là localhost, để một trang web bất kỳ trong trình duyệt không thể gọi vào ứng dụng (CSRF / DNS rebinding).
"""
import json
import mimetypes
import re
import secrets
import socket
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse

from cv_agent import __version__
from cv_agent.pipeline import DEFAULT_WORKERS

from .multipart import MultipartError, parse_multipart
from .service import Service, ServiceError

STATIC = Path(__file__).resolve().parent / "static"
MAX_BODY = 600 * 1024 * 1024
LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]"}


def _host_ok(value: Optional[str]) -> bool:
    """Host/Origin phải là localhost (chống trang web khác gọi vào ứng dụng). Không có giá trị thì cho qua (lệnh gọi không từ trình duyệt)."""
    if not value:
        return True
    host = re.sub(r"^[a-z][a-z0-9+.-]*://", "", value.strip().lower()).split("/")[0]
    host = host.split("]")[0] + "]" if host.startswith("[") else host.split(":")[0]
    return host in LOCAL_HOSTS

_BAD = "Dữ liệu gửi lên không hợp lệ."


def _text(value, default: str = "") -> str:
    """Trường chữ trong JSON: thiếu/null -> mặc định; sai kiểu (số, danh sách...) -> lỗi 400 thay vì lỗi 500 bên trong."""
    if value is None:
        return default
    if not isinstance(value, str):
        raise ServiceError(_BAD)
    return value


def _number(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ServiceError("Ngưỡng điểm không hợp lệ.")
    try:
        return float(value)
    except ValueError:
        raise ServiceError("Ngưỡng điểm không hợp lệ.") from None


def _int(value, default: int, lo: int, hi: int) -> int:
    if value is None or isinstance(value, bool):
        return default
    try:
        return max(lo, min(int(value), hi))
    except (TypeError, ValueError, OverflowError):
        return default


def _list(value, kind) -> list:
    """Danh sách mà mọi phần tử đều là `kind` (str hoặc int, không nhận bool)."""
    if value is None:
        return []
    if not isinstance(value, list) or any(isinstance(x, bool) or not isinstance(x, kind) for x in value):
        raise ServiceError(_BAD)
    return value


class App(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, service: Service):
        super().__init__(address, Handler)
        self.service = service
        self.token = secrets.token_urlsafe(24)


class Handler(BaseHTTPRequestHandler):
    server: App
    protocol_version = "HTTP/1.1"
    server_version = "CVScreening"
    timeout = 300                                         # giây: kết nối im lặng quá lâu (trình duyệt đã đóng, treo giữa chừng) thì giải phóng luồng

    def log_message(self, fmt, *args):                    # không in log từng request ra console
        pass

    # ---------------------------------------------------------------- tiện ích phản hồi
    def _send(self, status: int, body: bytes, content_type: str, extra: Optional[dict] = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if status >= 400:                                   # lỗi có thể xảy ra trước khi đọc hết body: đóng kết nối để không lẫn sang request sau
            self.send_header("Connection", "close")
            self.close_connection = True
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, status: int = 200) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _error(self, status: int, message: str) -> None:
        self._json({"error": message}, status)

    def _read_body(self) -> bytes:
        return self._raw

    def _json_body(self) -> dict:
        raw = self._read_body()
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ServiceError("Dữ liệu gửi lên không hợp lệ.") from None
        if not isinstance(data, dict):
            raise ServiceError("Dữ liệu gửi lên không hợp lệ.")
        return data

    # ---------------------------------------------------------------- kiểm tra an toàn
    def _guard(self, query: dict) -> bool:
        if not _host_ok(self.headers.get("Host")) or not _host_ok(self.headers.get("Origin")):
            self._error(403, "Chỉ cho phép truy cập từ chính máy này.")
            return False
        token = self.headers.get("X-CV-Token") or (query.get("token") or [""])[0]
        # so sánh dạng bytes: compare_digest với chuỗi có ký tự ngoài ASCII ném TypeError (thành lỗi 500 thay vì 403)
        if not secrets.compare_digest((token or "").encode("utf-8", "replace"), self.server.token.encode("ascii")):
            self._error(403, "Thiếu hoặc sai mã truy cập. Hãy tải lại trang.")
            return False
        return True

    # ---------------------------------------------------------------- định tuyến
    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def do_PUT(self):                                      # không hỗ trợ, nhưng trả lỗi JSON gọn thay vì trang lỗi HTML 501
        self._dispatch("PUT")

    do_PATCH = do_PUT

    def _dispatch(self, method: str) -> None:
        url = urlparse(self.path)
        path, query = unquote(url.path), parse_qs(url.query)
        # Luôn đọc hết body trước khi trả lời (kể cả khi sắp báo lỗi): nếu để thừa dữ liệu chưa đọc, đóng kết nối sẽ làm trình
        # duyệt nhận được "connection reset" thay vì thông báo lỗi.
        self._raw = b""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0:                                         # Content-Length âm/không hợp lệ: rfile.read(-1) sẽ chờ tới khi đóng kết nối
            self.close_connection = True
            return self._error(400, "Content-Length không hợp lệ.")
        if length > MAX_BODY:
            self.close_connection = True
            return self._error(413, "Dữ liệu tải lên quá lớn.")
        if length:
            try:
                self._raw = self.rfile.read(length)
            except OSError:                                    # hết thời gian chờ / trình duyệt đóng kết nối giữa chừng: bỏ yêu cầu, không in traceback
                self.close_connection = True
                return
        try:
            if not path.startswith("/api/"):
                return self._static(path) if method == "GET" else self._error(405, "Không hỗ trợ")
            if not self._guard(query):
                return
            self._api(method, path, query)
        except ServiceError as e:
            self._error(400, str(e))
        except MultipartError as e:
            self._error(400, str(e))
        except (ConnectionError, TimeoutError):                # trình duyệt đã đóng trang giữa chừng
            self.close_connection = True
        except Exception as e:                                # lỗi bất ngờ: báo gọn, không văng traceback cho người dùng
            try:
                self._error(500, f"Lỗi nội bộ: {type(e).__name__}: {e}")
            except OSError:
                self.close_connection = True

    def _static(self, path: str) -> None:
        if path in ("", "/"):
            page = (STATIC / "index.html").read_text(encoding="utf-8")
            page = page.replace("{{TOKEN}}", self.server.token).replace("{{VERSION}}", __version__)
            return self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
        root = STATIC.resolve()
        try:
            target = (root / path.lstrip("/")).resolve()
            # chặn ../ thoát khỏi thư mục static. Dùng is_relative_to chứ không so tiền tố chuỗi: "static_x" cũng bắt đầu bằng "static"
            allowed = target.is_relative_to(root) and target.is_file()
        except (ValueError, OSError):                         # ký tự NUL, tên không hợp lệ trên Windows...
            allowed = False
        if not allowed:
            return self._error(404, "Không tìm thấy")
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "image/svg+xml"):
            ctype += "; charset=utf-8"
        self._send(200, target.read_bytes(), ctype)

    def _api(self, method: str, path: str, query: dict) -> None:
        svc = self.server.service
        parts = [p for p in path.split("/") if p][1:]            # bỏ "api"
        route = (method, *parts[:2]) if parts else (method,)

        if method == "GET" and parts == ["bootstrap"]:
            return self._json({**svc.bootstrap(), "files": svc.public_files(), "version": __version__})
        if method == "POST" and parts == ["jd", "filter"]:
            return self._json(svc.filter_jd(_text(self._json_body().get("text"))))
        if method == "POST" and parts == ["jd", "upload"]:
            files = [f for f in parse_multipart(self.headers.get("Content-Type", ""), self._read_body()) if f[1]]
            if not files:
                raise ServiceError("Chưa chọn file JD.")
            return self._json({"text": svc.read_jd_file(files[0][1], files[0][2])})
        if method == "POST" and parts == ["files"]:
            items = [(name, data) for _, name, data in parse_multipart(self.headers.get("Content-Type", ""), self._read_body()) if name]
            if not items:
                raise ServiceError("Chưa chọn file nào.")
            added, rejected = svc.add_uploads(items)
            return self._json({"files": added, "rejected": rejected})
        if method == "DELETE" and len(parts) == 2 and parts[0] == "files":
            svc.remove_file(parts[1])
            return self._json({"ok": True})
        if method == "DELETE" and parts == ["files"]:
            svc.clear_files()
            return self._json({"ok": True})
        if method == "POST" and parts == ["folder"]:
            body = self._json_body()
            return self._json({"files": svc.add_folder(_text(body.get("path")), bool(body.get("recursive")))})
        if method == "POST" and parts == ["sample"]:
            return self._json(svc.load_sample())
        if method == "POST" and parts == ["screen"]:
            b = self._json_body()
            fit, maybe, reject = (_number(b.get(k)) for k in ("fit", "maybe", "reject"))
            job = svc.start_screen(_text(b.get("jd_text")), _text(b.get("core_jd")), _list(b.get("file_ids"), str), fit, maybe, reject,
                                   bool(b.get("ocr", True)), _int(b.get("workers"), DEFAULT_WORKERS, 1, 8))
            return self._json({"job_id": job})
        if method == "GET" and len(parts) == 2 and parts[0] == "jobs":
            return self._json(svc.job(parts[1]))
        if method == "POST" and len(parts) == 3 and parts[0] == "jobs" and parts[2] == "cancel":
            return self._json(svc.cancel_job(parts[1]))
        if method == "GET" and parts == ["runs"]:
            return self._json({"runs": svc.list_runs()})
        if route[:2] == (method, "runs") and len(parts) >= 2:
            run_id = parts[1]
            if method == "GET" and len(parts) == 2:
                return self._json(svc.get_run(run_id))
            if method == "DELETE" and len(parts) == 2:
                svc.delete_run(run_id)
                return self._json({"ok": True})
            if method == "POST" and parts[2:] == ["decision"]:
                b = self._json_body()
                index = b.get("index")
                if isinstance(index, bool) or not isinstance(index, int):
                    raise ServiceError("Không tìm thấy ứng viên.")
                decision = b.get("decision")
                return self._json(svc.set_decision(run_id, index, _text(decision) if decision is not None else None,
                                                   _text(b.get("note")) if b.get("note") is not None else None))
            if method == "POST" and parts[2:] == ["bulk"]:
                b = self._json_body()
                return self._json({"changed": svc.bulk_decision(run_id, _list(b.get("indices"), int), _text(b.get("decision")))})
            if method == "POST" and parts[2:] == ["rejudge"]:
                b = self._json_body()
                fit, maybe, reject = (_number(b.get(k)) for k in ("fit", "maybe", "reject"))
                return self._json(svc.rejudge_run(run_id, fit, maybe, reject))
            if method == "GET" and parts[2:] == ["report"]:
                scope = (query.get("scope") or ["suitable"])[0]
                return self._send(200, svc.report_html(run_id, scope).encode("utf-8"), "text/html; charset=utf-8")
            if method == "GET" and parts[2:] == ["emails"]:
                return self._json(svc.emails(run_id, (query.get("scope") or ["auto"])[0]))
            if method == "GET" and len(parts) == 4 and parts[2] == "export":
                data, filename, ctype = svc.export(run_id, parts[3])
                return self._send(200, data, ctype, {"Content-Disposition": f'attachment; filename="{filename}"'})
        self._error(404, "Không tìm thấy")


def find_free_port(preferred: int = 8765) -> int:
    for port in range(preferred, preferred + 50):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError("Không tìm được cổng trống")


def serve(port: Optional[int] = None, open_browser: bool = True, output_dir: Optional[Path] = None) -> None:
    port = port or find_free_port()
    app = App(("127.0.0.1", port), Service(output_dir))
    url = f"http://localhost:{port}/"
    print(f"CV Screening v{__version__} đang chạy tại {url}\n(Đóng cửa sổ này hoặc bấm Ctrl+C để tắt. Dữ liệu CV không rời khỏi máy.)")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        app.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.server_close()
        app.service.close()


if __name__ == "__main__":
    serve(open_browser="--no-browser" not in sys.argv)
