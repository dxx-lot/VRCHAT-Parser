import json
import re
from .base import BaseParser, MediaType, ParseError, ParseResult
from .utils import MOBILE_UA
_VID_RE = [re.compile('/video/(\\d+)'), re.compile('/share/video/(\\d+)'), re.compile('/note/(\\d+)'), re.compile('modal_id=(\\d+)'), re.compile('(\\d{15,})')]

def _extract_vid(text: str):
    for p in _VID_RE:
        m = p.search(text)
        if m:
            return m.group(1)
    return None

def _no_watermark(url: str) -> str:
    """去抖音官方水印：playwm -> play"""
    return url.replace('playwm', 'play') if url else url

class DouyinParser(BaseParser):
    platform = 'douyin'
    media_type = MediaType.VIDEO
    description = '抖音视频（分享链接，自动去官方水印）'
    patterns = [re.compile('v\\.douyin\\.com/[A-Za-z0-9]+'), re.compile('douyin\\.com/video/\\d+'), re.compile('iesdouyin\\.com/share/video/\\d+')]

    async def parse(self, url: str, session) -> ParseResult:
        m_url = re.search('https?://[^\\s\\u3001\\u3002，,；;]+', url)
        if m_url:
            url = m_url.group(0)
        resp = await session.get(url, headers={'User-Agent': MOBILE_UA})
        final_url = str(resp.url)
        vid = None
        for u in [str(h.url) for h in resp.history] + [final_url, url]:
            vid = _extract_vid(u)
            if vid:
                break
        if not vid:
            raise ParseError('无法从链接提取视频 ID：请在浏览器打开链接后，复制地址栏的完整链接再试')
        item = None
        import asyncio as _asyncio
        for _attempt in range(3):
            try:
                r = await session.get(f'https://www.iesdouyin.com/share/video/{vid}/', headers={'User-Agent': MOBILE_UA})
                rd = re.search('_ROUTER_DATA\\s*=\\s*(\\{.*?\\})\\s*</script>', r.text, re.S)
                if rd:
                    data = json.loads(rd.group(1))
                    loader = data.get('loaderData') or {}
                    for v in loader.values():
                        if isinstance(v, dict) and v.get('videoInfoRes'):
                            item = (v['videoInfoRes'].get('item_list') or [None])[0]
                            if item:
                                break
                    if item:
                        break
            except Exception:
                pass
            await _asyncio.sleep(0.6 * (_attempt + 1))
        if item is None:
            for _attempt in range(2):
                try:
                    r2 = await session.get('https://www.douyin.com/aweme/v1/web/aweme/detail/', params={'aweme_id': vid, 'aid': 6383, 'device_platform': 'webapp', 'browser_language': 'zh-CN', 'browser_platform': 'iPhone', 'browser_name': 'Safari', 'browser_version': '17.0'}, headers={'User-Agent': MOBILE_UA, 'Referer': f'https://www.douyin.com/video/{vid}'})
                    j = r2.json()
                    item = j.get('aweme_detail') or None
                    if item:
                        break
                except Exception:
                    pass
                await _asyncio.sleep(0.6 * (_attempt + 1))
        if item is None:
            try:
                r3 = await session.get(f'https://www.douyin.com/video/{vid}?previous_page=web_code_link', headers={'User-Agent': MOBILE_UA})
                rd3 = re.search('_ROUTER_DATA\\s*=\\s*(\\{.*?\\})\\s*</script>', r3.text, re.S)
                if rd3:
                    data3 = json.loads(rd3.group(1))
                    for v in (data3.get('loaderData') or {}).values():
                        if isinstance(v, dict) and v.get('videoInfoRes'):
                            item = (v['videoInfoRes'].get('item_list') or [None])[0]
                            if item:
                                break
            except Exception:
                pass
        if item is None:
            raise ParseError('抖音解析失败：平台接口可能已更新，请换个视频再试或反馈')
        video = item.get('video') or {}
        raw_urls = (video.get('download_addr') or {}).get('url_list') or (video.get('play_addr') or {}).get('url_list') or []
        play_url = raw_urls[0] if raw_urls else ''
        if not play_url:
            raise ParseError('未获取到播放地址')
        play_url = _no_watermark(play_url)
        return ParseResult(platform=self.platform, media_type=MediaType.VIDEO, title=item.get('desc') or '抖音视频', author=(item.get('author') or {}).get('nickname', ''), cover_url=((video.get('cover') or {}).get('url_list') or [None])[0], duration=(video.get('duration') or 0) // 1000 or None, direct_url=play_url, requires_proxy=False, referer='https://www.douyin.com/')
