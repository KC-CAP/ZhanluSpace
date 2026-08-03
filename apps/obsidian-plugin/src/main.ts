import { FileSystemAdapter, Plugin, type WorkspaceLeaf } from "obsidian";

import { IMPORT_VIEW_TYPE, ImportView } from "./import-view";
import { DEFAULT_SETTINGS, ZhanluSettingTab, type ZhanluSettings } from "./settings";
import { WorkerClient } from "./worker-client";

export default class ZhanluKnowledgePlugin extends Plugin {
  settings: ZhanluSettings = { ...DEFAULT_SETTINGS };
  workerClient!: WorkerClient;

  async onload(): Promise<void> {
    await this.loadSettings();
    this.workerClient = this.createWorkerClient();
    this.registerView(IMPORT_VIEW_TYPE, (leaf) => new ImportView(leaf, this));
    this.addRibbonIcon("book-plus", "打开斩律知识导入", () => void this.activateImportView());
    this.addCommand({
      id: "open-knowledge-import",
      name: "打开斩律知识导入",
      callback: () => void this.activateImportView(),
    });
    this.addSettingTab(new ZhanluSettingTab(this.app, this));
  }

  onunload(): void {
    void this.workerClient.dispose();
  }

  async saveSettings(): Promise<void> {
    await this.saveData(this.settings);
    await this.workerClient.dispose();
    this.workerClient = this.createWorkerClient();
  }

  getVaultPath(): string {
    const adapter = this.app.vault.adapter;
    if (!(adapter instanceof FileSystemAdapter)) {
      throw new Error("斩律知识库仅支持本地文件系统 Vault");
    }
    return adapter.getBasePath();
  }

  private async loadSettings(): Promise<void> {
    const saved = (await this.loadData()) as Partial<ZhanluSettings> | null;
    this.settings = { ...DEFAULT_SETTINGS, ...(saved ?? {}) };
  }

  private createWorkerClient(): WorkerClient {
    return new WorkerClient({
      pythonExecutable: this.settings.pythonExecutable,
      moduleName: this.settings.workerModule,
      timeoutMs: this.settings.jobTimeoutSeconds * 1000,
      environment: {
        ZHANLU_HERMES_EXECUTABLE: this.settings.hermesExecutable,
        ZHANLU_HERMES_PROFILE: this.settings.hermesProfile,
      },
    });
  }

  private async activateImportView(): Promise<void> {
    let leaf: WorkspaceLeaf | undefined = this.app.workspace.getLeavesOfType(IMPORT_VIEW_TYPE)[0];
    if (!leaf) {
      leaf = this.app.workspace.getRightLeaf(false) ?? undefined;
      if (!leaf) throw new Error("无法创建知识导入侧栏");
      await leaf.setViewState({ type: IMPORT_VIEW_TYPE, active: true });
    }
    await this.app.workspace.revealLeaf(leaf);
  }
}
