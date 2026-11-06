# 数据源与知识库管理实施进度

目标：在独立 Git worktree 完整实施同目录 `2026-11-05-data-source-knowledge-management.md`。当前状态为进行中，不能将本文件中的局部测试结果视为整份计划完成。

## 工作区

- 主目录：`/home/junge/pros/smart_reporting`，本次实施不修改此目录的应用代码。
- 原生管理 worktree：`/home/junge/.codex/worktrees/dc7b/smart_reporting`。
- 分支：`feat/data-source-knowledge-management`，基线 `4b543a53`。
- worktree 有独立 `.venv`，已通过 `uv sync --frozen --no-install-project --python 3.12` 安装；不依赖主目录 `.venv` 或临时密码库目录。
- 独立测试 PostgreSQL 18 容器：`reporting-management-test-db`，仅本机 `55439` 端口，库名/用户 `management_test`。不使用生产库。

## 任务状态

| 任务 | 状态 | 当前证据或剩余工作 |
| --- | --- | --- |
| 1 admin 登录、迁移、审计 | 进行中，核心后端已实现 | 13 项认证测试、组织范围事务测试通过；实际应用完整启动和浏览器验证尚未做 |
| 2 数据源版本与凭据 | 已完成后端阶段 | 6 项真实 PG 集成测试通过；连接测试、目录同步和页面尚未完成 |
| 3 目录/Profile/导入 | 进行中，核心后端已实现 | Profile、Catalog 版本、dry-run/幂等导入和 API 已有定点测试；实际 StarRocks 连接测试、CLI 和完整对账尚未完成 |
| 4 按运行冻结配置 | 未开始 | 必须覆盖 `_source`、恢复和可信 scope 来源 |
| 5 管理前端 | 未开始 | 当前页面文件缺失时返回 503，不能宣称登录 UI 已完成 |
| 6 文档版本与存储 | 未开始 | 维持业务知识与技术知识分离 |
| 7 Agno 索引与 worker | 未开始 | 需在新锁定环境复核 Agno 失败/过滤语义 |
| 8 知识管理与检索页面 | 未开始 | 依赖 6、7 |
| 9 报告知识引用 | 未开始 | 冻结成功才允许进入生成上下文 |
| 10 部署与完整验收 | 未开始 | 全量检查、浏览器、真实报告、备份恢复均未执行 |

## 2026-11-06 已完成的实现

- 新增 `management` 模块：Argon2id 密码、随机会话（哈希落库）、30 分钟闲置/8 小时绝对过期、账号登录锁定、CLI 初始化和重置、改密全会话撤销。
- 使用 PostgreSQL 短事务 advisory lock 协调账号初始化、登录最终提交、改密及会话操作；密码计算在线程中执行。登录验证后的 authVersion 再核对避免旧密码并发签发。
- 新增管理 API 与受保护路由，独立 Cookie、Origin/CSRF 检查、审计分页；应用挂载管理入口；管理写请求限制为 64 KiB（文档上传时需要增加专用路径限制）。
- 管理输入校验错误不回显原始输入；存储不可用为 503，认证无效为 401。
- Alembic `0001_admin` 仅管理独立 schema；初始化/恢复 CLI 隐藏读取密码，不接受密码命令行参数。
- 依赖声明与 `uv.lock` 已更新；uv 新版本会归一化旧平台 marker，保留原生生成锁文件，`uv lock --check` 通过。

## 实际验证结果

1. 开始前定点基线：`test_database.py`、`test_report_data_sources.py`，16 passed。
2. 新环境真实 PostgreSQL 18：`test_management_access.py`、`test_management_persistence.py`、`test_management_migration.py`，13 passed（39.08 秒）。显式 `-m integration`，没有 skip。
3. 既有请求回归：`test_reporting_request_identity.py`、`test_http_request_limits.py`，43 passed。
4. 新增管理模块及三份测试 Ruff check/format 通过；`git diff --check` 通过。
5. 管理模块定点 mypy：`--follow-imports=silent`，9 个源码文件无问题。未抑制管理文件内的错误；跟随其他项目模块的检查曾报告未修改报告代码中的 297 项错误（23 个文件），还未执行基线对比，不可据此声称完整项目类型检查通过。
6. 依赖锁文件：`uv lock --check` 通过。

复现集成测试：设置 `REPORTING_MANAGEMENT_TEST_DB_URL` 为**专用可清空测试库**的 SQLAlchemy PostgreSQL URL，再运行：

```bash
.venv/bin/python -m pytest -q -m integration \
  smart_reporting/tests/test_management_access.py \
  smart_reporting/tests/test_management_persistence.py \
  smart_reporting/tests/test_management_migration.py
```

测试会重建 `reporting_management` schema；不得设置为生产/开发业务库。最后的迁移测试会创建一个测试 admin，不能把它作为部署初始化步骤。

## 下一步

补齐任务 3 的 Profile API、配置导入、Catalog 元数据版本和实际连接测试，再进入任务 4 的运行配置冻结。最终收尾只运行一次完整检查；当前没有运行完整测试，也没有完成计划 A1–O1 的上线验收。
