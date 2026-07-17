---
name: odoo-e2e
description: 为本地 Odoo 12 项目准备隔离 PostgreSQL 数据库、启动临时 Odoo 实例，并运行 Playwright 端到端测试。用于执行、调试或复现 Odoo 端测，尤其适用于 /home/junge/.local/venvs/odoo12-e2e 虚拟环境、127.0.0.1:55432/postgres 数据库服务，或已有测试数据库/实例时必须新建隔离数据库且测试后必须终止端测进程的场景。
---

# Odoo 12 端到端测试

使用 `scripts/run_odoo_e2e.sh` 统一准备数据库、临时 Odoo 服务和 Playwright。每次运行必须使用不存在的新数据库，禁止直接在基准库或业务库上执行端测。

## 执行流程

1. 在项目根目录确认存在 `agui_chat/react_widget/package.json` 和 Odoo 插件目录。
2. 保持用户已有代码改动不变，不为端测重置或清理工作区。
3. 运行脚本。发现基准测试库时，同时克隆 PostgreSQL 数据库和对应 filestore；没有基准库时，用 Odoo 初始化新库。
4. 启动本次运行专用的 Odoo 进程；默认端口已占用时自动选择本地空闲端口。
5. 将新库名注入 `ODOO_E2E_DB`，运行项目已有的 `test:e2e:odoo`。
6. 无论成功、失败或中断，都终止并等待本次启动的 Playwright、浏览器和 Odoo 进程组退出；不要终止运行前已存在的进程。
7. 报告新数据库名、测试结果及日志路径。保留新数据库用于失败复盘，不自动删除。

## 运行命令

从项目根目录执行：

```bash
bash .agents/skills/odoo-e2e/scripts/run_odoo_e2e.sh
```

把额外参数原样传给 Playwright，例如只运行一个文件：

```bash
bash .agents/skills/odoo-e2e/scripts/run_odoo_e2e.sh integration-tests/qunit-host.spec.ts
```

先做无写入预检：

```bash
ODOO_E2E_DRY_RUN=1 bash .agents/skills/odoo-e2e/scripts/run_odoo_e2e.sh
```

## 配置

| 环境变量 | 默认值 | 用途 |
| --- | --- | --- |
| `ODOO_E2E_PROJECT_ROOT` | 当前目录 | Odoo 插件项目根目录 |
| `ODOO_E2E_VENV` | `/home/junge/.local/venvs/odoo12-e2e` | Odoo 12 Python 虚拟环境 |
| `ODOO_E2E_ODOO_ROOT` | `/home/junge/pros/odoo12` | 包含 `odoo-bin` 的源码目录 |
| `PGHOST` / `PGPORT` | `127.0.0.1` / `55432` | PostgreSQL 地址 |
| `PGUSER` / `PGDATABASE` | `odoo` / `postgres` | PostgreSQL 角色和维护数据库 |
| `ODOO_E2E_SOURCE_DB` | `odoo12_agui_e2e` | 只读克隆的基准测试库 |
| `ODOO_E2E_SOURCE_DATA_DIR` | `~/.local/share/Odoo` | 基准库 filestore 所在 Odoo 数据目录 |
| `ODOO_E2E_DB` | 自动生成 | 本次新库名；显式指定时也必须不存在 |
| `ODOO_E2E_HTTP_PORT` | `18069` 或空闲端口 | 临时 Odoo 服务监听端口 |
| `ODOO_E2E_LOGIN` / `ODOO_E2E_PASSWORD` | `admin` / `admin` | Odoo 测试登录凭据 |

认证优先使用标准 libpq 环境变量和 `.pgpass`。不要把数据库密码写进技能、项目文件或命令输出。

## 约束

- 只把名称匹配 `[A-Za-z0-9_]+` 的数据库作为源库或目标库，避免 SQL 和 `db-filter` 注入。
- 目标库已存在时立即停止，不覆盖、不升级、不删除它。
- 仅在脚本本次创建的数据库准备失败时删除残缺库；测试失败后保留完整隔离库。
- 必须通过独立进程组运行端测和临时 Odoo，退出清理先发送 `TERM`，超时后发送 `KILL`。
- 不自动安装依赖。缺少 `pnpm`、PostgreSQL 客户端、虚拟环境或 Odoo 源码时，报告缺项并停止。
