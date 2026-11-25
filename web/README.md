# Knowledge CI 知识工作台

这是用于查看知识生命周期、追溯历史证据和对照检索质量的多模式前端工作台。各模式的数据来源和权限边界分开，不用静态数据冒充实时结果。

## 数据模式

- **版本快照**：总览、原文溯源和版本 Diff 使用 `demo/snapshot.json`，保留 Snapshot V1 标识。这是固定版本的展示，不代表实时状态。
- **静态回放**：生命周期、评测对照和使用导览读取 `web/public/replay.json`。数据来自合成公开语料，页面只读、非实时，不请求 live API，不观察新任务。加载失败时显示错误，不回退到实时服务或伪造数据。
- **本机只读工作台**：通过同源 `/v1/management` 读取任务、版本和历史证据，需要服务端授权。无管理服务时停在安全提示，版本快照仍可访问。三阶段对照由用户手动选择，不能仅凭通过、失败、恢复通过的顺序声明因果。
- **受控更新**：默认关闭，仅限服务端明确授权的隔离副本和当前文档。预览不会提交，提交前需核对身份、范围、原文差异和 checksum，再显式确认。浏览器不接收或保存密钥；确认令牌仅短暂保留在内存。门禁失败不回滚，停止等待不取消后端操作，404 不能证明未写入。内存中仍有原请求时，只能用相同 payload 和同一幂等键重试；刷新或离开后令牌丢失，只能按命令 ID 回查，不能自动新建提交。

## 兼容入口

前端包名为 `knowledge-workbench`，它与 Python distribution `knowledge-ykforward` 是不同的包。Python import 为 `knowledge`，CLI 为 `knowledge`／`knowledge-mcp`，新 distribution 尚未发布，旧入口停止提供；默认运行根改为 `.knowledge/`，旧库与 session 不自动搬迁，见 [迁移说明](../docs/migration-to-knowledge.md)。版本快照入口仍为 `#overview`、`#trace`、`#diff`，静态回放使用 `#replay/guide` 等回放路由，本机只读页面使用 `#lifecycle`、`#evaluation`、`#guide`，受控变更使用 `#changes`。

在 `web/` 中，`pnpm dev` 用于本机开发，`pnpm verify` 用于常规完整验证，`pnpm verify:preview` 用于独立只读构建。该预览会输出到 `dist-preview/`，默认使用 `#replay/guide`，不触发公开发布。快照校验命令 `knowledge demo export --check`、类型生成命令及现有路径名称保持不变；命令和路径中的 `demo` 不作替换。

<!-- 文档校对记录
本次仅压缩 web/README 的校对记录，并补清本机开发、常规验证和只读预览构建的用户命令说明。
`pnpm dev` 用于本机开发，`pnpm verify` 用于常规完整验证，`pnpm verify:preview` 只生成只读 `dist-preview/`，默认 `#replay/guide`，不触发公开发布。
工作台数据边界、现有命令名和页面路由未改；技术片段按原意保真。
已做中文半角标点机械扫描，结果为 0；代码、命令、路径、URL 中的半角语法按规则豁免。
-->
