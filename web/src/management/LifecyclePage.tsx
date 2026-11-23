import React from "react";

import {
  useDocumentDiffPage,
  useDocumentPage,
  useEvidencePage,
  useJobPage,
  useJobsPage,
  useLineagePage,
  useRevisionPage,
  type ManagementQueryState,
} from "./hooks";
import {
  lifecycleDiffHash,
  lifecycleDocumentHash,
  lifecycleEvidenceHash,
  lifecycleJobHash,
  lifecycleJobsHash,
  lifecycleLineageHash,
  lifecycleRevisionHash,
  type LifecycleRoute,
} from "./route";
import { ManagementError, getManagementErrorMessage } from "./types";
import { DiffView } from "./components/DiffView";
import { DocumentDetail } from "./components/DocumentDetail";
import { EvidenceView } from "./components/EvidenceView";
import { JobDetail } from "./components/JobDetail";
import { JobList } from "./components/JobList";
import { LineageView } from "./components/LineageView";
import { ResourceState, type ResourceStateKind } from "./components/ResourceState";
import { ReplayBanner } from "./components/ReplayBanner";
import { RevisionDetail } from "./components/RevisionDetail";

interface LifecyclePageProps {
  readonly route: LifecycleRoute;
  readonly navigate: (hash: string) => void;
}

interface ErrorDescriptor {
  readonly kind: ResourceStateKind;
  readonly title: string;
  readonly description: string;
}

type JobsRouteProps = {
  readonly route: Extract<LifecycleRoute, { kind: "jobs" }>;
  readonly navigate: (hash: string) => void;
};

type SingleRouteProps<RouteKind extends LifecycleRoute["kind"]> = {
  readonly route: Extract<LifecycleRoute, { kind: RouteKind }>;
  readonly navigate: (hash: string) => void;
};

function withReplayChrome(mode: LifecycleRoute["mode"], content: React.ReactElement): React.ReactElement {
  return mode === "replay" ? <div className="space-y-5"><ReplayBanner />{content}</div> : content;
}

export const LifecyclePage: React.FC<LifecyclePageProps> = ({ route, navigate }) => {
  switch (route.kind) {
    case "jobs":
      return <JobsRouteView navigate={navigate} route={route} />;
    case "job":
      return <JobRouteView navigate={navigate} route={route} />;
    case "revision":
      return <RevisionRouteView navigate={navigate} route={route} />;
    case "document":
      return <DocumentRouteView navigate={navigate} route={route} />;
    case "diff":
      return <DiffRouteView navigate={navigate} route={route} />;
    case "lineage":
      return <LineageRouteView navigate={navigate} route={route} />;
    case "evidence":
      return <EvidenceRouteView navigate={navigate} route={route} />;
    case "invalid":
      return (
        <ResourceState
          description="链接包含未知路径、非法 UUID 或不受支持的查询参数，因此页面停在安全页，不发起任何管理请求。为避免泄露凭证或本机路径，这里不会回显原始 hash。"
          kind="invalid-route"
        />
      );
  }
};

const JobsRouteView: React.FC<JobsRouteProps> = ({ route, navigate }) => {
  const state = useJobsPage(route.status, route.offset);
  return withReplayChrome(route.mode, renderQuery(state, {
    error: describeError(state.error, "jobs", route.mode),
    ready: (page) => (
      <JobList
        buildJobHref={(id) => lifecycleJobHash(id, { mode: route.mode })}
        onPageChange={(offset) => navigate(lifecycleJobsHash({ offset, status: route.status, mode: route.mode }))}
        onRefresh={state.reload}
        onStatusChange={(status) => navigate(lifecycleJobsHash({ status, offset: 0, mode: route.mode }))}
        page={page}
        refreshing={state.refreshing}
        selectedStatus={route.status}
      />
    ),
  }));
};

const JobRouteView: React.FC<SingleRouteProps<"job">> = ({ route }) => {
  if (route.kind !== "job") return null;
  const state = useJobPage(route.id);
  return withReplayChrome(route.mode, renderQuery(state, {
    error: describeError(state.error, "resource", route.mode),
    ready: (job) => (
      <JobDetail
        buildJobHref={(id) => lifecycleJobHash(id, { mode: route.mode })}
        buildRevisionHref={(id) => lifecycleRevisionHash(id, { mode: route.mode })}
        job={job}
        jobsHref={lifecycleJobsHash({ mode: route.mode })}
        onRefresh={state.reload}
        refreshing={state.refreshing}
      />
    ),
  }));
};

const RevisionRouteView: React.FC<SingleRouteProps<"revision">> = ({ route }) => {
  if (route.kind !== "revision") return null;
  const state = useRevisionPage(route.id);
  return withReplayChrome(route.mode, renderQuery(state, {
    error: describeError(state.error, "resource", route.mode),
    ready: (revision) => (
      <RevisionDetail
        buildDiffHref={(newId, oldId) => lifecycleDiffHash(newId, oldId, 0, { mode: route.mode })}
        buildDocumentHref={(id) => lifecycleDocumentHash(id, 0, { mode: route.mode })}
        buildEvidenceHref={(id) => lifecycleEvidenceHash(id, { mode: route.mode })}
        buildLineageHref={(id) => lifecycleLineageHash(id, 0, { mode: route.mode })}
        jobsHref={lifecycleJobsHash({ mode: route.mode })}
        onRefresh={state.reload}
        refreshing={state.refreshing}
        revision={revision}
      />
    ),
  }));
};

const DocumentRouteView: React.FC<SingleRouteProps<"document">> = ({ route, navigate }) => {
  if (route.kind !== "document") return null;
  const state = useDocumentPage(route.id, route.offset);
  return withReplayChrome(route.mode, renderQuery(state, {
    error: describeError(state.error, "resource", route.mode),
    ready: (document) => (
      <DocumentDetail
        buildDiffHref={(newId, oldId) => lifecycleDiffHash(newId, oldId, 0, { mode: route.mode })}
        buildDocumentHref={(id) => lifecycleDocumentHash(id, 0, { mode: route.mode })}
        buildEvidenceHref={(id) => lifecycleEvidenceHash(id, { mode: route.mode })}
        buildLineageHref={(id) => lifecycleLineageHash(id, 0, { mode: route.mode })}
        document={document}
        jobsHref={lifecycleJobsHash({ mode: route.mode })}
        onPageChange={(offset) => navigate(lifecycleDocumentHash(route.id, offset, { mode: route.mode }))}
        onRefresh={state.reload}
        refreshing={state.refreshing}
      />
    ),
  }));
};

const DiffRouteView: React.FC<SingleRouteProps<"diff">> = ({ route, navigate }) => {
  if (route.kind !== "diff") return null;
  const state = useDocumentDiffPage(route.newId, route.oldId, route.offset);
  return withReplayChrome(route.mode, renderQuery(state, {
    error: describeError(state.error, "diff", route.mode),
    ready: (diff) => (
      <DiffView
        buildDocumentHref={(id) => lifecycleDocumentHash(id, 0, { mode: route.mode })}
        buildEvidenceHref={(id) => lifecycleEvidenceHash(id, { mode: route.mode })}
        buildLineageHref={(id) => lifecycleLineageHash(id, 0, { mode: route.mode })}
        diff={diff}
        jobsHref={lifecycleJobsHash({ mode: route.mode })}
        onPageChange={(offset) => navigate(lifecycleDiffHash(route.newId, route.oldId, offset, { mode: route.mode }))}
        onRefresh={state.reload}
        refreshing={state.refreshing}
      />
    ),
  }));
};

const LineageRouteView: React.FC<SingleRouteProps<"lineage">> = ({ route, navigate }) => {
  if (route.kind !== "lineage") return null;
  const state = useLineagePage(route.id, route.offset);
  return withReplayChrome(route.mode, renderQuery(state, {
    error: describeError(state.error, "resource", route.mode),
    ready: (lineage) => (
      <LineageView
        buildDocumentHref={(id) => lifecycleDocumentHash(id, 0, { mode: route.mode })}
        buildEvidenceHref={(id) => lifecycleEvidenceHash(id, { mode: route.mode })}
        buildLineageHref={(id) => lifecycleLineageHash(id, 0, { mode: route.mode })}
        jobsHref={lifecycleJobsHash({ mode: route.mode })}
        lineage={lineage}
        onPageChange={(offset) => navigate(lifecycleLineageHash(route.id, offset, { mode: route.mode }))}
        onRefresh={state.reload}
        refreshing={state.refreshing}
      />
    ),
  }));
};

const EvidenceRouteView: React.FC<SingleRouteProps<"evidence">> = ({ route }) => {
  if (route.kind !== "evidence") return null;
  const state = useEvidencePage(route.id);
  return withReplayChrome(route.mode, renderQuery(state, {
    error: describeError(state.error, "evidence", route.mode),
    ready: (evidence) => (
      <EvidenceView
        buildDocumentHref={(id) => lifecycleDocumentHash(id, 0, { mode: route.mode })}
        buildLineageHref={(id) => lifecycleLineageHash(id, 0, { mode: route.mode })}
        buildRevisionHref={(id) => lifecycleRevisionHash(id, { mode: route.mode })}
        evidence={evidence}
        jobsHref={lifecycleJobsHash({ mode: route.mode })}
        onRefresh={state.reload}
        refreshing={state.refreshing}
      />
    ),
  }));
};

function renderQuery<T>(
  state: ManagementQueryState<T>,
  options: {
    readonly ready: (data: T) => React.ReactNode;
    readonly error: ErrorDescriptor;
    readonly empty?: ErrorDescriptor;
  },
): React.ReactElement {
  if (state.status === "loading" && !state.refreshing) {
    return <ResourceState kind="loading" />;
  }
  if (state.status === "error" || state.data === null) {
    return (
      <ResourceState
        description={options.error.description}
        kind={options.error.kind}
        onRetry={state.reload}
        title={options.error.title}
      />
    );
  }
  if (state.status === "empty" && options.empty) {
    return <ResourceState description={options.empty.description} kind={options.empty.kind} title={options.empty.title} />;
  }
  return <>{options.ready(state.data)}</>;
}

function describeError(
  error: unknown,
  context: "jobs" | "resource" | "diff" | "evidence" | "generic",
  mode: LifecycleRoute["mode"],
): ErrorDescriptor {
  const bundleLabel = mode === "replay" ? "静态回放数据" : "管理服务";
  if (error instanceof ManagementError) {
    if (error.kind === "unauthorized") {
      return { kind: "unauthorized", title: mode === "replay" ? "静态回放资源不可授权" : "管理服务需要授权", description: getManagementErrorMessage(error) };
    }
    if (error.kind === "gone") {
      return { kind: "gone", title: "历史资源已不可用", description: getManagementErrorMessage(error) };
    }
    if (error.kind === "conflict") {
      return {
        kind: "blocked",
        title: context === "diff" ? "无法读取这组文档 Diff" : "当前资源无法安全读取",
        description: getManagementErrorMessage(error),
      };
    }
    if (error.kind === "not_found") {
      if (context === "jobs") {
        return {
          kind: "service-unavailable",
          title: mode === "replay" ? "未找到静态回放文件" : "当前站点未启用管理服务",
          description: mode === "replay"
            ? "请先由父流程生成并放置 web/public/replay.json，再刷新本页。"
            : "版本快照页仍可用，但要查看实时工作台，需要同源启用 /v1/management 并带上 Bearer 认证。",
        };
      }
      return { kind: "not-found", title: "未找到对应资源", description: getManagementErrorMessage(error) };
    }
    if (["unavailable", "network", "timeout", "invalid_response"].includes(error.kind)) {
      return {
        kind: "service-unavailable",
        title: `${bundleLabel}暂不可用`,
        description: mode === "replay"
          ? "页面不会回退到 fixture。请检查 replay.json 的路径、体积、schema 与引用完整性后再点重试。"
          : "页面没有回退到静态 fixture。请检查同源管理服务是否启用，再点重试。",
      };
    }
  }
  return {
    kind: "error",
    title: context === "evidence" ? "证据读取失败" : "读取失败",
    description: getManagementErrorMessage(error),
  };
}
