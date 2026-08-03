from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


mode = os.environ.get("FAKE_HERMES_MODE", "valid")
prompt = sys.argv[-1]
Path("invocation.json").write_text(
    json.dumps(
        {"argv": sys.argv[1:], "cwd": str(Path.cwd()), "prompt": prompt},
        ensure_ascii=False,
    ),
    encoding="utf-8",
)

if mode == "sleep":
    time.sleep(5)
elif mode == "exit":
    print("OPENROUTER_API_KEY=sk-secret-value", file=sys.stderr)
    raise SystemExit(7)
elif mode == "invalid-json":
    print("not json")
elif mode == "invalid-proposal":
    print('{"schema_version": 1}')
elif mode == "agent-failed":
    print("hermes -z: agent failed: No inference provider configured.")
else:
    fixture = Path(os.environ["FAKE_HERMES_RESPONSE"]).read_text(encoding="utf-8")
    print(f"```json\n{fixture}\n```")
