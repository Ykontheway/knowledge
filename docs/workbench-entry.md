# 统一工作台入口

**B-R2 已完成并验证。** 统一入口是 `scripts/workbench.py`，稳定命令为 `list`、`demo`、`accept`。命令语义、退出结果和报告引用以仓库内真实 `summary.json` 与 Git 历史为准。

B 系列状态见 [主计划](integrated-demo-roadmap.md)。B5／U22 只读 MCP 与 B6 受控正文更新均已完成并验证，原编号不变；MCP 是独立 stdio 入口，不是工作台 HTTP 代理。若后续要做本地 Mac 统一入口，需先单独补平台兼容，不并入 B-R2 已完成范围。

## 运行环境

文中 `ROOT` 指仓库根目录。统一入口当前要求：

- Python 3.11+
- 支持 FTS5 的 SQLite
- Node、pnpm
- 具备 Linux `/proc`、`subreaper`、`pidfd` 子进程追踪与清理核验能力

```bash
uv sync --locked --dev
(cd web && pnpm install --frozen-lockfile)
```

统一 `demo`／`accept` 现在只支持具备这些 Linux 能力的环境。macOS／Windows 不在已完成范围内；缺少必要能力时统一按 fail-closed 返回 `cleanup_unknown`，不会误报通过。原独立脚本仍保留，但这不代表统一入口已经跨平台。

下面示例使用 `uv run python`。若当前 Python 环境已安装项目和依赖，也可以直接运行：

```bash
python scripts/workbench.py list
```

## 先看入口命令

```bash
uv run python scripts/workbench.py list
uv run python scripts/workbench.py demo --help
uv run python scripts/workbench.py accept --help
```

`list` 只列出统一入口和安全默认值，不准备 seed，不启动服务，也不运行验收。

## demo 默认是 readonly

```bash
uv run python scripts/workbench.py demo
```

这等价于：

```bash
uv run python scripts/workbench.py demo --mode readonly
```

默认流程是：先在全新隔离库里生成并核验 seed，再启动已有 seed 的只读管理联调。这里的“只读”只指交互阶段 API；准备阶段会写新隔离库，backend 启动也可能执行已有 schema／FTS 初始化。

默认端口是 `--web-port 5175 --api-port 8015`，只监听 `127.0.0.1`。改端口时两个端口必须不同且空闲：

```bash
uv run python scripts/workbench.py demo --web-port 5176 --api-port 8016
```

本轮 readonly live 证据见 [B-R2 原 readonly 停止记录](releases/legacy-0.1.0.md#b-r2-统一入口)。该次运行以 `Ctrl+C` 收尾，summary 顶层状态为 `stopped`，launcher `exit_code=130`，清理核验为 `true`。这表示启动、停止和清理按设计工作，不表示评测 passed，也不表示验收 failed。

readonly demo 的 live 复核只做 HTTP GET：

- readonly backend 的 B4 session 路径返回 `404`
- Vite Node dev proxy 未开启时返回 `503`，不要写成“全部 404”
- seed 已经带有 3 个 jobs；demo 本身不新增 preview／command／额外 jobs
- 页面仍只做同源 GET，不写评测、不更新 baseline

## controlled demo 必须显式提供 actor

```bash
uv run python scripts/workbench.py demo --mode controlled --actor demo-editor
```

controlled 模式调用原 `scripts/prepare_mutation_demo.py`，继续使用固定私有根 `ROOT/.knowledge/mutation-demo/<scope-id>/`。统一入口自己传递这次准备出来的 database 和 manifest，不接受外部 database、manifest、路径、DSN 或 key。

`--actor` 没有默认值。只有 `--mode controlled` 才接受它，且必须显式传入。示例里的 `demo-editor` 只是本机演示 actor；session role 仍是 `demo_editor`，两者不是同一个字段，也不代表生产认证、SSO 或 RBAC。

本轮 controlled live 证据见 [B-R2 原 controlled 停止记录](releases/legacy-0.1.0.md#b-r2-统一入口)。该次运行同样以 `Ctrl+C` 收尾，summary 顶层状态为 `stopped`；`prepare_controlled` 先到 `ready`，launcher `exit_code=130`，清理核验为 `true`。这次复核仍只做 HTTP GET，不执行 preview 或 command。

controlled demo 已验证的边界：

- 演示验收实际传入的 actor 是 `demo-editor`
- session role 是 `demo_editor`
- server 端 actor 绑定生效，allowlist source 匹配
- 浏览器没有裸 mutation key
- backend 缺 key 返回 `401`
- 错误 `Origin` 返回 `403`
- Vite Node 同源 GET 正常

打开 `#changes` 后，仍只能改 manifest allowlist source 的当前正文。preview、确认提交和 GET 恢复的原 B4 契约没有被统一入口放宽，详见 [受控变更契约](controlled-mutations.md)。

## `--prepare-only` 只准备，不启动

```bash
uv run python scripts/workbench.py demo --prepare-only
uv run python scripts/workbench.py demo --mode controlled --actor demo-editor --prepare-only
```

`--prepare-only` 只完成对应模式的隔离副本准备，不启动 API 或 web。readonly 的准备会产出新 seed；controlled 的准备会产出新的私有 scope、database 和 manifest。它只表示准备完成，不表示演示通过，也不表示验收通过。

## accept 默认是 readonly suite

```bash
uv run python scripts/workbench.py accept
uv run python scripts/workbench.py accept --suite full
```

`accept` 默认等价于 `--suite readonly`。套件范围如下：

| `--suite` | 编排范围 |
| --- | --- |
| `readonly`（默认） | seed、management、evaluation |
| `full` | seed、management、evaluation、mutations |
| `management` | 只跑管理验收 |
| `evaluation` | 只跑评测工作台验收 |
| `mutations` | 只跑完整 B4 隔离变更验收 |

`readonly` 默认只编排 seed／management／evaluation。`full` 才会显式加入 mutations。`accept` 不接受 `--actor`；mutations 组件继续复用原 B4 driver 的验收身份和私有根约束。

单选示例：

```bash
uv run python scripts/workbench.py accept --suite evaluation
```

发行验证需要额外打开：

```bash
uv run python scripts/workbench.py accept --suite full --with-distribution
```

`--with-distribution` 只是在所选 suite 后追加 wheel／sdist 构建、检查和隔离 smoke。它不会发布到 PyPI，不会创建 release、tag，也不会触发部署。

## timeout 和停止语义

```bash
uv run python scripts/workbench.py accept --suite readonly --timeout 900
```

`demo` 和 `accept` 都支持 `--timeout`。真实默认值是 `900` 秒，取值范围是有限正数 `(0, 86400]`。限额按组件分别计时，不是整套 suite 共用一个总时长；demo 的 launcher 也有界，不会无限常驻。

中断和停止语义按真实结果记录：

- `Ctrl+C` 的 demo summary 会记为 `stopped`
- launcher 退出码记录为 `130`
- 父进程退出码是 `1`
- `stopped` 不是评测 `passed`，也不是把演示说成验收成功
- 旧 B-R2 两次 demo 的 `cleanup_verified=true`、端口关闭与无 orphan 结论见 [原运行审计](releases/legacy-0.1.0.md#b-r2-统一入口)，不作为本次更名验证

一旦出现下面任意情况，父编排都不会汇总成 pass：

- driver 非零退出
- `checks_failed > 0`
- timeout
- receipt 或报告不可核验
- cleanup 无法确认，或只能记成 `cleanup_unknown`

## summary、receipt 和报告引用

每次有效的 `demo`／`accept` 调用都会新建 `ROOT/.knowledge/workbench/<uuid>/summary.json`。父编排只汇总本次 session 的白名单字段，例如组件状态、退出码、checks、任务序列、清理结果和 repo-relative 报告路径。

B4 是固定私有根的例外：本次 scope 的 `b4-acceptance-report.json` 仍可能位于 session 外，但只能通过本次 receipt 引用，不能借历史 scope 的通过报告来回填结果。

## 已验证 summary（历史）

B-R2 原 readonly／full 通过汇总、较早通过及首次 `report_invalid` 失败均见 [B-R2 原运行审计](releases/legacy-0.1.0.md#b-r2-统一入口)。历史 full 各组件 `passed`、exit 0、checks_failed 0、cleanup_verified true，distribution 82 项与 wheel／sdist smoke 通过；8 个必需文件纳入检查。旧路径保持原样，不把原 summary 迁到新目录来证明新候选通过。

## B-R2 历史复核记录

- 当时 Python `pytest -q` 为 1902 passed、5 skipped；前端 430 passed、2 skipped。
- 显式 Linux live E2E 为 2 passed（41.21s），普通回归的 2 个 live skip 不改写为通过。
- Ruff check 通过，format 218 files，mypy 192 sources，两份 schema 字节不变；这些结果不属于本次更名验证。

## 原脚本继续独立使用

统一入口只做编排和汇总，不删除也不合并原脚本。真实文档、management、evaluation、mutation、prepare、launcher 和 distribution driver 都继续保留独立调用方式与原有安全断言。详细契约和原命令见 [真实文档验收](real-knowledge-acceptance.md)、[管理 API](management-api.md)、[评测工作台](evaluation-workbench.md)、[本机启动器](live-workbench.md) 和 [受控变更](controlled-mutations.md)。
