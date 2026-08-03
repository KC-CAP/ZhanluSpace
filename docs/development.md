# Development environment

## Tested runtimes

- Windows 11, PowerShell 5.1
- Python 3.12.13 for Zhanlu Worker development; package requires Python 3.11+
- Node.js 24.14.0 with pnpm 11.9.0 for the Obsidian plugin
- Hermes Agent 0.19.1, installed from the official NousResearch Windows installer on 2026-08-03
- Hermes managed Python 3.11.15

Hermes is installed outside the repository at `%LOCALAPPDATA%\hermes\hermes-agent`. The executable tested here is `%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\hermes.exe`. The plugin will expose this as a local setting instead of assuming a global PATH entry.

## Hermes contract

The Worker launches Hermes in the job staging directory using the documented pure one-shot interface:

```text
hermes [--profile <name>] --ignore-rules -z <prompt>
```

Hermes receives inline compiler rules, normalized untrusted source text, and at most 20 deterministically selected knowledge excerpts capped at 60,000 UTF-8 bytes. It does not receive the Vault path or Git credentials. The Worker accepts exactly one JSON proposal object and validates it with Pydantic before any rendering.

`hermes doctor` passed the core Python environment, package, SSL, security advisory, MCP command, directory, Git, ripgrep, and CLI checks. Optional messaging/browser tools were not configured and are not needed by this project. The installer reported a failed optional browser-tools `npm install`; `hermes -z` and `hermes doctor` remain operational.

The harmless one-shot probe correctly reached the CLI but reported `No inference provider configured`, because setup was intentionally skipped and no personal API credentials were added. Before a real model smoke test, the user must select a local or BYOK provider with `hermes model` or an approved profile. The Worker recognizes Hermes 0.19.1's stdout-form `hermes -z: agent failed:` response even when the process exits with code 0 and surfaces it as retryable `HERMES_FAILED`.

## Local setup

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
pnpm --dir apps/obsidian-plugin install
```

Generated environments, model responses, credentials, and `.knowledge-runtime/` never enter Git.
