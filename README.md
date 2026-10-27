# VRCHAT-Parser
可以访问我的解析网站和好友一起观看视频和音乐xingvrchat.com

该项目面向 VRChat 的多平台单视频、单曲与直播链接解析核心，提供解析原理、实现代码与调用示例。

## 解析范围

| 类型 | 平台 | 当前实现 |
| --- | --- | --- |
| 单视频 | B站、抖音 | 视频 ID / 短链识别、平台信息与播放地址；B站可选获取有权访问的 DASH 音视频地址 |
| 单曲 | 网易云、QQ音乐、酷狗 | 歌曲 ID / hash、元信息与播放地址；Cookie 由调用者自行提供 |
| 直播间 | B站、抖音、虎牙、斗鱼 | 房间识别、开播状态与平台 HLS / FLV 地址 |

只处理一条媒体或直播间链接。详细纳入和排除清单见 [范围说明](docs/SCOPE.md)，接口流程见 [解析原理](docs/ALGORITHMS.md)。

## 用本地网页开始

想直接粘贴链接、查看和复制结果，可使用随包提供的本机网页。无需 Docker、Redis、Node.js 或单独部署远端服务器。

- **Windows**：安装 Python 3.11+，下载并解压仓库，在项目根目录双击 `start-local.cmd`。
- **macOS / Linux**：安装 Python 3.11+，在项目根目录运行 `bash start-local.sh`。
- 首次运行会在项目内建立 `.venv` 并安装依赖，需要联网；之后打开终端提示的 **http://127.0.0.1:8765**。
- 也可按下面的步骤手动安装后执行 `python -m vrc_parsers.web`，或使用 `vrc-parser-web` 命令。

完整的下载、安装、端口更换、更新与排错步骤见 **[本地部署和使用指南](docs/LOCAL_USE.md)**。仓库仍为 Private 时，下载需要仓库访问权限。

网页支持单链接解析、结果复制、原始 JSON 和可选的本人 Cookie；不会持久化 Cookie 或历史。Cookie 会发送给本机服务，并在必要时经 HTTPS 发给对应的平台，不会自动发给作者网站。想和好友一起使用，点击页面的好友入口，会打开作者的网站，不会把本地链接、Cookie 或结果自动带过去。

## 快速使用

需要 Python 3.11 或更新版本：

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
python -m vrc_parsers.web
```

手动安装完成后打开终端提示的本机地址。使用命令行解析一条链接：

```sh
python -m vrc_parsers 'https://www.bilibili.com/video/BV1xx411c7mD'
```

上面的媒体 ID 是调用格式示例，请替换为你有权访问的真实链接。也可以使用安装后的 `vrc-parse` 命令。

```python
import asyncio
from vrc_parsers import parse_one

result = asyncio.run(parse_one("https://live.bilibili.com/123"))
print(result.to_dict())
```

返回结果包含平台、媒体类型、标题、作者、封面、时长、平台媒体 URL、Referer 和额外格式信息。未返回 URL、平台拒绝或链接不支持时抛出 `ParseError`。`requires_proxy` 沿用结果模型的兼容字段，表示播放端可能需要额外请求头或转发；本库不会启动代理服务。

需要账户访问时，由调用者向 `parse_one(..., cookie=...)` 传入自己的有效 Cookie。命令行可用 `--cookie-env 环境变量名` 从自己设置的变量读取；请不要把 Cookie 直接写进源码、Issue 或命令行历史。B站 `--bili-mode authenticated` 取账户可访问的普通播放地址，`--bili-mode dash` 另返回 `extra.dash` 中的视频/音频地址；不自动合流或转码。

## 验证与限制

```sh
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v
python tools/check_export.py
```

测试使用人工构造的响应和 mock，其中部分使用 HTTPX MockTransport，不访问真实平台。它们验证协议处理和单条输入边界，不能证明当前每个平台、地区、账号或媒体均可用。

本机网页另有内存 HTTP 请求处理回归和真实 TCP 集成用例；若宿主禁止本地监听，后者会明确显示跳过，不能视为 TCP 或真实浏览器验收通过。

本机网页固定只监听 `127.0.0.1`。不要将这个本机入口映射到公网或局域网；多人使用请打开页面中的好友入口。

- 平台接口、签名和风控会变化；结果 URL 可能短时有效，需要重新解析。
- 解析成功表示得到平台地址，VRChat 播放还取决于 HLS/FLV、编码、请求头与播放器兼容性。FLV 和音视频分离的 DASH 不能保证直接播放。
- QQ音乐当前提供服务器直连接口的单曲实现，未包含原站的私人节点；风控环境下不保证等同原站可用性。
- 网易云返回实际解析到的签名地址，可能绑定请求出口 IP；不同网络的播放器未必能直接使用，不包含原站二次签发/媒体代理流程。
- 酷狗默认只保留基础查询/回退接口及参数签名算法示例，没有内置原站登录签名常量或完整会员网关分支。
- 本库面向本地调用，限制已知平台域名并拒绝 IP/异常跳转，但不提供 DNS 固定或公网服务所需的完整 SSRF 隔离。服务化时须另做网络出口、资源、身份与日志边界。
- 不提供会员权限绕过或第三方账户凭据。仅解析你有权访问的内容，并遵守平台规则。

## 许可与第三方依赖

[完整许可](LICENSE) · [中文许可说明](docs/LICENSING.md) · [第三方依赖说明](THIRD_PARTY_NOTICES.md)。MIT 允许使用、修改、分发和商业使用；在副本或软件的重要部分中，须保留版权及完整许可声明。版权声明包含原作者和上游仓库地址，分发时请一并保留。

原作者：**dxx-lot**。项目出处：**[dxx-lot/VRCHAT-Parser](https://github.com/dxx-lot/VRCHAT-Parser)**。

本项目许可只覆盖作者有权授权的代码，不改变 HTTPX 等依赖各自的许可，也不授予第三方平台媒体或账户权限。
