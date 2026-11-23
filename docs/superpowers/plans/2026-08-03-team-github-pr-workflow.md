# Zhanlu 团队知识库实施方案

> 状态：方案完善，待用户评审；本文件是团队版实施计划，不代表功能已实现。

## 目标与已确认约束

- 团队成员在 Obsidian 中阅读和导入知识；GitHub Pull Request 是唯一审核和合入界面，不建设独立审核工作台。
- 团队库对所有仓库成员可读；不做目录、文档或字段级保密。
- 每个知识变更都必须经 PR；一名有权限且不同于提交人的审核者批准即可合入。
- 当前阶段仅承诺已支持的单个 Markdown/TXT 文件和 HTTP/HTTPS 网页导入。PDF、DOCX、OCR、批量导入仍单独排期，不是团队版前置条件。
- Hermes 在每位成员本机运行并生成结构化提案；Worker 校验、写文件并执行 Git 操作。CI 不重新调用模型。
- 团队成员统一使用负责人 DeepSeek API Key 的费用方案时，密钥只由负责人通过可信的密码管理器/安全渠道发给受信成员，保存在各自机器的 Hermes 本机配置中，绝不提交到 Git、Vault 或 PR。后续团队人数或成本控制需要时，再增加带成员认证和额度限制的模型网关。
- 需要独立审批的仓库至少有两位 GitHub 成员。仅一位成员时无法同时满足“提交人不能批准自己的 PR”；该场景继续使用个人模式，或等增加第二位审核者后启用团队保护规则。

## 推荐架构

继续使用本地优先方案，不新增 Web 服务：

```text
Contributor Obsidian Plugin
  -> Local Worker -> Hermes -> DeepSeek API
  -> local branch + commit -> GitHub PR
                               -> Knowledge CI + deterministic summary
                               -> one independent approval -> main
  <- another member fetch/pull on a clean main
```

Obsidian 插件只负责导入入口、状态和 GitHub PR 操作入口。GitHub 原生界面展示 Diff、评论、批准和合并；Actions 负责确定性校验与变更摘要。模型只生成候选知识，不能直接写远端 `main`。团队模式禁止本地自动合入，包括低风险新增。

## 团队使用流程

1. **管理员初始化仓库**：从 Vault 模板创建专用知识仓库，安装 Zhanlu 插件，设置默认分支 `main`、启用 Actions 和分支规则，添加初始 Schema/分类配置。
2. **成员加入**：每位成员用自己的 GitHub 账号获得仓库读写权限；Clone 仓库并用 Obsidian 打开 Vault。插件团队设置记录仓库坐标和 `team` 模式，不记录访问 Token。
3. **导入前同步**：成员确认工作区干净，Worker `fetch` 远端并快进到最新 `main`。若本地有未提交修改或分支落后不可快进，停止导入并给出可操作说明，不自动 stash、reset 或覆盖。
4. **本地生成提案**：成员导入单个 Markdown/TXT 或 URL。Worker 保存来源快照，调用本机 Hermes，确定性生成知识文档、关系、索引和 ingest manifest；通过本地校验后提交到唯一命名的贡献分支。
5. **推送并开 PR**：插件用 GitHub CLI 的现有登录态推送分支并创建可直接审核的 PR。相同 ingest ID 重试时更新已有 PR，不重复生成提交或 PR。
6. **CI 校验及生成说明**：GitHub Actions 校验提交内容，并以实际 Diff 和 manifest 生成可更新的 Markdown 摘要，列出新增/修改/取代文档、关系变化、来源、风险和检查结果。
7. **一人审核合入**：审核者在 GitHub Files changed 中阅读差异、评论并批准；所有必需检查通过、评论线程解决、分支基线符合规则后，由有权限的人合并。
8. **其他成员同步**：成员在 Obsidian 中点“同步团队知识库”；仅在干净工作区和可快进时自动更新。否则保留本地数据，展示冲突路径和恢复指引。

## PR 内容与策略

PR 标题和摘要从 manifest、文件差异和 CI 结果确定性生成，不使用模型自由生成的文字作为事实。正文至少包含：

- ingest ID、提交者、基于哪个 `main` commit、来源类型和可访问来源 URL；
- 新增、补充、反驳、取代、归档的知识条目；
- 新增/变更/删除的正式关系以及稳定 ID；
- 实际文件清单、提取质量、风险理由、编译器/Schema 版本；
- 本次 CI 检查结果和本地复核方式。

默认 PR **不附加重复的原始素材正文到描述**；如团队知识仓策略要求保留来源，则来源快照随分支正常提交并在 PR 文件差异中审阅。摘要中不得包含 API Key、GitHub Token、本机绝对路径、模型私有日志或未纳入 PR 的素材。

所有团队变更都开 PR，风险等级影响摘要和审核重点，不影响 PR 是否必需。删除、取代、低质量提取、Schema/分类变更应在摘要中突出风险。首次 MVP 不自动合并，不自动批准，不自动删除未合入分支，不 force-push。

## GitHub 仓库一次性配置

- 保护 `main`：禁止直接 push 和 force-push；要求 PR、Knowledge CI 通过、至少一个来自非提交者的批准、分支与目标分支最新、所有 review thread 已解决。
- 配置 Actions 最小权限。验证 job 只读；如果摘要需要写回 PR，单独使用仅有 `pull-requests: write` 的 job。
- 为知识路径和治理路径提供可选 CODEOWNERS 模板；小团队可以让同一位管理员承担多个领域职责，但提交者仍不能批准自己的 PR。
- Fork PR 不获得仓库密钥，不执行需要凭据的步骤。PR 创建依赖 GitHub CLI 的本机登录态；令牌由 CLI/系统凭据存储管理，插件不保存明文令牌。
- 初期不要求 Git LFS；现有 Markdown/TXT/网页材料不需要额外二进制存储服务。

## 数据、费用与权限

- GitHub 仓库权限决定谁能 clone、push 分支及审核；仓库内所有文件都对仓库成员可读，不能把“全员可读”误当作公开互联网可读。
- 团队模式写明组织/仓库名称、配置的模型和服务地址，以及导入时会发送给模型的素材正文；成员每次提交前都可取消。
- 若全员使用负责人 DeepSeek API Key：由负责人单独安全分发，密钥保存在各成员本机 Hermes 配置；仓库只记录非敏感的 provider/model 策略。负责人自行管理 Key 轮换和费用告知。不得把密钥写入 `.obsidian/`、`data.json`、GitHub 仓库变量可下载文件、PR、日志或测试快照。
- 第一版不实现共享 API Key 网关、复杂用量计费或本地加密代理；如团队无法安全分发同一 Key，应改为每人自带 API Key，或在独立后续阶段实现网关后再启用团队模型策略。
- 仓库不得存放需要保密的材料；来源授权/许可仍需由提交者确认。PR 审核用于知识正确性，不替代内容授权检查。

## 失败与恢复规则

| 情况 | 处理 |
| --- | --- |
| 网络或 GitHub API 暂时不可用 | 保留本地贡献分支和 commit，显示“尚未提交 PR”，允许重试，不报告成功 |
| `main` 在导入期间前进 | push/开 PR 前再次比较基线；能安全 rebase 时提供明确操作，不自动改写已公开分支 |
| PR 创建超时/重复点击 | 以 ingest ID 查找已有 PR 后更新；找不到时提示手动检查，不盲目创建多份 |
| CI 失败 | PR 留在 Open/Draft 状态，显示失败检查链接和本地复现命令 |
| 审核请求修改 | Contributor 在同一分支提交修正；更新 PR 摘要和检查，旧批准按 GitHub 规则失效 |
| 远端出现冲突 | 不执行 reset-hard/强制覆盖；停止自动同步，保留双方修改并提供 GitHub/CLI 恢复步骤 |
| 成员本地有未提交修改 | 同步命令禁用；明确列出工作区状态，要求成员自行提交或暂存 |
| 成员离职/权限撤回 | 管理员通过 GitHub 撤销仓库权限；本地仓库仍需该成员自行移除，不将凭据保存到 Vault |

## 分阶段实施

### 阶段 A：团队仓库与本地团队模式

- 增加 `personal | team` 配置、仓库/默认分支/remote 校验和团队数据去向提示。
- 增加只读 fetch、创建唯一贡献分支、事务性提交和安全重试；团队模式永不本地 merge。
- 增加使用 GitHub CLI 登录态的 PR 创建/更新命令；失败时保留本地分支。
- 提供管理员初始化指南、成员安装与 Key 配置指南、团队 Vault 模板。
- 验收：两名成员各自 clone；一人导入后只能形成分支/PR，无法触碰 `main`；另一人能够 clone 阅读。

### 阶段 B：Knowledge CI 与 PR 摘要

- 将当前 Vault 校验逻辑整理为只读 CI 命令，校验 Frontmatter、稳定 ID、来源/关系、索引、Wikilink、manifest、允许路径和凭据扫描。
- 在 `.github/workflows/` 增加 fork 安全、最小权限的 Actions。
- 由实际 Git Diff 生成 PR 摘要，不重新运行 Hermes；使用 ingest ID 幂等更新。
- 提供 CODEOWNERS 与分支规则模板/操作文档。
- 验收：无效关系、重复 ID、路径越界、缺失来源、秘密扫描命中均阻断合入；有效 PR 的摘要与 Diff 一致。

### 阶段 C：安全同步与发布

- 增加团队同步状态：落后 commit 数、分支状态、工作区状态；仅 clean + fast-forward 可自动同步。
- 增加 `gh`/GitHub CLI 版本、登录身份、权限和远端分支状态诊断。
- 在专用测试仓库完成真实 PR 演练：提交者不可批准自己的 PR、另一人批准、CI 通过、合并、第二成员快进同步。
- 更新 README、Obsidian 使用手册、管理员/成员指南、隐私和恢复文档；明确团队模式与个人模式的行为差异。

## 实施时涉及的主要文件边界

- `apps/obsidian-plugin/src/settings.ts`：团队模式、仓库目标和非敏感模型策略设置。
- `apps/obsidian-plugin/src/main.ts`：注册团队命令/视图入口，不将 GitHub 审核 UI 搬进 Obsidian。
- `apps/obsidian-plugin/src/import-view.ts`、`presenter.ts`：导入状态、PR 状态、同步状态及用户可执行动作。
- `apps/obsidian-plugin/src/protocol.ts`、`worker-client.ts`：新增团队作业/PR/同步事件协议。
- `src/zhanlu_worker/git.py`：本地团队分支、基线校验、commit/push、fetch/fast-forward 与不覆盖保护。
- `src/zhanlu_worker/compiler.py`、`validation.py`：复用现有确定性编译与验证；团队专属约束独立封装。
- `src/zhanlu_worker/github.py`（新增）：封装 `gh` 调用、PR 查找/创建/更新、状态查询；所有进程参数使用参数数组，不拼接 shell。
- `src/zhanlu_worker/summary.py`（新增）：从可信 manifest 和 Git diff 生成机器可读及 Markdown 摘要，不调用模型。
- `scripts/validate_vault.py` 或现有验证 CLI：提供 CI 只读入口。
- `.github/workflows/knowledge-ci.yml`、`.github/CODEOWNERS.example`（新增）：最小权限 CI 与治理模板。
- `docs/`、`README.md`：管理员初始化、成员 onboarding、个人/团队模式差异、密钥处理和恢复步骤。

## 验收标准

1. 团队模式下所有导入都产生成员分支和 PR；任何路径都不会本地自动合并到 `main`。
2. PR 的知识变化摘要与提交 Diff、manifest 完全一致，并可追溯到 source ID、ingest ID、贡献者和最终 merge commit。
3. Knowledge CI 失败、无独立批准、分支过期或未解决评论时，GitHub 规则阻止合并。
4. 不同成员可在 clean main 上快进同步；有本地修改或冲突时系统停止并保留数据。
5. 仓库和日志中找不到 DeepSeek API Key、GitHub Token、本机绝对路径或 Hermes 私有运行记录。
6. PR 审核只使用 GitHub 原生界面，Obsidian 负责本地知识阅读、导入和同步。
7. 在临时 bare remote、两个克隆和一个真实测试 GitHub 仓库中完成端到端演练。

## 明确不纳入本次团队版

- 新建审核工作台或独立知识库 Web 界面。
- 实时多人共同编辑同一 Markdown 文件。
- 自动批准、自动合并、force-push 或清理未合入分支。
- 知识文件的保密分区、权限继承或 ACL。
- PDF、DOCX、OCR、PPTX、XLSX、图片、音频、视频解析及批量目录导入。
- 把 API Key 写入代码仓以方便团队成员共享。
