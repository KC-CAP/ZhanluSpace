import { statSync } from "node:fs";
import { extname } from "node:path";
import { randomUUID } from "node:crypto";

import { ItemView, Notice, type WorkspaceLeaf } from "obsidian";

import { presentImport, type ImportActionId, type ImportScreenState } from "./presenter";
import type { CompletedEvent, Request } from "./protocol";
import { WorkerError, type RunningJob, type WorkerClient } from "./worker-client";
import type { ZhanluSettings } from "./settings";


export const IMPORT_VIEW_TYPE = "zhanlu-knowledge-import";

export interface ImportViewHost {
  settings: ZhanluSettings;
  workerClient: WorkerClient;
  getVaultPath(): string;
}

type ImportInput = Extract<Request, { type: "start" }>["input"];

export class ImportView extends ItemView {
  private selectedFilePath: string | undefined;
  private urlValue = "";
  private currentJob: RunningJob | undefined;
  private lastInput: ImportInput | undefined;
  private completed: CompletedEvent | undefined;
  private screen: ImportScreenState;

  constructor(leaf: WorkspaceLeaf, private readonly host: ImportViewHost) {
    super(leaf);
    this.screen = this.idleScreen();
  }

  getViewType(): string {
    return IMPORT_VIEW_TYPE;
  }

  getDisplayText(): string {
    return "知识导入";
  }

  getIcon(): string {
    return "book-plus";
  }

  onOpen(): Promise<void> {
    this.render();
    return Promise.resolve();
  }

  onClose(): Promise<void> {
    void this.currentJob?.cancel();
    return Promise.resolve();
  }

  private render(): void {
    const root = this.contentEl;
    root.empty();
    root.addClass("zhanlu-knowledge-view");
    const view = presentImport(this.screen);

    root.createEl("h2", { text: view.title });
    const status = root.createDiv({ cls: `zhanlu-status zhanlu-status--${view.tone}` });
    status.createEl("strong", { text: view.status });
    status.createEl("p", { text: view.detail });

    if (this.screen.kind === "idle" || this.screen.kind === "error") {
      this.renderInputs(root);
    }

    const facts = root.createEl("ul", { cls: "zhanlu-facts" });
    for (const fact of view.facts) facts.createEl("li", { text: fact });

    const actions = root.createDiv({ cls: "zhanlu-actions" });
    for (const action of view.actions) {
      const button = actions.createEl("button", {
        text: action.label,
        cls: action.primary ? "mod-cta" : undefined,
      });
      button.addEventListener("click", () => void this.handleAction(action.id));
    }
  }

  private renderInputs(root: HTMLElement): void {
    const dropZone = root.createDiv({ cls: "zhanlu-drop-zone" });
    dropZone.createEl("strong", { text: this.selectedFilePath ? "已选择文件" : "拖入一个 .md 或 .txt 文件" });
    dropZone.createEl("span", {
      text: this.selectedFilePath ?? "第一阶段一次只处理一个文件",
      cls: "zhanlu-path",
    });
    dropZone.addEventListener("dragover", (event) => {
      event.preventDefault();
      dropZone.addClass("is-dragover");
    });
    dropZone.addEventListener("dragleave", () => dropZone.removeClass("is-dragover"));
    dropZone.addEventListener("drop", (event) => this.handleDrop(event));

    const separator = root.createDiv({ cls: "zhanlu-separator", text: "或者" });
    separator.setAttribute("aria-hidden", "true");
    const label = root.createEl("label", { text: "网页地址", cls: "zhanlu-url-label" });
    const input = label.createEl("input", {
      type: "url",
      placeholder: "https://example.com/article",
      value: this.urlValue,
    });
    input.addEventListener("input", () => {
      this.urlValue = input.value.trim();
      if (this.urlValue) this.selectedFilePath = undefined;
    });
  }

  private handleDrop(event: DragEvent): void {
    event.preventDefault();
    const files = Array.from(event.dataTransfer?.files ?? []);
    if (files.length !== 1) {
      new Notice("请一次只拖入一个文件");
      return;
    }
    const file = files[0] as (File & { path?: string }) | undefined;
    const path = file?.path;
    if (!path) {
      new Notice("无法读取文件的本地路径；请使用 Obsidian 桌面版");
      return;
    }
    const extension = extname(path).toLowerCase();
    if (extension !== ".md" && extension !== ".txt") {
      new Notice("当前仅支持 .md 和 .txt 文件");
      return;
    }
    try {
      if (!statSync(path).isFile()) throw new Error("not a regular file");
    } catch {
      new Notice("拖入的路径不是可读取文件");
      return;
    }
    this.selectedFilePath = path;
    this.urlValue = "";
    this.screen = this.idleScreen();
    this.render();
  }

  private async handleAction(action: ImportActionId): Promise<void> {
    if (action === "cancel") {
      await this.currentJob?.cancel();
      return;
    }
    if (action === "open-changes") {
      await this.copyDiffCommand();
      return;
    }
    if (action === "confirm") {
      await this.confirmMerge();
      return;
    }
    if (action === "retry") {
      if (this.lastInput) await this.start(this.lastInput);
      return;
    }
    const input = this.selectedInput();
    if (input) await this.start(input);
  }

  private selectedInput(): ImportInput | undefined {
    if (this.selectedFilePath) return { kind: "file", value: this.selectedFilePath };
    if (!this.urlValue) {
      new Notice("请先拖入文件或填写网页地址");
      return undefined;
    }
    try {
      const url = new URL(this.urlValue);
      if (url.protocol !== "http:" && url.protocol !== "https:") throw new Error("unsupported protocol");
      return { kind: "url", value: url.toString() };
    } catch {
      new Notice("请输入有效的 http 或 https 网页地址");
      return undefined;
    }
  }

  private async start(input: ImportInput): Promise<void> {
    this.lastInput = input;
    this.completed = undefined;
    const jobId = randomUUID();
    const request: Request = {
      version: 1,
      type: "start",
      job_id: jobId,
      vault_path: this.host.getVaultPath(),
      input,
    };
    this.screen = { kind: "running", state: "queued", message: "准备启动本地 Worker", ...this.shared() };
    this.render();
    const running = this.host.workerClient.start(request, (event) => {
      if (event.type !== "state") return;
      this.screen = { kind: "running", state: event.state, message: event.message, ...this.shared() };
      this.render();
    });
    this.currentJob = running;
    await this.watch(running);
  }

  private async confirmMerge(): Promise<void> {
    const event = this.completed;
    if (!event || event.result.outcome !== "ready") return;
    const request: Request = {
      version: 1,
      type: "confirm",
      job_id: randomUUID(),
      vault_path: this.host.getVaultPath(),
      branch: event.result.branch,
      expected_head: event.result.head,
    };
    this.screen = { kind: "running", state: "validating", message: "正在核对分支与提交", ...this.shared() };
    this.render();
    const running = this.host.workerClient.start(request, (next) => {
      if (next.type !== "state") return;
      this.screen = { kind: "running", state: next.state, message: next.message, ...this.shared() };
      this.render();
    });
    this.currentJob = running;
    await this.watch(running);
  }

  private async watch(running: RunningJob): Promise<void> {
    try {
      const event = await running.result;
      this.completed = event;
      this.screen = { kind: "completed", event, ...this.shared() };
    } catch (error) {
      const workerError = error instanceof WorkerError ? error : new WorkerError("PLUGIN_ERROR", "插件调用失败");
      this.screen = {
        kind: "error",
        code: workerError.code,
        message: workerError.message,
        retryable: workerError.retryable,
        ...this.shared(),
      };
    } finally {
      if (this.currentJob === running) this.currentJob = undefined;
      this.render();
    }
  }

  private async copyDiffCommand(): Promise<void> {
    const result = this.completed?.result;
    if (!result) return;
    const command = result.outcome === "ready"
      ? `git -C "${this.host.getVaultPath()}" diff main...${result.branch}`
      : `git -C "${this.host.getVaultPath()}" show --stat --oneline ${result.head}`;
    await navigator.clipboard.writeText(command);
    new Notice("Git Diff 命令已复制到剪贴板");
  }

  private shared(): Pick<ImportScreenState, "profile" | "dataDestination"> {
    return {
      profile: this.host.settings.hermesProfile || "默认配置",
      dataDestination: this.host.settings.dataDestination,
    };
  }

  private idleScreen(): ImportScreenState {
    return { kind: "idle", ...this.shared() };
  }
}
