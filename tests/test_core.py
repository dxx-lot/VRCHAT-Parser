import asyncio
import hashlib
import json
import sys
import unittest
from unittest.mock import patch

import httpx

from vrc_parsers import ParseError, parse_one
from vrc_parsers.bilibili import BilibiliParser, _media_candidates, _pick_dash_avc, _wbi_sign
from vrc_parsers.client import choose_parser, _request_policy
from vrc_parsers.douyin import DouyinParser
from vrc_parsers.douyin_live import DouyinLiveParser
from vrc_parsers.bilibili_live import BilibiliLiveParser
from vrc_parsers.douyu_live import DouyuLiveParser, auth_value
from vrc_parsers.huya_live import HuyaLiveParser, hls_url, rewrite_manifest
from vrc_parsers.kugou import KugouParser, sign_parameters


def response(request, payload=None, text=None, headers=None):
    return httpx.Response(200, json=payload, text=text, headers=headers, request=request)


class InputTests(unittest.TestCase):
    def test_exact_domains_and_single_items(self):
        cases = {
            "https://www.bilibili.com/video/BV1xx411c7mD": "bilibili",
            "https://live.bilibili.com/123": "bilibili_live",
            "https://www.douyin.com/video/1234567890123456789": "douyin",
            "https://live.douyin.com/123": "douyin_live",
            "https://music.163.com/song?id=1": "netease",
            "https://y.qq.com/n/ryqq/songDetail/example": "qqmusic",
            "https://www.kugou.com/song/#hash=" + "a" * 32: "kugou",
            "https://www.huya.com/123": "huya_live",
            "https://www.douyu.com/123": "douyu_live",
        }
        for url, platform in cases.items():
            with self.subTest(url=url):
                self.assertEqual(choose_parser(url).platform, platform)

    def test_reject_bulk_and_unsupported_targets(self):
        for url in (
            "https://music.163.com/playlist?id=1", "https://music.163.com/#/playlist?id=1",
            "https://y.qq.com/n/ryqq/playlist/1", "https://www.kugou.com/yy/special/single/1.html",
            "https://www.bilibili.com.evil.invalid/video/BV1xx411c7mD",
            "https://example.invalid/?url=https://www.bilibili.com/video/BV1xx411c7mD",
            "http://127.0.0.1/video.mp4", "file:///etc/passwd", "https://u:p@www.bilibili.com/video/BV1xx411c7mD",
        ):
            with self.subTest(url=url), self.assertRaises(ParseError):
                choose_parser(url)

    def test_bili_modes_require_explicit_credentials(self):
        with self.assertRaises(ParseError):
            BilibiliParser(mode="dash")
        with self.assertRaises(ParseError):
            BilibiliParser(mode="unknown")

    def test_bili_candidate_filter_and_codec(self):
        self.assertEqual(_media_candidates({"url": "https://pcdn.invalid/a.mp4", "backup_url": ["https://cdn.bilivideo.com/a.mp4"]}), ["https://cdn.bilivideo.com/a.mp4"])
        video, audio = _pick_dash_avc({"dash": {"video": [
            {"id": 127, "codecid": 7, "baseUrl": "https://cdn.bilivideo.com/8k"},
            {"id": 120, "codecid": 12, "baseUrl": "https://cdn.bilivideo.com/hevc"},
            {"id": 80, "codecid": 7, "baseUrl": "https://cdn.bilivideo.com/avc"}],
            "audio": [{"bandwidth": 128000, "baseUrl": "https://cdn.bilivideo.com/audio"}]}})
        self.assertEqual(video["id"], 80)
        self.assertEqual(audio["bandwidth"], 128000)

    def test_protocol_signing_is_deterministic(self):
        with patch("vrc_parsers.bilibili.time.time", return_value=1700000000):
            signed = _wbi_sign({"b": "!x", "a": 1}, "fixture-key")
        expected = hashlib.md5(b"a=1&b=x&wts=1700000000fixture-key").hexdigest()
        self.assertEqual(signed["w_rid"], expected)
        self.assertEqual(sign_parameters({"b": 2, "a": 1, "empty": ""}, "fixture"), hashlib.md5(b"fixturea=1b=2fixture").hexdigest())
        enc = {"enc_time": 1, "key": "fixture", "rand_str": "seed", "is_special": 0}
        step = hashlib.md5(b"seedfixture").hexdigest()
        self.assertEqual(auth_value("1", 1700000000, enc), hashlib.md5((step + "fixture11700000000").encode()).hexdigest())
        with self.assertRaises(ParseError):
            auth_value("1", 1, {**enc, "enc_time": 10001})


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_credentials_are_never_sent_over_plain_http(self):
        sent = []
        def handler(request):
            sent.append(request)
            return response(request, {})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                     event_hooks={"request": [_request_policy]}) as session:
            for headers in ({"Cookie": "fixture=FAKE_AUDIT_ONLY"},
                            {"Authorization": "Bearer FAKE_AUDIT_ONLY"}):
                with self.subTest(header=next(iter(headers))), self.assertRaises(ParseError):
                    await session.get("http://c.y.qq.com/fixture", headers=headers)
            self.assertEqual(sent, [])
            await session.get("https://c.y.qq.com/fixture", headers={"Cookie": "fixture=FAKE_AUDIT_ONLY"})
            await session.get("http://c.y.qq.com/fixture")
            self.assertEqual(len(sent), 2)

    async def test_redirect_to_plain_http_cannot_forward_cookies(self):
        sent = []
        def handler(request):
            sent.append(request)
            if request.url.path == "/start":
                return httpx.Response(302, headers={
                    "Location": "http://c.y.qq.com/target",
                    "Set-Cookie": "fixture=FAKE_AUDIT_ONLY; Path=/",
                })
            return response(request, {})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True,
                                     event_hooks={"request": [_request_policy]}) as session:
            with self.assertRaises(ParseError):
                await session.get("https://c.y.qq.com/start")
            self.assertEqual(len(sent), 1)
            self.assertEqual(sent[0].url.scheme, "https")

    async def test_outgoing_host_policy(self):
        await _request_policy(httpx.Request("GET", "https://api.bilibili.com/test"))
        for url in ("http://127.0.0.1/", "https://bilibili.com.evil.invalid/", "https://user:pass@api.bilibili.com/test"):
            with self.assertRaises(ParseError):
                await _request_policy(httpx.Request("GET", url))

    async def test_bili_anonymous_and_dash_without_site_state(self):
        seen = []
        def handler(request):
            seen.append(request)
            if request.url.path.endswith("/view"):
                data = {"code": 0, "data": {"cid": 42, "title": "fixture", "owner": {"name": "test"}}}
            elif request.url.path.endswith("/nav"):
                data = {"data": {"isLogin": True}}
            elif request.url.params.get("fnval") == "4048":
                data = {"code": 0, "data": {"dash": {"video": [{"id": 120, "codecid": 7, "baseUrl": "https://cdn.bilivideo.com/video"}], "audio": [{"baseUrl": "https://cdn.bilivideo.com/audio"}]}}}
            else:
                data = {"code": 0, "data": {"quality": 64, "durl": [{"url": "https://cdn.bilivideo.com/fixture.mp4"}]}}
            return response(request, data)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as session:
            plain = await BilibiliParser(cookie="fixture-cookie").parse("https://www.bilibili.com/video/BV1xx411c7mD", session)
            self.assertTrue(all(not r.headers.get("cookie") for r in seen))
            full = await BilibiliParser(cookie="fixture-cookie", mode="dash").parse("https://www.bilibili.com/video/BV1xx411c7mD", session)
        self.assertEqual(plain.direct_url, "https://cdn.bilivideo.com/fixture.mp4")
        self.assertEqual(full.extra["dash"]["video_url"], "https://cdn.bilivideo.com/video")
        self.assertNotIn("renew_token", plain.extra)
        self.assertNotIn("fixture-cookie", json.dumps(full.to_dict()))

    async def test_douyin_video_router_payload(self):
        item = {"desc": "fixture", "author": {"nickname": "test"}, "video": {"download_addr": {"url_list": ["https://media.douyinvod.com/playwm/?id=1"]}, "duration": 5000}}
        body = "<script>_ROUTER_DATA = " + json.dumps({"loaderData": {"video/page": {"videoInfoRes": {"item_list": [item]}}}}) + "</script>"
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: response(req, text=body))) as session:
            result = await DouyinParser().parse("https://www.douyin.com/video/1234567890123456789", session)
        self.assertEqual(result.title, "fixture")
        self.assertNotIn("playwm", result.direct_url)

    async def test_bilibili_live(self):
        def handler(request):
            data = {"live_status": 1, "room_id": 123, "title": "fixture"} if "get_info" in request.url.path else {"durl": [{"url": "https://live.bilivideo.com/fixture.m3u8"}]}
            return response(request, {"data": data})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as session:
            result = await BilibiliLiveParser().parse("https://live.bilibili.com/123", session)
        self.assertEqual(result.extra["stream_format"], "hls")

    async def test_douyin_live(self):
        def handler(request):
            if request.method == "GET":
                return response(request, text="fixture", headers={"set-cookie": "ttwid=fixture; Path=/"})
            return response(request, {"data": {"data": [{"status": 2, "owner": {"nickname": "fixture"}, "stream_url": {"flv_pull_url": {"FULL_HD1": "https://live.douyinvod.com/fixture.flv"}}}]}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as session:
            result = await DouyinLiveParser().parse("https://live.douyin.com/123", session)
        self.assertEqual(result.extra["stream_format"], "flv")

    async def test_huya_line_selection(self):
        line = {"sStreamName": "fixture", "sHlsUrl": "https://hs.hls.huya.com/src", "sHlsAntiCode": "ctype=fixture&wsSecret=" + "a" * 32 + "&wsTime=ffffffff", "sCdnType": "HS"}
        payload = {"status": 200, "data": {"liveStatus": "ON", "stream": {"baseSteamInfoList": [line]}, "liveData": {"roomName": "fixture"}, "profileInfo": {"nick": "test"}}}
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: response(req, payload))) as session:
            result = await HuyaLiveParser().parse("https://www.huya.com/123", session)
        self.assertEqual(result.direct_url, hls_url(line))
        self.assertIn("https://hs.hls.huya.com/src/part.ts", rewrite_manifest("#EXTM3U\n#EXTINF:2,\npart.ts\n", result.direct_url))

    async def test_douyu_handshake(self):
        def handler(request):
            if "/betard/" in request.url.path:
                data = {"room": {"room_id": 1, "show_status": 1, "room_name": "fixture"}}
            elif "getEncryption" in request.url.path:
                data = {"error": 0, "data": {"enc_time": 0, "key": "fixture", "rand_str": "seed", "is_special": 0, "enc_data": "fixture"}}
            else:
                data = {"error": 0, "data": {"rtmp_url": "https://cdn.douyucdn.cn/live", "rtmp_live": "fixture.flv"}}
            return response(request, data)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as session:
            result = await DouyuLiveParser().parse("https://www.douyu.com/1", session)
        self.assertEqual(result.extra["stream_format"], "flv")

    async def test_kugou_primary_and_tracker(self):
        for primary in (True, False):
            seen = []
            def handler(request):
                seen.append(request)
                if "getSongInfo" in request.url.path:
                    return response(request, {"url": "https://media.kugou.com/fixture.mp3" if primary else "", "fileName": "test - fixture"})
                if request.url.host == "trackercdn.kugou.com":
                    return response(request, {"url": ["https://media.kugou.com/fallback.mp3"]})
                return response(request, text="fixture")
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as session:
                result = await KugouParser(cookie="fixture-cookie").parse("https://www.kugou.com/song/#hash=" + "a" * 32, session)
            self.assertTrue(result.direct_url.endswith(".mp3"))
            self.assertTrue(all(not req.headers.get("cookie") for req in seen if req.url.host == "trackercdn.kugou.com"))

    async def test_public_entry_is_mockable_and_does_not_load_application(self):
        original = httpx.AsyncClient
        def handler(request):
            data = {"live_status": 1, "room_id": 123} if "get_info" in request.url.path else {"durl": [{"url": "https://live.bilivideo.com/fixture.m3u8"}]}
            return response(request, {"data": data})
        def factory(**kwargs):
            return original(transport=httpx.MockTransport(handler), **kwargs)
        with patch("vrc_parsers.client.httpx.AsyncClient", factory):
            result = await parse_one("https://live.bilibili.com/123")
        self.assertEqual(result.platform, "bilibili_live")
        for name in ("main", "settings", "redis", "minecraft_integration"):
            self.assertNotIn(name, sys.modules)


if __name__ == "__main__":
    unittest.main()
