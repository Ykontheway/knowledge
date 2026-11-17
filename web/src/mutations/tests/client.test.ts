import { afterEach, describe, expect, it, vi } from "vitest";
import { MutationHttpClient } from "../client";
import { serializeRequest, textMetrics, validateMutation, MAX_TEXT_BYTES } from "../validation";
import { command, document, hashA, ids, json, makePreview, previewRequest, session } from "./fixtures";

afterEach(() => vi.useRealTimers());
describe("independent mutation validation and transport", () => {
  it("validates real DTO schemas and rejects unknown fields recursively", () => {
    expect(validateMutation("SessionDTO", session)).toEqual(session);
    expect(validateMutation("DocumentDTO", document)).toEqual(document);
    const preview = makePreview();
    expect(validateMutation("PreviewDTO", preview)).toEqual(preview);
    expect(validateMutation("CommandDTO", command)).toEqual(command);
    for (const payload of [{ ...session, token: "secret" }, { ...session, sources: [{ ...session.sources[0], href: "https://evil.invalid" }] },
      { ...session, role: undefined }, { ...session, capabilities: [] }, { ...session, capabilities: ["document.update", "document.update"] }]) {
      expect(() => validateMutation("SessionDTO", payload)).toThrow("invalid_response");
    }
    expect(() => validateMutation("CommandDTO", { ...command, committed: undefined })).toThrow("invalid_response");
    expect(() => validateMutation("DocumentDTO", { ...document, checksum: "unsafe" })).toThrow("invalid_response");
    expect(() => validateMutation("PreviewDTO", { ...makePreview(), counts: { ...makePreview().counts, added: Infinity } })).toThrow("invalid_response");
    expect(() => validateMutation("PreviewDTO", { ...makePreview(), expires_at: "2030-01-01" })).toThrow("invalid_response");
    expect(() => validateMutation("PreviewDTO", { ...makePreview(), diff: [{ kind: "modified", old_text: "\ud800", new_text: "a" }] })).toThrow("invalid_response");
  });
  it("counts codepoints and UTF-8 emoji at byte boundaries, with a separate JSON cap", () => {
    expect(textMetrics("中😀")).toEqual({ characters: 2, bytes: 7, valid: true });
    expect(textMetrics("😀".repeat(MAX_TEXT_BYTES / 4)).valid).toBe(true);
    expect(textMetrics("😀".repeat(MAX_TEXT_BYTES / 4) + "a").valid).toBe(false);
    expect(textMetrics("\ud800").valid).toBe(false);
    expect(serializeRequest("PreviewRequest", { ...previewRequest, text: "😀".repeat(MAX_TEXT_BYTES / 4) })).toContain("😀");
    expect(() => serializeRequest("PreviewRequest", { ...previewRequest, text: "a".repeat(MAX_TEXT_BYTES + 1) })).toThrow("too_large");
    expect(() => serializeRequest("PreviewRequest", { ...previewRequest, text: "\u0000".repeat(MAX_TEXT_BYTES) })).toThrow("too_large");
    expect(() => serializeRequest("PreviewRequest", { ...previewRequest, actor_id: "textbox" })).toThrow("invalid_request");
  });
  it("sends only relative whitelisted GET/POST without cookies, keys or redirects", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(json(session)).mockResolvedValueOnce(json(document))
      .mockResolvedValueOnce(json(makePreview())).mockResolvedValueOnce(json(command)).mockResolvedValueOnce(json(command));
    const client = new MutationHttpClient(fetcher);
    await client.getSession(); await client.getDocument(ids.document); await client.createPreview(previewRequest);
    const request = { preview_id: ids.preview, confirmation_token: "s".repeat(43), idempotency_key: ids.key, confirmed: true as const };
    await client.applyCommand(request); await client.getCommand(ids.command);
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual(["/v1/mutations/session", `/v1/mutations/documents/${ids.document}`, "/v1/mutations/previews", "/v1/mutations/commands", `/v1/mutations/commands/${ids.command}`]);
    for (const [, init] of fetcher.mock.calls) {
      expect(init.credentials).toBe("omit"); expect(init.redirect).toBe("error");
      expect(init.headers).not.toHaveProperty("Authorization");
      if (init.method === "POST") expect(init.headers).toMatchObject({ "Content-Type": "application/json", "X-Knowledge-Intent": "document-update" });
      else expect(init.headers).toEqual({ Accept: "application/json" });
    }
    expect(fetcher.mock.calls[3]![1].body).toBe(JSON.stringify(request));
    expect(() => client.getDocument("https://evil.invalid")).toThrow("invalid_request");
    expect(() => client.applyCommand({ ...request, secret: "x" } as typeof request)).toThrow("invalid_request");
    expect(fetcher).toHaveBeenCalledTimes(5);
  });
  it.each([[401, "unauthorized"], [403, "unauthorized"], [404, "not_found"], [409, "conflict"], [410, "expired"], [413, "too_large"], [415, "unsupported_media"], [422, "invalid_request"], [503, "unavailable"], [302, "invalid_response"], [501, "invalid_response"]])("maps status %i to safe enum without reading errors", async (status, kind) => {
    const response = new Response("RAW_SECRET_ERROR", { status: status as number });
    const read = vi.spyOn(response, "arrayBuffer");
    const client = new MutationHttpClient(vi.fn().mockResolvedValue(response));
    await expect(client.getSession()).rejects.toMatchObject({ kind, status });
    expect(read).not.toHaveBeenCalled();
  });
  it("bounds response bytes, rejects HTML, malformed UTF-8, bad JSON and nonfinite values", async () => {
    for (const response of [new Response("<script>secret</script>"), new Response("bad", { headers: { "Content-Type": "application/json" } }),
      json({ ...session, scope_id: "javascript:bad" }), new Response(new Uint8Array([255]), { headers: { "Content-Type": "application/json" } }),
      new Response("{}", { headers: { "Content-Type": "application/json", "Content-Length": String(3 * 1024 * 1024) } }),
      new Response(`{"counts":{"added":1e999}}`, { headers: { "Content-Type": "application/json" } })]) {
      await expect(new MutationHttpClient(vi.fn().mockResolvedValue(response)).getSession()).rejects.toMatchObject({ kind: "invalid_response" });
    }
    expect(hashA).toHaveLength(64);
  });
  it("times out and aborts even when a transport does not settle, never leaking raw errors", async () => {
    vi.useFakeTimers();
    const fetcher = vi.fn((_path: string, _init: RequestInit) => new Promise<Response>(() => undefined));
    const client = new MutationHttpClient(fetcher, 20);
    const timeout = client.getSession();
    const assertion = expect(timeout).rejects.toMatchObject({ kind: "timeout" });
    await vi.advanceTimersByTimeAsync(21); await assertion;
    expect(fetcher.mock.calls[0]![1].signal!.aborted).toBe(true);
    const controller = new AbortController();
    const aborted = client.getSession(controller.signal); controller.abort();
    await expect(aborted).rejects.toMatchObject({ kind: "aborted" });
    const raw = new MutationHttpClient(vi.fn().mockRejectedValue(new Error("secret url token")));
    await expect(raw.getSession()).rejects.toMatchObject({ kind: "network", message: "network" });
  });
});


it("aborted input is rejected before any fetch and streamed bytes cannot bypass the response cap", async () => {
  const fetcher = vi.fn((_path: string, _init: RequestInit) => Promise.resolve(json(session)));
  const controller = new AbortController(); controller.abort();
  await expect(new MutationHttpClient(fetcher).getSession(controller.signal)).rejects.toMatchObject({ kind: "aborted" });
  expect(fetcher).not.toHaveBeenCalled();
  const large = new Uint8Array(2 * 1024 * 1024 + 1);
  const cancel = vi.fn();
  const stream = new ReadableStream({ start(c) { c.enqueue(large); }, cancel });
  const response = new Response(stream, { headers: { "Content-Type": "application/json", "Content-Length": "0" } });
  await expect(new MutationHttpClient(vi.fn().mockResolvedValue(response)).getSession()).rejects.toMatchObject({ kind: "invalid_response" });
  expect(cancel).toHaveBeenCalled();
});
