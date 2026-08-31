import { describe, expect, it } from "vitest";

import { presentImport, type ImportScreenState } from "../src/presenter";
import type { CompletedEvent } from "../src/protocol";


const completed = (
  outcome: "merged" | "ready" | "no_change",
  risk: "low" | "high",
): CompletedEvent => ({
  version: 1,
  type: "completed",
  job_id: "11111111-1111-4111-8111-111111111111",
  result: {
    outcome,
    risk,
    branch: "knowledge/20260803-sample",
    head: "a".repeat(40),
    changed_files: ["knowledge/sample.md", "indexes/knowledge.md"],
    ingest_manifest: ".knowledge-runtime/jobs/sample/manifest.json",
    risk_reasons: risk === "high" ? ["更新了已有知识文档"] : [],
  },
});

const base = {
  profile: "personal-local",
  dataDestination: "Hermes 当前模型提供商",
};


describe("presentImport", () => {
  it("shows model profile and data destination before import", () => {
    const view = presentImport({ kind: "idle", ...base });

    expect(view.title).toBe("导入知识");
    expect(view.facts).toContain("模型配置：personal-local");
    expect(view.facts).toContain("数据去向：Hermes 当前模型提供商");
    expect(view.actions.map((action) => action.id)).toEqual(["start"]);
  });

  it("translates every running state and offers cancellation", () => {
    const states = [
      ["queued", "已排队"],
      ["acquiring", "正在读取素材"],
      ["extracting", "正在提取知识"],
      ["compiling", "正在生成变更"],
      ["validating", "正在校验知识库"],
      ["ready", "等待确认"],
      ["committed", "已创建提交"],
      ["merged", "已合入"],
      ["paused", "已暂停"],
    ] as const;

    for (const [state, label] of states) {
      const input: ImportScreenState = {
        kind: "running",
        state,
        message: "worker detail",
        ...base,
      };
      const view = presentImport(input);
      expect(view.status).toBe(label);
      expect(view.actions.map((action) => action.id)).toEqual(["cancel"]);
    }
  });

  it("presents a retryable error without leaking implementation details", () => {
    const view = presentImport({
      kind: "error",
      code: "HERMES_TIMEOUT",
      message: "Hermes 请求超时",
      retryable: true,
      ...base,
    });

    expect(view.status).toBe("导入失败，可以重试");
    expect(view.facts).toContain("错误代码：HERMES_TIMEOUT");
    expect(view.actions.map((action) => action.id)).toEqual(["retry"]);
  });

  it("shows a merged low-risk result", () => {
    const view = presentImport({ kind: "completed", event: completed("merged", "low"), ...base });

    expect(view.status).toBe("已自动合入个人知识库");
    expect(view.actions.map((action) => action.id)).toEqual(["open-changes"]);
  });

  it("shows changed files, reasons, branch, and confirmation for high risk", () => {
    const view = presentImport({ kind: "completed", event: completed("ready", "high"), ...base });

    expect(view.status).toBe("需要你确认后合入");
    expect(view.facts).toContain("分支：knowledge/20260803-sample");
    expect(view.facts).toContain("变更：knowledge/sample.md");
    expect(view.facts).toContain("风险：更新了已有知识文档");
    expect(view.actions).toEqual([
      { id: "open-changes", label: "查看 Git Diff", primary: false },
      { id: "confirm", label: "确认合入", primary: true },
    ]);
  });

  it("explains an idempotent no-change result", () => {
    const view = presentImport({
      kind: "completed",
      event: completed("no_change", "low"),
      ...base,
    });

    expect(view.status).toBe("没有需要更新的知识");
    expect(view.actions.map((action) => action.id)).toEqual([]);
  });
});
