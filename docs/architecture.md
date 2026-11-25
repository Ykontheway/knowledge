# 当前架构

Knowledge 是本地优先的 Knowledge CI 知识生命周期与质量门禁基础设施。它管理本机知识库、版本日志、检索证据和评测结果，不调用 LLM 生成答案。

当前 Python distribution `knowledge-ykforward==0.1.0` 为未发布 Alpha 候选，import 为 `knowledge`，CLI 仅 `knowledge`／`knowledge-mcp`；命名和旧目录处理见 [迁移说明](migration-to-knowledge.md)。核心链路与工作台已有实现，尚未生产化。适用范围是单机、单库、显式启用的工程场景；生产 SSO／RBAC、托管服务、高可用和部署 SLA 均不在当前承诺内。

2026-11-23 的旧公开静态预览及原地址见 [历史审计](releases/legacy-0.1.0.md#静态回放发布与验收)。它只读取固定合成数据；更名后的站点尚待重新部署与验证，不能据此声明 HTTP 管理 API、受控写入或 live 公网服务已上线。

## 分层各自守住边界

| 层 | 当前路径 | 职责与边界 |
| --- | --- | --- |
| 应用入口 | `src/knowledge/__init__.py`、`src/knowledge/application.py`、`src/knowledge/cli.py` | `KnowledgeLibrary` 组合服务；CLI 显式发起本地读写 |
| 领域模型 | `src/knowledge/domain/` | 严格校验来源、文档、单元、revision、引用和评测模型 |
| 存储与事务 | `src/knowledge/storage/` | SQLite、repository、显式 `UnitOfWork`、FTS5、任务持久化 |
| 导入 | `src/knowledge/ingestion/` | UTF-8 规范化、可追溯拆分、幂等导入 |
| 生命周期 | `src/knowledge/lifecycle/` | lineage、Diff、publication、revision、status 与 as-of |
| 时效 | `src/knowledge/lifecycle/freshness.py`、`src/knowledge/domain/freshness.py` | TTL、来源更新时间策略、显式 stale／refresh；没有独立 `freshness/` 包 |
| 冲突 | `src/knowledge/conflicts/` | 保存带证据的冲突候选，供人工审核，不自动判定事实真伪 |
| 检索 | `src/knowledge/retrieval/` | 资格过滤、lexical／vector／hybrid、RRF 与降级诊断 |
| 向量准备 | `src/knowledge/embedding/`、`src/knowledge/indexing/` | provider、缓存、索引适配与版本更新；真实 provider 由调用方配置 |
| 上下文 | `src/knowledge/context/` | whole-unit 选择、精确引用、字符预算与可选 token 预算 |
| 固定评测 | `src/knowledge/evaluation/`、`src/knowledge/quality/` | 不可变数据集、report、baseline、compare、回归 gate 与绝对质量验收 |
| 自动评测 | `src/knowledge/auto_evaluation/` | 显式 enable、配置绑定、同事务 outbox、提交后同步评测、lease／retry／recover |
| 对话与数据库结构 | `src/knowledge/conversations/`、`src/knowledge/database_schema/` | 对话候选人工审核；SQLite／PostgreSQL 只捕获 schema，不读取业务行 |
| HTTP 与管理投影 | `src/knowledge/api/` | loopback 上下文入口、认证后的只读 management、严格 DTO |
| 受控命令 | `src/knowledge/mutations/` | B4 scope／actor、preview、command、幂等提交与未知结果回查 |
| MCP | `src/knowledge/mcp/` | B5 默认只读 stdio；B6 显式 controlled、带外批准与 grant 消费 |
| 快照与回放 | `src/knowledge/snapshot/`、`src/knowledge/replay/` | 固定快照契约、公开合成 replay bundle 与文件校验 |
| 界面 | `web/` | 复用读 DTO 的工作台与静态回放；受控页面单独处理写命令状态 |

各入口复用核心事实，但 CLI、HTTP、management、MCP 和 replay 保留独立的认证、传输及失败恢复语义。

## 版本日志记录历史事实

来源到证据的关系按下表保存，更新不会覆盖旧文档或旧单元正文。

| 对象 | 关系与用途 |
| --- | --- |
| `Source` | 稳定来源身份，关联多个文档版本 |
| 不可变 `Document` | 保存一次规范化内容与 checksum，归属于来源 |
| span `KnowledgeUnit` | 绑定确切文档版本及半开字符范围，正文可从该版本核对 |
| lineage | 跨文档版本连接同一知识的演进；单元版本仍各自保留 |
| revision chain | append-only 记录新增、修改、移动、删除、stale／refresh 等事件 |
| publication timeline | append-only 记录来源在各时点发布的文档 head，包括历史重发 |

`knowledge_units.status` 是当前查询缓存。历史状态和检索资格必须从 publication／revision 日志重建，不能用今天的 status 重算旧任务或历史引用。

默认 `active` 单元属于查询时点的已发布 head；显式 stale 仍在 head。旧版本中的 `superseded`／`deleted` 按该时点的 head 与 lineage 判断，未发布文档也不参与默认召回。

TTL 依据 lineage 最近的 `added`、`modified` 或 `refreshed` revision 计时。移动单元或原样沿用正文不续期；没有对应事件时使用 head 发布时间。时效扫描在实际扫描时写 stale 事件，不倒填为 TTL 截止时刻，也没有后台自动扫描保证。

## 规范化文本是证据坐标系

loader 去除 UTF-8 BOM，把 CRLF／CR 转成 LF，并应用 Unicode NFC；其余空白保留。splitter 按标题或段落拆分，单元保存 `[start_char, end_char)`。

必须满足 `normalized_content[unit.start_char:unit.end_char] == unit.text`。偏移按规范化文本的 Python Unicode code point 计数，不是原始文件字节、UTF-16 单元或浏览器显示长度。

Diff、management evidence、context 与 MCP `get_evidence` 都绑定被引用的确切文档版本。历史 span 不能从 latest 正文截取来代替。

## 资格过滤先于候选上限

请求先确定查询时间，再按 metadata、publication 和 revision 还原 eligible head units；过滤发生在每条路由的 `candidate_limit` 之前，防止无资格旧版本占满候选。

- 默认只召回已发布 head 的 active 单元；核心 SDK／CLI 可显式使用 `include_stale`。
- superseded、deleted 和查询时点尚未发布的版本不进入候选池。
- `source_id` 缩小查询范围，不构成授权；资格判断不信任向量 payload。

| 路由 | 实现 | 限制 |
| --- | --- | --- |
| lexical | SQLite FTS5 | 字面匹配，不等同语义理解 |
| vector | 注入 `IndexingService`，对合格记录做临时精确内存 cosine scan | 当前 O(N)；需要显式 provider／index |
| hybrid | lexical 与 vector 排名经确定性 RRF 融合 | 不拼接或相加 BM25／cosine 原始分；RRF 分不是概率 |

FTS triggers 与知识行处于同一 SQLite 事务，一起提交或回滚；绕过标准 engine 的生写入不受此保证。缺少 provider／index 明确失败，缺向量或 hash 不一致返回 degraded 诊断，不静默伪装成健康检索。

## 上下文保留整块原文

Context 只消费一次 retrieval result，不再次搜索，不生成摘要。它按排名选 whole-unit evidence，去重 lineage，并排除同一文档版本内的重叠 span；预算放不下就跳过整块，空上下文合法。

citation 保存 source／document／unit ID、exact quote、字符区间和校验锚点。ID 将这些身份与范围及 SHA-256 quote hash 写入规范 JSON，再生成 UUID5，同一证据可稳定复算，不随排名变化。

| 预算 | 计数与输入输出 |
| --- | --- |
| 核心 `max_chars` | 计算完整 `context_text` 的 Unicode 字符数 |
| 核心 `max_tokens` | 可选，需要显式 token counter 或 `[tokens]` extra |
| MCP `build_context` | 独立的字符／块数预算，输入为 `max_chars`／`max_units`；不接受 `max_tokens`，不透传 core `context_text` |

引用完整性只证明证据可核对，不保证来源事实正确或下游答案忠实。原文与 Diff 都是不可信输入，转义不能替代下游权限限制。

## 固定评测与门禁拒绝不完整证据

评测集以 `(dataset_id, version, dataset_hash)` 标识，内容不可变；修改用例须创建新版本。报告记录检索配置、固定用例、时间及指标，baseline 只能由人工显式提升完整、健康的 report，不自动替换。

compare／gate 校验数据集 ID、版本、hash，以及 `mode`、`top_k`、`candidate_limit`、`rrf_k` 一致，还要核验完整用例并重算指标。固定用例的 `at` 保持一致；`require_same_time` 可进一步要求所有时间相同，可复现 CI 应选择共同显式时间。

回归与绝对质量 gate 按 fail-closed 处理：不完整、不可比、无适用指标、degraded 或违反策略时不放行。文件型 baseline／compare／gate 只校验 JSON，不打开知识库、重新检索或调用 provider。

任务还保存 `config_fingerprint`、`knowledge_fingerprint` 与 `trigger_revision_ids`。这些字段不冻结完整 corpus、外部来源、provider／model 或 vector backend 状态，也不阻止时间流逝改变 freshness。

工作台只对符合其 DTO 可比条件的完整报告显示 delta；knowledge fingerprint 可以不同，不同评测时间只用于观察。页面不能把 delta 自动归因于一次变更，也不能据此批准发布或接受 baseline。

## 自动评测在提交后执行

自动评测默认关闭。显式 `enable` 绑定评测集版本、hash、检索参数与策略，仅保存配置，不认定已有知识合格；首版只支持 lexical。

| 阶段 | 当前行为 |
| --- | --- |
| 知识写事务内 | revision／publication 与 durable job outbox 同事务写入，保存配置绑定与触发 revision |
| 外层提交成功后 | 立即同步执行评测；同一外层事务合并为一个任务 |
| 事务回滚 | 知识与 outbox 一起回滚，不留下任务 |
| 评测未通过 | 保留已提交知识与任务结果，不自动回滚或更新 baseline；CLI 返回 `3` 并说明已提交 |

文件发布／更新／历史重发、对话候选人工批准、schema 发布、stale／refresh 和时效策略变更可触发任务。原样重导、只读查询和评测集导入不触发；绕过 revision 的直接 SQL 不属于自动触发接口。

job 领取与完成用 lease CAS 防重复领取和旧 worker 迟写。`recover` 回收超时租约，`retry` 新建关联任务，旧终态保留；恢复只重跑评测，不重放知识写命令。

报告只保存聚合指标、检查与安全错误码，不保存源文、query、绝对路径或 provider 原始异常。当前没有后台调度服务，同步评测会增加写命令耗时；一次通过不担保未来时效状态。

## HTTP 管理投影限制到本机

HTTP 只绑定 loopback。management 必须显式启用并通过 Bearer 认证；B4 写路径另用独立 key，不能复用读取 key。工作台通过同源 Node proxy 转发，本机 key 只在服务进程环境，浏览器客户端和构建产物不持有 secret。

management 请求使用独立 SQLite 只读连接：文件库 `mode=ro`，内存库 backup 快照，专用连接加 `query_only`、`BEGIN` 并以 rollback 结束。`serve` 启动仍可执行已有 additive schema／FTS 初始化，HTTP 请求只读不等于整个启动零写入。

返回 frozen、`extra=forbid` 的 strict DTO 白名单。普通投影不泄露源全文、query、绝对 locator、任意 payload 或原始异常；evidence 是明确返回历史选段的例外，仍需认证与版本校验，不承诺自动脱敏。

Python 模型导出 schema，前端生成类型并做运行时校验；management／mutation exporter 与前端 drift 检查分别守住各自契约，不用共享类型掩盖协议变化。

## 受控命令原子提交

B4 默认关闭，只接受准备工具生成的私有 sandbox 与 manifest allowlist 的当前文档。scope、actor、旧 checksum、preview 正文与确认信息都在服务端绑定，preview 有效期为 300 秒。

apply 从 `BEGIN IMMEDIATE` 开始，校验 preview、TTL、checksum、scope／actor 和评测配置，把 command、幂等指纹、知识、revision／publication、FTS 与 outbox 一起提交；同键异请求拒绝，同键同请求重放原 command 结果。

已知拒绝不留下半截知识、command 或 outbox；提交后评测失败仍表示知识已提交。响应丢失或写结果未知时，**只按原 command／idempotency key 回查**，不自动换键或补发写请求，查不到也不能推定未提交。

## 默认 MCP 在存储层只读

B5 默认仅开放 `search`、`build_context`、`get_evidence`、`get_lineage`、`compare_documents` 五个工具，固定 lexical／active，不接 `include_stale`、vector／hybrid、SQL、数据库路径或凭据。

stdio 每个读取请求使用物理 `mode=ro`／`query_only` 专用连接并 rollback，不建表、不回填 FTS、不写 outbox 或批准审计。没有 HTTP／SSE／公网监听或 Bearer 认证。

工具有严格输入、`outputSchema`、`structuredContent` 和 JSON `TextContent`。`ToolAnnotations` 只提示客户端，实际保护来自只读连接和 DTO 校验；MCP 不暴露整个核心 SDK。

## 受控 MCP 另需带外批准

B6 只有显式 `--controlled` 才增加五个工具，总计十个；新增会话读取、当前正文读取、preview、apply 与 command 回查，没有批准签发 tool。它沿用 B4 mutation engine，不允许任意导入、候选批准、删除或 SQL 写入。

- 启动绑定私有 sandbox、manifest、scope 与 actor，不能由 tool 参数更换；受控预检通过后只允许新增批准表，不修复核心库。
- 人工在独立 TTY 执行 `knowledge mcp approve`，查看转义 Diff 并输入精确短语；Agent 的布尔确认或 `--yes` 均不能替代批准。
- grant 绑定 actor、scope、preview、幂等键、请求指纹与 token，最长 120 秒，且不得晚于 preview 的 300 秒期限。
- 首次 apply 在知识提交的同一事务消费 grant；精确匹配且已消费的 grant 即使过期，也只可只读重放已提交结果。
- 换身份、键、preview 或 token 不能复用批准；未知结果仍只按原键回查，评测 retry 不授权再次写知识。

独立 TTY 把批准移出模型通道，同一 OS 身份仍可能执行批准命令或读取 grant 文件，必须另做 OS 权限隔离。该机制不提供密码学人类身份证明或 SSO／RBAC。

## 静态回放共用读模型

`src/knowledge/replay/` 用固定公开合成语料生成 bundle，复用 management 的同一 DTO read model 与历史导航；`web/` 的 `#replay/*` 只读取静态 `replay.json`，不访问用户业务库。

回放不轮询新任务，不把 DTO href 当成 live 网络请求，加载失败也没有 live fallback。旧公开页面的 2026-11-23 上线结果见 [历史审计](releases/legacy-0.1.0.md#静态回放发布与验收)，更名后的地址尚待验证；新包发行、管理服务部署和受控写权限仍各自需要审批。

## 继续阅读

[开发说明](development.md)解释能力依赖与代码阅读；[核心参考](core-reference.md)保留 SDK／CLI 细节。事务与接口细节见[自动评测](auto-evaluation.md)、[管理 API](management-api.md)、[受控命令](controlled-mutations.md)、[只读 MCP](mcp-readonly.md)、[受控 MCP](mcp-controlled.md)和[静态回放](replay-preview.md)。

<!-- 本次更名更新 import、CLI、运行路径和历史审计链接；分层、事务、资格、引用与批准边界保留，没有执行代码验证或部署。 -->
