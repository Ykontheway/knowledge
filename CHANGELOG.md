# 变更记录

## 0.1.0 更名候选（未发布）

- 项目展示名统一为 Knowledge，GitHub 仓库为 `Ykontheway/knowledge`。
- Python distribution 为 `knowledge-ykforward`，Python 导入为 `knowledge`，CLI 仅保留 `knowledge` 与 `knowledge-mcp`；模块入口为 `python -m knowledge`。旧拼写的 import 和 CLI 不再提供兼容入口。
- 版本仍为 `0.1.0` Alpha。新 distribution 尚未发布到 PyPI，当前使用源码安装；没有新发布 hash、Actions run、tag、GitHub Release 或 main 合并结论。
- 默认运行目录改为 `.knowledge/`。旧目录不自动搬迁，不删除旧库，不移动旧 session；个人知识库可显式指定现有路径，演示 markers／receipt 应由新工具重建。详见 [迁移说明](docs/migration-to-knowledge.md)。
- 源事实、历史引用、UUID 常量和冻结数据契约不因更名改变。旧发行不能换名成为新发行；此前发布、开发、验收及失败记录集中保留在 [旧 0.1.0 发布审计](docs/releases/legacy-0.1.0.md)。
- 新发布 workflow 契约已在本地核验：仅手动 `workflow_dispatch`，`publish` 默认 `false`，不因 push 自动上传；源码固定为当次 `github.sha`，所有 CI gates 通过后上传同次运行的已验证 artifact。manifest 核对项目名、版本、文件名与 SHA256；publish job 不 checkout、不 rebuild，secret 仅给上传步骤。远端尚未运行，文档不代表发布已获授权。见 [发布维护说明](docs/releasing.md)。

### 2026-11-24 本地验收

- GitHub 已更名为 `Ykontheway/knowledge`，项目目录已为 `knowledge`；`uv sync --locked --dev` 通过，依赖版本未变。Ruff check／format 检查 256 个文件通过，mypy 检查 221 个源文件通过，actionlint 自动检查全部 3 个 workflow 通过，发布 workflow／manifest 的 123 项测试通过。
- 清除 `PYTHONPATH` 并设置 `GITHUB_ACTIONS=true`、`NO_COLOR=1`、`TERM=dumb` 后，Python 全量测试为 2673 passed、14 skipped，耗时 580.14 秒。前端 `pnpm verify` 为 529 passed、2 skipped，`pnpm verify:preview` 为 91 passed，预览构建产物检查包含 17 个允许资源；普通与 preview 构建均通过，现有 606 kB chunk warning 未修。跳过项不计为通过。
- snapshot 重新生成仅有 schema `$id` 的新 URL diff，snapshot JSON 不变；wheel／sdist 隔离验收均通过，详见 [本地验收记录](docs/releasing.md#2026-11-24-本地验收)。文档收尾后须重新构建并验收，不把临时候选 hash 作为最终发布 hash。
- 以上仅为本地验收。远端 workflow 尚未执行，新 PyPI 包未发布，main 未合并，Pages 未重新部署。

## 历史记录入口

[旧 0.1.0 发布审计](docs/releases/legacy-0.1.0.md) 保留 2026-11-23 首次 PyPI 发布、原源码与上传提交、文件名及 SHA256、原 Actions URL、发布后安装验收，以及 U／B 阶段的开发记录与原始运行路径。历史统计只属于各自阶段，不计入本次更名验证。
