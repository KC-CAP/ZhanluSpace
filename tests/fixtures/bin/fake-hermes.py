from __future__ import annotations

import json
import os
import re
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
elif mode == "dynamic-create":
    match = re.search(r"CURRENT SOURCE ID:\s*(\S+)", prompt)
    if match is None:
        raise SystemExit("source_id missing from prompt")
    source_id = match.group(1)
    print(
        json.dumps(
            {
                "schema_version": 1,
                "source_id": source_id,
                "actions": [
                    {
                        "action": "create",
                        "knowledge_id": "method:personal-knowledge-loop",
                        "title": "个人知识闭环",
                        "knowledge_type": "method",
                        "status": "draft",
                        "confidence": 0.91,
                        "content": "个人知识闭环将素材规范化、提取、校验并通过 Git 安全合入。",
                        "citations": [source_id],
                        "relations": [],
                    }
                ],
            },
            ensure_ascii=False,
        )
    )
else:
    fixture = Path(os.environ["FAKE_HERMES_RESPONSE"]).read_text(encoding="utf-8")
    print(f"```json\n{fixture}\n```")
