# 开发依赖与评审

本页说明当前实现为何按能力依赖组织，以及修改时应检查哪些代码与测试。产品入口见 [README](../README.md)，机制约束见 [当前架构](architecture.md)，SDK／CLI 用法见 [核心参考](core-reference.md)。

版本仍为 **`0.1.0` prepared alpha**，已有实现不等于正式发行或生产部署。包名 `konwledge`、主 CLI `knowledge`、兼容 CLI `konwledge` 与 stdio 入口 `konwledge-mcp` 保持不变。

## 能力按事实依赖推进

先建立版本事实与事务，再做资格检索和证据；固定评测成立后接入变更驱动 CI。安全读投影为工作台与 Agent 提供窄接口，controlled 命令则另加幂等恢复与批准边界。界面最后消费这些契约，不能反过来定义核心业务规则。

下表按依赖顺序阅读，不把历史 U／B 编号作为当前开发阶段。代码与测试路径均相对仓库根目录。

| 能力 | 依赖与修改重点 | 代码入口 | 对应测试 |
| --- | --- | --- | --- |
| 版本事实与事务 | 不可变文档／span 单元、lineage、revision／publication；知识与 FTS 一起提交 | `src/konwledge/domain/`、`src/konwledge/ingestion/service.py`、`src/konwledge/lifecycle/service.py`、`src/konwledge/storage/unit_of_work.py`、`src/konwledge/storage/full_text.py` | `tests/test_domain_models.py`、`tests/test_ingestion.py`、`tests/test_lifecycle.py`、`tests/test_storage.py`、`tests/test_full_text.py` |
| 资格检索与证据 | 从版本日志还原资格，先过滤再限候选；引用绑定 normalized span，整块选取 | `src/konwledge/retrieval/service.py`、`src/konwledge/context/citations.py`、`src/konwledge/context/service.py` | `tests/test_retrieval.py`、`tests/test_citations.py`、`tests/test_context.py`、`tests/test_freshness.py` |
| 固定评测 | 数据集不可变，报告可比，baseline 人工提升，质量 gate fail-closed | `src/konwledge/evaluation/`、`src/konwledge/quality/service.py` | `tests/test_evaluation_models.py`、`tests/test_evaluation_service.py`、`tests/test_evaluation_gates.py`、`tests/test_quality_contract.py` |
| 变更驱动 CI | 同事务 outbox，提交后同步评测；lease／retry 只恢复评测 | `src/konwledge/storage/auto_evaluation.py`、`src/konwledge/auto_evaluation/service.py` | `tests/test_auto_evaluation.py`、`tests/test_auto_evaluation_integration.py`、`tests/test_auto_evaluation_end_to_end.py` |
| 安全 read projection | 专用只读连接、strict DTO 白名单、历史证据；静态回放沿用读模型 | `src/konwledge/api/management_service.py`、`src/konwledge/api/management_models.py`、`src/konwledge/replay/` | `tests/test_management_api.py`、`tests/test_management_schema.py`、`tests/test_replay.py` |
| controlled 命令 | scope／actor、preview、command、幂等原子提交；带外 grant；未知结果原键回查 | `src/konwledge/mutations/service.py`、`src/konwledge/mcp/controlled.py`、`src/konwledge/mcp/approval_cli.py` | `tests/test_mutations_integration.py`、`tests/test_mcp_controlled_service.py`、`tests/test_mcp_approval_cli.py` |
| Agent 与 workbench | 默认 MCP 只读；工作台复用 DTO、导航与报告，受控入口显式启用 | `src/konwledge/mcp/service.py`、`web/src/management/`、`web/src/evaluation/`、`web/src/mutations/`、`scripts/workbench.py` | `tests/test_mcp_protocol.py`、`tests/test_mcp_service.py`、`tests/test_workbench_evaluation_acceptance.py`、`tests/test_mutation_workbench_acceptance.py` |

对话候选与 schema 捕获是其他来源入口，也要接回相同的版本与发布事实。改动分别检查 `src/konwledge/conversations/service.py` 与 `tests/test_conversation_core.py`、`src/konwledge/database_schema/service.py` 与 `tests/test_database_schema_core.py`；schema-only 不得变成业务行采集。

## 运行依赖按能力安装

需要 Python 3.11 或更新版本、启用 FTS5 的 SQLite。用 `uv sync --locked --dev` 准备开发环境；可选能力再按需追加 `--extra`，安装声明以 `pyproject.toml` 为准。

| 安装范围 | 依赖与用途 |
| --- | --- |
| core | `click`、`pydantic`、`sqlalchemy`、`typer`，支持核心模型、SQLite 事务与 CLI |
| `[api]` | FastAPI／Uvicorn，本机 loopback HTTP 与管理投影 |
| `[mcp]` | MCP SDK，本机 stdio；不带来 HTTP 写服务 |
| `[tokens]` | tiktoken，核心上下文可选精确 token 预算，不扩展 MCP 字符／块预算 |
| `[postgres]` | psycopg，只读 PostgreSQL schema 捕获 |
| `[lancedb]` | LanceDB／PyArrow，可选向量索引适配 |
| `dev` | pytest、Ruff、mypy、HTTP／MCP／客户端验收依赖，不等于 core 运行时契约 |

普通 CLI help／version 和核心安装不需要 `[api]`／`[mcp]`。测试用 hash embedding 只验证离线链路，不作为真实语义质量结论。

## 设计贡献用约束和测试说明

本项目的设计工作体现在版本事实、检索资格、精确证据、评测事务和窄接口的组合。下面列出可核对的实现，不宣称独创或行业领先，也不把测试通过等同于生产安全。

| 设计选择 | 检查位置 | 评审问题 |
| --- | --- | --- |
| 日志与当前缓存分开 | `src/konwledge/lifecycle/service.py`、`tests/test_status.py`、`tests/test_freshness.py` | as-of 是否回到日志？移动或原样沿用是否误续 TTL？ |
| 资格过滤前置 | `src/konwledge/retrieval/service.py`、`tests/test_retrieval.py` | 每条路由是否在 `candidate_limit` 前排除无资格版本？RRF 是否只融排名？ |
| 引用可复算 | `src/konwledge/context/citations.py`、`tests/test_citations.py` | UUID5 是否绑定 exact 版本、字符范围与 quote hash？超预算时是否跳过整块？ |
| 提交与质量结论分开 | `src/konwledge/storage/unit_of_work.py`、`tests/test_auto_evaluation_integration.py`、`tests/test_mutations_integration.py` | outbox 是否同事务？评测失败是否错误回滚知识？ |
| 写权限与恢复单独校验 | `src/konwledge/mcp/controlled.py`、`tests/test_mcp_controlled_service.py` | grant 是否同事务消费？未知结果是否只原键回查？ |

新增行为须补对应边界测试，再更新文档或生成 schema；不能只更新页面提示，让服务端仍接受越界输入。

## 界面复用读 DTO

management、评测工作台与 replay 共用读 DTO 和历史资源导航，浏览器不复制 publication、revision、资格判定或质量 gate 规则。页面可校验报告可比条件并显示 delta，但不重算核心门禁、不接受 baseline、不代发评测。

live transport 读取本机 API，replay transport 读取固定 `replay.json`。二者各自失败，不互相 fallback；B4 页面使用独立 mutation DTO，写入确认和 unknown outcome 恢复不能塞进普通 GET reader。

| 可机械共享的实现 | 允许复用的部分 | 不能顺带合并的部分 |
| --- | --- | --- |
| `web/src/shared/validation.ts`，测试为 `web/src/shared/validation.test.ts` | UUID、hash、Unicode 纯校验 | management／mutation DTO 白名单与领域规则 |
| `web/src/shared/readBoundedBytes.ts`，测试为 `web/src/shared/readBoundedBytes.test.ts` | 有界字节读取、超限取消等机械处理 | auth／session、读写恢复状态机与 live／replay transport |
| `scripts/schema_utils.py`，测试为 `tests/test_schema_utils.py` | JSON 输出、`$defs` 冲突检查、check／write 流程 | exporter 的领域模型集合与独立 acceptance driver |

shared 代码不能决定谁能读写、消费 grant 或重试 command。各 driver 保留独立进程、私有目录、环境凭据和清理校验，不因启动步骤相似就合成一条安全边界。

## 检查跟随修改范围

以下是开发验证入口。按改动选择专项，验证结果记录在对应 PR 或验收报告中，不把历史通过数相加。

| 修改范围 | 定向检查 |
| --- | --- |
| Python 代码 | `uv run ruff check .`、`uv run ruff format --check .`、`uv run mypy src tests scripts`；pytest 选择上表对应文件 |
| management／mutation DTO | `uv run python scripts/export_management_schema.py --check`、`uv run python scripts/export_mutation_schema.py --check`；检查对应 schema tests |
| 前端 | 在 `web/` 安装锁定依赖后执行 `pnpm verify`，核验生成类型 drift、运行时 DTO 与页面测试 |
| 静态回放 | `uv run --frozen python scripts/export_replay.py --check --output web/public/replay.json`；在 `web/` 执行 `pnpm check:replay`、`pnpm verify:preview` |
| 包发行候选 | `uv run python scripts/verify_distribution.py`；核验 wheel／sdist 隔离 smoke，不等同已发布 |

PostgreSQL、LanceDB、真实 MCP session、工作台 live 和发行隔离 smoke 都有各自条件。只在准备好的合成环境运行，默认 skip 不改写成通过；报告中的命令、时间、平台与失败历史分别保留。

## 评审先读边界再读实现

跨层 PR 建议按下表顺序读文档，再沿能力依赖表定位代码和测试。

| 阅读顺序 | 需要确认的内容 |
| --- | --- |
| [README](../README.md) | 产品用途、最小上手、当前版本与公开静态预览状态 |
| [architecture](architecture.md) | 版本事实、事务、资格、证据及独立传输边界 |
| [auto-evaluation](auto-evaluation.md) | 配置绑定、outbox、提交后评测、lease／retry 恢复 |
| [evaluation-workbench](evaluation-workbench.md) | 报告可比条件、null／delta 口径、页面不接受 baseline |
| [mcp-controlled](mcp-controlled.md) | 默认只读与显式 controlled、TTY grant、原键恢复及 OS 隔离 |
| [release](releasing.md) | 发行证据、平台范围、合并与发布分别授权 |

PR 目标分支为 `main`。通过 CI 不自动授权 merge、tag、GitHub Release、PyPI 或部署。当前 feature 中的 Pages workflow 仅手动 dispatch；合并会更新 main 的 workflow 定义，评审仍须核对目标分支的实际配置和部署副作用，不能把主分支 CI 当作公开发布批准。

## 已完成范围与生产待办分开

| 范围 | 当前实现 | 生产化仍需处理 |
| --- | --- | --- |
| 版本与检索 | 单机 SQLite、不可变版本、时效与冲突、资格过滤、精确 context、可选向量适配 | 真实 embedding provider 配置、质量与成本验证，生产索引及 provider 治理 |
| 质量 CI | 固定数据集、报告、人工 baseline、fail-closed gate、持久化自动评测任务 | 真实业务评测集与任务质量、用例级诊断；不以引用覆盖代替源事实或下游答案质量 |
| 自动评测执行 | 同事务 outbox、提交后同步运行、lease／retry／recover | 调度、隔离、耗时与吞吐控制；当前没有后台或跨库调度服务 |
| 接口与批准 | loopback、独立 key／Node proxy、物理只读 MCP、私有 scope 受控更新 | 部署授权、SSO／RBAC、OS 身份隔离及完整审计；TTY 不提供人类身份担保 |
| 存储与运维 | 显式事务、只读投影、schema 与 drift 校验 | 备份／恢复演练、并发与锁竞争、迁移、监控、高可用及服务回滚 |
| 平台与界面 | 本机工作台、默认只读 Agent 接口、公开静态 replay | macOS／Windows 等平台实测，live 服务部署；公开预览不连接业务库 |

2026-11-23 已上线 [静态预览](https://ykontheway.github.io/konwledge/)，它使用固定公开合成数据。实现完成、包发行与生产上线分别记录，不用静态网站状态替代后两项。

历史 U／B 编号、阶段计划和验收记录归档在 [integrated-demo-roadmap.md](integrated-demo-roadmap.md)，仅供追溯。当前依赖以本页和架构为准；历史记录不能成为新测试统计或自动开工、合并、发布的依据。

<!-- 文档校对记录
本次仅压缩 development 的校对记录，正文只做结构与表述整理，不改依赖关系、命令、代码路径和评审边界。
关键机制、验证入口和生产边界未变，技术片段和表格保持原意。
已做中文半角标点机械扫描，结果为 0；代码、命令、路径、URL 中的半角语法按规则豁免。
本记录只覆盖文档校对范围，不代表代码验证、发布或部署结论。
-->
