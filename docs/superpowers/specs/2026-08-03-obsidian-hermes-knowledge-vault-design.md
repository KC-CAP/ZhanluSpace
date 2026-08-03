# Obsidian + Hermes 个人与团队知识库设计

日期：2026-08-03

状态：待用户审阅

目标版本：MVP

## 1. 摘要

本项目构建一套以普通 Markdown 和 Git 为基础的个人与团队知识库工作流：

- Obsidian 是知识阅读、目录、编辑、反向链接和图谱可视化界面。
- Obsidian 插件提供文件拖入、网址导入、任务状态和 Git 操作入口。
- 本地 Knowledge Worker 调用 Hermes 完成抓取、解析、OCR、知识提取、关联分析和 Markdown 变更生成。
- Git 保存知识版本、来源、关系、目录和审计记录。
- GitHub Pull Request 是团队唯一审核与合入界面，不建设额外审核工作台。
- GitHub Actions 生成知识变更摘要并执行 Knowledge CI。

系统不依赖 Obsidian 保存知识关系。Obsidian Wikilink 是显示层，Frontmatter 中基于稳定 ID 的关系才是事实来源。因此知识库可以脱离 Obsidian 被其他工具解析、迁移和可视化。

## 2. 目标

### 2.1 个人知识库

- 用户可在 Obsidian 中拖入文件或粘贴网址。
- 系统保留原始素材并自动提取知识点。
- 系统可新建知识文档、补充现有文档并建议强关系。
- 系统自动维护可自定义目录和索引。
- 低风险变更在 Knowledge CI 通过后可自动合入本地 `main`。
- 高风险变更必须由用户查看变更清单和 Git Diff 后确认。
- 所有知识变化均可追溯和回滚。

### 2.2 团队知识库

- 所有成员可读取完整团队知识库，不提供目录级或文档级保密。
- 贡献者可在个人分支导入素材、修改知识和编辑目录。
- 贡献者不能直接写入 `main`，只能提交 GitHub Pull Request。
- 所有 Pull Request 只需一名合格审核者批准。
- 审核者不得是最后一次推送可审核变化的人。
- Knowledge CI 必须通过，未解决的审核对话必须清空。
- 合入后团队成员通过 Git Pull 在 Obsidian 中获取最新知识。

## 3. 非目标

MVP 不包含：

- 独立 Web 或桌面知识库界面。
- 独立审核工作台。
- 实时多人协同编辑。
- 同一仓库中的目录级、字段级或文档级权限。
- Obsidian Mobile 上运行本地 Hermes Worker。
- PPTX、XLSX、音频和视频解析。
- 完整企业搜索门户或通用 RAG 问答产品。
- 由 AI 绕过 Git 审核直接修改团队 `main`。

## 4. 设计原则

1. **Markdown 是正式知识格式。** 数据应当可读、可迁移并可在无 Obsidian 环境下解析。
2. **原始素材不可变。** 纠错写入知识文档，不覆盖历史来源。
3. **Git Diff 是最终变更事实。** Worker 状态、向量库和缓存都不是知识事实。
4. **AI 只生成提案。** 团队变更必须通过 Pull Request；个人高风险变更必须确认。
5. **正式关系少而明确。** 不要求每篇文档至少包含若干双链，避免图谱噪声。
6. **来源优先。** 每个重要结论必须能够追溯到来源 ID。
7. **可重建内容不进 Git。** 向量库、全文索引、OCR 缓存和模型输出缓存留在本地运行目录。
8. **故障不污染 Vault。** 生成和验证先在暂存区完成，通过后才一次性应用。

## 5. 产品形态

### 5.1 Obsidian 插件

插件只提供必要的流程入口，不重做 Obsidian 或 GitHub 已有界面。MVP 包含：

- 文件拖放区。
- 网页 URL 输入框。
- 导入并分析命令。
- 处理阶段、当前模型和数据去向提示。
- 打开导入清单命令。
- 在系统 Git 工具中打开 Diff 的命令。
- 个人模式的确认并合入操作。
- 团队模式的 Commit、Push 和创建 Pull Request 操作。
- 合入后提示同步最新 `main`。

插件不负责 PDF 解析、OCR、模型推理、知识关系判断或多文件写入。

### 5.2 Local Knowledge Worker

Worker 负责所有重任务：

- 网页获取和正文规范化。
- 文本、PDF、DOCX 和图片解析。
- OCR 和提取质量评估。
- 来源 ID 与 SHA-256 计算。
- 现有知识检索与查重。
- Hermes Skill 加载和模型调用。
- 知识文档与关系变更编译。
- 本地验证和风险分类。
- 导入清单生成。

插件启动短生命周期 Worker 任务，并通过结构化本地协议接收状态事件。MVP 不要求常驻网络服务，也不开放局域网端口。

### 5.3 Git Controller

Git Controller 是 Worker 的受限模块，负责：

- 检查工作区是否干净。
- 检查 `main` 是否与远端同步。
- 创建 `knowledge/<date>-<slug>` 分支。
- 检查 Git LFS 是否安装并可用。
- 将已验证的暂存结果一次性应用到知识分支。
- 生成 Commit。
- 团队模式 Push 分支并创建 GitHub Pull Request。
- 个人模式按照风险策略合入本地 `main`。

MVP 可以复用本机 `git`、`git-lfs` 和已认证的 GitHub CLI，避免插件保存 GitHub Token。

### 5.4 GitHub

GitHub 提供：

- Pull Request Diff、行级评论、批准、请求修改和合入。
- CODEOWNERS 自动请求领域审核者。
- 受保护 `main` 分支。
- Knowledge CI 必需检查。
- 知识变更摘要自动更新。
- 完整提交、审核和回滚历史。

GitHub Copilot 的 Pull Request 摘要可以作为可选通用摘要，但不能替代知识库专用摘要。

## 6. 运行架构

```text
Obsidian Plugin
    |
    | local structured task protocol
    v
Local Knowledge Worker
    |-- Source Pipeline
    |-- Hermes Adapter
    |-- Change Compiler
    |-- Local Validator
    `-- Git Controller
            |
            | commit / push
            v
GitHub Pull Request
    |-- Knowledge CI
    |-- Knowledge PR Summary
    `-- One human approval
            |
            v
          main
            |
            v
Team members pull and open the Vault in Obsidian
```

Hermes 不能直接访问团队 `main`。Worker 只向 Hermes 提供本次任务暂存区、允许读取的知识上下文和结构化输出要求。

## 7. 仓库结构

Git 仓库根目录同时是 Obsidian Vault：

```text
team-knowledge/
├── inbox/                         # 分支内待处理素材；main 通常为空
├── sources/                       # 不可变来源
│   ├── web/<source-id>/source.md
│   └── files/<source-id>/
│       ├── source.md              # 来源元数据与提取文本
│       └── original.<ext>         # Git LFS
├── knowledge/                     # 正式知识文档
│   ├── topics/
│   ├── entities/
│   ├── methods/
│   └── ...                        # 团队可通过 PR 调整
├── attachments/                   # 知识文档引用的附件
├── archive/                       # 被取代但保留的知识
├── _meta/
│   ├── schema.md                  # 字段、状态和关系规则
│   ├── taxonomy.md                # 允许的类型、目录和标签
│   ├── index.md                   # 自动维护的导航索引
│   └── ingests/<ingest-id>.md     # 每次导入的审计清单
├── .obsidian/                     # 仅跟踪必要的团队配置
├── .github/
│   ├── CODEOWNERS
│   ├── pull_request_template.md
│   └── workflows/knowledge-ci.yml
├── .gitattributes                 # Git LFS 规则
├── .gitignore
└── README.md
```

### 7.1 进入 Git 的内容

- 正式知识 Markdown。
- 来源记录、提取文本、来源指纹和原始文件。
- 知识文档使用的附件。
- Schema、分类、索引和逐次导入清单。
- 共享 Obsidian 配置、PR 模板、CODEOWNERS 和 CI 规则。

`.obsidian/` 采用白名单跟踪：团队只提交插件启用清单、必要的核心插件配置和本项目插件的非敏感默认设置。`workspace*.json`、最近文件、窗口布局、设备状态、缓存以及包含本地绝对路径的配置一律忽略。插件凭证永不写入 `.obsidian/`。

### 7.2 不进入 Git 的内容

- 向量数据库和全文搜索索引。
- OCR、下载和网页抓取缓存。
- 模型响应缓存。
- API Key、模型凭证和 GitHub Token。
- Hermes 会话、个人偏好和个人长期记忆。
- Obsidian 设备布局、最近打开文件和本地状态。
- `.knowledge-runtime/` 下的任务暂存数据。

### 7.3 Git LFS

PDF、DOCX、图片及其他二进制原件由 Git LFS 管理。Markdown、来源记录和提取文本仍由普通 Git 管理，以保持 Pull Request Diff 可读。

MVP 需要监控 Git LFS 存储与下载用量。当仓库规模超过团队配额或频繁更新大文件时，后续版本可迁移为对象存储；来源 ID 和内容 SHA-256 不随存储后端变化。

## 8. 数据模型

### 8.1 来源文档

```yaml
---
id: source:sha256:<digest>
kind: web | file | image
title: Hermes knowledge base practices
original_name: hermes-practices.pdf
source_url: https://example.com/article
content_sha256: <digest>
ingested_at: 2026-08-03T10:00:00+08:00
submitted_by: github-user
extractor: pdf-text-v1
extraction_quality: high | medium | low
data_policy: personal | team-approved
---
```

同一内容 SHA-256 只保存一份正式来源。不同 URL 指向相同内容时，来源记录增加别名，不重复生成知识。相同 URL 内容变化时，生成新的来源修订并保留旧修订。

### 8.2 知识文档

```yaml
---
id: concept:hybrid-search
type: topic | entity | method | comparison | note
status: draft | confirmed | contested | superseded | archived
confidence: 0.82
sources:
  - source:sha256:<digest>
relations:
  - type: supports
    target: concept:knowledge-retrieval
    evidence: source:sha256:<digest>
    confidence: 0.82
created: 2026-08-03
updated: 2026-08-03
---
```

重要段落使用 Markdown 脚注或来源标记关联具体来源 ID。Frontmatter 中的 `sources` 不能替代段落级来源标记。

### 8.3 正式关系

允许的 MVP 关系类型：

- `supports`
- `contradicts`
- `refines`
- `supersedes`
- `implements`
- `example_of`

关系以稳定知识 ID 为目标，不以文件路径或文件名为目标。文档移动或重命名不会破坏正式关系。

`related_to` 之类无明确语义的弱关系不自动写入正式数据。向量检索得到的相似关系只用于候选召回，除非达到规则阈值并通过适用的人工确认。

### 8.4 Obsidian 显示层

Worker 根据正式关系生成文档内的“相关知识”区块：

```markdown
<!-- knowledge-relations:start -->
## 相关知识

- 支持：[[知识检索]]
- 反驳：[[全量双向链接策略]]
<!-- knowledge-relations:end -->
```

Worker 只能改写两个标记之间的派生内容，不能覆盖用户在其他位置编写的正文。Knowledge CI 扫描所有知识文档的稳定 ID，并验证 Frontmatter 关系与 Wikilink 显示区块一致。Frontmatter 是事实来源，Wikilink 区块是可重新生成的派生显示。

## 9. 素材导入流程

任务状态：

```text
Queued
  -> Acquiring
  -> Extracting
  -> Compiling
  -> Validating
  -> Ready
  -> Committed
  -> Merged (personal) | PR Open (team)
```

任一处理中状态失败后进入 `Paused`。任务可以重试或取消。

### 9.1 规范化

- 将网页、文本、PDF、DOCX 或图片转换为规范化文本。
- 保存原件、来源元数据、提取文本和内容指纹。
- 评估提取质量。

### 9.2 查重

- 使用内容 SHA-256 识别完全重复来源。
- 使用 URL 与历史指纹识别网页变化。
- 使用关键词、稳定 ID 和语义检索查找现有知识候选。

### 9.3 知识编译

Hermes 对每个候选知识文档选择一种动作：

- `create`：创建新知识。
- `supplement`：补充现有知识。
- `support`：加入新的支持证据。
- `contradict`：记录冲突观点，不覆盖旧观点。
- `supersede`：建议新知识取代旧知识。
- `cite-only`：只增加来源引用。
- `no-change`：素材没有带来有效变化。

Hermes 不得因为弱语义相似而批量改写页面，也不要求新页面包含固定数量的链接。

### 9.4 暂存与验证

所有下载、OCR、Hermes 输出和候选文件先写入：

```text
.knowledge-runtime/jobs/<job-id>/
```

只有本地验证全部完成后，Worker 才一次性把来源、知识文档、索引和导入清单应用到当前知识分支。

### 9.5 导入清单

`_meta/ingests/<ingest-id>.md` 永久记录：

- 来源 ID、来源位置和内容指纹。
- 新增、修改、移动和归档的文件。
- 正式关系变化。
- 冲突、低置信内容和未解决警告。
- Hermes、Skill、模型、Schema 和规则版本。
- 提交者、处理时间和 Knowledge CI 结果。

GitHub Action 读取导入清单和实际 Diff，生成 Pull Request 描述，并检查两者一致。

## 10. 风险与合入策略

### 10.1 低风险

同时满足以下条件才属于低风险：

- 仅新增来源、新建知识或补充未确认内容。
- 不反驳或取代已确认知识。
- 不删除、归档、重命名或批量移动文档。
- 不修改 Schema、分类、CODEOWNERS 或 CI。
- 提取质量为高或中。
- 未检测到敏感信息或来源授权警告。
- 本次修改的既有知识文档不超过 10 篇。该默认阈值可在 `_meta/schema.md` 中通过治理 PR 调整。
- Knowledge CI 全部通过。

个人模式可自动 Commit 并合入本地 `main`。

### 10.2 高风险

下列任一条件使任务成为高风险：

- 反驳或取代已确认知识。
- 删除、归档、重命名或批量移动文档。
- 修改超过 10 篇既有知识文档，或超过仓库治理规则中更新后的安全阈值。
- 修改 Schema、分类或治理文件。
- OCR 或正文提取质量低。
- 来源可能包含敏感信息或授权状态不明确。
- 分支基线落后并与 `main` 产生冲突。

个人模式必须人工确认。团队模式仍然提交普通 Pull Request，并由一名合格审核者批准。

## 11. 团队权限与 GitHub 规则

### 11.1 角色

- **Reader**：Clone/Pull，并在 Obsidian 阅读。
- **Contributor**：创建分支、运行导入、提交 Pull Request。
- **Domain Owner**：审核所属知识目录。
- **Knowledge Admin**：维护 Schema、分类和知识治理规则。
- **Repo Admin**：管理成员、Actions、分支规则、密钥和 Git LFS。

小团队可以由同一人承担多个角色。

### 11.2 CODEOWNERS

示例：

```text
/knowledge/ai/**      @team-ai-reviewers
/knowledge/legal/**   @team-legal-reviewers
/sources/**           @source-curators
/_meta/**             @knowledge-admins
/.github/**            @repo-admins
/.github/CODEOWNERS    @repo-admins
```

### 11.3 `main` 保护规则

- 禁止直接 Push、Force Push 和分支删除。
- 必须通过 Pull Request。
- 必须通过 Knowledge CI。
- 必须解决全部 Review 对话。
- 必须获得一名合格审核者批准。
- 必须要求最后一次可审核 Push 由另一人批准，或在新提交后使旧审批失效。
- 涉及 CODEOWNERS 路径时自动请求相应负责人。

所有仓库成员可以读取全部内容；不实现同一仓库内的保密分区。

## 12. 模型与数据策略

### 12.1 个人库

个人用户可以选择：

- 本地模型。
- 自带 API Key 的云端模型。
- Hermes 支持的其他模型供应商。

处理开始前，插件显示本次模型、服务地址和将发送的数据范围。

### 12.2 团队库

团队管理员通过受审配置统一指定：

- 允许的模型供应商。
- 允许的模型名称。
- 本地或团队网关地址。
- 哪类素材可以发送到云端。
- 脱敏或禁止发送规则。

策略配置进入 Git 并通过 Pull Request 审核。API Key 和访问凭证不进入 Git，只存储在本地安全存储或团队密钥管理系统。

## 13. MVP 支持的素材

支持：

- 网页 URL 和 HTML。
- Markdown 和 TXT。
- 文本 PDF。
- 扫描 PDF。
- DOCX。
- PNG、JPG 和 WebP 图片 OCR。

延后：

- PPTX。
- XLSX。
- ENEX 和其他专有笔记导出格式。
- 音频和视频。

解析器选择必须经过许可证审查。MVP 不在未确认分发影响的情况下打包 AGPL 或 GPL 依赖。

## 14. Knowledge CI

Pull Request 必需检查包括：

1. Frontmatter 格式合法。
2. 稳定知识 ID 唯一。
3. 来源 ID、内容指纹和引用完整。
4. 正式关系目标存在。
5. 正式关系类型属于 Schema。
6. Obsidian Wikilink 显示区块与正式关系一致。
7. 无失效链接。
8. 自动索引与实际文件一致。
9. 无未声明的重复来源或重复知识。
10. 冲突和低提取质量已显式标记。
11. 文件路径未越界。
12. 确定性的密钥和个人信息模式扫描未发现意外凭证或明显敏感信息。
13. 二进制原件由 Git LFS 正确追踪。
14. 导入清单与实际 Git Diff 一致。

CI 的确定性检查决定是否允许合入；需要语义判断的敏感内容提示以及其他 LLM 评价只能作为评论或警告，不能单独成为不可解释的合入门槛。

## 15. Pull Request 摘要

Knowledge PR Summary Action 自动写入：

- 素材列表与来源类型。
- 新增知识文档。
- 修改、移动或归档的知识文档。
- 新增、删除或改变的正式关系。
- 冲突、低置信内容和高风险原因。
- Knowledge CI 结果。
- Hermes、Skill、模型和 Schema 版本。

摘要由实际 Diff 与导入清单共同生成，不能只依赖模型自由概括。审核仍使用 GitHub 原生 Files Changed 和行级评论。

## 16. 失败处理

- **网页抓取失败**：任务暂停，保留 URL 和日志，不修改 Vault。
- **文件解析失败**：保留原件和错误，不生成正式知识。
- **OCR 质量低**：保存候选提取结果，任务标记高风险并等待确认。
- **模型超时**：有限次数重试；允许切换团队策略许可的模型后续跑。
- **模型输出不合法**：拒绝应用，保存原始响应供诊断。
- **工作区不干净**：禁止开始新导入，提示用户先提交、暂存或取消现有变化。
- **分支落后**：要求同步或 Rebase；重新计算受影响文档。
- **本地验证失败**：任务停留在暂存区，不修改正式文件。
- **GitHub CI 失败**：Pull Request 禁止合入。
- **完全重复素材**：不重复写入知识，只记录来源别名或重复事件。
- **用户取消**：删除未应用的任务暂存数据；已进入 Git 的内容必须显式 Revert。

## 17. 安全边界

导入的网页和文件全部视为不可信数据：

- 素材中的命令、提示词和操作要求不得覆盖系统规则。
- Hermes 不得执行素材中出现的 Shell 命令。
- Hermes 只能访问显式授权的来源、知识上下文和任务暂存目录。
- 文件名和压缩内容必须防止路径穿越。
- 解析器必须限制文件大小、页数、解压体积和处理时间。
- Worker 不向模型传输本地路径、凭证或无关知识。
- 日志不得记录 API Key、Token 或完整敏感正文。
- GitHub Action 使用最小权限的 `GITHUB_TOKEN`。

## 18. 测试策略

### 18.1 单元测试

- 来源 ID 与 SHA-256。
- 各格式解析器。
- Frontmatter 和关系解析。
- 风险分类。
- 任务状态机。
- 变更清单与 PR 摘要。
- Knowledge CI 各检查器。

### 18.2 固定样本测试

维护一组授权测试素材和期望结果：

- 新建知识。
- 补充知识。
- 冲突观点。
- 重复来源。
- 网页内容变化。
- 扫描 PDF 和低质量 OCR。
- 恶意提示词和异常文件名。

同一版本 Worker、Hermes Skill、Schema 和固定模型配置应产生结构稳定、可审查的变更。

### 18.3 集成测试

- 临时 Git 仓库中的分支、Commit、Merge 和 Rebase。
- Git LFS 跟踪与缺失检测。
- 任务暂存区到正式分支的一次性应用。
- 模拟 GitHub Pull Request 和必需检查。
- 模拟 Hermes 超时、非法输出和恢复。

### 18.4 端到端测试

- Obsidian 拖入文件到个人低风险自动合入。
- Obsidian 粘贴网址到个人高风险确认。
- 团队导入、Push、创建 Pull Request、通过 CI、一次审核并合入。
- 合入后其他成员 Pull 并在 Obsidian 正常查看目录、链接和图谱。
- 中途终止 Worker 后恢复或安全取消。

## 19. MVP 成功标准

- 用户能在 Obsidian 中通过拖文件或粘贴 URL 启动导入。
- 每个正式知识结论都能追溯到至少一个来源 ID。
- 完全重复素材不会生成重复知识。
- Worker 中断不会留下半完成正式文档。
- 文档移动或重命名不会破坏基于稳定 ID 的正式关系。
- 无 Obsidian 环境也能解析知识、来源和关系。
- 个人低风险任务可自动合入，高风险任务不会自动合入。
- 团队 `main` 无法绕过 Pull Request、CI 和一名他人审核者。
- Pull Request 自动摘要准确列出实际新增、修改和关系变化。
- 合入后的 Vault 可被其他成员 Pull 并直接用 Obsidian 打开。

## 20. 分阶段交付边界

### 阶段一：本地个人闭环

- Vault 模板和 Schema。
- Source Pipeline。
- Hermes Adapter 与 Change Compiler。
- 本地 Validator。
- Obsidian 导入侧栏。
- 个人分支、Diff、风险确认和合入。

### 阶段二：团队 GitHub 闭环

- GitHub Push 和 Pull Request 创建。
- CODEOWNERS 与 `main` 保护规则。
- Knowledge CI。
- Knowledge PR Summary。
- Git LFS 配置和用量提示。

### 阶段三：质量与扩展

- 更多解析器。
- 团队模型网关与更强数据策略。
- 大规模索引和关系质量工具。
- 对象存储后端。
- 可选移动端远程 Worker。

## 21. 参考资料

- [参考文章：Hermes + Obsidian 本地知识库实践](https://zhuanlan.zhihu.com/p/2046722255548372917)
- [参考讨论：如何用 Hermes 搭建个人知识库](https://www.zhihu.com/question/2042009581841371508)
- [Hermes Agent](https://github.com/NousResearch/hermes-agent)
- [Hermes `llm-wiki` Skill](https://github.com/NousResearch/hermes-agent/blob/main/skills/research/llm-wiki/SKILL.md)
- [Hermes Agent MIT License](https://github.com/NousResearch/hermes-agent/blob/main/LICENSE)
- [Obsidian License Overview](https://obsidian.md/license)
- [Obsidian Pricing and Sync](https://obsidian.md/pricing)
- [GitHub CODEOWNERS](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners)
- [GitHub Protected Branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)
- [GitHub Copilot Pull Request Summary](https://docs.github.com/en/copilot/how-tos/copilot-on-github/copilot-for-github-tasks/create-a-pr-summary)
- [GitHub Git LFS](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-git-large-file-storage)
- [liumeixin/hermes-wiki-skills](https://github.com/liumeixin/hermes-wiki-skills)
