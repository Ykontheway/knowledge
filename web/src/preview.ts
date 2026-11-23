import type { HashRoute } from "./management/route";
import { isEvaluationRoute, isGuideRoute, isLifecycleRoute, guideHash } from "./management/route";

/** Only the explicitly selected preview build disables live and mutation routes. */
export function isReplayPreview(mode = import.meta.env.MODE): boolean {
  return mode === "replay";
}

export function initialHash(hash: string, preview = isReplayPreview()): string {
  return hash || (preview ? guideHash({ mode: "replay" }) : "#overview");
}

export function previewRouteAllowed(route: HashRoute, preview = isReplayPreview()): boolean {
  if (!preview) return true;
  if (route.view === "changes") return false;
  if (isLifecycleRoute(route) || isEvaluationRoute(route) || isGuideRoute(route)) {
    return route.mode === "replay";
  }
  return true;
}
