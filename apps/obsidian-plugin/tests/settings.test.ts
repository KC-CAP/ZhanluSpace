import { describe, expect, it } from "vitest";

import { isSafePythonModule } from "../src/settings-validation";


describe("isSafePythonModule", () => {
  it.each(["zhanlu_worker", "company.knowledge_worker", "_private.module2"])(
    "accepts a dotted Python module name: %s",
    (value) => expect(isSafePythonModule(value)).toBe(true),
  );

  it.each(["", "worker-name", "worker;import os", "worker module", ".worker", "worker."])(
    "rejects code and invalid module names: %s",
    (value) => expect(isSafePythonModule(value)).toBe(false),
  );
});
