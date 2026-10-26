"""网易云音乐单曲解析。只接受单曲链接，不处理歌单。"""

from __future__ import annotations

import re

from .base import BaseParser, MediaType, ParseError, ParseResult
from .utils import USER_AGENT, cookie_str_to_dict

_SONG = re.compile(r"(?:/|#)?song\?[^#]*?id=(\d+)", re.IGNORECASE)
_SHORT_LINK = re.compile(r"https?://(?:www\.)?163cn\.tv/[A-Za-z0-9]+", re.IGNORECASE)
_API = "https://music.163.com/api"


def _is_collection_url(url: str) -> bool:
    return re.search(
        r"(?:/|#)(?:playlist|album)(?:\?|/)|(?:playlist|album)(?:id|_id)=",
        url,
        re.IGNORECASE,
    ) is not None


def personal_track_error(item: object, allow_paid: bool) -> str:
    """检查上游播放信息是否代表可用的完整曲目。"""
    if not isinstance(item, dict):
        return "上游播放信息格式错误"
    if item.get("freeTrialInfo") is not None:
        return "当前账号只有试听权限，不能用于完整解析"
    try:
        fee = int(item.get("fee") or 0)
    except (TypeError, ValueError):
        return "上游没有返回可确认的歌曲权限"
    if not allow_paid and fee in (1, 4):
        return "该歌曲需要会员或单独购买，当前策略不允许解析"
    return ""


class NeteaseParser(BaseParser):
    platform = "netease"
    media_type = MediaType.AUDIO
    description = "网易云音乐单曲"
    patterns = [
        re.compile(r"music\.163\.com/(?:#/)?song\?[^#]*id=\d+", re.IGNORECASE),
        _SHORT_LINK,
    ]

    def __init__(self, cookie: str = ""):
        self.cookie = cookie
        # 调用方可按需置为 False；默认保留源解析器允许付费曲目的行为。
        self.allow_paid = True

    def _headers(self) -> dict[str, str]:
        return {"User-Agent": USER_AGENT, "Referer": "https://music.163.com/"}

    def _cookies(self) -> dict[str, str]:
        cookies = {"os": "pc", "appver": "8.9.70"}
        cookies.update(cookie_str_to_dict(self.cookie))
        return cookies

    async def _resolve_song_id(self, url: str, session) -> str:
        if _is_collection_url(url):
            raise ParseError("不支持歌单、专辑等集合链接；请提供网易云音乐单曲链接")
        match = _SONG.search(url)
        if match:
            return match.group(1)
        if not _SHORT_LINK.fullmatch(url.strip()):
            raise ParseError("无法识别网易云音乐单曲链接")
        try:
            response = await session.get(url, headers=self._headers())
        except Exception as exc:
            raise ParseError("网易云短链无法展开为单曲链接") from exc
        final_url = str(response.url)
        if _is_collection_url(final_url):
            raise ParseError("短链指向歌单或专辑；不支持集合链接，请提供单曲链接")
        match = _SONG.search(final_url)
        if not match:
            raise ParseError("网易云短链未指向可识别的单曲")
        return match.group(1)

    async def parse(self, url: str, session) -> ParseResult:
        song_id = await self._resolve_song_id(url, session)
        item: dict = {}
        restricted = False
        for level in ("exhigh", "higher", "standard"):
            try:
                response = await session.get(
                    f"{_API}/song/enhance/player/url/v1",
                    params={"ids": f"[{song_id}]", "level": level, "encodeType": "mp3"},
                    headers=self._headers(),
                    cookies=self._cookies(),
                )
                data = response.json().get("data") or [{}]
                candidate = data[0] if data else {}
                if candidate and candidate.get("url"):
                    reason = personal_track_error(candidate, self.allow_paid)
                    if reason:
                        restricted = True
                        continue
                    item = candidate
                    break
            except ParseError:
                raise
            except Exception:
                continue

        if not item:
            if restricted:
                raise ParseError("该歌曲需要会员、单独购买或只有试听权限，无法提供完整播放地址", 403)
            raise ParseError("该歌曲当前没有可用的完整播放地址", 404)

        song: dict = {}
        try:
            response = await session.get(
                f"{_API}/song/detail",
                params={"ids": f"[{song_id}]"},
                headers=self._headers(),
                cookies=self._cookies(),
            )
            songs = (response.json() or {}).get("songs") or []
            song = songs[0] if songs else {}
        except Exception:
            # 播放地址已确认时，元数据不可用不应阻断单曲解析。
            pass

        duration_ms = song.get("duration")
        return ParseResult(
            platform=self.platform,
            media_type=MediaType.AUDIO,
            title=song.get("name") or f"网易云音乐-{song_id}",
            author=" / ".join(artist.get("name", "") for artist in song.get("artists", [])),
            cover_url=(song.get("album") or {}).get("picUrl"),
            duration=int(duration_ms // 1000) if duration_ms else None,
            direct_url=item["url"],
            requires_proxy=False,
            referer="https://music.163.com/",
        )
