# 发布维护说明

本页说明 Knowledge 的新发行候选如何准备和审核。旧发布审计集中保留在 [旧 0.1.0 记录](releases/legacy-0.1.0.md)，不把旧文件、hash、源码提交或 Actions run 改名为新发行证据。

## 新发行仍是候选

当前目标是 `knowledge-ykforward==0.1.0` Alpha，尚未发布到 PyPI。实现完成、候选构建通过、包发布、main 合并、tag、GitHub Release 和 Pages 部署分别记录，任何一项都不自动证明其他项完成。源码安装及命名区别见 [迁移说明](migration-to-knowledge.md)。

| 核对位置 | 目标值 |
| --- | --- |
| `pyproject.toml` | `project.name = "knowledge-ykforward"`，`project.version = "0.1.0"`，Python `>=3.11`，Alpha classifier |
| `src/knowledge/__init__.py` | `__version__ = "0.1.0"`，lazy `KnowledgeLibrary` 导出 |
| `uv.lock` | editable `knowledge-ykforward` 记录，版本 `0.1.0` |
| console scripts | 仅 `knowledge = knowledge.cli:main`、`knowledge-mcp = knowledge.mcp.server:main` |
| 导入与模块运行 | `import knowledge`、`python -m knowledge`，不使用 distribution 名作为 import |
| 仓库地址 | `https://github.com/Ykontheway/knowledge` |

如元数据或依赖改动，使用 `uv lock` 生成锁文件并审阅 diff，不手工改一处来凑版本一致。不要清理或重置其他协作者的工作来制造干净工作区。

## 本地检查与隔离安装

本地验收结果见下方 2026-11-24 记录。以下命令保留供维护者复核，不表示远端 workflow 已运行：

```bash
uv sync --locked --dev
uv run pytest tests/test_release_metadata.py tests/test_project_naming.py tests/test_pypi_workflow.py
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests scripts
uv run pytest --cov=knowledge --cov-report=term-missing
uv run knowledge demo build --force
uv run knowledge demo export --check
uv run pytest tests/test_evaluation_gate_demo.py
uv run python scripts/export_management_schema.py --check
uv run python scripts/export_mutation_schema.py --check
uv run --frozen python scripts/export_replay.py --check --output web/public/replay.json
uv run python scripts/verify_distribution.py --output-dir release-verification
```

前端在 `web/` 下运行 `pnpm install --frozen-lockfile`、`pnpm verify` 和 `pnpm verify:preview`。PostgreSQL、LanceDB、MCP 和 Linux live 用例按各自合成隔离环境验收，不连接用户生产数据库；默认 skip 不计为通过。

发行验证必须检查 wheel／sdist 的 distribution metadata、`knowledge/` 包路径、PEP 561、打包语料、仅有的新 CLI 与运行数据排除规则。每种产物在仓库外新环境安装，确认 import 来自 `site-packages`；先证明 core-only help／version 与缺 extra 安全失败，再对同一产物验证可选能力。demo、引用、历史检索、baseline 比较、通过和阻断门禁均须保留。旧 import／CLI 的停止使用也须检查，不能由源码 checkout 掩盖隔离安装问题。

## 2026-11-24 本地验收

- GitHub 已更名为 `Ykontheway/knowledge`，项目目录已为 `knowledge`。`uv sync --locked --dev` 通过，依赖版本未变；Ruff check／format 检查 256 个文件通过，mypy 检查 221 个源文件通过，actionlint 自动检查全部 3 个 workflow 通过。
- 清除 `PYTHONPATH`，设置 `GITHUB_ACTIONS=true`、`NO_COLOR=1`、`TERM=dumb` 后，`python -m pytest --cov=knowledge` 全量结果为 2673 passed、14 skipped，耗时 580.14 秒。跳过项不计为通过。
- 前端 `pnpm verify` 为 529 passed、2 skipped；`pnpm verify:preview` 为 91 passed。预览构建产物检查包含 17 个允许资源，回放为 3 个 job、263215 字节，普通与 preview 构建均通过；现有 606 kB chunk warning 未修。snapshot 重新生成仅有 schema `$id` 的新 URL diff，snapshot JSON 不变。
- 发布 workflow／manifest 的 123 项测试通过。下节所列手动触发、当前源码 SHA、完整 CI gates、同次运行 artifact、manifest 校验及上传隔离契约均已在本地核验，远端尚未执行。
- wheel／sdist 在隔离环境中分别通过 core 9 项检查、CLI 6 步、demo 8 步、evaluation 6 个 case／42 个 gate，以及 quality 10 项检查／30 个 case／1000 个 unit；API 10 项、tokens 6 项、PostgreSQL 6 项检查均通过。
- 每种产物的只读 MCP 15 项检查通过，各有 18 次成功调用、39 次预期拒绝；受控 MCP 17 项检查通过，各有 36 次成功调用、17 次预期拒绝。成功调用与预期拒绝分别统计，不将拒绝或跳过项写成成功调用。
- 真实候选文件名为 `knowledge_ykforward-0.1.0-py3-none-any.whl` 和 `knowledge_ykforward-0.1.0.tar.gz`。本次文档收尾后必须重新构建并验收，sdist hash 会变化；不记录临时候选 hash，也不将其作为最终发布 hash。

以上仅为本地验收。新 workflow 尚未远端运行，新 PyPI 包未发布，main 未合并，Pages 未重新部署。

## 仅手动发布已验证产物

**新 workflow 的 YAML 与测试契约已在本地核验，远端尚未执行。以下说明已核验的本地配置及仍需远端确认的事项，不代表新包已发布。**

- PyPI workflow 仅接受 `workflow_dispatch`，`publish` 为 boolean，默认 `false`。旧 push marker 触发路径已移除，不因 feature／main push 或提交消息自动上传。
- 手动执行默认只做候选验证。上传 job 依赖全部 CI gates 成功：受支持 Python 版本、静态检查、行为测试、冻结 demo／schema／回放漂移、固定时间回归门禁、前端与 preview 验证、发行 metadata 和各隔离 smoke，以及 PostgreSQL、LanceDB lane。配置依赖已本地核验，各远端 lane 尚未运行。
- 只有显式 `publish=true`、所有必要 gates 成功并获发布授权，上传 job 才能下载并上传**同一次 workflow run** 验证的 artifact。构建一次，后续检查和上传复用同一 wheel／sdist；publish job 不 checkout、不运行仓库代码、不 rebuild，也不取旧 run 或任意 ref 的产物。
- 源码固定为当次 `github.sha`，不使用旧 release SHA。manifest 绑定该 SHA，严格核对项目名 `knowledge-ykforward`、版本 `0.1.0`、两个真实文件名和 SHA256，上传前再次校验。不在文档中预填新 hash／run，不把旧文件重命名当成新包。
- token 仅通过 secret 环境变量提供给上传步骤，不打印明文或传给其他步骤。远端 secret、项目身份、environment、默认分支 dispatch 可用性和所选 ref 仍需维护者确认。
- gate 阻断退出 `3`、无效证据退出 `2`、运行／I/O 失败退出 `1`，任何失败都不能转为无条件成功或继续上传。CI artifact 存在不等于 PyPI 发布成功。

本地 YAML、manifest 与测试核验不能替代远端 Actions 运行、发布授权或 PyPI 上传结果。

## 外部动作分别授权

main 合并／推送、tag、GitHub Release、PyPI 和静态站点发布都需分别获得明确授权。CI 通过不自动授权发布；本次文档工作不执行 git add／commit／push 或部署。

Pages 发布也须单独核对手动 dispatch、默认 `publish=false`、已验证 artifact、GitHub Actions Source、environment 保护及更名后的 base path。旧站点可访问的历史结果见 [审计记录](releases/legacy-0.1.0.md#静态回放发布与验收)，不能据此宣布新地址已上线。

## 上传后再写可安装

仅在上传真正成功后，记录新 distribution 的真实 PyPI URL、源码 SHA、workflow SHA／run、wheel／sdist 文件名和 SHA256。独立核对索引与下载字节，在仓库外新环境分别安装 wheel／sdist，检查 `import knowledge`、`knowledge --version`、`knowledge-mcp` 和 `python -m knowledge --version`，再运行离线端到端 smoke。

各 extra 与平台的已测／未测范围分别写清。只有索引确认和安装验收完成后，README 才能写“已发布／可安装”；任一渠道失败就如实记录，不删失败记录或覆盖旧发行证据。
