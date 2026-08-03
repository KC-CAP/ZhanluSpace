import type { CompletedEvent } from "./protocol";


export type ImportActionId = "start" | "cancel" | "retry" | "open-changes" | "confirm";

export interface ImportAction {
  id: ImportActionId;
  label: string;
  primary: boolean;
}

interface SharedScreenState {
  profile: string;
  dataDestination: string;
}

export type ImportScreenState = SharedScreenState & (
  | { kind: "idle" }
  | {
      kind: "running";
      state:
        | "queued"
        | "acquiring"
        | "extracting"
        | "compiling"
        | "validating"
        | "ready"
        | "committed"
        | "merged"
        | "paused";
      message: string;
    }
  | { kind: "error"; code: string; message: string; retryable: boolean }
  | { kind: "completed"; event: CompletedEvent }
);

export interface ImportPresentation {
  title: string;
  status: string;
  detail: string;
  tone: "neutral" | "progress" | "success" | "warning" | "error";
  facts: string[];
  actions: ImportAction[];
}

const stateLabels: Record<Extract<ImportScreenState, { kind: "running" }>['state'], string> = {
  queued: "已排队",
  acquiring: "正在读取素材",
  extracting: "正在提取知识",
  compiling: "正在生成变更",
  validating: "正在校验知识库",
  ready: "等待确认",
  committed: "已创建提交",
  merged: "已合入",
  paused: "已暂停",
};

const sharedFacts = (state: SharedScreenState): string[] => [
  `模型配置：${state.profile || "默认配置"}`,
  `数据去向：${state.dataDestination}`,
];

export function presentImport(state: ImportScreenState): ImportPresentation {
  if (state.kind === "idle") {
    return {
      title: "导入知识",
      status: "选择一个素材开始",
      detail: "拖入 Markdown/文本文件，或粘贴一个网页地址。",
      tone: "neutral",
      facts: sharedFacts(state),
      actions: [{ id: "start", label: "开始导入", primary: true }],
    };
  }

  if (state.kind === "running") {
    return {
      title: "导入知识",
      status: stateLabels[state.state],
      detail: state.message,
      tone: state.state === "paused" ? "warning" : "progress",
      facts: sharedFacts(state),
      actions: [{ id: "cancel", label: "取消", primary: false }],
    };
  }

  if (state.kind === "error") {
    return {
      title: "导入知识",
      status: state.retryable ? "导入失败，可以重试" : "导入失败",
      detail: state.message,
      tone: "error",
      facts: [...sharedFacts(state), `错误代码：${state.code}`],
      actions: state.retryable ? [{ id: "retry", label: "重试", primary: true }] : [],
    };
  }

  const { result } = state.event;
  const facts = [
    ...sharedFacts(state),
    `分支：${result.branch}`,
    ...result.changed_files.map((file) => `变更：${file}`),
    ...result.risk_reasons.map((reason) => `风险：${reason}`),
  ];
  if (result.outcome === "no_change") {
    return {
      title: "导入知识",
      status: "没有需要更新的知识",
      detail: "相同素材和知识内容已经存在。",
      tone: "success",
      facts,
      actions: [],
    };
  }
  if (result.outcome === "ready") {
    return {
      title: "导入知识",
      status: "需要你确认后合入",
      detail: "这次变更会影响已有知识，请先查看差异。",
      tone: "warning",
      facts,
      actions: [
        { id: "open-changes", label: "查看 Git Diff", primary: false },
        { id: "confirm", label: "确认合入", primary: true },
      ],
    };
  }
  return {
    title: "导入知识",
    status: "已自动合入个人知识库",
    detail: `已更新 ${String(result.changed_files.length)} 个文件。`,
    tone: "success",
    facts,
    actions: [{ id: "open-changes", label: "查看 Git Diff", primary: false }],
  };
}
