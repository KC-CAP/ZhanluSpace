# Zhanlu Knowledge Vault

这是一个由普通 Markdown、YAML Frontmatter 和 Git 组成的可移植知识库。Obsidian 是推荐的阅读、编辑与关系可视化界面，但不是数据运行时依赖。

## 目录

- `sources/`：按内容 SHA-256 保存的不可变来源记录与原件。
- `knowledge/`：正式知识文档，目录可通过 Git 变更调整。
- `archive/`：被取代或归档但仍需保留的知识。
- `_meta/`：Schema、分类、索引与每次导入清单。

每篇知识文档使用稳定 ID 引用来源和其他知识。文件移动或重命名不改变 ID。Frontmatter 中的 `relations` 是正式关系；“相关知识”区块由 Worker 生成，只用于 Obsidian 显示，不应手工编辑。

导入前请确保仓库工作区干净。低风险个人变更会在通过确定性校验后自动快进合入本地 `main`，高风险变更会保留在 `knowledge/<日期>-<任务>` 分支等待确认。
