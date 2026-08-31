# Development environment

## Tested runtimes

- Windows 11, PowerShell 5.1
- Python 3.12.13 for Zhanlu Worker development; package requires Python 3.11+
- Node.js 24.14.0 with pnpm 11.9.0 for the Obsidian plugin
- Hermes Agent 0.19.1, installed from the official NousResearch Windows installer on 2026-08-03
- Hermes managed Python 3.11.15
- Obsidian 1.13.4, installed from the `Obsidian.Obsidian` winget package

The installed Obsidian executable passed Windows Authenticode validation. Its signer is `Dynalist Inc` and the verified certificate thumbprint is `20B5809A5B1C52EB05EC7672673920913E0ED26D`.

Hermes is installed outside the repository at `%LOCALAPPDATA%\hermes\hermes-agent`. The executable tested here is `%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\hermes.exe`. The plugin will expose this as a local setting instead of assuming a global PATH entry.

## Hermes contract

The Worker launches Hermes in the job staging directory using the documented pure one-shot interface:

```text
hermes [--profile <name>] --ignore-rules -z <prompt>
```

Hermes receives inline compiler rules, normalized untrusted source text, and at most 20 deterministically selected knowledge excerpts capped at 60,000 UTF-8 bytes. It does not receive the Vault path or Git credentials. The Worker accepts exactly one JSON proposal object and validates it with Pydantic before any rendering.

`hermes doctor` passed the core Python environment, package, SSL, security advisory, MCP command, directory, Git, ripgrep, and CLI checks. Optional messaging/browser tools were not configured and are not needed by this project. The installer reported a failed optional browser-tools `npm install`; `hermes -z` and `hermes doctor` remain operational.

The harmless one-shot probe correctly reached the CLI but reported `No inference provider configured`, because setup was intentionally skipped and no personal API credentials were added. Before a real model smoke test, the user must select a local or BYOK provider with `hermes model` or an approved profile. The Worker recognizes Hermes 0.19.1's stdout-form `hermes -z: agent failed:` response even when the process exits with code 0 and surfaces it as retryable `HERMES_FAILED`.

The probe was repeated after the disposable Obsidian Vault and plugin were installed. Hermes 0.19.1 again reached the one-shot inference boundary and stopped at the same missing-provider prerequisite. Therefore the deterministic fake-Hermes E2E test is complete, while a real-provider content smoke test remains intentionally pending rather than being reported as successful.

## Local setup

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
pnpm --dir apps/obsidian-plugin install
```

Generated environments, model responses, credentials, and `.knowledge-runtime/` never enter Git.

## Verification

Run the Python unit/E2E suite, plugin tests, typecheck, production build, and whitespace audit with one command:

```powershell
.\scripts\verify.ps1 `
  -NodePath "C:\path\to\node.exe" `
  -PnpmPath "C:\path\to\pnpm.cmd"
```

The E2E test launches the public Worker JSONL CLI, substitutes Hermes through the supported argument-array configuration, creates and merges a real Git proposal, validates the resulting Vault, then repeats the import to prove idempotency. `ZHANLU_HERMES_LAUNCHER_ARGS` accepts only a JSON array of up to 16 non-empty arguments and never invokes a shell.

The Worker reconfigures stdin, stdout, and stderr to UTF-8 at process start. The Vault template also includes `.gitattributes` rules that keep knowledge text at LF across Windows Git branch switches.
