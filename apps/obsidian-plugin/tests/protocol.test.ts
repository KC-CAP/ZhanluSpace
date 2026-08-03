import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { eventSchema, requestSchema } from "../src/protocol";


const fixture = (name: string): unknown =>
  JSON.parse(
    readFileSync(new URL(`../../../protocol/fixtures/${name}`, import.meta.url), "utf8"),
  );


describe("requestSchema", () => {
  for (const name of ["start-file.json", "start-url.json", "confirm.json"]) {
    it(`round trips ${name} without semantic change`, () => {
      const payload = fixture(name);

      expect(requestSchema.parse(payload)).toEqual(payload);
    });
  }

  it.each([
    {
      version: 2,
      type: "start",
      job_id: "11111111-1111-4111-8111-111111111111",
      vault_path: "C:\\Vault",
      input: { kind: "file", value: "C:\\Inbox\\note.md" },
    },
    {
      version: 1,
      type: "start",
      job_id: "11111111-1111-4111-8111-111111111111",
      vault_path: "relative-vault",
      input: { kind: "file", value: "C:\\Inbox\\note.md" },
    },
    {
      version: 1,
      type: "start",
      job_id: "11111111-1111-4111-8111-111111111111",
      vault_path: "C:\\Vault",
      input: { kind: "url", value: "file:///C:/private.txt" },
    },
    {
      version: 1,
      type: "confirm",
      job_id: "33333333-3333-4333-8333-333333333333",
      vault_path: "C:\\Vault",
      branch: "main",
      expected_head: "0123456789012345678901234567890123456789",
    },
    {
      version: 1,
      type: "confirm",
      job_id: "33333333-3333-4333-8333-333333333333",
      vault_path: "C:\\Vault",
      branch: "knowledge/20260803-confirm",
      expected_head: "not-a-commit",
    },
  ])("rejects invalid request boundary values", (payload) => {
    expect(requestSchema.safeParse(payload).success).toBe(false);
  });
});


describe("eventSchema", () => {
  for (const name of ["state-event.json", "completed-event.json", "error-event.json"]) {
    it(`round trips ${name} without semantic change`, () => {
      const payload = fixture(name);

      expect(eventSchema.parse(payload)).toEqual(payload);
    });
  }
});
