# parsers/base.py —— 解析器框架，以后加平台只需要新建文件继承它
from __future__ import annotations

import inspect
import re
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, ClassVar


class MediaType(str, Enum):
    AUDIO = "audio"
    VIDEO = "video"


class ParseError(Exception):
    def __init__(self, message: str, code: int = 400):
        self.message = message
        self.code = code
        super().__init__(message)


@dataclass
class ParseResult:
    platform: str
    media_type: MediaType
    title: str
    author: str = ""
    cover_url: str | None = None
    duration: int | None = None
    direct_url: str | None = None
    requires_proxy: bool = False
    referer: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["media_type"] = self.media_type.value
        return d


_REGISTRY: dict[str, type["BaseParser"]] = {}


class BaseParser(ABC):
    platform: ClassVar[str] = "base"
    patterns: ClassVar[list[re.Pattern]] = []
    media_type: ClassVar[MediaType | None] = None
    description: ClassVar[str] = ""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.platform != "base" and not inspect.isabstract(cls):
            _REGISTRY[cls.platform] = cls

    @classmethod
    def match(cls, url: str) -> bool:
        return any(p.search(url) for p in cls.patterns)

    @abstractmethod
    async def parse(self, url: str, session) -> ParseResult:
        """解析链接。失败抛 ParseError。"""


def match_parser(url: str) -> BaseParser | None:
    for cls in _REGISTRY.values():
        if cls.match(url):
            return cls()
    return None


def list_platforms() -> list[dict]:
    return [
        {
            "platform": cls.platform,
            "media_type": cls.media_type.value if cls.media_type else None,
            "description": cls.description,
        }
        for cls in sorted(_REGISTRY.values(), key=lambda c: c.platform)
    ]