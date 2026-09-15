# -*- coding: utf-8 -*-
"""HTTP 基础设施：只监听 127.0.0.1，标准库实现，支持 SSE 长连接。

为什么手写而不用 Flask/FastAPI：平台要「拷给同事、双击就能跑」，
不能要求对方先配 Python 环境装一堆包。标准库够用了。
"""
import json
import mimetypes
import os
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from ..core import config

STATIC_DIR = os.path.join(config.PLATFORM_ROOT, "web")

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}


class SSE:
    """handler 返回这个对象时，服务端按 Server-Sent Events 逐条推送。"""

    def __init__(self, gen, keepalive=15):
        self.gen = gen
        self.keepalive = keepalive


class Request:
    def __init__(self, method, path, query, body, headers):
        self.method = method
        self.path = path
        self.query = query
        self.body = body
        self.headers = headers

    def q(self, key, default=None):
        v = self.query.get(key)
        return v[0] if v else default

    def qint(self, key, default=0):
        try:
            return int(self.q(key, default))
        except Exception:
            return default

    def qbool(self, key, default=False):
        v = self.q(key)
        if v is None:
            return default
        return str(v).lower() in ("1", "true", "yes", "on")


def _json_bytes(obj):
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


def make_handler(routes, quiet=True):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        # -------------------------------------------------- 基础
        def log_message(self, fmt, *args):
            if not quiet:
                super().log_message(fmt, *args)

        def _send(self, code, body, ctype="application/json; charset=utf-8",
                  extra=None):
            if isinstance(body, (dict, list)):
                body = _json_bytes(body)
            if isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _static(self, rel):
            """静态文件：只服务 web/ 目录内的文件，防目录穿越。"""
            rel = rel.strip("/") or "index.html"
            full = os.path.abspath(os.path.join(STATIC_DIR, rel))
            if not full.startswith(os.path.abspath(STATIC_DIR)):
                return False
            if not os.path.isfile(full):
                return False
            ext = os.path.splitext(full)[1].lower()
            ctype = MIME.get(ext) or mimetypes.guess_type(full)[0] or "application/octet-stream"
            try:
                with open(full, "rb") as fh:
                    data = fh.read()
            except Exception:
                return False
            self._send(200, data, ctype)
            return True

        # -------------------------------------------------- 请求解析
        def _read_body(self):
            length = int(self.headers.get("Content-Length") or 0)
            if not length:
                return {}
            raw = self.rfile.read(length)
            try:
                return json.loads(raw.decode("utf-8"))
            except Exception:
                return {}

        # -------------------------------------------------- 路由分发
        def _dispatch(self, method):
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)
            body = self._read_body() if method == "POST" else {}

            if method == "GET" and not path.startswith("/api/"):
                if self._static(path):
                    return

            req = Request(method, path, query, body, self.headers)
            for m, pattern, fn in routes:
                if m != method:
                    continue
                mt = pattern.match(path) if hasattr(pattern, "match") else None
                if not mt:
                    continue
                try:
                    kwargs = mt.groupdict()
                    out = fn(req, **kwargs) if kwargs else fn(req)
                except Exception as e:
                    out = {"ok": False, "error": str(e),
                           "trace": traceback.format_exc().splitlines()[-3:]}
                if isinstance(out, SSE):
                    return self._sse(out)
                if isinstance(out, tuple) and len(out) == 3:
                    return self._send(*out)
                return self._send(200, out)

            if path.startswith("/api/"):
                return self._send(404, {"ok": False, "error": "接口不存在：" + path})
            return self._send(404, {"ok": False, "error": "页面不存在"})

        def _sse(self, sse):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()

            def write(event, data):
                payload = json.dumps(data, ensure_ascii=False)
                self.wfile.write(("event: %s\ndata: %s\n\n" % (event, payload)).encode("utf-8"))
                self.wfile.flush()

            alive = [True]
            try:
                for item in sse.gen:
                    if not alive[0]:
                        break
                    if isinstance(item, tuple) and len(item) == 2:
                        write(item[0], item[1])
                    else:
                        write("message", item)
                write("end", {"done": True})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as e:
                try:
                    write("error", {"error": str(e)})
                except Exception:
                    pass
            finally:
                alive[0] = False

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

    return Handler


def create_server(routes, host=None, port=None, quiet=True):
    c = config.load()
    host = host or c["server"]["host"]
    port = port or c["server"]["port"]
    srv = ThreadingHTTPServer((host, int(port)), make_handler(routes, quiet=quiet))
    srv.daemon_threads = True
    return srv


def serve_forever(routes, host=None, port=None, on_ready=None, quiet=True):
    srv = create_server(routes, host, port, quiet=quiet)
    c = config.load()
    url = "http://%s:%s/" % (srv.server_address[0], srv.server_address[1])
    if on_ready:
        on_ready(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            srv.server_close()
        except Exception:
            pass
    return url
