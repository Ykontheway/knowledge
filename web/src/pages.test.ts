import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { snapshot } from "./data";
import { Layout } from "./Layout";
import { OverviewPage } from "./OverviewPage";
import { TraceabilityPage } from "./TraceabilityPage";
import { VersionDiffPage } from "./VersionDiffPage";
import config from "../tsconfig.json";

// Data-only tests cannot catch undefined component imports or identifiers that
// fail during rendering. These smoke tests cover that boundary without claiming
// to test browser interactions, fonts, or layout. `pnpm verify` also type-checks
// every page and builds the entry point (including its CSS and font imports).
describe("Demo page rendering", () => {
  it("renders the overview with the exported title", () => {
    const html = renderToStaticMarkup(createElement(OverviewPage));
    expect(html).toContain(snapshot.title);
    expect(html).toContain("增量索引优化");
    expect(html).toContain("预置示例语料的版本快照");
    expect(html).toContain("不代表实时状态");
    expect(html).toContain("knowledge demo export --check");
  });

  it("renders traceability with a source and document content", () => {
    const html = renderToStaticMarkup(createElement(TraceabilityPage));
    expect(html).toContain("原文内容");
    expect(html).toContain("CLI Inspector");
    expect(html).toContain("服务部署手册");
  });

  it("renders diff rows and all five change kinds", () => {
    const html = renderToStaticMarkup(createElement(VersionDiffPage));
    expect(html).toContain("单元级 Diff 详情");
    for (const kind of ["added", "modified", "moved", "unchanged", "removed"]) {
      expect(html).toContain(`${kind}:`);
    }
  });

  it("renders navigation and its repository link", () => {
    const html = renderToStaticMarkup(
      createElement(Layout, {
        currentView: "overview",
        currentSection: "版本快照",
        currentTitle: "总览",
        currentTone: "demo",
        onViewChange: () => {},
        replayHref: "#replay",
        children: createElement(OverviewPage),
      }),
    );
    expect(html).toContain("原文溯源");
    expect(html).toContain("生命周期工作台");
    expect(html).toContain("版本快照");
    expect(html).toContain("使用导览");
    expect(html).toContain("只读管理 API");
    expect(html).toContain("仅隔离副本");
    expect(html).toContain("https://github.com/Ykontheway/knowledge");
  });
});

describe("Type-checking policy", () => {
  it("keeps strict checking and unused-code checks enabled", () => {
    expect(config.compilerOptions.strict).toBe(true);
    expect(config.compilerOptions.noUnusedLocals).toBe(true);
    expect(config.compilerOptions.noUnusedParameters).toBe(true);
  });
});
