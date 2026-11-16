# 本机只读工作台

B2 已完成 V3 生命周期与变更视图，B3 已完成 V4 只读评测对照与手动导览，并通过完整回归、隔离 HTTP／jsdom UI 联调及两页页面渲染检查。现有 React／Vite／Tailwind 静态演示保留，实时工作台通过 B1 管理 API 读取已有数据库。两种数据来源明确区分；实时读取失败会显示错误，不自动回退到 fixture。当前没有公开 live 部署，版本仍为 `0.1.0` prepared，未创建 tag、PR、main 合并或 PyPI 发布。

## 用真实验收库启动

需要 Python 3.11+、支持 FTS5 的 SQLite、uv、Node 和 pnpm。首次运行在仓库根目录安装锁定依赖：

```bash
uv sync --locked --dev
(cd web && pnpm install --frozen-lockfile)
uv run python scripts/real_knowledge_acceptance.py \
  --output-dir .konwledge/real-knowledge-acceptance
```

验收脚本每次建立唯一运行目录。确认输出 `status` 为 `passed`，从输出的 `report` 路径找到这次 `report.json` 的父目录，再用其中已有的 `knowledge.db`。不要把输出根目录当作运行目录，也不要复用某台机器的固定目录或凭据。将下面的占位路径替换为实际运行目录后执行：

```bash
uv run python scripts/live_workbench.py \
  --database "<real-acceptance-run-directory>/knowledge.db" \
  --web-port 5175 --api-port 8015
```

启动器检查已有 SQLite 文件及两个不同的空闲 loopback 端口，自动生成随机临时 key，先等待 backend `/health` 就绪，再启动 Vite。打开 [本机任务列表](http://127.0.0.1:5175/#lifecycle/jobs)。按 `Ctrl+C` 只终止启动器自己创建的子进程组；启动失败也会清理这些进程，不按端口杀其它服务。

启动器不创建缺失数据库，但 backend 启动仍可能执行已有 additive schema／FTS 初始化。因此请使用隔离验收库，不能宣称启动完全不写库。HTTP 读取只读，页面不新增 evaluation、不更新 baseline，也不重跑任务。

## 页面与数据边界

- 静态入口仍是 `#overview`、`#trace`、`#diff`；实时入口是 `#lifecycle/jobs`，支持状态过滤、分页和手动刷新。切换状态回到第一页，刷新重读当前页；查看新增任务时先回第一页。跨请求分页不作为冻结快照。
- 实时 hash 导航覆盖任务详情、revision、document、lineage、版本 Diff 和 exact evidence。具体 ID 从页面链接获取，历史选段按确切 unit／document 版本读取，并显示字符范围、content hash 和 document checksum。缺失或损坏的历史证据明确报错，不用最新正文替换。
- 任务保留评测时间、数据集版本及配置／知识指纹；单元 status 展示的是持久化的当前缓存状态，不是任务当时的 as-of 状态。文档前后版本表示导入顺序，也不等于发布 head。
- 页面区分 `queued`、`running`、`passed`、`failed`、`blocked`、`superseded`，处理 loading、空数据、权限拒绝、资源不存在、历史资源不可用、服务错误和读取重试。这里的“重试”只重发 GET。缺少报告或指标为 `null` 时不显示成零或通过。
- 请求使用 `AbortController` 和 sequence 检查，切换路由、筛选或刷新后，旧响应不能覆盖新请求。DTO 通过 Ajv 运行时白名单校验，并检查 ID 与 href 的一致性。字符偏移按 Unicode code point 解释，不当作 JavaScript UTF-16 下标；原文选段按未受信文本展示，不执行 HTML。

B3 新增 `#evaluation?reference=UUID&candidate=UUID&offset=n` 和 `#guide?normal=UUID&fault=UUID&restore=UUID&offset=n`。用户手动选参考／候选或正常／故障／恢复角色，跨页保留。评测页手动刷新与有界观察共用刷新逻辑，刷新前记录列表头部，再重读当前页及按原 ID 选中的参考／候选；刷新新任务不替换选择。列表或选中任务读取中均视为 busy。导览刷新也重读当前页及已选的正常／故障／恢复任务。未知／重复 query、非法参数及这些入口下的未知子路由会阻断，不请求数据、不回显原始 hash。

评测对照先检查 dataset id／version／hash、config fingerprint、完整 passed／质量门禁 failed 报告及 8 项默认 checks 的集合与门槛。top_k actual 必须是两侧一致的正整数；degraded、非质量终态、配置不同或 case_count=null 不输出 delta。null 保留为未评估，比例差按百分点显示，不重算 gate 或接受 baseline。不同知识指纹和 evaluated_at 仅作观察，不自动因果归因。B1 没有 case-level query／cases，B3 不造逐用例失败诊断；stale_hits 按当时报告读取，不从当前 unit.status 重算。

导览检查角色状态、顺序、指纹和 trigger revision，再链接已有 job → revision → Diff → evidence。即使通过，也须核验真实 CLI 更新与恢复记录，不能仅凭 pass／fail／pass 序列证明故障注入。详细可比条件、无答案检索与引用覆盖的解释见 [评测对照与演示导览](evaluation-workbench.md)。

评测对照页的观察默认关闭，用户主动开启后每 10 秒刷新，最多 5 分钟／30 次；busy 跳过 tick，不延长窗口。隐藏、page key 变化、读取错误或卸载会停止，不自动 resume。停止只阻止后续 tick，不承诺取消已发 HTTP，手动刷新仍可用。B4 写交互与 B5 MCP 未实现，下一批 B4 另设计真实身份／权限、幂等和操作确认，不自动启动。

## 密钥只留在进程中

启动器仅向 backend 和 Vite 的 Node 子进程注入 `KNOWLEDGE_API_KEY`；Vite 另收 `KNOWLEDGE_MANAGEMENT_ORIGIN=http://127.0.0.1:8015`。手动接线也只在这两个进程环境中配置，不写入仓库、命令参数或 `VITE_*`，不把 key 交给浏览器。

浏览器只向同源 `/v1/management` 发 GET，不带 key 或 cookie；dev proxy 校验后再添加 backend Bearer 认证。代理未配置或配置无效时，合法管理请求返回 503。upstream 只接受带显式有效端口的 HTTP loopback，主机限 `127.0.0.1`、`localhost` 或 `[::1]`，拒绝公网地址、URL 凭据、额外路径或 query。转发前校验 Origin、Host、route、method 及 queries，拒绝未知／重复参数和写方法，不透传浏览器认证或任意请求头。

代理仅用于 Vite dev；`pnpm preview` 和 `dist/` 不含 dev proxy。静态构建保留演示，不能据此宣称 live 已部署，也不应为联调放开公网或任意 CORS。完整 HTTP 契约见 [只读管理 API](management-api.md)。

## 验证命令与已知结果

在仓库根目录检查 management schema／类型漂移及专项测试：

```bash
uv run python scripts/export_management_schema.py --check
uv run pytest tests/test_live_workbench.py tests/test_management_schema.py \
  tests/test_workbench_evaluation_acceptance.py
(cd web && pnpm verify)
```

Management schema 从 Python DTO／query 模型导出，与 Snapshot V1 独立，不修改 demo golden。`pnpm verify` 检查前端类型、Snapshot 类型漂移、`check:management`、Vitest 和构建；Python schema 的 `--check` 仍单独执行，不以生成命令代替漂移检查。

B3 隔离 HTTP 联调从仓库根目录运行：

```bash
uv run python scripts/workbench_evaluation_acceptance.py
```

验收脚本每次建立唯一运行目录，正式 CLI 只修改文档和数据库副本；临时 key 不进参数或原始错误报告，stdout／stderr 只记 hash，临时 loopback 子进程在 finally 关闭。2026-11-16 最后一次运行 `20261116T042018921245Z-951ad2f7` 通过，mean Recall 为 `1 → 0.666667 → 1`。刷新看到新增 passed 任务和 UI 提示，原选择与失败记录保留，`children_stopped=true`。这是真实前端 client／DTO／comparison engine／jsdom UI 经 HTTP dev proxy 的联调，不是浏览器整链点击验收。

B3 前端 `pnpm verify` 为 179 passed、1 skipped（10 files passed、1 skipped），typecheck、Snapshot 类型漂移、management 类型漂移与 build 通过，`pnpm install --frozen-lockfile` 通过。默认跳过的 1 项真实 HTTP integration 已由上述隔离验收单独运行通过，不计入普通回归通过数量。Python 完整回归为 1325 passed、3 skipped，ruff check／format、mypy 169 个源文件、Snapshot／schema 漂移检查均通过。专项测试包含于完整回归，不另行相加。

两页页面渲染检查通过，控制台为空，内容无外溢。首轮关键结果位于首屏以下，已调整并复查：评测页先显示 100% → 66.67%、−33.33 个百分点，导览先显示阶段判定和对照链接。临时测试密钥下的真实 build 扫描确认 dist 不含该密钥或测试后端地址；约 552 kB 的构建 chunk 仍有非阻断体积警告。本次云端浏览器不能直达 loopback，真实 HTTP／jsdom UI 联调与页面渲染检查分别记录，不宣称浏览器整链点击通过。完整结果见 [评测工作台验收记录](evaluation-workbench.md#回归命令与验收记录)。

## B2 历史验收记录

以下记录来自 B2，不作为 B3 全量结果。

完整 Python 回归取得 1320 passed、3 skipped，ruff、格式检查与 mypy 均通过。前端 `pnpm verify` 取得 126 tests、类型检查、Snapshot 类型漂移及构建通过；management schema／类型漂移也通过。proxy 专项 85 属于前端 126，launcher 专项 29、schema 专项 4 属于 Python 回归，不另行相加。

已用云端浏览器在隔离验收工作台走通失败任务 → 触发 revision → 历史 Diff → 旧版本证据。页面中的证据确切指向旧 document／unit，字符范围为 `[995, 1885)`，选段为 890 code points，未用最新正文替换。任务列表、失败详情、Diff 和证据页的静态布局检查均无控制台错误，列表显示 passed → failed → passed，Diff 为 1 modified／4 unchanged。管理 API 验收再次通过，读取前后 19 张表、137 行及内容摘要不变，评测任务仍为 3 条。

筛选、分页、读取重试、前进后退及竞态通过自动测试覆盖，本轮云端浏览器只做最短导航检查，没有逐项人工点验，也没有验证全部移动端尺寸或公开部署。构建仍有主 bundle 超过 500 kB 的非阻断提示，后续可按页面拆包。

<!-- 文稿复核：已回读事实、行文和节奏。机械扫描中文半角标点 0、长破折号 0、编号／量词标题 0、对比句式 0、元话语 0。事实账本：B3 回归与最后一次隔离联调、页面渲染及构建隔离检查一致，B2 历史记录保留；泛化启动命令、密钥、只读与停止观察边界不变。 -->
