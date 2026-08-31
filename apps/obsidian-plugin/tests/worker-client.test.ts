import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { afterEach, describe, expect, it } from "vitest";

import { WorkerClient, WorkerError } from "../src/worker-client";
import type { Request, StateEvent } from "../src/protocol";


const temporaryDirectories: string[] = [];

afterEach(() => {
  for (const directory of temporaryDirectories.splice(0)) {
    rmSync(directory, { recursive: true, force: true });
  }
});

const request = (vaultPath: string): Request => ({
  version: 1,
  type: "start",
  job_id: "11111111-1111-4111-8111-111111111111",
  vault_path: vaultPath,
  input: { kind: "file", value: join(vaultPath, "note.md") },
});

const client = (mode = "success", timeoutMs = 2000): WorkerClient =>
  new WorkerClient({
    pythonExecutable: process.execPath,
    launcherArgs: [fileURLToPath(new URL("./fixtures/fake-worker.mjs", import.meta.url))],
    moduleName: "zhanlu_worker",
    timeoutMs,
    environment: { FAKE_WORKER_MODE: mode },
  });

const vault = (): string => {
  const directory = mkdtempSync(join(tmpdir(), "zhanlu-worker-client-"));
  temporaryDirectories.push(directory);
  return directory;
};


it("decodes fragmented JSONL and resolves only after one terminal event", async () => {
  const vaultPath = vault();
  const states: StateEvent[] = [];

  const running = client().start(request(vaultPath), (event) => {
    if (event.type === "state") states.push(event);
  });
  const completed = await running.result;

  expect(states.map((event) => event.state)).toEqual(["queued"]);
  expect(completed.result.changed_files).toContain(`cwd:${vaultPath}`);
  expect(completed.result.changed_files).toContain("request:start");
});


describe.each([
  ["malformed", "MALFORMED_WORKER_OUTPUT"],
  ["unknown-version", "MALFORMED_WORKER_OUTPUT"],
  ["no-terminal", "MISSING_TERMINAL_EVENT"],
  ["duplicate-terminal", "DUPLICATE_TERMINAL_EVENT"],
  ["exit", "WORKER_EXITED"],
] as const)("worker failure mode %s", (mode, expectedCode) => {
  it(`rejects with ${expectedCode}`, async () => {
    const running = client(mode).start(request(vault()));

    await expect(running.result).rejects.toMatchObject({ code: expectedCode });
  });
});


it("redacts secret-like stderr from worker failures", async () => {
  const running = client("exit").start(request(vault()));

  try {
    await running.result;
    throw new Error("expected worker failure");
  } catch (error) {
    expect(error).toBeInstanceOf(WorkerError);
    expect(String(error)).not.toContain("sk-secret-value");
    expect(String(error)).toContain("[REDACTED]");
  }
});


it("times out and terminates a silent worker", async () => {
  const running = client("sleep", 30).start(request(vault()));

  await expect(running.result).rejects.toMatchObject({ code: "WORKER_TIMEOUT" });
});


it("cancels a running process and rejects its result", async () => {
  const running = client("sleep", 2000).start(request(vault()));

  await running.cancel();

  await expect(running.result).rejects.toMatchObject({ code: "CANCELLED" });
});


it("dispose cancels all active worker processes", async () => {
  const workerClient = client("sleep", 2000);
  const first = workerClient.start(request(vault()));
  const second = workerClient.start(
    { ...request(vault()), job_id: "22222222-2222-4222-8222-222222222222" },
  );

  await workerClient.dispose();

  await expect(first.result).rejects.toMatchObject({ code: "CANCELLED" });
  await expect(second.result).rejects.toMatchObject({ code: "CANCELLED" });
});
