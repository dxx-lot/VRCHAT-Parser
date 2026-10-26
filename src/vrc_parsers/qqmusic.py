"""QQ 音乐单曲解析。只使用当前客户端到平台的直连流程。"""

from __future__ import annotations

import re

from .base import BaseParser, MediaType, ParseError, ParseResult
from .utils import USER_AGENT

QQMUSIC_API = "https://u.y.qq.com/cgi-bin/musicu.fcg"
_SHORT_LINK = re.compile(r"https?://(?:c\.)?y\.qq\.com/[A-Za-z0-9/?=&._%-]+", re.IGNORECASE)


def _extract_url(text: str) -> str:
    match = re.search(r"https?://[^\s\u3001\u3002，,；;]+", text)
    return match.group(0) if match else text.strip()


def _songmid_from_text(text: str) -> str | None:
    match = (
        re.search(r"songmid=([A-Za-z0-9]+)", text, re.IGNORECASE)
        or re.search(r"songmid/([A-Za-z0-9]+)", text, re.IGNORECASE)
        or re.search(r"songDetail/([A-Za-z0-9]+)", text, re.IGNORECASE)
    )
    return match.group(1) if match else None


def _is_collection_url(url: str) -> bool:
    return re.search(
        r"/playlist/|/album(?:detail)?/|(?:playlist|disstid|taogeid|albumid|album_id)=",
        url,
        re.IGNORECASE,
    ) is not None


def _qq_uin(cookie: str) -> str:
    match = re.search(r"(?:^|;)\s*uin=o?0*(\d+)", cookie, re.IGNORECASE)
    return match.group(1) if match else "0"


async def extract_songmid_from_url(url: str, session, headers: dict[str, str] | None = None) -> str:
    """从 QQ 音乐单曲链接（包括短链）提取 songmid。"""
    url = _extract_url(url)
    if _is_collection_url(url):
        raise ParseError("不支持歌单、专辑等集合链接；请提供 QQ 音乐单曲链接")
    songmid = _songmid_from_text(url)
    if songmid:
        return songmid
    if not _SHORT_LINK.fullmatch(url):
        raise ParseError("QQ 音乐链接解析失败：无法识别单曲 ID")
    try:
        response = await session.get(url, headers=headers or {})
    except Exception as exc:
        raise ParseError("QQ 音乐短链无法展开为单曲链接") from exc
    final_url = str(response.url)
    if _is_collection_url(final_url):
        raise ParseError("短链指向歌单或专辑；不支持集合链接，请提供单曲链接")
    songmid = _songmid_from_text(final_url)
    if not songmid:
        raise ParseError("QQ 音乐短链未指向可识别的单曲")
    return songmid


class QQMusicParser(BaseParser):
    platform = "qqmusic"
    media_type = MediaType.AUDIO
    description = "QQ 音乐单曲（服务器直连）"
    patterns = [
        re.compile(r"y\.qq\.com/.+(?:songDetail|songmid)", re.IGNORECASE),
        _SHORT_LINK,
    ]

    def __init__(self, cookie: str = ""):
        self.cookie = cookie

    def _headers(self) -> dict[str, str]:
        headers = {"User-Agent": USER_AGENT, "Referer": "https://y.qq.com/"}
        if self.cookie.strip():
            headers["Cookie"] = self.cookie.strip()
        return headers

    async def parse(self, url: str, session) -> ParseResult:
        songmid = await extract_songmid_from_url(url, session, self._headers())
        payload = {
            "req_0": {
                "module": "music.vkey.GetVkeyServer",
                "method": "CgiGetVkey",
                "param": {
                    "guid": "7332953645",
                    "songmid": [songmid],
                    "songtype": [0],
                    "uin": _qq_uin(self.cookie),
                    "loginflag": 1,
                    "platform": "20",
                },
            },
        }
        direct_url = ""
        try:
            response = await session.post(QQMUSIC_API, json=payload, headers=self._headers())
            body = response.json() or {}
            data = (body.get("req_0") or {}).get("data") or {}
            infos = data.get("midurlinfo") or []
            purl = infos[0].get("purl") if infos else ""
            sip = (data.get("sip") or [""])[0]
            if purl and sip:
                direct_url = sip + purl
        except Exception:
            pass

        if not direct_url:
            try:
                fallback_response = await session.get(
                    "https://c.y.qq.com/v8/fcg-bin/fcg_play_single_song.fcg",
                    params={
                        "songmid": songmid,
                        "format": "json",
                        "platform": "yqq.json",
                        "fromtag": "1",
                    },
                    headers=self._headers(),
                )
                fallback_data = (fallback_response.json() or {}).get("data") or []
                direct_url = fallback_data[0].get("url") if fallback_data else ""
            except Exception:
                direct_url = ""

        if not direct_url:
            raise ParseError("QQ 音乐单曲暂不可用", 404)

        title, author, cover = "QQ 音乐", "", ""
        detail_payload = {
            "req_0": {
                "module": "music.pf_song_detail_svr",
                "method": "get_song_detail_yqq",
                "param": {"song_mid": songmid},
            },
        }
        try:
            detail_response = await session.post(
                QQMUSIC_API, json=detail_payload, headers=self._headers()
            )
            info = (
                ((detail_response.json() or {}).get("req_0") or {}).get("data") or {}
            ).get("track_info") or {}
            if info:
                title = info.get("title") or title
                author = " / ".join(singer.get("name", "") for singer in info.get("singer", []))
                cover = info.get("cover") or ""
        except Exception:
            # 元数据请求失败时仍可返回已取得的播放地址。
            pass

        return ParseResult(
            platform=self.platform,
            media_type=MediaType.AUDIO,
            title=title,
            author=author,
            cover_url=cover or None,
            direct_url=direct_url,
            requires_proxy=False,
            referer="https://y.qq.com/",
        )
