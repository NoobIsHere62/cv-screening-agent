"""Mở giao diện sàng lọc CV trong trình duyệt:   python serve.py   [--port 8765] [--no-browser]"""
import argparse

from cv_agent.textutil import safe_console
from webapp.server import serve


def main(argv=None) -> None:
    safe_console()
    ap = argparse.ArgumentParser(description="Giao diện web sàng lọc CV (chạy cục bộ, không cần internet)")
    ap.add_argument("--port", type=int, default=None, help="cổng (mặc định: 8765 hoặc cổng trống kế tiếp)")
    ap.add_argument("--no-browser", action="store_true", help="không tự mở trình duyệt")
    args = ap.parse_args(argv)
    serve(port=args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
