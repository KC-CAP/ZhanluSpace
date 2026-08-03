# 手工验收

## 前置条件

1. Vault 根目录就是 Git 仓库根目录，当前分支为 `main`，工作区没有未提交内容。
2. Hermes 已配置可用的本地或 BYOK 模型；执行 `hermes -z "只回复 OK"` 能完成推理。
3. 在插件设置中点击“检测环境”，Python Worker、Hermes、Git 均通过。

## 安装插件

```powershell
.\scripts\install-plugin.ps1 `
  -VaultPath "D:\path\to\vault" `
  -HermesPath "$env:LOCALAPPDATA\hermes\hermes-agent\venv\Scripts\hermes.exe" `
  -NodePath "C:\path\to\node.exe" `
  -PnpmPath "C:\path\to\pnpm.cmd"
```

先在 Obsidian 的“第三方插件”中启用 Zhanlu Knowledge。重启后，通过左侧书本加号图标或命令面板的“打开斩律知识导入”打开侧栏。

## 低风险导入

1. 拖入一个新的 `.md` 或 `.txt` 文件。
2. 导入前核对页面展示的 Hermes 配置与数据去向。
3. 点击“开始导入”，观察读取、提取、编译、校验、提交和合入状态。
4. 结果应为“已自动合入个人知识库”；Vault 位于 `main`，且 `git status --short` 为空。
5. 在 Obsidian 中打开 `knowledge/` 下的新文档，确认 Frontmatter、来源引用和派生关系区可读。
6. 再次导入同一文件，结果应为“没有需要更新的知识”，不得生成重复来源或知识文档。

## 高风险确认

1. 导入一份明确修订或反驳现有知识的素材。
2. 结果应停在“需要你确认后合入”，`main` 不发生变化。
3. 点击“查看 Git Diff”，粘贴并运行复制的只读命令。
4. 核对分支、变更文件和风险原因后点击“确认合入”。
5. 插件必须使用结果中精确的 branch/head 完成快进合入；主分支已前进且提案分支被删除。

## 失败与取消

- 导入过程中点击“取消”，Worker/Hermes 子进程应被终止，Vault 不得出现半成品变更。
- 关闭网络或配置无效模型时，应出现经过脱敏的错误代码，不显示 API Key、Token 或完整模型响应。
- 工作区存在未提交内容时，导入应在调用 Hermes 前失败并提示先处理 Git 工作区。
