# Konwledge

Konwledge 是本地优先的 **Knowledge CI 知识生命周期与质量门禁基础设施**。它记录可追溯的版本事实，把知识变更接到质量验收，并向应用提供绑定精确版本的检索证据与上下文。

当前核心开发与工作台实现已完成，版本为 0.1.0，处于 Alpha 阶段。`konwledge==0.1.0` 已于 2026-11-23 发布到 [PyPI](https://pypi.org/project/konwledge/0.1.0/)；实现完成、包发布和生产部署仍是三个不同状态。

包名保留 `konwledge`，主 CLI 为 `knowledge`，兼容别名 `konwledge` 和模块入口 `python -m konwledge` 继续可用。项目面向本机、单库工程使用，不是自治答案系统或生产服务。

2026-11-23 已发布 [在线只读预览](https://ykontheway.github.io/konwledge/#replay/guide)。页面只读取静态回放数据，不连接 live backend；导出、构建与发布边界见 [静态回放预览](docs/replay-preview.md)。

## 安装已发布的 0.1.0

需要 Python 3.11 或更新版本，建议在虚拟环境中安装。如果直接使用已发布包，无须先下载源码仓库：

```bash
pip install konwledge==0.1.0
knowledge --version
```

也可以按需安装已发布的可选 extra：

```bash
pip install 'konwledge[api,mcp,tokens]==0.1.0'
```

这些 extra 只会补充本机 HTTP、stdio MCP 和精确 token 预算相关依赖，不会自动部署 GUI、Web 服务或公开站点。

纯 `pip install` 不会把仓库里的 `examples/` 文件自动复制到你当前目录。下面基于 `examples/` 的命令需要先下载源码仓库，或自行准备等价的 `.md`／`.txt` 输入文件。

## 知识变更留下可验收的事实

导入文档后，Konwledge 保留来源、不可变文档版本、知识单元和 append-only revision。更新、移动、删除和重新发布历史版本都有记录，旧内容不会被静默覆盖。

source publication timeline 与 lineage revision chain 是历史事实。`knowledge_units.status` 只是当前查询缓存；as-of 查询从日志重建当时可见的版本，不用今天的状态冒充历史状态。

| 能力 | 当前实现 | 使用边界 |
| --- | --- | --- |
| 导入与版本化 | UTF-8 Markdown／TXT 规范化、精确拆分、幂等导入、单元级 Diff | 本地文件；文档版本和单元版本不可变 |
| 生命周期 | `active`、`stale`、`superseded`、`deleted`，as-of、时效策略、冲突候选 | 冲突由人工审核，不自动选定正确来源 |
| 检索与上下文 | lexical、可选 vector／hybrid、整块证据、exact citations | 不调用 LLM，不生成答案 |
| 评测与门禁 | 不可变评测集、report、baseline、compare、gate、quality acceptance | 基线需人工审核并显式提升 |
| 变更后自动评测 | 显式绑定评测集、持久化 job、history／retry／recover | 默认关闭；首版 lexical、同步执行 |
| 工作台与集成 | 本机 HTTP、管理投影、只读 MCP、受控更新、静态回放 | 读写权限及数据模式分别校验 |

这套记录让版本、检索结果和验收结论可以核对。引用完整性与检索指标不保证源事实正确，也不证明下游生成答案忠实。

## 先判资格，再检索

eligibility-first 检索先确定查询时点，按 publication／revision 日志还原 eligible head units，再进入 lexical、vector 或 hybrid 路由。资格判定发生在各路由的 `candidate_limit` 之前，避免旧版本挤占有效候选。

默认只召回 active published head units。核心 SDK／CLI 可显式使用 `--include-stale`、`--source` 或 `--at`；superseded、deleted 和尚未发布的版本不进入该时点的召回范围。

lexical 使用 SQLite FTS5，hybrid 使用确定性 RRF。vector／hybrid 需要调用方注入 `IndexingService`，或显式使用仅供链路验证的 `--demo-vectors`。缺少 provider／index 时明确失败，不静默回退；缺失向量会暴露 degraded 诊断。

## 证据绑定精确版本

每个知识单元保存规范化原文的半开字符区间，满足：

```text
normalized_content[unit.start_char:unit.end_char] == unit.text
```

引用包含 source／document／unit ID、exact quote、字符范围和校验信息，绑定被检索的具体版本。citation ID 对同一证据保持稳定，不随重跑检索或排名变化而改变。

上下文按排名选择 whole-unit evidence，去重 lineage 并排除同一文档版本的重叠区间。放不进预算时跳过整块，不截断引用或合成摘要；空上下文是合法结果。

核心上下文的 `max_chars` 计算完整 `context_text`，可选 `[tokens]` 支持精确 token 预算。MCP 使用独立的字符／块数预算，不接受 `max_tokens`。两套预算不能混用，详情见 [核心参考](docs/core-reference.md) 和 [只读 MCP](docs/mcp-readonly.md)。

## 从源码 checkout 开始

需要 Python 3.11 或更新版本，以及启用 FTS5 的 SQLite。以下命令在仓库根目录执行，从当前 checkout 安装，不依赖包索引：

```bash
python -m pip install .
knowledge --version
```

版本输出应为：

```text
knowledge 0.1.0
```

以下示例直接使用仓库自带的 `examples/` 文件；只有在你已经下载源码仓库时，这些路径才会存在：

```bash
knowledge import examples/getting-started.md -d .konwledge/knowledge.db
knowledge import examples/lifecycle.txt -d .konwledge/knowledge.db
knowledge list -d .konwledge/knowledge.db
knowledge search "character range" -d .konwledge/knowledge.db
knowledge context "character range" --max-units 1 -d .konwledge/knowledge.db
```

`import` 接受 `.md`、`.markdown`、`.txt` 文件，也可递归导入目录；按稳定相对路径顺序处理，跳过并汇总无关格式。相同内容重导是幂等操作，正文变化创建新版本并与当前 head 做 Diff。

默认库路径就是 `.konwledge/knowledge.db`，`--database` 与 `-d` 等价。已有普通 CLI 会自动创建父目录并执行增量 schema 初始化；HTTP `serve` 和默认只读 MCP 必须指向已准备好的库，不借查询启动修复或升级。

运行时数据库留在 `.konwledge/` 或使用 `*.db`／`*.sqlite`，不要提交业务库、凭据或本机验收产物。后续 SDK／CLI 用法见 [核心参考](docs/core-reference.md)，事务与存储职责见 [架构](docs/architecture.md)。

### 可选依赖按能力安装

核心安装不强依赖 HTTP、MCP、tokenizer、PostgreSQL 或 LanceDB。所有 extra 都是可选项：

| Extra | 从当前 checkout 安装 | 用途 |
| --- | --- | --- |
| `[api]` | `python -m pip install '.[api]'` | loopback HTTP 与显式启用的管理 API |
| `[mcp]` | `python -m pip install '.[mcp]'` | 本机 stdio MCP |
| `[tokens]` | `python -m pip install '.[tokens]'` | 核心上下文精确 token 预算 |
| `[postgres]` | `python -m pip install '.[postgres]'` | PostgreSQL 只读 schema 捕获 |
| `[lancedb]` | `python -m pip install '.[lancedb]'` | 可选 LanceDB 向量索引适配器 |

开发环境可用 `uv sync --locked --dev`，按需追加 `--extra`。开发组中的测试依赖不等于核心运行时依赖；help／version 不需要 `[api]` 或 `[mcp]`。

Python 公共入口为 `from konwledge import KnowledgeLibrary, __version__`，`KnowledgeLibrary` 与 `konwledge.application` 中的 facade 是同一实现。根导入延迟加载，不主动初始化数据库。`konwledge.domain`、`konwledge.evaluation` 和 PEP 561 `py.typed` 保留；alpha 阶段不承诺完整向后兼容。

## 给知识变更绑定质量门禁

先根据库中已导入的 source／lineage 制作业务评测集，再导入同一个知识库。下面的 `your-evaluation.json` 表示实际文件，`DATASET_UUID` 必须替换为导入结果或 `evaluation list` 中的 dataset UUID；`--version 1` 必须对应已导入的不可变版本。

```bash
knowledge evaluation import your-evaluation.json -d .konwledge/knowledge.db
knowledge evaluation list -d .konwledge/knowledge.db --json
knowledge evaluation run DATASET_UUID --version 1 --mode lexical \
  --top-k 5 --candidate-limit 50 --rrf-k 60 \
  -d .konwledge/knowledge.db --json
knowledge auto-evaluation enable --set-id DATASET_UUID --version 1 \
  -d .konwledge/knowledge.db
knowledge auto-evaluation status -d .konwledge/knowledge.db
knowledge auto-evaluation run -d .konwledge/knowledge.db
```

`enable` 固定 dataset ID／version／hash、检索参数与策略，仅保存配置，不认定已有知识合格。升级评测集版本后须显式重新绑定；`run` 用于检查当前知识。

自动评测默认关闭。启用后，文件发布／更新／重新发布、对话候选人工批准、SQLite／PostgreSQL schema 新版本发布，以及 stale／refresh 和时效策略变更会触发任务。原样重导、查询和评测集导入不触发。

写事务同时持久化 revision／publication 与 job outbox，提交成功后同步评测。同一外层事务合并为一个任务，事务回滚不留下任务。结果保留 dataset hash、config fingerprint 和 knowledge fingerprint，但不冻结完整 corpus／provider／backend 快照。

**质量 failed 时 CLI 退出 `3`，不回滚已提交知识，也不替换基线。** stderr 会提示 `knowledge committed; evaluation did not pass`，stdout 保留普通结果或 JSON。不能据此假定导入未发生而盲目重试。

```bash
knowledge auto-evaluation history -d .konwledge/knowledge.db
knowledge auto-evaluation show JOB_UUID -d .konwledge/knowledge.db
knowledge auto-evaluation retry JOB_UUID -d .konwledge/knowledge.db
knowledge auto-evaluation recover -d .konwledge/knowledge.db
knowledge auto-evaluation disable -d .konwledge/knowledge.db
```

`JOB_UUID` 取自任务历史。retry 新建关联任务，不覆盖旧终态；recover 回收过期租约。评测任务恢复与知识写入恢复是不同操作，完整状态和安全报告规则见 [自动评测](docs/auto-evaluation.md)。

### 比较前严格校验可比性

baseline／compare／gate 只处理 JSON 文件，不打开知识库、不调用 provider、不重新检索。baseline 只接受经完整校验的健康 report，默认拒绝覆盖已有输出；提升和替换均须人工显式操作。

比较要求 dataset ID、version、content hash、mode、`top_k`、`candidate_limit`、`rrf_k` 一致，并校验完整用例与重算指标。固定用例的 `at` 保持不变；需要所有时间一致时使用 `require_same_time`，可复现 CI 应选择共同显式时间。

默认回归策略检查全部六类指标的 aggregate 和 case，任何适用检查退化都可阻断；无适用指标、degraded 或违反时间策略时也不会放行。输入有效但 gate 阻断退出 `3`，通过退出 `0`，输入无效退出 `2`，I/O 或运行失败退出 `1`。

完整 report 由 `evaluation run --json` 输出到 stdout，交由调用方保存后再比较。下面的 `APPROVED_REPORT_JSON` 和 `CANDIDATE_REPORT_JSON` 分别表示已审核的健康 report 与新候选 report 的实际路径；已有基线不会被隐式替换：

```bash
knowledge evaluation baseline APPROVED_REPORT_JSON --output approved-baseline.json
knowledge evaluation compare approved-baseline.json CANDIDATE_REPORT_JSON
knowledge evaluation gate approved-baseline.json CANDIDATE_REPORT_JSON \
  --policy examples/evaluation-gate.json --json
```

完整文件命令与 policy 格式见 [核心参考](docs/core-reference.md#evaluation-baselines-and-regression-gates)；独立质量门槛、token 与性能口径见 [后端验收](docs/acceptance.md)。

## 默认只读，写入需要单独授权

| 入口 | 权限与数据边界 |
| --- | --- |
| CLI／`KnowledgeLibrary` | 本地核心操作；写入由显式命令或 SDK 调用发起 |
| `knowledge serve` | 可选 `[api]`，loopback HTTP、只读 `knowledge-context` 响应，不生成答案 |
| `knowledge serve --enable-management` | 显式启用、Bearer 认证、GET only、独立只读管理连接 |
| `knowledge mcp serve --database FILE` | 默认只有五个只读 stdio 工具，固定 lexical／active |
| `knowledge mcp serve --controlled ...` | 默认关闭，只更新私有隔离 scope 的 allowlist 当前正文 |
| 工作台与 `#replay/*` | 本机视图与静态回放分开；公开预览没有 live API fallback |

默认 MCP 使用 SQLite `mode=ro`／`query_only`，不建表、不回填 FTS、不写 outbox 或批准审计。工具输入不接受数据库路径、SQL、凭据或 URL；`konwledge-mcp` 保留为等价独立 stdio 入口。

受控 MCP 须显式 `--controlled`，由本机操作人员绑定 `--mutation-manifest`、`--actor`、`--demo-root` 与数据库。只接受已准备的私有 sandbox，不接任意业务库；候选批准、任意导入、retire／remove 和 SQL 写入未开放。

批准通过独立 `knowledge mcp approve` TTY 完成，绑定 scope、actor、preview、checksum 和同一幂等键。没有 `--yes` 或 Agent 布尔确认捷径；批准 token 不进 URL 或日志。带外 TTY 不替代 OS 权限隔离，也不提供密码学人类身份证明或 SSO／RBAC。

apply 在同一事务写知识、revision／publication、FTS、command、outbox 并消费 grant。评测失败仍表示知识已提交；响应丢失或结果未知时，只按原 command／幂等键回查，不自动换键补发写请求。

证据文本与 Diff 仍是不可信输入，JSON 转义不保证下游模型免受提示注入。接入前阅读 [只读 MCP](docs/mcp-readonly.md)、[受控 MCP](docs/mcp-controlled.md) 和 [工作台说明](web/README.md)。

## 兼容命令与路径保持原名

产品定位调整不重命名已建立的命令、目录、flags 或协议。`demo` 继续用于打包语料、gold set、快照及隔离验收，不是业务知识库的唯一起点。

- `knowledge demo build`、`knowledge demo export`、`--force`、`--check` 保留；数据仍使用 `.konwledge/demo/knowledge.db`、`demo/snapshot.json` 和 `demo/snapshot.schema.json`。
- `knowledge show`／`history`／`asof`／`stale`／`refresh`／`reconcile`／`publishable`、`freshness`、`conflicts`、`conversation`／`candidate`、`database`、`evaluation`、`quality` 和 `auto-evaluation` 路径保留。
- `--database`／`-d`、`--json`、`--at`、`--all`、`--document`、`--source`、`--include-stale`、`--mode`、`--demo-vectors` 及各命令原有 flags 保留，适用范围按原接口校验。
- `scripts/workbench.py` 的 `list`／`demo`／`accept`、`--mode controlled --actor demo-editor --prepare-only` 与 `--with-distribution` 保留；统一入口只支持具备清理核验能力的 Linux，不接受外部业务库参数。
- 旧前端 `#overview`、`#trace`、`#diff`，本机 `#lifecycle`、`#evaluation`、`#guide`，受控 `#changes` 及 `#replay/*` 路由保留，各模式仍独立限制访问。

完整内置链路见 [核心参考](docs/core-reference.md#versioned-snapshot)。历史实现编号与验收数字已留在 CHANGELOG 和历史路线文档，不拿旧统计充当本轮测试结果。

## 开发验证入口

以下为仓库保留的验证命令，不代表本文编辑时已运行：

```bash
uv sync --locked --dev
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests scripts
uv run pytest --cov=konwledge --cov-report=term-missing
uv run knowledge demo build --force
uv run knowledge demo export --check
uv run python scripts/export_management_schema.py --check
uv run python scripts/export_mutation_schema.py --check
uv run --frozen python scripts/export_replay.py --check --output web/public/replay.json
uv run python scripts/verify_distribution.py
```

前端检查在 `web/` 下执行，普通构建与只读预览分别验证：

```bash
cd web
pnpm install --frozen-lockfile
pnpm check:replay
pnpm verify
pnpm verify:preview
```

分层职责、可选服务验收与发行 smoke 见 [开发说明](docs/development.md)。当前没有后台自动评测调度、分布式协调、生产 ANN 或高可用治理；Linux 以外的 MCP／工作台平台实测也尚不完整。

## 文档导航

- [架构](docs/architecture.md)：领域分层、事务与读写边界。
- [开发说明](docs/development.md)：依赖、模块职责、代码阅读与验证。
- [核心参考](docs/core-reference.md)：原 README 自 Public Python API 起的完整 SDK／CLI 技术章节。
- [自动评测](docs/auto-evaluation.md)：评测集绑定、触发范围、状态与恢复。
- [后端验收](docs/acceptance.md)：默认质量门槛、token 预算与性能口径。
- [只读 MCP](docs/mcp-readonly.md)／[受控 MCP](docs/mcp-controlled.md)：查询契约与带外批准。
- [静态回放预览](docs/replay-preview.md)／[工作台说明](web/README.md)：静态、实时与受控模式。
- [参与贡献](CONTRIBUTING.md)／[变更记录](CHANGELOG.md)／[Apache License 2.0](LICENSE)。

<!-- 文档校对记录
本次补记 PyPI 首次正式发布事实，并新增已发布版本安装段，同时保留从源码 checkout 安装与仓库 examples 的原有示例边界。
关键机制、示例命令、版本名词和兼容入口未改；examples 仍要求先取得源码仓库，本记录不宣称 GUI、Web 服务或公开 live backend 已部署。
已对本次新增中文做半角标点机械扫描，结果为 0；代码块、命令、路径、URL、hash、版本号与既有历史文本按规则保留。
本记录只覆盖文档文字、链接与发布状态表述核对，不代表本次在本地重新执行 README 中的安装命令。
-->
