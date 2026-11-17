# B系列任务与重构路线

本文件是 B 系列唯一主计划，继续使用现有 `integrated-demo-roadmap.md`，不另建演示或重构路线图。按职责和验收依赖安排后续工作，不编造工期。B1～B4 保留原职责与已完成证据，B5／U22 仍指向 MCP；B-R1、B-R2 是衔接任务，不替换原编号。仓库此前未定义 B6，本计划仅把它列为候选编号。

B1 只读管理 API、B2 V3 live lifecycle、B3 V4 评测对照与导览均已完成；B4 在当前 feature 分支完成受控变更交互并通过隔离验收，V2 静态演示保留。此前 B4 收尾的 Python 1495 passed／3 skipped、前端 352 passed／2 skipped 是历史证据，不计入本轮 B-R1 的最终回归数量。

**B-R1 已完成并验证。** shared 的两个 TS 模块与 `scripts/schema_utils.py` 已接入两个领域调用方，最终回归、完整 B4 HTTP／jsdom 联调及新发行包隔离 smoke 均通过，结果见下文。B5 MCP 未实现，没有公开 live 部署；版本仍为 `0.1.0` prepared，未创建 tag、PR、main 合并、GitHub Release 或 PyPI 发布。

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
| B-R2 | 规划，未实现 | 统一演示／验收入口与可复现报告汇总 | B-R1 已验证；保留全部独立安全 driver | 入口按显式模式编排各 driver，重复运行使用新私有目录且不改 docs／业务库／旧报告。汇总能定位各子报告与 checks，真实更新记录和固定 dataset／config 下 passed → failed/QUALITY_GATE_FAILED → passed 可复核；提交响应丢失及重启后只 GET 恢复，command／job 不重复。任一 driver 失败不得被汇总成通过，子进程退出可核验 |
| B5／U22 | 规划，原编号保留，MCP 未实现 | 稳定查询服务上的只读 search／get／context MCP | 建议 B-R2 后接入；不阻塞 B1～B4 | 真实 MCP 客户端与工作台核对相同版本、证据、引用和字符范围。工具列表无写能力，恶意写调用拒绝且库内容／revision／jobs／baseline 不变；普通响应、错误与日志不泄漏源全文、私密 query、locator、绝对路径或凭据，证据／context 仅按明确授权与预算返回。发布审核另行确认 |
| B6（候选编号） | 规划，未实现，编号待确认 | 逐类扩展受控命令，先独立 preview／validator 审计，再接 MCP 写 | B4 命令安全契约与 B5 只读验收；每类单独审核 | 每条命令独立限定 target／scope／actor／权限与确认条件；越权、过期、冲突、非法输入失败时知识／command／outbox 无写入。同键同请求只提交一次，异请求冲突；提交后评测失败准确返回 `committed=true` 与 failed job／report，禁止伪报回滚。MCP 写沿用同一契约，不能扩大为任意文件／SQL 写权限 |
| 候选阶段（不占 B 编号） | 未完成，未获生产授权 | 生产 SSO／RBAC、部署与回滚策略 | 独立评审、数据使用授权与上线批准 | 用跨身份／跨 scope 用例证明权限拒绝，完成脱敏检查；部署隔离、健康检查与故障恢复可复现，回滚演练区分服务版本回滚和知识修订，eval failed 不自动回滚知识。须形成可核查审批与演练记录 |

推荐衔接为 **B-R1 已验证 → B-R2 统一入口与报告汇总 → B5／U22 只读 MCP → B6 逐类受控命令**。B-R2 优先解决入口和证据分散，后续 MCP 可直接复用已核验的数据链路；它不取代各 driver 的安全断言。后三项仍是规划，生产阶段单独评审，不混入重构完成状态，也不承诺日期。

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

启动命令见 [本机工作台](live-workbench.md)，只读契约见 [管理 API](management-api.md)，写入与恢复见 [受控变更工作台](controlled-mutations.md)。B2／B3 先运行真实文档 seed 验收，再把唯一运行目录交给 `scripts/live_workbench.py`；B4 先用 `scripts/prepare_mutation_demo.py` 新建独占私有目录，再把实际 `knowledge.db`、`mutation-manifest.json` 和 actor 交给启动器。两条链路都不固定机器路径或凭据，B-R2 应保留这一隔离要求。

临时读 key 仅留在 backend 与 Vite Node，启用 B4 时代理再代发独立写 key。浏览器只发同源 GET／POST；preview／dist 不提供 dev proxy，key 与 confirmation token 不进 URL、持久化存储或日志。草稿变化立即使 preview 失效；结果不确定或重启后按 command ID／原幂等键 GET 回查，不自动补发新写请求。契约允许用户显式重试原 payload／同键，但验收入口不得隐式 POST 恢复。

B3 的有界观察默认关闭，主动开启后每 10 秒刷新，最多 5 分钟／30 次，busy 跳过不延长窗口；隐藏、page key 变化、读取错误或卸载会停止，不自动 resume。刷新按原 ID 保留选择，不让新任务替换角色。停止只影响后续 tick，不承诺取消已发 HTTP；B4 的“停止等待”也不表示后端提交取消。

## 生产能力另设阶段门禁

自动评测内部持久化报告当前不保存 query 或源全文，B1 仅提供安全汇总。未来用例级诊断须另设隐私与授权契约，当前历史证据导航不宣称根因判断。外部演示只用可公开的项目文档及独立副本；业务库只用于经授权的私密验收，demo 私有隔离不等于生产 SSO／RBAC。

当前同步评测会增加变更耗时，演示仍是单库、小规模评测，未完成异步生产服务。后台调度、真实 embedding provider、向量／混合自动评测与 Agent 答案质量评测均为独立候选，需各自明确配置、隐私、成本和验收数据。B4 未增加候选批准写入、时效写入、LLM 答案评分或生产自治。

发布、部署和生产回滚均未在重构中完成。版本 prepared 或 workflow 配置不代表发布授权；PR、main 合并、tag、GitHub Release、PyPI 和公开部署仍须另行确认。

<!-- 事实／术语／数字核对一致：210 files／185 sources，Python 1515 passed／3 skipped，前端 430 passed／2 skipped。中文机械扫描：半角标点 0、长破折号 0、编号／量词标题 0、对比句式 0、元话语 0。 -->
