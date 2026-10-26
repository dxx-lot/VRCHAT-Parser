"""明确的平台白名单与单链接入口，不依赖 Web 应用。"""
from __future__ import annotations

import asyncio
import ipaddress
import re
from urllib.parse import unquote, urlsplit

import httpx

from .base import ParseError, ParseResult
from .bilibili import BilibiliParser
from .bilibili_live import BilibiliLiveParser
from .douyin import DouyinParser
from .douyin_live import DouyinLiveParser
from .douyu_live import DouyuLiveParser
from .huya_live import HuyaLiveParser
from .kugou import KugouParser
from .netease import NeteaseParser
from .qqmusic import QQMusicParser


def _url_parts(url: str):
    if not isinstance(url, str) or len(url) > 8192 or "\\" in url or any(ord(c) <= 32 for c in url):
        raise ParseError("请输入一条完整的 HTTP(S) 媒体链接")
    try:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username is not None or parts.password is not None or parts.port not in {None, 80, 443}:
            raise ValueError
    except ValueError:
        raise ParseError("媒体链接格式不正确") from None
    return parts


def _domain(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def choose_parser(url: str, *, cookie: str = "", bili_mode: str = "progressive"):
    parts = _url_parts(url)
    host = parts.hostname.lower()
    text = unquote(parts.path + "?" + parts.query + "#" + parts.fragment)
    if re.search(r"playlist|/album(?:/|\?)|plist|special/single|zlist|global_collection_id|(?:disstid|taogeid|listid|specialid)=", text, re.I):
        raise ParseError("本库只支持单视频、单曲和直播间，不支持歌单或批量链接")
    if host == "live.bilibili.com" and BilibiliLiveParser.match(url):
        return BilibiliLiveParser()
    if (_domain(host, "bilibili.com") or host == "b23.tv") and BilibiliParser.match(url):
        return BilibiliParser(cookie=cookie, mode=bili_mode)
    if host == "live.douyin.com" and DouyinLiveParser.match(url):
        return DouyinLiveParser()
    if any(_domain(host, d) for d in ("douyin.com", "iesdouyin.com")) and DouyinParser.match(url):
        return DouyinParser()
    if any(_domain(host, d) for d in ("music.163.com", "163cn.tv")) and NeteaseParser.match(url):
        return NeteaseParser(cookie=cookie)
    if _domain(host, "y.qq.com") and QQMusicParser.match(url):
        return QQMusicParser(cookie=cookie)
    if _domain(host, "kugou.com"):
        return KugouParser(cookie=cookie)
    for domain, cls in (("huya.com", HuyaLiveParser), ("douyu.com", DouyuLiveParser)):
        if _domain(host, domain) and cls.match(url):
            return cls()
    raise ParseError("暂不支持该平台或链接类型", 404)


# Outgoing requests may only target platform hosts and their media CDNs. This is
# a local parsing library, not a DNS-pinned server-side SSRF isolation boundary.
_UPSTREAMS = ("bilibili.com", "b23.tv", "bilivideo.com", "hdslb.com", "douyin.com",
              "iesdouyin.com", "douyinvod.com", "douyinpic.com", "snssdk.com", "amemv.com",
              "music.163.com", "163cn.tv", "music.126.net", "y.qq.com", "qqmusic.qq.com",
              "gtimg.cn", "qqmusic.tc.qq.com", "kugou.com", "huya.com", "huyaimg.com",
              "douyu.com", "douyucdn.cn", "douyucdn2.cn", "douyucdn3.cn", "douyucdn4.cn")


async def _request_policy(request: httpx.Request) -> None:
    host = request.url.host.lower()
    if request.url.scheme not in {"http", "https"} or request.url.userinfo or request.url.port not in {None, 80, 443}:
        raise ParseError("拒绝不安全的平台请求地址", 502)
    # 请求钩子在首次发送和每次重定向后执行；不依赖上游先跳转到 HTTPS。
    if request.url.scheme != "https" and any(
        request.headers.get(name, "").strip() for name in ("Cookie", "Authorization")
    ):
        raise ParseError("含凭据的平台请求必须使用 HTTPS，请更换为 HTTPS 链接", 502)
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ParseError("不允许请求直接 IP 地址", 502)
    if not any(_domain(host, domain) for domain in _UPSTREAMS):
        raise ParseError("平台跳转到了未列入白名单的主机", 502)


async def parse_one(url: str, *, cookie: str = "", bili_mode: str = "progressive", timeout: float = 30.0) -> ParseResult:
    parser = choose_parser(url, cookie=cookie, bili_mode=bili_mode)
    if not 0 < timeout <= 120:
        raise ParseError("超时时间必须在 0 到 120 秒之间")
    try:
        async with httpx.AsyncClient(timeout=min(timeout, 15), follow_redirects=True,
                                     max_redirects=5, trust_env=False,
                                     event_hooks={"request": [_request_policy]}) as session:
            result = await asyncio.wait_for(parser.parse(url, session), timeout=timeout)
    except (httpx.HTTPError, TimeoutError):
        raise ParseError("平台网络请求失败或超时", 502) from None
    if not result.direct_url:
        raise ParseError("平台未返回单条媒体地址", 502)
    return result
