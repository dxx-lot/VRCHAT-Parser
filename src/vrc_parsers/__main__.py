import argparse
import asyncio
import json
import os
import sys

from . import ParseError, parse_one


def main() -> None:
    parser = argparse.ArgumentParser(description="解析一个视频、歌曲或直播间链接")
    parser.add_argument("url")
    parser.add_argument("--bili-mode", choices=["progressive", "authenticated", "dash"], default="progressive")
    parser.add_argument("--cookie-env", help="从指定环境变量读取自己的 Cookie；不在命令行中传凭据")
    args = parser.parse_args()
    cookie = os.environ.get(args.cookie_env, "") if args.cookie_env else ""
    try:
        result = asyncio.run(parse_one(args.url, cookie=cookie, bili_mode=args.bili_mode))
    except ParseError as error:
        print(json.dumps({"error": error.message, "code": error.code}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1) from None
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
