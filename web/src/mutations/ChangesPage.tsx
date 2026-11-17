import { useEffect, useState } from "react";
import { changesHash, type ChangesHashRoute } from "../management/route";
import { useChangesEditor, useCommandRecovery } from "./hooks";
import { buttonClass, CommandResult, ErrorNotice, Identity, Panel, PreviewDiff } from "./components";
import { MAX_TEXT_BYTES, textMetrics } from "./validation";

export function ChangesPage({ route, navigate }: { route: ChangesHashRoute; navigate: (hash: string) => void }) {
  return <div className="mx-auto max-w-5xl space-y-5">
    <Panel>
      <h2 className="text-2xl font-bold">受控变更 <strong className="ml-2 rounded-lg bg-amber-200 px-2 py-1 text-base text-amber-950">仅演示副本</strong></h2>
      <p className="mt-3 text-sm text-slate-700">默认关闭，只有服务端明确授权的当前文档才可更新。预览不会提交；确认后只更新文档，不提供评测重试或回滚操作。</p>
      <p className="mt-2 text-sm text-slate-600">身份和凭据由服务端绑定。浏览器不接收或保存密钥，确认令牌仅短暂保留在内存，不进入 URL、存储或日志。</p>
      <p className="mt-2 text-sm text-amber-900">导航、超时或停止等待不能取消后端提交。结果不确定时，服务器可能已提交。</p>
    </Panel>
    {route.kind === "invalid" ? <Panel>
      <h3 className="font-bold">链接无效，已停在安全页</h3><p>不接受未知、重复或非法参数，不展示原始链接，也不会发送请求。</p>
      <a href="#changes">返回受控变更</a>
    </Panel> : route.kind === "command" ? <Recovery key={route.commandId} id={route.commandId} navigate={navigate} />
      : <Editor key={route.documentId ?? "entry"} documentId={route.documentId} navigate={navigate} />}
  </div>;
}
function Editor({ documentId, navigate }: { documentId?: string; navigate: (hash: string) => void }) {
  const flow = useChangesEditor(documentId, id => navigate(changesHash({ command: id })));
  const metrics = textMetrics(flow.draft);
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    setNow(Date.now());
    if (!flow.preview) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [flow.preview]);
  const expired = flow.preview && Date.parse(flow.preview.dto.expires_at) <= now;
  const editable = !!flow.document && !flow.uncertain && flow.busy !== "apply" && flow.busy !== "load";
  return <>
    <Panel>
      <h3 className="text-lg font-bold">选择授权来源，编辑当前文档</h3>
      {flow.session && <Identity actor={flow.session.actor_id} scope={flow.session.scope_id} />}
      <label className="block text-sm">授权来源
        <select aria-label="授权来源" className="ml-3 rounded border p-2" value={flow.source ?? ""} disabled={!!flow.busy || flow.uncertain}
          onChange={e => { void flow.pickSource(e.target.value); }}>
          <option value="" disabled>请选择来源</option>
          {flow.session?.sources.map(source => <option key={source.source_id} value={source.source_id}>{source.label}</option>)}
        </select>
      </label>
      <p className="mt-2 text-sm text-slate-600">切换或刷新来源会获取最新清单和当前版本。已有草稿会保留，请核对它是否适用于所选来源。</p>
      <button type="button" className={`${buttonClass} mt-3`} disabled={!!flow.busy || flow.uncertain} onClick={() => { void flow.reload(); }}>重新加载当前文档（保留草稿）</button>
      {flow.busy === "load" && <p role="status">正在确认授权并读取当前文档…</p>}
      <ErrorNotice error={flow.error} />
      {flow.document && <dl className="my-3 space-y-1 text-sm">
        <div><dt>当前 document_id</dt><dd className="break-all font-mono">{flow.document.document_id}</dd></div>
        <div><dt>预条件 checksum（只更新此版本）</dt><dd className="break-all font-mono">{flow.document.checksum}</dd></div>
        <div><dt>内容类型</dt><dd>{flow.document.content_type}</dd></div>
      </dl>}
      <label className="mt-4 block font-semibold" htmlFor="mutation-draft">文档草稿（未受信文本）</label>
      <textarea id="mutation-draft" aria-label="文档草稿" value={flow.draft} disabled={!editable} onChange={e => flow.edit(e.target.value)}
        className="mt-2 h-72 w-full rounded-xl border border-slate-300 bg-slate-50 p-4 font-mono text-sm" />
      <p className="mt-2 text-sm" role="status">字符数（Unicode codepoint）：{metrics.characters}；UTF-8：{metrics.bytes} / {MAX_TEXT_BYTES} 字节。范围：[0, {metrics.characters})，按 codepoint 计数，emoji 不按两个字符算。</p>
      {!metrics.valid && <p role="alert" className="text-red-800">超过 64 KiB 或包含无效 Unicode，不能预览。JSON 请求另限 128 KiB。</p>}
      {flow.notice && <p role="status" className="my-3 text-amber-900">{flow.notice}</p>}
      <button type="button" className={`${buttonClass} mt-3 bg-slate-900 text-white`} disabled={!editable || !!flow.busy || !metrics.valid || flow.needsReload}
        onClick={() => { void flow.previewChanges(); }}>预览变更</button>
      {flow.busy && <button className={`${buttonClass} ml-3`} type="button" onClick={flow.stopWaiting}>停止等待（不取消后端操作）</button>}
      {flow.busy === "preview" && <p role="status">正在获取服务端预览，尚未提交…</p>}
    </Panel>
    {flow.preview && <Panel>
      <h3 className="mb-4 text-lg font-bold">服务端预览（尚未提交）</h3>
      <PreviewDiff preview={flow.preview.dto} />
      {expired && <p role="alert" className="my-3 text-amber-900">预览已过期，请重新预览。不能使用旧预览提交新变更。</p>}
      {!flow.preview.dto.changed ? <>
        <p className="my-3">内容无变更，无需提交，也不会触发评测。</p>
        <button type="button" className={buttonClass} onClick={flow.finishNoChange}>结束无变更预览</button>
      </> : <>
        <label className="my-4 flex gap-3 text-sm"><input aria-label="确认更新演示副本" type="checkbox" checked={flow.checked}
          disabled={!!expired || !!flow.busy} onChange={e => flow.setChecked(e.target.checked)} />
          我确认更新演示副本，已核对操作者、范围、原文差异和 checksum；已知门禁失败不回滚。</label>
        <button type="button" className={`${buttonClass} bg-amber-300 text-amber-950`} disabled={!flow.checked || !!expired || !!flow.busy || flow.uncertain}
          onClick={() => { void flow.submit(); }}>确认并提交</button>
        {flow.busy === "apply" && <p role="status" className="mt-3">正在等待提交结果。服务器可能已提交，请勿另开新请求。</p>}
      </>}
    </Panel>}
  </>;
}
function Recovery({ id, navigate }: { id: string; navigate: (hash: string) => void }) {
  const flow = useCommandRecovery(id);
  useEffect(() => {
    if (flow.result && flow.result.command_id !== id) navigate(changesHash({ command: flow.result.command_id }));
  }, [flow.result, id, navigate]);
  return <>
    {flow.result && <CommandResult command={flow.result} />}
    <Panel>
      <h3 className="font-bold">命令回查与结果恢复</h3>
      <p className="my-3 break-all font-mono text-sm">恢复标识：{id}</p>
      {!flow.result && <p role="status" className="my-3 font-semibold text-amber-900">提交结果不确定，服务器可能已提交。停止等待不代表取消，404 也不能证明未写入。</p>}
      {flow.pending ? <p className="text-sm">原请求、确认令牌和幂等键仍在内存。重试只发送相同 payload 和同一幂等键，即使预览过期也交由服务端恢复已有结果。响应丢失时此恢复标识是请求幂等键，尚未确认服务端命令 ID；回查可能暂时查不到。</p>
        : !flow.result && <p className="text-sm">刷新或离开后原令牌已丢失，只能按命令 ID 回查，不能自动新建提交。再次编辑必须先重新加载最新文档并重新预览。</p>}
      <ErrorNotice error={flow.error} context="command" uncertain={!flow.result} />
      <button type="button" className={`${buttonClass} mt-3`} disabled={flow.busy} onClick={() => { void flow.lookup(); }}>回查提交记录</button>
      {flow.pending && !flow.result && <button type="button" className={`${buttonClass} ml-3`} disabled={flow.busy} onClick={() => { void flow.retry(); }}>用原请求重试（同一幂等键）</button>}
      {flow.busy && <><p role="status">正在等待服务端结果…</p><button type="button" className={`${buttonClass} mt-3`} onClick={flow.stopWaiting}>停止等待（不取消后端操作）</button></>}
      {flow.result && <p className="mt-3"><a href="#changes">重新加载最新文档，再开始一次变更</a></p>}
      {!flow.pending && !flow.result && <p className="mt-3"><a href="#changes">返回编辑页（先重新加载当前版本）</a></p>}
    </Panel>
  </>;
}
