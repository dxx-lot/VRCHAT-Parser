#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
    python3 -c 'import sys; assert sys.version_info >= (3, 11), "需要 Python 3.11 或更新版本"'
    python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import vrc_parsers; assert vrc_parsers.__version__ == "0.2.1"' >/dev/null 2>&1; then
    printf '%s\n' '首次启动：安装本项目和依赖，需要联网。'
    .venv/bin/python -m pip install .
fi
exec .venv/bin/python -m vrc_parsers.web "$@"
