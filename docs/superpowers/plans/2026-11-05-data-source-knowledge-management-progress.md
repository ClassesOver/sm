# 数据源与知识库管理实施进度

对应计划：[实施计划](2026-11-05-data-source-knowledge-management.md)。2026-11-06 更新：已提交配置发布、原子导入和持久化运行快照基础；Task 4 报告接入已有未提交实现和定点结果，但审查仍有两项 Important。本次只更新计划/进度，读取现存 JUnit、源码及审查结论，没有重跑应用测试；以下区分已提交、未提交、局部证据和未完成验收。

## 工作区与版本基线

- 主工作区：`/home/junge/pros/smart_reporting`；已有 Office 编辑器修改，本次未修改这些应用文件。主工作区尚无管理应用模块。
- 功能 worktree：`/home/junge/.codex/worktrees/dc7b/smart_reporting`，分支 `feat/data-source-knowledge-management`，起点 `4b543a53`；最新应用提交 `ef08213b`，本次文档更新前 HEAD `0aac2a93`（文档提交）。
- 两个工作区仅同步本计划和进度文档；管理应用代码仍在功能 worktree，不表示已合并。
- 已有提交：`1ae7200d` admin/迁移；`408a4b0d` 组织/数据源/Profile；`f3dc0cff` Catalog/导入初版。
- 配置存储与运行快照基础已提交 `ef08213b`；14 个报告接入应用/测试文件尚未提交，不能称 Task 4 完成。功能 worktree 有独立 `.venv`；已有验证使用专用 PostgreSQL 18 测试容器 `reporting-management-test-db`，端口 `55439`，库与用户均为 `management_test`。本次文档更新未检查容器状态，凭据不写入文档。

## 任务状态

| 任务 | 当前实现 | 剩余交付条件 |
| --- | --- | --- |
| 1 admin | 核心后端已提交；统一业务路由认证已补充 | 完整应用启动、实际路由矩阵、浏览器和部署验收 |
| 2 数据源 | 草稿/发布/凭据已提交；依赖检查、发布重试幂等已提交 | 规范化哈希已修复；连接测试、列表/详情、启停/默认源、差异/历史复制闭环 |
| 3 目录/Profile/导入 | 完整 metadata 快照、服务端同步、原子导入、CLI、固定 Profile 祖先闭包已提交 | 既有执行参数丢失已修复并复核；仍需旧配置导入差异提示、真实 StarRocks/metadata 验收 |
| 4 运行配置 | provider/迁移已提交；入口上下文、bootstrap、确认数据源及后续物化已有未提交实现；5 项 PG /261 项定点回归通过 | 先修会话状态越界和实时目录覆盖两项 Important；类型检查及应用装配尚未收口；完整 HTTP/MCP 恢复和真实 StarRocks 未验收 |
| 5 管理前端 | 未开始 | 独立 React 入口、页面操作及真实后端闭环 |
| 6 文档存储 | 未开始 | 原文文件、版本、受控访问、任务登记 |
| 7 Agno 索引/worker | 未开始 | 锁定版本核对、manifest 读回、租约/attempt/generation 恢复 |
| 8 知识管理/检索页面 | 未开始 | 上传、发布、检索与来源定位闭环 |
| 9 报告知识引用 | 未开始 | 片段冻结才注入；恢复不漂移；异常软告警 |
| 10 部署/完整验收 | 未开始 | 浏览器、真实数仓/报告、下载、备份恢复及一次完整检查 |

Task 复选框表示整项交付，不按局部测试通过自动勾选。M1、M2、M3 均未完成独立签收。

## 已提交后端行为

- 源发布在同一事务核对组织、Profile、完整目录和凭据版本；同内容重试返回原 revision，不重复审计。
- Catalog 复用已有 JSON 列保存 physical tables、完整 `ModelTermsResponse` 和草稿版本；内容哈希排除草稿计数。旧 list 可展示，发布/运行须重新同步。无需为 JSON 包装新增迁移。
- 同步 API 使用服务端草稿凭据调用现有 metadata client 和 StarRocks adapter，外部 I/O 不持管理事务，写入前 CAS；不接受浏览器清单冒充同步。
- 源/Profile/Catalog/导入 router 复用 admin 依赖，写事务再次认证。
- 导入先认证、解析和全源预检，提交前对比管理配置 baseline；一个事务发布 Profile、目录、凭据、源、默认源和审计。dry-run 不写版本；重复相同配置不变；审计故障整批回滚。
- CLI 提供 `import-config --database ... --company-id ... --directory ... [--dry-run]`，隐藏读取密码，finally 撤销临时 session。
- Profile 沿已发布父记录固定祖先闭包，祖先独立发布不改变旧父依据，闭包冲突明确拒绝。
- `0006_runtime_snapshots` 保存服务端运行身份与引用；provider 已移除 `_runs` 内存权威缓存，精确选版、校验依赖和引用摘要，支持跨实例恢复与同 run 并发固定。`register_run` 仅是内部方法，字符串 entrypoint 不能自行证明调用方可信，接入方仍须真实核验。

## 审查修复：两项 Important 已经定点验证并复核

| 问题 | 源码与复现 | 计划中的处理及验收 |
| --- | --- | --- |
| 合法输入的配置哈希不可重建 | `data_sources/service.py` 在 hash 后才 strip 名称/lower 数据库；`runtime.py` 用落库值重算。`name=" 数仓 "`、`database="WAREHOUSE"` 可发布但 freeze 返回配置身份不匹配 | Task 2 先统一规范化内容，再落库/哈希/恢复；覆盖管理保存与导入。历史异常版本不原地改 hash、不跳过验证，列入迁移对账并复制草稿重新发布 |
| 导入丢失既有执行参数 | `importer.py` 不保存文件 QueryLimits；`runtime.py` 恢复 parser 时使用默认值。文件 `(9,100,2048)` 会成为 `(30,1000000,268435456)`，只改这些值可能仍被视为无变更 | Task 3 保存内部快照、纳入版本 hash，Task 4 原样恢复；只改一项产生新版本，旧运行保持旧值。管理页面/公开写入 API 不增加限额字段；旧缺失记录从原文件重新导入对账 |

已先在真实 PG 复现这两项失败，再完成修复；新反例测试通过。只读审查者再次核对和探针验证，未发现阻碍提交的 Critical/Important。旧记录迁移后保留 NULL 并明确要求重新导入，既有 hash/运行引用不改写；dry-run 对这些旧源逐项提示仍待补充。另修复源 HTTP 创建/编辑的 Pydantic alias 错误，实际 API 用例通过，并确认写入 maxRows 返回 422。

## 已有验证与证据边界

以下第一批来自先前续做阶段；本次在此基础上只运行受影响的定点测试，新增结果在下一节单列。

| 检查 | 结果 | 本次能核对的证据 |
| --- | --- | --- |
| 管理存储/认证，14 份集成测试 | 37 passed，0 failed/error/skipped | 读取 `management.xml` 的 testsuite 计数：37/0/0/0 |
| 既有 HTTP identity/request limits | 43 passed，0 failed/error/skipped | 读取 `http-regression.xml`：43/0/0/0 |
| metadata client/Profile source binding | 26 passed | 续做执行交接记录；本次未见独立 JUnit，不升级为独立签收 |
| 定点 Ruff、git diff --check | 续做记录通过 | 本次文档修改另执行 diff 检查；不代表完整应用静态检查通过 |
| 六模块 mypy，follow-imports=silent | 通过 | 本次接收已有进程结果：`Success: no issues found in 6 source files`；仅 catalog/cli/importer/profiles/runtime/releases |

JUnit 目录：`/tmp/smart-reporting-management-acceptance/2026-11-06-storage-foundation/`。两个文件均为 2026-11-06 的测试结果；管理批次记录有第三方 imghdr 弃用警告。

管理集成测试覆盖：访问/持久化/组织/源/Profile/Catalog/同步/发布依赖/导入/CLI/资源认证/运行持久化/跨实例恢复/迁移。使用真实 PostgreSQL，但 StarRocks 网络与 metadata HTTP 使用受控响应；该历史批次不含两项新审查反例，也不含真实数仓、向量库、页面或报告链路；本次新反例见下节。

复现时显式设置 `REPORTING_MANAGEMENT_TEST_DB_URL` 指向专用可清空测试库，URL 使用 `postgresql+psycopg://`；fixture 重建 management schema，两批清库测试不可并行。普通 pytest 默认排除 integration，跳过不能算通过。新增修复仅运行受影响定点用例；所有阶段完成后执行一次完整检查。

更早的 13/16/22 项历史批次保留在 Git/交接记录中，不与 37/43/26 简单相加；重复运行和部分覆盖不构成更多独立证据。目前没有 A1–O1 完整验收 manifest，没有真实浏览器、真实 embedding、报告生成或备份恢复签收。

## 本次配置保真验证（提交 ef08213b）

- 先观察规范化 create/save 两例因配置 hash 不匹配失败，修复后两例通过；导入保真用例先观察 9 项执行参数回默认值失败，再修复并通过。
- 受影响的 6 份 PostgreSQL 集成测试：**21 passed，0 failed/error/skipped**，覆盖 sources、release_dependencies、source_import、runtime_persistence、resource_access、migration；没有重跑完整项目测试。
- 新增迁移 `0007_source_execution`；从 0005/0006 升级保留账号、会话、目录、源旧 hash 和运行引用，重复升级不变。旧源执行参数保持 NULL，不猜测已丢失的自定义值。
- 改动的 Python 文件 Ruff、9 个管理模块 mypy（`--follow-imports=silent`）、暂存 diff 检查均通过；只读复核无阻碍提交问题。
- 扩大 Ruff 扫描到未修改文件时，`data_sources/secrets.py` 和 `test_management_scopes.py` 有 4 项既有 import-order 问题，本次未顺带改动，不能称全管理目录 Ruff 全绿。
- 新证据：`/tmp/smart-reporting-management-acceptance/2026-11-06-config-fidelity/{management.xml,manifest.json}`。manifest 记录提交、源文件/JUnit hash、检查范围和 A1–O1 的 not_run；21 项结果不等于端到端验收。

## Task 4 报告接入与本次边界修复（fe3c20c3）

已实现部署级 file/database 选择；database 不调用文件加载器。HTTP capability 验签后绑定可信身份，MCP 读已验证 token claims，CLI 要求显式组织。运行登记与恢复绑定用户/组织/thread；配置引用持久固定，后续画像、规划和物化从原发布版本重建校验，不以可编辑 session_state 作为授权。

三项 Important 已按反例修复：

- 保留真实 references 篡改表/字段/Profile/语义不能扩大取数范围。实际 Agno session PATCH 和原生 pause→PATCH→重建实例→continue 均覆盖；SQL 与 hash 同时篡改、通配投影和移除组织过滤在数仓 I/O 前拒绝，合法原查询可物化 CSV。
- database confirm 与画像保留发布 metadata/schema hash，实时类型/可空性/说明变化返回具体告警，缺表/列不能继续取数。file 保留原目录匹配方式。告警写入确认步骤和运行状态，本次不改签发链路。
- 全部画像 SQL 应用冻结 Profile 的组织过滤；总计只加组织条件，期间内统计/覆盖/Top-K 叠加期间条件。DuckDB 实际执行经 SQLGlot 转译的 StarRocks SQL，检查两个组织、外期/NULL 计数、含引号及反斜杠的值；复核发现混合大小写字段校验不一致，补失败反例后用发布列名映射修复。

bootstrap 使用有效 AsyncEngine，缺失或错误引擎明确失败；database 应用导入探针断言 provider 存在且 registry/profiles 为 None，通过。仅证明导入装配，未验证 lifespan、真实模型或真实数仓。

### 分批验证与限制

证据目录 `/tmp/smart-reporting-management-acceptance/2026-11-06-runtime-boundaries/`，计数不累加为独立验收：

| 批次 | 结果与说明 |
| --- | --- |
| 接入集成 runtime.xml | 24 passed，0 skip；真实 PG，数仓网络受控，Agno session 存储用 SQLite |
| 受影响普通回归 regressions.xml | 首次 487 passed / 5 failed / 5 skipped；失败均为旧 fixture 没有新增异步接口，补适配后 planner-adapters.xml 的 5 项定点通过 |
| 工作流画像过滤 profile-runtime.xml | 2 passed；真实 PG 发布/冻结，验证过滤传入画像与非法选表在 Catalog I/O 前拒绝 |
| 画像/metadata/type profile-scope.xml | 23 passed；含初版画像两例和描述漂移，之后字段大小写反例另有最终文件 |
| 画像最终 profile-scope-final.xml | 5 passed；组织值/字段大小写四组合及发布结构保留 |
| bootstrap | 3 passed；包括无引擎/错误引擎反例，先红后绿 |
| 生命周期 lifecycle.xml → lifecycle-fixed.xml | 局部类型修复曾使缺省 provider 的旧 fixture 7 项失败；恢复原 getattr 兼容方式后 7 passed |
| 定点 mypy | identity/http/bootstrap/cli/settings/base/datasets/profiling 共 8 模块通过；planning 仍有两项既有 arg-type（ReportEditorContext 字典、Column 列表追加 Alias），未声称全目录通过 |

普通回归的 5 skip 是既有 V1 上传、旧分析预算/日期环境与旧 thinking 契约，不能当通过。Ruff 改动代码检查及 diff 检查另记录；planner 契约测试文件有未改动的既有 import-order 问题。不重跑完整测试。

外部证据边界：只读复核确认原两项直接路径修复，并发现/复核画像组织过滤；画像结果由独立 SQL 引擎计算，而非 mock 预设统计。仍没有真实 StarRocks、真实 embedding、浏览器、完整部署 HTTP/MCP 启停、报告生成下载或备份恢复签收。database 全局 diagnostics 仍不是管理源真实连通性证明。

## 下一执行批次

1. Task 4 接入及边界修复已提交 fe3c20c3；真实部署验收仍待完成。
2. 旧配置 dry-run 逐源提示已补；继续连接测试、列表/详情、分页版本、启停/默认源 CAS、差异和历史复制 API，完成 React 管理页面。
3. 顺序推进知识原文/版本、Agno 索引与可恢复 worker、管理检索、报告冻结引用；不增加负责人或可编辑查询限额。
4. 按 A1–O1（含 D3、D4）补真实证据；知识异常与验收失败不阻断已生成且身份可核验 PDF/Word 的下载签发。未执行项明确 not_run，最终一次完整检查。

## 旧执行参数导入对账补充

预览和正式导入结果返回 `legacySourceIds`：仅列出本次文件中、当前组织草稿或当前发布版本缺少执行参数快照的源。即使旧 hash 恰好相同，NULL 参数也不能当作无变更，必须从原文件生成新发布版本；旧版本 hash、NULL 和运行引用不改。修复后保留历史 NULL 不会重复提示。

真实 PG `test_management_source_import.py`：3 passed（先观察新增断言失败，再修复通过）；覆盖 dry-run 不落库、同 hash/NULL 修复、新版本参数、历史不改及修复后幂等。JUnit：上述证据目录 `import-legacy.xml`。importer 定点 mypy、改动文件 Ruff 与 diff 检查通过；只读复核无 Critical/Important。本次未运行完整项目测试。
