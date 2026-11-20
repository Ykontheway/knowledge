# 受控 MCP 正文更新

B6 **已完成并验证（Unreleased）**：受控正文更新 MCP 已通过 Linux 主验收。默认 MCP 保持 [B5／U22 已完成的只读验收](mcp-readonly.md#最终验证已通过)范围内的五个只读工具，主验收确认默认模式对知识、command、outbox 与批准审计均为零写入；显式 `--controlled` 后新增五个工具，总计十个。主验收汇总为 36 成功、17 拒绝、61 响应；3 次正文提交产生 3 个 command 与 3 个 job，评测链路为 `passed → failed → passed`，独立 PTY 批准共 3 次。Linux 真实 SDK session、独立 PTY 批准、完整回归及 wheel／sdist 隔离发行 smoke 均通过，macOS／Windows 未实测。版本仍为 `0.1.0` prepared，未提交或推送，未创建 PR、合并 main、创建 tag、发布 PyPI 或公开部署。

## 只更新隔离演示正文

默认 MCP 仍只有 B5 的五个只读工具，使用 SQLite URI `mode=ro`／`query_only`，不创建批准表；主验收确认默认模式对知识、command、outbox 与批准审计均为零写入。显式启用 `--controlled` 后才增加五个工具，总计十个；只支持 manifest allowlist 中 `file` 来源的当前 `markdown`／`text` 正文更新。没有批准签发工具，也没有新增写 HTTP 接口。候选批准、retire／remove、任意文件导入和 SQL 写入均未开放；后续命令逐类评审，B6 不扩大为生产写权限。

受控服务只接受 B4 prepare 格式的私有 sandbox：`ROOT/<scope-UUID>/mutation-manifest.json` 和 `ROOT/<scope-UUID>/<seed-dir>/knowledge.db`，同 seed 目录须有通过的 `report.json`。`<seed-dir>` 以准备结果为准，准备脚本生成运行目录，隔离安装 smoke 使用 `seed`。根目录、scope 及其子目录须为当前 OS owner 所有、权限 `700`，文件为 `600`；拒绝 symlink、硬链接文件、路径身份替换、scope／database 不匹配或 allowlist 与库内 source 集合不一致。必须已有 B4 表、FTS 和已启用且绑定有效评测集的 auto-evaluation，不接用户业务库。

## 先准备，再按实际路径启动

在仓库根目录运行：

```bash
uv sync --extra mcp
uv run python scripts/prepare_mutation_demo.py
```

准备脚本新建副本并输出 `status=ready`、`manifest`、`database`、`scope_id` 和 `source_ids`。从这次 summary 选择实际路径和 ID，不沿用历史演示 ID；它不接受用户文档或已有业务数据库。`workbench.py demo --prepare-only` 默认是 readonly，不会给出 mutation manifest；如使用该入口，必须加 `--mode controlled --actor demo-editor --prepare-only`。

把下列 `FILE`、`MANIFEST` 换成 summary 中的实际 `database`、`manifest`，`ROOT` 换成对应私有演示根目录：

```bash
knowledge mcp serve --database FILE --controlled --mutation-manifest MANIFEST --actor demo-editor --demo-root ROOT
# 等价独立 stdio 入口
konwledge-mcp --database FILE --controlled --mutation-manifest MANIFEST --actor demo-editor --demo-root ROOT
```

`--demo-root` 默认是当前工作目录下的 `.konwledge/mutation-demo`；从其他目录启动时应显式指定正确根目录。database、manifest、actor、ROOT 都由本机操作人员在 CLI 绑定，工具参数不能输入或更换它们。只读模式不能夹带受控启动参数，B4 bearer key 也不能换取 MCP 写权限。`demo-editor` 是 actor 示例，session role 为 `demo_editor`，capability 仅为 `document.update`。

MCP 仍只走 stdio，stdout 只写协议，安全诊断写 stderr。可选依赖仍为 `mcp>=1.30.0,<2`，已测 B5 baseline 是 `1.30.0`；SDK 不进入 core 运行时依赖，B6 不新增 FastAPI 依赖。普通 CLI help／version 和批准 CLI 不需要 SDK，缺 extra 的 MCP 启动安全失败且不接触数据库。

## 工具参数是封闭白名单

五个原有只读工具与 [B5 查询契约](mcp-readonly.md#工具与输入范围)保持不变。新增工具如下，实际 schema 由 `tools/list` 返回；所有输入都拒绝未知字段。

| 工具 | 必需参数 | 作用 |
| --- | --- | --- |
| `get_mutation_session` | 无，传 `{}` | 读取绑定的 scope／actor、allowlist 当前 source／document ID 与 checksum |
| `get_mutation_document` | `document_id` | 读取允许范围内当前文档的完整正文，不读取历史版本 |
| `preview_document_update` | `source_id`、`document_id`、`expected_checksum`、`text` | 返回 Diff、`preview_id`、`new_checksum`、过期时间及 `confirmation_token`，只写预览审计 |
| `apply_document_update` | `preview_id`、`confirmation_token`、`idempotency_key`、`approval_token` | 持人工带外批准提交已审阅预览 |
| `get_mutation_command` | `command_id` | 按原幂等键只读回查持久化提交与评测状态 |

ID 和幂等键均为 UUID，checksum 为小写 SHA-256。`apply_document_update` **没有 `confirmed` 字段**，Agent 填布尔值不能完成审批。get 工具不写表或启动评测；preview 可写审计，但不写知识、command 或 outbox。ToolAnnotations 只提示客户端，不能代替服务校验。

完整当前正文是操作人员明确授权返回的受控文本；会话标签固定为“演示文档”。DTO 不透传 raw metadata、locator、URL、任意 payload 或原始异常。正文和 Diff 仍是不可信输入，下游须自行限制模型与工具权限。

## 人工批准通过独立终端

先调用 session，选择本次 allowlist 的当前文档，再读取正文并提交 preview。保留 preview 返回的 `confirmation_token`，为本次提交固定一个 UUID `KEY`，在批准、apply 和恢复中使用同一个键。人工在独立终端运行：

```bash
knowledge mcp approve --database FILE --mutation-manifest MANIFEST --actor demo-editor --demo-root ROOT --preview-id PREVIEW_ID --idempotency-key KEY
```

`FILE`、`MANIFEST`、actor 和 ROOT 必须与受控服务一致，`PREVIEW_ID` 来自刚才的 preview。批准要求 **stdin 和 stderr 都是终端**，管道输入会拒绝。CLI 在 stderr 显示 JSON 转义的完整 Diff、旧／新 checksum、scope／actor、键及过期时间；ESC、控制字符和 bidi 字符不会作为终端控制序列解释。核对后必须键入显示的完整短语，替换下列占位值：

```text
APPROVE PREVIEW_ID KEY NEW_CHECKSUM
```

没有 `--yes`、`--confirmed` 或其他自动确认参数。签发的 grant 保存在固定 `scope/mcp-approvals/<grant-UUID>.json`，目录 `700`、文件 `600`，含批准／scope／preview ID、actor、幂等键、`expires_at` 和 `approval_token`；数据库批准审计保存 `token_hash`、`preview_binding_hash` 与 `request_fingerprint` 等绑定字段。stdout 只返回安全文件位置与批准 ID，不打印正文或 token，token 不进 URL 或日志。

人工仅将文件中的 `approval_token` 转交给 MCP apply；`confirmation_token` 必须仍取自 preview。批准命令只签发 grant 审计，不提交知识、command 或 outbox。grant 最长有效 **120 秒**，且不晚于 preview 的 **300 秒**期限；绑定 actor、scope、幂等键、preview 内容与 confirmation token 对应的请求指纹。首次 apply 在知识提交事务中消费 grant。

独立 TTY 只把批准移出模型通道。若 Agent 能以同一 OS 身份运行批准命令或读取批准文件，仍须用 OS 权限隔离审批能力；这里没有密码学人类身份证明，也没有企业 SSO／RBAC。

## 提交与评测分开判断

受控启动先做严格只读 scope／schema 预检，通过后只允许新增 `mcp_approvals` 表，不升级核心 schema、不回填 FTS。已有 B4 表须由准备阶段建立，不能靠 MCP 修复业务库。

正文实际变化时，apply 在同一个 `BEGIN IMMEDIATE` 事务里校验并写入知识、revision／publication、FTS、command 和 auto-evaluation outbox，同时消费 grant。提交后的评测状态按原链路读取：即使 `evaluation_status=failed`，结果仍是 **`committed=true`、`isError=false`**，不能伪报回滚或自动接受 baseline。正文未变时记录 command 并消费批准，不新增 revision／job，返回 `changed=false`、`evaluation_status=not_triggered`。

同键且请求完全相同只返回原 command／job，不重复写；已经消费的精确 grant 即使过期也可只读重放已提交结果。换键、换 preview、换 token 或换身份均不能复用批准。同键异请求拒绝，这种重放能力不授权客户端自动补发写请求。

## 拒绝与未知结果恢复

| 场景 | 固定错误示例 | 处理 |
| --- | --- | --- |
| 未启用 controlled 就调用新增工具，或夹带未知字段／`confirmed` | `mcp_tool_not_found`、`mcp_invalid_arguments` | 不开放写服务，按实际 schema 修正 |
| 不在 allowlist、历史文档、checksum 已变、跨 actor／scope | `mcp_source_not_allowed`、`mcp_historical_document`、`mcp_checksum_conflict`、`mcp_scope_mismatch` | 重新读取当前授权范围，不绕过冲突 |
| 缺批准、批准过期或绑定不符、preview 过期 | `mcp_approval_required`、`mcp_approval_expired`、`mcp_approval_conflict`、`mcp_preview_expired` | 已知未提交的请求须重新预览／人工批准 |
| 同键异请求 | `mcp_idempotency_conflict`、`mcp_approval_conflict` | 保留原键回查，不能用换键掩盖冲突 |
| apply 提交结果或响应无法确认 | `mcp_mutation_outcome_unknown` | 只回查原 command，不推断未提交或回滚 |

已知校验拒绝不会写知识、command 或 outbox；已存在的 preview／grant 审计不因此删除。工具错误返回 `isError=true` 和固定 code／status，不返回私密正文、输入值或 raw exception；status 只是 stdio 错误分类，不是 HTTP 响应。

apply 返回未知、stdin EOF、进程退出或响应丢失后，重新连接到同一 FILE／MANIFEST／actor／ROOT，调用 `get_mutation_command`，令 **`command_id` 等于原 `idempotency_key`**。找不到或无法读取原 command 时，仍保留原键并交操作人员核查；不自动重试 apply，也不自动发 POST。EOF 清理资源不表示撤销数据库提交，评测 job 重试与知识写恢复须分开处理。

## 大小限制按实际序列化计数

- preview／apply 的已解析参数按紧凑 JSON UTF-8 序列化计数，含转义，最多 **128 KiB**；`text` 最多 **64 KiB UTF-8**，Diff 最多 200 项。超限或非法 Unicode 安全拒绝。
- 完整 `CallToolResult` 最多 **2 MiB**，计入 JSON text 转义、`structuredContent` 和结果字段，不含 JSON-RPC wrapper。该限制不约束输入 wire 大小或峰值内存；参数预算也在 SDK 读取消息之后检查。
- 不截断精确文本。一般响应超限返回 `mcp_response_too_large`；apply 已调用后若响应超限或序列化失败，则返回 `mcp_mutation_outcome_unknown` 并要求原键回查，不能承诺未提交。

<!-- 兼容早期引用，旧锚点保留。 -->
<a id="b6-最终验收待补"></a>
<a id="b6-最终验收已通过"></a>
## B6 最终验收已通过

Linux 真实 SDK session、独立 PTY 人工批准、事务提交与原键恢复、完整回归，以及 wheel／sdist 隔离发行 smoke 均已通过。每种发行格式的受控 MCP lane 各通过 17 项检查，均记录十工具、4 条冻结用例、36 次成功调用、17 次拒绝、61 个协议响应、5 个 session、3 次 PTY 批准。3 次正文提交产生 3 个 command、3 个 job 与 3 次 grant 消费，评测链路为 `passed → failed → passed`。调用数与协议响应数按验收报告的独立统计口径记录。

| 检查 | 结果与范围 |
| --- | --- |
| 当前代码 Python 全量复核 | `uv run --frozen --extra mcp pytest -q`：2439 passed、7 skipped，401.46 秒 |
| 静态检查 | Ruff check 通过；format check 为 238 files；`mypy src tests scripts` 为 210 sources，无错误 |
| 前端与 schema 联调记录 | `pnpm verify` 为 430 passed、2 skipped；management／mutation exporter `--check` 均保持不变 |
| 显式 Linux 统一入口 E2E | 2 passed，45.10 秒；普通 Python 回归中这两项仍默认 skip |
| full 工作台及发行 | seed／management／evaluation／mutations／distribution 全部 passed，exit 0，无 timeout，清理核验通过 |
| wheel／sdist 真实 MCP | 每种格式的受控 lane 17 项通过，旧 core-only／extra/default／min1.30 lanes 也通过；SDK 1.30.0、Pydantic 2.14.3 |

7 项 Python skip 分别为缺 PostgreSQL DSN 的 1 项、未安装 LanceDB 的 2 项、内存 MCP 不适用文件 RO／WAL 的 2 项，以及默认关闭的工作台 live 2 项。显式 live E2E 另跑通过，不改写普通回归计数，也不表示已验证真实 PostgreSQL 或 LanceDB 环境。前端两个默认 live skip 保留；生产 build 的 chunk 体积提醒为非阻断项。

本地原始报告保留在 `.konwledge`，不随 Git 提交：

- [完整工作台汇总](../.konwledge/workbench/8f935dcb-ec6b-4a67-8b56-a02d8c970ce4/summary.json)与其 distribution 组件的 [`wheel-smoke-summary.json`](../.konwledge/workbench/8f935dcb-ec6b-4a67-8b56-a02d8c970ce4/distribution/652e52a2-0561-4279-8e7e-5152062332a7/driver/wheel-smoke-summary.json)、[`sdist-smoke-summary.json`](../.konwledge/workbench/8f935dcb-ec6b-4a67-8b56-a02d8c970ce4/distribution/652e52a2-0561-4279-8e7e-5152062332a7/driver/sdist-smoke-summary.json)。B-R2 的 82 项发行摘要投影不包含 MCP，须单独检查底层 `mcp_controlled_extra`，不能当作 B6 验收数量。
- [前端、schema 与进程清理审计](../.konwledge/byproducts/b6-final-regression-20261118/regression-audit.json)及同目录日志。live demo 的 [readonly](../.konwledge/workbench/1d01488c-5d7e-4889-a895-52de88faa83f/summary.json)与 [controlled](../.konwledge/workbench/79b9c0c8-9d1e-463a-b726-c14260519f44/summary.json)停止记录均为 `stopped`、exit 130、清理核验通过，不记成评测 passed。
- 首轮发行失败记录 `.konwledge/b6-distribution-first-verification/failure-summary.json` 保留；TTL 测试时钟修复后的第二轮 wheel／sdist 报告保留在 `.konwledge/b6-distribution-second-verification`，不覆盖失败历史。

收尾隔离发行复核已通过，命令为：

```bash
uv run --frozen --extra mcp python scripts/verify_distribution.py --output-dir .konwledge/b6-closeout-distribution-verified
```

本次 [`wheel-smoke-summary.json`](../.konwledge/b6-closeout-distribution-verified/wheel-smoke-summary.json)与 [`sdist-smoke-summary.json`](../.konwledge/b6-closeout-distribution-verified/sdist-smoke-summary.json)均确认受控 lane 的 17 项检查通过，旧 core-only／extra/default／min1.30 lanes 也通过，调用及提交计数与上表一致。收尾隔离环境实际为 SDK `1.30.0`、Pydantic `2.14.4`；上表及 full 联调历史环境为 Pydantic `2.14.3`，没有人工 pin Pydantic。验收后仅补录本段报告引用与实际依赖版本，源码及协议合同未变。

默认 MCP 维持 B5 的五个只读工具与零写入结果；显式 `--controlled` 后才开放受控正文更新。sdist 已覆盖本文及受控 smoke／测试文件。B5 历史计数和发行证据保持原范围。macOS／Windows 未实测，B-R2 的 Linux 清理依赖继续单列平台待办，不计作 B6 平台通过。版本仍为 `0.1.0` prepared／Unreleased；feature 分支提交与推送以 Git 历史为准，不代表 PR、main 合并、tag、PyPI 发布或公开部署授权。

<!-- B6 收尾校对：事实、平台与读写边界已逐项回读。实际 grep_search 扫描 README.md、CHANGELOG.md、docs/mcp-controlled.md、docs/mcp-readonly.md、docs/integrated-demo-roadmap.md、docs/workbench-entry.md 六文件：中文半角标点、元话语、反转句式、破折号有效命中均为 0；章节编号原始命中 1，为 CHANGELOG 的 0.1.0 版本索引，予以豁免。保留 B1～B5 历史验收数字，B6 默认零写入、Linux 已验、macOS／Windows 未测；live stopped 不计作 passed。本次仅修正过时状态、补齐最终证据与命令，原正文合同不变。 -->
