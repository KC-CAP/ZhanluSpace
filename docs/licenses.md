# 依赖许可证审计

审计日期：2026-08-03。版本来自本项目锁文件和已验证虚拟环境；发布前应重新运行审计。

## 运行时直接依赖

| 组件 | 已验证版本 | 许可证 | 用途 |
|---|---:|---|---|
| beautifulsoup4 | 4.15.0 | MIT | HTML 正文清洗 |
| httpx | 0.28.1 | BSD-3-Clause | URL 获取 |
| pydantic | 2.13.4 | MIT | 协议与提案 Schema |
| PyYAML | 6.0.3 | MIT | Frontmatter 渲染/解析 |
| zod | 4.4.3 | MIT | Obsidian 插件协议校验 |

Python 传递运行时依赖使用 MIT、BSD-3-Clause、MPL-2.0 或 PSF-2.0。`pnpm licenses list --json` 显示插件依赖和开发工具使用 MIT、Apache-2.0、ISC 或 BSD-3-Clause。Phase 1 没有捆绑 AGPL/GPL 运行时代码。

Hermes Agent 与 Obsidian 是用户单独安装的外部程序，不进入插件 bundle、Python wheel 或本仓库；其各自许可不因本项目安装脚本而改变。Obsidian npm 包在这里仅提供 MIT 许可的 API 类型，并被生产 bundle 标记为 external。

## 仓库内容边界

以下内容没有被 Git 跟踪，也不应进入发行提交：

- 用户素材正文、抓取网页、知识作业暂存和模型原始响应；
- API Key、GitHub Token、Hermes 配置密钥或 Obsidian 用户设置；
- `.venv/`、`.knowledge-runtime/`、`node_modules/`、构建缓存和测试缓存；
- Hermes 模型缓存、Hermes 安装目录、Obsidian 可执行文件或安装包；
- 本机手工测试 Vault。

安装脚本只把生产插件文件、其独立 Worker 虚拟环境和不含密钥的工具路径写入用户明确指定的 Vault 插件目录。个人/团队知识内容的版权与授权仍由素材提交者和知识库所有者负责。
