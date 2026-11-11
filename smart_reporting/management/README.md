# 管理工作台交付与验收

管理工作台只深化机构范围、数据源草稿与发布任务。React 19、Ant Design 6、React Router 7、TanStack Query 5 分别承担页面、统一控件、导航和服务端状态；报告编辑器保持独立入口。

## 构建与启动

在 `smart_reporting/report_editor/frontend` 执行：

```bash
npm ci
npm run build:management
npm run check:management-budget
```

管理入口为 `/management/`，规范跳转 `/management/sources`；匿名用户进入登录。部署需要 `AGENT_MANAGEMENT_PUBLIC_ORIGIN`，连接写入需要 `AGENT_MANAGEMENT_CREDENTIAL_KEYS`。账号初始化及重置沿用现有 CLI，不在页面、日志或示例配置中保存默认密码。

完整镜像必须先构建报告编辑器，再构建管理入口。编辑器构建会清空父 static 目录，不能反向执行。Dockerfile 将最终产物放在 `/opt/report-editor-static/management`，源码 bind mount 不会覆盖它。单独构建管理页面只清理自己的输出目录。

`sourceId=new` 仍为合法标识；它的详情使用 `/management/sources/new/view`，编辑使用 `/management/sources/new/edit`，与创建页 `/management/sources/new` 分离。

## 变更的真实含义

- 编辑默认保留已有连接；省略 DSN 不生成新凭据，显式 null 或空串非法。更换数据库时必须提供匹配的新连接。
- 草稿版本用于乐观并发控制。待发布状态比较内容 hash，不比较草稿版本号与发布 revision。
- 发布前预检不锁定发布条件。正式提交仍核验 expectedVersion、组织与已发布依赖。
- 发布成功说明配置版本已登记，不代表数仓连接正常或所有运行已立即切换。已运行报告保留冻结配置。
- 目录的历史结构只有同步时间，没有发布时间。版本选项返回 `publishedAt:null`、实际 `syncedAt`，不冒充已知发布时间。
- 写请求不自动重试。结果未知时先读回，比较公开字段，由用户选择采用服务器或保留本地输入；连接明文无法通过公开回执核实。
- 401 清理会话与业务缓存；当前密码错误不撤销仍有效会话。密码、DSN 和 CSRF token 不写入 URL 或持久浏览器存储。

## 隔离验收

真实数据库测试使用专用 PostgreSQL，不能指向业务库。现有 pytest fixture 会删除 management schema，执行前必须检查目标。

`isolated_server.py` 只允许显式提供 `127.0.0.1:55439/management_test`（或 localhost）；缺少地址直接失败，不读取业务 `.env`。将测试库密码通过环境或秘密管理工具注入，勿写在命令记录中。

```bash
# 先安全设置 REPORTING_MANAGEMENT_TEST_DB_URL。
.venv/bin/python scripts/management/isolated_server.py --reset-test-data
```

服务在 `http://127.0.0.1:7789` 启动完整 AgentOS。该命令明确重建专用 management 测试 schema，创建两机构同 ID 源、55 行分页样本、空机构及发布依赖；临时账号凭据写入 `/tmp/management-depth-credentials.json`，权限 0600。不使用业务 admin，也不连接真实数仓或模型。

前端目录执行：

```bash
npm run test:management
npm run test:e2e:management
node scripts/measure-management.mjs
```

浏览器测试必须串行。正常流程使用真实 HTTP；断网/响应丢失等通过浏览器路由注入故障，报告中单独列明。测试后可用 `scripts/management/verify_sql.py` 只读核对凭据记录数与发布事实。不要在浏览器测试运行时执行会重建同一 schema 的 pytest fixture。

构建预算读取 Vite manifest 的依赖图，登录 gzip 总量上限 300 KiB，登录后列表累计 500 KiB。构建插件同时拒绝引入编辑器、Office 或图表引擎依赖。性能脚本固定 Chromium、1440×900、4 倍 CPU、10 Mbps/100 ms，执行五次冷启动；截图仅用于促使 headless 合成待绘制帧，不记录密码。LCP 中位数上限 2.5 秒。

自动错误 DOM 快照可能包含密码字段值，故 E2E 使用显式脱敏上下文，不录 HAR、trace 或视频。截图仅在无密码输入的页面生成。归档仍需排查临时凭据，不能把测试账号密码作为报告内容。

## 发布与回退

1. 发布前记录当前镜像 digest、前端 manifest/hash、配置版本与加密 key ID；保留对应镜像及静态产物，不从当前工作目录猜测旧版本。
2. 候选后端与管理 bundle 作为同一版本验证：健康检查、根路径、登录、详情深链、静态资源、组织范围、保存及发布。不要把新 bundle 单独交给旧后台。
3. 先在隔离环境或预发布验证源码 bind mount 场景，再切换业务实例。生产发布、真实运维用户验收属于独立步骤。
4. 回退同时切换到上一镜像与它自带的 bundle。保持数据库、账号、不可变发布版本和全部历史加密密钥；不回退账号库，不删除已产生的版本或凭据。
5. 回退后再次检查健康、对应版本的页面路由与资源。如果上一版本不包含管理工作台，管理入口恢复 404 是回退该版本的明确结果，不能宣称旧工作台仍可用。

本轮工程证据见 `output/management-depth/` 和 `docs/superpowers/reports/2026-11-09-management-delivery.md`。其中用户可用性验收必须由至少三名未参与实现的管理员/运维执行六任务并记录耗时、错误与错误机构写入数。未参与时保持 pending；自动化和模型审查不能替代真实用户。

## 表访问范围

先执行管理库迁移 `alembic -c alembic-management.ini upgrade head`（新增 0008），再部署同版本的后台和管理 bundle。旧发布目录和运行引用不会改写。

管理员进入数据源详情的“表访问范围”，按“刷新数据库目录 → 选择表/视图 → 保存表范围 → 发布”操作。发现只读取数据库目录和字段，不读取业务样本或统计行数。目录读取成功不代表业务查询健康；业务说明补充失败时可继续使用真实结构及数据库注释。

新发现对象不自动暴露。已选对象消失时会单列提示，需明确取消；空选择可在页面保留编辑，但不能保存为有效范围。每个数据源最多 200 张表。更换连接后旧快照和目录绑定失效，必须重新发现、明确保存范围才能发布。保存会在同一事务创建不可变可绑定目录、绑定草稿并递增版本；数据源发布前新报告仍用旧发布范围，已有报告与恢复继续使用旧冻结版本。

接口均位于 `/management/api/v1/sources/{sourceId}`：

| 方法与路径 | 说明 |
| --- | --- |
| POST `/table-discoveries` | 保存连接的目录发现；提交 expectedDraftVersion |
| GET `/table-discoveries/{discoveryId}/tables` | q、kind（all/table/view）、offset、limit、selectedOnly 服务端筛选与分页 |
| GET `/table-discoveries/{discoveryId}/columns` | database、table 明确定位字段结构 |
| GET `/table-access` | 草稿/发布范围、草稿版本、可用发现快照 |
| PUT `/table-access` | expectedDraftVersion、discoveryId、完整 selectedTables（database、name） |

接口复用 scopeDatabase、companyId、管理员会话及 CSRF。写入不自动重试，409 保留本地输入；网络响应丢失后先读取最新版本和实际范围，由管理员明确选择采用服务器范围或保留本地选择继续核对。

表范围的唯一运行时依据是已绑定的不可变目录。目录中的 DDL 根据所选真实字段重建，隐藏表引用的术语/度量语义会被移除并告警；视图许可不授予底层表的直接查询权限。此控制不改变报告 PDF/Word 生成后非阻断下载签发规则。

本轮浏览器使用 `scripts/management/upgrade_server.py --reset-test-data` 与 `upgrade.spec.ts`。它沿用同一专用管理测试库限制，仅数仓目录 I/O 使用固定测试结构；并非真实 StarRocks 集成验收。工程证据写在 `output/management-upgrade/`，真实 StarRocks 与人工体验评价单独记录。
