# B系列任务与重构路线

本文件是 B 系列唯一主计划，继续使用现有 `integrated-demo-roadmap.md`，不另建演示或重构路线图。按职责和验收依赖安排后续工作，不编造工期。B1～B4 保留原职责与已完成证据，B5／U22 仍指向 MCP；B-R1、B-R2 是衔接任务，不替换原编号。B6 已完成并验证，沿用原编号；后续命令仍须逐类评审，不扩大为生产写权限。

B1 只读管理 API、B2 V3 live lifecycle、B3 V4 评测对照与导览均已完成；B4 在当前 feature 分支完成受控变更交互并通过隔离验收，V2 静态演示保留。此前 B4 收尾的 Python 1495 passed／3 skipped、前端 352 passed／2 skipped 是历史证据，不计入本轮 B-R1 的最终回归数量。

**B-R1 已完成并验证。** shared 的两个 TS 模块与 `scripts/schema_utils.py` 已接入两个领域调用方，最终回归、完整 B4 HTTP／jsdom 联调及新发行包隔离 smoke 均通过，结果见下文。B5／U22 只读 MCP 已完成并验证，没有公开 live 部署；版本仍为 `0.1.0` prepared，未创建 tag、PR、main 合并、GitHub Release 或 PyPI 发布。

**B-R2 已完成并验证。** `scripts/workbench.py` 已统一 `list`、`demo`、`accept` 入口；`demo` 默认 `readonly`，`controlled` 必须显式 `--actor demo-editor`，`--prepare-only` 只准备不启动；`accept` 默认 `readonly` 只跑 seed／management／evaluation，`full` 才加 mutations，`--with-distribution` 再加 wheel／sdist smoke。受控演示的 CLI actor 示例使用 `demo-editor`，session role 仍是 `demo_editor`。通过 summary 见 [`.konwledge/workbench/7014a5a8-5dda-4406-b159-592d5620ab0b/summary.json`](../.konwledge/workbench/7014a5a8-5dda-4406-b159-592d5620ab0b/summary.json) 和历史 full [`.konwledge/workbench/ef8c8448-e402-4951-8324-44579ce0045b/summary.json`](../.konwledge/workbench/ef8c8448-e402-4951-8324-44579ce0045b/summary.json)，两次 Ctrl+C demo 证据见 [`.konwledge/workbench/9beb853b-909a-4165-86b7-5b59574baac7/summary.json`](../.konwledge/workbench/9beb853b-909a-4165-86b7-5b59574baac7/summary.json) 和 [`.konwledge/workbench/17cf59ec-b616-47ee-8f52-5b79ea8824f4/summary.json`](../.konwledge/workbench/17cf59ec-b616-47ee-8f52-5b79ea8824f4/summary.json)；较早一次 full 通过 [`.konwledge/workbench/2297462f-6e76-4207-abc0-8d4b8e625ba3/summary.json`](../.konwledge/workbench/2297462f-6e76-4207-abc0-8d4b8e625ba3/summary.json) 保留为历史记录。统一入口当前只支持具备 Linux `/proc`、`subreaper`、`pidfd` 清理核验能力的环境；macOS／Windows 缺少必要能力时会 fail-closed 返回 `cleanup_unknown`。B5／U22 只读 MCP 已完成并验证；B6 正文更新也已完成并验证，36 成功、17 拒绝、61 响应与 3 次 command／job 提交已补齐，默认 MCP 零写入，Linux PTY／SDK session 与 wheel／sdist 隔离 smoke 通过；macOS／Windows 未测。MCP 的 stdio 平台语义与 B-R2 清理依赖分开记录，生产权限能力未做。

## 静态回放已整合，发布只做准备

本轮完成回放数据导出、页面整合与独立预览构建的实现，不新增 B 系列或 P 系列编号，不改变 B1～B6 的原职责与历史验收范围。使用工具自建 `.konwledge/replay/<UUID>` 私有 scope 和固定可公开合成语料，经正式 SDK 发布、自动评测 outbox 生成真实的 `passed → failed → passed` 任务；同一 dataset／config、固定 4 条 cases，Recall 为 `1 → 2/3 → 1`，质量失败不回滚已提交知识。仓库内 `web/public/replay.json` 已生成并通过 Python `--check`，不开放任意业务库导出或自动脱敏。

前端显式 replay 路由复用 B1 DTO／`ManagementClient` 和静态 transport，保留分页与 mode，坏 bundle 报错且无 live fallback。独立 `pnpm verify:preview` 检查真实 fixture、nullable hash 与 preview 行为，构建 `dist-preview` 并检查资源白名单、固定敏感模式、相对资产和回放字节相等。preview 默认 `#replay/guide`，隐藏受控变更菜单并阻断手输 changes／live 路由；普通构建的 Snapshot V1／live／B4 契约不变。

Pages workflow 已改为手动 `workflow_dispatch`，`publish` boolean 默认 false；prepare 检查随源码提交的 JSON，运行普通与 preview 验证并上传 `replay-preview` artifact，只有显式 true 才允许 publish job 部署。本轮不运行 Actions 或公开部署，没有生成或验证可用的网站 URL。未来发布仍须确认 Pages Source 为 GitHub Actions、environment 权限与保护，以及默认分支已有可 dispatch 的 workflow、选定 ref 包含本轮实现。仅向 feature 分支推送不能保证新 workflow 名称或 UI 参数可用，此项待维护者确认，不代办 main 变更。

操作、数据契约与发布前置见 [静态回放预览](replay-preview.md)。本轮 Python 全量 2540 passed／7 skipped、前端 529 passed／2 skipped，回放预览专项 91 项、59 项 HTTP 子路径检查与 6 次静态呈现检查通过，真实 wheel／sdist 通过；版本仍为 `0.1.0` prepared，公开发布与生产权限授权另行确认。

## 数据流回到同一评测链路

```text
核心知识／document／revision 变更
  → 同事务自动评测 outbox（须先显式启用 auto-evaluation）
  → 提交后评测 → 持久化 job／report
  → B1 管理只读投影 → B2 生命周期导航 → B3 严格评测对照

B4 隔离 allowlist 正文草稿
  → preview → explicit confirm → command 写提交
  → command／知识 revision／publication 审计／outbox 同事务落库
  → 同一提交后评测／管理只读链路 → 前端结果、Diff 与历史证据
```

核心知识与 revision 是版本事实；自动评测提供持久化汇总，管理 API 只读投影，前端不重新执行评测或接受 baseline。mutation 提交后也回到这条链路，不另造评测系统。评测失败不回滚已提交知识，响应丢失不表示提交取消；command GET 恢复与评测任务重试各守自己的边界。

## B1～B4 各守职责

- **B1 只读管理契约**：明确启用并认证的 GET，提供 jobs、revision、lineage、版本 Diff 与 exact evidence。文件库用独立 `mode=ro` 连接，匿名内存库用独立 backup 快照；`query_only` 仅作用于专用读取连接，不污染原 session／StaticPool 或后续 SDK 写入。GET 不写表、不触发评测或写 hooks；backend 启动仍可能执行已有 schema／FTS 初始化。普通 DTO 不透传 query、源全文、locator、绝对路径或任意 payload，原文选段仅由认证后的 evidence 端点明确返回。
- **B2 live lifecycle**：接入真实任务、知识版本和历史证据，负责过滤、分页、手动刷新、hash 导航与 loading／空数据／安全错误状态。Abort／sequence 防止旧响应覆盖，失败不回退 fixture；当前 unit.status 不冒充任务 as-of。Snapshot V1 与 V2 静态演示独立保留，GET 不新增任务或更新 baseline。
- **B3 严格评测对照与有界刷新**：人工选参考／候选，核验 dataset id／version／hash、config fingerprint、报告完整性和状态，只有完整 passed 或 `failed/QUALITY_GATE_FAILED` 报告进入质量对照。8 项默认 checks 按 `name + threshold` 唯一匹配，追加的 regression_gate 也参与核对；`top_k_contract.actual` 必须是两侧一致的正整数。缺项、degraded、非质量终态、计数错误或 null 不一致均阻断 delta。比例差为百分点，null 保留为未评估；知识指纹与时间差异只作观察，不自动因果归因，不重算 U16 gate。没有 case-level query／cases，不造逐用例失败诊断。
- **B4 isolated allowlist write**：默认关闭，只对 `prepare_mutation_demo.py` 生成的私有隔离库、manifest allowlist source 的当前正文开放写入。独立 mutation key 与只读 key 分离，server 绑定 actor；preview 绑定 source、当前 document、旧 checksum、新 text hash、actor、scope、TTL 和 confirmation token，再由用户 explicit confirm。幂等键与请求指纹绑定，按 scope／actor 隔离，跨身份不可读写原命令；command、revision、publication 审计和 auto-evaluation outbox 同事务写入，post-commit eval 不改变提交事实。preview 可保留预览审计，但不写核心知识或触发评测。GET 不创建 mutation 表或启动评测，浏览器不提交文件路径、SQL 凭据或任意写目标。

8 项默认 checks 的名称、指标适用范围与阻断规则见 [评测工作台](evaluation-workbench.md#满足可比条件才显示-delta)；preview／apply／recovery 契约见 [受控变更工作台](controlled-mutations.md)。

## 已完成证据保留原范围

2026-11-13 的真实项目文档隔离验收使用现有 `docs/auto-evaluation.md` 和 `docs/acceptance.md`，导入 11 个知识单元。首次发布后冻结 4 条用例，包含多证据与无答案问题；正向变更、故障注入和恢复均由正式 CLI 导入触发自动评测。Recall@5 为 `1.0 → 0.666667 → 1.0`，失败记录保留，重复导入不产生新任务。详见 [真实文档变更验收](real-knowledge-acceptance.md)。

该证据覆盖本机 SQLite 与 lexical 检索，使用默认绝对质量门禁，没有自动接受 baseline 或证明 delta 回归。它不证明生产业务效果、模型语义理解、生成答案正确性或完整 Agent 任务成功率。

此前 B4 报告 [b4-acceptance-report.json](../.konwledge/mutation-demo/b239f388-6ef5-401f-879b-e43cf59fb68e/b4-acceptance-report.json) 保留为历史证据。本轮完整 B4 HTTP／jsdom driver 已通过，`children_stopped=true`，scope 为 `c2c9b890-e706-4362-a7fe-e4675edef052`，报告见 [本轮 B4 验收报告](../.konwledge/mutation-demo/c2c9b890-e706-4362-a7fe-e4675edef052/b4-acceptance-report.json)。三次变更产生的 command 与 jobs 各 3，固定 config fingerprint 与 dataset 下任务链路仍为 `passed → failed → passed`，mean Recall 为 `1 → 2/3 → 1`；提交后响应丢失只做 GET 恢复、不重复写，重启后历史失败／Diff／证据仍可回查。

B2 历史浏览器验收只覆盖最短导航，未逐项人工检查全部状态和移动端尺寸。B3 的 jsdom／真实 HTTP 联调与页面渲染检查各有范围；B4 也只是隔离 Vite／API／UI／core 联调，不等于公开环境浏览器整链点击验收。历史数量不相加，也不回填为 B-R1 最终结果。

## 任务按验收衔接

| ID | 状态 | 目标 | 依赖 | 验收口径 |
| --- | --- | --- | --- | --- |
| B1 | 已完成 | 只读管理契约与历史证据投影 | 保留 U18 协议、认证、本机边界 | 真实库 HTTP 导航通过，读取前后全表内容不变；独立 query_only 不影响 SDK 写入，无普通响应全文／敏感字段泄漏。见 [管理 API](management-api.md) |
| B2（V3） | 已完成 | live lifecycle、分页刷新与版本导航 | B1；Snapshot V1 不改 golden | 历史前端 126、Python 1320 passed／3 skipped；最短导航与管理只读摘要通过，不回退 fixture、不写评测或 baseline。见 [本机工作台](live-workbench.md#b2-历史验收记录) |
| B3（V4） | 已完成 | 指纹／8 checks 严格对照、手动导览与有界观察 | B2 与持久化 report；仍只用 B1 GET | 历史前端 179 passed／1 skipped、Python 1325 passed／3 skipped，类型／漂移／lint／格式／mypy／build／锁定安装通过；隔离 HTTP 联调与两页渲染通过。可比条件、null、刷新边界均保留。见 [评测验收](evaluation-workbench.md#回归命令与验收记录) |
| B4 | 已完成实现并通过隔离验收 | allowlist 正文 preview／confirm／apply／GET recovery | B3；私有 manifest、独立 key、server actor、auto-evaluation 显式启用 | 本轮固定 scope 报告通过，command／jobs 各 3，passed → failed → passed；响应丢失只 GET 恢复不重复写，post-commit eval 失败保留知识。未扩展到业务库或生产身份系统 |
| B-R1 | 已完成并验证 | 收敛机械 reader／纯函数／schema 工具，保持领域行为 | B1～B4 原契约和独立测试 | 字节超限、stream／fallback、异常、UUID／hash／Unicode 与 schema 工具测试通过；领域 error／headers／UTF-8／DTO／limits 与 GET／写边界不变。两个 schema 输出逐字节不变，`--check` 不写文件／目录；最终回归、B4 driver、wheel／sdist 隔离 smoke 通过，详见下文；提交记录以 Git 历史为准 |
| B-R2 | 已完成并验证 | 统一演示／验收入口与可复现报告汇总，命令见 [工作台入口](workbench-entry.md) | B-R1 已验证；保留全部独立安全 driver | `demo` 默认 `readonly`，`controlled` 必须显式 `--actor demo-editor`，CLI actor 示例是 `demo-editor`，session role 仍是 `demo_editor`；`accept` 默认 `readonly`，`full` 才加 mutations，`--with-distribution` 再加 wheel／sdist smoke。通过 summary 为 [7014a5a8-5dda-4406-b159-592d5620ab0b](../.konwledge/workbench/7014a5a8-5dda-4406-b159-592d5620ab0b/summary.json) 和历史 full [ef8c8448-e402-4951-8324-44579ce0045b](../.konwledge/workbench/ef8c8448-e402-4951-8324-44579ce0045b/summary.json)；readonly／controlled demo 的停止证据为 [9beb853b-909a-4165-86b7-5b59574baac7](../.konwledge/workbench/9beb853b-909a-4165-86b7-5b59574baac7/summary.json) 和 [17cf59ec-b616-47ee-8f52-5b79ea8824f4](../.konwledge/workbench/17cf59ec-b616-47ee-8f52-5b79ea8824f4/summary.json)，均 `stopped` 且 `cleanup_verified=true`，但不记作评测成功。较早一次 full 通过 [2297462f-6e76-4207-abc0-8d4b8e625ba3](../.konwledge/workbench/2297462f-6e76-4207-abc0-8d4b8e625ba3/summary.json) 与首次失败 [559fcce3-a270-4739-80e8-ebe3598bd044](../.konwledge/workbench/559fcce3-a270-4739-80e8-ebe3598bd044/summary.json) 均保留原样；统一入口当前仅支持具备 Linux `/proc`、`subreaper`、`pidfd` 能力的环境，缺少必要能力时 fail-closed 返回 `cleanup_unknown` |
| B5／U22 | 已完成并验证（Unreleased），原编号保留 | 五个只读 stdio 工具：search／build_context／get_evidence／get_lineage／compare_documents | B-R2 后接入；不阻塞 B1～B4，独立 MCP SDK extra，不继承 B4 写权限 | Linux 真实 SDK `1.30.0` session、完整回归与 wheel／sdist 隔离安装通过，macOS 未实测。独立 SQLite ro／query_only／事务 rollback 保留，不建库／升级 schema／回填 FTS／写 outbox；严格输入、lexical／active、字符／块预算与历史精确证据白名单不变。四项 ToolAnnotations hint、标准 outputSchema／structuredContent／JSON text 与完整 CallToolResult 2 MiB 上限均已实现并验证，无旧 SDK fallback；详见 [只读 MCP](mcp-readonly.md#最终验证已通过) |
| B6 | 已完成并验证（Unreleased），原编号保留 | 首类受控 MCP 命令只更新 sandbox allowlist 当前正文，后续命令逐类评审 | B4 单事务核心与 B5 五工具只读默认；显式 controlled、私有 root／manifest、server actor、独立 TTY 人工批准 | 增加五工具后共十个，无批准签发工具或新增写 HTTP。Linux 主验收汇总为 36 成功、17 拒绝、61 响应；3 次正文提交产生 3 个 command 与 3 个 job，评测链路为 `passed → failed → passed`，独立 PTY 批准 3 次。默认 MCP 零写入，Linux PTY／SDK session、全量回归与 wheel／sdist 隔离 smoke 通过；macOS／Windows 未测，不开放业务库或任意文件／SQL 写入。详见 [受控 MCP](mcp-controlled.md#b6-最终验收已通过) |
| 候选阶段（不占 B 编号） | 未完成，未获生产授权 | 生产 SSO／RBAC、部署与回滚策略 | 独立评审、数据使用授权与上线批准 | 用跨身份／跨 scope 用例证明权限拒绝，完成脱敏检查；部署隔离、健康检查与故障恢复可复现，回滚演练区分服务版本回滚和知识修订，eval failed 不自动回滚知识。须形成可核查审批与演练记录 |

推荐衔接为 **B-R1 已验证 → B-R2 已完成并验证 → B5／U22 只读 MCP → B6 受控命令**。B-R2 已把入口、summary 和证据口径收敛到同一条链路，但不取代各 driver 的安全断言。B5／U22 与 B6 均已完成并验证，依赖链路已闭环。受控模式必须独立绑定范围并取得人工批准，默认五工具只读不变。后续命令仍逐类评审，不能按本轮正文权限扩展到候选批准、retire／remove 或任意导入。若后续需要本地 Mac 统一入口，应单列平台兼容待办，不并入 B-R2 已完成状态；MCP 的 stdio 语义不改变该限制。生产阶段单独评审，不混入实现完成状态，也不承诺日期。

## B5／U22 只开放 stdio 读取

**实现与验收已完成，仍为 Unreleased。** 两个入口为 `knowledge mcp serve --database FILE` 与 `konwledge-mcp --database FILE`，五个工具只读，不继承 B4 写权限。可选 `[mcp]` 与开发组均使用 `mcp>=1.30.0,<2`，核心 `pydantic>=2.7,<3` 未收紧；已测 baseline 为 SDK `1.30.0`，不承诺旧 SDK `1.2`／`1.20` 支持。缺 extra 安全失败，不接触或创建数据库。

严格输入、历史精确证据与字符／块预算保留；SQLite ro／query_only／事务 rollback 提供实际防护。四项 ToolAnnotations hint、标准 outputSchema／structuredContent／JSON text 与完整 `CallToolResult` 2 MiB 上限均已实现并验证，无旧 SDK fallback。完整机制和错误语义见 [只读 MCP 使用说明](mcp-readonly.md)。

Linux 真实 session、最终全量回归及隔离发行均通过，结果与命令见 [最终验证](mcp-readonly.md#最终验证已通过)。新版 [full summary](../.konwledge/workbench/be248fe7-e37c-4b6a-a0cf-d697a927bd8a/summary.json) 各组件均通过；MCP 的 72 项底层检查已单独确认，不把 B-R2 既有 82 项投影当作 MCP 验收。新版 live demo 的停止记录与原始 wheel／sdist 报告见 [发行证据](mcp-readonly.md#隔离发行验证保留原始证据)，旧 B-R2 历史报告保留原样。macOS 未实测，Mac 统一入口继续单列平台待办，不计入 B5 或 B-R2 已完成范围。

B5 五工具只读默认与上述历史结果保持不变。B6 验收结果见下节；feature 分支提交与推送以 Git 历史为准，实现状态不代表发布授权。

## B6 正文更新已完成并验证

Linux 主验收已补齐。命令和完整契约见 [受控 MCP 正文更新](mcp-controlled.md)。范围固定为 B4 prepare 格式的私有 sandbox 当前正文；root／manifest／actor 由操作人员绑定，工具不能指定写目标。带外 TTY 审阅 Diff 后签发私有 grant，apply 只能持批准提交，Agent 布尔确认无效；同 OS 身份仍须权限隔离，生产 SSO／RBAC 未做。

主验收汇总为 36 成功、17 拒绝、61 响应；3 次正文提交产生 3 个 command 与 3 个 job，评测链路为 `passed → failed → passed`，独立 PTY 批准 3 次。默认 MCP 维持 B5 的五个只读工具与零写入结果；Linux PTY／SDK session、全量回归与 wheel／sdist 隔离发行验证均通过，macOS／Windows 未测，B-R2 平台待办继续独立保留。B5 的 2131 等历史结果不改写，也不回填为 B6。

后续受控命令仍按类别单独核验 validator、scope／actor、审计、preview、批准与失败恢复；当前没有 candidate approve、retire／remove、任意文件导入或 SQL 写入。知识提交、人工批准与提交后评测各有状态：评测失败不撤销知识，未知写结果只按固定原键回查；生产写、部署与回滚仍须单独评审。

## B-R1 只合并机械逻辑

| 收敛位置 | 共用内容 | 调用方必须保留 |
| --- | --- | --- |
| `web/src/shared/readBoundedBytes.ts` | `readBoundedBytes` 只读 bytes，检查有限 content-length 和实际累计字节，超限取消 stream、释放 lock，保留 arrayBuffer fallback 与原异常传播 | ManagementClient 与 MutationHttpClient 各自保留 HTTP 状态／领域 error、headers、redirect／content-type、UTF-8 解码和 timeout／Abort。shared 不接凭据、不解 JSON、不重试、不决定 GET／POST |
| `web/src/shared/validation.ts` | UUID／hash 正则与 `validUnicode` 纯函数，保留正则 flags、大小写规则和 surrogate pair 判定 | 两个领域的 assertUuid、Ajv 设置、DTO 白名单、递归检查、链接／query 验证和限额不合并；不能因共用函数扩大接受范围 |
| `scripts/schema_utils.py` | `dump_json` 的 JSON 格式、`insert_definition_strict` 的 `$defs` 冲突检查、`check_or_write` 的文件检查／写出 | 两个 exporter 保留领域模型集合、validation／serialization mode、bundle header／元数据／refs／排序、冲突错误文案、CLI 路径及 stdout／stderr／退出码；两个 schema bundle 仍独立 |

management response 上限仍为 5 MiB，mutation response 为 2 MiB，mutation text／request 为 64／128 KiB。management 保留原 TextDecoder 行为，mutation 保留 `TextDecoder("utf-8", { fatal: true })`、JSON content-type 检查及正无穷声明拦截；HTTP 错误正文不读取。这些差异不搬进 shared，也不趁重构统一安全策略。

schema 输出逐字节不变：UTF-8、`ensure_ascii=False`、两空格缩进、末尾换行以及各 bundle 的定义顺序均保留。定向测试覆盖相同 `$defs` 可复用、冲突不得覆盖、缺失／漂移时 `--check` 不创建或改写文件／目录，以及两个 CLI 的直接脚本／模块调用和原有文案。发行检查的 `SCHEMA_SDIST_FILES` 已包含 `scripts/schema_utils.py` 与 `tests/test_schema_utils.py`，并验证缺文件时拒绝通过，避免 sdist 遗漏共享依赖。

B-R1 最终验证结果，不与历史数量相加：

- `ruff check .` 通过；`ruff format --check .` 为 210 files；`mypy src tests scripts` 为 185 sources success。
- management／mutation exporter 的 `--check` 均通过，两份 schema 输出逐字节不变。
- Python `pytest` 为 **1515 passed、3 skipped**；前端 `pnpm verify` 为 **430 passed、2 skipped**。两个 live test 常规运行需要联调环境，默认 skip；真实 B4 HTTP／jsdom 联调另跑通过，不表示两个 skipped 都已运行。
- 新发行验证目录 [`.konwledge/b-r1-distribution-verified`](../.konwledge/b-r1-distribution-verified) 的 wheel／sdist 隔离 smoke 通过，未发布。生产 build 的 **584.38 kB** chunk 体积提醒是非阻断优化项。

**明确不合并**：Auth／session／StorageBase 的读写安全隔离，B4 preview／apply／recovery hooks 与事务边界，B3 比较算法，真实验收 driver。职责相似不代表行为等价；B-R2 只增加入口编排和报告汇总，不合并真实文档、management、evaluation、mutation driver 的故障注入、读取摘要或恢复断言。

## 本机演示仍用独立副本

统一演示与验收的命令约定见 [工作台入口](workbench-entry.md)。B-R2 已完成并验证：默认 demo 先在全新隔离库生成正常／故障／恢复 seed，再启动管理只读联调；只读指交互 API，准备会写新隔离库。controlled demo 必须显式提供 `--actor demo-editor`，CLI actor 示例只是本机主体，session role 仍是 `demo_editor`，并由原 prepare 在固定 `.konwledge/mutation-demo` 私有根创建本次副本。入口自行传递准备结果，不接受已有 database／manifest／DSN，原脚本仍可独立使用；启动与写入原契约见 [本机启动器](live-workbench.md)、[管理 API](management-api.md) 和 [受控变更](controlled-mutations.md)。

临时读 key 仅留在 backend 与 Vite Node，启用 B4 时代理再代发独立写 key。浏览器只发同源 GET／POST；preview／dist 不提供 dev proxy，key 与 confirmation token 不进 URL、持久化存储或日志。草稿变化立即使 preview 失效；结果不确定或重启后按 command ID／原幂等键 GET 回查，不自动补发新写请求。契约允许用户显式重试原 payload／同键，但验收入口不得隐式 POST 恢复。

B3 的有界观察默认关闭，主动开启后每 10 秒刷新，最多 5 分钟／30 次，busy 跳过不延长窗口；隐藏、page key 变化、读取错误或卸载会停止，不自动 resume。刷新按原 ID 保留选择，不让新任务替换角色。停止只影响后续 tick，不承诺取消已发 HTTP；B4 的“停止等待”也不表示后端提交取消。

## 生产能力另设阶段门禁

自动评测内部持久化报告当前不保存 query 或源全文，B1 仅提供安全汇总。未来用例级诊断须另设隐私与授权契约，当前历史证据导航不宣称根因判断。真实项目文档验收保留可公开项目文档与独立副本的范围；[静态回放预览](replay-preview.md) 只使用工具自建的固定安全合成语料，不导出业务库或自动脱敏业务原文。业务库只用于经授权的私密验收，demo 私有隔离不等于生产 SSO／RBAC。

当前同步评测会增加变更耗时，演示仍是单库、小规模评测，未完成异步生产服务。后台调度、真实 embedding provider、向量／混合自动评测与 Agent 答案质量评测均为独立候选，需各自明确配置、隐私、成本和验收数据。B4 未增加候选批准写入、时效写入、LLM 答案评分或生产自治。

发布、部署和生产回滚均未在重构中完成。版本 prepared 或 workflow 配置不代表发布授权；PR、main 合并、tag、GitHub Release、PyPI 和公开部署仍须另行确认。

## B-R2 验收记录已固定

B-R2 结论已由真实报告固定：readonly 验收通过 [7014a5a8-5dda-4406-b159-592d5620ab0b](../.konwledge/workbench/7014a5a8-5dda-4406-b159-592d5620ab0b/summary.json)，历史 full `--with-distribution` 验收通过 [ef8c8448-e402-4951-8324-44579ce0045b](../.konwledge/workbench/ef8c8448-e402-4951-8324-44579ce0045b/summary.json)，readonly／controlled demo 的停止证据分别是 [9beb853b-909a-4165-86b7-5b59574baac7](../.konwledge/workbench/9beb853b-909a-4165-86b7-5b59574baac7/summary.json) 和 [17cf59ec-b616-47ee-8f52-5b79ea8824f4](../.konwledge/workbench/17cf59ec-b616-47ee-8f52-5b79ea8824f4/summary.json)。历史 full summary 的 seed、management、evaluation、mutations、distribution 全部 `passed`，所有组件 `checks_failed=0`、`cleanup_verified=true`，distribution 的 wheel／sdist smoke 通过，`WORKBENCH_SDIST_FILES` 的 8 个必需文件均已纳入校验。最终复核为 `pytest -q` **1902 passed、5 skipped**、`pnpm verify` **430 passed、2 skipped**，以及显式设置 `KNOWLEDGE_WORKBENCH_DEMO_LIVE=1` 后统一入口 E2E **2 passed（41.21s）**。较早一次 full 通过 [2297462f-6e76-4207-abc0-8d4b8e625ba3](../.konwledge/workbench/2297462f-6e76-4207-abc0-8d4b8e625ba3/summary.json) 和历史失败 [559fcce3-a270-4739-80e8-ebe3598bd044](../.konwledge/workbench/559fcce3-a270-4739-80e8-ebe3598bd044/summary.json) 保留原样，不重写。B-R1 与 B4 历史证据继续保留原范围，不回填为 B-R2 结果。
