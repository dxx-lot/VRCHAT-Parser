"""酷狗单曲：分享链接/歌曲 hash → 官方基础播放接口。

本模块不包含歌单、私人节点或原应用的登录签名常量。
"""
import hashlib
import re
from urllib.parse import unquote

from .base import BaseParser, MediaType, ParseError, ParseResult
from .utils import USER_AGENT


def sign_parameters(params: dict, salt: str) -> str:
    """协议算法示例；salt 由调用者提供，不内置原应用常量。"""
    text = "".join(f"{k}={params[k]}" for k in sorted(params) if params[k] not in (None, ""))
    return hashlib.md5((salt + text + salt).encode(), usedforsecurity=False).hexdigest()


class KugouParser(BaseParser):
    platform = "kugou"
    media_type = MediaType.AUDIO
    description = "酷狗音乐单曲（基础接口）"
    patterns = [re.compile(r"(?:^|\.)kugou\.com[/#?]")]

    def __init__(self, cookie: str = ""):
        self.cookie = cookie

    @staticmethod
    def _single(url: str) -> None:
        if re.search(r"playlist|plist|special/single|zlist|global_collection_id|(?:listid|specialid)=", url, re.I):
            raise ParseError("本库仅解析酷狗单曲，不支持歌单或批量链接")

    async def parse(self, url: str, session) -> ParseResult:
        self._single(url)
        response = await session.get(url, headers={"User-Agent": USER_AGENT})
        final = str(response.url)
        self._single(final)
        text = unquote(final + " " + url)
        match = re.search(r"hash=([a-f0-9]{32})", text, re.I)
        if not match:
            match = re.search(r'''["']hash["']\s*:\s*["']([a-f0-9]{32})''', response.text, re.I)
        if not match:
            raise ParseError("无法从单曲链接中识别酷狗歌曲 hash")
        album = re.search(r"album_id=(\d+)", text)
        return await self._parse_song(match.group(1), album.group(1) if album else "", session)

    async def _parse_song(self, song_hash: str, album_id: str, session) -> ParseResult:
        headers = {"User-Agent": USER_AGENT, "Referer": "https://www.kugou.com/"}
        url, title, author, cover = "", "酷狗音乐", "", ""
        for use_cookie in (False, True):
            if use_cookie and not self.cookie:
                break
            request_headers = dict(headers)
            if use_cookie:
                request_headers["Cookie"] = self.cookie
            try:
                response = await session.get(
                    "https://m.kugou.com/app/i/getSongInfo.php",
                    params={"cmd": "playInfo", "hash": song_hash}, headers=request_headers,
                )
                data = response.json()
                url = data.get("url") or ""
                filename = data.get("fileName") or ""
                if " - " in filename:
                    author, title = filename.split(" - ", 1)
                elif filename:
                    title = filename
                cover = data.get("imgUrl") or ""
                if url:
                    break
            except Exception:
                continue
        if not url:
            # 只传歌曲 hash 与协议参数，不向此回退接口发送账户 Cookie。
            params = {"key": hashlib.md5((song_hash + "kgcloudv2").encode(), usedforsecurity=False).hexdigest(),
                      "hash": song_hash, "appid": "1005", "pid": "2", "cmd": "25", "behavior": "play"}
            if album_id:
                params["album_id"] = album_id
            try:
                data = (await session.get("https://trackercdn.kugou.com/i/v2/", params=params, headers=headers)).json()
                urls = data.get("url") or []
                url = urls[0] if isinstance(urls, list) and urls else ""
            except Exception:
                pass
        if not url:
            raise ParseError("酷狗基础接口没有返回可用地址；付费、地区限制或平台风控不保证支持")
        return ParseResult(platform=self.platform, media_type=self.media_type, title=title,
                           author=author, cover_url=cover, direct_url=url,
                           referer="https://www.kugou.com/")
