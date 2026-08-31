# Worker protocol

Obsidian launches one short-lived Worker process per operation. Protocol version 1 uses UTF-8 JSON Lines over standard streams and never opens a network port.

## Framing

1. The plugin writes exactly one request object followed by `\n` to standard input, then closes standard input.
2. The Worker writes zero or more `state` events followed by exactly one terminal `completed` or `error` event to standard output.
3. Every event is one compact JSON object followed by `\n`.
4. Output after a terminal event is invalid.
5. Logs and diagnostics use standard error. They must never be mixed into standard output.

Canonical request and event objects live in [`fixtures`](fixtures). Python validates them with Pydantic in `zhanlu_worker.protocol`; the Obsidian plugin validates the same files with Zod in `src/protocol.ts`.

## Compatibility

Both peers reject unknown protocol versions, unknown fields, malformed UUIDs, relative Vault/file paths, non-HTTP web inputs, proposal branches outside `knowledge/<YYYYMMDD>-<slug>`, and commit IDs that are not 40 lowercase hexadecimal characters. A protocol change that is not backward-compatible requires a new integer version and new canonical fixtures.
