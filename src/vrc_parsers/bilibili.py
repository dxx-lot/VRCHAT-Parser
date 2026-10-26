from __future__ import annotations
import asyncio
import hashlib
import re
import time
import urllib.parse
from .base import BaseParser, MediaType, ParseError, ParseResult
from .utils import USER_AGENT

_QUALITY_LABELS = {6: '240P', 16: '360P', 32: '480P', 64: '720P', 74: '720P60', 80: '1080P', 112: '1080P+', 116: '1080P60', 120: '4K', 125: 'HDR', 126: '杜比视界', 127: '8K'}

def _quality_label(qn: int) -> str:
    return _QUALITY_LABELS.get(int(qn or 0), f'QN{int(qn or 0)}')
_DASH_LOOKUP_TIMEOUT = 3.0

def _dash_url(item: dict) -> str:
    return next(iter(_media_candidates(item)), '')

def _media_candidates(item: dict) -> list[str]:
    """Only existing trusted CDN domains; PCDN primary URLs never hide safe backups."""
    values = [item.get('baseUrl'), item.get('base_url'), item.get('url')]
    for key in ('backupUrl', 'backup_url'):
        backups = item.get(key) or []
        values.extend([backups] if isinstance(backups, str) else backups if isinstance(backups, (list, tuple)) else [])
    safe = []
    for value in values:
        if is_bili_media_url(value) and value not in safe:
            safe.append(value)
        if len(safe) >= 4:
            break
    return safe

def _pick_dash_avc(data: dict) -> tuple[dict | None, dict | None]:
    """选取 VRChat/AVPro 最稳的最高 H.264 视频和普通 AAC 音轨。"""
    dash = (data or {}).get('dash') or {}
    videos = [v for v in dash.get('video') or [] if _dash_url(v)]
    avc = [v for v in videos if int(v.get('codecid') or 0) == 7 and int(v.get('id') or 0) <= 120]
    video = max(avc, key=lambda v: (int(v.get('id') or 0), int(v.get('bandwidth') or 0)), default=None)
    audios = [a for a in dash.get('audio') or [] if _dash_url(a)]
    audio = max(audios, key=lambda a: int(a.get('bandwidth') or 0), default=None)
    return (video, audio)

def is_bili_media_url(url: str) -> bool:
    """Validate platform CDN media URLs."""
    if not isinstance(url, str) or len(url) > 16384 or any((ord(c) < 33 or c == '\\' for c in url)):
        return False
    try:
        p = urllib.parse.urlsplit(url)
        host = (p.hostname or '').lower()
        return p.scheme in {'https', 'http'} and p.username is None and (p.password is None) and (p.port in {None, 80, 443}) and any((host == d or host.endswith('.' + d) for d in ('bilivideo.com', 'hdslb.com')))
    except (TypeError, ValueError):
        return False

async def _pick_fast_media(session, candidates: list[str], referer: str='', budget: float=1.2) -> str:
    """Read at most one small chunk; slow/failed peers cannot extend the race budget."""
    candidates = list(dict.fromkeys((url for url in candidates if is_bili_media_url(url))))[:4]
    if not candidates:
        raise ParseError('B站暂未提供可安全使用的媒体线路，请稍后重试', 502)
    if len(candidates) < 2:
        return candidates[0]

    async def probe(url):
        headers = {'User-Agent': USER_AGENT, 'Cookie': '', 'Range': 'bytes=0-1023'}
        if referer:
            headers['Referer'] = referer
        try:
            async with session.stream('GET', url, headers=headers, timeout=1.0, follow_redirects=False) as response:
                if response.status_code in {200, 206}:
                    async for chunk in response.aiter_bytes(1024):
                        if chunk:
                            return url
        except Exception:
            pass
        return None
    tasks = [asyncio.create_task(probe(url)) for url in candidates[:4]]
    pending = set(tasks)
    deadline = asyncio.get_running_loop().time() + budget
    try:
        while pending:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            (done, pending) = await asyncio.wait(pending, timeout=remaining, return_when=asyncio.FIRST_COMPLETED)
            if not done:
                break
            for task in done:
                chosen = task.result()
                if chosen:
                    return chosen
        return candidates[0]
    finally:
        for task in pending:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
_BVID = re.compile('(BV[0-9A-Za-z]{10}|av\\d+)')
_MIXIN_TAB = [46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52]

def _mixin_key(orig: str) -> str:
    return ''.join((orig[i] for i in _MIXIN_TAB))[:32]

async def _fetch_wbi_key(session):
    r = await session.get('https://api.bilibili.com/x/web-interface/nav', headers={'User-Agent': USER_AGENT, 'Referer': 'https://www.bilibili.com/', 'Cookie': ''})
    j = r.json()
    wbi = (j.get('data') or {}).get('wbi_img') or {}
    img = wbi.get('img_url', '')
    sub = wbi.get('sub_url', '')
    if not img or not sub:
        return None
    ik = img.rsplit('/', 1)[-1].split('.')[0]
    sk = sub.rsplit('/', 1)[-1].split('.')[0]
    return _mixin_key(ik + sk)

def _wbi_sign(params: dict, mixin_key: str) -> dict:
    params = dict(params)
    params['wts'] = int(time.time())
    items = sorted(params.items())
    qs = urllib.parse.urlencode([(k, ''.join((c for c in str(v) if c not in "!'()*"))) for (k, v) in items])
    params['w_rid'] = hashlib.md5((qs + mixin_key).encode(), usedforsecurity=False).hexdigest()
    return params

class BilibiliParser(BaseParser):
    platform = 'bilibili'
    media_type = MediaType.VIDEO
    description = 'B站视频（BV/av 号，支持短链）'
    patterns = [re.compile('bilibili\\.com/video/[A-Za-z0-9]+'), re.compile('b23\\.tv/[A-Za-z0-9]+')]

    async def _resolve_bvid(self, url: str, session) -> str:
        m = _BVID.search(url)
        if m:
            return m.group(1)
        resp = await session.get(url, headers={'User-Agent': USER_AGENT})
        m = _BVID.search(str(resp.url))
        if not m:
            raise ParseError('无法从短链解析出 BV 号')
        return m.group(1)

    async def _parse(self, url: str, session, use_account: bool, cookie: str, mode: str | None) -> ParseResult:
        mode = mode or ('authenticated' if use_account else 'progressive')
        if mode not in {'progressive', 'authenticated', 'dash'}:
            raise ParseError('不支持的 B站播放方式', 422)
        if not use_account and mode != 'progressive':
            raise ParseError('此模式需要显式启用账户访问', 403)
        authenticated = use_account and mode != 'progressive'
        if authenticated and (not (cookie or '').strip()):
            raise ParseError('未提供 B站访问凭据', 503)
        bvid = await self._resolve_bvid(url, session)
        headers = {'User-Agent': USER_AGENT, 'Referer': f'https://www.bilibili.com/video/{bvid}', 'Cookie': cookie or '' if authenticated else ''}
        view_request = session.get('https://api.bilibili.com/x/web-interface/view', params={'bvid': bvid}, headers=headers)
        if authenticated:
            try:
                (view, nav) = await asyncio.gather(view_request, session.get('https://api.bilibili.com/x/web-interface/nav', headers=headers))
                if not (nav.json().get('data') or {}).get('isLogin'):
                    raise ParseError('调用者提供的 B站 Cookie 已失效', 503)
            except ParseError:
                raise
            except Exception as exc:
                raise ParseError('B站登录态或视频信息校验失败，请稍后重试', 502) from exc
        else:
            view = await view_request
        info_json = view.json()
        if info_json.get('code') != 0:
            raise ParseError('获取视频信息失败（视频不存在或链接有误）')
        info = info_json.get('data') or {}
        cid = info.get('cid')
        if not cid:
            raise ParseError('获取视频 cid 失败')

        async def api_data(params):
            for api in ('https://api.bilibili.com/x/player/playurl', 'https://api.bilibili.com/x/player/wbi/playurl'):
                try:
                    query = dict(params)
                    if api.endswith('wbi/playurl'):
                        key = await _fetch_wbi_key(session)
                        if not key:
                            continue
                        query = _wbi_sign(query, key)
                    reply = (await session.get(api, params=query, headers=headers)).json()
                    if reply.get('code', 0) == 0:
                        yield (reply.get('data') or {})
                except Exception:
                    continue

        async def progressive():
            if not authenticated:
                try:
                    reply = (await session.get('https://api.bilibili.com/x/player/playurl', params={'bvid': bvid, 'cid': cid, 'qn': 64, 'platform': 'html5', 'high_quality': 1}, headers=headers)).json()
                    data = reply.get('data') or {}
                    durl = data.get('durl') or []
                    urls = _media_candidates(durl[0]) if durl else []
                    if reply.get('code', 0) == 0 and urls and (int(data.get('quality') or 0) <= 64):
                        return (urls, int(data.get('quality') or 0), True)
                except Exception:
                    pass
                if use_account:
                    raise ParseError('B站暂未提供可用线路，请稍后重试', 502)
            async for data in api_data({'bvid': bvid, 'cid': cid, 'qn': 64, 'fnval': 1, 'fourk': 0}):
                durl = data.get('durl') or []
                urls = _media_candidates(durl[0]) if durl else []
                quality = int(data.get('quality') or 0)
                if urls and quality <= 64:
                    return (urls, quality, False)
            raise ParseError('B站暂未提供可安全使用的媒体线路，请稍后重试', 502)

        async def dash():
            async for data in api_data({'bvid': bvid, 'cid': cid, 'qn': 120, 'fnval': 4048, 'fourk': 1}):
                (video, audio) = _pick_dash_avc(data)
                if video and audio:
                    qn = int(video.get('id') or data.get('quality') or 0)
                    return {'bvid': bvid, 'cid': str(cid), 'video_url': _dash_url(video), 'audio_url': _dash_url(audio), 'video_urls': _media_candidates(video), 'audio_urls': _media_candidates(audio), 'quality_id': qn, 'quality_label': _quality_label(qn), 'video_bandwidth': int(video.get('bandwidth') or 0), 'audio_bandwidth': int(audio.get('bandwidth') or 0), 'video_codecid': int(video.get('codecid') or 0)}
            return None
        dash_mux = None
        if authenticated and mode == 'dash':

            async def optional_dash():
                try:
                    return await asyncio.wait_for(dash(), timeout=_DASH_LOOKUP_TIMEOUT)
                except Exception:
                    return None
            dash_task = asyncio.create_task(optional_dash())
            try:
                (candidates, quality, html5_mode) = await progressive()
                dash_mux = await dash_task
            finally:
                if not dash_task.done():
                    dash_task.cancel()
                await asyncio.gather(dash_task, return_exceptions=True)
        else:
            (candidates, quality, html5_mode) = await progressive()
        direct = await _pick_fast_media(session, candidates, '' if html5_mode else headers['Referer'])
        extra = {'quality_id': quality, 'quality_label': _quality_label(quality) if quality else '源站画质', 'mode': mode}
        if dash_mux:
            extra['dash'] = dash_mux
        return ParseResult(platform=self.platform, media_type=MediaType.VIDEO, title=info.get('title', 'B站视频'), author=(info.get('owner') or {}).get('name', ''), cover_url=info.get('pic'), duration=info.get('duration'), direct_url=direct, requires_proxy=True, referer='' if html5_mode else 'https://www.bilibili.com', extra=extra)

    def __init__(self, cookie='', mode='progressive'):
        if mode not in {'progressive', 'authenticated', 'dash'}:
            raise ParseError('不支持的 B站解析模式')
        if mode != 'progressive' and (not cookie):
            raise ParseError('此模式需要调用者提供有权访问该内容的 Cookie')
        (self.cookie, self.mode) = (cookie, mode)

    async def parse(self, url, session):
        try:
            return await asyncio.wait_for(self._parse(url, session, self.mode != 'progressive', self.cookie, self.mode), 12)
        except asyncio.TimeoutError:
            raise ParseError('B站接口响应超时', 504) from None
