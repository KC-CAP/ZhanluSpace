# Vault Schema v1

## 来源记录

来源 ID 为 `source:sha256:<64 位小写十六进制>`，且摘要必须与 `content_sha256` 相同。

```yaml
id: source:sha256:<digest>
kind: web | file | image
title: 来源标题
original_name: example.md
source_url: https://example.com/article
content_sha256: <digest>
ingested_at: 2026-08-03T12:00:00Z
submitted_by: local-user
extractor: markdown-v1
extraction_quality: high | medium | low
data_policy: personal | team-approved
```

## 知识记录

知识 ID 由类型前缀、冒号和稳定 slug 组成。`sources` 至少包含一个存在的来源 ID；重要段落还应在正文中标出具体来源。

```yaml
id: method:hybrid-search
type: topic | entity | method | comparison | note
status: draft | confirmed | contested | superseded | archived
confidence: 0.82
sources:
  - source:sha256:<digest>
relations:
  - type: supports
    target: topic:knowledge-retrieval
    evidence: source:sha256:<digest>
    confidence: 0.82
created: 2026-08-03
updated: 2026-08-03
```

正式关系只允许 `supports`、`contradicts`、`refines`、`supersedes`、`implements` 和 `example_of`。相似度召回不是正式关系。

## 生成区块

Worker 只可替换以下标记之间的内容，标记之外的正文必须原样保留：

```markdown
<!-- knowledge-relations:start -->
## 相关知识

_暂无正式关系。_
<!-- knowledge-relations:end -->
```

个人模式默认仅在不反驳/取代确认知识、不删除/移动文件、不修改治理文件、抽取质量不低且修改既有知识不超过 10 篇时判定为低风险。
