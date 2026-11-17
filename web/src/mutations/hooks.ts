import { useEffect, useRef, useState } from "react";
import { mutationClient } from "./client";
import { MutationError, safeError, type CommandDTO, type CommandRequest, type DocumentDTO, type PreviewDTO, type SessionDTO } from "./types";
import { textMetrics, serializeRequest } from "./validation";

export interface PendingCommand {
  readonly request: Readonly<CommandRequest>;
  readonly scope: string;
  readonly actor: string;
  readonly source: string;
  readonly previousDocument: string;
  readonly newChecksum: string;
}
// Short-lived process memory only. Navigation keeps the same request; refresh loses it.
// Keys are non-secret recovery identifiers. Tokens never leave this map except for POST.
const pendingCommands = new Map<string, PendingCommand>();
const knownCommands = new Map<string, CommandDTO>();
export function pendingCommand(id: string): PendingCommand | undefined { return pendingCommands.get(id); }
export function forgetPending(id: string): void { pendingCommands.delete(id); }
export function forgetKnown(id: string): void { knownCommands.delete(id); }
function rememberCommand(command: CommandDTO) {
  // Results contain no token. Bound this cache; never persist it.
  if (knownCommands.size >= 32) knownCommands.delete(knownCommands.keys().next().value!);
  knownCommands.set(command.command_id, command);
}
export function assertCommandMatches(command: CommandDTO, pending: PendingCommand): void {
  if (command.scope_id !== pending.scope || command.actor_id !== pending.actor || command.source_id !== pending.source ||
      command.previous_document_id !== pending.previousDocument || command.new_checksum !== pending.newChecksum || !command.committed) {
    throw new MutationError("invalid_response");
  }
}
interface ReadyPreview { dto: PreviewDTO; pending: PendingCommand }
interface EditorState {
  session?: SessionDTO; document?: DocumentDTO; draft: string; preview?: ReadyPreview;
  checked: boolean; busy?: "load" | "preview" | "apply"; error?: MutationError;
  notice?: string; needsReload: boolean; source?: string; uncertain: boolean; draftInitialized: boolean;
}
export function useChangesEditor(documentId: string | undefined, recover: (id: string) => void) {
  const [state, setState] = useState<EditorState>({ draft: "", checked: false, needsReload: false, uncertain: false, draftInitialized: false });
  const current = useRef(state);
  const alive = useRef(false);
  const sequence = useRef(0);
  const controller = useRef<AbortController | undefined>(undefined);
  const mutex = useRef(false);
  function patch(update: Partial<EditorState>) {
    if (!alive.current) return;
    current.current = { ...current.current, ...update };
    setState(current.current);
  }
  function interrupt() { sequence.current++; controller.current?.abort(); }
  function begin() { interrupt(); controller.current = new AbortController(); return { seq: sequence.current, signal: controller.current.signal }; }
  function active(seq: number) { return alive.current && sequence.current === seq; }

  async function load(source?: string, preserve = true) {
    if (mutex.current) return;
    const { seq, signal } = begin();
    const previous = current.current;
    patch({ busy: "load", error: undefined, preview: undefined, checked: false });
    try {
      const session = await mutationClient.getSession(signal);
      if (!active(seq)) return;
      const outstanding = [...pendingCommands.entries()].find(([, value]) => value.scope === session.scope_id && value.actor === session.actor_id);
      if (outstanding) { patch({ session, busy: undefined, uncertain: true }); recover(outstanding[0]); return; }
      const allowed = source || previous.source;
      const selected = allowed ? session.sources.find(s => s.source_id === allowed) : documentId
        ? session.sources.find(s => s.document_id === documentId) : session.sources[0];
      if (!selected) throw new MutationError(documentId || allowed ? "unauthorized" : "not_found");
      const document = await mutationClient.getDocument(selected.document_id, signal);
      if (!active(seq)) return;
      if (document.scope_id !== session.scope_id || document.source_id !== selected.source_id ||
          document.document_id !== selected.document_id || document.checksum !== selected.checksum || document.content_type !== selected.content_type) {
        throw new MutationError("conflict", 409);
      }
      const keepDraft = preserve && previous.draftInitialized;
      const changedHead = previous.document && (previous.document.document_id !== document.document_id || previous.document.checksum !== document.checksum);
      patch({ session, document, source: selected.source_id, draft: keepDraft ? previous.draft : document.text,
        draftInitialized: true, busy: undefined, needsReload: false, error: undefined,
        notice: keepDraft ? changedHead ? "当前文档版本已更新。你的草稿已保留，请核对后重新预览。" : "已获取当前文档，草稿已保留。请核对后重新预览。" : undefined });
    } catch (error) {
      if (active(seq)) patch({ busy: undefined, error: safeError(error), document: undefined, needsReload: true });
    }
  }
  useEffect(() => {
    alive.current = true;
    void load(undefined, false);
    return () => { alive.current = false; interrupt(); };
    // The parent keys the editor by validated document route.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  function edit(draft: string) {
    if (mutex.current || current.current.uncertain) return;
    interrupt();
    patch({ draft, preview: undefined, checked: false, busy: undefined, error: undefined,
      notice: current.current.preview ? "输入已更新，原预览失效。请重新预览。" : current.current.notice });
  }
  async function preview() {
    const s = current.current;
    if (mutex.current || s.busy || s.uncertain || s.needsReload || !s.document || !s.session || !textMetrics(s.draft).valid) return;
    const request = { scope_id: s.session.scope_id, source_id: s.document.source_id, document_id: s.document.document_id,
      expected_checksum: s.document.checksum, text: s.draft };
    const { seq, signal } = begin();
    patch({ busy: "preview", preview: undefined, checked: false, error: undefined, notice: undefined });
    try {
      serializeRequest("PreviewRequest", request);
      const dto = await mutationClient.createPreview(request, signal);
      if (!active(seq)) return;
      if (dto.scope_id !== request.scope_id || dto.source_id !== request.source_id || dto.document_id !== request.document_id ||
          dto.expected_checksum !== request.expected_checksum || Date.parse(dto.expires_at) <= Date.now()) throw new MutationError("invalid_response");
      if (typeof globalThis.crypto?.randomUUID !== "function") throw new MutationError("unavailable");
      const pending: PendingCommand = Object.freeze({ request: Object.freeze({ preview_id: dto.preview_id, confirmation_token: dto.confirmation_token,
        idempotency_key: globalThis.crypto.randomUUID(), confirmed: true as const }), scope: s.session.scope_id, actor: s.session.actor_id,
        source: s.document.source_id, previousDocument: s.document.document_id, newChecksum: dto.new_checksum });
      patch({ busy: undefined, preview: { dto, pending } });
    } catch (error) {
      if (active(seq)) { const safe = safeError(error); patch({ busy: undefined, error: safe, needsReload: safe.kind === "conflict" }); }
    }
  }
  async function submit() {
    const s = current.current;
    const ready = s.preview;
    if (mutex.current || s.busy || !ready || !s.checked || !ready.dto.changed || s.uncertain) return;
    if (Date.parse(ready.dto.expires_at) <= Date.now()) { patch({ preview: undefined, checked: false, error: new MutationError("expired") }); return; }
    mutex.current = true;
    const { seq, signal } = begin();
    const key = ready.pending.request.idempotency_key;
    pendingCommands.set(key, ready.pending);
    patch({ busy: "apply", error: undefined });
    try {
      const command = await mutationClient.applyCommand(ready.pending.request, signal);
      assertCommandMatches(command, ready.pending);
      rememberCommand(command);
      forgetPending(key);
      if (active(seq)) { patch({ busy: undefined, preview: undefined, checked: false }); recover(command.command_id); }
    } catch (error) {
      const safe = safeError(error);
      const definitive = safe.status !== undefined && [401, 403, 404, 409, 410, 413, 415, 422, 400].includes(safe.status);
      if (definitive) forgetPending(key);
      if (active(seq)) {
        if (definitive) patch({ busy: undefined, error: safe, preview: undefined, checked: false,
          needsReload: safe.kind !== "expired", notice: "草稿已保留。重新加载不会自动覆盖草稿。" });
        else { patch({ busy: undefined, uncertain: true, error: safe }); recover(key); }
      }
    } finally { mutex.current = false; }
  }
  function stopWaiting() {
    const s = current.current;
    if (s.busy === "apply" && s.preview) {
      const key = s.preview.pending.request.idempotency_key;
      interrupt(); patch({ uncertain: true, busy: undefined }); recover(key);
    } else { interrupt(); patch({ busy: undefined, notice: "已停止等待。停止等待不承诺取消服务端操作。" }); }
  }
  function finishNoChange() { if (!current.current.preview?.dto.changed) patch({ preview: undefined, checked: false, notice: "内容无变更，已结束预览。没有提交命令，也没有触发评测。" }); }
  return { ...state, edit, previewChanges: preview, submit, reload: () => load(),
    pickSource: (source: string) => load(source, true), setChecked: (checked: boolean) => patch({ checked }), stopWaiting, finishNoChange };
}

export function useCommandRecovery(id: string) {
  const [state, setState] = useState<{ busy: boolean; result?: CommandDTO; error?: MutationError }>(() => ({ busy: false, result: knownCommands.get(id) }));
  const alive = useRef(false);
  const sequence = useRef(0);
  const controller = useRef<AbortController | undefined>(undefined);
  const mutex = useRef(false);
  const pending = pendingCommand(id);
  async function run(retry: boolean) {
    if (mutex.current) return;
    if (retry && !pending) return;
    mutex.current = true;
    const seq = ++sequence.current;
    controller.current?.abort(); controller.current = new AbortController();
    setState(s => ({ ...s, busy: true, error: undefined }));
    try {
      const result = retry && pending ? await mutationClient.applyCommand(pending.request, controller.current.signal)
        : await mutationClient.getCommand(id, controller.current.signal);
      if (pending) assertCommandMatches(result, pending);
      if (!retry && !pending && result.command_id !== id) throw new MutationError("invalid_response");
      rememberCommand(result);
      forgetPending(id);
      if (alive.current && sequence.current === seq) setState({ busy: false, result });
    } catch (error) {
      if (alive.current && sequence.current === seq) setState(s => ({ ...s, busy: false, error: safeError(error) }));
      // Once uncertain, even 404/409/410 cannot prove the earlier write did not happen.
      // Keep the exact request, including its expired token, for server-side idempotent recovery.
    } finally { mutex.current = false; }
  }
  useEffect(() => {
    alive.current = true; void run(false);
    return () => { alive.current = false; sequence.current++; controller.current?.abort(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);
  function stopWaiting() { controller.current?.abort(); }
  return { ...state, pending, lookup: () => run(false), retry: () => run(true), stopWaiting };
}
