import type { ReactNode } from "react";
import { ERROR_MESSAGES, type CommandDTO, type MutationError, type PreviewDTO } from "./types";
import { lifecycleDiffHash, lifecycleDocumentHash, lifecycleJobHash, lifecycleRevisionHash } from "../management/route";

export const panelClass = "rounded-2xl border border-slate-200 bg-white p-6 shadow-sm";
export const buttonClass = "rounded-xl border border-slate-300 px-4 py-2 text-sm font-semibold disabled:opacity-40";
export function Panel({ children }: { children: ReactNode }) { return <section className={panelClass}>{children}</section>; }
export function ErrorNotice({ error, context = "editor", uncertain = false }: { error?: MutationError; context?: "editor" | "command"; uncertain?: boolean }) {
  const message = uncertain && error?.kind === "expired"
    ? "原请求恢复时返回预览已过期，但此前提交结果仍不确定。请继续回查或用原请求重试，不要另发新更新。"
    : uncertain && error?.kind === "conflict"
    ? "原请求恢复时发生冲突，但不能据此判断此前未写入。请保留同一请求，继续回查或等待。"
    : error?.kind === "not_found" && context === "editor"
    ? "受控变更服务未启用，或当前授权文档已不可用。请刷新来源清单；原有只读和静态页面仍可使用。"
    : error ? ERROR_MESSAGES[error.kind] : undefined;
  return message ? <p role="alert" className="my-3 rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">{message}</p> : null;
}
export function Identity({ actor, scope }: { actor: string; scope: string }) {
  return <dl className="my-3 grid gap-2 text-sm sm:grid-cols-2">
    <div><dt className="text-slate-500">操作者（服务端绑定）</dt><dd className="break-all font-mono">{actor}</dd></div>
    <div><dt className="text-slate-500">范围 scope_id</dt><dd className="break-all font-mono">{scope}</dd></div>
  </dl>;
}
export function PreviewDiff({ preview }: { preview: PreviewDTO }) {
  return <div className="space-y-4">
    <dl className="space-y-2 text-sm">
      <div><dt>更新前 checksum</dt><dd className="break-all font-mono">{preview.expected_checksum}</dd></div>
      <div><dt>更新后 checksum</dt><dd className="break-all font-mono">{preview.new_checksum}</dd></div>
      <div><dt>预览到期时间（最长 300 秒）</dt><dd>{preview.expires_at}</dd></div>
    </dl>
    <p className="text-sm">新增 {preview.counts.added} · 修改 {preview.counts.modified} · 移动 {preview.counts.moved} · 未变 {preview.counts.unchanged} · 删除 {preview.counts.removed}</p>
    <p className="text-sm text-slate-500">以下仅展示服务端返回的原文差异。文本不会作为 HTML 执行，也不会生成推测性解释。</p>
    {preview.diff.map((entry, index) => <section key={index} className="overflow-hidden rounded-xl border border-slate-200">
      <h4 className="bg-slate-100 px-3 py-1 text-sm">{entry.kind}</h4>
      <div className="grid sm:grid-cols-2">
        <div className="min-w-0 bg-red-50 p-3"><h5>更新前</h5><pre className="whitespace-pre-wrap break-all text-sm">{entry.old_text ?? "（无）"}</pre></div>
        <div className="min-w-0 bg-green-50 p-3"><h5>更新后</h5><pre className="whitespace-pre-wrap break-all text-sm">{entry.new_text ?? "（无）"}</pre></div>
      </div>
    </section>)}
  </div>;
}
const evaluationMessages: Record<CommandDTO["evaluation_status"], string> = {
  passed: "评测门禁通过。知识变更已提交。",
  failed: "知识变更已成功提交，但评测门禁失败。失败评测不是回滚，文档仍保留已提交的新版本。",
  pending: "知识变更已提交，评测结果仍待确认。页面不会自动触发或重试评测，请回查命令或查看各任务详情。",
  not_triggered: "知识变更操作已提交，本次未触发评测。无变更操作不会触发评测。",
  unavailable: "知识变更已提交，评测状态暂不可用。页面不会自动触发或重试评测。",
};
export function CommandResult({ command }: { command: CommandDTO }) {
  return <Panel>
    <h3 className="text-xl font-bold text-green-800">{command.changed ? "知识变更已成功提交" : "无变更操作已提交"}</h3>
    <p className="mt-2 font-semibold">committed：true</p>
    <p className="my-3" role="status">{evaluationMessages[command.evaluation_status]}</p>
    <Identity actor={command.actor_id} scope={command.scope_id} />
    <dl className="space-y-2 text-sm">
      <div><dt>命令 ID（不是幂等键）</dt><dd className="break-all font-mono">{command.command_id}</dd></div>
      <div><dt>已提交 checksum</dt><dd className="break-all font-mono">{command.new_checksum}</dd></div>
    </dl>
    <ul className="mt-4 space-y-2 text-sm text-blue-800">
      <li><a href={lifecycleDocumentHash(command.document_id)}>查看已提交文档版本</a></li>
      {command.changed && <li><a href={lifecycleDiffHash(command.document_id, command.previous_document_id)}>查看这次文档 Diff</a></li>}
      {command.revision_ids.map(id => <li key={id}><a href={lifecycleRevisionHash(id)}>Revision：{id}</a></li>)}
      {command.job_ids.map(id => <li key={id}><a href={lifecycleJobHash(id)}>评测任务：{id}</a></li>)}
    </ul>
    <p className="mt-4 text-sm text-slate-600">多个评测任务需逐个查看。评测对照页由你手动选择参考和候选，不会自动挑选历史基线。</p>
    <a className="text-sm text-blue-800" href="#evaluation">打开评测对照，手动选择任务</a>
  </Panel>;
}
