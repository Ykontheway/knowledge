import React, { useEffect, useMemo, useState } from "react";

import { Layout, type View } from "./Layout";
import { OverviewPage } from "./OverviewPage";
import { TraceabilityPage } from "./TraceabilityPage";
import { VersionDiffPage } from "./VersionDiffPage";
import { EvaluationPage } from "./evaluation/EvaluationPage";
import { GuidePage } from "./evaluation/GuidePage";
import { LifecyclePage } from "./management/LifecyclePage";
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
  type HashRoute,
} from "./management/route";

function currentHash(): string {
  return typeof window === "undefined" ? "#overview" : window.location.hash || "#overview";
}

const App: React.FC = () => {
  const [route, setRoute] = useState<HashRoute>(() => parseHashRoute(currentHash()));

  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const handleHashChange = () => setRoute(parseHashRoute(currentHash()));
    handleHashChange();
    window.addEventListener("hashchange", handleHashChange);
    return () => window.removeEventListener("hashchange", handleHashChange);
  }, []);

  const breadcrumb = useMemo(() => getBreadcrumbMeta(route), [route]);
  const currentView: View = route.view;

  const handleViewChange = (view: View) => {
    if (typeof window === "undefined") return;
    if (view === "lifecycle") window.location.hash = lifecycleEntryHash();
    else if (view === "evaluation") window.location.hash = evaluationHash();
    else if (view === "guide") window.location.hash = guideHash();
    else if (view === "changes") window.location.hash = changesHash();
    else window.location.hash = demoHash(view);
  };

  const navigate = (hash: string) => {
    if (typeof window === "undefined") return;
    window.location.hash = hash;
  };

  const content = route.view === "changes" ? (
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
    <Layout
      currentSection={breadcrumb.section}
      currentTitle={breadcrumb.title}
      currentTone={breadcrumb.tone}
      currentView={currentView}
      onViewChange={handleViewChange}
    >
      {content}
    </Layout>
  );
};

export default App;
