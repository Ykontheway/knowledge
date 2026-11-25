# 只读 MCP 使用说明

B5／U22 的**更名前实现与历史验收已完成**，原 ID 不变。默认 MCP 只提供本机 stdio 查询，不开放写工具；当前新 distribution `knowledge-ykforward==0.1.0` 为未发布 Alpha 候选，import 为 `knowledge`，CLI 为 `knowledge`／`knowledge-mcp`。Linux 真实 SDK session、完整回归与 wheel／sdist 隔离安装的旧结果见 [审计](releases/legacy-0.1.0.md#b5-原始隔离发行记录)，不能替代新候选验证。本文不代表已推送、部署或获得生产授权；旧入口与目录处理见 [迁移说明](migration-to-knowledge.md)。

B5 默认五工具及下文历史验收保持不变。B6 受控正文更新已完成并验证，只有显式启用 `--controlled` 才增加五个工具，总计十个；人工批准走独立 TTY，MCP 不签发批准。本文的只读、不建表语义均指默认模式；受控启动、批准与原键恢复见 [受控 MCP 正文更新](mcp-controlled.md)，[最终验收](mcp-controlled.md#b6-最终验收已通过)单独记录，不计入 B5 历史结果。

## 安装按需选择

核心安装不需要 MCP SDK，普通 CLI 的 help、version 和已有命令保持独立。运行 MCP 才需要可选 `[mcp]`，extra 与开发组均使用 `mcp>=1.30.0,<2`；核心 Pydantic 仍为 `pydantic>=2.7,<3`，未收紧。

```bash
# 未来发布并核验后才可使用；当前请用下方源码安装
pip install 'knowledge-ykforward[mcp]==0.1.0'
```

这条命令说明可选 extra 的安装方式，不表示包已发布到 PyPI。当前可从仓库安装：

```bash
pip install '.[mcp]'
```

开发环境使用：

```bash
uv sync --extra mcp
```

为避免上游兼容问题，选择 SDK `1.30.0` 作为已测 baseline。旧 SDK `1.2`、`1.20` 与最新 Pydantic 组合缺少私有 `eval_type_backport`，补依赖也未解决，不承诺支持这两版或整个 SDK 区间。当前主环境实际为 SDK `1.30.0`／Pydantic `2.14.1`；隔离发行环境的解析结果见下文。

开发组／CI 使用 SDK 做测试和类型检查，不把 SDK 加入 core 运行时依赖。缺少 extra 时，两个 MCP 入口都只向 stderr 给出安全安装提示，退出码为 `1`，stdout 不输出协议外文本，也不接触或创建数据库。

## 两个入口共用 stdio

```bash
knowledge mcp serve --database FILE
knowledge-mcp --database FILE
```

`FILE` 由本机操作人员替换为已有 SQLite 数据库文件。两个命令使用相同 stdio 实现，stdin 接收 MCP 消息，stdout 只写协议响应，安全诊断写 stderr。会话结束或 stdin EOF 后释放读取连接、传输和 engine。

MCP 不监听 HTTP 端口，不提供 SSE、公网服务或 SSO。它与 U18 的 `knowledge serve` HTTP 入口不同，不继承 HTTP bearer key，也不开放 B4 mutation API。MCP 查询不能把 B4 写 key 或其他凭据换成写权限。

客户端配置示例：

```json
{
  "mcpServers": {
    "knowledge": {
      "command": "knowledge",
      "args": [
        "mcp",
        "serve",
        "--database",
        "/absolute/path/to/knowledge.db"
      ]
    }
  }
}
```

请替换示例路径，并确保客户端能找到 `knowledge`。这段 JSON 是用户手动使用的配置样例，路径不是凭据；本文不自动配置客户端，也不启动长期服务。启动权和数据库访问范围由本机操作人员决定，数据库选择发生在 CLI，不发生在工具参数中。

## 数据库读取不初始化写服务

每次 stdio 会话独立绑定已有本地数据库；每个读取请求另开 SQLite URI `mode=ro` 连接，设置 `PRAGMA query_only=ON`，显式开启事务，结束时 rollback 并关闭专用连接。不复用写 session，也不改变原 SDK 写连接的状态。

默认只读模式的启动和读取均不创建或升级 schema，包括不创建 `mcp_approvals`；不创建／回填 FTS，不写 auto-evaluation outbox、不启动评测，也不构造 `KnowledgeLibrary` 写服务。缺失数据库不会自动创建；缺表、缺 FTS 或不兼容旧 schema 会安全失败，不修复、不升级、不静默降级。数据库准备或升级须在 MCP 之外由操作人员另行决定。

默认只读会话的工具名称是封闭白名单。参数只接受查询、ID、历史时间及有界预算／分页，不接收数据库路径、SQL、凭据或 URL。所有输入模型使用 `extra="forbid"`，未知字段和写工具调用均拒绝。`query` 是检索文本，不能据此执行 SQL 或访问任意路径／URL。

## 工具与输入范围

| 工具 | 输入 | 返回 |
| --- | --- | --- |
| `search` | `query`；可选 `top_k`、`candidate_limit`、`rrf_k`、`at`、`source_id` | active 精确证据、版本锚点及固定检索诊断 |
| `build_context` | search 参数，加 `max_chars`、`max_units` | 有预算的完整证据 `blocks` 和跳过原因 |
| `get_evidence` | `unit_id` | 指定 unit 所属版本的精确文本、字符范围与历史 hash／revision 锚点 |
| `get_lineage` | `lineage_id`；可选 `limit`、`offset` | 分页版本链 `versions`，不返回正文 |
| `compare_documents` | `old_document_id`、`new_document_id`；可选 `limit`、`offset` | 同一来源两个版本的 Diff 计数与分页 `changes`，不返回正文 |

每个 Tool 均设置 `ToolAnnotations`：`readOnlyHint=true`、`destructiveHint=false`、`idempotentHint=true`、`openWorldHint=false`。这些字段只给客户端提示，实际防护由 SQLite `mode=ro`／`query_only` 提供。

`search` 和 `build_context` 固定 `lexical`、`include_stale=false`。`mode` 和 `include_stale` 不属于输入模型，不能开启 vector／hybrid 或纳入 stale。`source_id` 可缩小检索范围，但不构成生产权限认证。

`at` 仅用于 search／build_context。输入模型的 before 校验允许 Python 带时区的 `datetime`，wire 输入接受带时区的 ISO 8601 日期时间字符串，例如 `2026-11-10T00:00:00Z`；数字、布尔值及数字字符串均拒绝，不转换为时间戳。默认使用本次检索时间。active 资格按该时间的 publication／revision 记录判断，不拿今天的 unit 状态缓存替代历史状态。lineage／Diff 中的 `status` 是持久化当前缓存，不能解释为历史时点状态。时间参数、版本顺序和 Diff 均不承诺时间因果或根因判断。

| 参数 | 默认值 | 范围 |
| --- | --- | --- |
| `query` | 必填 | 严格字符串，1～4096 字符且非空白 |
| `top_k` | 5 | 1～100 |
| `candidate_limit` | `max(50, top_k)` | 1～1000，且不小于 `top_k` |
| `rrf_k` | 60 | 1～1000 |
| `max_chars` | 8000 | 0～100000 |
| `max_units` | 10 | 1～100 |
| `limit` | 20 | 1～100，仅 lineage／Diff 分页 |
| `offset` | 0 | 0～100000，仅 lineage／Diff 分页 |

整数预算和分页参数使用严格校验，不把布尔值当整数。工具的实际输入 schema 随 `tools/list` 返回。

## 上下文只限制字符和块数

`build_context` 只提供字符／块数预算，**没有 token budget，`max_tokens` 不在 MCP 输入模型中**。核心上下文 API 的可选 token 能力不扩展到这里。

`used_chars = sum(len(block.text) for block in blocks)`，按 Python Unicode code point 计数；标签、ID、JSON 转义和外层协议不计入字符预算。超过预算的整块跳过，不截断原文，也不生成摘要。按检索顺序去重 lineage、排除同一文档版本中的重叠范围，并限制块数；跳过原因是 `duplicate`、`overlap`、`budget` 或 `max_units`。

MCP 返回结构化 `blocks`，每块包含完整选段与 ID／hash 锚点，并使用连续的 `[1]`、`[2]` 标签。这里的 MCP `ContextPacket` 是独立输出模型，不透传核心 `ContextPacket.context_text`，不渲染 source URL，也不返回 locator／href。

空检索或空上下文是合法结果，不表示 LLM 拒答。检索分数、引用完整性和历史校验都不证明知识内容或生成答案正确；服务不调用 LLM。下游仍须把证据文本当作不可信输入，并自行控制模型和工具权限。

## 历史证据保留原版本

`get_evidence` 按明确的 `unit_id` 查该 unit 所属 document，保留原文空白和 Unicode，返回半开字符区间 `[start_char, end_char)`。校验内容包括 unit／document 关联、范围长度、文本 SHA-256 `content_hash`、`document_checksum` 与 revision／publication 历史锚点；响应只给锚点 ID，不透传 revision payload。

原样延续到新 document 的 unit 可能没有单独 revision，此时用该版本首次 publication 的 document checksum 与发布前的 lineage 内容 hash 联合锚定。历史锚点缺失或损坏时明确失败，绝不改用 latest 正文或最新 revision 替代旧版本证据。

输出使用独立白名单 DTO：仅在 search／context／evidence 中返回选中的精确文本，以及规定的 ID、hash、字符范围、状态、排名／分数或预算／分页字段。源 raw metadata、locator、href、任意 payload 和异常原文均不透传。正文自身可能含敏感内容，白名单并不替代操作人员对数据库和客户端的数据使用授权。

## 结构化响应有完整大小上限

每个 Tool 均声明标准 `outputSchema`；结果同时提供 `structuredContent` 与内容一致的 JSON `TextContent`，没有旧 SDK fallback。

整个 `CallToolResult` 的 UTF-8 序列化结果上限为 **2 MiB（2097152 bytes）**，包含 text 的 JSON 转义、`structuredContent` 及其他结果字段。该上限不包含 JSON-RPC 外层，也不限制输入 bytes 或序列化峰值内存。它与 `build_context` 的字符／块预算分开计算。

超限返回 `mcp_response_too_large`／`413`，不截断 exact evidence。非法 Unicode 或非有限浮点无法安全序列化时，返回固定 `mcp_internal_error`／`500`，不反射异常或原始值。

## 工具错误只返回固定代码

可寻址的工具错误用 MCP `CallToolResult` 返回 `isError=true`，JSON 文本只包含固定错误对象，不返回成功 DTO 的 `structuredContent`，例如：

```json
{"error":{"code":"mcp_invalid_arguments","status":400}}
```

`status` 用于工具错误分类，服务只使用 stdio，不发送 HTTP 响应。工具错误 `code` 使用白名单；未知服务异常统一转成 `mcp_internal_error`，不回显输入值、私密 query、路径、SQL、凭据或异常原文。

| status | code |
| --- | --- |
| 400 | `mcp_invalid_arguments` |
| 404 | `mcp_tool_not_found`、`unit_not_found`、`lineage_not_found`、`document_not_found` |
| 409 | `diff_source_mismatch`、`mcp_record_invalid`、`historical_evidence_invalid`、`historical_lineage_invalid` |
| 410 | `historical_document_unavailable`、`historical_source_unavailable`、`historical_evidence_unavailable` |
| 413 | `mcp_response_too_large` |
| 503 | `mcp_storage_unavailable`、`mcp_snapshot_unavailable` |
| 500 | `mcp_internal_error` |

无法解析的协议消息由 SDK 处理，不承诺每条坏消息都能得到工具错误；stdout 不混入普通日志，stderr 也不输出异常详情。

## 最终验证已通过

以下结果属于更名前 B5 历史验收，不是本次更名验证。新 distribution `knowledge-ykforward` 尚未发布，旧 import／CLI 停止提供，迁移见 [说明](migration-to-knowledge.md)。

本轮实测范围是 **Linux 的真实 SDK stdio session**，覆盖初始化、五工具调用、拒绝非法请求、EOF 清理及数据库读取前后不变。macOS 尚未实测。B-R2 的 Linux `/proc`、`subreaper`、`pidfd` 清理依赖保留，本轮不计作 B-R2 平台兼容验收。

主环境使用 SDK `1.30.0`／Pydantic `2.14.1`，最终结果如下；定向测试与全量有重叠，不相加：

| 检查 | 最终结果 |
| --- | --- |
| `uv run --frozen --extra mcp ruff check .` | all passed |
| `uv run --frozen --extra mcp ruff format --check .` | 227 files，通过 |
| `uv run --frozen --extra mcp mypy src tests scripts` | 200 sources，通过 |
| `uv run --frozen --extra mcp pytest -q` | 2131 passed、7 skipped，322.01s |
| 前端 `pnpm verify` | 430 passed、2 skipped |
| management／mutation schema `--check` | 两份输出不变 |
| MCP protocol tests | 36 passed |
| MCP service／protocol／distribution／release 定向测试 | 343 passed、2 skipped；这 2 项为内存库下文件／WAL 检查不适用 |

全量的 7 项跳过分别为：缺少 `KNOWLEDGE_TEST_POSTGRES_DSN` 的 PostgreSQL 用例 1 项、未安装 `lancedb` 的用例 2 项、内存库下 `file-ro`／`WAL` 检查不适用 2 项、需 `KNOWLEDGE_WORKBENCH_DEMO_LIVE=1` 的 B-R2 real demo 2 项。显式 Linux live 验证使用 `KNOWLEDGE_WORKBENCH_DEMO_LIVE=1 uv run --frozen --extra mcp pytest -q --tb=no tests/test_workbench_demo_live.py`，结果为 **2 passed，40.66s**，不另加到全量数量。

## 隔离发行验证保留原始证据

历史 full 汇总、原 wheel／sdist 路径、实际依赖版本和 live 停止记录见 [B5 原始隔离发行记录](releases/legacy-0.1.0.md#b5-原始隔离发行记录)。当时 full 各组件 passed，82 项仅 B-R2 汇总投影，**不包含 MCP extra**；MCP 底层共 72 项独立通过（wheel／sdist 各 core-only 6、extra/default 15、min1.30 15），不与上表全量相加。每个 extra lane 的 3 session、18 成功、39 拒绝、63 响应及 EOF 清理保留原统计。

旧 live demo 均 `stopped`、launcher `exit_code=130`、`cleanup_verified=true`，不计为验收 `passed`。旧路径及失败记录不搬迁、不改名，不能据此回填新 distribution 的检查结果。

本节仅保留 B5 的 Linux 五工具真实 SDK session 与只读发行历史结果。B6 正文更新已完成并验证，最终结果另列于 [受控 MCP 验收](mcp-controlled.md#b6-最终验收已通过)，不改写 B5 计数。feature 分支提交与推送以 Git 历史为准；未创建 MR／PR、合并 main、创建 tag、发布 Release／PyPI 或公开部署。路线和状态见 [B系列任务与重构路线](integrated-demo-roadmap.md)。

<!-- B5 历史结果与 B6 最终状态已分开核对；六文档的中文收尾校对与机械扫描记录见 mcp-controlled.md 文末。 -->
