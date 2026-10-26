"""斗鱼当前公开换链接口；本地迭代 MD5，不执行远程 JS。"""
import hashlib
import re
import time
import uuid
from urllib.parse import urlsplit
from .base import BaseParser, MediaType, ParseError, ParseResult
from .live_direct import cdn_url, metadata, room_name

def auth_value(room: str, timestamp: int, encryption: dict) -> str:
    try:
        count = encryption['enc_time']
        (key, value) = (encryption['key'], encryption['rand_str'])
        if type(count) is not int or not 0 <= count <= 10000 or (not isinstance(key, str)) or (not isinstance(value, str)) or (len(key) > 4096) or (len(value) > 4096) or (encryption.get('is_special') not in (0, 1)):
            raise ValueError
        for _ in range(count):
            value = hashlib.md5((value + key).encode()).hexdigest()
        suffix = '' if encryption['is_special'] == 1 else room + str(timestamp)
        return hashlib.md5((value + key + suffix).encode()).hexdigest()
    except (KeyError, ValueError, TypeError):
        raise ParseError('斗鱼签名参数异常，请稍后重新解析', 502) from None

def play_url(stream: dict) -> str:
    (base, name) = (stream.get('rtmp_url'), stream.get('rtmp_live'))
    if not isinstance(base, str) or not isinstance(name, str):
        return ''
    if not re.fullmatch('[A-Za-z0-9_-]+\\.(?:flv|m3u8)(?:\\?[^#\\s]*)?', name):
        return ''
    url = cdn_url(base.rstrip('/') + '/' + name, ('douyucdn.cn', 'douyucdn2.cn'))
    return url

class DouyuLiveParser(BaseParser):
    platform = 'douyu_live'
    media_type = MediaType.VIDEO
    description = '斗鱼直播（官方 CDN 直连；FLV 需兼容播放器）'

    @classmethod
    def match(cls, url: str) -> bool:
        return bool(room_name(url, 'douyu.com'))

    async def parse(self, url: str, session) -> ParseResult:
        name = room_name(url, 'douyu.com')
        if not name:
            raise ParseError('请输入有效的斗鱼直播间链接')
        payload = await metadata(session, 'GET', 'https://www.douyu.com/betard/' + name)
        room = payload.get('room') or {}
        if not isinstance(room, dict):
            raise ParseError('斗鱼直播间数据异常', 502)
        rid = str(room.get('room_id') or '')
        if not re.fullmatch('\\d{1,12}', rid):
            raise ParseError('斗鱼直播间不存在或接口暂不可用')
        if str(room.get('show_status')) != '1' or str(room.get('videoLoop', 0)) == '1':
            raise ParseError('主播当前未开播（轮播录像不作为直播解析）')
        did = uuid.uuid4().hex
        enc = await metadata(session, 'GET', 'https://www.douyu.com/wgapi/livenc/liveweb/websec/getEncryption', params={'did': did})
        encryption = enc.get('data')
        if enc.get('error') != 0 or not isinstance(encryption, dict):
            raise ParseError('斗鱼换链暂不可用，请稍后重试', 502)
        timestamp = int(time.time())
        auth = auth_value(rid, timestamp, encryption)
        opaque = encryption.get('enc_data')
        if not isinstance(opaque, str) or not 0 < len(opaque) <= 65536:
            raise ParseError('斗鱼签名参数异常', 502)
        play = await metadata(session, 'POST', 'https://www.douyu.com/lapi/live/getH5PlayV1/' + rid, data={'enc_data': opaque, 'tt': str(timestamp), 'did': did, 'auth': auth, 'cdn': 'hw-h5', 'rate': '0', 'hevc': '0', 'fa': '0', 'ive': '0'})
        stream = play.get('data')
        direct = play_url(stream) if isinstance(stream, dict) and play.get('error') == 0 else ''
        if not direct:
            raise ParseError('斗鱼暂未提供可用直链，请稍后重新解析', 502)
        stream_format = 'hls' if urlsplit(direct).path.endswith('.m3u8') else 'flv'
        return ParseResult(platform=self.platform, media_type=self.media_type, title=room.get('room_name') or '斗鱼直播', author=room.get('nickname') or '', direct_url=direct, extra={'is_live': True, 'stream_format': stream_format, 'direct_only': True, 'room_id': rid, 'playback_notice': '斗鱼当前返回 FLV。VRChat 播放器可能不兼容；本库不转流，失效后请重新解析。' if stream_format == 'flv' else ''})
