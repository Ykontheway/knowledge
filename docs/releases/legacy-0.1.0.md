# 旧 0.1.0 发布审计

本页集中保留更名前的发布身份、源码提交、文件名、URL、SHA256 和运行记录。旧拼写只在此处作为历史事实出现，不是当前安装说明。`knowledge-ykforward==0.1.0` 仍是未发布候选，不能借用本页的发布结果、hash 或运行编号。

## 2026-11-23 PyPI 首次发布

- 首次发布 Alpha 包 `konwledge==0.1.0`：[PyPI 页面](https://pypi.org/project/konwledge/0.1.0/)。当时原名可用，未追加后缀。
- 发行源码固定为 `3768ceba0719cd21916ea80ae175151a92d4ded1`，上传流程提交为 `7e263833b4f2a316c87f4091306ea6def26ba865`。当时没有合并或推送 `main`、创建 tag、创建 GitHub Release，也没有更新在线预览。
- [预检运行 45151862632](https://github.com/Ykontheway/konwledge/actions/runs/45151862632) 的检查全部通过，上传任务跳过；[正式发布运行 45154046544](https://github.com/Ykontheway/konwledge/actions/runs/45154046544) 的 8 个任务全部通过，包括 `UploadSuccess`。
- 已独立核对正式 PyPI 索引 JSON、元数据及下载字节的 SHA256：

| 原始文件名 | SHA256 | 原始下载地址 |
| --- | --- | --- |
| `konwledge-0.1.0-py3-none-any.whl` | `801e74af65419db1877d16c87cd2a53c5f67fcae4927fbba59c19a58ed950f17` | [PyPI 文件列表](https://pypi.org/project/konwledge/0.1.0/#files) |
| `konwledge-0.1.0.tar.gz` | `2e9dd69ff48582f1117befc33328ef38324a185f3a3008bc263e9ed8e08f46ee` | [PyPI 文件列表](https://pypi.org/project/konwledge/0.1.0/#files) |

原文未记录 files.pythonhosted.org 的具体 URL，本次不补造下载地址。历史本机构建位置包括 `release-verification/build/konwledge-0.1.0-py3-none-any.whl`、`release-verification/build/konwledge-0.1.0.tar.gz`、`dist/konwledge-0.1.0-py3-none-any.whl`、`dist/konwledge-0.1.0.tar.gz` 及 `dist/u18-verification/build/` 下同名文件；本地同名文件不能仅凭名称认定为上述已发布字节。

- 当时本地全量测试为 2590 通过、7 跳过，耗时 583.21 秒。远端三组 Python 检查通过；匿名无法读取完整日志，不补写远端测试数量。
- 发布后从正式 PyPI 在仓库外的新环境中分别安装 wheel 和 `--no-binary konwledge` sdist，确认导入来自 `site-packages`，`knowledge`、`konwledge`、`python -m konwledge` 及独立 `konwledge-mcp` 属于旧入口身份，CLI 别名输出 `0.1.0`。核心验收覆盖 9 项检查、8 个步骤、6 个评测用例和 42 项门禁检查；Replay 包含 3 个 job、16 个 diff。
- 独立 MCP 安装及真实 stdio 验收通过，覆盖 5 个工具和 15 项检查，SDK 为 `1.30`；`pip check` 通过。
- 发布后安装验收使用 Linux、Python 3.11.15、无缓存的隔离环境。MCP 首次安装超时未算通过，另建环境重试后通过；`[api]`、`[tokens]`、`[postgres]`、`[lancedb]` 的发布后安装未复跑，Windows 与 macOS 未验收。包发布不等于部署 GUI 或在线服务。
- 旧发布使用 `PYPI_API_TOKEN`，仅由 GitHub 上传步骤通过 `UV_PUBLISH_TOKEN` 消费，未检查明文或权限范围。如首次用了账户级 token，应换项目级 token 并撤销原 token；后续优先 Trusted Publishing。不要重建不同字节覆盖旧 `0.1.0`。

## 发布前状态快照

2026-11-12 的原始准备说明如下，保留当时的未发布时态：

> As of 2026-11-12, v0.1.0 is prepared as an alpha release candidate in source metadata. U14–U16 acceptance, automatic knowledge-change evaluation, and U18–U20 remain Unreleased additions and do not change the version. This work does not merge `main`, create a pull request, tag a commit, create a GitHub Release, publish to PyPI, or deploy/verify a public site. Local artifacts produced during verification are not a published release.
>
> No installation instructions should claim that `konwledge==0.1.0` is available from PyPI until the package index confirms it.

旧元数据准备检查对应 `src/konwledge/__init__.py`、`konwledge.__version__`、`uv.lock` 的 editable `konwledge` 记录；当时 `knowledge` 与 `konwledge` 入口都指向 `konwledge.cli:main`。旧校验命令包括 `uv run pytest --cov=konwledge --cov-report=term-missing`。这些仅说明旧身份，当前维护检查见 [发布维护说明](../releasing.md)。

## 发布前开发记录

以下内容来自原 CHANGELOG，记录首次正式发布前各阶段的开发与验收。保留历史数字、编号、未发布状态和旧路径，不给旧成果换发行身份。文中的“本次”“本轮”“下一批”“当前”均指对应阶段；不是更名后的重测或新发布结论。

### 产品定位与开发逻辑整理

- README 按知识生命周期、资格检索、精确证据、质量门禁与受控接口组织，详细 SDK／CLI 参考移入 `docs/core-reference.md`。新增 `docs/development.md`，按能力依赖和评审风险介绍开发逻辑；架构文档覆盖自动评测、工作台、MCP 和静态回放。
- 页面与 CI 使用“版本快照”“使用导览”“隔离副本”和 Knowledge CI 工作台名称。兼容命令、协议、路径、role／actor、固定快照与回放数据保持不变；没有扩大写权限或改动核心状态机。
- 记录 2026-11-23 首次静态只读预览发布及线上核验。发布提交为 `2ed4f9acda77118c582be709a681d51b34dffb56`，当时源码文案变更不自动更新线上版本；静态预览不代表实时后端或生产写服务上线。
- pytest 显式配置仓库根目录导入路径，使测试辅助模块 `scripts` 不再依赖本机 `PYTHONPATH`。首次 PR CI 的三组 Python 检查暴露收集错误，清除环境变量后本机已复现；不将脚本加入运行包，不修改门禁或跳过条件。
- Python quality CI 显式设置 `NO_COLOR=1` 与 `TERM=dumb`，使 pytest 和发行 smoke 的 CLI 帮助／诊断输出确定且不带颜色；保留原有断言与 `GITHUB_ACTIONS`。
- 修复工作台报告读取在普通 OS 身份下的权限错误分类：`PermissionError` 返回 `file_invalid`，不再归为 `json_invalid`。
- 包版本保持 `0.1.0` prepared alpha，未正式发行。后续条目保留各 U／B 阶段的历史范围与验收数字，不改写为本次验证结果。

### 静态回放导出与预览准备

- 回放导出、页面整合和独立 preview 构建已完成实现，仍归入 Unreleased，版本保持 `0.1.0` prepared；当轮只准备发布预览，不执行 Actions、公开部署、PR／main、tag、Release 或 PyPI 发布。
- 新增 `src/konwledge/replay/{bundle,corpus,files,producer}.py` 与 `scripts/export_replay.py --output FILE`／`--check --output FILE`。只在工具自建 `.konwledge/replay/<UUID>` 私有 scope 生成固定可公开合成语料，经正式 SDK 发布与自动评测 outbox 产生真实的 `passed → failed → passed` 任务；同一 dataset／config、固定 4 条 cases，Recall 为 `1 → 2/3 → 1`。质量失败 `QUALITY_GATE_FAILED` 不回滚已提交知识，不声明业务原因或生成答案质量。
- `web/public/replay.json` 使用严格 B1 DTO，含 3 jobs、16 revisions、4 documents、3 lineages、12 units、12 evidence、16 diffs。嵌套 Page 保留，`limit=100`、`offset=0`、`total=items.length`；公开证据仅固定安全白名单，不提供业务原文自动脱敏或通用业务库 export。
- replay 路由保留分页与 mode，坏 bundle 报错且无 live fallback；合法 nullable `navigation.content_hash` 的后置误拒绝已修复，前置 schema 约束不变。
- 普通 `pnpm verify` 保留 Snapshot V1／live／B4；独立 preview 输出 `dist-preview`，菜单及手输路由阻断实时／写入口。Pages workflow 在该阶段改为手动 `workflow_dispatch`，`publish` 默认 false，prepare 检查提交的 JSON 并上传 `replay-preview`，显式 true 才部署；默认分支 dispatch、所选 ref 和 Pages 权限须另核对。
- 当轮 Python 全量 2540 passed／7 skipped、前端 529 passed／2 skipped、回放专项 91 passed；17 个资源、59 项 HTTP 子路径检查与 6 次静态呈现检查通过，真实 wheel／sdist 隔离验证通过。具体静态发布记录见下节。

### B6 受控 MCP

- B6 当时已完成并验证，版本为 `0.1.0` prepared。Linux 主验收为 36 成功、17 拒绝、61 响应；3 次正文提交产生 3 个 command 与 3 个 job，`passed → failed → passed`，独立 PTY 批准 3 次。默认五工具只读，知识、command、outbox 与批准审计零写入。该阶段未创建 PR、合并 main、tag、发布 PyPI 或公开部署。
- 显式 `--controlled --mutation-manifest MANIFEST --actor demo-editor --demo-root ROOT` 后增加五工具，共十个；只限 B4 prepare 私有 sandbox 的 allowlist 当前正文，不开放候选批准、retire／remove、任意导入或 SQL 写入。
- `knowledge mcp approve` 独立 TTY 审阅 JSON 转义 Diff，要求完整短语，无 `--yes`／`--confirmed`。grant 最长 120 秒、不晚于 preview 300 秒，绑定身份／scope／键／内容／指纹；apply 不接受布尔确认。Linux PTY／SDK 已测，macOS／Windows 未测，不宣称 SSO／RBAC 或密码学人类证明。
- 受控启动仅新增 `mcp_approvals`，不升级核心／回填 FTS。get 不写，preview／approve 只写审计；知识／FTS／command／outbox／grant 消费同事务，质量失败仍是 `committed=true`、`isError=false`。未知结果仅原键回查。
- sdist 增补受控 smoke／测试及文档。参数 128 KiB、正文 64 KiB、完整 CallToolResult 2 MiB，不含 JSON-RPC wrapper，不限制 wire／峰值内存；可选 SDK `mcp>=1.30.0,<2`，无新增 FastAPI 依赖。

### B5／U22 只读 MCP

- 当时 Unreleased、`0.1.0` prepared。Linux 真实 SDK session、完整回归与隔离安装通过，未创建 MR／PR、合并 main、tag、Release／PyPI 或公开部署。
- 当时两个入口为 `knowledge mcp serve --database FILE` 与 `konwledge-mcp --database FILE`。可选 SDK `mcp>=1.30.0,<2`，核心 `pydantic>=2.7,<3` 未收紧；baseline SDK 1.30.0，不承诺旧 SDK 1.2／1.20。缺 extra 安全失败，不接触数据库。
- 固定 lexical／active，严格输入，独立 `mode=ro`／`query_only`／rollback，不建库、升级、回填 FTS、写 outbox。字符／块数预算不接受 token。
- 四项 ToolAnnotations、outputSchema、structuredContent／JSON text 与完整 2 MiB 响应已验证；不含 JSON-RPC 外层，超限 `413/mcp_response_too_large`，非法 Unicode／浮点固定安全 `500`。
- MCP 的 72 项底层发行检查独立确认，不混入 B-R2 既有 82 项投影；live demo 停止记 `stopped`，macOS 未测。
- 修复旧 lease 测试时钟早于实际 mutation 发布时间的问题，仅改测试时钟；49 项及相关 2 项重复 5 轮通过，生产 threshold 未改。

### B-R2 统一入口

- `scripts/workbench.py` 的 `list`／`demo`／`accept` 已完成，demo 默认 readonly，controlled 显式 actor，prepare-only 不启动；accept 默认 readonly，full 加 mutations，with-distribution 加 smoke；不接受外部 database／manifest／DSN／key。
- 历史 readonly [7014a5a8-5dda-4406-b159-592d5620ab0b](../../.konwledge/workbench/7014a5a8-5dda-4406-b159-592d5620ab0b/summary.json) 与 full [ef8c8448-e402-4951-8324-44579ce0045b](../../.konwledge/workbench/ef8c8448-e402-4951-8324-44579ce0045b/summary.json) 均通过。full 各组件 passed、exit 0、checks_failed 0、cleanup_verified true，distribution checks_passed 82，wheel／sdist 均通过。
- readonly demo [9beb853b-909a-4165-86b7-5b59574baac7](../../.konwledge/workbench/9beb853b-909a-4165-86b7-5b59574baac7/summary.json) 与 controlled demo [17cf59ec-b616-47ee-8f52-5b79ea8824f4](../../.konwledge/workbench/17cf59ec-b616-47ee-8f52-5b79ea8824f4/summary.json) 均 Ctrl+C、stopped、launcher exit 130、清理通过，不计为评测成功。
- readonly GET 的 backend B4 session 返回 404，未启用的 Vite proxy 返回 503；seed 已有 3 jobs，不新增 preview／command／jobs。controlled GET 确认 actor demo-editor、role demo_editor、绑定与 allowlist 一致，无浏览器裸 key，缺 key 401、错 Origin 403。
- 较早 full [2297462f-6e76-4207-abc0-8d4b8e625ba3](../../.konwledge/workbench/2297462f-6e76-4207-abc0-8d4b8e625ba3/summary.json) 通过；首次 full [559fcce3-a270-4739-80e8-ebe3598bd044](../../.konwledge/workbench/559fcce3-a270-4739-80e8-ebe3598bd044/summary.json) 因 report_invalid 失败。后续仅收紧 summary 投影，没有放宽 driver／安全校验。
- 仅支持 Linux /proc、subreaper、pidfd；缺能力 fail-closed cleanup_unknown。最终 Ruff 通过、format 218 files、mypy 192 sources、schema 不变、前端 430 passed／2 skipped、Python 1902 passed／5 skipped；3 个既有可选 skip、2 个默认 live skip，显式 live 2 passed（41.21s）。WORKBENCH_SDIST_FILES 8 个必需文件已纳入。

### B-R1 机械共享重构

- 两个 TS shared reader／validation 与 scripts/schema_utils.py 接入，领域 error／headers／UTF-8／DTO／limits／GET／写边界不变，不合并 Auth／session／StorageBase、B4 hooks、B3 算法或 driver。
- SCHEMA_SDIST_FILES 纳入共享脚本和测试，缺失拒绝。隔离验证 [旧目录](../../.konwledge/b-r1-distribution-verified) wheel／sdist 通过、未发布。
- Ruff 通过、format 210 files、mypy 185 sources、两份 schema 字节不变；Python 1515 passed／3 skipped、前端 430 passed／2 skipped。两个 live 默认跳过，584.38 kB chunk 非阻断。
- 完整 B4 driver [c2c9b890-e706-4362-a7fe-e4675edef052](../../.konwledge/mutation-demo/c2c9b890-e706-4362-a7fe-e4675edef052/b4-acceptance-report.json) 通过、children_stopped true，command／jobs 各 3，Recall 1 → 2/3 → 1，GET 恢复不重复写，历史失败／Diff／证据保留。

### B4 受控变更

- 默认关闭 /v1/mutations，独立 mutation key，服务端绑定 actor，浏览器无 key。prepare 仅新建私有副本、隔离 knowledge.db、manifest、report；allowlist 当前正文，拒绝任意业务库。
- live_workbench 显式 manifest／actor，#changes 预览和人工确认提交，command 链接只 GET 恢复。preview 绑定 source／document／checksums／actor／scope／TTL／token；BEGIN IMMEDIATE 校验并原子提交 command／revision／outbox，评测失败不回滚。
- 拒绝浏览器路径、SQL 凭据、DSN、任意目标，不自动写或重试不确定请求；GET 不建表／不评测。仅原 payload／同键可显式重放。
- 历史 driver [b239f388-6ef5-401f-879b-e43cf59fb68e](../../.konwledge/mutation-demo/b239f388-6ef5-401f-879b-e43cf59fb68e/b4-acceptance-report.json) 全通过，command／jobs 各 3，Recall 1 → 0.6666667 → 1，响应丢失 GET 恢复、凭据不持久化、重启后历史回查，children_stopped true。
- Ruff 通过、format 208 files、mypy 183 sources、schema 不变、Python 1495 passed／3 skipped、前端 352 passed／2 skipped；2 个 live 默认跳过。旧隔离目录 `.konwledge/b4-final-distribution-verified` wheel／sdist 通过、未发布／部署；584.87 kB chunk 非阻断。

### B3 评测对照

- V4 只读对照、手动导览，B1 同源 GET，严格 UUID／分页／query／路由，选择保留，新任务不替换。dataset／config／checks／threshold／top_k／null／degraded 严格可比，仅显示 delta，不重算 U16 gate 或接受 baseline；固定 8 checks。
- 导览还需 CLI 实操，pass／fail／pass 不自动当作真实故障或因果，B1 无 case-level query／cases，不造业务原因，引用覆盖不证明 LLM 答案正确。
- 主动观察每 10 秒、最多 5 分钟／30 次，busy 跳过不延长；隐藏／路由／错误／卸载停止，不自动 resume，不承诺取消已发 HTTP。
- 2026-11-16 最后 run `20261116T042018921245Z-951ad2f7` 通过，真实 HTTP／jsdom UI，Recall 1 → 0.666667 → 1，CLI 新任务提示与旧选择／失败保留，children_stopped true。
- 前端 179 passed／1 skipped（10 files／1 skipped），Python 1325 passed／3 skipped，mypy 169 sources，schema／Snapshot 不变。专项不相加，真实 integration 独立执行。
- 两页渲染检查通过，关键 Recall 和阶段结论前置，无控制台错误；临时密钥 build 未泄露。云端浏览器不能直达 loopback，不称整链点击验收；约 552 kB chunk 非阻断。
- B4 当时列下一批，MCP／release／PR／main／tag／PyPI／部署仍需授权。

### B2 本机只读工作台

- 完成 V3 真实任务／revision／document／lineage／Diff／evidence 导航与状态过滤、分页刷新；loading／空／安全错误／重试，Abort／sequence 防覆盖，无 fixture fallback，unit.status 不冒充 as-of。
- 独立 management schema／类型／Ajv／UUID／href／Unicode code point 校验，Snapshot V1 不变。Vite dev loopback GET proxy，缺配置 503，key 仅 Node／backend，preview／dist 无 proxy，无公开 live。
- launcher 等待 health、只清理自己子进程；当时 backend 允许 additive schema／FTS 初始化，请求只读，不评测／改 baseline。
- 前端 126 tests、Python 1320 passed／3 skipped、Ruff／mypy／漂移通过。云端浏览器仅最短失败任务到旧证据导航，19 表／137 行摘要不变。
- 当时 B3 下一批、V4 延后，B4／B5 尚未实现，0.1.0 prepared，无 tag／PR／main／PyPI／公开部署。

### B1 只读管理 API

- 显式启用、认证 GET，分页任务、revision、lineage、Diff、exact evidence；DTO frozen／extra forbid，白名单投影。
- knowledge serve --enable-management 与 create_app(enable_management=True) 要求 key，默认不挂载端点，保留 U18／V1／loopback 边界。
- 独立 SQLite ro，不写库／评测，历史证据验证版本／范围／hash，缺失／损坏／跨源／写方法安全拒绝。
- 增加管理安全接线、真实 HTTP 导航和安装 smoke，当时未改前端／发布／部署。

### 后端验收、自动评测与真实文档

- U14 可选 tokens／tiktoken，保留字符预算／ContextPacket／冻结 Demo。
- U15 独立 30 条公开基准、真实 lifecycle 和旧／过期干扰，不替换 6 条 Demo／人工基线。
- U16 TopK 5、Recall ≥ 0.80、MRR ≥ 0.65、引用覆盖 100%、过期命中 0、无答案准确率；1,000 active 单元、30 次采样、P95 ≤ 1.5 秒本机性能门槛。
- 默认关闭 auto-evaluation，同事务 outbox、提交后同步、固定 dataset／config／knowledge 指纹，安全错误／lease／retry，不自动改基线／回滚。quality failed 保留 stdout、stderr 提示、退出 3。
- real_knowledge_acceptance.py 用真实项目文档隔离副本、固定评测集、正式 CLI 完成正向／失败／恢复／幂等，新增 3 tests，当时不改生产服务、不做前端／管理接口／部署。

### U20 数据库结构

- SQLite／PostgreSQL schema-only 捕获，SQLite ro／authorizer／PRAGMA／超时，PostgreSQL psycopg 3／只读 repeatable-read／timeouts。测试仅合成 SQLite 或 CI 临时 PostgreSQL，不访问用户库／凭据。
- 不可变 snapshot／规范 hash／稳定 lineage／检索物化／diff，幂等未变、恢复复用 document 追加版本；capture-postgres 只取 --dsn-env，不输出 DSN／用户名／SQL／驱动原错。
- 可选 postgres，仅专用 CI PostgreSQL 16／17 安装驱动，核心不含 psycopg。隔离 smoke 验证 schema 变化、业务行不进入 snapshot、只读列表、API 当前字段，V1 DATABASE 明确失败，golden 不改。
- 旧临时测试 DSN 为 `postgresql+psycopg://konwledge_test:konwledge_test@127.0.0.1:5432/konwledge_test`，仅 CI dummy 值。角色最小只读权限，注释／DDL 等可敏感，不入公开资产。

### U19 对话

- 不可变对话 schema，10 MiB／UTF-8／重复 key 严格检查，连续版本／规范导出／幂等。候选仅 user／assistant 显式事实／决策标记，不读 system／tool、不调用 LLM、不自动判真。
- 人工批准／拒绝终态审计，批准原子物化知识，拒绝不写知识，重导保持决定，反向终态退出 2。pending／rejected 不检索，approved 可检索。
- conversation／candidate CLI stdin／latest／过滤／JSON／安全覆盖，隔离 API 查询只批准内容，无写；合成 conversation-demo.json，不公开原聊天／库。
- V1 来源类型冻结 url／file／repository／manual，conversation 保留真实类型，V1 明确失败，不重生成 golden／前端；当时无新依赖／API／前端／发布。

### U18 HTTP

- 可选 api（FastAPI／Uvicorn）loopback 上下文 API、health／models／ContextPacket／OpenAI chat completion 子集，无推理／usage。
- knowledge serve 既有文件、mode=rw、端口 1..65535、KNOWLEDGE_API_KEY、禁 access log。当时启动允许 additive schema／FTS；这是历史行为说明，不替代当前 serve 约束。
- dev 加 API／HTTPX／OpenAI／LangChain SDK，核心不变。离线 SDK 验证 packet、鉴权／严格错误／只读请求，隔离 core-only 后同一 wheel／sdist api ASGI smoke。
- 当时 0.1.0 未提升、无前端／部署／发布，CI PR／main，不是 feature push。

### 2026-11-11 prepared 候选

- 当时 v0.1.0 仅完成本地 readiness，未 main merge、tag、GitHub Release、PyPI 或公开 demo 部署。
- U01–U16 已有 UTF-8／规范化／SHA256／split／exact spans／幂等、SQLite 显式事务／FTS／不可变版本／lineage／as-of、TTL／冲突／人工审核、eligibility-first lexical／vector／hybrid／RRF、whole-unit 上下文／稳定 UUID5 citations／预算、不可变评测／baseline／fail-closed gates、hash embedding／Memory／可选 LanceDB、冻结 Demo／Snapshot V1／V2／CI。
- U17 同步 pyproject／konwledge.__version__／uv.lock 的 0.1.0 alpha、Python 3.11+，lazy facade／py.typed、隔离 wheel／sdist／entrypoint／资源／CLI／检索／评测／门禁检查，以及架构／贡献／发布／安装文档。
- 当时限制：hash embedding 非语义生产质量，评测不证明源事实／生成答案正确，Konwledge 不调用 LLM；O(N) 单机 exact vector 非大规模 ANN；SQLite 无破坏性迁移编排／HA／多租户／SLA；可复现需控制 corpus／时间／provider，不冻结全部 corpus／backend；原始报告可含源文／locator／路径，compact baseline 仍含作者 query／ID。
- 前端 V2 是 2026-11-06 当时范围，后续 B2／B3／B4／B5 的增量记录分别保留，公开 live 未部署，workflow 不证明上线。

## 静态回放发布与验收

2026-11-23 已公开的旧地址为 [Knowledge CI 工作台](https://ykontheway.github.io/konwledge/#replay/guide)，旧根地址为 `https://ykontheway.github.io/konwledge/`。发布源码提交 [2ed4f9acda77118c582be709a681d51b34dffb56](https://github.com/Ykontheway/konwledge/commit/2ed4f9acda77118c582be709a681d51b34dffb56)，对应 [Actions 45105672969](https://github.com/Ykontheway/konwledge/actions/runs/45105672969)。首次 prepare 通过，publish 被仅允许 main 的 environment 规则拒绝；保留 main 规则，只加入当时 feature 分支后重跑失败的 publish 成功，没有合并或修改 main。

当时线上根页面与 17 个资源均返回 200，与验收构建逐字节一致；导览、评测对照和手输 #changes 阻断页呈现正常，捕获控制台为空，管理／写 API 返回 404。范围仅静态加载与呈现，非整链交互、移动端或生产服务验收。

| 历史回放文件元数据 | 值 |
| --- | --- |
| 文件 | `web/public/replay.json` |
| schema／mode | `1`／`replay` |
| generated_at | `2026-11-20T08:32:21.682543Z` |
| 大小 | `263215` bytes |
| SHA256 | `9cd0af3875b768b3a50326fc386452fcb88bf11af8ad58ef64f0499fc4a35d05` |
| jobs／revisions／documents | `3`／`16`／`4` |
| lineages／units／evidence／diffs | `3`／`12`／`12`／`16` |

这是旧固定文件的身份，不能给新导出复用；新 scope 的 UUID 与时间会变化。历史三阶段固定 4 cases、相同 dataset／config，Recall `1 → 2/3 → 1`，failed 不回滚知识。

发布前历史验收为 Python 2540 passed／7 skipped（415.83 秒）；MCP／回放发行与导出专项 350 passed（18.21 秒）；Ruff 248 files、mypy 219 sources；两份 schema 字节不变；前端 529 passed／2 skipped，回放专项 91 passed；17 资源／263215 bytes，wheel／sdist 各 3 jobs／16 diffs；本机静态 HTTP 59 项，根路径及 `/konwledge/` 子路径字节一致，API 404、POST 405；静态呈现 6 次，进程清理完成。Python 7 skip 与前端 2 skip 保留各自可选／live 范围，约 606 kB chunk 非阻断，未做移动端／真实浏览器交互；首轮两项旧发行编排测试失败后仅适配 replay_core 摘要，不放宽发行校验。

原本机证据不随 Git 提交：[acceptance-report.json](../../.konwledge/byproducts/replay-preview/acceptance-report.json)、[http-checks.json](../../.konwledge/byproducts/replay-preview/http-checks.json)、[html_vision.original.log](../../.konwledge/byproducts/replay-preview/html_vision.original.log)、[发行目录](../../.konwledge/replay-preview-final-distribution)。本次不移动这些文件，也不将历史 URL 换成新仓库地址来伪造重新部署。

## 真实文档运行身份

2026-11-13 的执行源码提交为 `acd1c2adf1eba3d29cde2413cd8feecc1d3428fc`，成功运行目录 `.konwledge/real-knowledge-acceptance/20261113T062525019181Z-11d25751/`，[report.json](../../.konwledge/real-knowledge-acceptance/20261113T062525019181Z-11d25751/report.json)。使用原 `docs/auto-evaluation.md` 与 `docs/acceptance.md` 副本，2 文档／11 单元，冻结 4 cases（3 有答案、1 无答案），dataset v1 hash `1267746d99bf9114891b7667762d25056c6932a110b55db61093eb13df906787`。

初始／正向／故障／恢复 Recall 与 MRR 为 `1.0／1.0／0.666667／1.0`，引用覆盖和无答案准确率均 1.0；正向／恢复 Precision@5 0.266667，故障 0.2，不声称全部满分。三次自动变更退出 `0／3／0`，stale_hits 0、degraded false，QUALITY_GATE_FAILED 仍提交；任务数恢复后幂等 `3 → 3`，保留失败／旧版本。新增 3 tests 当时通过。调试失败运行仍在同根目录，未覆盖；revision 读取修复为 repository，不改生产服务。

B3 最终历史运行 ID `20261116T042018921245Z-951ad2f7` 位于 `.konwledge/workbench-evaluation-acceptance/20261116T042018921245Z-951ad2f7/`；Recall `1 → 0.666667 → 1`，delta `-0.33333333333333337／+0.33333333333333337`，新任务提示和旧选择／失败保留，children_stopped true。没有真实浏览器整链点击结论。

## B5 原始隔离发行记录

历史 full [be248fe7-e37c-4b6a-a0cf-d697a927bd8a](../../.konwledge/workbench/be248fe7-e37c-4b6a-a0cf-d697a927bd8a/summary.json) 各组件 passed、exit 0、checks_failed 0、cleanup_verified true、timed_out false。82 项仅 B-R2 投影，不包含 MCP。

原始 [wheel summary](../../.konwledge/workbench/be248fe7-e37c-4b6a-a0cf-d697a927bd8a/distribution/7d01e2b1-2eec-46b4-884d-7c6a4173b973/driver/wheel-smoke-summary.json) 与 [sdist summary](../../.konwledge/workbench/be248fe7-e37c-4b6a-a0cf-d697a927bd8a/distribution/7d01e2b1-2eec-46b4-884d-7c6a4173b973/driver/sdist-smoke-summary.json) 各 core-only 6、extra/default 15、min1.30 15，共 72 MCP 检查。core 无 SDK，Pydantic 2.14.3；extra／min SDK 1.30.0、Pydantic 2.14.3，无人工 pin；每 extra lane 3 session、18 成功、39 拒绝、63 响应，数据库 SHA 与 2 文件不变，EOF 清理通过。

历史主环境 SDK 1.30.0／Pydantic 2.14.1；Ruff 227 files、mypy 200 sources、Python 2131 passed／7 skipped（322.01s）、前端 430 passed／2 skipped、MCP protocol 36 passed、定向 343 passed／2 skipped，专项不相加。显式 Linux live 2 passed（40.66s）；7 skips 为 PostgreSQL 1、LanceDB 2、内存 file-ro／WAL 2、默认 workbench live 2。

旧 live demo [readonly 84efd3b9-8553-449d-8764-9d8ae4787db5](../../.konwledge/workbench/84efd3b9-8553-449d-8764-9d8ae4787db5/summary.json) 与 [controlled d466d8fe-1dc8-4b70-8eab-54edbfdf4693](../../.konwledge/workbench/d466d8fe-1dc8-4b70-8eab-54edbfdf4693/summary.json) 均 stopped、exit 130、清理通过，不计 passed。旧 SDK 1.2／1.20 与当时 Pydantic 缺私有 eval_type_backport，补依赖仍未解决，未承诺支持。

## B6 原始隔离发行记录

历史全量 Python 2439 passed／7 skipped（401.46 秒）、Ruff 238 files、mypy 210 sources、前端 430 passed／2 skipped、两份 schema 不变、显式 Linux live 2 passed（45.10 秒）。当时全量环境及 full 联调为 SDK 1.30.0／Pydantic 2.14.3。

[完整工作台 8f935dcb-ec6b-4a67-8b56-a02d8c970ce4](../../.konwledge/workbench/8f935dcb-ec6b-4a67-8b56-a02d8c970ce4/summary.json)，[wheel](../../.konwledge/workbench/8f935dcb-ec6b-4a67-8b56-a02d8c970ce4/distribution/652e52a2-0561-4279-8e7e-5152062332a7/driver/wheel-smoke-summary.json)／[sdist](../../.konwledge/workbench/8f935dcb-ec6b-4a67-8b56-a02d8c970ce4/distribution/652e52a2-0561-4279-8e7e-5152062332a7/driver/sdist-smoke-summary.json) 各受控 lane 17 检查，十工具／4 cases／36 成功／17 拒绝／61 响应／5 session／3 PTY 批准，3 command／job／grant 消费。旧 core-only／default／min lanes 也通过，不把 82 投影当作 MCP 数量。

[回归与进程审计](../../.konwledge/byproducts/b6-final-regression-20261118/regression-audit.json)，旧 live [readonly 1d01488c-5d7e-4889-a895-52de88faa83f](../../.konwledge/workbench/1d01488c-5d7e-4889-a895-52de88faa83f/summary.json)／[controlled 79b9c0c8-9d1e-463a-b726-c14260519f44](../../.konwledge/workbench/79b9c0c8-9d1e-463a-b726-c14260519f44/summary.json) 均 stopped／130／清理通过。

首轮失败 `.konwledge/b6-distribution-first-verification/failure-summary.json` 保留；测试 TTL 时钟修复后第二轮 `.konwledge/b6-distribution-second-verification` 不覆盖失败。收尾原命令为 `uv run --frozen --extra mcp python scripts/verify_distribution.py --output-dir .konwledge/b6-closeout-distribution-verified`，[wheel](../../.konwledge/b6-closeout-distribution-verified/wheel-smoke-summary.json)／[sdist](../../.konwledge/b6-closeout-distribution-verified/sdist-smoke-summary.json) 受控 lane 各 17 通过，旧 lanes 也通过，实际 SDK 1.30.0／Pydantic 2.14.4，无人工 pin。两种依赖环境分别保留，不混写。

以上全部是更名前历史结果。更名后需新的测试、构建、审批及索引验收，不复用旧 session／receipt 来证明新候选。
