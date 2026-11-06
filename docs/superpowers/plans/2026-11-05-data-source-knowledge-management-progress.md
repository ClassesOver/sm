# 数据源与知识库管理实施进度

对应计划：[实施计划](2026-11-05-data-source-knowledge-management.md)。2026-11-06 更新：计划修订后继续在功能 worktree 实施，已提交配置发布、原子导入和持久化运行快照基础。以下区分已有实施、定点验证与仍需完成的验收。

## 工作区与版本基线

- 主工作区：`/home/junge/pros/smart_reporting`；已有 Office 编辑器修改，本次未修改这些应用文件。主工作区尚无管理应用模块。
- 功能 worktree：`/home/junge/.codex/worktrees/dc7b/smart_reporting`，分支 `feat/data-source-knowledge-management`，起点 `4b543a53`，本批应用提交 `ef08213b`（前序 HEAD `f3dc0cff`）。
- 两个工作区仅同步本计划和进度文档；管理应用代码仍在功能 worktree，不表示已合并。
- 已有提交：`1ae7200d` admin/迁移；`408a4b0d` 组织/数据源/Profile；`f3dc0cff` Catalog/导入初版。
- 下表中的配置存储与运行快照续做代码已提交为 `ef08213b`；报告接入尚未完成。功能 worktree 有独立 `.venv`；已有验证使用专用 PostgreSQL 18 测试容器 `reporting-management-test-db`，端口 `55439`，库与用户均为 `management_test`。本次未检查容器状态，凭据不写入文档。

## 任务状态

| 任务 | 当前实现 | 剩余交付条件 |
| --- | --- | --- |
| 1 admin | 核心后端已提交；统一业务路由认证已补充 | 完整应用启动、实际路由矩阵、浏览器和部署验收 |
| 2 数据源 | 草稿/发布/凭据已提交；依赖检查、发布重试幂等已提交 | 规范化哈希已修复；连接测试、列表/详情、启停/默认源、差异/历史复制闭环 |
| 3 目录/Profile/导入 | 完整 metadata 快照、服务端同步、原子导入、CLI、固定 Profile 祖先闭包已提交 | 既有执行参数丢失已修复并复核；仍需旧配置导入差异提示、真实 StarRocks/metadata 验收 |
| 4 运行配置 | 数据库快照、可信身份登记方法、freeze/load_pinned、跨实例/并发测试已提交 | 方法尚未接入可信 HTTP/MCP/CLI 入口、bootstrap、confirm_source 或后续取数；不可称 database 模式可用 |
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

## 下一执行批次

1. 已完成上述修复、定点验证、只读复核与应用提交。后续补旧配置 dry-run 逐源提示，并以原文件重新导入对账；不改写旧发布 hash。
2. 复用已有 Task 4.1 基础，完成 4.2–4.4：可信 HTTP/MCP/受控 CLI 上下文 → 运行登记与恢复授权 → confirm_source 冻结 → 后续实际取数。验证不能以请求字符串、admin Cookie 或 default/default 授权，database 不回退 file。
3. 补齐数据源页面所需 API，完成 Task 5；再推进 6–9 知识库与报告引用，不增加原范围之外的子系统。
4. Task 10 按 A1–O1 留存真实证据：操作页面、真实取数、知识检索、生成报告、直接下载核验和独立恢复；最后一次完整检查。未执行项明确标为 not_run。

继续保持：单 admin、StarRocks、现有 Profile、PDF/DOCX/Markdown/UTF-8 TXT、Agno 优先、无负责人、无可编辑查询限额、无首版 SSO/多角色 ACL/OCR/网页抓取/通用 BI。知识异常与报告验收失败不阻断已生成且身份可核验 PDF/Word 的下载签发。
