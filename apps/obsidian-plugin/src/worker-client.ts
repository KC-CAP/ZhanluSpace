import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";

import {
  eventSchema,
  requestSchema,
  type CompletedEvent,
  type Event,
  type Request,
} from "./protocol";


export interface WorkerClientOptions {
  pythonExecutable: string;
  moduleName: string;
  timeoutMs: number;
  launcherArgs?: readonly string[];
  environment?: Readonly<Record<string, string>>;
}

export interface RunningJob {
  result: Promise<CompletedEvent>;
  cancel(): Promise<void>;
}

export class WorkerError extends Error {
  readonly code: string;
  readonly retryable: boolean;
  readonly stderr: string;

  constructor(code: string, message: string, retryable = false, stderr = "") {
    const redacted = redact(stderr);
    super(`${code}: ${message}${redacted ? `; stderr=${redacted}` : ""}`);
    this.name = "WorkerError";
    this.code = code;
    this.retryable = retryable;
    this.stderr = redacted;
  }
}

interface ActiveJob extends RunningJob {
  readonly closed: Promise<void>;
}

export class WorkerClient {
  private readonly active = new Set<ActiveJob>();

  constructor(private readonly options: WorkerClientOptions) {}

  start(requestValue: Request, onEvent: (event: Event) => void = () => {}): RunningJob {
    const request = requestSchema.parse(requestValue);
    const child = spawn(
      this.options.pythonExecutable,
      [...(this.options.launcherArgs ?? []), "-m", this.options.moduleName],
      {
        cwd: request.vault_path,
        env: { ...process.env, ...this.options.environment },
        shell: false,
        windowsHide: true,
        stdio: ["pipe", "pipe", "pipe"],
      },
    );

    let resolveResult: (event: CompletedEvent) => void = () => {};
    let rejectResult: (error: WorkerError) => void = () => {};
    const result = new Promise<CompletedEvent>((resolve, reject) => {
      resolveResult = resolve;
      rejectResult = reject;
    });
    // Cancellation can reject before a view has had a chance to await the job.
    // Keep the public promise rejecting, while marking it as observed for Node's
    // unhandled-rejection bookkeeping.
    void result.catch(() => {});
    let resolveClosed: () => void = () => {};
    const closed = new Promise<void>((resolve) => {
      resolveClosed = resolve;
    });
    let buffer = "";
    let stderr = "";
    let terminal: Event | undefined;
    let failure: WorkerError | undefined;
    let finished = false;

    const fail = (error: WorkerError): void => {
      if (failure === undefined) failure = error;
    };

    const parseLine = (line: string): void => {
      if (!line.trim() || failure !== undefined) return;
      let raw: unknown;
      try {
        raw = JSON.parse(line);
      } catch {
        fail(new WorkerError("MALFORMED_WORKER_OUTPUT", "stdout contains invalid JSON"));
        void killTree(child);
        return;
      }
      const parsed = eventSchema.safeParse(raw);
      if (!parsed.success) {
        fail(
          new WorkerError(
            "MALFORMED_WORKER_OUTPUT",
            "stdout event does not satisfy protocol version 1",
          ),
        );
        void killTree(child);
        return;
      }
      const event = parsed.data;
      if (terminal !== undefined) {
        fail(
          new WorkerError(
            event.type === "completed" || event.type === "error"
              ? "DUPLICATE_TERMINAL_EVENT"
              : "OUTPUT_AFTER_TERMINAL_EVENT",
            "worker wrote an event after its terminal event",
          ),
        );
        void killTree(child);
        return;
      }
      if (event.type === "completed" || event.type === "error") terminal = event;
      else {
        try {
          onEvent(event);
        } catch {
          fail(new WorkerError("EVENT_CALLBACK_FAILED", "event callback threw"));
          void killTree(child);
        }
      }
    };

    child.stdout.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => {
      buffer += chunk;
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) parseLine(line);
    });
    child.stderr.setEncoding("utf8");
    child.stderr.on("data", (chunk: string) => {
      stderr = (stderr + chunk).slice(-65_536);
    });
    child.on("error", (error) => {
      fail(new WorkerError("WORKER_SPAWN_FAILED", error.message, false, stderr));
    });

    const timer = setTimeout(() => {
      fail(new WorkerError("WORKER_TIMEOUT", "worker exceeded its timeout", true, stderr));
      void killTree(child);
    }, this.options.timeoutMs);

    const activeJob: ActiveJob = {
      result,
      closed,
      cancel: async () => {
        if (finished) return;
        fail(new WorkerError("CANCELLED", "worker job was cancelled", false, stderr));
        await killTree(child);
        await closed;
      },
    };
    this.active.add(activeJob);

    child.on("close", (code) => {
      clearTimeout(timer);
      if (buffer.trim()) parseLine(buffer);
      finished = true;
      this.active.delete(activeJob);
      if (failure !== undefined) rejectResult(failure);
      else if (terminal === undefined) {
        rejectResult(
          new WorkerError(
            code === 0 ? "MISSING_TERMINAL_EVENT" : "WORKER_EXITED",
            code === 0
              ? "worker exited without a terminal event"
              : `worker exited with code ${String(code)}`,
            code !== 0,
            stderr,
          ),
        );
      } else if (terminal.type === "error") {
        rejectResult(
          new WorkerError(terminal.code, terminal.message, terminal.retryable, stderr),
        );
      } else if (terminal.type === "completed") resolveResult(terminal);
      else {
        rejectResult(
          new WorkerError("MISSING_TERMINAL_EVENT", "last event was not terminal", false, stderr),
        );
      }
      resolveClosed();
    });

    child.stdin.end(`${JSON.stringify(request)}\n`, "utf8");
    return activeJob;
  }

  async dispose(): Promise<void> {
    await Promise.all([...this.active].map(async (job) => job.cancel()));
  }
}


async function killTree(child: ChildProcessWithoutNullStreams): Promise<void> {
  if (child.exitCode !== null || child.killed) return;
  if (process.platform !== "win32") {
    child.kill("SIGTERM");
    return;
  }
  await new Promise<void>((resolve) => {
    const killer = spawn("taskkill", ["/PID", String(child.pid), "/T", "/F"], {
      shell: false,
      windowsHide: true,
      stdio: "ignore",
    });
    killer.on("error", () => {
      child.kill();
      resolve();
    });
    killer.on("close", () => resolve());
  });
}


function redact(value: string): string {
  return value
    .replace(/(?:api[_-]?key|token|secret|password)\s*=\s*\S+/giu, "[REDACTED]")
    .replace(/\bsk-[A-Za-z0-9_-]+/gu, "[REDACTED]")
    .trim();
}
