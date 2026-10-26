"""第三方直播直链的输入校验与有界匿名元数据请求；不读取媒体。"""
import asyncio
import json
import re
from urllib.parse import parse_qs, urlsplit
import httpx
from .base import ParseError
from .utils import USER_AGENT
DIRECT_LIVE_PLATFORMS = frozenset({'huya_live', 'douyu_live'})

def room_name(url: str, domain: str) -> str:
    try:
        p = urlsplit(url)
        if p.scheme not in {'http', 'https'} or p.username is not None or p.password is not None or (p.port not in {None, 80, 443}) or (p.hostname not in {domain, 'www.' + domain, 'm.' + domain}) or any((ord(c) <= 32 for c in url)):
            return ''
        name = p.path.strip('/')
        if domain == 'douyu.com' and re.fullmatch('topic/[A-Za-z0-9_-]+', name):
            name = (parse_qs(p.query).get('rid') or [''])[0]
        return name if re.fullmatch('[A-Za-z0-9_-]{1,64}', name) else ''
    except (ValueError, TypeError):
        return ''

def cdn_url(url: str, domains: tuple[str, ...]) -> str:
    if not isinstance(url, str) or any((ord(c) <= 32 for c in url)):
        return ''
    try:
        p = urlsplit(url)
        host = p.hostname or ''
        if p.scheme != 'https' or p.username is not None or p.password is not None or (p.port not in {None, 443}) or p.fragment or (not any((host == d or host.endswith('.' + d) for d in domains))):
            return ''
    except ValueError:
        return ''
    return url

async def _metadata_body(session, method: str, url: str, *, params=None, data=None) -> bytes:
    try:
        async with asyncio.timeout(10), session.stream(method, url, params=params, data=data, timeout=8, follow_redirects=False, headers={'User-Agent': USER_AGENT, 'Cookie': '', 'Referer': 'https://' + urlsplit(url).hostname + '/'}) as r:
            if r.status_code != 200:
                raise ParseError('直播平台接口暂不可用，请稍后重试', 502)
            body = bytearray()
            async for part in r.aiter_bytes():
                body.extend(part)
                if len(body) > 2 * 1024 * 1024:
                    raise ParseError('直播平台响应过大', 502)
        return bytes(body)
    except (httpx.HTTPError, TimeoutError, ValueError, TypeError):
        raise ParseError('直播平台接口响应异常，请稍后重新解析', 502) from None

async def metadata_text(session, url: str) -> str:
    try:
        return (await _metadata_body(session, 'GET', url)).decode('utf-8')
    except UnicodeError:
        raise ParseError('直播间页面数据异常，请稍后重新解析', 502) from None

async def metadata(session, method: str, url: str, *, params=None, data=None) -> dict:
    try:
        result = json.loads(await _metadata_body(session, method, url, params=params, data=data))
        if not isinstance(result, dict):
            raise ValueError
        return result
    except (ValueError, TypeError):
        raise ParseError('直播平台接口响应异常，请稍后重新解析', 502) from None
