"""
http_handler.py — HTTP/1.1 request parser and response builder.

Parses raw TCP byte streams into structured HTTPRequest objects and
serialises HTTPResponse objects back to wire-format bytes.

Supports:
  - Methods: GET, POST, HEAD
  - Query-string parameter parsing
  - Connection: keep-alive / close
  - JSON and binary response bodies
"""

import json
from urllib.parse import parse_qs, urlparse
from dataclasses import dataclass, field


# ─────────────────────────────────────────────
#  Request
# ─────────────────────────────────────────────

@dataclass
class HTTPRequest:
    method: str
    path: str
    query: dict          # {key: value}  (single-value) or {key: [v1, v2]} (multi)
    headers: dict        # lower-cased header names
    body: bytes = b""
    keep_alive: bool = True

    def json(self) -> dict:
        """Decode the request body as JSON, returning {} on failure."""
        if not self.body:
            return {}
        try:
            return json.loads(self.body.decode("utf-8"))
        except Exception:
            return {}


def parse_request(raw: bytes) -> tuple["HTTPRequest | None", bool]:
    """
    Parse a raw HTTP/1.1 byte stream.

    Returns (HTTPRequest, keep_alive) on success, or (None, False) on failure.
    """
    try:
        # Split header block from optional body
        if b"\r\n\r\n" not in raw:
            return None, False

        header_block, body = raw.split(b"\r\n\r\n", 1)
        lines = header_block.decode("iso-8859-1").split("\r\n")

        # Request-Line: METHOD /path?q=1 HTTP/1.1
        parts = lines[0].split(" ", 2)
        if len(parts) < 2:
            return None, False

        method = parts[0].upper()
        raw_url = parts[1]

        parsed = urlparse(raw_url)
        path = parsed.path or "/"
        query_raw = parse_qs(parsed.query)
        query = {k: v[0] if len(v) == 1 else v for k, v in query_raw.items()}

        # Headers
        headers: dict[str, str] = {}
        for line in lines[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()

        keep_alive = headers.get("connection", "keep-alive").lower() != "close"

        return HTTPRequest(method, path, query, headers, body, keep_alive), keep_alive

    except Exception as exc:
        print(f"[HTTPHandler] Parse error: {exc}")
        return None, False


# ─────────────────────────────────────────────
#  Response
# ─────────────────────────────────────────────

_STATUS_PHRASES = {
    200: "OK",
    201: "Created",
    204: "No Content",
    400: "Bad Request",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    500: "Internal Server Error",
    503: "Service Unavailable",
}

_MIME_BY_EXT = {
    ".html": "text/html; charset=utf-8",
    ".css":  "text/css; charset=utf-8",
    ".js":   "application/javascript; charset=utf-8",
    ".json": "application/json",
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".ico":  "image/x-icon",
    ".svg":  "image/svg+xml",
    ".txt":  "text/plain; charset=utf-8",
}


def build_response(
    status: int = 200,
    body: "bytes | str | dict | list" = b"",
    content_type: str = "text/html; charset=utf-8",
    keep_alive: bool = True,
    extra_headers: "dict | None" = None,
) -> bytes:
    """
    Serialise an HTTP/1.1 response to bytes.

    - dict / list bodies are automatically JSON-encoded.
    - str bodies are UTF-8 encoded.
    """
    if isinstance(body, (dict, list)):
        body = json.dumps(body, indent=2).encode("utf-8")
        content_type = "application/json"
    elif isinstance(body, str):
        body = body.encode("utf-8")

    phrase = _STATUS_PHRASES.get(status, "Unknown")

    headers = {
        "Server":         "PyMTWebServer/1.0",
        "Content-Type":   content_type,
        "Content-Length": str(len(body)),
        "Connection":     "keep-alive" if keep_alive else "close",
    }
    if extra_headers:
        headers.update(extra_headers)

    header_lines = [f"HTTP/1.1 {status} {phrase}"]
    header_lines += [f"{k}: {v}" for k, v in headers.items()]
    header_bytes = ("\r\n".join(header_lines) + "\r\n\r\n").encode("iso-8859-1")

    return header_bytes + body


def mime_for_extension(ext: str) -> str:
    return _MIME_BY_EXT.get(ext.lower(), "application/octet-stream")
