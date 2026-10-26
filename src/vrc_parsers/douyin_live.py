import re
from .base import BaseParser, MediaType, ParseError, ParseResult
from .utils import MOBILE_UA

class DouyinLiveParser(BaseParser):
    platform = 'douyin_live'
    media_type = MediaType.VIDEO
    description = '抖音直播（live.douyin.com 房间）'
    patterns = [re.compile('live\\.douyin\\.com/(\\d+)')]

    async def parse(self, url: str, session) -> ParseResult:
        m = self.patterns[0].search(url)
        rid = m.group(1)
        r0 = await session.get(f'https://live.douyin.com/{rid}', headers={'User-Agent': MOBILE_UA})
        ttwid = session.cookies.get('ttwid') or r0.cookies.get('ttwid')
        headers = {'User-Agent': MOBILE_UA, 'Referer': f'https://live.douyin.com/{rid}'}
        if ttwid:
            headers['Cookie'] = f'ttwid={ttwid}'
        payload = {'aid': 6383, 'app_name': 'douyin_web', 'device_platform': 'web', 'browser_language': 'zh-CN', 'browser_platform': 'Win32', 'browser_name': 'Chrome', 'browser_version': '124.0.0.0', 'web_rid': rid, 'enter_from_merge': 'web_search', 'cookie_enabled': True, 'screen_width': 1920, 'screen_height': 1080, 'browser_online': True}
        r = await session.post('https://live.douyin.com/webcast/room/web/enter/', data=payload, headers=headers)
        j = r.json()
        room = ((j.get('data') or {}).get('data') or [{}])[0]
        room_status = room.get('status', 4)
        if room_status == 4:
            raise ParseError('主播当前未开播')
        if room_status != 2:
            raise ParseError('直播间状态异常（抖音接口可能已更新）')
        flv = (room.get('stream_url') or {}).get('flv_pull_url') or {}
        keys = [k for k in flv if flv[k]]
        if not keys:
            raise ParseError('获取直播流失败（抖音接口可能已更新）')
        order = ['FULL_HD1', 'ORIGION', 'HD1', 'SD1', 'SD2']
        best = next((k for k in order if k in keys), keys[0])
        return ParseResult(platform=self.platform, media_type=MediaType.VIDEO, title=(room.get('owner') or {}).get('nickname', '抖音直播'), author='', cover_url=((room.get('cover') or {}).get('url_list') or [None])[0], direct_url=flv[best], requires_proxy=False, referer='https://live.douyin.com/', extra={'is_live': True, 'stream_format': 'flv', 'quality': best})
