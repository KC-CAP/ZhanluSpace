# Local Personal Knowledge Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付一个桌面端 Obsidian 插件与本地 Python Worker，使用户可以拖入 Markdown/TXT 文件或粘贴网页 URL，经 Hermes 编译为可追溯的知识文档；低风险变更自动合入本地 `main`，高风险变更停留在独立分支等待用户确认。

**Architecture:** Obsidian 插件只负责输入、进度和确认交互，通过一次一进程的 JSONL stdio 协议调用 Worker。Worker 在 `.knowledge-runtime/jobs/<job-id>/` 中获取并规范化素材，调用 Hermes 生成严格结构化的知识提案，再由确定性代码校验、渲染 Frontmatter/Wikilink、计算风险并执行 Git 事务。Hermes 不直接写 Vault，正式关系以稳定 ID 和 YAML Frontmatter 为准。

**Tech Stack:** TypeScript 5、Obsidian Plugin API、Zod、Vitest、esbuild；Python 3.11+、Pydantic 2、PyYAML、httpx、BeautifulSoup、pytest；Hermes Agent CLI；Git。

## Global Constraints

- 本计划只覆盖个人本地闭环以及 Markdown、TXT、网页 URL/HTML；PDF、DOCX、图片 OCR 在下一份素材适配计划中实现。
- 团队 Push、GitHub Pull Request、CODEOWNERS、Actions 与分支保护在团队协作计划中实现。
- 所有实现遵循测试驱动：每个行为先写失败测试、确认失败原因，再实现最小代码并重新运行测试。
- 不向 Hermes 暴露 Vault 路径、Git 凭据或无关文档；素材内容按不可信数据处理。
- Hermes 只返回结构化提案。Frontmatter、关系展示区、索引、导入清单和 Git 操作均由确定性代码生成。
- 不覆盖用户未授权的脏工作区；Worker 在发现 `git status --porcelain` 非空时必须在写入前失败。
- 所有子进程使用参数数组启动，禁止拼接 Shell 命令。
- `.knowledge-runtime/`、模型响应、网页缓存、插件本地设置与凭据不进入 Git。
- 本阶段使用 `pnpm` 与 Python `venv`，不引入 Docker、数据库、常驻端口或后台服务。

---

## Task 1: Scaffold the Worker, Plugin, and Shared Protocol Fixtures

**Files:**

- Create: `pyproject.toml`
- Create: `src/zhanlu_worker/__init__.py`
- Create: `src/zhanlu_worker/__main__.py`
- Create: `tests/conftest.py`
- Create: `tests/test_package.py`
- Create: `apps/obsidian-plugin/package.json`
- Create: `apps/obsidian-plugin/tsconfig.json`
- Create: `apps/obsidian-plugin/esbuild.config.mjs`
- Create: `apps/obsidian-plugin/manifest.json`
- Create: `apps/obsidian-plugin/versions.json`
- Create: `apps/obsidian-plugin/src/main.ts`
- Create: `apps/obsidian-plugin/styles.css`
- Create: `apps/obsidian-plugin/vitest.config.ts`
- Create: `protocol/fixtures/start-file.json`
- Create: `protocol/fixtures/start-url.json`
- Create: `protocol/fixtures/confirm.json`
- Modify: `.gitignore`

- [x] **Step 1: Add the minimal Python smoke test**

Create `tests/test_package.py`:

```python
def test_package_exposes_version() -> None:
    import zhanlu_worker

    assert zhanlu_worker.__version__ == "0.1.0"
```

- [x] **Step 2: Run the smoke test and verify that it fails**

Run:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest tests/test_package.py -q
```

Expected: FAIL because `zhanlu_worker` or `__version__` does not exist.

- [x] **Step 3: Implement the package and command entry point**

Define `__version__ = "0.1.0"` and a console script named `zhanlu-worker` that calls `zhanlu_worker.__main__:main`. Add runtime dependencies `pydantic>=2.11,<3`, `PyYAML>=6,<7`, `httpx>=0.28,<1`, `beautifulsoup4>=4.13,<5`; add development dependencies `pytest>=8,<9`, `pytest-cov>=6,<7`, and `respx>=0.22,<1`.

- [x] **Step 4: Scaffold the desktop-only Obsidian plugin**

Use the official sample plugin build shape. Set:

```json
{
  "id": "zhanlu-knowledge",
  "name": "Zhanlu Knowledge",
  "version": "0.1.0",
  "minAppVersion": "1.6.0",
  "description": "Compile files and web pages into a Git-backed knowledge vault.",
  "author": "ZhanluSpace",
  "isDesktopOnly": true
}
```

Add scripts `dev`, `build`, `test`, `lint`, and `typecheck`. Pin a committed `pnpm-lock.yaml` by running `pnpm install` in the plugin directory.

- [x] **Step 5: Add canonical request fixtures**

The three fixtures must use protocol version `1`, UUID job IDs, absolute example vault paths, and these request types:

```json
{"version":1,"type":"start","job_id":"11111111-1111-4111-8111-111111111111","vault_path":"C:\\Vault","input":{"kind":"file","value":"C:\\Inbox\\note.md"}}
```

```json
{"version":1,"type":"start","job_id":"22222222-2222-4222-8222-222222222222","vault_path":"C:\\Vault","input":{"kind":"url","value":"https://example.com/article"}}
```

```json
{"version":1,"type":"confirm","job_id":"33333333-3333-4333-8333-333333333333","vault_path":"C:\\Vault","branch":"knowledge/20260803-confirm","expected_head":"0123456789012345678901234567890123456789"}
```

- [x] **Step 6: Extend ignore rules and verify both toolchains**

Ignore `.venv/`, `__pycache__/`, `.pytest_cache/`, `.coverage`, `.knowledge-runtime/`, plugin `node_modules/`, plugin `main.js`, plugin `data.json`, and Obsidian workspace state. Do not ignore protocol fixtures or Vault template files.

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_package.py -q
pnpm --dir apps/obsidian-plugin run typecheck
pnpm --dir apps/obsidian-plugin run build
```

Expected: PASS.

- [x] **Step 7: Commit the scaffold**

```powershell
git add .gitignore pyproject.toml src tests apps protocol
git commit -m "build: scaffold knowledge worker and Obsidian plugin"
```

---

## Task 2: Define and Validate the Cross-Language JSONL Protocol

**Files:**

- Create: `src/zhanlu_worker/protocol.py`
- Create: `tests/test_protocol.py`
- Create: `apps/obsidian-plugin/src/protocol.ts`
- Create: `apps/obsidian-plugin/tests/protocol.test.ts`
- Create: `protocol/fixtures/state-event.json`
- Create: `protocol/fixtures/completed-event.json`
- Create: `protocol/fixtures/error-event.json`
- Create: `protocol/README.md`

- [x] **Step 1: Write Python fixture contract tests**

Test that each request fixture parses into a discriminated Pydantic model and serializes without semantic change. Test rejection of protocol version `2`, relative Vault paths, non-HTTP URL input, invalid branch names, and invalid 40-character commit hashes.

- [x] **Step 2: Run the Python protocol tests and verify failure**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_protocol.py -q
```

Expected: FAIL because protocol models are missing.

- [x] **Step 3: Implement Python request/event models**

Define these public types:

```python
JobState = Literal["queued", "acquiring", "extracting", "compiling", "validating", "ready", "committed", "merged", "paused"]
RiskLevel = Literal["low", "high"]
Request = Annotated[StartRequest | ConfirmRequest, Field(discriminator="type")]
Event = Annotated[StateEvent | CompletedEvent | ErrorEvent, Field(discriminator="type")]
```

`CompletedEvent.result` must contain `outcome`, `risk`, `branch`, `head`, `changed_files`, `ingest_manifest`, and `risk_reasons`. `outcome` is `merged`, `ready`, or `no_change`.

- [x] **Step 4: Add TypeScript schema tests against the same fixtures**

Use Zod schemas and `safeParse`. Verify all six canonical fixtures, plus the same invalid cases used by Python.

- [x] **Step 5: Run the TypeScript tests and verify failure**

```powershell
pnpm --dir apps/obsidian-plugin test -- protocol.test.ts
```

Expected: FAIL because TypeScript protocol schemas are missing.

- [x] **Step 6: Implement TypeScript schemas and document framing**

Each process accepts exactly one request JSON object followed by newline on stdin. Stdout contains only newline-delimited protocol events. Diagnostics go to stderr. A terminal `completed` or `error` event is mandatory, and output after a terminal event is invalid.

- [x] **Step 7: Verify and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_protocol.py -q
pnpm --dir apps/obsidian-plugin test -- protocol.test.ts
git add src tests apps/obsidian-plugin protocol
git commit -m "feat: define worker JSONL protocol"
```

---

## Task 3: Acquire and Normalize Markdown, TXT, and Web Sources

**Files:**

- Create: `src/zhanlu_worker/sources.py`
- Create: `tests/test_sources.py`
- Create: `tests/fixtures/sources/note.md`
- Create: `tests/fixtures/sources/note.txt`
- Create: `tests/fixtures/sources/article.html`

- [x] **Step 1: Write source adapter tests**

Cover:

- UTF-8 Markdown preserving headings and body text.
- UTF-8 and UTF-8-BOM TXT normalization to LF.
- Unsupported extension rejection before copying.
- File size limit of 10 MiB in this phase.
- URL schemes restricted to `http` and `https`.
- Redirect limit of five, response size limit of 10 MiB, and request timeout of 20 seconds.
- HTML removal of `script`, `style`, `nav`, `footer`, and form controls while retaining title, headings, paragraphs, lists, tables, canonical URL, final URL, and retrieval time.
- SHA-256 computed over normalized UTF-8 content.
- Identical normalized content yielding the same `source:sha256:<digest>` regardless of file name.

- [x] **Step 2: Run tests and verify failure**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_sources.py -q
```

Expected: FAIL because source acquisition is missing.

- [x] **Step 3: Implement normalized source models and adapters**

Define:

```python
class NormalizedSource(BaseModel):
    source_id: str
    kind: Literal["file", "web"]
    title: str
    normalized_text: str
    content_sha256: str
    original_name: str | None
    source_url: HttpUrl | None
    final_url: HttpUrl | None
    retrieved_at: datetime
    extractor: str
    extraction_quality: Literal["high", "medium", "low"]
```

Use `Path.resolve(strict=True)` for files, reject directories and symlinks in Phase 1, stream URL responses, and never execute or resolve commands found in source text.

- [x] **Step 4: Persist only inside the job staging directory**

Implement `write_staged_source(job_dir, source)` to create `input/normalized.md`, `input/metadata.json`, and for file inputs `input/original.<ext>`. Use exclusive directory creation and reject a job ID whose directory already exists.

- [x] **Step 5: Verify and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_sources.py -q
git add src/zhanlu_worker/sources.py tests
git commit -m "feat: normalize text files and web sources"
```

---

## Task 4: Implement the Vault Schema and Deterministic Validator

**Files:**

- Create: `src/zhanlu_worker/vault.py`
- Create: `src/zhanlu_worker/validation.py`
- Create: `tests/test_vault.py`
- Create: `tests/test_validation.py`
- Create: `vault-template/README.md`
- Create: `vault-template/_meta/schema.md`
- Create: `vault-template/_meta/taxonomy.md`
- Create: `vault-template/_meta/index.md`
- Create: `vault-template/knowledge/topics/.gitkeep`
- Create: `vault-template/knowledge/entities/.gitkeep`
- Create: `vault-template/knowledge/methods/.gitkeep`
- Create: `vault-template/sources/files/.gitkeep`
- Create: `vault-template/sources/web/.gitkeep`
- Create: `vault-template/.gitignore`

- [x] **Step 1: Write parsing and validation tests**

Create fixtures in temporary Vaults and test:

- required source fields and `source:sha256:<64 lowercase hex>` format;
- required knowledge fields and unique stable knowledge IDs;
- allowed types `topic`, `entity`, `method`, `comparison`, `note`;
- allowed statuses `draft`, `confirmed`, `contested`, `superseded`, `archived`;
- allowed relations `supports`, `contradicts`, `refines`, `supersedes`, `implements`, `example_of`;
- every source and relation target resolves;
- paths remain under `sources/`, `knowledge/`, `_meta/ingests/`, or `archive/`;
- duplicate IDs, malformed YAML, broken targets, and path traversal fail with machine-readable codes;
- relation display blocks are derived and exactly match Frontmatter relations.

- [x] **Step 2: Run tests and verify failure**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_vault.py tests/test_validation.py -q
```

Expected: FAIL because Vault parsing and validation are missing.

- [x] **Step 3: Implement Vault records and repository scan**

Define `SourceRecord`, `KnowledgeRecord`, `Relation`, `VaultIndex`, `ValidationIssue`, and `ValidationReport`. Use `yaml.safe_load`; require a single YAML mapping between opening and closing `---`; reject YAML object tags and aliases exceeding the configured safe limits.

- [x] **Step 4: Implement relation display generation**

Only replace content between:

```markdown
<!-- knowledge-relations:start -->
<!-- knowledge-relations:end -->
```

Resolve target display names by stable ID through `VaultIndex`. Preserve all text outside the two markers byte-for-byte. Sort relations by relation type then target ID to make output deterministic.

- [x] **Step 5: Add the Vault template**

The template documents stable IDs, source citations, formal relation semantics, mutable directory taxonomy, and the generated-block rule. Its `.gitignore` excludes `.knowledge-runtime/`, `.obsidian/workspace*.json`, `.obsidian/cache/`, and plugin `data.json` while allowing required shared Obsidian configuration later.

- [x] **Step 6: Verify and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_vault.py tests/test_validation.py -q
git add src tests vault-template
git commit -m "feat: validate portable knowledge vaults"
```

---

## Task 5: Define Compilation Proposals and a Safe Hermes Adapter

**Files:**

- Create: `src/zhanlu_worker/proposals.py`
- Create: `src/zhanlu_worker/hermes.py`
- Create: `src/zhanlu_worker/prompts/knowledge_compiler.md`
- Create: `tests/test_proposals.py`
- Create: `tests/test_hermes.py`
- Create: `tests/fixtures/hermes/create.json`
- Create: `tests/fixtures/hermes/supplement.json`
- Create: `tests/fixtures/hermes/contradict.json`
- Create: `tests/fixtures/hermes/no-change.json`
- Create: `tests/fixtures/bin/fake-hermes.py`
- Create: `docs/development.md`

- [x] **Step 1: Write proposal schema tests**

The proposal schema must support actions `create`, `supplement`, `support`, `contradict`, `supersede`, `cite-only`, and `no-change`. Reject unknown actions, unknown relation types, duplicate target IDs, paths supplied by the model, knowledge IDs outside `[a-z][a-z0-9-]{2,79}:[a-z0-9][a-z0-9-]{1,119}`, confidence outside `[0,1]`, and citations not equal to the current source ID.

- [x] **Step 2: Write Hermes process tests using the fake executable**

Test:

- subprocess receives an argument list, not a shell string;
- working directory is the job directory;
- prompt contains compiler rules, normalized source, and only selected knowledge context;
- prompt labels source/context as untrusted data;
- stdout JSON envelope is parsed into a proposal;
- stderr is captured with secret-like values redacted;
- timeout kills the process tree and returns retryable error `HERMES_TIMEOUT`;
- non-zero exit, empty response, malformed JSON, and schema-invalid proposal never reach Vault rendering.

- [x] **Step 3: Run tests and verify failure**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_proposals.py tests/test_hermes.py -q
```

Expected: FAIL because proposal and Hermes adapter code are missing.

- [x] **Step 4: Implement the strict proposal schema**

Hermes may propose semantic content, stable IDs, titles, document types, statuses, confidence, citations, and formal relations. It may not propose filesystem paths, Git commands, frontmatter text, HTML comments, or arbitrary YAML.

- [x] **Step 5: Implement one-shot Hermes invocation**

Use the official CLI's pure one-shot mode with a configurable executable and profile. The command contract is:

```text
hermes --ignore-rules -z <prompt>
```

When a profile is configured, insert `--profile <name>` before `--ignore-rules`. Set a 120-second default timeout. The documented `-z` mode writes only final response text; accept exactly one JSON object, optionally enclosed by one JSON code fence. Do not pass `--yolo`; do not expose Git or Vault paths in the prompt.

- [x] **Step 6: Implement lexical context selection**

Tokenize normalized text and knowledge titles/body into lowercase alphanumeric/CJK terms. Select at most 20 existing documents by deterministic overlap score, then stable ID. Cap context at 60,000 UTF-8 bytes and include each selected stable ID, title, status, source IDs, relations, and bounded body excerpt. Vector retrieval is explicitly deferred.

- [x] **Step 7: Verify against an installed Hermes CLI when available**

Run:

```powershell
hermes --version
hermes doctor
```

If Hermes is not installed, install from the official NousResearch distribution, rerun both commands, and record the CLI version in `docs/development.md`. Use a harmless one-shot probe containing no private data to freeze the actual JSON envelope in an integration fixture.

- [x] **Step 8: Verify and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_proposals.py tests/test_hermes.py -q
git add src tests docs/development.md
git commit -m "feat: compile structured proposals with Hermes"
```

---

## Task 6: Compile Proposals into Deterministic Change Sets

**Files:**

- Create: `src/zhanlu_worker/compiler.py`
- Create: `src/zhanlu_worker/risk.py`
- Create: `tests/test_compiler.py`
- Create: `tests/test_risk.py`
- Create: `tests/fixtures/vault/basic/`

- [x] **Step 1: Write change compiler tests**

Cover:

- source record path derived only from source kind and SHA-256;
- new knowledge path derived from type and stable ID slug;
- existing document located by stable ID, independent of file name;
- `create` writes a new draft document with paragraph-level source marker;
- `supplement` appends a clearly delimited sourced section without replacing existing prose;
- `support` and `cite-only` add evidence idempotently;
- `contradict` preserves existing claims and adds a contested section plus formal relation;
- `supersede` marks old record `superseded` and creates or updates the replacement;
- `no-change` writes only an ingest manifest when the source alias is new, and writes nothing for a fully recorded duplicate;
- formal relations render matching Wikilinks;
- `_meta/index.md` and ingest manifest ordering are deterministic;
- applying the same change set twice is idempotent.

- [x] **Step 2: Write risk classifier tests**

Low risk requires all of: no deletion/move, no governance path, no contradiction/supersede, no confirmed knowledge replacement, extraction quality high/medium, at most 10 modified existing knowledge documents, and a clean validation report. Every violated condition yields a stable risk reason code.

- [x] **Step 3: Run tests and verify failure**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_compiler.py tests/test_risk.py -q
```

Expected: FAIL because compiler and risk classifier are missing.

- [x] **Step 4: Implement immutable `ChangeSet` generation**

Define `FileChange` with operations `create`, `update`, `delete`, `move`; Phase 1 compiler may emit only `create` and `update`. Every path is a normalized POSIX path validated to stay within allowed roots. Every update contains `before_sha256` and `after_sha256` for optimistic concurrency.

- [x] **Step 5: Implement deterministic source and knowledge Markdown rendering**

Use YAML safe dump with explicit field order, UTF-8, LF, no aliases, and `allow_unicode=True`. Do not serialize model-provided YAML. Source records include normalized text and metadata; original file bytes are copied to the source directory for file input.

- [x] **Step 6: Implement ingest manifests and indexes**

Manifest records source ID, input alias, changed paths, relation changes, warnings, risk reasons, Hermes version/profile, compiler version, schema version, and timestamp. `index.md` groups knowledge by type and sorts by title then ID.

- [x] **Step 7: Verify and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_compiler.py tests/test_risk.py -q
git add src tests
git commit -m "feat: compile deterministic knowledge change sets"
```

---

## Task 7: Apply Changes through Safe Git Transactions

**Files:**

- Create: `src/zhanlu_worker/git.py`
- Create: `tests/test_git.py`

- [x] **Step 1: Write Git integration tests in temporary repositories**

Cover:

- repository root must equal the requested Vault root;
- default branch `main` must exist;
- dirty tracked or untracked worktree rejects before branch creation;
- branch name is `knowledge/<YYYYMMDD>-<job-id-prefix>` and is created from current `main`;
- staged writes verify optimistic hashes and use atomic replace;
- only paths listed in `ChangeSet` may be staged;
- validation failure leaves `main` and the worktree unchanged;
- low-risk valid change commits and fast-forward merges into local `main`;
- high-risk valid change commits but remains on `main` with proposal branch preserved;
- confirm requires matching branch head and a still-clean `main`, reruns validation, then fast-forward merges;
- stale head, divergent main, merge conflict, failed commit, and interrupted apply never leave a partially staged Vault;
- commit message contains ingest ID and source ID but no source body.

- [x] **Step 2: Run tests and verify failure**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_git.py -q
```

Expected: FAIL because Git controller is missing.

- [x] **Step 3: Implement a subprocess-only Git client**

All Git calls use `subprocess.run(args, cwd=vault, check=False, shell=False)` where `args` is a validated list of strings. Set `GIT_TERMINAL_PROMPT=0`. Enforce explicit timeouts and return typed errors with redacted output. Never call reset-hard, clean, checkout-discard, force-push, or branch deletion containing unmerged work.

- [x] **Step 4: Implement transactional apply**

Before changing the worktree, verify all `before_sha256` values. Copy changed files to a transaction backup under the job directory. On any pre-commit failure, restore only files owned by that transaction and verify hashes. After a successful proposal commit, switch back to `main`; low-risk changes merge with `--ff-only`, while high-risk changes return branch/head for later confirmation.

- [x] **Step 5: Verify and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_git.py -q
git add src/zhanlu_worker/git.py tests/test_git.py
git commit -m "feat: apply knowledge changes as safe Git transactions"
```

---

## Task 8: Orchestrate End-to-End Worker Jobs

**Files:**

- Create: `src/zhanlu_worker/jobs.py`
- Modify: `src/zhanlu_worker/__main__.py`
- Create: `tests/test_jobs.py`
- Create: `tests/test_cli.py`

- [x] **Step 1: Write state-machine and orchestration tests**

Test valid transition sequences:

```text
queued -> acquiring -> extracting -> compiling -> validating -> committed -> merged
queued -> acquiring -> extracting -> compiling -> validating -> ready
queued -> acquiring -> paused
```

Reject skipped, repeated, or post-terminal transitions. Test duplicate source, Hermes timeout, invalid proposal, validation failure, dirty repo, low-risk merge, high-risk ready, and confirm flows using fake source/Hermes adapters and temporary Git repositories.

- [x] **Step 2: Write CLI framing tests**

Test exactly one stdin request, ordered stdout JSONL events, stderr-only logs, exit code `0` for terminal `completed`, exit code `1` for terminal `error`, malformed input error, EOF handling, and no output after terminal event.

- [x] **Step 3: Run tests and verify failure**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_jobs.py tests/test_cli.py -q
```

Expected: FAIL because orchestration is missing.

- [x] **Step 4: Implement `JobRunner` and dependency injection**

`JobRunner` owns acquisition, context selection, Hermes invocation, compilation, validation, risk classification, and Git application. Adapters are constructor dependencies so unit tests never call the network, real Hermes, or the user's repository.

- [x] **Step 5: Implement CLI logging and cancellation behavior**

Use structured event serialization on stdout and concise diagnostic logs on stderr. Handle Ctrl+C and parent-process termination by stopping child processes, marking the job paused, and leaving validated staging files for diagnosis without applying them to the Vault.

- [x] **Step 6: Run the full Python suite and commit**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
git add src tests
git commit -m "feat: orchestrate personal knowledge import jobs"
```

---

## Task 9: Build the Obsidian Worker Client

**Files:**

- Create: `apps/obsidian-plugin/src/worker-client.ts`
- Create: `apps/obsidian-plugin/tests/worker-client.test.ts`
- Create: `apps/obsidian-plugin/tests/fixtures/fake-worker.mjs`

- [x] **Step 1: Write worker process client tests**

Cover:

- spawn with configurable Python executable and `-m zhanlu_worker` arguments;
- Vault absolute path and request written as one JSON line;
- fragmented and multiple stdout chunks decoded correctly;
- ordered state callbacks;
- stderr retained separately and redacted;
- malformed JSONL, unknown protocol version, duplicate terminal events, exit without terminal event, non-zero exit, timeout, and cancellation surfaced as typed errors;
- process tree terminated on plugin unload;
- no use of a shell and no network port.

- [x] **Step 2: Run the test and verify failure**

```powershell
pnpm --dir apps/obsidian-plugin test -- worker-client.test.ts
```

Expected: FAIL because the worker client is missing.

- [x] **Step 3: Implement `WorkerClient`**

Expose:

```typescript
export interface WorkerClientOptions {
  pythonExecutable: string;
  moduleName: string;
  timeoutMs: number;
}

export interface RunningJob {
  result: Promise<CompletedEvent>;
  cancel(): Promise<void>;
}
```

Use Electron/Node `child_process.spawn` with `shell: false`, hidden window on Windows, UTF-8 streaming decoder, and an `AbortSignal`-aware lifecycle.

- [x] **Step 4: Verify and commit**

```powershell
pnpm --dir apps/obsidian-plugin test -- worker-client.test.ts
pnpm --dir apps/obsidian-plugin run typecheck
git add apps/obsidian-plugin
git commit -m "feat: connect Obsidian to the local worker"
```

---

## Task 10: Add the Obsidian Import View, Settings, and Confirmation Flow

**Files:**

- Modify: `apps/obsidian-plugin/src/main.ts`
- Create: `apps/obsidian-plugin/src/settings.ts`
- Create: `apps/obsidian-plugin/src/import-view.ts`
- Create: `apps/obsidian-plugin/src/presenter.ts`
- Create: `apps/obsidian-plugin/tests/presenter.test.ts`
- Modify: `apps/obsidian-plugin/styles.css`

- [x] **Step 1: Write pure presenter tests**

Test Chinese labels and actions for idle, running states, paused/error, low-risk merged, high-risk ready, and no-change. A high-risk result must show branch, changed files, risk reasons, `打开 Git Diff` and `确认合入` actions. Model/profile/data destination text must appear before start.

- [x] **Step 2: Run tests and verify failure**

```powershell
pnpm --dir apps/obsidian-plugin test -- presenter.test.ts
```

Expected: FAIL because presentation logic is missing.

- [x] **Step 3: Implement plugin settings**

Settings are local Obsidian plugin data only and include Python executable, Worker module, Hermes executable, optional Hermes profile, job timeout, and the explicit personal-data policy label. Never store API keys or GitHub tokens. Add a `检测环境` action that runs version/preflight checks without importing content.

- [x] **Step 4: Implement the import side view**

Register a ribbon icon and command `打开斩律知识导入`. The view provides:

- a file drop zone accepting exactly one `.md` or `.txt` file in Phase 1;
- a URL input accepting `http`/`https`;
- current model/profile and data destination notice;
- start/cancel controls;
- ordered progress states;
- terminal summary with changed files and risk reasons;
- high-risk confirmation button issuing a `confirm` request with exact branch/head;
- a Git Diff button invoking the configured system Git GUI or copying the safe `git diff main...<branch>` command, without running an arbitrary configured shell string.

- [x] **Step 5: Wire drag-and-drop safely**

Use desktop `File.path`; reject directories, multiple files, unsupported extensions, and missing paths in the UI before spawning Worker. The Worker remains the security authority and repeats validation.

- [x] **Step 6: Verify and commit**

```powershell
pnpm --dir apps/obsidian-plugin test
pnpm --dir apps/obsidian-plugin run typecheck
pnpm --dir apps/obsidian-plugin run build
git add apps/obsidian-plugin
git commit -m "feat: add Obsidian knowledge import experience"
```

---

## Task 11: Add Reproducible Verification and a Real Local Smoke Test

**Files:**

- Create: `scripts/verify.ps1`
- Create: `scripts/install-plugin.ps1`
- Create: `tests/e2e/test_personal_loop.py`
- Create: `tests/fixtures/e2e/source.md`
- Modify: `docs/development.md`
- Create: `docs/manual-test.md`

- [x] **Step 1: Write the end-to-end test first**

The test creates a temporary Vault from `vault-template`, initializes `main`, configures a deterministic fake Hermes executable, runs a file import through the real CLI, asserts the exact event sequence, verifies the low-risk commit is merged into `main`, validates the entire Vault, reruns the same source, and verifies no duplicate knowledge or source record is created.

- [x] **Step 2: Run the E2E test and verify failure**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/e2e/test_personal_loop.py -q
```

Expected: FAIL until all real components are correctly connected.

- [x] **Step 3: Make the E2E test pass without test-only production branches**

Use dependency configuration only: the same CLI, schemas, compiler, validator, and Git controller run in both tests and production. The fake Hermes executable only replaces the external model process.

- [x] **Step 4: Add a single verification entry point**

`scripts/verify.ps1` must stop on error and run:

```powershell
.\.venv\Scripts\python.exe -m pytest --cov=zhanlu_worker --cov-report=term-missing
pnpm --dir apps/obsidian-plugin test
pnpm --dir apps/obsidian-plugin run typecheck
pnpm --dir apps/obsidian-plugin run build
git diff --check
```

- [x] **Step 5: Add a safe plugin installer**

`scripts/install-plugin.ps1` accepts a mandatory explicit Vault path, resolves it, requires `.obsidian/`, creates only `.obsidian/plugins/zhanlu-knowledge/`, and copies `main.js`, `manifest.json`, and `styles.css`. It must reject the repository root, home directory, drive root, missing build outputs, and unresolved paths. It must not launch Obsidian automatically.

- [x] **Step 6: Install or update Obsidian for manual testing**

If Obsidian is absent, download it from the official Obsidian distribution, verify the downloaded installer is signed by Dynalist Inc. or the current official publisher, install it, and record the tested Obsidian version. Do not install community plugins unrelated to this project.

- [ ] **Step 7: Run a real Hermes manual smoke test**

Blocked on this machine: Hermes 0.19.1 is installed and reaches the one-shot inference boundary, but no local/BYOK inference provider is configured. The deterministic end-to-end substitute passes; `docs/development.md` records the honest real-provider prerequisite.

Create a disposable test Vault containing no private data. Import `tests/fixtures/e2e/source.md` with the configured real Hermes profile. Verify the proposal is schema-valid, the source is traceable, the relation display matches Frontmatter, and the Git commit/merge behavior matches risk. Delete only the disposable Vault after resolving and verifying its absolute test path.

- [x] **Step 8: Run the full verification suite**

```powershell
powershell -ExecutionPolicy Bypass -File scripts/verify.ps1
git status --short
```

Expected: all tests/builds pass and only intended files are changed.

- [x] **Step 9: Commit verification assets**

```powershell
git add scripts tests/e2e tests/fixtures/e2e docs/development.md docs/manual-test.md
git commit -m "test: verify the local personal knowledge loop"
```

---

## Task 12: Final Review and Phase-One Handoff

**Files:**

- Create: `README.md`
- Modify: `docs/development.md`
- Modify: `docs/manual-test.md`

- [ ] **Step 1: Document the supported workflow and explicit limits**

Document installation, Vault initialization, Hermes configuration, Markdown/TXT drag import, URL import, progress states, low-risk auto-merge, high-risk confirmation, recovery, logs, and uninstall. State plainly that PDF/DOCX/OCR and GitHub team PR are not in this phase.

- [ ] **Step 2: Audit licenses and packaged dependencies**

Record direct dependency licenses. Confirm no AGPL/GPL runtime is bundled in Phase 1 and no source content, model cache, credential, `.venv`, `node_modules`, or Obsidian installer is tracked by Git.

- [ ] **Step 3: Run completion verification from a clean checkout state**

```powershell
powershell -ExecutionPolicy Bypass -File scripts/verify.ps1
git diff --check
git status --short
git log --oneline --decorate -12
```

Expected: verification passes; the worktree is clean after the documentation commit.

- [ ] **Step 4: Commit documentation**

```powershell
git add README.md docs
git commit -m "docs: explain the personal knowledge workflow"
```

- [ ] **Step 5: Produce the next implementation plans**

Create separate reviewed plans for:

1. PDF, DOCX, scanned PDF, PNG/JPG/WebP OCR adapters and Git LFS source storage.
2. Team GitHub workflow: push, PR creation, Knowledge CI, PR summary, CODEOWNERS, one-person approval, and post-merge sync.

Do not mix either scope into fixes for this phase unless a failing acceptance criterion proves it is required.

## Acceptance Criteria

- A desktop Obsidian user can drag one Markdown/TXT file or enter one URL and see truthful ordered progress.
- Source records are content-addressed, traceable, immutable in meaning, and duplicate-safe.
- Hermes returns proposals only; invalid or malicious model output cannot choose paths, write YAML, or execute Git.
- Formal relationships survive file rename because they use stable IDs; Obsidian Wikilinks are deterministic derived display.
- No formal Vault file changes before acquisition, compilation, deterministic validation, and risk classification succeed.
- Low-risk personal changes create an auditable commit and fast-forward local `main` automatically.
- High-risk changes create an auditable proposal branch but do not merge until exact-head confirmation.
- A dirty worktree, stale branch, invalid output, timeout, cancellation, or failed validation never overwrites unrelated user changes.
- Python tests, plugin tests, typecheck, plugin build, E2E test, and `git diff --check` pass through one command.
- The same Vault remains readable and structurally valid without Obsidian installed.

## References

- [Approved system design](../specs/2026-08-03-obsidian-hermes-knowledge-vault-design.md)
- [Official Obsidian sample plugin](https://github.com/obsidianmd/obsidian-sample-plugin)
- [Hermes CLI command reference](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/reference/cli-commands.md)
- [Hermes skills documentation](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills/)
- [Hermes skill authoring guide](https://hermes-agent.nousresearch.com/docs/developer-guide/creating-skills)
