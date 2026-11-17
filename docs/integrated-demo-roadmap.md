# 前后端一体化演示路线

目标是做出可以现场演示、结果可核查的 Knowledge CI 工作台：修改知识后，观众能看到版本变化、自动评测结果，以及支持判断的原始证据。本路线按已经落地的实现和验收衔接，不承诺未经估算的完成日期。

真实项目文档验收与 B1 只读管理 API 已完成。B2 完成 V3 生命周期与变更视图，B3 完成 V4 只读评测对照与手动导览；当前 feature 分支的 B4 受控变更交互也已完成实现并通过隔离验收，V2 静态演示继续保留。本轮收尾校验已完成：ruff、格式、mypy、management／mutation schema、Python 回归、`pnpm verify`、B4 driver 和发行包隔离 smoke 均通过；`pnpm verify` 结果为 352 passed、2 skipped，两个 skipped 是需要联调服务环境的 live acceptance 默认跳过。B4 的写入链路和恢复链路验收见 [受控变更工作台](controlled-mutations.md)。B5 MCP 未实现，没有公开 live 部署。版本仍为 `0.1.0` prepared，未创建 tag、PR、main 合并、GitHub Release 或 PyPI 发布。

## 真实文档验收结果

2026-11-13 的隔离运行使用现有 `docs/auto-evaluation.md` 和 `docs/acceptance.md`，导入 11 个知识单元。评测集在首次发布后冻结，共 4 条用例，包含多证据与无答案问题。正向变更、故障注入和恢复均通过正式 CLI 导入触发自动评测。故障时 Recall@5 从 1.0 降到 0.666667，恢复后回到 1.0；失败记录保留，重复导入不产生新任务。

这是项目文档的真实验收，覆盖本机 SQLite 与 lexical 检索。它不证明生产业务效果、模型语义理解、生成答案正确性或完整 Agent 任务成功率。该次验收使用默认绝对质量门禁，没有自动接受基线或宣称已完成 delta 回归。

B1 提供任务、revision、lineage、文档版本 Diff 与精确历史证据的只读契约。B2 接入实时页面，支持任务过滤、分页、手动刷新和 hash 导航。B3 在持久化汇总上增加人工参考／候选对照、指纹与完整性检查、指标解释及阶段导览，仍只读 B1 GET。B1 没有 case-level query／cases，B3 不造逐用例失败诊断。

B4 把“允许用户改一小步正文”接到同一条演示链路上：只对 `prepare_mutation_demo.py` 生成的隔离 demo 库、manifest allowlist 内 source 的当前正文开放更新。最新验收报告 [`.konwledge/mutation-demo/b239f388-6ef5-401f-879b-e43cf59fb68e/b4-acceptance-report.json`](../.konwledge/mutation-demo/b239f388-6ef5-401f-879b-e43cf59fb68e/b4-acceptance-report.json) 全部通过，全部 checks 为 true，frontend_update 与 frontend_recovery 均通过，三次变更产生的 command 与 jobs 恰好各 3；固定 config fingerprint 与 dataset 下任务链路为 `passed → failed → passed`，mean Recall 为 `1 → 0.6666667 → 1`。

## 产品特色围绕变更展开

工作台从一次知识变更进入，展示该次变更的 revision、关联任务和固定评测集。用户先回答“这次改动是否通过”，再查看相关的知识版本与引用。

- **结果能回到证据**：从评测任务进入版本 Diff，再定位知识单元与原文范围，显示来源、版本及持久化当前状态；该状态不冒充任务当时的 as-of。
- **失败与修复都有记录**：正常、故障、恢复任务由用户手动选择，再核验 CLI 实操。仅有 pass／fail／pass 序列不能证明故障注入，修复也不覆盖失败报告。
- **知识有时间边界**：查看确切文档版本及 lineage 历史，区分 stale、superseded 和退役内容，不用最新正文替换历史证据。
- **指标有适用范围**：dataset pin 与 config fingerprint 一致，报告完整且 checks 门槛相同，才输出 delta。比例差为百分点，null 保留为未评估；不同知识指纹或评测时刻仅作观察，不能自动因果归因。引用覆盖和无答案空检索都不证明 LLM 答案正确。
- **写入仍然可控**：B4 preview 绑定 source、旧 document、checksum、新 text hash、actor、scope、TTL 和 confirmation token；command 使用固定幂等键与请求绑定，在一个事务里写 command、revision 和 auto-evaluation outbox。评测失败不回滚知识，不自动补发不确定写请求。

视觉上保留现有 V2 基础，先保证每个状态能解释、每个数字有来源，再做动效和外观润色。

## 开发批次按验收衔接

| 批次 | 开发范围 | 交付验收 | 依赖与边界 |
| --- | --- | --- | --- |
| B1：只读数据契约，已完成 | 明确启用的管理 API、DTO 与契约测试 | 真实验收库返回 passed → failed → passed；任务定位 revision、版本与历史证据，HTTP 读取前后全表内容不变 | 保留 U18 协议、认证与本机边界，不新增写接口；backend 启动仍可能执行已有 schema／FTS 初始化 |
| B2：V3 生命周期视图，已完成 | 静态演示保留，接入 jobs、revision、document、lineage、Diff 与 exact evidence；过滤、分页、刷新和 hash 导航 | B2 历史结果为前端 126、Python 1320 passed／3 skipped；云端最短导航及管理只读摘要通过，详见工作台说明 | 依赖 B1；Snapshot V1 独立不改 golden；GET 不新增评测或更新 baseline，不回退 fixture；仅 dev loopback 代理，key 不交给浏览器 |
| B3：V4 评测导览，已完成 | 人工参考／候选聚合对照、指纹与报告完整性检查、指标口径、手动阶段导览和有界轮询 | 前端 179 passed／1 skipped（10 files passed／1 skipped），Python 1325 passed／3 skipped；类型、漂移、lint／格式、mypy、构建与锁定安装通过；默认跳过的真实 HTTP integration 另行通过，两页页面渲染检查通过 | 依赖 B2；同 dataset／config 与 checks 门槛才输出 delta，不重算 gate 或接受 baseline；没有 case-level 数据，不造逐用例诊断；不代表浏览器整链点击 |
| B4：受控变更交互，已完成实现 | 默认关闭的 `/v1/mutations`、独立 bearer mutation key、server 绑定 mutation actor、manifest allowlist 当前正文修改、`#changes` 预览／确认／提交／恢复 | `prepare_mutation_demo.py` 创建独占私有目录与 manifest；真实前端覆盖提交响应丢失、GET 恢复不重复写、凭据不持久化和重启后历史失败／Diff／证据回查；scope `b239f388-6ef5-401f-879b-e43cf59fb68e` 报告通过，command 与 jobs 各 3，任务链路 `passed → failed → passed` | 依赖 B3；必须显式给 `live_workbench.py --mutation-manifest --mutation-actor`；浏览器不提交文件路径或 SQL 凭据；不自动写、不自动重试不确定请求；评测失败不回滚知识 |
| B5：U22 MCP，未实现 | 在稳定查询服务上实现只读 search／get／context MCP，完成客户端验收后安排发布审核 | Agent 与工作台核对同一知识版本、证据和引用；演示可重置，公开数据通过检查 | MCP 不阻塞 B1～B4；发布、部署和生产数据使用需另行明确授权 |

各批次独立验证。开发成果的交付流程是在 feature 分支提交并推送，版本仍未发布。开发完成不等于发布授权，PR、main 合并、tag、GitHub Release、PyPI 和部署仍需另行确认。

## 本机演示接线

启动命令与安全说明见 [本机工作台](live-workbench.md)，B4 的写入契约与恢复边界见 [受控变更工作台](controlled-mutations.md)，HTTP 只读契约见 [只读管理 API](management-api.md)，B3 路由、对照条件与隔离验收见 [评测工作台](evaluation-workbench.md)。

B2/B3 继续先运行真实文档 seed 验收，再把唯一运行目录交给 `scripts/live_workbench.py`。B4 则先运行 `scripts/prepare_mutation_demo.py` 生成独占目录，再把实际输出的 `knowledge.db` 与 `mutation-manifest.json` 交给 `scripts/live_workbench.py --mutation-manifest --mutation-actor`。两条链路都不固定某台机器的路径或凭据。

Vite Node 与 backend 保存临时读 key；启用 B4 时，Vite Node 代理还会代发写 key。浏览器只发同源 GET／POST；preview／dist 不提供 dev proxy。B2 继续处理 loading、空列表、安全错误、读取重试和完整任务状态，null 不当作零；请求用 Abort 与 sequence 防止旧响应覆盖。B3 选择跨页保留，刷新新任务不替换选择。B4 预览在草稿变化后立即失效，恢复页按命令 ID 或原幂等键回查，不再隐式补写新请求。

有界观察默认关闭，用户主动开启后每 10 秒刷新，最多 5 分钟／30 次，busy 跳过不延长窗口；隐藏、page key 变化、读取错误或卸载会停止，不自动 resume。停止只影响后续 tick，不承诺取消已发 HTTP，手动刷新仍可用。B4 的“停止等待”也只是不再等浏览器这次响应，不表示后端提交已取消。

B2 历史浏览器验收只覆盖最短导航，没有逐项人工检查全部状态和移动端尺寸。B3 的 jsdom／真实 HTTP 联调与页面渲染检查各有范围；B4 的真实前端验收同样是隔离 Vite/API/UI/core 联调，不等于公开环境点击验收。

## 展示安全与后续能力

自动评测内部报告当前不保存 query 或源全文。B1 不暴露 SQLite 表、私密评测集、绝对路径或任意 payload，原文选段仅在认证后的 evidence 端点明确返回。未来若做用例级诊断，须另行设计隐私与授权契约；当前只提供触发变更与历史证据定位，不宣称根因判断。

B4 不接受浏览器文件路径、SQL 凭据、DSN 或任意写目标。浏览器只改正文，preview 不写核心知识表；只读 GET 不能创建 mutation 表或启动评测。确认 token 不进 URL 或持久化存储，结果不确定时也不自动发新写请求；恢复依赖身份隔离的命令 GET 与原幂等请求。

当前同步评测会增加变更耗时。现场演示继续使用单库、小规模评测，不把它包装成异步生产服务。后台调度、真实 embedding provider、向量／混合自动评测和 Agent 答案质量评测，分别补 provider 配置、隐私边界、成本与验收数据后再推进。B4 也没有新增候选批准写入、时效写入、LLM 答案评分或生产自治。

外部演示默认使用可公开的项目文档和独立副本；用户业务库只用于经授权的私密验收。公开部署前还需确认认证、数据脱敏、运行可恢复性和服务暴露边界。

<!-- 文稿复核：已回读事实、行文和节奏。机械扫描中文半角标点 0（排除 URL／路径／inline code 命中）、长破折号 0、编号／量词标题 0、对比句式 0、元话语 0。事实账本：B4 保持已实现，更新最新验收 scope b239f388-6ef5-401f-879b-e43cf59fb68e、command/jobs 各 3、352／2 前端、全量收尾校验已完成；未写入密钥、正文或内部技能内容。 -->
