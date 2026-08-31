import process from "node:process";


let input = "";
for await (const chunk of process.stdin) {
  input += chunk;
}

const request = JSON.parse(input);
const mode = process.env.FAKE_WORKER_MODE ?? "success";
if (JSON.stringify(process.argv.slice(2)) !== JSON.stringify(["-m", "zhanlu_worker"])) {
  process.stderr.write("unexpected arguments");
  process.exit(9);
}

const state = {
  version: 1,
  type: "state",
  job_id: request.job_id,
  state: "queued",
  message: "任务已排队",
};
const completed = {
  version: 1,
  type: "completed",
  job_id: request.job_id,
  result: {
    outcome: "ready",
    risk: "high",
    branch: "knowledge/20260803-confirm",
    head: "0".repeat(40),
    changed_files: [`cwd:${process.cwd()}`, `request:${request.type}`],
    ingest_manifest: "_meta/ingests/example.md",
    risk_reasons: ["MANUAL"],
  },
};

if (mode === "sleep") {
  setTimeout(() => process.exit(0), 5000);
} else if (mode === "exit") {
  process.stderr.write("OPENROUTER_API_KEY=sk-secret-value");
  process.exit(7);
} else if (mode === "malformed") {
  process.stdout.write("{broken}\n");
} else if (mode === "unknown-version") {
  process.stdout.write(`${JSON.stringify({ ...state, version: 2 })}\n`);
} else if (mode === "no-terminal") {
  process.stdout.write(`${JSON.stringify(state)}\n`);
} else if (mode === "duplicate-terminal") {
  process.stdout.write(`${JSON.stringify(completed)}\n${JSON.stringify(completed)}\n`);
} else {
  const output = `${JSON.stringify(state)}\n${JSON.stringify(completed)}\n`;
  process.stdout.write(output.slice(0, 7));
  setTimeout(() => process.stdout.write(output.slice(7, 31)), 5);
  setTimeout(() => process.stdout.end(output.slice(31)), 10);
}
