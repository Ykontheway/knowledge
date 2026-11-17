import { MutationError, type CommandDTO, type CommandRequest, type DocumentDTO, type PreviewDTO, type PreviewRequest, type SessionDTO } from "./types";
import { assertUuid, MAX_RESPONSE_BYTES, serializeRequest, validateMutation, type SchemaMap } from "./validation";

export type MutationFetcher = (path: string, init: RequestInit) => Promise<Response>;
const BASE = "/v1/mutations";
const GET_HEADERS = Object.freeze({ Accept: "application/json" });
const POST_HEADERS = Object.freeze({ ...GET_HEADERS, "Content-Type": "application/json", "X-Knowledge-Intent": "document-update" });
function statusError(status: number): MutationError {
  switch (status) {
    case 401: case 403: return new MutationError("unauthorized", status);
    case 404: return new MutationError("not_found", status);
    case 409: return new MutationError("conflict", status);
    case 410: return new MutationError("expired", status);
    case 413: return new MutationError("too_large", status);
    case 415: return new MutationError("unsupported_media", status);
    case 400: case 422: return new MutationError("invalid_request", status);
    case 503: return new MutationError("unavailable", status);
    default: return new MutationError("invalid_response", status);
  }
}
async function readJson(response: Response): Promise<unknown> {
  if (response.redirected || !/^application\/json(?:;|$)/i.test(response.headers.get("content-type") ?? "")) throw new MutationError("invalid_response");
  const size = Number(response.headers.get("content-length"));
  if (size > MAX_RESPONSE_BYTES) throw new MutationError("invalid_response");
  const reader = response.body?.getReader();
  let bytes: Uint8Array;
  if (!reader) {
    bytes = new Uint8Array(await response.arrayBuffer());
  } else {
    const chunks: Uint8Array[] = [];
    let total = 0;
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        total += value.byteLength;
        if (total > MAX_RESPONSE_BYTES) { await reader.cancel().catch(() => undefined); throw new MutationError("invalid_response"); }
        chunks.push(value);
      }
      bytes = new Uint8Array(total);
      let offset = 0;
      for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    } finally { reader.releaseLock(); }
  }
  if (bytes.byteLength > MAX_RESPONSE_BYTES) throw new MutationError("invalid_response");
  try { return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) as unknown; }
  catch { throw new MutationError("invalid_response"); }
}
export class MutationHttpClient {
  constructor(private readonly fetcher: MutationFetcher = (path, init) => globalThis.fetch(path, init), private readonly timeoutMs = 15_000) {}
  getSession(signal?: AbortSignal): Promise<SessionDTO> { return this.request("/session", "SessionDTO", undefined, signal); }
  getDocument(id: string, signal?: AbortSignal): Promise<DocumentDTO> { return this.request(`/documents/${assertUuid(id)}`, "DocumentDTO", undefined, signal); }
  getCommand(id: string, signal?: AbortSignal): Promise<CommandDTO> { return this.request(`/commands/${assertUuid(id)}`, "CommandDTO", undefined, signal); }
  createPreview(payload: PreviewRequest, signal?: AbortSignal): Promise<PreviewDTO> {
    return this.request("/previews", "PreviewDTO", serializeRequest("PreviewRequest", payload), signal);
  }
  applyCommand(payload: CommandRequest, signal?: AbortSignal): Promise<CommandDTO> {
    return this.request("/commands", "CommandDTO", serializeRequest("CommandRequest", payload), signal);
  }
  private async request<Name extends keyof SchemaMap>(suffix: string, name: Name, body?: string, signal?: AbortSignal): Promise<SchemaMap[Name]> {
    if (signal?.aborted) throw new MutationError("aborted");
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let cancel: () => void = () => undefined;
    const interrupted = new Promise<never>((_, reject) => {
      cancel = () => { controller.abort(); reject(new MutationError("aborted")); };
      if (signal?.aborted) cancel();
      else signal?.addEventListener("abort", cancel, { once: true });
      timer = setTimeout(() => { controller.abort(); reject(new MutationError("timeout")); }, this.timeoutMs);
    });
    try {
      if (signal?.aborted) throw new MutationError("aborted");
      const operation = (async () => {
        const response = await this.fetcher(`${BASE}${suffix}`, {
          method: body === undefined ? "GET" : "POST", body, headers: body === undefined ? GET_HEADERS : POST_HEADERS,
          credentials: "omit", redirect: "error", signal: controller.signal,
        });
        // Error bodies may contain secrets: never read them.
        if (!response.ok) throw statusError(response.status);
        return validateMutation(name, await readJson(response));
      })();
      return await Promise.race([operation, interrupted]);
    } catch (error) {
      if (error instanceof MutationError) throw error;
      if (controller.signal.aborted || (error instanceof Error && error.name === "AbortError")) throw new MutationError("aborted");
      if (error instanceof Error && error.name === "TimeoutError") throw new MutationError("timeout");
      throw new MutationError("network");
    } finally { clearTimeout(timer); signal?.removeEventListener("abort", cancel); }
  }
}
export const mutationClient = new MutationHttpClient();
