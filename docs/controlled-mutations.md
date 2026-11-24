# 受控变更工作台（B4）

B4 的更名前实现与隔离验收已完成，旧结果见 [历史审计](releases/legacy-0.1.0.md#b4-受控变更)。当前新 distribution `knowledge-ykforward==0.1.0` 仍是未发布候选；受控变更默认关闭、不自动打开、不发布到公开环境。它只面向 `scripts/prepare_mutation_demo.py` 生成的隔离演示库，用来演示“知识提交后立即触发评测、失败也保留审计”的完整链路。

相关导航：

- [README 概览](../README.md)
- [本机工作台启动说明](live-workbench.md)
- [前后端一体化演示路线](integrated-demo-roadmap.md)
- [评测对照与导览](evaluation-workbench.md)

## 一分钟启动

推荐直接用准备脚本和启动器，不手配数据库、副本目录或写密钥。

```bash
uv run python scripts/prepare_mutation_demo.py
```

脚本会新建一个独占、私有的运行目录，例如 `.knowledge/mutation-demo/<scope-id>/`，并输出这次运行的：

- `manifest`：`mutation-manifest.json`
- `database`：隔离副本里的 `knowledge.db`
- `scope_id`：这次写演示的作用域
- `source_ids`：允许编辑的 source allowlist

拿到上一步输出的实际路径后，再显式启用 B4：

```bash
uv run python scripts/live_workbench.py \
  --database "<mutation-demo-run-directory>/knowledge.db" \
  --web-port 5175 --api-port 8015 \
  --mutation-manifest "<mutation-demo-run-directory>/mutation-manifest.json" \
  --mutation-actor demo-editor
```

要点：

- `--mutation-manifest` 和 `--mutation-actor` 必须一起提供；只给一个会直接失败。
- `mutation_actor` 必须是安全的本机 ASCII 身份标识；服务端会把它绑定到 mutation 审计记录。
- 启动器会为这次联调临时生成独立的读取 key 和写入 key，两者不能相同。
- 浏览器不持有 key。浏览器只发同源请求；Vite Node 代理代发 Bearer 写请求，backend 在自己的环境里校验独立写 key。
- `prepare_mutation_demo.py` 只接受它自己新建的私有目录、`mutation-manifest.json` 和同目录 `knowledge.db`；不复用共享库，不接业务数据库。

## 页面流转

B4 页面入口是 `#changes`。

典型流程：

1. 进入 `#changes`，服务端返回当前 actor、scope 和允许编辑的 source 列表。
2. 在“授权来源”里选择 source，页面只读取该 source 当前 head document 的正文。
3. 在文本框里改正文，点击“预览变更”。
4. 页面显示服务端生成的完整 Diff、变更计数和 5 分钟 TTL 预览。
5. 勾选明确确认框后，才能点击“确认并提交”。
6. 成功后跳到 `#changes?command=<id>`，再链接到 `#lifecycle/...` 和 `#evaluation`。

如果提交响应在浏览器侧丢失，页面不会自动再发一个新写请求，而是进入“结果不确定”状态，改为按原幂等键做命令回查或原请求重试。

## 后端契约摘要

B4 的 HTTP 路由前缀是 `/v1/mutations`，默认 **不挂载**。只有显式启用后才可用。

| 路由 | 方法 | 作用 | 关键边界 |
| --- | --- | --- | --- |
| `/session` | GET | 返回 actor、scope、capabilities 和允许编辑的 sources | 需要独立写 key；只返回 allowlist 会话信息 |
| `/documents/{document_id}` | GET | 返回当前 head document 的正文 | 只允许当前文档，不允许历史 document |
| `/previews` | POST | 生成服务端预览 | 只预览，不提交知识，不触发评测 |
| `/commands` | POST | 应用一次确认过的命令 | 使用幂等键；事务内写命令、revision 和 auto-evaluation outbox |
| `/commands/{command_id}` | GET | 按命令 ID 或原幂等键回查结果 | 用于响应丢失后的恢复，不再新建写入 |

只读 GET 不能创建 mutation 表，也不能启动评测。默认不启用 B4 的应用保持 `/v1/mutations/*` 为 404，普通只读 GET 不会偷偷补 schema 或打开评测路径。

## 允许写什么，不允许写什么

B4 只允许做一类写入：**修改 manifest allowlist 中 source 的当前正文**。

明确边界如下：

- 只接受 `prepare_mutation_demo.py` 生成的隔离 demo 库。
- manifest 只允许最多 16 个 source，且必须和库内实际 source 集合严格匹配。
- 只允许 `file` / `manual` 来源、`markdown` / `text` 文档类型。
- 只允许当前 head document；历史 document 会返回冲突，不会覆盖旧版本。
- 页面只编辑正文，不接受浏览器文件路径、数据库路径、SQL 凭据、DSN 或任意写目标。
- preview 和 command 都要求严格 JSON、UTF-8、无重复 key；正文上限 64 KiB，请求体上限 128 KiB。
- 浏览器不保存确认 token，不写入 URL、`localStorage`、`sessionStorage` 或日志。

## preview 和 command 的绑定关系

服务端 preview 会记录完整绑定条件，不会把文本当成随手预览的临时内容。它会把下面这些信息绑在一起：

- `source_id`
- 当前 `document_id`
- 旧 `expected_checksum`
- 新正文的 `new_checksum` / `text_fingerprint`
- `actor_id`
- `scope_id`
- TTL（300 秒）
- `confirmation_token`
- Diff 计数和完整 Diff 内容

提交 command 时，客户端还必须额外给出：

- `preview_id`
- `confirmation_token`
- `idempotency_key`
- `confirmed: true`

`confirmed` 必须是 JSON 布尔值 `true`；不是字符串，也不能省略。

## 幂等、事务与评测

B4 的写入恢复靠固定幂等键，不靠“再点一次试试”。

关键行为：

- command 先把 `scope`、`actor`、`preview_id`、`confirmation_token hash`、`idempotency_key`、`confirmed` 绑定成请求指纹。
- 事务从 `BEGIN IMMEDIATE` 开始，在真正写入前先校验 preview、TTL、checksum 和自动评测配置。
- 如果同一个 `idempotency_key` 已存在：
  - 请求指纹完全相同，直接返回原结果；
  - 指纹不同，返回 `409 idempotency_conflict`。
- mutation command、知识 revision、publication revision 和 auto-evaluation outbox 在同一个事务内落库。
- `after_commit` 阶段即使评测失败，也**不回滚已提交知识**；知识提交与评测失败会明确分开显示。
- 结果不确定时，不自动发新写请求，也不自动重试；恢复路径是 `GET /v1/mutations/commands/{command_id}` 或用原 payload 重试同一幂等键。

因此，B4 支持两件事同时成立：

1. 写入已经成功落库；
2. 评测失败，或者浏览器没收到那次成功响应。

这是设计里明确保留的可恢复状态，不属于异常分支。

## 与 B3 导航的衔接

B4 不做“改完就结束”的孤立页面，直接接到 B3 的证据导航：

- command 结果会给出 `revision_ids` 和 `job_ids`；
- 页面可继续跳到 `#lifecycle/jobs/<id>`、`#lifecycle/revisions/<id>`、旧新 document Diff 和 `#evaluation`；
- 恢复页 `#changes?command=<id>` 在刷新或重启后只做 GET 回查，不再隐式 POST；
- 旧失败记录、历史 Diff 和证据回查都要保留，不能因为后续恢复成功就被覆盖。

## 已有验收事实

B4 最后一次历史隔离验收报告及原路径见下方审计链接；以下数量不属于本次更名验证：

- [B4 原始运行记录](releases/legacy-0.1.0.md#b4-受控变更)

报告结论：

- `status=passed`，全部 checks 为 true，frontend_update 与 frontend_recovery 均为 passed。
- 三次变更产生的 command 与 jobs 恰好各 3。
- 同一套固定 config fingerprint 和 dataset 下，任务链路是 `passed → failed → passed`。
- mean Recall 为 `1 → 0.6666667 → 1`。
- 真实前端验收覆盖：
  - commit 后浏览器响应丢失；
  - 按命令 GET 恢复且不重复写；
  - 浏览器不持久化凭据或确认 token；
  - 重启后 `#changes?command=<id>` 只做 GET 恢复；
  - 历史失败、Diff 和证据仍可回查。
- B4 完整 driver 另跑已通过，`children_stopped=true`。
- 静态渲染检查显示 `#changes` 初始页面布局正常、无 console errors；恢复入口静态中间状态显示清楚。这里仅说明静态页面检查结果，真实交互验收来自 jsdom + HTTP driver。
- 历史发行验证的原目录与通过记录见 [B4 审计](releases/legacy-0.1.0.md#b4-受控变更)；这不代表已发布，本次也没有做发布动作。
- 生产 build 仍有 584.87 kB chunk 体积提醒，属于后续可优化项，不是功能失败。

本轮前端 `pnpm verify` 已包含 mutationtypecheck 和 check:mutations，typecheck、类型漂移、测试和 build 全通过，结果为 `352 passed / 2 skipped`。两个 skipped 是需要联调服务环境的 live acceptance 默认跳过，不是假失败。

## 不在 B4 范围内的事

下面这些都不属于当前 B4：

- 任意来源写入、候选批准写入、时效操作写入
- 自动重试不确定写请求
- 自动回滚知识或自动接受 baseline
- 浏览器直接持有 Bearer key
- preview / dist 静态构建里的写代理
- PR、main 合并、tag、公开部署、PyPI 发布

B5 / U22 MCP 也还没有实现。

<!-- 文稿复核：已回读事实、行文和节奏。机械扫描中文半角标点 0（排除 URL／路径／inline code 命中）、长破折号 0、编号／量词标题 0、对比句式 0、元话语 0。事实账本：仅记录 B4 已实现的默认关闭、独立写密钥、actor 绑定、manifest allowlist、#changes 流程、幂等恢复、事务与最新 scope b239f388-6ef5-401f-879b-e43cf59fb68e 隔离验收；补齐 352／2、发行包隔离 smoke、静态渲染和 584.87 kB 非阻断提醒；未写入密钥、正文或内部技能内容。 -->
