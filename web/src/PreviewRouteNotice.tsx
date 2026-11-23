import React from "react";
import { ShieldCheck } from "lucide-react";
import { replayEntryHash } from "./management/route";

export const PreviewRouteNotice: React.FC = () => (
  <section className="rounded-2xl border border-amber-200 bg-amber-50 p-6 text-amber-950" role="status">
    <div className="flex items-center gap-2 text-lg font-semibold">
      <ShieldCheck size={22} />
      <h2>此预览仅开放静态回放</h2>
    </div>
    <p className="mt-3 max-w-3xl text-sm leading-6">
      实时 API 和受控更新仅用于本机工作台，本预览不会连接后端或提交变更。可从回放导览查看已导出的任务、评测对照和历史证据。
    </p>
    <a className="mt-4 inline-flex rounded-xl bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-700" href={replayEntryHash()}>
      查看三阶段回放
    </a>
  </section>
);
