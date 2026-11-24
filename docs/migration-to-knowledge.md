# 迁移到 Knowledge

项目已统一使用 Knowledge，GitHub 仓库为 `Ykontheway/knowledge`。新包 `knowledge-ykforward==0.1.0` 目前仍是 Alpha 候选，尚未发布到 PyPI；旧发行审计见 [旧 0.1.0 记录](releases/legacy-0.1.0.md)，不能拿旧发布结果证明新包已可安装。

## 安装名与导入名不同

| 用途 | 当前名称 |
| --- | --- |
| 展示名／仓库目录 | Knowledge／`knowledge` |
| Python distribution（pip／uv 包索引名） | `knowledge-ykforward` |
| Python import | `knowledge`，例如 `from knowledge import KnowledgeLibrary` |
| CLI | 仅 `knowledge`、`knowledge-mcp` |
| Python 模块入口 | `python -m knowledge` |
| 默认运行目录 | `.knowledge/`，普通 CLI 默认库为 `.knowledge/knowledge.db` |

旧拼写的 import、CLI 别名及独立 MCP 命令已停止提供。更新代码导入、终端脚本和 MCP 客户端配置；不要把 Python import 写成 distribution 名。源事实、文档／单元／lineage／revision 身份、历史引用和 UUID 常量保持不变，更名不重写知识历史。

## 建议用新虚拟环境

使用 Python 3.11+ 和支持 FTS5 的 SQLite。新建环境可以避免旧包留下的入口混入 PATH；目前从源码安装：

```bash
git clone https://github.com/Ykontheway/knowledge.git
cd knowledge
python -m venv .venv
# Linux／macOS；Windows 使用对应的虚拟环境激活命令
. .venv/bin/activate
python -m pip install '.[api,mcp,tokens]'
knowledge --version
python -m knowledge --version
```

本地 wheel／sdist 隔离安装已核对，两项 version 输出均为 `knowledge 0.1.0`。只需 core 时使用 `python -m pip install .`；开发环境使用 `uv sync --locked --dev`，按需追加 `--extra`。仓库 `examples/` 不会由普通 pip 安装自动复制到当前目录。

以下仅展示**未来发布并验证后**的包索引安装写法，现在不要当作可执行的安装入口：

```bash
python -m pip install 'knowledge-ykforward[api,mcp,tokens]==0.1.0'
uv pip install 'knowledge-ykforward[mcp]==0.1.0'
```

## 旧库留在原处

旧隐藏目录不会自动搬到 `.knowledge/`，也不会自动合并。不要删除旧知识库，不要移动旧 session，或改写旧 summary／receipt 路径来制造新运行记录。先备份并核对原库用途和 schema，再决定是否使用新工具打开。

个人 Knowledge 知识库可通过显式路径继续选择原文件。把占位值换成现有库的真实绝对路径，不必为改名搬库：

```bash
knowledge list -d /absolute/path/to/existing/knowledge.db
knowledge search "检索问题" -d /absolute/path/to/existing/knowledge.db
knowledge mcp serve --database /absolute/path/to/existing/knowledge.db
# 等价独立 stdio 入口
knowledge-mcp --database /absolute/path/to/existing/knowledge.db
```

这里指兼容的项目知识数据库，不是任意 SQLite 文件。普通 CLI 打开可能执行 additive schema／FTS 初始化，所以即使 `list` 或 `search` 也应先备份并确认升级范围。默认只读 MCP 不建表、不升级、不回填 FTS；缺表／FTS 或 schema 不兼容时安全失败，准备与升级必须另行决定。不能把业务 SQLite 数据库直接作为可写 Knowledge 元数据库，更不能据此宣称生产可用。

## 演示标记重新生成

旧 demo markers、manifest、receipt、grant 和 session 是旧运行的审计证据，不是可搬迁的个人库。保留原记录，用新工具在新的 `.knowledge/` 隔离目录重新准备：

```bash
uv run knowledge demo build --force
uv run python scripts/workbench.py demo --prepare-only
uv run python scripts/workbench.py demo --mode controlled --actor demo-editor --prepare-only
```

`--force` 仅用于工具管理的新演示目录，不能指向个人知识库。使用本次输出的 database、manifest、scope／source ID，不复用旧 receipt 或批准 token；只读与受控准备结果不能混用。受控 MCP 仍只接受已准备的私有 sandbox 和 allowlist 当前正文，不开放任意业务库写入。统一工作台需要 Linux 的清理核验能力，macOS／Windows 不属于已验证范围。

新发行 workflow 契约已在本地核验：仅手动 `workflow_dispatch`、默认 `publish=false`，全部 CI gates 成功后才允许上传同次运行的已验证产物，上传阶段不 checkout、不 rebuild。远端 workflow 尚未执行，迁移文档不代表发布已获授权。见 [发布维护说明](releasing.md)。

## 2026-11-24 本地验收

GitHub 已更名为 `Ykontheway/knowledge`，项目目录已为 `knowledge`；locked sync 通过，依赖版本未变。Python 全量测试为 2673 passed、14 skipped；前端为 529 passed、2 skipped，preview 为 91 passed。wheel／sdist 隔离安装与验收均通过，跳过项不计为通过，详见 [本地验收记录](releasing.md#2026-11-24-本地验收)。

新 PyPI 包仍未发布，main 未合并，Pages 未重新部署。文档收尾后必须重新构建并验收，临时候选 hash 不作为最终发布 hash。
