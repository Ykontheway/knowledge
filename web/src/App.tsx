import React, { useEffect, useMemo, useState } from "react";

import { Layout, type View } from "./Layout";
import { OverviewPage } from "./OverviewPage";
import { TraceabilityPage } from "./TraceabilityPage";
import { VersionDiffPage } from "./VersionDiffPage";
import { PreviewRouteNotice } from "./PreviewRouteNotice";
import { initialHash, isReplayPreview, previewRouteAllowed } from "./preview";
import { EvaluationPage } from "./evaluation/EvaluationPage";
import { GuidePage } from "./evaluation/GuidePage";
import { LifecyclePage } from "./management/LifecyclePage";
import { ManagementRuntimeProvider } from "./management/runtime";
import { ChangesPage } from "./mutations/ChangesPage";
import {
  changesHash,
  demoHash,
  evaluationHash,
  getBreadcrumbMeta,
  guideHash,
  isEvaluationRoute,
  isGuideRoute,
  isLifecycleRoute,
  lifecycleEntryHash,
  parseHashRoute,
  replayEntryHash,
  type HashRoute,
} from "./management/route";

function currentHash(): string {
  return initialHash(typeof window === "undefined" ? "" : window.location.hash);
}

const App: React.FC = () => {
  const [route, setRoute] = useState<HashRoute>(() => parseHashRoute(currentHash()));
  const preview = isReplayPreview();
  const allowed = previewRouteAllowed(route, preview);

  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const handleHashChange = () => setRoute(parseHashRoute(currentHash()));
    handleHashChange();
    window.addEventListener("hashchange", handleHashChange);
    return () => window.removeEventListener("hashchange", handleHashChange);
  }, []);

  const breadcrumb = useMemo(() => getBreadcrumbMeta(route), [route]);
  const currentView: View = route.view;
  const isManagement = isLifecycleRoute(route) || isEvaluationRoute(route) || isGuideRoute(route);
  const managementMode = preview ? "replay" : isManagement ? route.mode : "live";
  const runtimeMode = preview || (managementMode === "replay" && !(isManagement && route.kind === "invalid"))
    ? "replay"
    : "live";

  const handleViewChange = (view: View) => {
    if (typeof window === "undefined") return;
    if (view === "lifecycle") window.location.hash = lifecycleEntryHash({ mode: managementMode });
    else if (view === "evaluation") window.location.hash = evaluationHash({ mode: managementMode });
    else if (view === "guide") window.location.hash = guideHash({ mode: managementMode });
    else if (view === "changes") window.location.hash = preview ? replayEntryHash() : changesHash();
    else window.location.hash = demoHash(view);
  };

  const navigate = (hash: string) => {
    if (typeof window === "undefined") return;
    window.location.hash = hash;
  };

  const content = !allowed ? (
    <PreviewRouteNotice />
  ) : route.view === "changes" ? (
    <ChangesPage navigate={navigate} route={route} />
  ) : isLifecycleRoute(route) ? (
    <LifecyclePage navigate={navigate} route={route} />
  ) : isEvaluationRoute(route) ? (
    <EvaluationPage navigate={navigate} route={route} />
  ) : isGuideRoute(route) ? (
    <GuidePage navigate={navigate} route={route} />
  ) : route.view === "trace" ? (
    <TraceabilityPage />
  ) : route.view === "diff" ? (
    <VersionDiffPage />
  ) : (
    <OverviewPage />
  );

  return (
    <ManagementRuntimeProvider mode={runtimeMode}>
      <Layout
        currentSection={allowed ? breadcrumb.section : "只读预览"}
        currentTitle={allowed ? breadcrumb.title : "此入口不在预览范围"}
        currentTone={allowed ? breadcrumb.tone : "replay"}
        currentView={currentView}
        onViewChange={handleViewChange}
        replayHref={replayEntryHash()}
        replayOnly={preview}
      >
        {content}
      </Layout>
    </ManagementRuntimeProvider>
  );
};

export default App;
