# parsers/utils.py —— 公共工具
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# 手机版 UA：抖音接口必须用它
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


def cookie_str_to_dict(cookie: str) -> dict[str, str]:
    out = {}
    for part in cookie.split(";"):
        part = part.strip()
        if "=" in part:
            k, _, v = part.partition("=")
            out[k] = v
    return out