import { spawn } from "node:child_process";

import { Notice, PluginSettingTab, Setting, type App } from "obsidian";

import { isSafePythonModule } from "./settings-validation";

export { isSafePythonModule } from "./settings-validation";


export interface ZhanluSettings {
  pythonExecutable: string;
  workerModule: string;
  hermesExecutable: string;
  hermesProfile: string;
  jobTimeoutSeconds: number;
  dataDestination: string;
}

export const DEFAULT_SETTINGS: ZhanluSettings = {
  pythonExecutable: "python",
  workerModule: "zhanlu_worker",
  hermesExecutable: "hermes",
  hermesProfile: "default",
  jobTimeoutSeconds: 300,
  dataDestination: "Hermes 当前模型提供商（素材正文会被发送给该提供商）",
};

export interface SettingsHost {
  settings: ZhanluSettings;
  saveSettings(): Promise<void>;
}

export class ZhanluSettingTab extends PluginSettingTab {
  constructor(app: App, private readonly host: SettingsHost) {
    super(app, host as never);
  }

  display(): void {
    const { containerEl } = this;
    containerEl.empty();
    containerEl.createEl("h2", { text: "斩律知识库设置" });
    containerEl.createEl("p", {
      text: "这里只保存本机工具路径和模型配置名称，不保存 API Key 或 GitHub Token。",
      cls: "setting-item-description",
    });

    this.textSetting("Python 可执行文件", "建议使用已安装 zhanlu-worker 的虚拟环境 Python。", "pythonExecutable");
    this.textSetting("Worker 模块", "默认：zhanlu_worker", "workerModule");
    this.textSetting("Hermes 可执行文件", "Hermes Agent CLI 的完整路径或命令名。", "hermesExecutable");
    this.textSetting("Hermes 配置", "显示在导入页，并传递给 Hermes；留空则使用默认配置。", "hermesProfile");
    this.textSetting("数据去向说明", "导入前始终显示给使用者。", "dataDestination");

    new Setting(containerEl)
      .setName("作业超时（秒）")
      .setDesc("允许 30–3600 秒。")
      .addText((text) => {
        text.inputEl.type = "number";
        text.inputEl.min = "30";
        text.inputEl.max = "3600";
        text.setValue(String(this.host.settings.jobTimeoutSeconds));
        text.onChange(async (value) => {
          const parsed = Number.parseInt(value, 10);
          if (Number.isFinite(parsed)) {
            this.host.settings.jobTimeoutSeconds = Math.min(3600, Math.max(30, parsed));
            await this.host.saveSettings();
          }
        });
      });

    new Setting(containerEl)
      .setName("检测环境")
      .setDesc("检查 Python Worker、Hermes 和 Git 是否可以启动；不会读取或导入素材。")
      .addButton((button) => {
        button.setButtonText("开始检测").onClick(async () => {
          button.setDisabled(true);
          try {
            const checks = await runEnvironmentChecks(this.host.settings);
            const failures = checks.filter((check) => !check.ok);
            new Notice(
              failures.length === 0
                ? "环境检测通过：Python Worker、Hermes、Git 均可用"
                : `环境检测未通过：${failures.map((check) => check.name).join("、")}`,
              8000,
            );
          } finally {
            button.setDisabled(false);
          }
        });
      });
  }

  private textSetting(
    name: string,
    description: string,
    key: Exclude<keyof ZhanluSettings, "jobTimeoutSeconds">,
  ): void {
    new Setting(this.containerEl)
      .setName(name)
      .setDesc(description)
      .addText((text) => {
        text.setValue(this.host.settings[key]).onChange(async (value) => {
          this.host.settings[key] = value.trim();
          await this.host.saveSettings();
        });
      });
  }
}

interface EnvironmentCheck {
  name: string;
  ok: boolean;
}

async function runEnvironmentChecks(settings: ZhanluSettings): Promise<EnvironmentCheck[]> {
  if (!isSafePythonModule(settings.workerModule)) {
    return [
      { name: "Python Worker", ok: false },
      { name: "Hermes", ok: await exitsSuccessfully(settings.hermesExecutable, ["--version"]) },
      { name: "Git", ok: await exitsSuccessfully("git", ["--version"]) },
    ];
  }
  const checks = [
    ["Python Worker", settings.pythonExecutable, ["-c", `import ${settings.workerModule}`]],
    ["Hermes", settings.hermesExecutable, ["--version"]],
    ["Git", "git", ["--version"]],
  ] as const;
  return Promise.all(
    checks.map(async ([name, executable, args]) => ({
      name,
      ok: await exitsSuccessfully(executable, [...args]),
    })),
  );
}

async function exitsSuccessfully(executable: string, args: string[]): Promise<boolean> {
  return new Promise((resolve) => {
    const child = spawn(executable, args, {
      shell: false,
      windowsHide: true,
      stdio: "ignore",
    });
    const timer = setTimeout(() => {
      child.kill();
      resolve(false);
    }, 10_000);
    child.on("error", () => {
      clearTimeout(timer);
      resolve(false);
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      resolve(code === 0);
    });
  });
}
