"""虎牙公开房间信息换取官方 HLS；客户端直连 CDN。"""
import asyncio
import json
import re
import time
from html.parser import HTMLParser
from urllib.parse import parse_qs, urljoin, urlsplit
import httpx
from .base import BaseParser, MediaType, ParseError, ParseResult
from .live_direct import cdn_url, metadata, metadata_text, room_name

class _InlineScripts(HTMLParser):

    def __init__(self):
        super().__init__()
        self.scripts = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'script' and 'src' not in attrs and ((attrs.get('type') or '').lower() in ('', 'text/javascript', 'application/javascript')):
            self.current = []

    def handle_data(self, data):
        if self.current is not None:
            self.current.append(data)

    def handle_endtag(self, tag):
        if tag == 'script' and self.current is not None:
            self.scripts.append(''.join(self.current))
            self.current = None

def page_room(text: str) -> str:
    page = _InlineScripts()
    page.feed(text)
    decoder = json.JSONDecoder()
    trivia = re.compile('(?:\\s+|//[^\\r\\n]*(?:\\r?\\n|$)|/\\*[\\s\\S]*?\\*/)*')
    declaration = re.compile('(?:var|let|const)\\s+([A-Za-z_$][\\w$]*)\\s*=\\s*')
    for script in page.scripts:
        pos = 0
        while pos < len(script):
            pos = trivia.match(script, pos).end()
            match = declaration.match(script, pos)
            if not match:
                break
            try:
                (data, pos) = decoder.raw_decode(script, match.end())
            except (ValueError, RecursionError):
                break
            pos = trivia.match(script, pos).end()
            if pos < len(script) and script[pos] != ';':
                break
            if match[1] == 'TT_ROOM_DATA':
                value = data.get('profileRoom') if isinstance(data, dict) else None
                if type(value) in (int, str) and re.fullmatch('[0-9]{1,12}', str(value)):
                    return str(value)
                break
            pos += 1
    return ''

async def numeric_room(room: str, session) -> str:
    if room.isdigit():
        return room
    text = await metadata_text(session, 'https://www.huya.com/' + room)
    result = page_room(text)
    if not result:
        raise ParseError('无法识别虎牙直播间别名，请使用该主播的数字房间号', 400)
    return result
HUYA_HLS_HOSTS = frozenset({'hs.hls.huya.com', 'al.hls.huya.com', 'tx.hls.huya.com', 'txdirect.hls.huya.com'})
HUYA_MANIFEST_UA = 'HYSDK(Windows,30000002)_APP(pc_exe&7030003&official)_SDK(trans&2.29.0.5493)'

def allowed_hls_url(url: str) -> bool:
    if not cdn_url(url, ('hls.huya.com',)):
        return False
    parsed = urlsplit(url)
    return parsed.hostname in HUYA_HLS_HOSTS and bool(re.fullmatch('/(?:src|huyalive)/[A-Za-z0-9_-]{1,200}\\.m3u8', parsed.path))

def hls_url(line: dict, *, ratio: int=0) -> str:
    (name, base, anti) = (line.get(k, '') for k in ('sStreamName', 'sHlsUrl', 'sHlsAntiCode'))
    if not all((isinstance(v, str) for v in (name, base, anti))) or not re.fullmatch('[A-Za-z0-9_-]{1,200}', name) or type(ratio) is not int or (not 0 <= ratio <= 100000):
        return ''
    if base.startswith('http://'):
        base = 'https://' + base[7:]
    try:
        query = parse_qs(anti, keep_blank_values=True)
        expires = query['wsTime'][0]
        if any((len(v) != 1 for v in query.values())) or not re.fullmatch('[A-Za-z0-9_-]{1,64}', query['ctype'][0]) or (not re.fullmatch('[0-9a-fA-F]{32}', query['wsSecret'][0])) or (not re.fullmatch('[0-9a-fA-F]{1,16}', expires)) or (int(expires, 16) <= time.time()):
            return ''
    except (KeyError, ValueError, TypeError):
        return ''
    result = base.rstrip('/') + '/' + name + '.m3u8?' + anti
    if ratio and 'ratio' not in query:
        result += '&ratio=' + str(ratio)
    return result if allowed_hls_url(result) else ''

def rewrite_manifest(text: str, base: str) -> str:
    if not allowed_hls_url(base) or not text.startswith('#EXTM3U'):
        raise ParseError('虎牙未返回有效播放清单', 502)
    allowed_tags = {'EXTM3U', 'EXT-X-VERSION', 'EXT-X-TARGETDURATION', 'EXT-X-MEDIA-SEQUENCE', 'EXT-X-DISCONTINUITY-SEQUENCE', 'EXTINF', 'EXT-X-DISCONTINUITY', 'EXT-X-PROGRAM-DATE-TIME', 'EXT-X-INDEPENDENT-SEGMENTS', 'EXT-X-ENDLIST'}
    (output, segments, pending) = ([], 0, False)
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith('#'):
            if line[1:].split(':', 1)[0] not in allowed_tags or 'URI=' in line.upper():
                raise ParseError('暂不支持该虎牙清单格式', 502)
            if line.startswith('#EXTINF:'):
                if pending:
                    raise ParseError('虎牙播放清单格式异常', 502)
                pending = True
            output.append(line)
            continue
        try:
            child = urljoin(base, line)
            parsed = urlsplit(child)
        except ValueError:
            raise ParseError('虎牙清单包含无效分片地址', 502) from None
        if not pending or not cdn_url(child, ('hls.huya.com',)) or parsed.hostname not in HUYA_HLS_HOSTS or (not re.fullmatch('/(?:src|huyalive)/[A-Za-z0-9_-]{1,240}\\.ts', parsed.path)):
            raise ParseError('虎牙清单包含不允许的分片地址', 502)
        output.append(child)
        pending = False
        segments += 1
    if not segments or segments > 64 or pending:
        raise ParseError('虎牙播放清单为空或不完整', 502)
    return '\n'.join(output) + '\n'

async def fetch_manifest(session, url: str) -> str:
    if not allowed_hls_url(url):
        raise ParseError('不允许的虎牙清单地址', 403)
    try:
        async with asyncio.timeout(10), session.stream('GET', url, follow_redirects=False, timeout=8, headers={'User-Agent': HUYA_MANIFEST_UA, 'Cookie': '', 'Referer': ''}) as response:
            if response.status_code != 200:
                raise ParseError('虎牙播放清单暂不可用，请重新解析', 502)
            if response.headers.get('content-type', '').split(';', 1)[0].strip().lower() not in {'application/vnd.apple.mpegurl', 'application/x-mpegurl', 'audio/mpegurl', 'audio/x-mpegurl'}:
                raise ParseError('虎牙响应不是播放清单', 502)
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > 32768:
                    raise ParseError('虎牙播放清单过大', 502)
        return rewrite_manifest(body.decode('utf-8'), url)
    except (httpx.HTTPError, TimeoutError, UnicodeError, ValueError):
        raise ParseError('虎牙播放清单加载失败，请重新解析', 502) from None

def _line_key(line: dict):
    (cdn, base, name) = (line.get(k) for k in ('sCdnType', 'sHlsUrl', 'sStreamName'))
    if not all((isinstance(value, str) for value in (cdn, base, name))):
        return None
    try:
        parsed = urlsplit(base)
        return (cdn, parsed.hostname, parsed.path.rstrip('/') + '/' + name + '.m3u8')
    except ValueError:
        return None

class HuyaLiveParser(BaseParser):
    platform = 'huya_live'
    media_type = MediaType.VIDEO
    description = '虎牙直播（官方 HLS 直连）'

    @classmethod
    def match(cls, url: str) -> bool:
        return bool(room_name(url, 'huya.com'))

    async def parse(self, url: str, session) -> ParseResult:
        room = room_name(url, 'huya.com')
        if not room:
            raise ParseError('请输入有效的虎牙直播间链接')
        room = await numeric_room(room, session)
        payload = await metadata(session, 'GET', 'https://mp.huya.com/cache.php', params={'m': 'Live', 'do': 'profileRoom', 'roomid': room})
        data = payload.get('data') or {}
        if payload.get('status') != 200 or not isinstance(data, dict):
            raise ParseError('虎牙直播间不存在或接口暂不可用')
        if data.get('liveStatus') != 'ON':
            raise ParseError('主播当前未开播')
        if data.get('isRoomPay') or data.get('roomPay'):
            raise ParseError('暂不支持付费直播间')
        stream = data.get('stream') or {}
        if not isinstance(stream, dict):
            raise ParseError('虎牙直播间数据异常', 502)
        lines = stream.get('baseSteamInfoList') or []
        if not isinstance(lines, list):
            raise ParseError('虎牙直播间数据异常', 502)
        hls = stream.get('hls')
        if 'hls' in stream and (not isinstance(hls, dict) or not isinstance(hls.get('multiLine'), list)):
            raise ParseError('虎牙 HLS 线路清单异常，请重新解析', 502)
        advertised = hls.get('multiLine') if isinstance(hls, dict) else None
        choices = {}
        if isinstance(advertised, list):
            for item in advertised:
                if not isinstance(item, dict) or not isinstance(item.get('url'), str) or (not isinstance(item.get('cdnType'), str)):
                    continue
                try:
                    parsed = urlsplit(item['url'])
                    bitrate = parse_qs(parsed.query).get('ratio', ['0'])[0]
                    if re.fullmatch('[0-9]{1,6}', bitrate) and int(bitrate) <= 100000:
                        choices[item['cdnType'], parsed.hostname, parsed.path] = int(bitrate)
                except (ValueError, TypeError):
                    continue
            lines = [line for line in lines if isinstance(line, dict) and _line_key(line) in choices]

        def priority(line):
            rate = line.get('iWebPriorityRate', 0)
            return (not bool(re.fullmatch('HS[0-9]*', str(line.get('sCdnType', '')))), -(rate if type(rate) is int else 0))
        lines = sorted((line for line in lines if isinstance(line, dict)), key=priority)
        direct = next((link for line in lines if (link := hls_url(line, ratio=choices.get(_line_key(line), 0)))), '')
        if not direct:
            raise ParseError('虎牙未返回可用的 HLS 直链，请重新解析', 502)
        (live, profile) = (data.get('liveData') or {}, data.get('profileInfo') or {})
        if not isinstance(live, dict) or not isinstance(profile, dict):
            raise ParseError('虎牙直播间数据异常', 502)
        return ParseResult(platform=self.platform, media_type=self.media_type, title=live.get('introduction') or live.get('roomName') or '虎牙直播', author=profile.get('nick') or '', direct_url=direct, extra={'is_live': True, 'stream_format': 'hls', 'direct_only': True, 'manifest_only': True, 'room_id': str(profile.get('profileRoom') or room)})
