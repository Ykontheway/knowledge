# 静态回放预览

静态只读预览已于 **2026-11-23** 发布：[Knowledge CI 工作台](https://ykontheway.github.io/konwledge/#replay/guide)。它展示固定公开合成语料产生的真实评测记录，不连接用户业务库或实时后端，也不开放写工具。包版本仍为 `0.1.0` prepared alpha，未正式发行；当前架构见 [架构说明](architecture.md)，开发依赖见 [开发说明](development.md)。

## 导出只使用固定合成语料

实现位于 `src/konwledge/replay/{bundle,corpus,files,producer}.py`，仓库入口为 [scripts/export_replay.py](../scripts/export_replay.py)。导出器只在工具自建的 `.konwledge/replay/<UUID>` 私有 scope 内生成固定、可公开的合成语料，通过正式 `KnowledgeLibrary` SDK 发布知识，并由自动评测 outbox 产生真实任务与持久化报告。它不读取用户业务库，也不开放通用业务库导出。

从仓库根目录检查现有文件：

```bash
uv run --frozen python scripts/export_replay.py --check --output web/public/replay.json
```

`--check` 只读校验静态 JSON，不生成语料、不打开数据库、不调用 HTTP，也不新增任务。成功输出 `REPLAY_VALID`。

如需另建回放文件，选择已有父目录下尚不存在的文件名：

```bash
uv run --frozen python scripts/export_replay.py --output web/public/replay-new.json
uv run --frozen python scripts/export_replay.py --check --output web/public/replay-new.json
```

默认输出为 `web/public/replay.json`；不带 `--check` 才执行导出，成功输出 `REPLAY_EXPORTED`。输出文件已存在时拒绝覆写，路径中的 symlink 也会被拒绝；输出父目录须已存在。没有 `--database`、`--manifest`、`--URL` 或 `--force`，不能指定已有数据库、外部语料、URL 或私有 scope。更新仓库内文件须由维护者另行审阅并处理，不能靠强制覆盖参数绕过保护。

公开证据只接受固定安全全文／段落白名单。这项保护针对工具自己的合成语料，不提供任意业务原文自动脱敏。导出不透传 query、metadata、locator、local path 或 raw exception，不能据此宣称业务数据已安全脱敏。

## 回放包沿用 B1 DTO

[web/public/replay.json](../web/public/replay.json) 使用严格的 B1 DTO，顶层结构如下，资源内容在示意中省略：

```json
{
  "schema_version": 1,
  "mode": "replay",
  "generated_at": "带时区的生成时间",
  "story": {
    "reference_job_id": "参考任务 UUID",
    "candidate_job_id": "候选任务 UUID",
    "recovery_job_id": "恢复任务 UUID"
  },
  "resources": {
    "jobs": [],
    "revisions": [],
    "documents": [],
    "lineages": [],
    "units": [],
    "evidence": [],
    "diffs": []
  }
}
```

`resources` 下各集合都是 DTO 数组。嵌套字段 `DocumentDTO.units`、`LineageDTO.versions`、`DocumentDiffDTO.changes` 则保留 B1 的 `Page` 对象：

```text
Page = {items: [...], total: 全部条目数, limit: 100, offset: 0}
```

不要把外层字段改名为 `items`，也不要把这些 Page 改成数组。回放包保存全部条目，`total` 必须等于 `items.length`；前端静态 transport 再按请求分页。

当前仓库文件的安全元数据已核对，未复制原始证据全文：

| 项目 | 值 |
| --- | --- |
| schema／mode | `1`／`replay` |
| `generated_at` | `2026-11-20T08:32:21.682543Z` |
| 文件大小 | `263215` bytes |
| SHA-256 | `9cd0af3875b768b3a50326fc386452fcb88bf11af8ad58ef64f0499fc4a35d05` |
| jobs／revisions／documents | `3`／`16`／`4` |
| lineages／units／evidence／diffs | `3`／`12`／`12`／`16` |

三阶段按 `story` 的角色 ID 识别，不按 jobs 数组位置推断。任务为 `passed → failed → passed`，共用同一 dataset id／version／hash 和 config generation／fingerprint，固定 4 条 cases；mean Recall 为 `1 → 2/3 → 1`。质量失败码为 `QUALITY_GATE_FAILED`，失败知识已经提交，评测不回滚提交，也不自动接受 baseline。

这些数据验证合成语料上的检索与评测链路。页面没有 case-level query／cases，不提供逐用例业务原因诊断，也不声明源事实正确或生成答案质量。新一次导出会建立新的私有 scope，任务 UUID 与时间会变化；上述 bytes／hash 只标识当前文件，不承诺每次导出字节相同。

## 页面显式区分 replay 与 live

回放复用 `ManagementClient`、B1 DTO schema 和现有页面，通过静态 transport 在内存中处理管理资源读取。浏览器先读取同源 `replay.json`，不会把 DTO 中的管理 href 当成真实 API 网络请求。加载失败或 bundle 损坏时显示错误，没有 live fallback，也不伪造成功数据。

| hash | 页面 |
| --- | --- |
| `#replay`、`#replay/guide` | 正常／故障／恢复导览 |
| `#replay/evaluation` | 参考／候选评测对照 |
| `#replay/lifecycle`、`#replay/lifecycle/jobs` | 任务列表 |
| `#replay/lifecycle/jobs/{job-id}` | 任务详情 |
| `#replay/lifecycle/revisions/{revision-id}` | revision 详情 |
| `#replay/lifecycle/documents/{document-id}` | 文档版本与单元分页 |
| `#replay/lifecycle/documents/{new-id}/diff?old={old-id}` | 历史 Diff |
| `#replay/lifecycle/lineages/{lineage-id}` | lineage 历史 |
| `#replay/lifecycle/evidence/{unit-id}` | 精确历史证据 |

分页、过滤、评测选择和资源导航保留 `mode=replay`，不会跳回 live 路由。回放只展示已有任务，不观察新任务；证据仍绑定具体历史版本，当前 unit.status 不冒充任务 as-of 状态。

source revision 的 `navigation.content_hash` 可以合法为 `null`。前置 Ajv schema 负责字段必填性与 nullability，后置 hash 检查已修复对合法 null 的误拒绝；非 nullable 字段的 null 和非法 hash 仍会被拒绝。该修复不放宽 B1 DTO schema。

## 本机预览使用独立构建

普通 `pnpm verify` 仍构建 `web/dist`，保留 Snapshot V1、live 工作台与默认关闭的 B4 受控变更契约。回放预览使用独立 Vite mode 和输出目录，不改变普通 production／dev／test 的入口规则。

从仓库根目录完成 Python 检查后，在 `web/` 下准备预览：

```bash
cd web
pnpm install --frozen-lockfile
pnpm verify
pnpm verify:preview
# 仅在需要查看本机预览时启动服务，不是公开部署
pnpm preview:replay --host 127.0.0.1
```

- `pnpm check:replay` 运行真实 `public/replay.json` fixture integration、nullable hash 和 preview 测试。
- `pnpm build:preview` 执行 `tsc --noEmit` 与 `vite build --mode replay --outDir dist-preview`。
- `pnpm verify:preview` 依次执行 `check:replay`、`build:preview` 和 [scripts/check-preview.mjs](../web/scripts/check-preview.mjs)。
- `pnpm preview:replay` 只服务本机的 `dist-preview`。该目录已加入 `.gitignore`，不作为源码提交。

preview mode 的空 hash 默认进入 `#replay/guide`，菜单隐藏受控变更入口。手输 `#changes` 或 live 的 `#guide`、`#evaluation`、`#lifecycle/...` 会显示 blocked notice，不发出这些路由的网络请求。旧 `#overview`、`#trace`、`#diff` 仍展示 Snapshot V1，preview 菜单继续指向 replay 页面。

构建检查只允许 `index.html`、`replay.json`、`favicon.svg` 与 `assets/` 下允许的 JS／CSS／字体资源，拒绝 symlink 和特殊文件；按固定敏感模式检查私钥、bearer、带凭据 DSN 和本机路径。它还检查 HTML 资产使用 `./` 相对地址、引用文件存在、构建中的 replay 与源码文件逐字节相等，以及 `story` 对应的 3 个任务状态。相对资产支持站点子路径；固定模式扫描不等于通用业务数据脱敏或生产安全审计。

## 发布操作与已上线记录

[deploy-demo.yml](../.github/workflows/deploy-demo.yml) 已改为手动 `workflow_dispatch`，不再因 push `main` 自动部署。`publish` 是 boolean，默认 `false`。

`prepare` job 用 `uv run --frozen` 检查随源码提交的 `web/public/replay.json`，不在 CI 临时重建回放库；随后运行 `pnpm verify` 和 `pnpm verify:preview`，上传 `replay-preview` artifact。artifact 是预览构建产物，不代表站点已上线。[常规 web CI](../.github/workflows/ci.yml) 也已加入 `pnpm verify:preview`。

只有手动运行时显式设为 `publish=true`，且 `prepare` 成功，才允许 `publish` job 将同一已验证 artifact 部署到 Pages。workflow 文件名 `deploy-demo.yml` 为兼容既有 dispatch 入口保留，显示名称为 `Knowledge CI Replay Preview`；名称调整不改变发布权限，也不自动触发部署。

每次发布前，维护者须确认：

- GitHub Pages 的 **Build and deployment → Source** 已设为 **GitHub Actions**。
- `github-pages` environment 的部署权限、允许分支与保护规则符合发布要求；publish job 所需 `pages: write`、`id-token: write` 未被仓库或组织策略阻断。
- 默认分支中已有允许 `workflow_dispatch` 的对应 workflow，选定 ref 包含本轮实现与审核后的回放文件。GitHub 的 dispatch 入口通常要求默认分支已有 workflow；仅向 feature 分支推送新 workflow，不能保证新的名称或 UI 输入参数已经出现。首次发布已验证现有入口可用，后续发布仍须核对默认分支定义与选定 ref，不自动代办 main 变更。
- 本轮最终复核记录齐备，并取得单独的公开发布授权。部署后再根据 Actions 的实际结果核验站点地址与子路径加载。

首次发布使用 feature 分支提交 `2ed4f9acda77118c582be709a681d51b34dffb56`，对应 [Actions 运行 45105672969](https://github.com/Ykontheway/konwledge/actions/runs/45105672969)。首次尝试的 prepare 通过，但 publish 被仅允许 main 的环境规则拒绝；保留 main 规则并只加入当前 feature 分支后，重跑失败的 publish 成功，没有合并或修改 main。

线上核验确认根页面与 17 个资源均返回 `200`，与验收构建逐字节一致；回放文件大小和 SHA-256 与本页记录一致，完整 bundle 校验通过。导览、评测对照和手输 `#changes` 的阻断页均正常呈现，捕获的控制台日志为空；管理和写 API 路径返回 `404`。这些是静态加载与呈现检查，不代替真实浏览器交互、移动端或生产服务验收。

当前文案整理后的源码仍须经新的发布操作才会更新公开页面。准备构建、上传 artifact、创建 PR 和公开部署是不同状态，不能相互代替。

## 复核命令保留结果范围

除上述 Python bundle 检查和前端命令外，可从仓库根目录复核相关 Python 测试、格式与类型：

```bash
uv run pytest tests/test_replay.py tests/test_distribution_replay.py tests/test_distribution.py
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests scripts
uv run python scripts/export_management_schema.py --check
uv run python scripts/export_mutation_schema.py --check
```

仓库内回放文件已生成并通过 Python `--check`。以下保留回放实现阶段、首次发布前的历史验收，不代表后续文案变更的验证。专项数量是全量中的子集，不能相加；B1～B6 历史验收继续保留原范围。

| 验收 | 结果 |
| --- | --- |
| Python 全量 | `2540 passed、7 skipped`，415.83 秒 |
| MCP／回放发行与导出专项 | `350 passed`，18.21 秒 |
| Ruff／mypy | check 通过、248 files 已格式化；219 source files 无类型错误 |
| schema 漂移 | management／mutation exporter `--check` 均保持不变；前端三类类型漂移检查通过 |
| 前端完整验证 | `pnpm verify` 通过，`529 passed、2 skipped`，普通 production build 成功 |
| 回放预览专项 | `pnpm verify:preview` 通过，91 项测试通过，独立 replay build 成功 |
| 构建产物检查 | 17 个允许资源，3 个任务，回放 263215 bytes 与源码逐字节一致 |
| 真实 wheel／sdist 隔离发行 | 两种格式均通过；`replay_core` 为 3 jobs／16 diffs，既有 MCP 默认／最低 SDK／受控 lanes 继续通过 |
| 本机静态 HTTP | 59 项通过；根路径及 `/konwledge/` 子路径资源逐字节一致；API 路径 404，POST 405 |
| 静态页面呈现 | 导览、两组对照、生命周期、历史证据和写入口阻断页共 6 次检查通过，捕获的控制台日志为空；临时服务已清理 |

Python 7 项 skip 保留既有可选 PostgreSQL、LanceDB、内存 MCP 文件特性及未显式启用的工作台 live 用例范围；前端 2 项也是需真实本机服务的既有 live 用例。本轮没有启动这些可选服务，不把 skip 写成通过。build 的约 606 kB JS chunk 提醒仍为非阻断优化项。静态呈现检查没有提供精确视口尺寸或截图路径，未做移动端及真实浏览器交互验收；完整导航由真实数据的 jsdom 整合测试覆盖。

原始证据留在本机 `.konwledge`，不随 Git 提交：[`acceptance-report.json`](../.konwledge/byproducts/replay-preview/acceptance-report.json)、[`http-checks.json`](../.konwledge/byproducts/replay-preview/http-checks.json)、[`html_vision.original.log`](../.konwledge/byproducts/replay-preview/html_vision.original.log)，以及发行目录 [`.konwledge/replay-preview-final-distribution`](../.konwledge/replay-preview-final-distribution)。首轮完整回归暴露的两项旧发行编排测试未适配新 `replay_core` 摘要，已补齐隔离解释器与摘要断言；没有放宽实际发行校验。上述结果是发布前的本机验收，不与首次线上发布的检查数量相加；线上发布记录见“发布操作与已上线记录”。

<!-- 文档校对记录
本次补录首次发布和线上核验，保留回放实现阶段的历史验收；新源码文案尚未重新部署。
机械扫描命中 1 处半角标点，位于 Page 结构代码块，按代码语法豁免；中文正文有效命中为 0，元话语及破折号为 0。
固定数据、命令、DTO、安全限制与提交后评测关系未变，部署事实与后续发布权限分开说明。
-->
