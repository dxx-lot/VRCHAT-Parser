"""安装后运行：python examples/parse_one.py 'https://www.bilibili.com/video/BV…'"""
import asyncio
import json
import sys

from vrc_parsers import parse_one


async def main():
    result = await parse_one(sys.argv[1])
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
