"""Đọc body multipart/form-data (tải nhiều file CV) chỉ bằng thư viện chuẩn, không cần cài thêm gói."""
from email import policy
from email.parser import BytesParser


class MultipartError(ValueError):
    pass


def parse_multipart(content_type: str, body: bytes) -> list[tuple[str, str, bytes]]:
    """-> [(tên trường, tên file ('' nếu không phải file), nội dung bytes)]"""
    if not content_type or "multipart/form-data" not in content_type.lower() or "boundary=" not in content_type.lower():
        raise MultipartError("Yêu cầu không phải multipart/form-data")
    header = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8")
    try:
        msg = BytesParser(policy=policy.HTTP).parsebytes(header + body)
    except Exception as e:                                         # thư viện email có thể ném nhiều loại lỗi với dữ liệu hỏng
        raise MultipartError(f"Không đọc được dữ liệu tải lên: {type(e).__name__}") from e
    if not msg.is_multipart():
        raise MultipartError("Body multipart rỗng hoặc sai định dạng")
    out = []
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition") or ""
        filename = part.get_filename() or ""
        payload = part.get_payload(decode=True)
        if payload is None:
            payload = (part.get_content() or "").encode("utf-8") if not part.is_multipart() else b""
        out.append((name, filename, payload))
    return out
