# 第三方依赖与来源

当前运行依赖为 `httpx==0.28.1`，以及用于安全版本约束的 `certifi>=2026.10.19`，通过 pip 获取，未将其源码或二进制复制到此仓库。

- 上游项目：[encode/httpx](https://github.com/encode/httpx)
- 对应版本许可入口：[httpx 0.28.1 LICENSE.md](https://github.com/encode/httpx/blob/0.28.1/LICENSE.md)
- HTTPX 对应版本采用 `BSD-3-Clause`，独立于本项目的 MIT 许可；本仓库没有重新许可 HTTPX。
- certifi 的许可为 `MPL-2.0`，上游为 [certifi/python-certifi](https://github.com/certifi/python-certifi)，本项目不修改或打包其证书文件。最低版本用于排除 [GHSA-6q48-6c7w-9gw2](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2) 所涉及的旧信任库。
- 构建工具为 setuptools；离线测试使用 Python 标准库 unittest 与 HTTPX MockTransport。

HTTPX 的间接依赖由安装环境解析，应保留各自许可。发布打包环境、镜像或依赖合集时，另生成该实际环境的完整依赖与许可清单。

原理文档与请求参数描述来自本项目既有解析实现，不包含平台媒体内容，也不提供第三方账号或访问授权。对平台接口的调用须由使用者自行遵守其规则。
