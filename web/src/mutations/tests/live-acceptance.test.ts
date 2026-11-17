// @vitest-environment jsdom
// 默认只有一个 skipped 测试；无 production fetch/client/schema 修改，无伪造 DTO。
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import { spawnSync } from "node:child_process";
import { writeFileSync, lstatSync, realpathSync } from "node:fs";
import { resolve, dirname, relative, isAbsolute } from "node:path";
import { MutationHttpClient } from "../client";
import type { CommandRequest, PreviewDTO } from "../types";
import { validateMutation } from "../validation";
import { ChangesPage } from "../ChangesPage";
import { forgetKnown, forgetPending, pendingCommand } from "../hooks";
import { parseHashRoute, type ChangesHashRoute } from "../../management/route";
import { ManagementClient } from "../../management/client";
import { compareJobs } from "../../evaluation/comparison";

const enabled = process.env.KNOWLEDGE_MUTATION_ACCEPTANCE === "1";
const realFetch = globalThis.fetch;
const roots = new Set<Root>();
const environment = globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean };
const previousAct = environment.IS_REACT_ACT_ENVIRONMENT;
const cleanupIds = new Set<string>();
function env(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error("B4_CONFIG_MISSING");
  return value;
}
function must(condition: unknown, code: string): asserts condition {
  if (!condition) throw new Error(code);
}
afterEach(async () => {
  await act(async () => { for (const root of roots) root.unmount(); });
  roots.clear(); document.body.replaceChildren();
  for (const id of cleanupIds) { forgetKnown(id); forgetPending(id); }
  cleanupIds.clear(); globalThis.fetch = realFetch;
  if (previousAct === undefined) delete environment.IS_REACT_ACT_ENVIRONMENT;
  else environment.IS_REACT_ACT_ENVIRONMENT = previousAct;
});
async function tick(action: () => void = () => undefined) {
  await act(async () => { action(); await new Promise(resolve => setTimeout(resolve, 20)); });
}
async function wait(predicate: () => boolean) {
  const end = Date.now() + 30_000;
  while (Date.now() < end) { if (predicate()) return; await tick(); }
  throw new Error("B4_UI_WAIT_TIMEOUT");
}
function button(container: HTMLElement, text: string): HTMLButtonElement {
  const found = [...container.querySelectorAll("button")].find(item => item.textContent?.trim() === text);
  must(found, "B4_BUTTON_MISSING"); return found;
}
function privateTarget(manifest: string, target: string) {
  const parent = dirname(realpathSync(manifest));
  must(realpathSync(dirname(target)) === parent && dirname(resolve(target)) === parent,
    "B4_REPORT_OUTSIDE_OWNED_SCOPE");
  const info = lstatSync(parent);
  must(!info.isSymbolicLink() && (info.mode & 0o777) === 0o700 && info.uid === process.getuid?.(), "B4_NOT_PRIVATE");
}
function readonlySnapshot(manifest: string) {
  const repo = resolve(import.meta.dirname, "../../../..");
  const relativeManifest = relative(resolve(repo, ".konwledge/mutation-demo"), manifest);
  must(relativeManifest !== "" && !relativeManifest.startsWith("..") && !isAbsolute(relativeManifest), "B4_NOT_OWNED");
  const result = spawnSync(env("B4_PYTHON"), [resolve(repo, "scripts/mutation_workbench_acceptance.py"),
    "--snapshot-manifest", manifest], { cwd: repo, encoding: "utf8", timeout: 20_000,
    env: { PATH: process.env.PATH, HOME: process.env.HOME, PYTHONDONTWRITEBYTECODE: "1" } });
  must(result.status === 0, "B4_READONLY_SNAPSHOT_FAILED");
  return JSON.parse(result.stdout) as { core_hash: string; counts: Record<string, number> };
}

describe.skipIf(!enabled)("B4 真实 Vite/API/ChangesPage 验收", () => {
  it("真实预览显式确认、提交响应丢失回查，重启无 token GET 恢复及 B3 对照", async () => {
    environment.IS_REACT_ACT_ENVIRONMENT = true;
    const origin = env("B4_WEB_ORIGIN");
    must(/^http:\/\/127\.0\.0\.1:[1-9][0-9]{0,4}$/.test(origin), "B4_NOT_LOOPBACK");
    must(![5175, 8015].includes(Number(new URL(origin).port)), "B4_RESERVED_PORT");
    const manifest = env("B4_MANIFEST");
    privateTarget(manifest, env("B4_REPORT"));
    let discard = process.env.B4_PHASE === "update";
    let allowLookup = !discard;
    let commandRequest: CommandRequest | undefined;
    let preview: PreviewDTO | undefined;
    let sentCommands = 0;
    let lookupCount = 0;
    // 唯一 wrapper：补 loopback origin 与真实浏览器同源头；保持实际 client Intent。
    // 不安装 auth、不生成 DTO；响应丢失仅发生在上游真正成功之后。
    const fetcher = async (path: string, init: RequestInit): Promise<Response> => {
      must(path.startsWith("/v1/"), "B4_UNEXPECTED_REQUEST");
      const headers = new Headers(init.headers);
      headers.set("Origin", origin); headers.set("Sec-Fetch-Site", "same-origin");
      must(!headers.has("Authorization"), "B4_BROWSER_HAS_CREDENTIAL");
      if (init.method === "POST") must(headers.get("X-Knowledge-Intent") === "document-update", "B4_INTENT_CHANGED");
      if (path === "/v1/mutations/commands") {
        sentCommands++;
        commandRequest = JSON.parse(init.body as string) as CommandRequest;
        cleanupIds.add(commandRequest.idempotency_key);
      }
      if (path.startsWith("/v1/mutations/commands/")) {
        lookupCount++;
        const end = Date.now() + 30_000;
        while (!allowLookup && Date.now() < end && !init.signal?.aborted) {
          await new Promise(resolve => setTimeout(resolve, 20));
        }
        must(allowLookup, "B4_LOOKUP_NOT_RELEASED");
      }
      const response = await realFetch(origin + path, { ...init, headers });
      if (path === "/v1/mutations/previews" && response.ok) {
        preview = validateMutation("PreviewDTO", await response.clone().json());
      }
      if (path === "/v1/mutations/commands" && discard && response.ok) {
        discard = false;
        // 先收到服务器 committed DTO，随后只丢弃浏览器收到的响应。
        const committed = validateMutation("CommandDTO", await response.json());
        must(committed.committed, "B4_NOT_COMMITTED_BEFORE_DROP");
        throw new TypeError("B4_SIMULATED_RESPONSE_LOSS");
      }
      return response;
    };
    globalThis.fetch = (input, init) => {
      must(typeof input === "string", "B4_UNEXPECTED_FETCH_INPUT");
      return fetcher(input, init ?? {});
    };
    const client = new MutationHttpClient(fetcher);
    const management = new ManagementClient(fetcher);
    const container = document.createElement("div"); document.body.appendChild(container);
    const root = createRoot(container); roots.add(root);
    function render(hash: string) {
      window.history.replaceState(null, "", hash);
      const route = parseHashRoute(hash);
      must(route.view === "changes", "B4_BAD_ROUTE");
      root.render(createElement(ChangesPage, { route: route as ChangesHashRoute, navigate: render }));
    }
    if (process.env.B4_PHASE === "update") {
      const session = await client.getSession();
      must(session.actor_id === "demo-editor" && session.scope_id === env("B4_SCOPE_ID"), "B4_IDENTITY_MISMATCH");
      const original = await client.getDocument(env("B4_DOCUMENT_ID"));
      must(session.sources.some(s => s.source_id === original.source_id) && original.source_id === env("B4_SOURCE_ID"), "B4_SOURCE_NOT_ALLOWED");
      await tick(() => render(`#changes?document=${original.document_id}`));
      await wait(() => container.querySelector<HTMLTextAreaElement>("textarea")?.disabled === false);
      const area = container.querySelector<HTMLTextAreaElement>("textarea")!;
      must(area.value === original.text, "B4_CURRENT_TEXT_MISMATCH");
      const anchor = "同一外层事务合并为一个任务";
      must(original.text.split(anchor).length === 2, "B4_ANCHOR_NOT_UNIQUE");
      const safe = original.text.replace(anchor, "一个任务合并同一外层事务内的变更") +
        "\n\nB4safeupdate 仅在授权演示副本验证安全可检索说明。";
      await tick(() => {
        Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(area, safe);
        area.dispatchEvent(new Event("input", { bubbles: true }));
      });
      const before = readonlySnapshot(manifest);
      await tick(() => button(container, "预览变更").click());
      await wait(() => !!container.querySelector("input[type=checkbox]"));
      must(preview && preview.changed && preview.diff.length === Object.values(preview.counts).reduce((a, b) => a + b, 0), "B4_INCOMPLETE_PREVIEW");
      must(before.core_hash === readonlySnapshot(manifest).core_hash && sentCommands === 0, "B4_PREVIEW_WROTE_CORE");
      expect(button(container, "确认并提交").disabled).toBe(true);
      await tick(() => container.querySelector<HTMLInputElement>("input[type=checkbox]")!.click());
      expect(button(container, "确认并提交").disabled).toBe(false);
      await tick(() => button(container, "确认并提交").click());
      await wait(() => !!commandRequest && lookupCount >= 1 && container.textContent?.includes("提交结果不确定") === true);
      must(!container.textContent?.includes("知识变更已成功提交"), "B4_PREMATURE_COMMIT_CLAIM");
      allowLookup = true;
      await wait(() => container.textContent?.includes("知识变更已成功提交") === true);
      must(commandRequest && Number(sentCommands) === 1 && lookupCount >= 1, "B4_UNCERTAIN_GENERATED_ANOTHER_COMMAND");
      const command = await client.getCommand(commandRequest.idempotency_key);
      must(command.command_id === commandRequest.idempotency_key && command.evaluation_status === "passed", "B4_RECOVERY_MISMATCH");
      must(pendingCommand(commandRequest.idempotency_key) === undefined, "B4_PENDING_NOT_RECOVERED");
      const stable = readonlySnapshot(manifest);
      const replay = await client.applyCommand(commandRequest);
      must(JSON.stringify(replay) === JSON.stringify(command) && stable.core_hash === readonlySnapshot(manifest).core_hash, "B4_DUPLICATE_WRITE");
      must(container.querySelector(`a[href='#lifecycle/jobs/${command.job_ids[0]}']`) &&
        container.querySelector(`a[href='#lifecycle/revisions/${command.revision_ids[0]}']`) &&
        container.querySelector("a[href='#evaluation']"), "B4_LINKS_MISSING");
      must(!window.location.hash.includes(commandRequest.confirmation_token) &&
        !container.textContent?.includes(commandRequest.confirmation_token) &&
        !localStorage.length && !sessionStorage.length, "B4_TOKEN_PERSISTED");
      writeFileSync(env("B4_REPORT"), JSON.stringify({ status: "passed", command_id: command.command_id,
        preview_core_unchanged: true, explicit_confirmation: true, response_lost_after_commit: true,
        uncertain_notice_before_get: true,
        identity_scoped_get_recovered: true, duplicate_write_prevented: true, credential_not_persisted: true,
        post_count: sentCommands, lookup_count: lookupCount }), { flag: "wx", mode: 0o600 });
    } else {
      must(process.env.B4_PHASE === "recover", "B4_UNKNOWN_PHASE");
      const id = env("B4_COMMAND_ID"); cleanupIds.add(id);
      // 新 Vitest 进程，没有旧内存 token/cache，hash reload 只发 GET。
      await tick(() => render(`#changes?command=${id}`));
      await wait(() => container.textContent?.includes("知识变更已成功提交") === true);
      must(sentCommands === 0 && lookupCount === 1 && !container.querySelector("textarea") &&
        !pendingCommand(id), "B4_RELOAD_SUBMITTED");
      const normal = await management.getJob(env("B4_POSITIVE_JOB"));
      const failed = await management.getJob(env("B4_FAULT_JOB"));
      const restored = await management.getJob(env("B4_RESTORE_JOB"));
      const down = compareJobs(normal, failed); const up = compareJobs(failed, restored);
      const decline = down.metrics.find(m => m.key === "mean_recall")?.delta;
      const recovery = up.metrics.find(m => m.key === "mean_recall")?.delta;
      must(normal.status === "passed" && failed.status === "failed" && restored.status === "passed" &&
        down.comparable && up.comparable && typeof decline === "number" && decline < 0 &&
        typeof recovery === "number" && recovery > 0, "B4_NOT_COMPARABLE");
      const oldDocument = await management.getDocument(env("B4_DOCUMENT_ID"), { limit: 100 });
      const failedDocument = await management.getDocument(env("B4_FAULT_DOCUMENT"), { limit: 100 });
      const diff = await management.getDocumentDiff(oldDocument.id, failedDocument.id, { limit: 100 });
      must(diff.changes.items.length === diff.changes.total && diff.changes.total > 0, "B4_DIFF_INCOMPLETE");
      must(oldDocument.units.items.length > 0, "B4_NO_HISTORICAL_UNITS");
      const evidence = await management.getEvidence(oldDocument.units.items[0]!.id);
      must(evidence.document_id === oldDocument.id && evidence.revision_ids.length > 0, "B4_HISTORICAL_EVIDENCE_MISSING");
      const jobs = await management.listJobs({ limit: 100 });
      must(jobs.items.some(j => j.id === failed.id && j.status === "failed"), "B4_OLD_FAILURE_LOST");
      writeFileSync(env("B4_REPORT"), JSON.stringify({ status: "passed", command_id: id,
        restart_credential_free_get_only: true, old_failure_preserved: true, historical_diff_complete: true,
        historical_evidence_available: true, comparable: true, mean_recall_down: decline,
        mean_recall_up: recovery, diff_count: diff.changes.total, post_count: sentCommands }), { flag: "wx", mode: 0o600 });
    }
  }, 120_000);
});
