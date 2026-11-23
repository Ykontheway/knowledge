# 评测对照与使用导览

B3 已完成 V4 只读评测对照、手动阶段导览和有界轮询，并通过真实 HTTP 联调与完整回归。页面沿用 B2 的启动器与 B1 同源 GET，不新增管理接口，不重跑评测，不接受或替换 baseline。V2 版本快照视图和 Snapshot V1 保持不变。

## 沿用 B2 启动方式

首次运行在仓库根目录安装锁定依赖，并生成隔离验收库：

```bash
uv sync --locked --dev
(cd web && pnpm install --frozen-lockfile)
uv run python scripts/real_knowledge_acceptance.py \
  --output-dir .konwledge/real-knowledge-acceptance
```

确认 seed 验收输出 `status` 为 `passed`，将它实际输出的 `report.json` 父目录代入启动命令：

```bash
uv run python scripts/live_workbench.py \
  --database "<actual-seed-run>/knowledge.db" \
  --web-port 5175 --api-port 8015
```

打开 [评测对照](http://127.0.0.1:5175/#evaluation) 或 [使用导览](http://127.0.0.1:5175/#guide)。启动器只使用已有库，backend 启动仍可能执行已有 schema／FTS 初始化；HTTP 请求只读。临时 key 仅留在 backend 与 Vite Node 子进程环境，浏览器不带 key。dev proxy 仅支持严格 loopback 接线，preview／dist 不含代理，读取失败不回退 fixture。完整启动与安全说明见 [本机只读工作台](live-workbench.md)。

## 手动选择要比较的任务

路由格式如下，UUID 从真实任务列表获取，`offset` 是列表分页偏移：

```text
#evaluation?reference=UUID&candidate=UUID&offset=n
#guide?normal=UUID&fault=UUID&restore=UUID&offset=n
```

未选角色时可直接打开 `#evaluation` 或 `#guide`。评测对照只接受 `reference`、`candidate`、`offset`；导览只接受 `normal`、`fault`、`restore`、`offset`。UUID 非法、offset 非法、未知或重复 query、多余问号，以及这些入口下的未知子路由都会停在安全提示，不请求数据，不回显原始 hash。

参考任务和候选任务由用户指定。参考任务没有“已接受 baseline”的含义，页面也不会挑选最近一次 passed 作为基线。选择保存在 URL，翻页时保留，并按 ID 独立读取任务详情，不拿当前列表页的数据代替。手动刷新与有界观察共用刷新逻辑，刷新前记录列表头部，再重读当前列表页及按原 ID 选中的参考／候选。列表头部变化会提示用户，新增任务不会替换已选角色，旧失败任务仍保留。导览刷新也重读当前列表页及已选的正常／故障／恢复任务。跨请求分页不是冻结快照。

## 满足可比条件才显示 delta

前端使用真实 ManagementClient、运行时 DTO 校验与对照逻辑，展示持久化的聚合 metrics、checks、actual 和 threshold。对照前检查以下条件：

- 两侧为不同任务，均有完整 report。`passed` 必须与报告通过状态及空错误码一致；`failed` 必须是 `QUALITY_GATE_FAILED`，且报告未通过。`queued`／`running`／`blocked`／`superseded` 和运行错误不作质量对照。
- `dataset_id`、`dataset_version`、`dataset_hash` 完全相同，`config_fingerprint` 完全相同；必要指纹齐全，评测时间可解析，候选时间不能早于参考时间。
- 两侧 `case_count` 为正整数，answerable／no-answer 为非负整数，合计正确且两侧计数一致。`case_count=null` 不合法，不按零处理。
- 报告没有 degraded；指标取值、适用样本与 null 状态一致。缺少应有指标、越界数值或仅一侧为 null 都会阻断。
- 两侧都有 8 项默认 checks。按 `name + threshold` 唯一匹配，集合与门槛一致；若配置追加 `regression_gate`，也参与集合核对。`top_k_contract.actual` 必须是两侧一致的正整数，不能用布尔值或小数代替。

默认 checks 包含 `top_k_contract`、`recall_at_k`、`mean_reciprocal_rank`、`no_answer_accuracy`、`retrieval_evidence_citation_coverage`、`stale_or_retired_hits`、`stale_isolation_configuration`、`retrieval_degradation`。缺项、重复组合或门槛变化都不能输出 delta。质量门禁 failed 可以保留完整、可比的报告，不能仅因未通过就丢弃。

任何可比条件不满足，页面说明阻断原因，delta 不输出。报告里的 `null` 表示未评估，不归零；checks 的 passed／actual 仍按报告展示，不重新判门禁。合法 delta 为“候选减参考”，比例指标的差显示为百分点。例如 Recall 从 1 到 0.666667，差约为 −33.33 个百分点；不能写成相对百分比改善。MRR／nDCG 的百分比显示也不代表概率。

后端 `config_fingerprint` 对配置和数据集内容求 hash，配置包含 generation、enabled、mode、top_k、candidate_limit、rrf_k、quality_policy、baseline、regression_policy 等，仅排除 updated_at。前端不能从 hash 逆推出 mode，不因默认值就把任意任务标为 lexical；检索模式以对应验收记录为准。

`knowledge_fingerprint` 可以不同，这表示不同知识快照。不同 `evaluated_at` 的结果可用于观察，但不构成 same-time gate，也不能把 delta 自动归因到一次变更。页面不重算 U16 回归门禁，不接受 baseline，不将“可比”解释成“允许发布”。

## 指标只解释检索报告

| 字段 | 阅读口径 |
| --- | --- |
| `no_answer_accuracy` | 无答案检索用例中返回空结果的比例，没有这类用例时为未评估；不衡量 LLM 拒答是否正确 |
| `citation_coverage` | 检索证据中可验证引用的覆盖率，不证明生成答案正确或来源事实正确 |
| `stale_hits` | 当时 report 中非 active 命中的计数，包含陈旧或退役命中；不使用当前 `unit.status` 重算 |
| Recall／Precision／MRR／nDCG／Hit Rate | 对固定评测集的检索与排名汇总，不评估 LLM 答案质量 |

B1 只提供安全汇总，没有 case-level query 或 cases 明细。B3 因此不生成“失败问题列表”、逐用例诊断或根因判断。现有 job → revision → Diff → evidence 导航可以核查触发变更及确切历史原文，不能代替用例级失败证据。单元 `status` 仍是持久化当前缓存，不能当成任务 as-of。

## 导览阶段还要核验 CLI 实操

正常、故障、恢复阶段须人工选择。页面检查角色状态为 passed → `failed/QUALITY_GATE_FAILED` → passed，评测时间顺序成立，两组任务均满足可比条件，相邻知识指纹变化，故障与恢复任务有 trigger revision。满足后可进入 normal → fault、fault → restore 对照，并沿 B2 的 job → revision → Diff → evidence 核查历史证据。

只看到 pass／fail／pass 序列不足以证明真实故障注入。阶段检查通过仅表示所选任务满足导览条件，仍需对应的隔离库 CLI 更新与恢复记录。导览的展开、收起与下一步只改变展示，不执行命令，不拼接本机路径或原始 query，不写数据库。

## 观察由用户开启

评测对照页提供“观察新任务（5分钟）”。默认关闭，用户主动开启后每 10 秒刷新当前列表页及已选参考／候选，最多 5 分钟、30 次刷新。列表或选中任务读取中均视为 busy，跳过 tick，不延长原观察窗口。刷新按原 ID 保留选择，不自动切到新任务。

页面隐藏、page key／观察范围变化、读取错误或组件卸载都会停止；恢复可见或错误消失后不自动 resume，需用户重新开启。手动停止只阻止后续 tick，不承诺取消已经发出的 HTTP 请求。停止观察后仍可手动刷新。路由切换与 GET 读取继续使用 B2 的 Abort／sequence 防止旧响应覆盖，不能将它与“停止观察”混为一谈。

## 跑隔离 HTTP 联调验收

安装上述依赖后，从仓库根目录运行新 driver：

```bash
uv run python scripts/workbench_evaluation_acceptance.py
```

每次输出唯一 run ID，报告为 `.konwledge/workbench-evaluation-acceptance/<run-id>/report.json`，按其中 `artifacts` 查 seed report 和 frontend summary。不要把某次 ID 写死到通用命令。driver 在自己的运行目录生成 SQLite 和真实项目文档副本，正式 CLI 导入只写副本，不改仓库原始 docs 或用户业务库。

验收启动临时 loopback backend 与 Vite dev proxy，通过真实前端 client、运行时 DTO、comparison engine 和 jsdom UI 发真实 HTTP。副本再次 CLI import 后，检查新任务、UI 提示、原选择和旧失败报告。临时 secret 只注入服务子进程环境，不放命令参数或原始错误报告；命令 stdout／stderr 仅记录 hash。临时进程在 finally 中关闭。

2026-11-16 在最终页面修订后复跑成功，run ID 为 `20261116T042018921245Z-951ad2f7`。seed 正常 → 故障 → 恢复的 mean Recall 为 `1 → 0.666667 → 1`；normal → fault 的 `mean_recall_delta=-0.33333333333333337`，fault → restore 为 `+0.33333333333333337`。再次 CLI import 产生 passed 新任务，UI 新任务提示可见，selection 与旧 failure 保留，`children_stopped=true`。这是 jsdom UI 与真实 HTTP dev proxy 联调，不是浏览器整链点击或视觉验收。

## 回归命令与验收记录

```bash
uv run python scripts/export_management_schema.py --check
uv run pytest tests/test_workbench_evaluation_acceptance.py
cd web && pnpm verify
```

`pnpm verify` 已串联 typecheck → Snapshot 类型漂移 → `check:management` → Vitest → build。Python management schema 漂移检查仍单独执行；Snapshot V1、demo golden 和生成类型不变。

新增 Python driver 的 5 tests 已通过；comparison 31、poll 11、route／App 专项已通过，typecheck 与 build 已通过。普通 Vitest 未设置 acceptance 环境时，真实 HTTP integration 显式 skip 1；普通测试不会启动联调服务或访问验收库。这些专项有重叠，不能相加充当全量数量。

- 前端完整回归：179 项通过、1 项真实 HTTP integration 在默认环境跳过（10 个测试文件通过、1 个跳过）；类型检查、两种类型漂移检查和构建通过，`pnpm install --frozen-lockfile` 通过。真实 integration 已由隔离 driver 单独执行通过，不计入普通回归通过数量。
- Python 完整回归：1325 项通过、3 项跳过；ruff check／format、mypy 169 个源文件通过。Demo Snapshot 和管理 schema 漂移检查通过。
- 页面渲染检查：评测对照和导览两页通过，控制台为空，内容无外溢。首轮发现关键指标位于首屏以下，已前置“核心结果”并复查，真实 Recall 显示 100% → 66.67%、−33.33 个百分点；导览先显示阶段判定及对照链接。本次云端浏览器不能直达 loopback，真实 HTTP／jsdom UI 联调与页面渲染检查各有范围，未记作浏览器整链点击验收。
- 构建隔离检查：以临时测试密钥执行真实 build，并检查 dist 不含该密钥或测试后端地址，结果通过。约 552 kB 的 chunk 体积警告非阻断，未宣称完成加载性能优化。

B3 开发完成后，B4 受控变更写交互作为下一批另行设计，必须先落实真实身份／权限、幂等和操作确认，不自动开工。U22 MCP、release、PR、main 合并、tag、PyPI 和部署授权均未改变，见 [演示路线](integrated-demo-roadmap.md)。开发成果的交付流程是在 feature 分支提交并推送，版本仍未发布，不创建 PR、不合并 main，也不公开部署。

<!-- 文稿复核：已回读事实、行文和节奏。机械扫描中文半角标点 0、长破折号 0、编号／量词标题 0、对比句式 0、元话语 0。事实账本：前端 179／1（文件 10／1）、Python 1325／3、mypy 169 与最终验收一致；保留 null、百分点、指标范围、不同时间仅观察和不接受 baseline 的边界。HTTP 联调与页面渲染分别记录，B4 与公开发布未获自动授权。 -->
