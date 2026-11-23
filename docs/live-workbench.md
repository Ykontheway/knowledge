# 本机工作台（B2～B4）

工作台已支持生命周期与变更视图、只读评测对照、使用导览，以及显式启用的隔离受控变更。版本快照视图独立保留；实时工作台通过只读管理 API 读取已有数据库，写入另按显式开关接入 `/v1/mutations`。当前没有公开 live 后端部署，包版本仍为 `0.1.0` prepared alpha；已发布的 [静态回放预览](replay-preview.md) 不连接本机管理服务。

B4 阶段的历史收尾校验已完成：ruff check、ruff format --check（208 files）、mypy（183 sources）、management／mutation schema --check、Python 回归（1495 passed、3 skipped）、前端 `pnpm verify`（352 passed、2 skipped）、B4 driver 和发行包隔离 smoke 均通过。两个前端 skipped 是需要联调服务环境的 live acceptance 默认跳过，不是假失败。

## 只读启动（B2／B3）

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

启动器检查已有 SQLite 文件及两个不同的空闲 loopback 端口，自动生成随机临时读 key，先等待 backend `/health` 就绪，再启动 Vite。打开 [本机任务列表](http://127.0.0.1:5175/#lifecycle/jobs)。按 `Ctrl+C` 只终止启动器自己创建的子进程组；启动失败也会清理这些进程，不按端口杀其它服务。

启动器不创建缺失数据库，但 backend 启动仍可能执行已有 additive schema／FTS 初始化。因此请使用隔离验收库，不能宣称启动完全不写库。HTTP 读取只读，页面不新增 evaluation、不更新 baseline，也不重跑任务。

## 受控变更启动（B4）

B4 只接受 `scripts/prepare_mutation_demo.py` 新建的私有演示副本，不接业务数据库。先准备这次写演示的独占目录：

```bash
uv run python scripts/prepare_mutation_demo.py
```

脚本会在 `.konwledge/mutation-demo/<scope-id>/` 下创建私有目录、隔离 `knowledge.db`、`mutation-manifest.json` 和 `report.json`，并在 stdout 返回本次 `manifest`、`database`、`scope_id` 与 `source_ids`。

拿到上一步实际输出的 `manifest` 和 `database` 后，再显式打开 B4：

```bash
uv run python scripts/live_workbench.py \
  --database "<mutation-demo-run-directory>/knowledge.db" \
  --web-port 5175 --api-port 8015 \
  --mutation-manifest "<mutation-demo-run-directory>/mutation-manifest.json" \
  --mutation-actor demo-editor
```

要点：

- `--mutation-manifest` 与 `--mutation-actor` 必须同时提供。
- `mutation_actor` 必须是安全的本机 ASCII 标识，服务端会把它写入 mutation 审计。
- 启动器会临时生成独立读 key 和写 key，两者不同；浏览器都拿不到。
- B4 页面入口是 `#changes`，恢复入口是 `#changes?command=<command-id>`。
- 只允许 manifest allowlist source 的当前正文修改；不接受浏览器文件路径、SQL 凭据、DSN 或任意写目标。

完整写边界、命令恢复和验收记录见 [受控变更工作台](controlled-mutations.md)。

## 页面与数据边界

- 静态入口仍是 `#overview`、`#trace`、`#diff`；实时入口包括 `#lifecycle/jobs`、`#evaluation`、`#guide` 和 B4 的 `#changes`。B2/B3 继续支持状态过滤、分页、手动刷新与 hash 导航。
- 实时 hash 导航覆盖任务详情、revision、document、lineage、版本 Diff 和 exact evidence。历史选段按确切 unit／document 版本读取，并显示字符范围、content hash 和 document checksum。缺失或损坏的历史证据明确报错，不用最新正文替换。
- B4 的 `#changes` 先让用户选择授权 source，再读取该 source 当前 head document。页面只编辑正文；preview 展示完整 Diff 和计数，确认框不勾选就不能提交。
- `#changes?command=<id>` 只做命令结果恢复。刷新或重启后，如果确认 token 已丢失，页面只能按命令 ID 做 GET 回查，不能自动新建提交。
- 请求使用 `AbortController` 和 sequence 检查，切换路由、筛选、刷新或切换 source 后，旧响应不能覆盖新请求。B4 预览在草稿变化后立即失效，不允许拿旧预览提交新正文。
- DTO 通过 Ajv 和 mutation schema 双重运行时白名单校验，并检查 ID、href、checksum、scope、actor 等关键字段。字符偏移按 Unicode code point 解释，不当作 JavaScript UTF-16 下标；原文和 Diff 一律按未受信文本展示，不执行 HTML。
- 评测对照仍只在 dataset id／version／hash、config fingerprint、完整 passed／质量门禁 failed 报告及 8 项默认 checks 集合一致时输出 delta。B4 沿用这条只读对照边界，不在前端重算 gate，也不接受 baseline。

## 密钥只留在子进程环境

启动器向 backend 和 Vite 的 Node 子进程注入 `KNOWLEDGE_API_KEY`，并把 `KNOWLEDGE_MANAGEMENT_ORIGIN=http://127.0.0.1:<api-port>` 交给前端 dev 代理。启用 B4 时，启动器还会额外为子进程注入 `KNOWLEDGE_MUTATION_ENABLED=1`、独立的 `KNOWLEDGE_MUTATION_KEY` 和 `KNOWLEDGE_MUTATION_ACTOR`。

浏览器只向同源 `/v1/management` 和 `/v1/mutations` 发 GET／POST，不带 key、cookie 或浏览器侧 Authorization。Vite Node 代理在校验同源、路径、方法、JSON、intent 和 body 大小后，才代发 upstream 请求：

- 管理 GET 用只读 key。
- B4 的 mutation GET／POST 用独立写 key。
- preview／dist 不包含这些 dev proxy。

确认 token 只短暂保留在前端进程内存，用于同一次 preview 对应的 POST；它不会进入 URL、`localStorage`、`sessionStorage`、构建产物或验收报告。

## 验证命令与已知结果

在仓库根目录检查 management schema／mutation schema 漂移及专项测试：

```bash
uv run python scripts/export_management_schema.py --check
uv run python scripts/export_mutation_schema.py --check
uv run pytest tests/test_live_workbench.py tests/test_management_schema.py \
  tests/test_mutation_workbench_acceptance.py tests/test_mutations_demo.py
(cd web && pnpm gen:mutations)
(cd web && pnpm check:mutations)
(cd web && pnpm mutationtypecheck)
(cd web && pnpm verify)
```

Management schema 与 mutation schema 都独立于 Snapshot V1，不修改 demo golden。上面的两个 Python `--check` 分别检查 management／mutation schema 漂移；`pnpm gen:mutations` 重新生成 mutation 类型，`pnpm check:mutations` 检查是否漂移；`pnpm mutationtypecheck` 单独检查 mutation proxy 的 Node/TypeScript 约束。`pnpm verify` 已包含 mutationtypecheck、Snapshot／management／mutation 类型漂移、Vitest 和构建。

B3 隔离 HTTP 联调从仓库根目录运行：

```bash
uv run python scripts/workbench_evaluation_acceptance.py
```

B4 隔离 HTTP／UI／core 验收从仓库根目录运行：

```bash
uv run python scripts/mutation_workbench_acceptance.py
```

B4 验收脚本会先调用 `scripts/prepare_mutation_demo.py` 准备独占演示副本，再启动真实 backend、Vite dev 和固定的前端 live test。报告写到对应运行目录的 `b4-acceptance-report.json`。当前仓库里的最后一次通过报告位于：

- [`.konwledge/mutation-demo/b239f388-6ef5-401f-879b-e43cf59fb68e/b4-acceptance-report.json`](../.konwledge/mutation-demo/b239f388-6ef5-401f-879b-e43cf59fb68e/b4-acceptance-report.json)

已知结果：

- B3：2026-11-16 最后一次运行 `20261116T042018921245Z-951ad2f7` 通过，真实前端 client／DTO／comparison engine／jsdom UI 经 HTTP dev proxy 联调，mean Recall 为 `1 → 0.666667 → 1`。刷新看到新增 passed 任务和 UI 提示，原选择与失败记录保留，`children_stopped=true`。
- B4：scope `b239f388-6ef5-401f-879b-e43cf59fb68e` 的报告通过；全部 checks 为 true，frontend_update 与 frontend_recovery 均为 passed，三次变更产生的 command 与 jobs 恰好各 3，固定 config fingerprint 与 dataset 下任务序列为 `passed → failed → passed`，mean Recall 为 `1 → 0.6666667 → 1`。真实前端验收覆盖提交响应丢失、GET 恢复不重复写、凭据不持久化，以及重启后历史失败／Diff／证据回查；driver 另跑已通过且 `children_stopped=true`。
- 前端 `pnpm verify` 全通过，结果为 `352 passed / 2 skipped`；两个 skipped 是需要联调服务环境的 live acceptance 默认跳过，不是假失败。typecheck、类型漂移、Vitest 和 build 均通过，`pnpm verify` 已包含 mutationtypecheck 与 check:mutations。
- 发行验证 `scripts/verify_distribution.py --output-dir .konwledge/b4-final-distribution-verified` 已通过 wheel／sdist 隔离安装 smoke；这只是分发验证，不代表已发布，本次也没有公开部署。静态渲染检查显示 `#changes` 初始页面布局正常、无 console errors；恢复入口静态中间状态显示清楚。真实交互验收来自 jsdom + HTTP driver。生产 build 仍有 584.87 kB chunk 体积提醒，属于后续可优化项，不是功能失败。

## B2 历史验收记录

以下记录来自 B2，不作为 B3 或 B4 的全量结果。

完整 Python 回归取得 1320 passed、3 skipped，ruff、格式检查与 mypy 均通过。前端 `pnpm verify` 取得 126 tests、类型检查、Snapshot 类型漂移及构建通过；management schema／类型漂移也通过。proxy 专项 85 属于前端 126，launcher 专项 29、schema 专项 4 属于 Python 回归，不另行相加。

已用云端浏览器在隔离验收工作台走通失败任务 → 触发 revision → 历史 Diff → 旧版本证据。页面中的证据确切指向旧 document／unit，字符范围为 `[995, 1885)`，选段为 890 code points，未用最新正文替换。任务列表、失败详情、Diff 和证据页的静态布局检查均无控制台错误，列表显示 passed → failed → passed，Diff 为 1 modified／4 unchanged。管理 API 验收再次通过，读取前后 19 张表、137 行及内容摘要不变，评测任务仍为 3 条。

筛选、分页、读取重试、前进后退及竞态通过自动测试覆盖；当轮云端浏览器只做最短导航检查，没有逐项人工点验，也没有验证全部移动端尺寸或公开部署。构建仍有主 bundle 超过 500 kB 的非阻断提示，后续可按页面拆包。

<!-- 文稿复核：已回读事实、行文和节奏。机械扫描中文半角标点 0（排除 URL／路径／inline code 命中）、长破折号 0、编号／量词标题 0、对比句式 0、元话语 0。事实账本：补齐 B4 启动命令、#changes／command 恢复入口、独立读写密钥、默认关闭、allowlist 正文修改、最新 scope b239f388-6ef5-401f-879b-e43cf59fb68e、352／2 前端、发行包隔离 smoke、静态渲染和 584.87 kB 非阻断提醒；未写入密钥、正文或内部技能内容。 -->
