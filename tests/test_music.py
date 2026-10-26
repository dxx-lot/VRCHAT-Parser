import unittest

from vrc_parsers.base import ParseError
from vrc_parsers.netease import NeteaseParser
from vrc_parsers.qqmusic import QQMusicParser


class FakeResponse:
    def __init__(self, body=None, url="https://example.invalid/landing"):
        self._body = body or {}
        self.url = url

    def json(self):
        return self._body


class SensitiveErrorResponse(FakeResponse):
    def json(self):
        raise RuntimeError("response body contains FAKE_SECRET")


class FakeSession:
    def __init__(self, get_responses=None, post_responses=None):
        self.get_responses = list(get_responses or [])
        self.post_responses = list(post_responses or [])
        self.calls = []

    async def get(self, url, **kwargs):
        self.calls.append(("get", url, kwargs))
        if not self.get_responses:
            raise AssertionError(f"unexpected GET: {url}")
        return self.get_responses.pop(0)

    async def post(self, url, **kwargs):
        self.calls.append(("post", url, kwargs))
        if not self.post_responses:
            raise AssertionError(f"unexpected POST: {url}")
        return self.post_responses.pop(0)


class MusicParserTests(unittest.IsolatedAsyncioTestCase):
    async def test_netease_single_track_success(self):
        session = FakeSession(
            get_responses=[
                FakeResponse({"data": [{"url": "https://media.example.invalid/signed/audio?sig=FAKE", "fee": 0}]}),
                FakeResponse({"songs": [{
                    "name": "示例歌曲",
                    "artists": [{"name": "示例歌手"}],
                    "album": {"picUrl": "https://img.example.invalid/cover.jpg"},
                    "duration": 123400,
                }]}),
            ]
        )
        parser = NeteaseParser(cookie="session=FAKE_ONLY")
        result = await parser.parse("https://music.163.com/song?id=12345", session)
        self.assertEqual(result.title, "示例歌曲")
        self.assertEqual(result.author, "示例歌手")
        self.assertEqual(result.duration, 123)
        self.assertEqual(result.direct_url, "https://media.example.invalid/signed/audio?sig=FAKE")
        self.assertEqual(session.calls[0][2]["cookies"]["session"], "FAKE_ONLY")
        self.assertFalse(any("cookie" in key.lower() for key in result.extra))
        self.assertNotIn("FAKE_ONLY", result.direct_url)
        self.assertNotIn("FAKE_ONLY", repr(result))

    async def test_netease_paid_track_can_be_disallowed(self):
        session = FakeSession(get_responses=[
            FakeResponse({"data": [{"url": "https://media.example.invalid/paid.mp3", "fee": 1}]})
            for _ in range(3)
        ])
        parser = NeteaseParser()
        parser.allow_paid = False
        with self.assertRaises(ParseError) as caught:
            await parser.parse("https://music.163.com/song?id=222", session)
        self.assertEqual(caught.exception.code, 403)
        self.assertEqual(len(session.calls), 3)

    async def test_netease_unavailable_track_fails(self):
        session = FakeSession(get_responses=[FakeResponse({"data": [{"url": None}]}) for _ in range(3)])
        with self.assertRaises(ParseError) as caught:
            await NeteaseParser().parse("https://music.163.com/song?id=333", session)
        self.assertEqual(caught.exception.code, 404)

    async def test_netease_collection_and_short_link_to_collection_are_rejected(self):
        parser = NeteaseParser()
        with self.assertRaisesRegex(ParseError, "不支持歌单"):
            await parser.parse("https://music.163.com/playlist?id=44", FakeSession())
        with self.assertRaisesRegex(ParseError, "专辑"):
            await parser.parse("https://music.163.com/album?id=55", FakeSession())
        session = FakeSession(get_responses=[FakeResponse(url="https://music.163.com/album?id=55")])
        with self.assertRaisesRegex(ParseError, "短链指向歌单"):
            await parser.parse("https://163cn.tv/AbCd12", session)

    async def test_qq_single_track_success(self):
        session = FakeSession(post_responses=[
            FakeResponse({"req_0": {"data": {
                "midurlinfo": [{"purl": "audio.mp3"}],
                "sip": ["https://media.example.invalid/"],
            }}}),
            FakeResponse({"req_0": {"data": {"track_info": {
                "title": "示例歌曲", "singer": [{"name": "示例歌手"}],
                "cover": "https://img.example.invalid/cover.jpg",
            }}}}),
        ])
        result = await QQMusicParser(cookie="uin=o000FAKE").parse(
            "https://y.qq.com/n/ryqq/songDetail/AbCdEf", session
        )
        self.assertEqual(result.title, "示例歌曲")
        self.assertEqual(result.author, "示例歌手")
        self.assertEqual(result.direct_url, "https://media.example.invalid/audio.mp3")
        self.assertEqual(len(session.calls), 2)

    async def test_qq_missing_vkey_url_fails(self):
        session = FakeSession(post_responses=[FakeResponse({"req_0": {"data": {
            "midurlinfo": [{"purl": ""}], "sip": ["https://media.example.invalid/"]
        }}})])
        with self.assertRaisesRegex(ParseError, "暂不可用"):
            await QQMusicParser().parse("https://y.qq.com/n/ryqq/songDetail/AbCdEf", session)

    async def test_qq_uses_cookie_uin_and_falls_back_to_single_song_endpoint(self):
        session = FakeSession(
            get_responses=[FakeResponse({"data": [{
                "url": "https://media.example.invalid/fallback.mp3?sig=FAKE"
            }]})],
            post_responses=[
                FakeResponse({"req_0": {"code": -1, "data": {"midurlinfo": [], "sip": []}}}),
                FakeResponse({"req_0": {"data": {"track_info": {"title": "回退歌曲"}}}}),
            ],
        )
        result = await QQMusicParser(cookie="uin=o00012345; session=FAKE_ONLY").parse(
            "https://y.qq.com/n/ryqq/songDetail/AbCdEf", session
        )
        self.assertEqual(session.calls[0][2]["json"]["req_0"]["param"]["uin"], "12345")
        self.assertIn("fcg_play_single_song.fcg", session.calls[1][1])
        self.assertEqual(result.direct_url, "https://media.example.invalid/fallback.mp3?sig=FAKE")
        self.assertNotIn("FAKE_ONLY", result.direct_url)

    async def test_qq_failure_does_not_expose_response_or_cookie(self):
        session = FakeSession(
            post_responses=[SensitiveErrorResponse()],
            get_responses=[FakeResponse({"message": "cookie=FAKE_ONLY"})],
        )
        with self.assertRaises(ParseError) as caught:
            await QQMusicParser(cookie="uin=o123; session=FAKE_ONLY").parse(
                "https://y.qq.com/n/ryqq/songDetail/AbCdEf", session
            )
        self.assertNotIn("FAKE_SECRET", str(caught.exception))
        self.assertNotIn("FAKE_ONLY", str(caught.exception))

    async def test_qq_collection_and_short_link_to_collection_are_rejected(self):
        parser = QQMusicParser()
        with self.assertRaisesRegex(ParseError, "不支持歌单"):
            await parser.parse("https://y.qq.com/playlist/123", FakeSession())
        with self.assertRaisesRegex(ParseError, "专辑"):
            await parser.parse("https://y.qq.com/albumDetail/123", FakeSession())
        session = FakeSession(get_responses=[FakeResponse(url="https://y.qq.com/albumDetail/123")])
        with self.assertRaisesRegex(ParseError, "短链指向歌单"):
            await parser.parse("https://c.y.qq.com/AbCd12", session)


if __name__ == "__main__":
    unittest.main()
