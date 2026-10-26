import contextlib
import http.client
import io
import json
from pathlib import Path
import re
import threading
import unittest
from urllib.parse import quote
from types import SimpleNamespace
from unittest.mock import patch

from vrc_parsers import MediaType, ParseError, ParseResult
from vrc_parsers.web import BODY_LIMIT, LocalHandler, LocalServer, _safe_error, main


class MemoryConnection:
    """传入真实 HTTP 字节并记录响应，不建立或监听网络 socket。"""
    def __init__(self, incoming):
        self.input = io.BytesIO(incoming)
        self.output = bytearray()

    def makefile(self, mode, *args):
        return self.input

    def sendall(self, data):
        self.output.extend(data)

    def settimeout(self, value):
        pass


class LocalWebTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        async def parser(url, **kwargs):
            self.calls.append((url, kwargs))
            return ParseResult(platform="bilibili", media_type=MediaType.VIDEO,
                               title="fixture <script>not HTML</script>", author="test",
                               direct_url="https://cdn.bilivideo.com/fixture.mp4")
        self.server = SimpleNamespace(server_port=18765, local_hosts={"127.0.0.1:18765", "localhost:18765"},
                                      local_token="fixture-local-token", parse_media=parser, parse_lock=threading.Lock())
        self.origin = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        pass

    def wire(self, data):
        connection = MemoryConnection(data)
        LocalHandler(connection, ("127.0.0.1", 12345), self.server)
        head, _, body = bytes(connection.output).partition(b"\r\n\r\n")
        lines = head.decode("iso-8859-1").split("\r\n")
        status = int(lines[0].split()[1])
        headers = dict(line.split(": ", 1) for line in lines[1:])
        return status, headers, body

    def request(self, method, path, body=None, headers=None):
        headers = dict(headers or {})
        headers.setdefault("Host", f"127.0.0.1:{self.server.server_port}")
        body = body or b""
        if body:
            headers.setdefault("Content-Length", str(len(body)))
        raw = f"{method} {path} HTTP/1.0\r\n" + "".join(f"{k}: {v}\r\n" for k, v in headers.items()) + "\r\n"
        return self.wire(raw.encode("iso-8859-1") + body)

    def post(self, payload=None, overrides=None, raw=None):
        headers = {"Origin": self.origin, "X-VRC-Local-Token": self.server.local_token,
                   "Content-Type": "application/json"}
        if overrides:
            for key, value in overrides.items():
                if value is None:
                    headers.pop(key, None)
                else:
                    headers[key] = value
        body = raw if raw is not None else json.dumps(payload or {"url": "https://www.bilibili.com/video/BV1xx411c7mD"}).encode()
        return self.request("POST", "/api/parse", body=body, headers=headers)

    def test_page_and_assets_are_bounded_local_resources(self):
        status, headers, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(self.server.local_token.encode(), body)
        self.assertNotIn(b"{{LOCAL_TOKEN}}", body)
        self.assertIn("no-store", headers["Cache-Control"])
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        for path in ("/assets/app.css", "/assets/app.js", "/api/health"):
            self.assertEqual(self.request("GET", path)[0], 200)
        for path in ("/../pyproject.toml", "/%2e%2e/AGENTS.md", "/src/vrc_parsers/client.py", "/assets/../../README.md"):
            self.assertEqual(self.request("GET", path)[0], 404)
        status, _, body = self.request("HEAD", "/")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"")

    def test_post_success_and_cookie_not_in_result_or_logs(self):
        fake_cookie = "session=FAKE_LOCAL_ONLY"
        before = set(Path.cwd().iterdir())
        captured = io.StringIO()
        with contextlib.redirect_stderr(captured):
            status, headers, body = self.post({"url": "https://www.bilibili.com/video/BV1xx411c7mD", "cookie": fake_cookie, "bili_mode": "progressive"})
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])
        self.assertEqual(self.calls[0][1]["cookie"], fake_cookie)
        self.assertNotIn(fake_cookie.encode(), body)
        self.assertNotIn(fake_cookie, captured.getvalue())
        self.assertNotIn("Set-Cookie", headers)
        self.assertEqual(before, set(Path.cwd().iterdir()))

    def test_external_origin_missing_origin_and_bad_token_are_rejected(self):
        cases = [({"Origin": "https://example.invalid"}, 403), ({"Origin": "null"}, 403),
                 ({"Origin": None}, 403), ({"X-VRC-Local-Token": "wrong"}, 403),
                 ({"X-VRC-Local-Token": "é"}, 403), ({"X-VRC-Local-Token": None}, 403)]
        for headers, expected in cases:
            with self.subTest(headers=headers):
                self.assertEqual(self.post(overrides=headers)[0], expected)
        self.assertEqual(self.calls, [])

    def test_host_rebinding_and_preflight_are_rejected(self):
        self.assertEqual(self.request("GET", "/", headers={"Host": f"example.invalid:{self.server.server_port}"})[0], 403)
        status, headers, _ = self.request("OPTIONS", "/api/parse", headers={"Origin": "https://example.invalid"})
        self.assertEqual(status, 403)
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        raw = f"GET / HTTP/1.0\r\nHost: 127.0.0.1:{self.server.server_port}\r\nHost: example.invalid\r\n\r\n"
        self.assertEqual(self.wire(raw.encode())[0], 403)

    def test_payload_validation_and_bulk_rejection_precede_parser(self):
        for raw in (b"not-json", b"[]", b'{"url":1}', b'{"url":"x","unknown":true}'):
            self.assertEqual(self.post(raw=raw)[0], 400)
        self.assertEqual(self.post(overrides={"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.post(raw=b"x" * (BODY_LIMIT + 1))[0], 413)
        for url in ("https://music.163.com/playlist?id=1", "http://127.0.0.1/private", "https://www.bilibili.com.evil.invalid/video/BV1xx411c7mD"):
            self.assertEqual(self.post({"url": url})[0], 400)
        self.assertEqual(self.post({"url": "https://www.bilibili.com/video/BV1xx411c7mD", "cookie": "a\r\nb"})[0], 400)
        self.assertEqual(self.calls, [])

    def test_busy_parser_has_no_background_queue(self):
        started, finish = threading.Event(), threading.Event()
        async def slow(url, **kwargs):
            started.set()
            finish.wait(timeout=2)
            return ParseResult(platform="bilibili", media_type=MediaType.VIDEO, title="fixture", direct_url="https://cdn.bilivideo.com/f.mp4")
        self.server.parse_media = slow
        output = []
        first = threading.Thread(target=lambda: output.append(self.post()[0]))
        first.start()
        try:
            self.assertTrue(started.wait(timeout=1))
            self.assertEqual(self.post()[0], 429)
        finally:
            finish.set()
            first.join(timeout=3)
        self.assertEqual(output, [200])

    def test_errors_do_not_echo_credentials_and_lock_is_released(self):
        fake_cookie = "session=FAKE_LOCAL_ONLY"
        async def failing(url, **kwargs):
            raise ParseError("upstream: " + kwargs["cookie"])
        self.server.parse_media = failing
        self.assertEqual(self.post({"url": "https://www.bilibili.com/video/BV1xx411c7mD", "cookie": fake_cookie})[0], 502)
        _, _, body = self.post({"url": "https://www.bilibili.com/video/BV1xx411c7mD", "cookie": fake_cookie})
        self.assertNotIn(fake_cookie.encode(), body)
        self.assertFalse(self.server.parse_lock.locked())
        self.assertNotIn("FAKE_LOCAL_ONLY", _safe_error("err=" + quote("FAKE_LOCAL_ONLY"), fake_cookie))

    def test_prevalidation_errors_are_filtered_too(self):
        fake_cookie = "session=FAKE_PREVALIDATION_ONLY"
        with patch("vrc_parsers.web.choose_parser", side_effect=ParseError("invalid " + fake_cookie)):
            status, _, body = self.post({"url": "https://www.bilibili.com/video/BV1xx411c7mD", "cookie": fake_cookie})
        self.assertEqual(status, 400)
        self.assertNotIn(b"FAKE_PREVALIDATION_ONLY", body)
        self.assertEqual(self.calls, [])

    def test_invalid_result_url_is_not_exposed_as_media(self):
        for url in ("javascript:alert(1)", "http://127.0.0.1/private", "http://localhost/private", "https://u:p@example.invalid/media"):
            async def invalid(link, **kwargs):
                return ParseResult(platform="bilibili", media_type=MediaType.VIDEO, title="fixture", direct_url=url)
            self.server.parse_media = invalid
            status, _, body = self.post()
            self.assertEqual(status, 502)
            self.assertFalse(json.loads(body)["ok"])

    def test_process_tokens_are_unique_and_cli_cannot_bind_public(self):
        with patch("vrc_parsers.web.ThreadingHTTPServer.__init__") as constructor:
            first, second = LocalServer(8765), LocalServer(8765)
            self.assertNotEqual(first.local_token, second.local_token)
            self.assertEqual(constructor.call_args.args[0], ("127.0.0.1", 8765))
        for args in (["--host", "0.0.0.0"], ["--port", "0"], ["--port", "99999"]):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(args)


class RealLoopbackTests(unittest.TestCase):
    def test_tcp_health_and_parse(self):
        async def parser(url, **kwargs):
            return ParseResult(platform="bilibili", media_type=MediaType.VIDEO, title="fixture", direct_url="https://cdn.bilivideo.com/fixture.mp4")
        try:
            server = LocalServer(0, parser=parser)
        except PermissionError:
            self.skipTest("宿主不允许真实回环监听；内存 HTTP 处理回归另行执行，不能视为 TCP 验收通过")
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        thread.start()
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        try:
            connection.request("GET", "/api/health")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertTrue(json.loads(response.read())["ok"])
            connection.close()
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            body = json.dumps({"url": "https://www.bilibili.com/video/BV1xx411c7mD"})
            connection.request("POST", "/api/parse", body, {"Origin": f"http://127.0.0.1:{server.server_port}", "X-VRC-Local-Token": server.local_token, "Content-Type": "application/json"})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertTrue(json.loads(response.read())["ok"])
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
