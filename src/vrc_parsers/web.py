"""本机网页入口。固定绑定回环，不提供媒体代理或远程服务。"""
from __future__ import annotations

import argparse
import asyncio
import hmac
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
import ipaddress
import json
import re
import secrets
import threading
from urllib.parse import quote, urlsplit

from .base import ParseError
from .client import choose_parser, parse_one
from .utils import cookie_str_to_dict

BODY_LIMIT = 32768
ASSETS = {
    "/assets/app.css": ("app.css", "text/css; charset=utf-8"),
    "/assets/app.js": ("app.js", "text/javascript; charset=utf-8"),
}
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
       "base-uri 'none'; form-action 'self'; frame-ancestors 'none'")


def _safe_error(message: str, cookie: str) -> str:
    values = [cookie, *cookie_str_to_dict(cookie).values()] if cookie else []
    if (not isinstance(message, str) or len(message) > 240
            or re.search(r"https?://|(?:cookie|authorization)\s*[:=]", message, re.I)
            or any(value and (value in message or quote(value, safe="") in message) for value in values)):
        return "解析未成功，请检查链接、访问权限或稍后重试"
    return message


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, port: int = 8765, parser=parse_one):
        self.local_token = secrets.token_urlsafe(32)
        self.parse_media = parser
        self.parse_lock = threading.Lock()
        super().__init__(("127.0.0.1", port), LocalHandler)

    @property
    def local_hosts(self):
        port = self.server_port
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        return hosts | {"127.0.0.1", "localhost"} if port == 80 else hosts


class LocalHandler(BaseHTTPRequestHandler):
    server_version = "VRCHATParserLocal/0.2"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *args):
        # 不记录 URL、请求正文、Cookie 或解析结果。
        pass

    def _send(self, status: int, body: bytes, content_type="application/json; charset=utf-8"):
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass

    def _json(self, status: int, value: dict):
        self._send(status, json.dumps(value, ensure_ascii=False).encode("utf-8"))

    def _error(self, status: int, message: str):
        self._json(status, {"ok": False, "error": message})

    def _local_request(self):
        hosts = self.headers.get_all("Host", [])
        if len(hosts) != 1 or hosts[0].lower() not in self.server.local_hosts:
            self._error(403, "仅允许通过本机地址访问")
            return False
        try:
            parts = urlsplit(self.path)
        except ValueError:
            self._error(400, "请求地址格式不正确")
            return False
        if parts.scheme or parts.netloc:
            self._error(400, "请求地址格式不正确")
            return False
        return True

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self._local_request():
            return
        path = urlsplit(self.path).path
        if path == "/api/health":
            self._json(200, {"ok": True, "service": "VRCHAT-Parser Local"})
            return
        try:
            resources = files("vrc_parsers").joinpath("web_assets")
            if path == "/":
                page = resources.joinpath("index.html").read_text(encoding="utf-8")
                if page.count("{{LOCAL_TOKEN}}") != 1:
                    raise ValueError("Invalid local page resource")
                page = page.replace("{{LOCAL_TOKEN}}", html.escape(self.server.local_token, quote=True))
                self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
            elif path in ASSETS:
                name, content_type = ASSETS[path]
                self._send(200, resources.joinpath(name).read_bytes(), content_type)
            else:
                self._error(404, "页面不存在")
        except (OSError, ValueError):
            self._error(500, "页面资源缺失，请重新安装本项目")

    def do_OPTIONS(self):
        self._error(403, "不接受跨站请求")

    def do_POST(self):
        if not self._local_request():
            return
        if self.path != "/api/parse":
            self._error(404, "接口不存在")
            return
        origins = self.headers.get_all("Origin", [])
        expected_origin = "http://" + self.headers["Host"].lower()
        if origins != [expected_origin]:
            self._error(403, "请从本机网页发起解析")
            return
        tokens = self.headers.get_all("X-VRC-Local-Token", [])
        if (len(tokens) != 1 or not tokens[0].isascii()
                or not hmac.compare_digest(tokens[0], self.server.local_token)):
            self._error(403, "页面已失效，请刷新后重试")
            return
        if self.headers.get_content_type() != "application/json" or self.headers.get("Transfer-Encoding"):
            self._error(415, "仅接受 JSON 请求")
            return
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1 or not re.fullmatch(r"[1-9][0-9]{0,8}", lengths[0]):
            self._error(400, "请求正文长度不正确")
            return
        size = int(lengths[0])
        if size > BODY_LIMIT:
            self._error(413, "请求内容过长")
            return
        try:
            raw = self.rfile.read(size)
            if len(raw) != size:
                raise ValueError
            data = json.loads(raw)
            if not isinstance(data, dict) or set(data) - {"url", "cookie", "bili_mode"}:
                raise ValueError
            url, cookie, mode = data.get("url"), data.get("cookie", ""), data.get("bili_mode", "progressive")
            if not isinstance(url, str) or not isinstance(cookie, str) or not isinstance(mode, str):
                raise ValueError
            if len(cookie) > 16384 or any(c in cookie for c in "\r\n\0") or mode not in {"progressive", "authenticated", "dash"}:
                raise ValueError
            choose_parser(url, cookie=cookie, bili_mode=mode)
        except TimeoutError:
            self._error(408, "读取请求超时，请重试")
            return
        except ParseError as exc:
            self._error(400, _safe_error(exc.message, cookie))
            return
        except (ValueError, TypeError, UnicodeError):
            self._error(400, "请输入有效的单条链接与解析选项")
            return
        if not self.server.parse_lock.acquire(blocking=False):
            self._error(429, "正在处理另一条链接，请稍后重试")
            return
        try:
            async def run():
                return await asyncio.wait_for(self.server.parse_media(url, cookie=cookie, bili_mode=mode), timeout=35)
            result = asyncio.run(run())
            parts = urlsplit(result.direct_url or "")
            if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username is not None or parts.password is not None:
                raise ValueError
            try:
                address = ipaddress.ip_address(parts.hostname)
            except ValueError:
                if parts.hostname == "localhost" or parts.hostname.endswith((".localhost", ".local")):
                    raise ValueError
            else:
                if not address.is_global:
                    raise ValueError
            self._json(200, {"ok": True, "result": result.to_dict()})
        except ParseError as exc:
            self._error(502, _safe_error(exc.message, cookie))
        except Exception:
            self._error(502, "解析未成功，请检查链接或稍后重试")
        finally:
            self.server.parse_lock.release()


def main(argv=None):
    parser = argparse.ArgumentParser(description="启动 VRCHAT-Parser 本机网页（仅回环访问）")
    parser.add_argument("--port", type=int, default=8765, help="本机端口，默认 8765")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("端口必须在 1 到 65535 之间")
    try:
        server = LocalServer(args.port)
    except OSError:
        parser.exit(1, "无法启动本机网页，端口可能已被占用；请用 --port 换一个端口。\n")
    print(f"本机网页：http://127.0.0.1:{server.server_port}", flush=True)
    print("按 Ctrl+C 停止。此服务不向局域网或公网开放。", flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
