"""Read-only export layout and manifest checker; never deletes files."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    ".gitignore", "AGENTS.md", "README.md", "LICENSE", "pyproject.toml", "THIRD_PARTY_NOTICES.md",
    "docs/ALGORITHMS.md", "docs/SCOPE.md", "docs/LICENSING.md", "docs/LOCAL_USE.md",
    "start-local.cmd", "start-local.sh",
    "examples/parse_one.py", "tools/check_export.py", "tests/test_core.py", "tests/test_music.py", "tests/test_web.py",
    *{"src/vrc_parsers/" + n + ".py" for n in (
        "__init__", "__main__", "base", "utils", "client", "bilibili", "douyin", "netease",
        "qqmusic", "kugou", "bilibili_live", "douyin_live", "huya_live", "douyu_live", "live_direct", "web")},
    *{"src/vrc_parsers/web_assets/" + name for name in ("index.html", "app.css", "app.js")},
}
FORBIDDEN_IMPORTS = {"main", "settings", "redis", "sqlalchemy", "fastapi", "minecraft_integration"}
FORBIDDEN_NAMES = {"_parse_playlist", "_ne_playlists", "_ne_playlist_items", "renew_playurl_token", "_get_pxy_redis", "_kugou_cookie"}


def files():
    result = {}
    for path in ROOT.rglob("*"):
        parts = path.relative_to(ROOT).parts
        if any(p in {".git", ".venv", "__pycache__", "build", "dist"} or p.endswith(".egg-info") for p in parts):
            continue
        if path.is_symlink():
            raise ValueError("Symlink not allowed: " + str(path.relative_to(ROOT)))
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT).as_posix()
        if path.stat().st_nlink != 1:
            raise ValueError("Hard link not allowed: " + rel)
        result[rel] = path
    return result


def main():
    manifest = json.loads((ROOT / "export-manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or manifest.get("license_status") != "owner-selected-mit":
        raise ValueError("Unexpected export manifest state")
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    if not license_text.startswith("MIT License\n") or "Copyright (c) 2026 dxx-lot (https://github.com/dxx-lot/VRCHAT-Parser)" not in license_text:
        raise ValueError("MIT copyright and upstream attribution missing")
    actual = files()
    if set(actual) != EXPECTED | {"export-manifest.json"}:
        raise ValueError("Layout drift: extra=%s missing=%s" % (sorted(set(actual) - EXPECTED - {"export-manifest.json"}), sorted(EXPECTED - set(actual))))
    records = manifest["files"]
    if len(records) != len(EXPECTED) or {r["path"] for r in records} != EXPECTED:
        raise ValueError("Manifest file allowlist mismatch")
    for record in records:
        rel = record["path"]
        raw = actual[rel].read_bytes()
        if hashlib.sha256(raw).hexdigest() != record["sha256"] or len(raw) != record["size"]:
            raise ValueError("Content drift: " + rel)
        text = raw.decode("utf-8")
        if re.search(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", text):
            raise ValueError("Private key marker in " + rel)
        if rel.startswith("src/"):
            inspected = text
            if rel == "src/vrc_parsers/web_assets/index.html":
                # 作者明确允许的普通好友导航链接；不能作为 API 或资源地址。
                allowed = 'href="https://xingvrchat.com/"'
                if inspected.count(allowed) != 1:
                    raise ValueError("Friend navigation link must occur exactly once")
                inspected = inspected.replace(allowed, 'href="AUTHORIZED_FRIEND_PORTAL"')
            if re.search(r"(?:xingvrchat|dxxvodio)\.com|(?:/Users/|/www/wwwroot/)", inspected):
                raise ValueError("Private deployment reference in " + rel)
            tree = ast.parse(text, filename=rel) if rel.endswith(".py") else None
            for node in ast.walk(tree) if tree else ():
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    names = [a.name.split(".")[0] for a in node.names] if isinstance(node, ast.Import) else [(node.module or "").split(".")[0]]
                    if set(names) & FORBIDDEN_IMPORTS:
                        raise ValueError("Application import in " + rel)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (node.name in FORBIDDEN_NAMES or node.name.startswith("_pl_")):
                    raise ValueError("Excluded function in " + rel)
                if isinstance(node, ast.Constant) and node.value == "song_list":
                    raise ValueError("Batch result key in " + rel)
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and re.search(r"/api/(?:v\d+/)?(?:playlist|v\d+/playlist)|playlist/detail|musicu.*playlist", node.value, re.I):
                    raise ValueError("Batch endpoint in " + rel)
        if rel.endswith(".py"):
            compile(text, rel, "exec")
    print("PASS: %d allowlisted files + manifest; hashes, UTF-8, syntax and application boundaries verified." % len(EXPECTED))
    print("MIT license selected; Git metadata privacy and real platform acceptance are outside this check.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("FAIL:", exc, file=sys.stderr)
        raise SystemExit(1) from None
