import re
from .base import BaseParser, MediaType, ParseError, ParseResult
from .utils import USER_AGENT

class BilibiliLiveParser(BaseParser):
    platform = 'bilibili_live'
    media_type = MediaType.VIDEO
    description = 'B站直播（live.bilibili.com 房间）'
    patterns = [re.compile('live\\.bilibili\\.com/(\\d+)')]

    async def parse(self, url: str, session) -> ParseResult:
        m = self.patterns[0].search(url)
        short_id = m.group(1)
        headers = {'User-Agent': USER_AGENT, 'Referer': 'https://live.bilibili.com/', 'Cookie': ''}
        r = await session.get('https://api.live.bilibili.com/room/v1/Room/get_info', params={'room_id': short_id}, headers=headers)
        info = r.json().get('data') or {}
        live_status = info.get('live_status', 0)
        if live_status != 1:
            raise ParseError('主播当前未开播')
        real_room_id = info.get('room_id', short_id)
        r2 = await session.get('https://api.live.bilibili.com/room/v1/Room/playUrl', params={'cid': real_room_id, 'qn': 10000, 'platform': 'h5'}, headers=headers)
        durl = (r2.json().get('data') or {}).get('durl') or []
        if not durl:
            raise ParseError('获取直播流失败')
        return ParseResult(platform=self.platform, media_type=MediaType.VIDEO, title=info.get('title') or 'B站直播', author=info.get('uname') or '', cover_url=info.get('user_cover'), direct_url=durl[0]['url'], requires_proxy=False, referer='https://live.bilibili.com/', extra={'is_live': True, 'stream_format': 'hls', 'qualities': [{'name': q.get('desc', ''), 'url': q.get('url')} for q in durl]})
