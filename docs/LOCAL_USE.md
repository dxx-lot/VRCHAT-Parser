# 本机网页使用指南

本网页在你的电脑上运行，用于解析单条视频、音乐或直播链接。请使用 Python 3.11 或更新版本。先运行对应系统的版本检查命令，确认显示版本为 3.11 或更高；如果默认 Python 版本较旧，可把后续命令中的 `py -3` 或 `python3` 改为已安装的新版本命令，例如 `py -3.12` 或 `python3.12`。平台接口和媒体格式会变化，解析结果不保证始终可用，也不保证能被每个播放器播放。

## 下载项目

可直接克隆本仓库或下载 ZIP。使用 Git 克隆：

```sh
git clone https://github.com/dxx-lot/VRCHAT-Parser.git
cd VRCHAT-Parser
```

也可以从仓库页面下载 ZIP 并解压，然后在终端进入解压后的 `VRCHAT-Parser` 目录。

## 安装并启动

### Windows

先在 PowerShell 中检查 Python 版本；确认 `py -3 --version` 显示 3.11 或更高后，运行：

```powershell
py -3 --version
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe -m vrc_parsers.web
```

直接运行虚拟环境中的 Python，不需要修改 PowerShell 执行策略。如果 `py -3 --version` 显示低于 3.11，请将这组命令里的 `py -3` 换成已安装的版本选择器，例如 `py -3.12`。

### macOS

先检查 `python3 --version`，确认显示 3.11 或更高，再运行：

```sh
python3 --version
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python -m vrc_parsers.web
```

如果 `python3 --version` 显示低于 3.11，请将这组命令里的 `python3` 换成已安装的新版本命令，例如 `python3.12`。

### Linux

先检查 `python3 --version`，确认显示 3.11 或更高，再运行：

```sh
python3 --version
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python -m vrc_parsers.web
```

如果 `python3 --version` 显示低于 3.11，请将这组命令里的 `python3` 换成已安装的新版本命令，例如 `python3.12`。

启动后，在本机浏览器打开：

```text
http://127.0.0.1:8765
```

需要使用其他端口时，在启动命令末尾添加 `--port 9000`，并将浏览器地址中的 `8765` 换成所选端口。结束使用时，在运行服务的终端按 `Ctrl+C`。

仓库也提供便捷启动脚本：Windows 可运行 `start-local.cmd`，macOS/Linux 可运行 `bash start-local.sh`。脚本首次启动会安装项目依赖。

更新到当前仓库版本后，在项目目录运行：

```sh
python -m pip install --upgrade .
```

若使用虚拟环境，Windows PowerShell 运行 `.\.venv\Scripts\python.exe -m pip install --upgrade .`；macOS/Linux 运行 `.venv/bin/python -m pip install --upgrade .`。

## 使用与隐私

1. 在页面粘贴一条受支持的媒体链接，然后选择“开始解析”。
2. 只有在你需要访问本人有权查看的内容时，才展开“高级选项”填写自己的 Cookie。Cookie 只用于本次请求，在本机内存中处理，并在必要时经 HTTPS 发给对应平台；页面不会将它保存到浏览器存储，也不会自动发给作者的网站。使用后可点“清空”。如果输入 HTTP 链接且本次请求需要凭据，请更换为平台的 HTTPS 链接。
3. B站模式可选普通播放、本人可访问的播放或 DASH 音视频地址。DASH 可能需要兼容的播放器分别处理音视频。
4. 标题、作者、解析地址和原始 JSON 会显示在当前页面。关闭或刷新页面后，页面本身不保留这些内容。

请勿在共享电脑填写 Cookie。不要分享包含本人授权信息的内容。解析出的地址可能短时有效，并由平台策略决定能否访问。

## 支持范围与限制

项目支持单条 B站、抖音视频，网易云、QQ音乐、酷狗单曲，以及 B站、抖音、虎牙、斗鱼直播间链接。页面不处理歌单、批量任务或其他未纳入范围的链接。

返回地址的媒体格式由平台决定，可能包括渐进式音视频、HLS、FLV 或 DASH。VRChat 及其他播放器对封装、编码、请求头和音视频分离的支持各不相同。得到解析地址不代表媒体一定能播放；平台接口、签名和地区策略也可能变化。

“和好友一起使用”按钮只会打开 `https://xingvrchat.com/`。它不会附带当前输入、Cookie 或解析结果。

## 常见问题

- **网页打不开**：先确认启动命令仍在运行，再使用终端打印的 `127.0.0.1` 地址。这个地址只属于运行服务的电脑，不能作为好友分享地址。
- **端口已占用**：给启动命令追加 `--port 9000`，浏览器也改为 `http://127.0.0.1:9000`，不用关闭其他应用。
- **首次安装失败**：先确认 Python 版本至少为 3.11，网络能够下载依赖，且终端位于项目根目录。Linux 缺少 venv 组件时，按发行版说明安装 Python 的 venv 支持。
- **提示找不到模块或页面资源**：使用指南中的虚拟环境 Python 重新执行 `-m pip install --upgrade .`，再启动本机服务。
- **解析失败或媒体不能播放**：先换一条普通、公开的单视频或单曲链接测试；地区、账号权限、平台风控和格式都会影响结果，不要把解析失败当作本机安装失败。

本机网页会直接请求相应的平台来解析，首次安装也需要下载依赖；它不会自动把本地内容上传到作者网站。多人使用请点页面的好友入口，不要给本机服务配置端口映射。
