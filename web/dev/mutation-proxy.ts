import { request } from "node:http";
import type { IncomingMessage, ServerResponse } from "node:http";
import type { AddressInfo } from "node:net";
import { TextDecoder } from "node:util";
import type { Plugin } from "vite";

const namespace = "/v1/mutations";
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const maxRequestBytes = 128 * 1024;
const maxResponseBytes = 512 * 1024;
type RuntimeConfig = { hostname: string; port: number; writeKey: string; readKey: string };
type Environment = Record<string, string | undefined>;

// 仅 configureServer 调用；不 loadEnv/define/VITE_*，不修改 B1 GET 代理。
export function mutationConfig(env: Environment): RuntimeConfig | undefined {
  if (env.KNOWLEDGE_MUTATION_ENABLED !== "1") return;
  const origin = env.KNOWLEDGE_MANAGEMENT_ORIGIN;
  const writeKey = env.KNOWLEDGE_MUTATION_KEY;
  const readKey = env.KNOWLEDGE_API_KEY;
  if (!origin || !writeKey || !readKey || writeKey === readKey) return;
  if (![writeKey, readKey].every((key) => /^[\x21-\x7e]{1,1024}$/.test(key))) return;
  const match = /^http:\/\/(127\.0\.0\.1|localhost|\[::1\]):([1-9][0-9]{0,4})$/.exec(origin);
  if (!match || Number(match[2]) > 65535) return;
  return { hostname: match[1] === "[::1]" ? "::1" : "127.0.0.1", port: Number(match[2]), writeKey, readKey };
}

export function allowedMutationPath(raw: string, method: string): boolean {
  if (raw.length > 2048 || /[?#%\\\s]/.test(raw)) return false;
  if (method === "POST") return raw === `${namespace}/previews` || raw === `${namespace}/commands`;
  if (method !== "GET") return false;
  if (raw === `${namespace}/session`) return true;
  const parts = raw.split("/");
  return parts.length === 5 && parts.slice(0, 3).join("/") === namespace &&
    ["documents", "commands"].includes(parts[3] ?? "") && uuid.test(parts[4] ?? "");
}

function safeError(res: ServerResponse, status: number, code: string): void {
  if (res.destroyed || res.writableEnded) return;
  res.writeHead(status, { "Content-Type": "application/json", "Cache-Control": "no-store", Connection: "close" });
  res.end(JSON.stringify({ error: {
    message: "Mutation request unavailable or rejected.",
    type: status >= 500 ? "internal_error" : "invalid_request_error", param: null, code,
  } }));
}

function singleHeaders(req: IncomingMessage): boolean {
  const seen = new Set<string>();
  for (let i = 0; i < req.rawHeaders.length; i += 2) {
    const name = req.rawHeaders[i]?.toLowerCase() ?? "";
    if (seen.has(name)) return false;
    seen.add(name);
  }
  return true;
}

export function sameMutationOrigin(req: IncomingMessage, port: number): boolean {
  // 与 launcher 传给后端的 origin 完全一致。Host 不决定转发 origin/target。
  if (!Number.isInteger(port) || port < 1 || port > 65535 || req.headers.host !== `127.0.0.1:${port}`) return false;
  const expected = `http://127.0.0.1:${port}`;
  const origin = req.headers.origin;
  const site = req.headers["sec-fetch-site"];
  if (origin !== undefined && origin !== expected) return false;
  if (site !== undefined && site !== "same-origin") return false;
  const mode = req.headers["sec-fetch-mode"];
  if (mode !== undefined && !["cors", "same-origin"].includes(String(mode))) return false;
  const dest = req.headers["sec-fetch-dest"];
  if (dest !== undefined && dest !== "empty") return false;
  const referer = req.headers.referer;
  if (referer !== undefined) {
    try {
      const ref = new URL(referer);
      if (ref.origin !== expected || ref.username || ref.password) return false;
    } catch { return false; }
  }
  if (req.method === "POST") return origin === expected;
  // 浏览器 GET 可以没有 Origin，但必须提供同源 Referer 或 Sec-Fetch-Site。
  return origin === expected || referer !== undefined || site === "same-origin";
}

function readBody(req: IncomingMessage, res: ServerResponse): Promise<Buffer | undefined> {
  return new Promise((resolve) => {
    const chunks: Buffer[] = [];
    let size = 0;
    let finished = false;
    const finish = (body?: Buffer, status?: number) => {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      req.off("data", data);
      req.off("end", end);
      req.off("aborted", aborted);
      req.off("error", aborted);
      res.off("close", aborted);
      if (status) safeError(res, status, "mutation_proxy_body");
      resolve(body);
    };
    const data = (chunk: Buffer) => {
      size += chunk.length;
      if (size > maxRequestBytes || (req.method === "GET" && size > 0)) {
        finish(undefined, size > maxRequestBytes ? 413 : 400);
        req.resume();
      } else chunks.push(chunk);
    };
    const end = () => finish(Buffer.concat(chunks));
    const aborted = () => finish(undefined, 400);
    const timer = setTimeout(() => { finish(undefined, 408); req.resume(); }, 5000);
    req.on("data", data);
    req.once("end", end);
    req.once("aborted", aborted);
    req.once("error", aborted);
    res.once("close", aborted);
    if (req.aborted || res.destroyed) aborted();
  });
}

function safeJSON(body: Buffer): { parsed: unknown; text: string } {
  const text = new TextDecoder("utf-8", { fatal: true }).decode(body);
  const parsed: unknown = JSON.parse(text);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error();
  return { parsed, text };
}

function unsafeFields(value: unknown): boolean {
  if (!value || typeof value !== "object") return false;
  if (Array.isArray(value)) return value.some(unsafeFields);
  return Object.entries(value).some(([key, item]) =>
    /^(stack|raw_?stack|traceback|secret|api_?key|mutation_?key|authorization|environment|headers|target|database_path|source_path)$/i.test(key) || unsafeFields(item));
}

export function mutationMiddleware(config: RuntimeConfig | undefined, port: () => number) {
  return (req: IncomingMessage, res: ServerResponse, next: () => void): void => {
    const path = req.url ?? "";
    if (!path.startsWith(namespace)) { next(); return; }
    // 提前失败/收流后仍可能发生 socket error，不允许未处理事件导致 dev server 退出。
    req.on("error", () => {});
    // 未显式配置时整个写 namespace 固定关闭，无任何上游请求。
    if (!config) { safeError(res, 503, "mutation_proxy_unavailable"); return; }
    if (!singleHeaders(req)) { safeError(res, 400, "mutation_proxy_headers"); return; }
    const frontendPort = port();
    if (!sameMutationOrigin(req, frontendPort)) { safeError(res, 403, "mutation_proxy_forbidden"); return; }
    if (req.method !== "GET" && req.method !== "POST") { safeError(res, 405, "mutation_proxy_method"); return; }
    if (!allowedMutationPath(path, req.method)) { safeError(res, 400, "mutation_proxy_path"); return; }
    const length = req.headers["content-length"];
    if (length !== undefined && (!/^(0|[1-9][0-9]*)$/.test(length) || !Number.isSafeInteger(Number(length)))) {
      safeError(res, 400, "mutation_proxy_body"); return;
    }
    if (length !== undefined && Number(length) > maxRequestBytes) { safeError(res, 413, "mutation_proxy_body"); return; }
    if (req.method === "GET" && (req.headers["transfer-encoding"] || (length !== undefined && length !== "0"))) {
      safeError(res, 400, "mutation_proxy_body"); return;
    }
    if (req.method === "POST") {
      if (!/^application\/json(?:;\s*charset=utf-8)?$/i.test(req.headers["content-type"] ?? "")) {
        safeError(res, 415, "mutation_proxy_content_type"); return;
      }
      if (req.headers["x-knowledge-intent"] !== "document-update") { safeError(res, 400, "mutation_proxy_intent"); return; }
    }
    void readBody(req, res).then((body) => {
      if (!body || res.destroyed || res.writableEnded) return;
      if (req.method === "POST") {
        try { safeJSON(body); } catch { safeError(res, 400, "mutation_proxy_json"); return; }
      }
      // 收齐并限流校验后才创建 request；backend 独立检查严格 DTO、duplicate JSON keys。
      const headers: Record<string, string> = {
        Authorization: `Bearer ${config.writeKey}`, Accept: "application/json",
        Origin: `http://127.0.0.1:${frontendPort}`,
      };
      if (req.method === "POST") Object.assign(headers, {
        "Content-Type": "application/json", "Content-Length": String(body.length),
        "X-Knowledge-Intent": "document-update",
      });
      const upstream = request({ hostname: config.hostname, port: config.port, method: req.method, path, headers, agent: false }, (response) => {
        const status = response.statusCode ?? 502;
        if (![200, 201, 202].includes(status) || !/^application\/json(?:;|$)/i.test(response.headers["content-type"] ?? "")) {
          response.resume();
          safeError(res, status >= 400 && status <= 599 ? status : 502, "mutation_upstream_unavailable");
          return;
        }
        const chunks: Buffer[] = [];
        let size = 0;
        response.on("data", (chunk: Buffer) => {
          size += chunk.length;
          if (size > maxResponseBytes) {
            safeError(res, 502, "mutation_upstream_unavailable"); upstream.destroy();
          } else chunks.push(chunk);
        });
        response.on("error", () => safeError(res, 502, "mutation_upstream_unavailable"));
        response.on("aborted", () => safeError(res, 502, "mutation_upstream_unavailable"));
        response.on("end", () => {
          if (res.destroyed || res.writableEnded) return;
          try {
            const { parsed, text } = safeJSON(Buffer.concat(chunks));
            const normalized = JSON.stringify(parsed);
            if ([config.readKey, config.writeKey].some((key) => text.includes(key) || normalized.includes(key)) || unsafeFields(parsed)) throw new Error();
            res.writeHead(status, { "Content-Type": "application/json", "Cache-Control": "no-store" });
            res.end(text);
          } catch { safeError(res, 502, "mutation_upstream_unavailable"); }
        });
      });
      upstream.on("error", () => safeError(res, 502, "mutation_upstream_unavailable"));
      upstream.setTimeout(5000, () => { safeError(res, 504, "mutation_upstream_unavailable"); upstream.destroy(); });
      res.once("close", () => upstream.destroy());
      upstream.end(body);
    }).catch(() => safeError(res, 502, "mutation_proxy_unavailable"));
  };
}

export function mutationProxy(): Plugin {
  return {
    name: "loopback-mutation-proxy", apply: "serve",
    configureServer(server) {
      const config = mutationConfig(process.env);
      server.middlewares.use(mutationMiddleware(config, () => {
        const address = server.httpServer?.address();
        return address && typeof address !== "string" ? (address as AddressInfo).port : 0;
      }));
    },
    // 不安装 configurePreviewServer；静态 build 也没有写代理。
  };
}
