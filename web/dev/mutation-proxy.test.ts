// @vitest-environment node
import { createServer as httpServer, request } from "node:http";
import type { IncomingHttpHeaders, Server, ServerResponse } from "node:http";
import type { AddressInfo } from "node:net";
import { randomBytes } from "node:crypto";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { build, createServer, preview, resolveConfig } from "vite";
import { allowedMutationPath, mutationConfig, mutationMiddleware, mutationProxy } from "./mutation-proxy";

const id = "12345678-1234-1234-1234-123456789abc";
const servers: Server[] = [];
const writeKey = randomBytes(32).toString("hex");
const readKey = randomBytes(32).toString("hex");
const env = (origin = "http://127.0.0.1:8015") => ({
  KNOWLEDGE_MUTATION_ENABLED: "1", KNOWLEDGE_MANAGEMENT_ORIGIN: origin,
  KNOWLEDGE_MUTATION_KEY: writeKey, KNOWLEDGE_API_KEY: readKey,
});
const port = (server: Server) => (server.address() as AddressInfo).port;
const origin = (server: Server) => `http://127.0.0.1:${port(server)}`;
async function listen(server: Server): Promise<Server> {
  servers.push(server);
  await new Promise<void>((done) => server.listen(0, "127.0.0.1", done));
  return server;
}
async function send(server: Server, path = "/v1/mutations/session", method = "GET", headers: IncomingHttpHeaders | string[] = {}, body?: string | Buffer) {
  return new Promise<{ status: number; body: string; headers: IncomingHttpHeaders }>((done, reject) => {
    const req = request({ hostname: "127.0.0.1", port: port(server), path, method, agent: false,
      headers: Array.isArray(headers) ? headers : Object.fromEntries(Object.entries({ origin: origin(server), ...headers }).filter(([, value]) => value !== undefined)) }, (res) => {
      let text = "";
      res.on("data", (chunk) => { text += chunk; });
      res.on("end", () => done({ status: res.statusCode!, body: text, headers: res.headers }));
    });
    req.on("error", reject);
    req.end(body);
  });
}
function frontend(target?: string) {
  const server = httpServer();
  const middleware = mutationMiddleware(target ? mutationConfig(env(target)) : undefined, () => port(server));
  server.on("request", (req, res) => middleware(req, res, () => res.end("static")));
  return listen(server);
}
const postHeaders = { "content-type": "application/json", "x-knowledge-intent": "document-update" };
afterEach(async () => {
  vi.unstubAllEnvs();
  for (const server of servers.splice(0)) {
    server.closeAllConnections();
    await new Promise<void>((done, reject) => server.close((error) => error ? reject(error) : done()));
  }
});

describe("配置完整、显式 enabled、独立读写 key", () => {
  it.each(["", "0", "true", undefined])("flag 非 1 时关闭 %s", (flag) => {
    expect(mutationConfig({ ...env(), KNOWLEDGE_MUTATION_ENABLED: flag })).toBeUndefined();
  });
  it.each(["KNOWLEDGE_MUTATION_KEY", "KNOWLEDGE_API_KEY", "KNOWLEDGE_MANAGEMENT_ORIGIN"])("缺配置 %s", (name) => {
    expect(mutationConfig({ ...env(), [name]: undefined })).toBeUndefined();
  });
  it.each(["http://evil:3", "https://127.0.0.1:3", "http://127.0.0.2:3", "http://127.1:3", "http://localhost:03", "http://localhost:65536", "http://localhost:0", "http://localhost:3/", "http://user@localhost:3", "http://localhost:3?q=x", "http://localhost:3#hash"])("拒绝 target %s", (target) => {
    expect(mutationConfig(env(target))).toBeUndefined();
  });
  it.each(["", " ", "x\r\nInjected: x"])("拒绝非法 key", (key) => {
    expect(mutationConfig({ ...env(), KNOWLEDGE_MUTATION_KEY: key })).toBeUndefined();
  });
  it("相同 key/VITE 变量都不启用", () => {
    expect(mutationConfig({ ...env(), KNOWLEDGE_API_KEY: writeKey })).toBeUndefined();
    expect(mutationConfig({ VITE_KNOWLEDGE_MUTATION_KEY: writeKey })).toBeUndefined();
    expect(mutationConfig(env())?.hostname).toBe("127.0.0.1");
    expect(mutationConfig(env("http://[::1]:3"))?.hostname).toBe("::1");
  });
});

describe("五个固定 routes，无 query、无编码路径", () => {
  it.each([["GET", "/session"], ["GET", `/documents/${id}`], ["GET", `/commands/${id}`], ["POST", "/previews"], ["POST", "/commands"]])("允许 %s %s", (method, path) => {
    expect(allowedMutationPath(`/v1/mutations${path}`, method!)).toBe(true);
  });
  it.each(["/documents", "/documents/not-uuid", `/documents/${id}/`, "/session?", "/session?x=y", "/session?x=1&x=2", "/session#x", "/session%2f..", "/session\\x", "/../health", "/commands", "/session/extra", "/session??", "/documents/%31" ])("拒绝 %s", (path) => {
    expect(allowedMutationPath(`/v1/mutations${path}`, "GET")).toBe(false);
  });
});

describe("真实 HTTP：校验先于上游、浏览器凭据不转发", () => {
  let requests: { method: string | undefined; path: string | undefined; headers: IncomingHttpHeaders; body: string }[];
  let upstream: Server;
  let web: Server;
  let respond: (res: ServerResponse) => void;
  beforeEach(async () => {
    requests = [];
    respond = (res) => { res.writeHead(200, { "Content-Type": "application/json", "Set-Cookie": "bad=x" }); res.end('{"ok":true}'); };
    upstream = await listen(httpServer((req, res) => {
      const record = { method: req.method, path: req.url, headers: req.headers, body: "" };
      requests.push(record);
      req.on("data", (chunk) => { record.body += chunk; });
      req.on("end", () => respond(res));
    }));
    web = await frontend(origin(upstream));
  });
  it.each([["GET", "/session"], ["GET", `/documents/${id}`], ["GET", `/commands/${id}`], ["POST", "/previews"], ["POST", "/commands"]])("正常 %s %s；写 key 而非读 key", async (method, path) => {
    const result = await send(web, `/v1/mutations${path}`, method, {
      ...postHeaders, authorization: "Bearer client-untrusted", cookie: "bad=x", forwarded: "host=evil",
      "proxy-authorization": "bad", "x-forwarded-host": "evil", "sec-fetch-site": "same-origin",
    }, method === "POST" ? '{"text":"safe"}' : undefined);
    expect(result.status).toBe(200);
    expect(requests).toHaveLength(1);
    const headers = requests[0]!.headers;
    expect(headers.authorization === `Bearer ${writeKey}`).toBe(true);
    expect(headers.authorization === `Bearer ${readKey}`).toBe(false);
    expect(headers.origin).toBe(origin(web));
    for (const name of ["cookie", "forwarded", "proxy-authorization", "x-forwarded-host", "referer"]) expect(headers[name]).toBeUndefined();
    expect(headers["x-knowledge-intent"]).toBe(method === "POST" ? "document-update" : undefined);
    expect(result.headers["set-cookie"]).toBeUndefined();
    expect(result.headers["access-control-allow-origin"]).toBeUndefined();
    expect(result.body.includes(writeKey) || result.body.includes(readKey)).toBe(false);
  });
  it.each([{ origin: "null" }, { origin: "http://evil:3" }, { host: "evil:3" }, { host: "127.0.0.1:1" }, { referer: "http://evil/" }, { referer: "invalid" }, { "sec-fetch-site": "cross-site" }, { "sec-fetch-site": "same-site" }, { "sec-fetch-site": "none" }, { "sec-fetch-mode": "navigate" }, { "sec-fetch-dest": "document" }])("拒绝跨源/非法 browser headers %j", async (headers) => {
    expect((await send(web, undefined, "GET", headers)).status).toBe(403);
    expect(requests).toHaveLength(0);
  });
  it("GET 无 Origin 有同源 Referer/FetchSite 可用；完全无 browser guards 拒绝", async () => {
    expect((await send(web, undefined, "GET", { origin: undefined, referer: `${origin(web)}/` })).status).toBe(200);
    expect((await send(web, undefined, "GET", { origin: undefined, "sec-fetch-site": "same-origin" })).status).toBe(200);
    expect((await send(web, undefined, "GET", { origin: undefined })).status).toBe(403);
  });
  it.each(["PATCH", "PUT", "DELETE", "OPTIONS", "HEAD"])("拒绝 method %s", async (method) => {
    expect((await send(web, undefined, method)).status).toBe(405);
    expect(requests).toHaveLength(0);
  });
  it.each(["/documents/no-uuid", "/session?x=y", "/session%2F..", "/session?x=1&x=2"])("非法 path %s 不访问上游", async (path) => {
    expect((await send(web, `/v1/mutations${path}`)).status).toBe(400);
    expect(requests).toHaveLength(0);
  });
  it.each(["Origin", "Referer", "Sec-Fetch-Site", "X-Knowledge-Intent", "Authorization", "Content-Type"])("拒绝重复 header %s", async (name) => {
    const result = await send(web, undefined, "GET", ["Host", `127.0.0.1:${port(web)}`, "Origin", origin(web), name, "bad", name, "bad"]);
    expect(result.status).toBe(400);
    expect(requests).toHaveLength(0);
  });
  it("重复 Host 在发送前拒绝", async () => {
    expect((await send(web, undefined, "GET", ["Host", `127.0.0.1:${port(web)}`, "Host", "evil", "Origin", origin(web)])).status).toBe(400);
    expect(requests).toHaveLength(0);
  });
  it.each(["application/jsonp", "text/plain", "application/json; charset=latin1", "application/json; boundary=x"])("拒绝 Content-Type %s", async (type) => {
    expect((await send(web, "/v1/mutations/previews", "POST", { ...postHeaders, "content-type": type }, "{}")).status).toBe(415);
    expect(requests).toHaveLength(0);
  });
  it("POST 必须 Origin、Intent；GET 不可携带 body", async () => {
    expect((await send(web, "/v1/mutations/previews", "POST", { ...postHeaders, origin: undefined }, "{}")).status).toBe(403);
    expect((await send(web, "/v1/mutations/previews", "POST", { "content-type": "application/json" }, "{}")).status).toBe(400);
    expect((await send(web, undefined, "GET", { "content-length": "2" }, "{}")).status).toBe(400);
    expect(requests).toHaveLength(0);
  });
  it.each(["not json", "[]", "null", '{"x":NaN}'])("拒绝 invalid JSON", async (body) => {
    expect((await send(web, "/v1/mutations/previews", "POST", postHeaders, body)).status).toBe(400);
    expect(requests).toHaveLength(0);
  });
  it("UTF8 fatal 校验", async () => {
    expect((await send(web, "/v1/mutations/previews", "POST", postHeaders, Buffer.from([0xff]))).status).toBe(400);
    expect(requests).toHaveLength(0);
  });
  it("UTF8 charset 可用；重复 JSON keys 交给后端严格 DTO", async () => {
    expect((await send(web, "/v1/mutations/previews", "POST", { ...postHeaders, "content-type": "application/json; charset=utf-8" }, '{"x":1,"x":2}')).status).toBe(200);
  });
  it.each([false, true])("128KiB body limit（chunked=%s）在任何上游请求前", async (chunked) => {
    const body = JSON.stringify({ text: "a".repeat(128 * 1024) });
    expect((await send(web, "/v1/mutations/previews", "POST", {
      ...postHeaders, ...(chunked ? { "transfer-encoding": "chunked" } : { "content-length": String(Buffer.byteLength(body)) }),
    }, body)).status).toBe(413);
    expect(requests).toHaveLength(0);
  });
  it.each(["/previews?x=y", "/commands?x=1&x=2", "/previews%2f"])("POST query/encoded path %s 不访问上游", async (path) => {
    expect((await send(web, `/v1/mutations${path}`, "POST", postHeaders, "{}")).status).toBe(400);
    expect(requests).toHaveLength(0);
  });
  it("恰好128KiB可完成收流；收齐前不创建上游请求", async () => {
    const body = JSON.stringify({ text: "a".repeat(128 * 1024 - 11) });
    expect(Buffer.byteLength(body)).toBe(128 * 1024);
    const req = request({ hostname: "127.0.0.1", port: port(web), path: "/v1/mutations/previews", method: "POST", headers: { ...postHeaders, origin: origin(web) } });
    const response = new Promise<number>((done, reject) => {
      req.on("response", (res) => { res.resume(); res.on("end", () => done(res.statusCode!)); });
      req.on("error", reject);
    });
    req.write(body.slice(0, 20));
    await new Promise((done) => setTimeout(done, 20));
    expect(requests).toHaveLength(0);
    req.end(body.slice(20));
    expect(await response).toBe(200);
    expect(requests).toHaveLength(1);
  });
  it("凭据 Referer 和双重 Host 同源混淆拒绝", async () => {
    expect((await send(web, undefined, "GET", { referer: `http://user:pass@127.0.0.1:${port(web)}/` })).status).toBe(403);
    expect((await send(web, undefined, "GET", { host: `localhost:${port(web)}` })).status).toBe(403);
    expect(requests).toHaveLength(0);
  });
  it("上游响应流中断只返回固定安全错误", async () => {
    respond = (res) => {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.write('{"text":"unfinished');
      setTimeout(() => res.destroy(), 5);
    };
    const result = await send(web);
    expect(result.status).toBe(502);
    expect(result.body).not.toContain("unfinished");
  });
  it("请求中途断开不会发上游", async () => {
    const req = request({ hostname: "127.0.0.1", port: port(web), path: "/v1/mutations/previews", method: "POST", headers: { ...postHeaders, origin: origin(web) } });
    req.on("error", () => {});
    req.write('{"text":"unfinished');
    await new Promise((done) => setTimeout(done, 20));
    req.destroy();
    await new Promise((done) => setTimeout(done, 20));
    expect(requests).toHaveLength(0);
  });
  it("disabled namespace POST 固定503；不接管 B1/静态页面", async () => {
    const offline = await frontend();
    expect((await send(offline, "/v1/mutations/commands", "POST", {}, "{}")).status).toBe(503);
    expect((await send(offline)).status).toBe(503);
    expect((await send(web, "/v1/management/jobs")).body).toBe("static");
    expect((await send(web, "/")).body).toBe("static");
    expect(requests).toHaveLength(0);
  });
  it.each([302, 401, 403, 409, 422, 500, 503])("上游 %s 错误安全 JSON，无 redirect/key/rawstack", async (status) => {
    respond = (res) => { res.writeHead(status, { Location: "http://evil", "Content-Type": "application/json" }); res.end(JSON.stringify({ stack: "raw-stack", secret: writeKey })); };
    const result = await send(web);
    expect(result.status).toBe(status === 302 ? 502 : status);
    expect(result.headers.location).toBeUndefined();
    expect(result.body.includes(writeKey) || result.body.includes(readKey) || result.body.includes("raw-stack") || result.body.includes(origin(upstream))).toBe(false);
  });
  it.each(["write", "read", "escaped", "stack", "invalid", "html", "oversize"])("成功响应也拦截 %s", async (mode) => {
    respond = (res) => {
      res.writeHead(200, { "Content-Type": mode === "html" ? "text/html" : "application/json" });
      res.end(mode === "write" ? JSON.stringify({ text: writeKey }) : mode === "read" ? JSON.stringify({ text: readKey }) : mode === "escaped" ? `{"text":"${[...writeKey].map((c) => `\\u${c.charCodeAt(0).toString(16).padStart(4, "0")}`).join("")}"}` : mode === "stack" ? '{"raw_stack":"bad"}' : mode === "oversize" ? JSON.stringify({ text: "a".repeat(512 * 1024) }) : "not json");
    };
    expect((await send(web)).status).toBe(502);
  });
  it("连接失败无日志或 target", async () => {
    const offline = await frontend("http://127.0.0.1:1");
    const log = vi.spyOn(console, "error").mockImplementation(() => {});
    try { expect((await send(offline)).status).toBe(502); expect(log).not.toHaveBeenCalled(); }
    finally { log.mockRestore(); }
  });
});

it("实际 Vite dev fail closed/loopback/CORS；preview hook 不存在", async () => {
  vi.stubEnv("KNOWLEDGE_MUTATION_ENABLED", undefined);
  const config = await resolveConfig({ configFile: resolve("vite.config.ts"), logLevel: "silent" }, "serve");
  expect(config.server.host).toBe("127.0.0.1");
  expect(config.server.cors).toBe(false);
  expect(config.server.allowedHosts).not.toBe(true);
  expect(config.server.proxy).toBeUndefined();
  expect(mutationProxy().configurePreviewServer).toBeUndefined();
  const vite = await createServer({ configFile: resolve("vite.config.ts"), logLevel: "silent", server: { port: 0 } });
  try {
    await vite.listen();
    expect((await send(vite.httpServer! as Server)).status).toBe(503);
  } finally { await vite.close(); }
});

it("隔离最小内存 build：两个 secrets 都不进 browser/config.env，不构建并发 UI", async () => {
  for (const [name, value] of Object.entries(env())) vi.stubEnv(name, value);
  const root = await mkdtemp(join(tmpdir(), "mutation-build-"));
  try {
    await writeFile(join(root, "index.html"), '<script type="module" src="/entry.js"></script>');
    await writeFile(join(root, "entry.js"), "console.log(import.meta.env, process.env)");
    const configFile = resolve("vite.config.ts");
    const config = await resolveConfig({ configFile, root, logLevel: "silent" }, "build");
    const output = await build({ configFile, root, publicDir: false, logLevel: "silent", build: { write: false } });
    const text = JSON.stringify(output) + JSON.stringify(config.env);
    expect([readKey, writeKey, "KNOWLEDGE_MUTATION_KEY", "KNOWLEDGE_API_KEY", "http://127.0.0.1:8015"].some((value) => text.includes(value))).toBe(false);
    expect(Object.keys(config.env).some((name) => name.startsWith("KNOWLEDGE_"))).toBe(false);
  } finally { await rm(root, { recursive: true, force: true }); }
}, 15_000);

it("已启用配置的实际 preview 仍无写代理", async () => {
  let calls = 0;
  const upstream = await listen(httpServer((_req, res) => { calls++; res.end("upstream"); }));
  for (const [name, value] of Object.entries(env(origin(upstream)))) vi.stubEnv(name, value);
  const root = await mkdtemp(join(tmpdir(), "mutation-preview-"));
  const server = await preview({ configFile: resolve("vite.config.ts"), root, logLevel: "silent", build: { outDir: root }, preview: { port: 0 } });
  try {
    await writeFile(join(root, "index.html"), "static");
    const result = await send(server.httpServer as Server, "/v1/mutations/commands", "POST", {}, "{}");
    expect(calls).toBe(0);
    expect([404, 503]).toContain(result.status);
    expect(result.headers["access-control-allow-origin"]).toBeUndefined();
    expect(result.body.includes(readKey) || result.body.includes(writeKey)).toBe(false);
  } finally {
    (server.httpServer as Server).closeAllConnections();
    await new Promise<void>((done, reject) => server.httpServer.close((error) => error ? reject(error) : done()));
    await rm(root, { recursive: true, force: true });
  }
});
