# Konwledge

Konwledge is a local-first toolkit for managing the full lifecycle of knowledge used by AI applications. The project will track where knowledge came from, how it changed, when it became stale, and whether a change improved or degraded retrieval quality.

> 状态：**v0.1.0 已准备、未发布（alpha）；B-R1、B-R2 已完成并验证，B5／U22 只读 MCP 已完成并验证；B6 受控 MCP 正文更新已完成并验证。** U17 完成本地发布准备；U18～U20（**Unreleased**）已加入本机上下文 API、对话导入与人工审核、只读数据库 schema 捕获。U14～U16 验收、知识变更自动评测和真实项目文档隔离验收已完成。B1 提供只读管理 API，B2 完成 V3 生命周期与变更视图，B3 完成 V4 只读评测对照与手动导览，B4 在当前 feature 分支完成受控变更交互并通过隔离验收，B6 主验收确认默认 MCP 零写入，Linux PTY／SDK session 与 wheel／sdist 隔离 smoke 通过；macOS／Windows 未测，原 V2 静态演示保留。版本仍为 `0.1.0` prepared，未创建 tag、PR、main 合并、GitHub Release、PyPI 发布或公开 live 部署。

> 静态回放数据导出、页面整合和预览构建已完成实现，当前只准备发布预览；命令与发布前置见 [静态回放预览](docs/replay-preview.md)。没有执行公开部署，本轮完整回归与静态预览验收已通过，结果见该说明。

B-R2 收尾复核（历史结果，不计作 B5／U22 验收）：`ruff check .` 通过，`ruff format --check .` 为 218 files，`mypy src tests scripts` 为 192 sources success；Python `pytest -q` 为 **1902 passed、5 skipped**，其中 3 个是既有可选用例，另 2 个是需显式设置 `KNOWLEDGE_WORKBENCH_DEMO_LIVE=1` 的 demo live 用例默认 skip；management／mutation schema `--check` 通过，两份输出保持不变；前端 `pnpm verify` **430 passed、2 skipped**。`tests/test_workbench_demo_live.py` 常规默认 **2 skipped**，显式设置 `KNOWLEDGE_WORKBENCH_DEMO_LIVE=1` 后统一入口 E2E **2 passed（41.21s）**。workbench 发行验证的 `WORKBENCH_SDIST_FILES` 现含入口脚本 3 项、测试 4 项、文档 1 项，共 8 个必需文件，缺任一项都拒绝通过。B-R1 的 [`.konwledge/b-r1-distribution-verified`](.konwledge/b-r1-distribution-verified) wheel／sdist 隔离 smoke 仍保留为历史证据，生产 build 的 584.38 kB chunk 提醒仍是非阻断优化项。

B 系列唯一主计划见 [B系列任务与重构路线](docs/integrated-demo-roadmap.md)。B-R1 已收敛 `web/src/shared/readBoundedBytes.ts`、`web/src/shared/validation.ts` 和 `scripts/schema_utils.py`；`SCHEMA_SDIST_FILES` 已纳入共享脚本及 `tests/test_schema_utils.py`，缺文件拒绝检查通过。**B-R2 已完成并验证**：`scripts/workbench.py` 统一 `list`、`demo`、`accept` 入口，`demo` 默认 `readonly`，`controlled` 必须显式 `--actor demo-editor`，`--prepare-only` 只准备不启动；`accept` 默认 `readonly` 只跑 seed／management／evaluation，`full` 才加 mutations，`--with-distribution` 再加 wheel／sdist smoke。受控演示的 CLI actor 示例使用 `demo-editor`，session role 仍是 `demo_editor`。通过 summary 见 [`.konwledge/workbench/7014a5a8-5dda-4406-b159-592d5620ab0b/summary.json`](.konwledge/workbench/7014a5a8-5dda-4406-b159-592d5620ab0b/summary.json) 和历史 full [`.konwledge/workbench/ef8c8448-e402-4951-8324-44579ce0045b/summary.json`](.konwledge/workbench/ef8c8448-e402-4951-8324-44579ce0045b/summary.json)，两次 Ctrl+C demo 证据见 [`.konwledge/workbench/9beb853b-909a-4165-86b7-5b59574baac7/summary.json`](.konwledge/workbench/9beb853b-909a-4165-86b7-5b59574baac7/summary.json) 和 [`.konwledge/workbench/17cf59ec-b616-47ee-8f52-5b79ea8824f4/summary.json`](.konwledge/workbench/17cf59ec-b616-47ee-8f52-5b79ea8824f4/summary.json)；较早一次 full 通过 [`.konwledge/workbench/2297462f-6e76-4207-abc0-8d4b8e625ba3/summary.json`](.konwledge/workbench/2297462f-6e76-4207-abc0-8d4b8e625ba3/summary.json) 保留为历史记录。统一入口不接受外部 database／manifest／路径／DSN／key，当前只支持具备 `/proc`、`subreaper`、`pidfd` 清理核验能力的 Linux 环境；macOS／Windows 会 fail-closed 返回 `cleanup_unknown`。后续衔接仍为 **B5／U22 只读 MCP → B6 受控命令**，原编号不变；B5／U22 与 B6 均已完成并验证，依赖链路已闭环。B6 主验收补齐 36 成功、17 拒绝、61 响应；3 次正文提交产生 3 个 command 与 3 个 job，评测链路为 `passed → failed → passed`，独立 PTY 批准 3 次，默认 MCP 零写入。MCP 使用独立 stdio 入口，不受 B-R2 的 Linux 清理依赖约束；B6 只在 Linux 实测通过，macOS／Windows 未测。生产阶段单独评审，不改 B1～B4 职责或不合并边界。

## Implemented increments

| Increment | Completed | Outcome |
| --- | --- | --- |
| U01 | 2026-10-12 | Installable package, CLI smoke test, linting, typing, tests, and CI |
| U02 | 2026-10-13 | Frozen domain models with validation and JSON roundtrips |
| U03 | 2026-10-15 | SQLite schema, typed repositories, explicit transactions, and persistence tests |
| U04 | 2026-10-16 | UTF-8 Markdown/TXT loading, normalization, SHA-256 fingerprints, and idempotent ingestion |
| U05 | 2026-10-19 | Heading-aware splitting, exact character ranges, section paths, and persisted traceability |
| U06 | 2026-10-20 | Typer import/list/show CLI, recursive corpus discovery, examples, and automatic local database setup |
| U07 | 2026-10-21 | Embedding provider protocol, deterministic hash test provider, batching service, and provider/model cache keys |
| U08 | 2026-10-23 | `VectorIndex` protocol, in-memory top-K search with metadata filters, optional LanceDB adapter, and `IndexingService` for `KnowledgeUnit` vectors |
| U09 | 2026-10-29 | Unit-level document diff, stable lineages, append-only revision chains, partial index rebuilds, `knowledge history`, and U08 LanceDB hardening |
| U10 | 2026-10-30 | Publication timeline, `active`/`stale`/`superseded`/`deleted` statuses, as-of snapshots, revert handling, `knowledge asof`/`stale`/`refresh`/`reconcile` |
| V1 | 2026-11-02 | Demo corpus and story, deterministic `knowledge demo build`, `knowledge demo export` with a Pydantic snapshot model, JSON Schema, golden-file tests, and a CI drift check |
| V2 | 2026-11-03 | Static demo site in `web/` (Vite, React, TypeScript, Tailwind): overview, traceability, and version-diff pages rendered from the snapshot; types generated from the JSON Schema; Vitest; GitHub Pages workflow |
| U11 | 2026-11-06 | Source-scoped TTL and known source-update policies; append-only configuration; atomic dry-run/apply stale scans; active-only publication API and CLI; controlled-clock regression tests |
| U12 | 2026-11-09 | Deterministic service-port conflict candidates, frozen two-sided evidence, atomic persistence, human review states and audit chain, historical preview and conflict CLI |
| U13 | 2026-11-09 | Transactionally synchronized SQLite FTS5, vector retrieval, deterministic RRF fusion, active-only/source/as-of filtering, missing-vector diagnostics, and search CLI |
| U14 | 2026-11-10 | Deterministic exact citations, whole-unit context budgets, duplicate/overlap filtering, source-safe JSON records, and context SDK/CLI |
| U15 | 2026-11-10 | Immutable versioned evaluation sets, retrieval metrics, read-only reports, and evaluation SDK/CLI |
| U16 | 2026-11-10 | Portable healthy baselines, deterministic report comparison, policy-driven regression gates, and CI-ready exit codes |
| U17 | 2026-11-11 | v0.1.0 metadata coherence, lazy root API, isolated wheel/sdist verification, and release/contributor/architecture documentation |
| U18 | Unreleased | 可选 `[api]` 本机只读 HTTP、`serve` 安全启动、OpenAI/LangChain SDK 验收、可选依赖及隔离分发验证（无版本提升） |
| U19 | Unreleased | 不可变对话版本、确定性候选提取、人工批准/拒绝审计，以及 conversation/candidate CLI（无版本提升） |
| U20 | Unreleased | SQLite/PostgreSQL 只读 schema 捕获、不可变版本历史、检索物化、导出和 schema diff（无版本提升） |
| B1 | Unreleased | 明确启用的只读管理 API、任务与历史证据导航、真实库 HTTP 验收 |
| V3（B2） | Unreleased | 保留 V2 静态演示，新增本机实时生命周期与变更视图、严格 dev proxy 和启动器 |
| V4（B3） | Unreleased | 只读评测对照、手动阶段导览与有界轮询；前端 179 passed／1 skipped、Python 1325 passed／3 skipped，隔离 HTTP／jsdom UI 联调及两页页面渲染检查通过 |
| B4 | Unreleased | 默认关闭的受控变更 demo：独立 bearer mutation key、server 绑定 mutation actor、manifest allowlist 当前正文更新、`#changes` 预览／确认提交／GET 恢复；本轮 scope `c2c9b890-e706-4362-a7fe-e4675edef052` 隔离验收通过 |
| B-R1 | Unreleased | 已完成并验证 shared reader／validation 与 schema 工具收敛；最终回归、B4 driver 与 wheel／sdist 隔离 smoke 通过，提交记录以 Git 历史为准 |
| B-R2 | Unreleased | 已完成并验证统一 `list`／`demo`／`accept` 入口，历史结果与 Linux 清理依赖保留 |
| B5／U22 | Unreleased | 已完成并验证只读 stdio MCP、可选 `[mcp]` 和五个查询工具；SDK `1.30.0` baseline、完整回归与 wheel／sdist 隔离安装通过 |
| B6 | Unreleased | 已完成并验证受控正文更新 MCP；36 成功／17 拒绝／61 响应，3 个 command／job，Linux PTY／SDK session 与 wheel／sdist 隔离 smoke 通过 |

Each increment builds on the preceding implementation. 当前分支包含 U01～U20、V1／V2、B1、V3（B2）、V4（B3）、B4、B-R1、B-R2、已完成并验证的 B5／U22 和 B6。`U` 扩展核心库，`V` 扩展展示；B4 默认关闭，MCP 须显式启动且默认只有五个只读工具。B6 须另加 `--controlled`，生产写权限与公开部署仍需另行明确授权。

## Why this project

Many RAG demos stop after documents can be chunked, embedded, and searched. Konwledge focuses on the work that follows:

- trace every knowledge unit back to its source;
- preserve revisions instead of silently overwriting content;
- identify stale, superseded, deleted, and conflicting knowledge;
- evaluate retrieval after every knowledge or indexing change;
- provide model-ready context with explicit citations.

## Planned delivery

The initial roadmap is split into small, testable uploads:

| Milestone | Target | Outcome |
| --- | --- | --- |
| Project foundation | Days 1–5 | Installable package, tests, linting, typing, and CI |
| Knowledge ingestion | Days 8–17 | Traceable Markdown and text ingestion |
| Knowledge lifecycle | Days 20–32 | Revisions, freshness, status, and conflict candidates |
| Retrieval | Days 35–38 | Hybrid retrieval and citation-aware context assembly |
| Knowledge CI | Days 41–45 | Versioned evaluation set and regression gates |
| Optional integrations | Days 46–60 | Model API, conversations, database schemas, UI, and MCP |

The roadmap names `v0.0.1-mvp`, `v0.1.0`, and `v0.2.0` as public checkpoints. A version appearing in source metadata or this roadmap does not mean that its tag or package has been published.

## Installation and quick start

Konwledge requires Python 3.11 or newer and an SQLite build with FTS5 enabled. The release candidate is not published on PyPI; install it from a clone:

```bash
python -m pip install .
knowledge --version
```

For a locally built artifact instead:

```bash
uv build
python -m pip install dist/konwledge-0.1.0-py3-none-any.whl
```

Expected output:

```text
knowledge 0.1.0
```

`python -m konwledge --version` invokes the same CLI. The `konwledge` console script remains a legacy alias; new examples use `knowledge`.

### End-to-end demo: import to regression gate

This recipe builds the packaged eight-step demo, searches current knowledge, assembles cited context, imports the committed gold set, writes a candidate report at the baseline's fixed time, and applies the committed policy:

```bash
uv sync --locked --dev
uv run knowledge demo build --force
uv run knowledge search "监听" -d .konwledge/demo/knowledge.db
uv run knowledge context "监听" --max-units 2 -d .konwledge/demo/knowledge.db
uv run knowledge evaluation import examples/evaluation-demo.json \
  -d .konwledge/demo/knowledge.db
uv run knowledge evaluation run 52522ebd-b1dc-4ace-824c-f8054c8547af \
  --version 1 --mode lexical --top-k 5 --candidate-limit 50 --rrf-k 60 \
  --at 2026-11-10T00:00:00Z -d .konwledge/demo/knowledge.db --json > candidate.json
uv run knowledge evaluation gate examples/evaluation-baseline.json candidate.json \
  --policy examples/evaluation-gate.json --json
```

A passing gate exits `0`; a valid regression exits `3`. Invalid input exits `2`, and runtime or file I/O failures exit `1`. In the packaged story, the active guide uses port `8080`; the FAQ's `8000` answer is stale and excluded by default. Baseline replacement is an intentional review action, never an automatic CI side effect. The packaged hash embedding provider and demo vectors exercise plumbing only; they are not semantic-quality or production-performance evidence.

## 后端验收与自动评测（Unreleased）

U14 增加真实 Token 预算；U15 保留原 6 条 Demo，另建 30 条独立用例；U16 增加默认质量门槛和 1,000 active 单元的 P95 性能验收。运行 `uv run knowledge quality acceptance` 即可检查，不修改业务库或人工基线。详见 [后端验收](docs/acceptance.md)。

业务知识变更自动评测默认关闭。导入自己的评测集后，用 `knowledge auto-evaluation enable --set-id <set-id> --version 1 -d .konwledge/knowledge.db` 绑定，再运行 `auto-evaluation run` 检查当前知识。之后文件发布／更新、候选批准、Schema 新版本和时效变化会自动评测，任务支持历史查询、重试及租约恢复。变更已提交但评测未通过时，CLI 返回 `3` 并明确提示；不自动回滚或更新基线。配置和边界见 [知识变更自动评测](docs/auto-evaluation.md)。

## 真实文档验收与后续开发

已用项目自身 `docs/auto-evaluation.md`、`docs/acceptance.md` 跑通隔离的真实文档验收：正向变更自动通过，关键证据缺失后自动失败，恢复后重新通过。固定 4 条用例、默认策略及数据集 hash 不变；失败知识已提交、失败报告保留，原样重导不触发任务。这里验证的是项目使用文档与 lexical 检索，不是生产业务库或生成答案质量。

```bash
uv run python scripts/real_knowledge_acceptance.py \
  --output-dir .konwledge/real-knowledge-acceptance
```

每次运行建立独立 SQLite 和文档副本，证据保存在输出根目录下的唯一运行目录，不覆盖旧报告，也不改原始文档。详见 [真实文档变更验收](docs/real-knowledge-acceptance.md)。

B1 已提供只读管理契约，B2 已完成 V3 生命周期与变更视图，B3 已完成 V4 评测对照与手动导览开发；现有静态演示保留。当前 feature 分支的 B4 已完成受控变更交互：`/v1/mutations` 默认关闭，需独立写密钥、manifest 和 actor 显式启用，只允许隔离 demo 库内 allowlist source 的当前正文修改，并保留幂等命令与评测审计。B1 没有 case-level query／cases，页面不造逐用例失败诊断。B5／U22 只读 MCP 已完成并验证，使用独立 stdio 入口且默认不开放写工具；B6 的显式受控正文更新也已完成并验证，主验收确认默认 MCP 零写入，3 次正文提交产生 3 个 command 与 3 个 job，Linux PTY／SDK session 与 wheel／sdist 隔离 smoke 通过，macOS／Windows 未测，不改变 B5 只读默认或新增写 HTTP。Snapshot V1 和现有上下文 API 保持兼容，没有公开 live 部署。详见 [B系列任务与重构路线](docs/integrated-demo-roadmap.md) 和 [受控变更工作台](docs/controlled-mutations.md)。

## 静态回放预览（Unreleased）

回放数据导出、页面整合与独立预览构建已完成实现，本轮只准备发布预览，不执行公开部署。仓库内 `web/public/replay.json` 已生成并通过 Python `--check`，包含固定可公开合成语料经正式 SDK／自动评测 outbox 产生的真实 `passed → failed → passed` 任务；同一 dataset／config、固定 4 条 cases，Recall 为 `1 → 2/3 → 1`。质量失败不回滚已提交知识，不声明业务原因或生成答案质量。本任务不新增 B 系列或 P 系列编号，B1～B6 历史验收范围与 `0.1.0` prepared 状态不变。

```bash
# 仓库根目录：只读检查现有回放文件，不重建数据库
uv run --frozen python scripts/export_replay.py --check --output web/public/replay.json
# web/：普通构建仍保留 Snapshot V1／live／B4
cd web
pnpm install --frozen-lockfile
pnpm verify
pnpm verify:preview
# 仅在需要查看本机预览时启动，不是公开部署
pnpm preview:replay --host 127.0.0.1
```

显式 `#replay`／`#replay/guide`／`#replay/evaluation`／`#replay/lifecycle/...` 复用 B1 DTO schema 和静态 transport，分页与导航保留 replay mode，坏 bundle 报错且无 live fallback。独立 replay preview 构建输出 `dist-preview`，空 hash 默认进入 `#replay/guide`，隐藏受控变更菜单并阻断手输 changes／live 路由，旧 V1 路由保留。导出只接受工具自建的安全合成库，不提供任意业务原文自动脱敏；输出拒绝 symlink／覆写，没有 `--database`／`--manifest`／`--URL`／`--force`。

Pages workflow 已改为手动 `workflow_dispatch`，`publish` boolean 默认 false；prepare 检查随源码提交的 JSON 并上传 `replay-preview` artifact，只有显式 true 才允许 publish job 部署。本轮不运行 Actions，未生成或验证可用的网站 URL；未来发布须确认 Pages Source、environment 权限／保护、默认分支已有可 dispatch 的 workflow，以及所选 ref 包含本轮实现。仅向 feature 分支推送不能保证新 workflow 名称或 UI 参数可用，不代办 main 变更。

完整命令、DTO／Page 结构、bundle bytes／hash 与发布前置见 [静态回放预览](docs/replay-preview.md)，实现状态见 [B系列任务与重构路线](docs/integrated-demo-roadmap.md)。本轮 Python 2540 passed／7 skipped、前端 529 passed／2 skipped、回放预览专项 91 项通过；完整证据与未验范围见该说明。

## 本机工作台统一入口（B-R2，Unreleased）

启动与验收统一使用 [工作台入口说明（B-R2 已完成并验证）](docs/workbench-entry.md)。`list` 只列命令；`demo` 默认 `--mode readonly`，`controlled` 必须显式 `--actor demo-editor`，`--prepare-only` 只准备不启动；`accept` 默认 `readonly` 只跑 seed／management／evaluation，`full` 才加 mutations，`--with-distribution` 再加 wheel／sdist smoke。受控演示的 CLI actor 示例使用 `demo-editor`，session role 仍是 `demo_editor`。通过 summary 见 [`.konwledge/workbench/7014a5a8-5dda-4406-b159-592d5620ab0b/summary.json`](.konwledge/workbench/7014a5a8-5dda-4406-b159-592d5620ab0b/summary.json) 和历史 full [`.konwledge/workbench/ef8c8448-e402-4951-8324-44579ce0045b/summary.json`](.konwledge/workbench/ef8c8448-e402-4951-8324-44579ce0045b/summary.json)；较早一次 full 通过 [`.konwledge/workbench/2297462f-6e76-4207-abc0-8d4b8e625ba3/summary.json`](.konwledge/workbench/2297462f-6e76-4207-abc0-8d4b8e625ba3/summary.json) 保留为历史记录；两次 Ctrl+C demo 停止证据见 [`.konwledge/workbench/9beb853b-909a-4165-86b7-5b59574baac7/summary.json`](.konwledge/workbench/9beb853b-909a-4165-86b7-5b59574baac7/summary.json) 和 [`.konwledge/workbench/17cf59ec-b616-47ee-8f52-5b79ea8824f4/summary.json`](.konwledge/workbench/17cf59ec-b616-47ee-8f52-5b79ea8824f4/summary.json)，两者都记为 `stopped`，不算验收 passed。原 `scripts/live_workbench.py` 和各验收 driver 继续独立使用，原命令见 [本机启动器](docs/live-workbench.md)。

默认 demo 会先在新隔离库生成正常／故障／恢复 seed，再启动已有 seed 的只读管理联调；准备会写隔离库，backend 启动也可能执行已有 schema／FTS 初始化。只读 demo 的 live 复核只做 HTTP GET：readonly backend 的 B4 session 路径返回 `404`，Vite Node dev proxy 未开启时返回 `503`，不要写成“全部 404”；seed 已有 3 个 jobs，demo 本身不新增 preview／command／额外 jobs。交互 API 只读，页面不新增 evaluation 或更新 baseline。临时 key 仅留在 backend 与 Vite Node 进程，浏览器同源 GET 不带 key；preview／dist 不提供该代理，不自动回退 fixture。统一入口不接受外部 database／manifest／路径／DSN／key，当前只支持具备 `/proc`、`subreaper`、`pidfd` 清理核验能力的 Linux 环境；macOS／Windows 不在已完成范围内，缺少必要能力时会 fail-closed 返回 `cleanup_unknown`，不会误报通过。

实时生命周期页面提供任务过滤、分页刷新，以及 revision／document／lineage／Diff／exact evidence 的 hash 导航。B3 新增 [评测对照](http://127.0.0.1:5175/#evaluation) 和 [手动导览](http://127.0.0.1:5175/#guide)：选择跨页保留，比例 delta 按百分点显示，null 为未评估。评测页手动刷新与有界观察共用刷新逻辑，刷新前记录列表头部，再重读当前页及按原 ID 选中的参考／候选；列表或选中任务读取中均视为 busy，不切换选择。导览刷新也重读当前页及已选的正常／故障／恢复任务。

无答案空检索和引用覆盖不证明 LLM 答案正确；单元状态是持久化当前缓存，stale_hits 不用它重算。观察由用户主动开启，每 10 秒刷新，最多 5 分钟／30 次；busy 跳过不延长窗口，隐藏、page key 变化、读取错误或卸载后停止，不自动恢复。停止仅阻止后续 tick，不承诺取消已发 HTTP，手动刷新仍可用。

### B3 最终验收

从仓库根目录跑 B3 隔离验收：

```bash
uv run python scripts/workbench_evaluation_acceptance.py
```

报告保存在 `.konwledge/workbench-evaluation-acceptance/<run-id>/report.json`，每次使用唯一目录，不改原始 docs 或用户库。2026-11-16 最后一次运行 `20261116T042018921245Z-951ad2f7` 通过：真实前端 client／DTO／comparison engine／jsdom UI 经 HTTP dev proxy 联调，mean Recall 为 `1 → 0.666667 → 1`。副本 CLI import 后新增 passed 任务，UI 提示、原选择与失败记录保留，`children_stopped=true`。

- 前端 `pnpm verify`：179 passed、1 skipped（10 files passed、1 skipped），typecheck、Snapshot 类型漂移、management 类型漂移与 build 通过；`pnpm install --frozen-lockfile` 通过。默认跳过的 1 项真实 HTTP integration 已由隔离验收另行运行通过，不计入普通回归通过数量。
- Python 完整回归：1325 passed、3 skipped；ruff check／format、mypy 169 个源文件及 Snapshot／schema 漂移检查通过。
- 页面渲染检查：评测对照与导览两页通过，控制台为空，内容无外溢。首屏结果位置已修正并复查，评测页先显示 Recall 100% → 66.67%、−33.33 个百分点，导览先显示阶段判定及对照链接。
- 构建隔离检查：用临时测试密钥执行真实 build，dist 扫描不含该密钥或测试后端地址；历史 B4 收尾 build 有 584.87 kB chunk 体积提醒，属非阻断优化项，不是功能失败。

本次云端浏览器无法直达 loopback，真实 HTTP／jsdom UI 联调与页面渲染检查各有范围，不代表浏览器整链点击验收。B3 对照条件与完整结果见 [评测工作台](docs/evaluation-workbench.md#回归命令与验收记录)，启动安全与 B2 历史验收见 [本机只读工作台](docs/live-workbench.md)。

## 受控变更工作台（B4，Unreleased）

B4 在当前 feature 分支已完成实现并通过隔离验收，但默认关闭，只面向 `scripts/prepare_mutation_demo.py` 生成的隔离 demo 库，不接受浏览器文件路径、SQL 凭据或任意写目标。B-R2 的显式 controlled demo 命令见 [统一工作台入口](docs/workbench-entry.md#controlled-demo-必须显式提供-actor)，该入口已完成并验证；受控 demo 的停止证据见 [`.konwledge/workbench/17cf59ec-b616-47ee-8f52-5b79ea8824f4/summary.json`](.konwledge/workbench/17cf59ec-b616-47ee-8f52-5b79ea8824f4/summary.json)。原 prepare 与 launcher 命令保留在 [受控变更工作台](docs/controlled-mutations.md#一分钟启动)。

启动器会为本次进程生成独立读／写 bearer key，浏览器继续只发同源请求；`#changes` 页面让用户选择允许的来源、编辑正文、查看完整 Diff、勾选确认后提交，`#changes?command=<id>` 仅按幂等标识做 GET 恢复。preview 绑定 source／当前 document／old checksum／new checksum／actor／scope／TTL／confirmation token；command 在 `BEGIN IMMEDIATE` 后校验并把命令、revision 与 auto-evaluation outbox 一并写入事务，评测失败不回滚已提交知识，不自动重试不确定写请求。

本轮完整 B4 HTTP／jsdom driver 通过，`children_stopped=true`，scope 为 `c2c9b890-e706-4362-a7fe-e4675edef052`，报告位于 [`.konwledge/mutation-demo/c2c9b890-e706-4362-a7fe-e4675edef052/b4-acceptance-report.json`](.konwledge/mutation-demo/c2c9b890-e706-4362-a7fe-e4675edef052/b4-acceptance-report.json)。三次变更产生的 command 和 jobs 各为 3，任务链路仍为 `passed → failed → passed`，mean Recall 为 `1 → 2/3 → 1`；提交后响应丢失只做 GET 恢复、不重复写，重启后历史失败／Diff／证据仍可回查。契约见 [受控变更工作台](docs/controlled-mutations.md)，本轮记录见 [B系列任务与重构路线](docs/integrated-demo-roadmap.md)。

## 工作台只读管理 API（B1，Unreleased）

```bash
# 先通过凭据管理器或进程环境注入非空 KNOWLEDGE_API_KEY。
knowledge serve --enable-management --host 127.0.0.1 --port 8000 \
  --database .konwledge/knowledge.db
```

管理端点默认关闭，开启后必须认证，全部为 GET。`/v1/management` 提供分页任务、revision、lineage、文档版本 Diff 和精确历史证据。普通响应使用白名单，不透传源全文、query、locator 或任意 payload；证据端点按明确授权返回对应版本的原文选段。读取不新增任务，不用最新正文替换历史证据。

```bash
uv run python scripts/management_api_acceptance.py \
  --database "<real-acceptance-run-directory>/knowledge.db" \
  --report .konwledge/b1-management-acceptance-new.json
```

脚本在真实文档验收库上通过 HTTPX ASGITransport 检查完整导航与只读边界，不监听公网、不代表已部署。详见 [管理 API 契约、安全边界与验收](docs/management-api.md)。

## 本机 API（U18，Unreleased）

```bash
python -m pip install '.[api]'
knowledge import examples --database .konwledge/knowledge.db
knowledge serve --host 127.0.0.1 --port 8000 --database .konwledge/knowledge.db
```

`serve` 仅接受 loopback（`127.0.0.1`、`::1`、`localhost`）与已有数据库；不会自动创建缺失库。启动允许现有 additive schema/FTS 初始化，HTTP 请求只读。密钥仅取自 `KNOWLEDGE_API_KEY` 环境变量，显式空白拒绝启动，access logging 关闭。原生 `/v1/context` 返回 `ContextPacket`；本机 `/v1/chat/completions` 固定模型 `knowledge-context`、一条 user 消息，assistant content 是 packet JSON，**不调用模型、不生成答案、不编造 usage**。stream/tools/sampling/Responses API/历史对话不支持。

核心安装的 help/version 不依赖 `[api]`。默认 dev 组为测试和类型检查安装 API、HTTPX 与客户端 SDK；SDK 不进入 wheel 运行时依赖。详见 [API 请求 schema、鉴权、官方 SDK 示例与验收](docs/api.md)。分发验证对 wheel/sdist 分别先跑 core-only，再跑 `[api]` 隔离 ASGI smoke，不监听端口或请求外部 provider。

## 对话导入与人工审核（U19，Unreleased）

```bash
knowledge conversation import examples/conversation-demo.json -d .konwledge/knowledge.db
knowledge candidate list --json -d .konwledge/knowledge.db
knowledge candidate approve <candidate-uuid> --reviewer alice@example.com \
  --reason "已对照来源" -d .konwledge/knowledge.db
knowledge search "深色模式" -d .konwledge/knowledge.db
```

导入先在数据库外校验 10 MiB 上限、UTF-8、重复 key 和严格 schema。系统只从 `user`/`assistant` 的显式 `Fact:`、`事实：`、`Decision:`、`决策：` 单行提取候选，不调用 LLM，也不自动认定内容真实。候选默认是 `pending`，批准后才产生可检索知识；拒绝不会产生知识。审核决定是终态，新版本不会自动撤销旧版本已批准的事实。`--reviewer` 只用于审计归属，不提供身份认证。

`conversation show --json`、导出、候选详情和数据库可能保留原始私密聊天。命令、完整 schema、默认 latest 版本规则和退出码见 [对话导入与人工审核](docs/conversations.md)。U19 不修改 U18 的只读 HTTP API，也不增加运行时依赖。

## 数据库 schema 捕获（U20，Unreleased）

SQLite 捕获使用核心安装，PostgreSQL 需要可选的 psycopg 3 驱动：

```bash
uv sync --locked --dev --extra postgres
uv run knowledge database capture-sqlite source.sqlite \
  --name "Local schema" --json -d .konwledge/knowledge.db

export KNOWLEDGE_CAPTURE_DSN='postgresql+psycopg://capture_role:password@127.0.0.1:5432/app'
uv run knowledge database capture-postgres \
  --dsn-env KNOWLEDGE_CAPTURE_DSN --name "Application schema" \
  --schema public --json -d .konwledge/knowledge.db
```

CLI 不接受直接传入 DSN，只读取 `--dsn-env` 指定的安全环境变量名。捕获先在元数据库之外完成；无效目标或失败连接不会新建 Knowledge Library 数据库。snapshot 只含 catalog 元数据，不含业务行，但注释、默认值、索引表达式和 DDL 片段仍可能敏感。

`knowledge database list/history/show/export/diff` 用于查看不可变版本、导出规范 JSON 和比较 schema。结构不变时重复捕获保持当前版本；结构变化和恢复都会留下历史记录。完整命令、安全边界、最低权限建议及合成 SQLite 示例见 [数据库 schema 捕获](docs/database-schema.md)。`SourceKind.DATABASE` 尚未进入前端 V1 snapshot 合同，相关导出会明确失败，不修改既有 golden 和前端类型。

## 只读 MCP（B5／U22，Unreleased）

B5／U22 **已完成并验证**，原 ID 保留，版本仍为 `0.1.0` prepared。Linux 真实 SDK stdio session、完整回归与 wheel／sdist 隔离安装均通过；提交以 Git 历史为准，本轮不提交或推送，未创建 MR／PR、合并 main、创建 tag、发布 Release／PyPI 或公开部署。

```bash
# 当前仓库安装；extra 的通用写法为 pip install 'konwledge[mcp]'
pip install '.[mcp]'
knowledge mcp serve --database FILE
# 等价 stdio 入口
konwledge-mcp --database FILE
```

`FILE` 由本机操作人员替换为已有 SQLite 文件。可选 `[mcp]` 与开发组均使用 `mcp>=1.30.0,<2`，核心 `pydantic>=2.7,<3` 未收紧；为避免上游兼容问题，选用已测 SDK `1.30.0` baseline，不承诺旧 SDK `1.2`／`1.20` 支持。开发使用 `uv sync --extra mcp`，SDK 不进入 core 运行时依赖。基本 CLI 不需要 SDK，缺 extra 安全提示只写 stderr、退出 `1`，不接触或创建数据库。

默认 MCP 只有 stdio，不提供 HTTP、SSE、公网、SSO 或写工具。五个工具为 `search`、`build_context`、`get_evidence`、`get_lineage`、`compare_documents`，不接收路径、SQL、凭据或 URL，不继承 B4 写权限。每次读取使用独立 SQLite `mode=ro`／`query_only`／事务 rollback，不创建或升级 schema，包括不创建批准表；不回填 FTS、不写 outbox、不构造写服务。

检索固定 lexical／active，历史 `at`、source scope 与分页不承诺时间因果。严格输入和独立输出白名单保留；精确证据按旧版本校验范围及 hash 锚点，不用 latest 替代。MCP context 仅限制字符和块数，无 token 预算，不透传核心 `context_text`、source URL、raw metadata／locator／href；空上下文不表示 LLM 拒答或答案正确。

每个 Tool 已实现四项 `ToolAnnotations` hint、标准 `outputSchema`、`structuredContent` 与 JSON `TextContent`，无旧 SDK fallback。hint 只提示客户端，物理只读连接才提供防护。完整 `CallToolResult` UTF-8 序列化结果含 text 转义及结构化内容，上限 2 MiB；超限返回 `413/mcp_response_too_large`，不截断精确证据。该上限不含 JSON-RPC 外层，不限制输入 bytes 或序列化峰值；非法 Unicode／非有限浮点安全返回固定 `500`。

最终主环境为 SDK `1.30.0`／Pydantic `2.14.1`，Python 全量 **2131 passed、7 skipped（322.01s）**，前端 **430 passed、2 skipped**；ruff、格式、mypy 与两份 schema 检查均通过。新版 [full summary](.konwledge/workbench/be248fe7-e37c-4b6a-a0cf-d697a927bd8a/summary.json) 各组件通过；MCP 的 72 项底层发行检查单独确认通过，不计入 B-R2 既有 82 项投影。隔离 core-only 未装 SDK，extra/default 与 min1.30 均为 SDK `1.30.0`／Pydantic `2.14.3`，未人工 pin Pydantic。

本轮 B5 仅 Linux 实测，macOS 尚未验证，B-R2 平台待办独立保留。完整命令、客户端配置、输入限额、错误语义、发行与停止证据见 [只读 MCP 使用说明](docs/mcp-readonly.md)；上述 2131 等结果保留为 B5 历史证据，不作为 B6 验收。

## 受控 MCP（B6，已完成并验证）

B6 **已完成并验证**，版本仍为 `0.1.0` prepared。默认 MCP 保持 B5 的五个只读工具，主验收确认默认模式对知识、command、outbox 与批准审计均为零写入；显式受控模式才增加五个工具，总计十个。Linux 主验收汇总为 36 成功、17 拒绝、61 响应；3 次正文提交产生 3 个 command 与 3 个 job，评测链路为 `passed → failed → passed`，独立 PTY 批准 3 次。先准备新的 B4 私有 sandbox，再用本次 summary 的实际 `database`、`manifest` 替换 `FILE`、`MANIFEST`；`ROOT` 为对应演示根目录，默认当前目录下的 `.konwledge/mutation-demo`：

```bash
uv run python scripts/prepare_mutation_demo.py
knowledge mcp serve --database FILE --controlled --mutation-manifest MANIFEST --actor demo-editor --demo-root ROOT
```

独立 `konwledge-mcp` 接受相同启动参数。工具不能指定路径或 actor，只能更新 allowlist 当前正文；没有批准签发工具，也没有新增写 HTTP。人工通过 `knowledge mcp approve` 在独立 TTY 审阅 Diff 并签发 grant，apply 无 `confirmed` 字段；提交后评测失败仍为 `committed=true`、`isError=false`，响应不确定只按原幂等键回查。完整批准命令、私有文件与权限边界、限额及拒绝／恢复流程见 [受控 MCP 正文更新](docs/mcp-controlled.md) 和 [B6 最终验收](docs/mcp-controlled.md#b6-最终验收已通过)。Linux PTY／SDK session 与 wheel／sdist 隔离 smoke 已实测通过，macOS／Windows 未测，不使用用户业务库，也不宣称生产写授权。

收尾复核：Python **2439 passed、7 skipped**；Ruff check／format check 通过（238 files），`mypy src tests scripts` 为 210 sources，无错误。前端 430 passed／2 skipped 与显式 Linux E2E 2 passed 保留各自联调范围；wheel／sdist 的受控 MCP lane 各通过 17 项检查，不混入 B-R2 的 82 项旧投影。完整证据和复核命令见 [B6 最终验收](docs/mcp-controlled.md#b6-最终验收已通过)。

## Import CLI

导入等已有 CLI 命令会自动创建 SQLite schema 与父目录；HTTP `serve` 与 `mcp serve` 例外，必须指向已有数据库文件。默认只读 MCP 不初始化 schema／FTS；显式 controlled 也不升级核心或回填 FTS，只在严格 scope 预检通过后新增批准审计表 `mcp_approvals`。
默认数据库为 `.konwledge/knowledge.db`，可通过 `--database`（或 `-d`）指定其他位置。空仓库示例：

```bash
uv run knowledge import examples --database .konwledge/demo.db
uv run knowledge list --database .konwledge/demo.db
uv run knowledge show <unit-id-from-list> --database .konwledge/demo.db
uv run knowledge history <unit-id-from-list> --database .konwledge/demo.db
uv run knowledge asof --all --database .konwledge/demo.db
uv run knowledge search "deployment" --database .konwledge/demo.db
```

`import` accepts one `.md`, `.markdown`, or `.txt` file, or recursively discovers those formats in
a directory. Files are processed in stable relative-path order; unrelated file formats in a
directory are skipped and summarized. Reimporting unchanged content is idempotent, while changed
content creates a new immutable document version whose units are diffed against the previous
version (see [Incremental updates](#incremental-updates)).

The legacy `konwledge` executable remains an alias for compatibility. Local SQLite databases are
runtime data: keep them under `.konwledge/` or use a `*.db`/`*.sqlite` name, and do not commit them.
These paths are covered by `.gitignore`.

## Development checks

Run the Python checks used by GitHub Actions:

```bash
uv sync --locked --dev
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests scripts
uv run pytest --cov=konwledge --cov-report=term-missing
uv run knowledge demo build --force && uv run knowledge demo export --check
uv run pytest tests/test_evaluation_gate_demo.py
uv run python scripts/verify_distribution.py
```

The last command builds and inspects both the wheel and source distribution, installs each into a fresh isolated environment outside the checkout, and smoke-tests the installed root API, both CLI aliases, packaged demo resources, retrieval/context, evaluation, and gate behavior. Ordinary `pytest` runs against the checkout and does not replace that installed-artifact check. These checks require no provider credentials or network service.

`.github/workflows/ci.yml` runs on pull requests and pushes to `main`; a push only to a feature branch does not trigger it. The workflow also runs the fixed-time U16 gate against the committed baseline and policy. CI may upload build artifacts for inspection, but it does not publish a package or approve a baseline change.

The demo site has its own CI job:

```bash
cd web
pnpm install --frozen-lockfile
pnpm verify        # typecheck → mutationtypecheck → Snapshot／management／mutation 类型漂移 → Vitest → build
pnpm verify:preview # 真实回放 fixture／nullable hash／preview 测试 → 独立构建 → 资产检查
```

仓库保留独立站点验证 job 和手动 Pages workflow，均运行 `pnpm verify` 与 `pnpm verify:preview`；后者生成独立 `dist-preview`，不替代普通构建。Pages 默认只准备 artifact，不自动部署，详见 [静态回放预览](docs/replay-preview.md#公开发布须另行确认)。其中 `check:management` 检查前端管理类型漂移，`check:mutations` 检查 mutation 类型漂移；需要更新类型时运行 `pnpm gen:mutations`，提交前用 `pnpm check:mutations` 校验。Python management／mutation schema 仍从仓库根目录单独检查：

```bash
uv run python scripts/export_management_schema.py --check
uv run python scripts/export_mutation_schema.py --check
```

前端 B2／V3、B3／V4、B4 与 B-R2 统一入口已完成并验证；Pages 配置不代表已公开部署，preview／dist 也不含本机 dev proxy。保留 `strict`、`noUnusedLocals` 和 `noUnusedParameters`；开发后执行 `pnpm typecheck` 和 `pnpm verify`。B-R2／B5 历史 `pnpm verify` 已包含 mutationtypecheck、Snapshot／management／mutation 类型漂移、测试和构建，结果为 **430 passed、2 skipped**；该数字不作为静态回放本轮最终结果。B5／U22 最新 Python 全量、显式 Linux live、ruff／格式／mypy 与隔离发行结果见 [最终验证](docs/mcp-readonly.md#最终验证已通过)，两份 management／mutation schema `--check` 输出不变；上文 B-R2 的 1902／5 与 41.21s 保留为历史结果，不作为本轮验收。`WORKBENCH_SDIST_FILES` 含入口脚本 3 项、测试 4 项、文档 1 项，共 8 个必需文件；缺任一项都会拒绝发行验证。Vitest 覆盖静态演示、实时 adapter／路由／请求状态、评测对照、有界轮询与受控变更状态，但不代替浏览器交互或页面渲染检查。

The optional LanceDB adapter has its own CI job. Run it locally with:

```bash
uv sync --dev --extra lancedb
uv run pytest tests/test_indexing.py tests/test_lifecycle.py -k lance
```

可选 PostgreSQL 捕获有独立 CI job，使用临时 dummy 凭据测试 PostgreSQL 16 和 17：

```bash
uv sync --locked --dev --extra postgres
KNOWLEDGE_TEST_POSTGRES_DSN='postgresql+psycopg://konwledge_test:konwledge_test@127.0.0.1:5432/konwledge_test' \
  uv run pytest tests/test_database_schema_postgres.py
```

默认核心与 dev 安装不依赖 psycopg。只有设置 `KNOWLEDGE_TEST_POSTGRES_DSN` 后，PostgreSQL 测试才会执行。

## Repository layout

```text
.
├── .github/workflows/
│   ├── ci.yml
│   └── deploy-demo.yml
├── src/konwledge/
│   ├── api/                # 可选本机上下文 HTTP 传输（U18）
│   ├── domain/
│   │   ├── __init__.py
│   │   ├── conversations.py
│   │   ├── evaluation.py
│   │   └── models.py
│   ├── conversations/       # 对话导入、确定性提取与人工终态审核（U19）
│   ├── database_schema/     # schema-only 收集、规范模型、diff 与发布服务（U20）
│   ├── embedding/
│   │   ├── __init__.py
│   │   ├── providers.py
│   │   └── service.py
│   ├── indexing/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── lance.py
│   │   ├── memory.py
│   │   └── service.py
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── loaders.py
│   │   ├── normalization.py
│   │   ├── pipeline.py
│   │   ├── service.py
│   │   └── splitting.py
│   ├── demo/
│   │   ├── corpus/          # packaged story files (guide v1-v3, on-call FAQ)
│   │   ├── __init__.py
│   │   ├── builder.py
│   │   └── scenario.py
│   ├── mutations/           # B4 受控正文修改 demo API、preview/command 审计与安全边界
│   ├── lifecycle/
│   │   ├── __init__.py
│   │   ├── diff.py
│   │   ├── revisions.py
│   │   ├── service.py
│   │   └── status.py
│   ├── retrieval/
│   │   ├── __init__.py
│   │   ├── fusion.py
│   │   ├── models.py
│   │   └── service.py
│   ├── context/
│   │   ├── __init__.py
│   │   ├── assembly.py
│   │   ├── citations.py
│   │   ├── models.py
│   │   └── service.py
│   ├── evaluation/
│   │   ├── __init__.py
│   │   ├── metrics.py
│   │   ├── models.py
│   │   └── service.py
│   ├── snapshot/
│   │   ├── __init__.py
│   │   ├── export.py
│   │   └── models.py
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── database.py
│   │   ├── evaluation.py
│   │   ├── repository.py
│   │   ├── tables.py
│   │   └── unit_of_work.py
│   ├── __init__.py
│   ├── __main__.py
│   ├── application.py
│   └── cli.py
├── demo/
│   ├── README.md
│   ├── snapshot.json        # generated, committed, checked in CI
│   └── snapshot.schema.json # generated, committed, checked in CI
├── examples/
│   ├── evaluation-demo.json # packaged-demo evaluation gold set
│   ├── getting-started.md
│   └── lifecycle.txt
├── scripts/
│   ├── installed_api_smoke.py # 仓库外 [api] ASGI 验证，无 SDK/监听
│   ├── installed_smoke.py    # smoke checks run from isolated installations
│   └── verify_distribution.py
├── docs/
│   ├── api.md
│   ├── architecture.md
│   ├── controlled-mutations.md
│   └── releasing.md
├── tests/
├── web/                     # V2 静态演示与 B2～B4 本机工作台
│   ├── scripts/gen-types.mjs
│   └── src/
│       ├── lib/             # snapshot views, code-point slicing, formatting (+ Vitest)
│       ├── types/snapshot.gen.ts
│       └── *Page.tsx
├── CHANGELOG.md
├── CONTRIBUTING.md
├── LICENSE
├── README.md
└── pyproject.toml
```

`api/` 已实现可选本机传输；`providers` 等其余模块仅在具有可执行行为时新增。

## Public Python API

`KnowledgeLibrary` is the root application facade and is lazily exported, so importing `konwledge` does not eagerly initialize application services or a database:

```python
from konwledge import KnowledgeLibrary, __version__
from konwledge.storage import create_schema, create_session_factory, create_sqlite_engine

engine = create_sqlite_engine("sqlite+pysqlite:///knowledge.db")
create_schema(engine)
library = KnowledgeLibrary(create_session_factory(engine))

results = library.search("deployment")
packet = library.build_context("deployment", max_units=3)
```

The wheel and source distribution include a PEP 561 `py.typed` marker so installed consumers can use the inline type annotations.

The established typed models and evaluation helpers remain importable from `konwledge.domain` and `konwledge.evaluation`. Subpackages such as `storage`, `ingestion`, `indexing`, `retrieval`, and `context` expose lower-level composition points used by the facade and tests. At alpha, those lower-level boundaries (and even the core APIs as capabilities are added) may change between minor releases; v0.1.0 does not promise complete backward compatibility.

For design and project workflow details, see:

- [Architecture](docs/architecture.md)
- [受控变更工作台](docs/controlled-mutations.md)
- [对话导入与人工审核](docs/conversations.md)
- [Contributing](CONTRIBUTING.md)
- [Release process](docs/releasing.md)
- [Changelog](CHANGELOG.md)

## Domain models

U02 introduces five immutable [Pydantic v2](https://docs.pydantic.dev/) models under `konwledge.domain`:

- `Source` records where imported knowledge originated;
- `Document` identifies one normalized source document and its checksum;
- `KnowledgeUnit` stores a traceable, independently retrievable text range;
- `Revision` records versioned changes without silently overwriting history;
- `Citation` links model-ready context back to an exact knowledge unit.

The models reject unknown fields, require timezone-aware timestamps, and support JSON roundtrips through `model_dump_json()` and `model_validate_json()`. Document checksums use lowercase SHA-256 hex strings. Knowledge units preserve exact text whitespace, use half-open character ranges, and carry their current heading and full section path.

## SQLite metadata storage

U03 persists the domain graph with SQLAlchemy 2.x and SQLite. `Source`, `Document`, `KnowledgeUnit`, `Revision`, and `Citation` each have a typed repository, while `UnitOfWork` keeps commit and rollback boundaries explicit. Revision history is append-only; lifecycle services will create revision records alongside future domain changes.

SQLite foreign-key enforcement is enabled for every connection. Tests use an isolated in-memory database and cover roundtrips, updates, deletes, constraint failures, commits, and rollbacks. Create an application database with:

```python
from konwledge.storage import create_schema, create_sqlite_engine

engine = create_sqlite_engine("sqlite:///konwledge.db")
create_schema(engine)
```

## Text ingestion

U04 loads one UTF-8 `.md`, `.markdown`, or `.txt` file from a stored file `Source`. The loader removes an optional UTF-8 BOM, converts CRLF and CR line endings to LF, applies Unicode NFC normalization, and calculates a lowercase SHA-256 fingerprint. It preserves all other whitespace so later character offsets remain traceable to the normalized text.

`FileIngestionService` returns both the persisted `Document` metadata and the normalized content needed by the U05 splitter. Importing the same source path and normalized content again returns the existing document instead of inserting a duplicate.

```python
from konwledge.ingestion import FileIngestionService
from konwledge.storage import create_session_factory

session_factory = create_session_factory(engine)
result = FileIngestionService(session_factory).ingest(source_id)
print(result.document.checksum, result.created)
```

## Traceable splitting

U05 turns normalized document content into persisted `KnowledgeUnit` records. Markdown headings define section boundaries and hierarchical paths; headings inside fenced code blocks are ignored. Plain text and heading-free Markdown fall back to paragraph boundaries.

Every unit stores an exact half-open range `[start_char, end_char)`. The invariant `content[start_char:end_char] == unit.text` makes the original location directly recoverable. `TraceableIngestionService` connects U04 ingestion with idempotent unit creation, while an existing document version reuses its stored units.

```python
from konwledge.ingestion import (
    FileIngestionService,
    KnowledgeUnitService,
    TraceableIngestionService,
)

service = TraceableIngestionService(
    FileIngestionService(session_factory),
    KnowledgeUnitService(session_factory),
)
result = service.ingest(source_id)
for unit in result.units:
    assert result.ingestion.content[unit.start_char : unit.end_char] == unit.text
```

## Embedding provider

U07 introduces an offline-friendly embedding layer. The `EmbeddingProvider` protocol defines the minimal surface a backend must expose (`name`, `model`, `dimension`, and `embed`). `HashEmbeddingProvider` ships as a deterministic SHA-256 provider so tests never require network access or API keys.

`EmbeddingService` adds batching, dimension checks, and a provider/model-aware cache key. Caching is opt-in: pass an `InMemoryEmbeddingCache` (or any object with `get`/`set`) to keep repeated calls cheap and idempotent; cache keys compose `(provider_name, model, text)` and remain stable across runs.

```python
from konwledge.embedding import (
    EmbeddingService,
    HashEmbeddingProvider,
    InMemoryEmbeddingCache,
    embedding_cache_key,
)

service = EmbeddingService(
    HashEmbeddingProvider(dimension=32),
    cache=InMemoryEmbeddingCache(),
    batch_size=8,
)
vectors = service.embed(["alpha", "beta", "alpha"])
assert vectors[0] == vectors[2]
assert embedding_cache_key("hash", "sha256-v1", "alpha") == service.cache_key("alpha")
```

## Vector index

U08 turns embeddings into a searchable store. The `VectorIndex` protocol captures `upsert`, `delete`, `get`, `search`, and `rebuild`; the default `InMemoryVectorIndex` ships a dependency-free cosine search with stable id-tiebreak ranking and metadata filters (`{"status": "active"}`, `{"tags": {"in": [...]}}`, `{"status": {"not": [...]}}`). An optional `LanceVectorIndex` adapter targets LanceDB when the local checkout is synchronized with `uv sync --extra lancedb`; the module imports cleanly without the dependency and raises a clear install hint only when the adapter is instantiated. The adapter uses an explicit Arrow schema, so empty rebuilds keep the vector dimension, filtered searches scan every row instead of a fixed oversampling window, and reopening a table with another dimension fails with a clear error.

`IndexingService` wires the embedding service and the vector index together so you can embed and persist `KnowledgeUnit` objects in one call, run top-K searches by raw text, and rebuild the entire index deterministically:

```python
from konwledge.embedding import EmbeddingService, HashEmbeddingProvider, InMemoryEmbeddingCache
from konwledge.indexing import IndexingService, InMemoryVectorIndex

embeddings = EmbeddingService(HashEmbeddingProvider(dimension=32), cache=InMemoryEmbeddingCache())
indexing = IndexingService(
    embedding_service=embeddings,
    vector_index=InMemoryVectorIndex(dimension=32),
)
indexing.index_units(units)  # upsert vectors + traceable payload
hits = indexing.search("python testing patterns", top_k=5, filters={"status": "active"})
indexing.remove_units([units[0].id])  # delete a single unit by id
indexing.rebuild(units)  # atomically replace the whole index
```

Repeating `search` with identical input always returns the same ranking: `InMemoryVectorIndex`
breaks ties on `id` after sorting by descending cosine score, and the hash provider is
deterministic, so vectors never silently drift between runs.

## Incremental updates

U09 answers "what actually changed?" when a file is imported again with new content. Each new
document version is compared with the previous version of the same source at the knowledge-unit
level:

| Change | Rule | Re-embedded? |
| --- | --- | --- |
| `unchanged` | identical text in the same section (its position may shift) | no, vector reused |
| `moved` | identical text in a different section | no, vector reused |
| `modified` | similar text (≥ 0.5 ratio) or a rewrite inside the same named section | yes |
| `added` | no matching unit in the previous version | yes |
| `removed` | previous unit with no match in the new version | vector deleted |

Every unit has a `lineage_id` that stays stable across versions, so "the Usage paragraph" can be
followed through edits even though each immutable document version stores new unit ids. Lineage
changes are written as append-only `Revision` records (`create`, `update`, `delete`) in the same
transaction as the new units; unchanged units add no history. Databases created before U09 gain
the nullable `lineage_id` column automatically, and legacy rows start their own lineage.

```text
$ knowledge import guide.md
updated: guide.md | document=… | units=4 | changes=+1 ~1 >0 =2 -0 | re-embed=2

$ knowledge history <unit-id>
lineage: 9581…
versions: 2
revisions: 2
  rev 1 create (added) unit=9581… at 2026-10-29T03:25:26+00:00
  rev 2 update (modified) unit=ea17… at 2026-10-29T03:25:27+00:00
```

`IndexingService.apply_diff` turns the diff into a partial index rebuild. It embeds only `added`
and `modified` units, copies stored vectors for `unchanged` and `moved` units (falling back to
embedding if a vector is missing), refreshes their payload with the new `document_id`,
`lineage_id`, and `content_hash`, and deletes the previous version's ids:

```python
service = TraceableIngestionService(ingestion, KnowledgeUnitService(session_factory))
result = service.ingest(source_id)
if result.diff is not None:
    report = indexing.apply_diff(result.diff)
    print(result.diff.summary(), report.embedded, report.reused, report.deleted)
```

Tests verify the acceptance criterion directly: with no embedding cache configured, the provider
receives exactly the texts of the changed units. Statuses, as-of queries, and reverts build on this
in U10 (see [Knowledge status and as-of queries](#knowledge-status-and-as-of-queries)).

## Knowledge status and as-of queries

U10 answers "which knowledge was valid at time T?". Each source keeps an append-only
**publication timeline**: every time its head version changes, a `published` revision is recorded
on the source. Because each document version is an immutable snapshot, the status of any unit
version at any moment follows from that timeline plus the lineage's own revision chain:

| Status | Meaning at time T |
| --- | --- |
| `active` | the unit belongs to the source's head version |
| `stale` | head version, but the newest lineage revision at or before T is an explicit stale mark |
| `superseded` | an older version whose lineage lives on in the head (edited, moved, or carried over) |
| `deleted` | an older version whose lineage no longer exists in the head |

Units of a version not yet published at T are invisible. A stale mark lasts until the next revision
of the lineage: re-importing unchanged content keeps it, while an edit, a revert, or
`knowledge refresh` clears it.

```text
$ knowledge asof --at 2026-10-30T15:11:51+08:00 --all
as of: 2026-10-30T15:11:51+08:00
source file /notes/guide.md
  head: document 7f9c… published 2026-10-30T07:11:50+00:00
  active     unit cd9f… section=Guide | # Guide Intro text.
  active     unit 8401… section=Guide / Usage | ## Usage Run the CLI with --database.
  active     unit 1868… section=Guide / FAQ | ## FAQ Ask in issues.
  superseded unit f074… section=Guide | # Guide Intro text.
  deleted    unit 8940… section=Guide / Install | ## Install Run uv sync.
  superseded unit 6343… section=Guide / Usage | ## Usage Run the CLI.
3 effective unit(s) across 1 source(s) | active=3 stale=0 superseded=2 deleted=1

$ knowledge stale <unit-id> --reason "uv flags changed"
$ knowledge show <unit-id> --at 2026-10-30T15:00:00+08:00
$ knowledge asof --document <document-id>     # the moment that version was published
$ knowledge refresh <unit-id> --reason "reviewed"
```

Other behaviour worth knowing:

- **Reverts are real versions.** Restoring a file to content that was imported before republishes
  the stored version (`reverted:` in the import output), diffs it against the head by lineage, and
  appends `reverted` revisions, so `IndexingService.apply_diff` brings the index back as well. The
  next new version is diffed against the head, not against the most recently created document.
- **The revision log is the source of truth.** `knowledge_units.status` is a cache of the current
  status, rewritten in the same transaction as every publication or mark so filters and vector
  payloads can use it. As-of answers are always derived from the log.
- **Older databases keep working.** Without publications, the timeline is inferred from ingestion
  order (U09 behaviour). The next import of a source materializes that history as `backfilled`
  publications, and `knowledge reconcile` rebuilds the cached statuses in one go.

The Python API mirrors the CLI:

```python
library = KnowledgeLibrary(session_factory)
snapshot = library.snapshot(at=datetime(2026, 10, 30, 7, 12, tzinfo=UTC), include_retired=True)
print(snapshot.counts())  # {'active': 3, 'stale': 0, 'superseded': 2, 'deleted': 1}
library.lifecycle.mark_stale(unit_id, reason="uv flags changed")
```

## Freshness policies

U11 builds on U10's explicit `stale`/`refresh` revisions. A `FreshnessPolicy` is configured
per source and stored as an append-only `freshness_policy` source revision, so configuration
survives restarts and historical scans read the policy that existed at that time. No new
SQLite columns or demo schema changes are required.

| Rule | When it flags a current head unit |
| --- | --- |
| `ttl_expired` | Scan time is at or after the last content confirmation plus `ttl_seconds` |
| `source_updated` | A supplied source-update time has arrived and is later than both head publication and the lineage's last review |

The TTL reference is the lineage's latest `added`, `modified`, or `refreshed` revision.
Moving a unit or carrying identical content into a new version does **not** renew its TTL.
A revert renews only lineages whose content actually changes. Older histories without these
revisions fall back to the head publication time. Timestamps must be timezone-aware; the
boundary is inclusive (`checked_at >= expires_at`), and a CLI day is exactly 86,400 seconds.
Deadlines are computed in UTC so daylight-saving transitions do not shorten or lengthen the
TTL. Unsupported intervals/deadlines are rejected with a validation error rather than overflowing.

```bash
uv run knowledge list                         # includes source UUIDs
uv run knowledge freshness configure <source-id> --ttl-days 30
uv run knowledge freshness show <source-id>
uv run knowledge freshness scan               # preview; does not write stale marks
uv run knowledge freshness scan --apply       # append marks atomically
uv run knowledge publishable                  # only active head units
uv run knowledge publishable --include-stale  # opt in to stale knowledge
uv run knowledge refresh <unit-id> --reason "reviewed against source"
uv run knowledge freshness configure <source-id> --disable
```

A configuration command replaces the whole policy. To keep both rules, supply both
`--ttl-days` and `--source-updated-at`, for example:

```bash
uv run knowledge freshness configure <source-id> --ttl-days 30 \
  --source-updated-at 2026-11-06T12:00:00+08:00
uv run knowledge freshness scan --source <source-id> \
  --at 2026-11-06T13:00:00+08:00                 # historical preview only
```

Source-update times are **known inputs**, not a filesystem watcher, HTTP poller, or automatic
external-source synchronization. Future update times do not flag units until that time arrives.
An empty/disabled policy skips scanning; it does not clear existing stale marks. Review those
units with `refresh`. Already-stale units are not marked twice, and retired/unpublished versions
are never scanned. Stale marks retain the rule codes, TTL reference/deadline, and applied policy
in their revision payload.

Applying a scan writes all marks and cached statuses in one transaction, at the observed scan
time rather than backdating them to the TTL deadline. This preserves earlier as-of answers.
`--at` is read-only and cannot be combined with `--apply`; a regressing clock is rejected.
No background task runs by itself: schedule the CLI externally if periodic scans are wanted.

```python
from konwledge.domain import FreshnessPolicy

library.freshness.configure(source_id, FreshnessPolicy(ttl_seconds=30 * 86400))
preview = library.freshness.scan()  # dry_run=True by default
expired = [item for item in preview.decisions if item.expired]
applied = library.freshness.scan(dry_run=False)
ready = library.publishable_units()  # active only
historical = library.publishable_units(at=aware_datetime)
```

`KnowledgeSnapshot.effective_units` still includes active **and stale** head units for U10
compatibility. `publishable_units` is the new active-only boundary for future retrieval/context
assembly. U11 does not automatically filter the lower-level `VectorIndex` or implement the U13
retrieval pipeline. The controlled-clock tests cover deadlines, review/updates/reverts, policy
history, dry-run/apply, batch rollback, CLI validation, and historical publication filtering.

## Conflict detection

U12 detects **candidates**, not which source is correct. Its first deterministic rule,
`port_mismatch`, compares different sources asserting different scalar ports for the same
named `*-service`. It scans only the published head's active and stale units; superseded,
deleted, and unpublished units do not participate. Stale evidence stays visible because an
outdated FAQ may be the contradictory source that needs review.

The service name must be unambiguous in the unit, its section path, or the document (in that
order). Recognized forms include `order-service listens on port 8080`, the Chinese listening
form used in the demo, and `PORT=8080`. Negations, examples, alternatives, ranges, missing
service names, and invalid port numbers are skipped rather than guessed. These conservative
rules can miss natural-language conflicts; U12 does not provide general semantic detection.

```bash
uv run knowledge conflicts scan               # preview; no conflict records are written
uv run knowledge conflicts scan --apply       # persist new candidates atomically
uv run knowledge conflicts list --status pending
uv run knowledge conflicts show <conflict-id>  # JSON with both exact evidence quotes
uv run knowledge conflicts review <conflict-id> --status confirmed \
  --reason "Verified that the current sources disagree" --reviewer "reviewer@example.com"
uv run knowledge conflicts history <conflict-id>
uv run knowledge conflicts scan --at 2026-10-20T12:00:00+08:00  # historical preview only
```

Each record freezes both sources, documents, units, lineages, quotes, character offsets,
section paths, and observed unit statuses. A key based on the rule, subject, predicate,
lineages, and values deduplicates repeated scans and unchanged assertions across versions.
Changing a value creates a new key. Existing records and their original evidence are never
automatically deleted, overwritten, reopened, or resolved when content changes.

| Status | Meaning |
| --- | --- |
| `pending` | Awaiting review, or explicitly reopened |
| `confirmed` | A reviewer confirmed that the sources disagree |
| `dismissed` | A reviewer rejected this candidate |
| `resolved` | A reviewer recorded that the conflict was handled |

Any explicit status change requires a non-empty reason and appends a conflict revision;
repeating the current status is rejected. Review time cannot precede detection or earlier
reviews. Review does not choose a winning source, modify knowledge-unit statuses, or filter
retrieval results. The caller is responsible for recording reviewer identity accurately.

`scan --at` evaluates both publication state and conflict-review state at that time, without
exposing future review fields. It cannot be combined with `--apply`. The scan summary exposes
stable `candidates=`, `created=`, and `existing=` counts; persisted entries also show their UUID
and status. `list`, `show`, and `history` display the current record and complete audit chain.

```python
preview = library.conflicts.scan()  # dry_run=True by default
applied = library.conflicts.scan(dry_run=False)
created = applied.created
existing = applied.existing
historical = library.conflicts.scan(at=aware_datetime)
```

The CLI's existing schema initialization adds the new `conflicts` table to older libraries;
no existing columns or demo snapshot schema change. To try the demo conflict:

```bash
uv run knowledge demo build
uv run knowledge conflicts scan -d .konwledge/demo/knowledge.db
```

This finds exactly the current guide's active `8080` assertion versus the FAQ's stale `8000`
assertion, with both original quotes and offsets. Old guide versions are not treated as
current contradictory evidence. The static frontend and demo snapshot remain unchanged.

## Hybrid retrieval

U13 adds `library.search(...)` and `library.retrieval` with three explicit modes:

| Mode | Candidate routes | Configuration |
| --- | --- | --- |
| `lexical` (default) | SQLite FTS5, ordered by BM25 | No model or vector index required |
| `vector` | Exact cosine over eligible stored vectors | An injected `IndexingService` |
| `hybrid` | Both routes, merged with reciprocal rank fusion | An injected `IndexingService` |

The default query scope is **active published head units only**. `--include-stale` opts into
stale head units, and `--source` restricts the source UUID. Eligibility is resolved from the
publication/revision log at one timezone-aware time, before either route's candidate limit.
Cached vector status or text never controls eligibility or result evidence. Superseded,
deleted, and unpublished versions are excluded; `--at` selects the head that existed then.
The hit's top-level `status` is authoritative for the requested time; its nested `unit.status`
is the persisted current cache and may differ in a historical answer.

```bash
uv run knowledge search "order-service"                    # full-text, active only
uv run knowledge search "服务端口" --include-stale
uv run knowledge search "监听" --at 2026-10-10T12:00:00+08:00
uv run knowledge search "deployment" --top-k 3 --candidate-limit 20 --json
uv run knowledge search "port" --source <source-id>
uv run knowledge search "order-service" --mode hybrid --demo-vectors
```

The standalone CLI has no production embedding provider configured. `--demo-vectors` builds
an **ephemeral hash-vector index** of stored versions, does not write it to disk, and warns on
stderr that hash embeddings test the retrieval pipeline rather than semantic quality.
Without that flag or an injected SDK index, `vector` and `hybrid` fail explicitly rather than
silently switching to full-text. Normal search is read-only: it does not embed the corpus,
write revisions, change statuses, repair vectors, or modify the original index. Opening the
CLI still performs the existing additive schema initialization.

RRF scores are `sum(1 / (rrf_k + route_rank))`, with 1-based ranks and `rrf_k=60` by default.
Each unit counts at most once per route; ties are broken by UUID. Raw BM25 and cosine scores
are diagnostic fields, not quantities added together or confidence probabilities. Single-route
search uses the same rank-derived score. `candidate_limit` defaults to `max(50, top_k)`, applies
to each route, and must be at least `top_k`.

FTS5 indexes every stored unit version. Insert/text-update/delete triggers synchronize it in
the same SQLite transaction; existing libraries are backfilled on initialization. CJK text is
split into single-character tokens, with contiguous CJK query runs compiled as phrases. Other
terms are quoted and combined with AND, so user input is literal text, not FTS operators or
SQL. This supports short Chinese substrings without an extra dependency, but does not provide
Chinese linguistic segmentation, stemming, synonym expansion, or general semantic matching.
Writes through raw SQLite connections must register `knowledge_fts_text`; use the supplied
`create_sqlite_engine` for normal writes. A SQLite build without FTS5 fails with a clear error.

For a small local library, vector retrieval fetches eligible records and performs an exact
cosine scan in a temporary in-memory index. This avoids retired/stale vectors crowding out
valid candidates, but is O(N) over eligible units, not a large-scale ANN solution. U09 still
removes old-version vectors on incremental updates. Missing vectors or conflicting stored
content hashes are exposed in `missing_vector_ids` and `result.degraded`; hybrid can still
return historical FTS evidence, while the CLI warns that vector recall is incomplete. Provider
or backend failures are not silently treated as missing coverage. Callers must use the same
embedding provider/model for stored vectors and queries.

```python
from konwledge.application import KnowledgeLibrary
from konwledge.retrieval import RetrievalMode

# `indexing` is an IndexingService using your provider and a Memory/Lance VectorIndex.
# Populate it explicitly with index_units/rebuild/apply_diff; import does not auto-index.
library = KnowledgeLibrary(session_factory, indexing_service=indexing)
result = library.search("deployment port", mode=RetrievalMode.HYBRID, top_k=5)
for hit in result.hits:
    print(hit.unit.text, hit.source.uri, hit.unit.start_char, hit.unit.end_char)
    print(hit.lexical_rank, hit.vector_rank, hit.score)
if result.degraded:
    print("Missing usable vectors:", result.missing_vector_ids)
```

Results preserve original units, source/document/lineage IDs, section paths and character
ranges, along with resolved status, route ranks and raw scores. `--json` emits the complete
result on stdout; diagnostics stay on stderr. U13 does not generate answers, create citations,
assemble model context, resolve conflicts, or apply evaluation gates; those remain later slices.
The static frontend and V1 snapshot contract are unchanged.

## Context assembly and citations

U14 turns one retrieval snapshot into a `ContextPacket`: ranked whole-unit evidence,
exact citations, explicit skip reasons, and bounded `context_text`. It does not generate
an answer or call an LLM.

```bash
uv run knowledge context "deployment" --max-chars 8000 --max-units 3
uv run knowledge context "deployment" --top-k 10 --candidate-limit 20 --json
uv run knowledge context "监听" --at 2026-10-10T12:00:00+08:00 \
  -d .konwledge/demo/knowledge.db --json
uv run knowledge context "order-service" --mode hybrid --demo-vectors --include-stale
```

The CLI accepts the same retrieval options as `search`. Vector/hybrid modes still require
an injected SDK index or the explicit offline `--demo-vectors` flag. The latter only tests
pipeline wiring, not semantic quality. Diagnostics remain on stderr; `--json` writes exactly
one full packet to stdout. Human output includes a summary, the rendered context, and skips.

Selection preserves retrieval order and applies the following rules:

- Include only `active` evidence, or `stale` when explicitly requested. Historical packets
  use the hit's status at `evaluated_at`, not today's nested unit-status cache.
- Never repeat a unit or lineage. Reject overlapping spans inside one document version;
  adjacent spans and evidence from different documents are allowed.
- Keep each accepted unit's complete original text. When a record does not fit, skip the
  whole unit and consider the next hit; do not truncate quotes or synthesize summaries.
- Assign continuous labels `[1]`, `[2]`, etc. Return skipped unit IDs with `status`,
  `duplicate`, `overlap`, `budget`, or `max_units` reasons.

`max_chars` remains a character limit. The Unreleased `max_tokens` option adds an exact,
optional tokenizer budget alongside it; see [token budget and acceptance](docs/acceptance.md).

`max_chars` defaults to **8,000 Python Unicode code points**, not bytes or model tokens.
It measures `len(context_text)`, including the fixed preamble, labels, metadata, JSON escapes,
and record newlines. It excludes the query, CLI summary, outer packet JSON, and any caller
system prompt. `max_chars=0` returns empty context and budget skips; `max_units` must be
positive and defaults to 10. `top_k` caps retrieved hits **before** assembly: increase it if
more alternatives should be available after budget skips. Selection is greedy, not an
optimal packing algorithm. An empty packet is a valid result, never a reason to fabricate
an answer.

Each block carries a `Citation` with source/document/unit IDs, the source locator, exact
`[start_char, end_char)` offsets, and `quote == unit.text`. Offsets refer to the **normalized
imported document version**, not raw-file byte offsets. Original whitespace and Unicode are
preserved. Citation IDs are deterministic UUID5 values derived from source, document, unit,
range, and quote hash: rerunning retrieval or changing ranks does not change the ID for the
same evidence. A new document/unit version gets its own citation. Retrieval scores are
selection diagnostics, not citation confidence; `confidence` stays `None`.

Rendered context is a fixed trust-boundary notice followed by one compact JSON record per
block. Source quotes are escaped JSON strings, so embedded newlines or fake markup do not
create additional records. This identifies source text as untrusted evidence; it is **not**
a guarantee that a downstream model will resist prompt injection. Callers still need their
own system instructions and tool authorization boundaries.

```python
from konwledge.context import assemble_context, verify_citation

packet = library.build_context("deployment", top_k=10, max_chars=8000, max_units=3)
print(packet.context_text, packet.used_chars)
for label, citation in packet.citation_map.items():
    print(label, citation.locator, citation.start_char, citation.end_char)

# Reuse an existing retrieval result without another search or clock read.
result = library.search("deployment")
packet = assemble_context(result, max_chars=8000, max_units=3)
assert packet == library.context.assemble(result, max_chars=8000, max_units=3)
for block in packet.blocks:
    hit = next(hit for hit in result.hits if hit.unit.id == block.citation.knowledge_unit_id)
    verify_citation(block.citation, hit)
```

`ContextPacket` validates continuous labels, allowed statuses, unique units/lineages,
non-overlapping spans, exact offset lengths, rendered text, and both limits on JSON roundtrip.
`packet.citations`, `packet.citation_map`, and `packet.degraded` are SDK properties, not
serialized fields; JSON contains `blocks[].citation`, `skipped`, and `missing_vector_ids`.
Missing-vector diagnostics propagate unchanged even if all evidence is skipped.

Assembly is read-only: it does not persist citations, add revisions, change statuses,
repair vectors, or read live source files. CLI opening still performs the existing additive
schema initialization, and explicit demo mode builds temporary vectors. The generic
`CitationRepository` remains available for callers who explicitly choose persistence, but
U14 never writes to it. No evaluation gates, frontend changes, or demo snapshot/schema
changes are included in this increment.

## Retrieval evaluation

U15 stores evaluation sets as immutable, contiguous versions and runs retrieval against that pinned
gold version, with a shared default evaluation time, without persisting reports. Build the packaged
demo first, then import and run its gold set:

```bash
uv run knowledge demo build
uv run knowledge evaluation import examples/evaluation-demo.json \
  -d .konwledge/demo/knowledge.db
uv run knowledge evaluation list -d .konwledge/demo/knowledge.db --json
uv run knowledge evaluation show 52522ebd-b1dc-4ace-824c-f8054c8547af --version 1 \
  -d .konwledge/demo/knowledge.db
uv run knowledge evaluation export 52522ebd-b1dc-4ace-824c-f8054c8547af --version 1 \
  --output exported-evaluation.json -d .konwledge/demo/knowledge.db
uv run knowledge evaluation run 52522ebd-b1dc-4ace-824c-f8054c8547af --version 1 \
  --top-k 5 -d .konwledge/demo/knowledge.db --json
```

The JSON file is the complete gold snapshot: its set UUID identifies a logical dataset, `version`
identifies immutable gold at that point, and stable item IDs identify cases across versions. Each
case carries its own optional source, historical `at`, and `include_stale` scope; the runner does
not replace those fields with blanket CLI filters. Imports reject unknown gold lineages/sources.
Historical and stale cases are therefore compared only within the scope encoded by the author,
which keeps lifecycle comparisons fair. Re-importing identical content is idempotent; changing an
existing version is rejected. `list` returns only latest versions, while `history`, `show`, and
`export` expose exact versions.

Reports are read-only and contain the dataset/hash, full retrieval results, per-case scores, and
macro aggregates. Recall, MRR, and nDCG use binary lineage matches; duplicate ranked slots do not
inflate credit. Precision@k always divides by `k`. Answerable aggregates exclude no-answer cases,
and no-answer accuracy excludes answerable cases, so unavailable aggregates are `null` in JSON
and `n/a` in human output. A no-answer success means retrieval returned no hits; it does not mean an
LLM generated a refusal. Lineage matching measures whether the intended knowledge was retrieved;
it does not prove that an edited fact is correct or that a generated answer is faithful. Gold labels
still need human review. Reproducible comparisons require the same dataset version, query scopes,
retrieval settings, corpus versions, and embedding provider/model/index; U15 does not freeze or
version the entire corpus or vector backend.

The CLI has no production vector provider. Vector/hybrid evaluation requires an SDK-configured
`IndexingService` or explicit `--demo-vectors`, which creates one temporary hash index over all
stored versions for the run and warns that it is not a semantic-quality measurement. Missing
vectors remain visible per case and are never repaired automatically. U15 reports are the complete,
validated candidate input consumed by U16's file-only comparison and gate commands.

```python
from konwledge.evaluation import EvaluationSet

created = library.evaluation.import_set(EvaluationSet.model_validate_json(text))
report = library.evaluation.run(created.dataset.id, version=1, top_k=5)
print(report.metrics.mean_recall, report.dataset_hash, report.degraded)
```

## Evaluation baselines and regression gates

U16 turns an approved, healthy U15 report into a compact portable baseline, compares a new complete
report with it, and optionally applies a fail-closed policy. These commands only read and write JSON
files: they do not open SQLite, initialize a provider, use the network, rerun retrieval, or modify the
source report.

```bash
# Capture a complete candidate report from the U15 runner.
uv run knowledge evaluation run <set-id> --version 1 --top-k 5 --json \
  -d .konwledge/demo/knowledge.db > candidate.json

# Promote a reviewed healthy report explicitly; existing outputs are never replaced implicitly.
uv run knowledge evaluation baseline candidate.json --output approved-baseline.json
uv run knowledge evaluation baseline candidate.json --output approved-baseline.json --overwrite

# Inspect every aggregate and per-case delta, then enforce the strict default or a policy file.
uv run knowledge evaluation compare approved-baseline.json candidate.json
uv run knowledge evaluation gate approved-baseline.json candidate.json --json
uv run knowledge evaluation gate approved-baseline.json candidate.json \
  --policy examples/evaluation-gate.json
```

`baseline` validates the complete report and recomputes every metric before creating any output
parent or file. It refuses degraded reports and existing destinations (including input/output being
the same path) unless `--overwrite` is explicit, then publishes atomically in the destination
directory. A baseline keeps dataset scopes, case ranks and scores, but omits hit quotes, source
locators, document/unit IDs, and absolute corpus paths. Dataset-authored strings such as names and
queries remain. This makes it portable, not a signed proof that retrieval really ran; gold review
and baseline replacement are human decisions and are never passed automatically.

`compare` requires exactly the same dataset ID, version, content hash, retrieval mode, `top_k`,
`candidate_limit`, and `rrf_k`, plus complete cases and recomputed scores. Normal run times may
differ so monitoring can observe corpus changes; fixed case-level `at` anchors remain fixed. Set
`require_same_time` in a policy when all effective times must match. For reproducible CI, run both
sides at a common explicit time such as `--at 2026-11-10T00:00:00Z`.

The default policy covers all six metrics (recall, precision, MRR, nDCG, hit rate, and no-answer
accuracy) at both aggregate and case scopes with zero allowed absolute drop. Thus an average gain
cannot hide one bad case. Rules may set an inclusive `min_value`, `max_abs_drop`, and/or
`max_relative_drop`; all configured numeric checks are conjunctive with an epsilon of `1e-12`.
Relative thresholds are unit fractions (`0.01` means 1%). Relative drop from a zero baseline is zero,
while an absolute floor still applies. A metric unavailable for a cohort is `null`, not zero, and its
check has `passed: null`; a policy producing no applicable numeric checks blocks rather than passing.
Missing vectors/degraded candidates, time-policy violations, and metric regressions also block.

The stable process exit codes are:

| Code | Meaning |
| --- | --- |
| `0` | Valid comparison, or a gate that passed |
| `1` | File I/O or unexpected runtime failure |
| `2` | Malformed, incomplete, tampered, mismatched, or otherwise invalid input/configuration |
| `3` | Inputs were valid, but the gate blocked the candidate |

With `--json`, stdout is exactly one parseable baseline, comparison, or `GateResult`, including on
exit 3; diagnostics and candidate missing-vector IDs stay on stderr. Human gate output labels
aggregate and `case <item-id>` checks and prints clear violations. Comparison itself always exits 0
for a valid degraded or regressed candidate because it applies no threshold.

The committed `examples/evaluation-baseline.json` and `examples/evaluation-gate.json` provide the CI
wiring. CI builds/imports the demo, runs at `2026-11-10T00:00:00Z` with `--top-k 5`, writes the full
candidate report, and gates it against those files. The normal workflow trigger remains pushes to
`main` and pull requests. The hash-vector demo tests plumbing only: neither these retrieval metrics
nor their gates assess source correctness, content quality, generation quality, answer faithfulness,
or production embedding quality.

## Demo snapshot

V2 静态演示继续读取 CLI 导出的 JSON snapshot，V1 提供这条数据管线。B2／B3 本机实时视图另用独立 management schema，B3 评测对照与导览不修改 Snapshot V1 或 demo golden。

```bash
uv run knowledge demo build            # plays the story into .konwledge/demo/
uv run knowledge demo export           # writes demo/snapshot.json and demo/snapshot.schema.json
uv run knowledge demo export --check   # exit 1 if the committed files are out of date
```

The story ("the life of one piece of knowledge") follows a fictional service deployment guide
through three versions while an on-call FAQ keeps quoting the old port:

```text
2026-10-05T10:00:00+08:00 | 导入《服务部署手册》v1 | units=8 | embedded=8 reused=0 deleted=0
2026-10-05T10:30:00+08:00 | 导入《值班 FAQ》 | units=3 | embedded=3 reused=0 deleted=0
2026-10-12T14:00:00+08:00 | 发布《服务部署手册》v2 | changes=+2 ~1 >1 =5 -1 | embedded=3 reused=6 deleted=8
2026-10-15T09:30:00+08:00 | 标记“监控告警”过期 | stale: 监控告警
2026-10-16T11:00:00+08:00 | 标记“健康检查”过期 | stale: 健康检查
2026-10-17T15:00:00+08:00 | 确认“健康检查”仍然有效 | refreshed: 健康检查
2026-10-19T16:00:00+08:00 | 发布《服务部署手册》v3 | changes=+0 ~2 >0 =7 -0 | embedded=2 reused=7 deleted=9
2026-10-20T11:00:00+08:00 | 标记 FAQ 端口答案过期 | stale: 服务端口是多少？
Demo library built in .../.konwledge/demo (8 steps, 12 vectors in the index).
```

The v1 -> v2 diff contains all five change kinds, and the final state contains all four statuses.
The embedding numbers above come from a real `IndexingService` run during the build and match the
`embedding` block the exporter computes for each diff.

- **Deterministic by construction.** The builder injects a sequential UUID factory and a scripted
  clock into `KnowledgeLibrary` (which now passes both to every layer), and the corpus ships inside
  the package. Two builds in different directories export byte-identical files.
- **Derived, not duplicated.** `export_snapshot` reads only the metadata store: statuses and the
  per-event as-of `timepoints` come from `LifecycleService`, diffs are recomputed by lineage
  between consecutive head versions, and document text is rebuilt from the units and kept only
  when it reproduces the stored checksum. File URIs are made relative so no machine paths leak.
- **A versioned contract.** `LibrarySnapshot` (Pydantic) is the single contract with the front end;
  `demo/snapshot.schema.json` is generated from it. Breaking changes bump `schema_version`.
  Snapshot V1 keeps its origin-kind enum frozen at `url`, `file`, `repository`, and `manual` even as
  the domain grows. Approved `conversation` sources retain that kind and provenance, so V1 export
  fails explicitly instead of omitting or reclassifying them. The committed goldens and generated
  frontend types were not regenerated for U19.
- **Guarded against drift.** `tests/test_demo.py` compares a fresh export with the committed golden
  files, validates the snapshot against the schema, and CI repeats the check through the CLI.

See [demo/README.md](demo/README.md) for the snapshot layout.

## Demo site

`web/` 保留 Vite + React + TypeScript + Tailwind 静态演示，仍在构建时打包 `demo/snapshot.json`，不自行实现生命周期规则。下面三页使用 Snapshot；实时工作台通过本机 B1 API 展示真实历史、评测对照和手动导览，B4 受控变更页通过默认关闭的 `/v1/mutations` 与 Vite dev proxy 接线。运行与边界见 [本机工作台](docs/live-workbench.md)、[受控变更工作台](docs/controlled-mutations.md) 和 [评测工作台](docs/evaluation-workbench.md)。

| Page | Shows | Backed by |
| --- | --- | --- |
| Overview | Source, version, unit, lineage, and revision counts; vector reuse across incremental updates | `stats`, `sources[].diffs[].embedding` |
| Traceability | Document text and its units side by side; clicking a unit highlights its character range and mirrors `knowledge show` | `sources[].documents[]` |
| Version diff | Unit-level changes between consecutive versions, colored by the five kinds, with re-embedded/reused vectors | `sources[].diffs[]`, `lineages[]` |

```bash
cd web
pnpm install --frozen-lockfile
pnpm dev           # http://localhost:5173
pnpm gen:types     # regenerate src/types/snapshot.gen.ts after a schema change
```

- **Typed by the schema.** `src/types/snapshot.gen.ts` is generated from `demo/snapshot.schema.json`;
  CI fails when it drifts.
- **Ranges match the CLI.** Snapshot offsets are Python code points, so the site slices by code
  point, not UTF-16 unit; Vitest checks that every unit's range reproduces its stored text and that
  the segments tile each document exactly.
- **公开部署仍未执行。** `.github/workflows/deploy-demo.yml` 现为手动 `workflow_dispatch`，`publish` 默认 false，只准备并上传 `replay-preview` artifact；只有显式 true 才允许 Pages publish job。发布前仍须确认默认分支 workflow dispatch、所选 ref 与 Pages 权限，配置不代表网站已可用。详见 [静态回放预览](docs/replay-preview.md)。

## License

Licensed under the [Apache License 2.0](LICENSE).
