"""单链接解析库。平台按显式白名单导入。"""
from .base import MediaType, ParseError, ParseResult
from .client import parse_one

__all__ = ["MediaType", "ParseError", "ParseResult", "parse_one"]
__version__ = "0.2.1"
