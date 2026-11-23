import type { CommandDTO, PreviewDTO, PreviewRequest, SessionDTO, DocumentDTO } from "../types";
// Tests only; no fixtures are imported by runtime code.
export const ids = {
  scope: "11111111-1111-4111-8111-111111111111", source: "22222222-2222-4222-8222-222222222222",
  document: "33333333-3333-4333-8333-333333333333", preview: "44444444-4444-4444-8444-444444444444",
  key: "55555555-5555-4555-8555-555555555555", command: "66666666-6666-4666-8666-666666666666",
  newDocument: "77777777-7777-4777-8777-777777777777", revision: "88888888-8888-4888-8888-888888888888",
  job: "99999999-9999-4999-8999-999999999999",
};
export const hashA = "a".repeat(64), hashB = "b".repeat(64);
export const session: SessionDTO = { scope_id: ids.scope, actor_id: "demo-editor", role: "demo_editor", capabilities: ["document.update"],
  sources: [{ source_id: ids.source, document_id: ids.document, checksum: hashA, content_type: "markdown", label: "演示文档" }] };
export const document: DocumentDTO = { scope_id: ids.scope, source_id: ids.source, document_id: ids.document, checksum: hashA, content_type: "markdown", text: "原文😀" };
export const previewRequest: PreviewRequest = { scope_id: ids.scope, source_id: ids.source, document_id: ids.document, expected_checksum: hashA, text: "新文本😀" };
export function makePreview(changed = true): PreviewDTO {
  return { preview_id: ids.preview, scope_id: ids.scope, source_id: ids.source, document_id: ids.document,
    expected_checksum: hashA, new_checksum: changed ? hashB : hashA, expires_at: new Date(Date.now() + 300_000).toISOString(),
    confirmation_token: "s".repeat(43), changed, counts: { added: 0, modified: changed ? 1 : 0, moved: 0, unchanged: changed ? 0 : 1, removed: 0 },
    diff: [{ kind: changed ? "modified" : "unchanged", old_text: document.text, new_text: previewRequest.text }] };
}
export const command: CommandDTO = { command_id: ids.command, scope_id: ids.scope, actor_id: session.actor_id, source_id: ids.source,
  previous_document_id: ids.document, document_id: ids.newDocument, new_checksum: hashB, committed: true, changed: true,
  revision_ids: [ids.revision], job_ids: [ids.job], evaluation_status: "failed" };
export function json(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } });
}
export function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}
