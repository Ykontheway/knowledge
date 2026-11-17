# Changelog

All notable changes to Konwledge are documented in this file.

The project is in alpha. Minor releases may refine public and lower-level APIs as capabilities are added; v0.1.0 does not provide a complete backward-compatibility guarantee.

## Unreleased - U14-U20 and B1-B4, B-R1, B-R2

### B-R2 统一入口已完成并验证

- `scripts/workbench.py` 已完成统一入口，稳定命令为 `list`、`demo`、`accept`。`demo` 默认 `--mode readonly`；`--mode controlled` 必须显式 `--actor demo-editor`；`--prepare-only` 只准备不启动。
- `accept` 默认等价于 `--suite readonly`，只编排 seed／management／evaluation；`full` 才加入 mutations；`--with-distribution` 再追加 wheel／sdist smoke。统一入口不接受外部 database／manifest／路径／DSN／key。
- 已验证 summary：readonly 通过 [`.konwledge/workbench/7014a5a8-5dda-4406-b159-592d5620ab0b/summary.json`](.konwledge/workbench/7014a5a8-5dda-4406-b159-592d5620ab0b/summary.json)，最新 full `--with-distribution` 通过 [`.konwledge/workbench/ef8c8448-e402-4951-8324-44579ce0045b/summary.json`](.konwledge/workbench/ef8c8448-e402-4951-8324-44579ce0045b/summary.json)。最新 full summary 中 seed、management、evaluation、mutations、distribution 全部 `status=passed`，所有组件 `exit_code=0`、`checks_failed=0`、`cleanup_verified=true`；distribution `checks_passed=82`，wheel／sdist smoke 均通过。
- 两次 live demo 证据见 [`.konwledge/workbench/9beb853b-909a-4165-86b7-5b59574baac7/summary.json`](.konwledge/workbench/9beb853b-909a-4165-86b7-5b59574baac7/summary.json) 和 [`.konwledge/workbench/17cf59ec-b616-47ee-8f52-5b79ea8824f4/summary.json`](.konwledge/workbench/17cf59ec-b616-47ee-8f52-5b79ea8824f4/summary.json)。两者都以 `Ctrl+C` 收尾，summary 状态是 `stopped`，launcher `exit_code=130`，清理核验为 true；停止语义与评测 `passed`／`failed` 分开记录，不把演示停止写成验收成功。
- readonly demo 的 live 复核只做 HTTP GET：readonly backend 的 B4 session 路径返回 `404`，Vite Node dev proxy 未开启时返回 `503`，不写成“全部 404”；seed 已有 3 个 jobs，demo 本身不新增 preview／command／额外 jobs。controlled demo 验证了演示验收实际 actor `demo-editor`、session role `demo_editor`、server actor 与 allowlist source 匹配，浏览器无裸 key，backend 缺 key 返回 `401`，错误 `Origin` 返回 `403`，Vite Node 同源 GET 正常。
- 较早一次 full 通过 [`.konwledge/workbench/2297462f-6e76-4207-abc0-8d4b8e625ba3/summary.json`](.konwledge/workbench/2297462f-6e76-4207-abc0-8d4b8e625ba3/summary.json) 保留为历史通过记录。首个 full summary [`.konwledge/workbench/559fcce3-a270-4739-80e8-ebe3598bd044/summary.json`](.konwledge/workbench/559fcce3-a270-4739-80e8-ebe3598bd044/summary.json) 保留为历史失败记录：distribution 当时因 `report_invalid` 被正确判成失败。后续修复只把 summary 投影收紧到 known schema，没有放宽原 driver 或业务安全校验。
- 统一入口当前只支持具备 Linux `/proc`、`subreaper`、`pidfd` 子进程追踪与清理核验能力的环境。macOS／Windows 缺少必要能力时会 fail-closed 返回 `cleanup_unknown`，不会误报通过。
- 最终复核：`ruff check .` 通过，`ruff format --check .` 为 218 files，`mypy src tests scripts` 为 192 sources success，management／mutation schema `--check` 保持不变，前端 `pnpm verify` 为 430 passed、2 skipped，Python `pytest -q` 为 **1902 passed、5 skipped**；其中 3 个是既有可选用例，另 2 个是需显式设置 `KNOWLEDGE_WORKBENCH_DEMO_LIVE=1` 的 demo live 用例默认 skip。显式设置该环境变量后，统一入口 E2E 为 2 passed（41.21s）。`WORKBENCH_SDIST_FILES` 已覆盖入口脚本 3 项、测试 4 项、文档 1 项，共 8 个必需文件，缺任一项发行验证都会拒绝通过。

### Refactor：B-R1 已验证

- **B-R1 已完成并验证。** frontend shared 收敛为 `web/src/shared/readBoundedBytes.ts` 与 `web/src/shared/validation.ts`，共用有界字节 reader 和 UUID／hash／Unicode 纯函数；`scripts/schema_utils.py` 共用 JSON dump、`$defs` 冲突检查和 check／write 文件处理。两个领域调用方保留 error、headers、UTF-8、DTO、limits 与 GET／写边界；不合并 Auth／session／StorageBase、B4 hooks、B3 比较算法或真实验收 driver。
- `SCHEMA_SDIST_FILES` 已纳入 `scripts/schema_utils.py` 与 `tests/test_schema_utils.py`，缺文件拒绝检查通过，避免 sdist 遗漏共享依赖。新发行验证 [`.konwledge/b-r1-distribution-verified`](.konwledge/b-r1-distribution-verified) 的 wheel／sdist 隔离 smoke 通过，未发布。
- 最终检查：`ruff check .` passed；`ruff format --check .` 为 210 files；`mypy src tests scripts` 为 185 sources success；management／mutation schema `--check` 通过，两份输出逐字节不变。Python `pytest` 为 **1515 passed、3 skipped**，前端 `pnpm verify` 为 **430 passed、2 skipped**；两个 live test 常规需联调环境、默认 skip。生产 build 的 584.38 kB chunk 提醒非阻断。
- 完整 B4 HTTP／jsdom driver 另跑通过，`children_stopped=true`，scope 为 `c2c9b890-e706-4362-a7fe-e4675edef052`，见 [本轮 B4 验收报告](.konwledge/mutation-demo/c2c9b890-e706-4362-a7fe-e4675edef052/b4-acceptance-report.json)。command／jobs 各 3，任务仍为 `passed → failed → passed`，mean Recall 为 `1 → 2/3 → 1`；GET 恢复不重复写，历史失败／Diff／证据保留。这不表示普通回归的两个 skipped 都已运行。
- [B系列任务与重构路线](docs/integrated-demo-roadmap.md) 保留 B1～B4 职责、ID、依赖和不合并边界。B-R2 已完成并验证；后续仍接 B5／U22 只读 MCP、B6 候选受控命令，二者尚未实现；生产 SSO／RBAC、部署与回滚另设阶段门禁。下列 B4 的 1495／352 等数量及旧条目的“本轮／本次”仍指历史验收，不与 B-R1 最终数量相加，也不作为 B-R2 结果。

### B4 受控变更交互

- 新增默认关闭的 `/v1/mutations` demo API。写入必须显式启用，并使用独立于只读 key 的 bearer mutation key；服务端把 `mutation_actor` 绑定到 mutation command、revision 和发布审计，浏览器不持有 key。
- 新增 `scripts/prepare_mutation_demo.py`，只为本机演示新建独占私有目录、隔离 `knowledge.db`、`mutation-manifest.json` 和 `report.json`。manifest 只接受生成目录内的私有数据库，并把允许写入的 source 范围固定为 demo 库 allowlist。
- 新增 `scripts/live_workbench.py --mutation-manifest --mutation-actor` 显式启用路径。`#changes` 页面支持选择允许的 source、编辑正文、查看完整 Diff、勾选确认后提交；`#changes?command=<id>` 只做命令结果恢复，不自动补发新的写请求。
- preview 绑定 source、当前 document、旧 checksum、新正文 hash、actor、scope、TTL 和 confirmation token。command 用幂等键与请求指纹绑定，在 `BEGIN IMMEDIATE` 后先校验，再把 command、revisions 和 auto-evaluation outbox 一并写入事务。after_commit 阶段即使评测失败，也不回滚已提交知识。
- 明确拒绝浏览器文件路径、数据库路径、SQL 凭据、DSN 和任意写目标；不自动写、不自动重试不确定请求。只读 GET 不能创建 mutation 表，也不能启动评测。结果不确定时，只支持按身份隔离的 GET 恢复命令，或用原 payload 重试同一幂等键。
- 历史完整 B4 driver scope `b239f388-6ef5-401f-879b-e43cf59fb68e` 的隔离验收报告 [`.konwledge/mutation-demo/b239f388-6ef5-401f-879b-e43cf59fb68e/b4-acceptance-report.json`](.konwledge/mutation-demo/b239f388-6ef5-401f-879b-e43cf59fb68e/b4-acceptance-report.json) 全部通过：全部 checks 为 true，frontend_update 与 frontend_recovery 均为 passed，三次变更产生的 command 与 jobs 恰好各 3，任务链路为 `passed → failed → passed`，mean Recall 为 `1 → 0.6666667 → 1`。真实前端验收覆盖 commit 后响应丢失、GET 恢复不重复写、凭据不持久化，以及重启后历史失败／Diff／证据回查；driver 另跑已通过且 `children_stopped=true`。
- B4 历史收尾校验已完成：`ruff check .` 通过，`ruff format --check .` 显示 208 files already formatted，`mypy src tests scripts` 通过 183 sources，management_schema／mutation_schema `--check` 通过，`uv run pytest -q` 为 1495 passed、3 skipped。前端 `pnpm verify` 现已包含 mutationtypecheck 和 check:mutations，typecheck、类型漂移、测试和 build 全通过，结果为 352 passed、2 skipped；两个 skipped 是需要联调服务环境的 live acceptance 默认跳过，不是假失败。发行验证 `scripts/verify_distribution.py --output-dir .konwledge/b4-final-distribution-verified` 已通过 wheel／sdist 隔离安装 smoke，未发布或公开部署；提交记录以 Git 历史为准。

### B3 评测对照与手动导览

- V4 只读开发与验收已完成，新增 `#evaluation` 参考／候选对照与 `#guide` 手动正常／故障／恢复导览，仍使用 B1 同源 GET。严格检查角色 UUID、分页偏移、未知／重复 query 和未知子路由，非法链接不请求数据、不回显原始 hash；选择保存在 URL，跨页保留，刷新新任务不替换选择。
- 聚合 metrics／checks 按 dataset id／version／hash、config fingerprint、完整 passed／质量门禁 failed 报告、8 项默认 checks 集合及 threshold 核对。top_k actual 必须是两侧一致的正整数；degraded、非质量终态、配置不同或 case_count=null 不输出 delta。报告 null 保留为未评估，比例差为百分点，不重算 U16 gate、不接受 baseline，不从指纹逆推检索 mode。
- 导览检查角色状态、时间顺序、相邻知识指纹变化、两组可比性与 trigger revision，再链接 B2 job → revision → Diff → evidence。阶段通过仍须核验 CLI 实操，不把 pass／fail／pass 自动当成真实故障注入或因果证明。没有 case-level query／cases，不造失败问题列表；无答案空检索与引用覆盖不证明 LLM 答案正确，stale_hits 不用当前 unit.status 重算。
- 新增用户主动开启的有界观察，每 10 秒刷新，最多 5 分钟／30 次。手动刷新与观察共用刷新逻辑，刷新前记录列表头部，再重读当前页与按原 ID 选中的参考／候选；列表或选中任务读取中均视为 busy，跳过不延长窗口。导览刷新也重读当前页及已选三阶段任务。隐藏、page key 变化、读取错误或卸载后停止观察，不自动 resume；停止只阻止后续 tick，不承诺取消已发 HTTP，手动刷新仍可用。
- 新增 `scripts/workbench_evaluation_acceptance.py` 隔离验收。2026-11-16 最后一次 run `20261116T042018921245Z-951ad2f7` 通过，真实前端 client／DTO／comparison engine／jsdom UI 经 HTTP dev proxy 联调，mean Recall 为 `1 → 0.666667 → 1`。副本 CLI import 后新增 passed 任务，UI 提示可见，选择与失败记录保留，`children_stopped=true`。临时 secret 仅留服务子进程环境，报告只记 stdout／stderr hash，不改原始 docs 或用户库。
- 前端 `pnpm verify` 为 179 passed、1 skipped（10 files passed、1 skipped），typecheck、Snapshot 类型漂移、management 类型漂移与 build 通过；锁定安装通过。默认跳过的真实 HTTP integration 已由隔离验收单独运行通过，不计入普通回归通过数量。Python 完整回归为 1325 passed、3 skipped，ruff check／format、mypy 169 个源文件及 Snapshot／schema 漂移检查均通过。专项测试不另行相加，Snapshot V1 不变。
- 两页页面渲染检查通过，控制台为空，内容无外溢。首屏结果位置已修正并复查，评测对照先显示 Recall 100% → 66.67%、−33.33 个百分点，导览先显示阶段判定和对照链接。以临时测试密钥执行真实 build，dist 扫描无该密钥或测试后端地址；历史 B4 收尾 build 有 584.87 kB chunk 体积提醒，属非阻断优化项，不是功能失败。本次云端浏览器无法直达 loopback，HTTP／jsdom UI 联调与页面渲染检查各有范围，不代表浏览器整链点击验收。命令与记录见 [评测工作台](docs/evaluation-workbench.md#回归命令与验收记录)。
- B5 MCP、release、PR／main、tag、PyPI 和部署授权不变。B4 没有扩展到候选批准写入、时效写入、LLM 答案评分或生产自治。

以下旧条目中的“本次”“本轮”“下一批”均指各自增量完成时的范围，保留历史说明。B2 的 126／1320／3 是历史验收数量，不作为 B3 全量结果。

### B2 本机只读工作台

- 已授权恢复前端开发，完成 V3 生命周期与变更视图；保留 React／Vite／Tailwind 静态演示，新增真实任务、revision、document、lineage、Diff 和 exact evidence 的 hash 导航，支持任务状态过滤、分页与刷新。
- 增加 loading、空数据、安全错误和读取重试处理，区分完整任务状态，`null` 不等于零或通过；请求使用 Abort 与 sequence 防止旧响应覆盖，不自动回退到 fixture。单元状态是持久化当前缓存，不冒充任务 as-of。
- 新增独立 management schema／TypeScript 类型及两端 `--check` 漂移检查，DTO 用 Ajv 运行时白名单校验，检查 ID／href，并按 Unicode code point 解释字符偏移；Snapshot V1 与 demo golden 保持不变。
- 增加仅 Vite dev 可用的严格 loopback 代理，配置缺失时合法管理请求返回 503，转发前校验 Origin、Host、路由、GET 方法和 queries。key 仅保存在 backend／Vite Node 进程环境，浏览器同源 GET 不带 key；preview／dist 不含 dev proxy，无公开 live 部署。
- 增加 `scripts/live_workbench.py`：使用已有验收库、随机临时 key，先等待 backend health 再启动 web，退出只清理自己的子进程。backend 沿用已有 additive schema／FTS 启动初始化，HTTP 读取只读，不新增 evaluation 或更新 baseline。启动步骤见 [本机只读工作台](docs/live-workbench.md)。
- 前端 126 tests、类型检查／构建与管理契约漂移检查通过；Python 1320 passed、3 skipped，ruff／格式／mypy 通过。云端浏览器走通失败任务到旧版本证据，任务列表、失败详情、Diff 和证据页静态检查无控制台错误。管理验收确认读取前后 19 张表、137 行及内容摘要不变。
- 任务详情的初步 metrics／checks 不代替 B3 可比结果、用例级诊断与导览；按 B2 当时范围，B3 还是下一批、V4 延后，B4 写交互／B5 MCP 也尚未进入实现。v0.1.0 仍为 prepared，未创建 tag、PR、main 合并、PyPI 发布或公开部署。

### B1 工作台只读管理 API

- 增加明确启用的 `/v1/management` GET 契约：分页任务、revision 导航、稳定 lineage、文档版本与 Diff，以及精确历史证据。响应模型 frozen、extra forbid，报告与 payload 使用白名单投影。
- `knowledge serve --enable-management` 和 `create_app(..., enable_management=True)` 必须提供有效密钥；默认不挂载管理端点。保留 U18 请求协议、Snapshot V1、loopback、已有数据库与关闭 access log 的边界。
- 使用独立 SQLite 只读连接，不写库、不触发评测。历史证据校验版本、范围和 hash；缺失、损坏、跨源 Diff、非法请求和写方法均有明确安全结果。
- 增加管理契约、安全接线与真实库 HTTP 导航验收，并扩展 wheel/sdist 新模块检查和安装后管理 smoke。本次未修改前端、发布或部署。

### 后端验收与自动评测

- U14 增加可选 `[tokens]` 与真实 tiktoken 预算，覆盖完整 context rendering；保留默认字符预算、ContextPacket JSON 和冻结 Demo 不变。
- U15 新增独立 30 条公开基准，通过真实 lifecycle 发布、历史版本和过期干扰验证检索；不替换 6 条 Demo 或人工基线。
- U16 增加 TopK 5、Recall ≥ 0.80、MRR ≥ 0.65、引用覆盖 100%、过期命中 0 和无答案准确率门禁；新增 1,000 active 单元、30 次采样的 P95 ≤ 1.5 秒本机性能验收。
- 增加默认关闭的 `auto-evaluation`。启用后在知识变更事务中持久化任务，提交后同步评测；固定数据集版本/hash 与知识指纹，保留安全错误码、租约恢复和重试审计，不自动更新基线或回滚已提交知识。
- CLI 新增 `quality` 与 `auto-evaluation`，知识变更评测未通过时保留普通／JSON stdout，在 stderr 提示并退出 `3`。扩展 wheel/sdist 独立安装 smoke、真实 tokenizer 验收与 CI 证据。
- 本次不改变 v0.1.0 身份、U18 HTTP 请求协议或 Snapshot V1，不包含 MCP、前端、正式发布或部署。

### 真实文档验收与展示路线

- 新增 `scripts/real_knowledge_acceptance.py`，用项目真实使用文档、独立 SQLite 与固定评测集，通过正式 CLI 验证正向变更、质量下降、恢复和重复导入。每次运行保留独立报告，不改原始文档，不接受或更新人工基线。
- 新增 3 个测试，覆盖变更后自动任务、失败不回滚与历史保留、固定期望和安全失败报告；本次不修改生产服务。
- 增加前后端一体化展示路线，按只读管理契约、V3 生命周期与变更视图、V4 评测导览、受控写入和 U22 MCP 安排依赖。本轮仅验收与规划，未开发前端、增加 HTTP 管理接口或执行部署。

### U20

- 增加 SQLite 与 PostgreSQL schema-only 捕获。SQLite 使用 `mode=ro`、catalog authorizer、元数据 PRAGMA 和有界超时；PostgreSQL 使用 psycopg 3、只读 repeatable-read 事务及连接、statement、lock timeout。
- 增加不可变 schema snapshot 历史、规范 JSON/hash、稳定表 lineage、当前结构检索物化和 schema diff。重复捕获未变化结构保持幂等，结构恢复会复用已有 document 并追加捕获版本。
- 增加 `knowledge database capture-sqlite/capture-postgres/list/history/show/export/diff`。PostgreSQL DSN 只从 `--dsn-env` 指定的环境变量读取；CLI 不接受 DSN 值，失败诊断不回显凭据、用户名、原始 SQL 或驱动错误。
- 增加可选 `[postgres]` 依赖，核心安装仍不需要 psycopg。CI 使用 PostgreSQL 16/17 服务和临时测试凭据运行专用集成测试，默认 quality job 不安装该驱动。
- 扩展源码与隔离安装 smoke，覆盖合成 SQLite 增量捕获、业务行不泄漏、只读 list/history、schema diff，以及 API 对当前字段可检索、退役字段不可检索。
- `SourceKind.DATABASE` 不进入 V1 snapshot 合同。V1 导出遇到数据库来源会明确失败，不修改 demo golden、JSON Schema、前端类型或现有前端。

### U19

- 增加不可变对话 schema、10 MiB/UTF-8/重复 key 严格校验、版本历史与规范 JSON 导出；同一 ID/版本内容不可变，重复导入相同内容保持幂等。
- 增加确定性候选提取：只识别 `user`/`assistant` 消息中的显式事实和决策标记；不读取 `system`/`tool`，不调用 LLM，也不自动认定候选真实。
- 增加人工批准/拒绝终态审核与审计归属。批准在一个事务中物化可检索知识，拒绝不写知识；重导入保留决定，新版本不自动撤销旧版本已批准事实。
- 增加 `knowledge conversation` 和顶层 `knowledge candidate` CLI，支持 stdin、latest 默认、状态/对话/版本过滤、稳定 JSON、规范导出和安全覆盖保护。
- 扩展源码与安装后验收，覆盖待审核不可检索、批准可检索、拒绝缺席、重复审核审计、终态冲突和 HTTP 只读查询。U19 不增加运行时依赖，不修改 U18 API 协议，不改前端，也不发布或部署。
- 冻结 snapshot V1 合同中的来源类型，继续保持 `url`、`file`、`repository`、`manual` 四项。批准后的对话仍是 `conversation` 来源；V1 导出遇到这类来源会明确失败，不会省略或改标。demo golden、JSON Schema 与前端生成类型均未重新生成。

### U18

- 增加可选 `[api]`（FastAPI/Uvicorn）本机只读上下文传输：健康检查、模型列表、原生 `ContextPacket` 与严格的 OpenAI chat completion 子集；不执行推理、不返回虚构 usage。
- 增加 `knowledge serve`：仅 loopback，端口 `1..65535`，已有数据库与 SQLite `mode=rw`，密钥只取自 `KNOWLEDGE_API_KEY`（拒绝显式空白），禁用 access log，启动允许 additive schema/FTS 初始化，退出释放 engine。
- 默认 dev 组增加 API 类型/测试依赖、HTTPX 与官方 OpenAI/LangChain SDK；wheel 核心依赖不变，SDK 不作为运行时依赖。
- 增加无需外部模型/网络服务的真实 SDK 验收与 CLI 启动测试；固定查询、`as_of` 和检索控制，验证两个 SDK 的 packet 与原生 JSON 相等，未知选项仍拒绝。
- 分发验证保留 core-only smoke，并为 wheel/sdist 增加仓库外 `[api]` ASGI smoke；检查 API 文件打包、optional marker、无 SDK 运行时依赖、只读请求和 engine 释放。
- 增加 API 文档并更新架构/发布说明；U18 不提升版本、不修改前端、不部署、不发布。CI 触发范围仍为 PR/`main`，不是功能分支 push。

## 0.1.0 - 2026-11-11 (prepared, not published)

This release candidate closes local readiness for the first Knowledge CI workflow. It has not been merged to `main`, tagged, published as a GitHub Release, uploaded to PyPI, or used to verify a public demo deployment.

### Core capabilities delivered through U01-U16

- Local UTF-8 Markdown and text ingestion with normalization, SHA-256 identity, heading-aware splitting, exact character ranges, stable source/document/unit traceability, and idempotent imports.
- SQLite metadata persistence with explicit transactions, foreign keys, additive local upgrades, synchronized FTS5, immutable document versions, append-only revisions, lineage-aware diffs, reverts, and as-of lifecycle state.
- Freshness policies for source-scoped TTL and known source-update times, active-only publication defaults, and atomic dry-run/apply scans.
- Conservative conflict candidates with frozen two-sided evidence, deduplication, human review states, and an append-only audit chain.
- Lexical, vector, and hybrid retrieval with eligibility-first lifecycle filtering, deterministic reciprocal-rank fusion, historical/source scopes, and explicit missing-vector degradation.
- Whole-unit context assembly with exact citations, deterministic citation identity, duplicate/overlap controls, bounded character/unit budgets, and source text rendered as untrusted evidence.
- Immutable, versioned evaluation sets; deterministic retrieval metrics and read-only reports; compact healthy baselines; validated comparisons; and policy-driven fail-closed gates with stable process exit codes.
- Deterministic hash embeddings for offline plumbing tests, an in-memory exact vector index, and an optional LanceDB adapter.
- Reproducible packaged demo data, a versioned JSON snapshot/schema contract, golden drift tests, a V2 read-only static site, and CI for Python, the site build, the optional adapter, demo drift, and the committed regression gate.

### U17 release-readiness additions

- Synchronized v0.1.0 identity across `pyproject.toml`, `konwledge.__version__`, and `uv.lock`, with the package classified as alpha and Python 3.11+ retained.
- Added a lazy package-root `KnowledgeLibrary` export and the packaged PEP 561 `py.typed` marker while retaining the established domain and evaluation import surfaces.
- Added wheel and source-distribution inspection plus isolated installed-package verification for metadata, entry points, packaged resources, CLI aliases, module execution, retrieval/context, evaluation, and gate behavior.
- Added architecture, contribution, release, installation, end-to-end demo, API-boundary, and release-status documentation.
- Documented that CI runs for pull requests and pushes to `main`, not an ordinary push only to a feature branch, and that CI artifacts are not published packages.

### Known limitations

- `HashEmbeddingProvider` and `--demo-vectors` validate deterministic pipeline wiring; they do not provide semantic embeddings or production-quality retrieval scores.
- Evaluation matches expected lineages. It does not assess whether source facts are correct, whether retrieved text fully answers a question, or whether a generated answer is faithful. Konwledge does not automatically call an LLM or generate answers.
- Vector retrieval for a small local library copies eligible vectors into an exact in-memory index and scans them in O(N) time. This is a single-machine design, not a distributed or large-scale ANN service.
- The metadata store uses local SQLite with additive upgrades. It does not provide destructive migration orchestration, high availability, multi-tenant isolation, or a production support SLA.
- Reproducible reports require callers to control corpus versions, evaluation times, retrieval settings, and provider/index identity. Evaluation does not freeze the entire corpus, vector backend, or embedding provider/model.
- Regression gates cannot be bypassed by an average improvement: the committed strict policy checks aggregate and per-case metrics, blocks degraded candidates, and fails closed on invalid or uncovered evidence.
- Raw evaluation reports may include source text, locators, IDs, and local paths. Compact baselines omit hit quotes, source locators, document/unit IDs, and absolute corpus paths, but still contain dataset-authored queries and identifiers.
- v0.1.0 prepared 当时沿用 2026-11-06 的范围决定，前端停在 V2。后续 B2 已获授权恢复并实现 V3，B3 已完成 V4 只读对照与手动导览，当前 feature 分支的 B4 也已实现受控变更 demo 并通过隔离验收；本次云端浏览器无法直达 loopback，B3／B4 的 HTTP 联调、页面渲染与真实前端恢复验收各有范围，不代表浏览器整链点击验收。B5 MCP 未实现，公开 live 部署未执行，workflow 配置不代表站点已上线。
- No v0.1.0 tag, GitHub Release, PyPI package publication, or public-site deployment is part of this prepared candidate.
