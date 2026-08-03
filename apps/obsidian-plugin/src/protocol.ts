import { z } from "zod";


const absolutePath = z.string().refine(
  (value) => /^(?:[A-Za-z]:[\\/]|\\\\|\/)/u.test(value),
  "path must be absolute",
);
const jobId = z.string().uuid();
const branch = z.string().regex(/^knowledge\/[0-9]{8}-[a-z0-9][a-z0-9-]{0,63}$/u);
const commitHash = z.string().regex(/^[0-9a-f]{40}$/u);

const fileInputSchema = z
  .object({
    kind: z.literal("file"),
    value: absolutePath,
  })
  .strict();

const urlInputSchema = z
  .object({
    kind: z.literal("url"),
    value: z.string().url().refine((value) => /^https?:\/\//u.test(value)),
  })
  .strict();

const startRequestSchema = z
  .object({
    version: z.literal(1),
    type: z.literal("start"),
    job_id: jobId,
    vault_path: absolutePath,
    input: z.discriminatedUnion("kind", [fileInputSchema, urlInputSchema]),
  })
  .strict();

const confirmRequestSchema = z
  .object({
    version: z.literal(1),
    type: z.literal("confirm"),
    job_id: jobId,
    vault_path: absolutePath,
    branch,
    expected_head: commitHash,
  })
  .strict();

export const requestSchema = z.discriminatedUnion("type", [
  startRequestSchema,
  confirmRequestSchema,
]);

export const jobStateSchema = z.enum([
  "queued",
  "acquiring",
  "extracting",
  "compiling",
  "validating",
  "ready",
  "committed",
  "merged",
  "paused",
]);

const stateEventSchema = z
  .object({
    version: z.literal(1),
    type: z.literal("state"),
    job_id: jobId,
    state: jobStateSchema,
    message: z.string(),
  })
  .strict();

const completedEventSchema = z
  .object({
    version: z.literal(1),
    type: z.literal("completed"),
    job_id: jobId,
    result: z
      .object({
        outcome: z.enum(["merged", "ready", "no_change"]),
        risk: z.enum(["low", "high"]),
        branch,
        head: commitHash,
        changed_files: z.array(z.string()),
        ingest_manifest: z.string(),
        risk_reasons: z.array(z.string()),
      })
      .strict(),
  })
  .strict();

const errorEventSchema = z
  .object({
    version: z.literal(1),
    type: z.literal("error"),
    job_id: jobId,
    code: z.string(),
    message: z.string(),
    retryable: z.boolean(),
  })
  .strict();

export const eventSchema = z.discriminatedUnion("type", [
  stateEventSchema,
  completedEventSchema,
  errorEventSchema,
]);

export type Request = z.infer<typeof requestSchema>;
export type Event = z.infer<typeof eventSchema>;
export type StateEvent = z.infer<typeof stateEventSchema>;
export type CompletedEvent = z.infer<typeof completedEventSchema>;
export type ErrorEvent = z.infer<typeof errorEventSchema>;
