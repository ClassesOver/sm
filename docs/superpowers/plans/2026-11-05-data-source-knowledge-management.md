# 数据源与业务知识库管理后台实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 默认在当前执行会话中顺序实施；本计划不要求启动子 agent。

**Goal:** 在现有 Reporting 服务内交付一个可运营、可恢复、可验证的企业管理闭环：admin 登录后维护 StarRocks 数据源、业务口径和版本化知识库，报告按已验证组织冻结数据与知识依据；首版不扩展为通用 BI 平台。

**Architecture:** 在现有 FastAPI / AgentOS 单体服务内增加管理模块，复用 PostgreSQL 和 SQLAlchemy。前端增加独立 React 管理入口；知识解析、分块、向量检索复用 Agno Knowledge / PgVector，原始文件使用持久化目录。配置按运行冻结，文档按版本发布，后台任务持久化恢复。

**Tech Stack:** Python 3.12、Agno 3.1.2、FastAPI、SQLAlchemy 2、PostgreSQL 18、pgvector、React 19、TypeScript、Vite、Loguru；迁移使用 Alembic，本地 admin 密码使用 pwdlib[argon2] 的 Argon2id，凭据加密使用现有 cryptography。

**Spec:** 本文件“已确认范围”和“关键设计”是本次实施的需求基线，来自本轮对话。

**Revision:** 2026-11-06，按“深入而不是更大”修订。保留专家方法、原始材料、具体工具、独立验收证据及重写题目；本次按隔离分支当前源码和现存 JUnit 校正基线，把配置规范化哈希、既有执行参数保真两项审查问题纳入 Task 2/3/4 的前置修复。计划描述目标，进度文件记录实施与证据边界；计划修订后续做的配置基础与审查修复已提交为 `ef08213b`；尚未启用 database 报告模式或执行上线验收。

## 先回答“深入而不是更大”

### 顶尖专家会额外做什么

专家不会只增加页面字段。他们会先把“谁能看什么、哪一版配置生效、报告引用了什么”变成可检查的不变量，再设计页面：

1. **做边界建模**：明确本系统是 Reporting 的管理与证据控制面，不承担 BI 的自助指标探索、仪表盘编排、OLAP 加速或经营驾驶舱职责。
2. **做身份与权限威胁建模**：区分 admin 管理会话、报告调用身份、编辑会话和公开下载授权，验证一个凭据不能横向升级到另一个入口。
3. **做版本与溯源建模**：把数据源、Profile、目录、知识文档、索引代次、报告运行和引用快照串成可回放的版本链，而不是只存“当前配置”。
4. **做失败语义设计**：区分“未命中”“索引未完成”“索引不可用”“内容不适用”和“原文身份失效”，用软告警保留可用产物，不把失败伪装成成功。
5. **做迁移和恢复演练**：验证数据库、原文文件、向量索引和加密密钥必须一起备份恢复；验证服务重启、任务租约过期和旧版本回读。
6. **做可观测性与审计最小集**：记录谁在何时发布了哪一个版本、测试针对哪个草稿、报告冻结了哪些依据；不记录密码、DSN、Cookie 或原文敏感内容。
7. **做反例验收**：刻意测试并发发布、改密竞态、伪造组织范围、跨组织同文档、部分向量写入、失效文档和异常下载链路，而不只演示一条成功路径。

这些工作增加的是可证明性和故障边界，不增加首版业务模块；因此首版继续排除 SSO、多角色 ACL、OCR、网页抓取、指标建模和通用 BI 看板。

### 他们会从哪些最原始的素材入手

不以“已经整理好的需求表”作为唯一输入，而以以下可复核素材建立事实基线：

| 素材 | 取法 | 用途 |
| --- | --- | --- |
| 真实 FastAPI 路由表和中间件 | 静态枚举注册路由、依赖和异常映射 | 生成管理 API 访问矩阵，防止漏保护 |
| 现有会话、Cookie、CSRF 和授权实现 | 阅读 `report_editor` grant/session/repository/api | 复用已验证的令牌哈希、期限和写请求保护方式 |
| 现有数据源/Profile JSON、DDL、元数据响应 | 使用脱敏配置、真实目录快照和 schema hash | 定义导入、继承、发布和运行冻结的真实契约 |
| 真实 StarRocks 连接与失败响应 | 独立测试库中的连接、超时、权限和目录变化 | 证明连接测试与元数据同步不是只验证格式 |
| 原始 PDF、DOCX、Markdown、TXT 文件 | 小型脱敏资料集，保留页码、标题、行号和前后版本 | 校验解析定位、版本保留、检索引用和原文哈希 |
| PostgreSQL/pgvector 数据库与迁移日志 | 并发事务、部分提交、重启、恢复库 | 验证版本指针、索引 manifest、租约和备份一致性 |
| 已生成 PDF/Word 及其 SHA-256 | 故障注入和直接 HTTP 下载 | 证明验收告警不会错误阻断可核验产物签发 |
| 真实浏览器操作和网络记录 | Playwright 桌面/窄屏、登录过期、409 冲突 | 证明页面行为与 API 契约一致，而非只通过组件单测 |

### 具体方法和工具

- **契约方法**：先写访问矩阵、状态机、不变量和版本引用结构，再实现 API；用 JSON Schema/Pydantic 约束公开输入，公开输出使用字段白名单，并检查日志脱敏。
- **代码与接口**：`rg`/静态路由枚举、pytest、HTTPX/ASGI client、SQLAlchemy 事务测试、可注入时钟和故障注入 fixture。
- **安全**：Argon2id（pwdlib）、随机 session + SHA-256 哈希、Origin/CSRF、密码/DSN/Cookie 负向断言；不把 admin Cookie 传给报告授权路径。
- **数据与检索**：Agno Reader/Chunking/Knowledge/PgVector，确定性 embedding fixture + 少量真实中文 embedding 验收；manifest、chunk hash、向量维度和定位回读。
- **浏览器与部署**：Playwright、Docker Compose、独立 PostgreSQL/pgvector、迁移演练、容器重启和独立恢复环境；前端仅构建独立 management bundle。
- **证据产出**：JUnit、脱敏 HTTP 摘要、页面截图、文件 SHA-256 对账、恢复记录和 `manifest.json`，明确 `passed/failed/skipped/not_run`，不把跳过当通过。

### 除了我们之外，什么可以证明结果正确

正确性不由模型或开发者口头判断，而由四类外部证据共同证明：

1. **独立系统证据**：真实 PostgreSQL/pgvector、真实 StarRocks 连接、真实文件系统和直接 HTTP 下载结果。
2. **独立实现证据**：用 `python-docx`/`lxml`、PDF 文本工具、SHA-256、数据库查询和向量 manifest 回读检查输出，不调用被测业务函数自证。
3. **独立人员证据**：另一位工程师依据 runbook 和资料集复现访问矩阵、版本对账、检索定位及恢复步骤；不能只看作者测试报告。
4. **独立运行证据**：容器重启、任务中止、数据库恢复、密码重置和失效会话重放后的结果；所有结果带版本、时间和配置 hash。

### 重写后的题目

> 请在现有 smart_reporting 项目内，设计并分阶段实施一个不过度扩张的企业级 Reporting 管理控制面：提供单一 `admin` 登录和服务端会话，管理 StarRocks 数据源、现有 Profile/元数据及其不可变版本，建设支持 PDF/DOCX/Markdown/TXT 的业务知识库和可恢复索引任务，并将已验证的数据配置与知识引用冻结到报告运行中。方案必须明确与 BI 的边界，不增加负责人或可配置查询限额，不引入首版 SSO、多角色 ACL、OCR、网页抓取或通用仪表盘；必须从真实路由、现有认证实现、脱敏配置/DDL、原始文档、数据库与渲染产物入手，说明具体方法和工具，并用独立的安全、并发、故障注入、浏览器、备份恢复和 PDF/Word 下载证据证明结果正确。请输出可执行的分阶段计划、接口和数据不变量、验收资料集、证据 manifest 及明确的未覆盖边界。

## 全局约束

- 用户要求：“企业级的方案计划，也不要过于复杂”“建设自己的管理页面和配置存储”“知识库也加上”“查询限额 负责人 不要”“需要有admin 用户登陆控制”。
- 不提供负责人字段，不新增查询限额管理字段、表单或 API；现有取数执行契约不在本次拆改范围。原文件已有的 `QueryLimits` 作为内部兼容快照保留、参与版本身份并在取数时恢复，不成为管理页面或公开写入 API 的可编辑能力。
- 应用代码日志系统使用 Loguru。
- 优先复用 Agno，禁止为解析、分块、向量检索另造框架。
- 禁止重复完整测试；任务执行定点验证，收尾只执行一次完整检查。
- 语义业务校验使用软告警，以语义消歧减少对固定措辞的依赖。
- 报告验收或发布门禁失败不得暂停/阻断工作流或阻止下载链接签发；如 PDF/Word 已生成且实际文件身份可读取，应保留并签发下载链接，同时明确返回验收失败原因和告警，不得标记验收通过。只有产物未生成或无法读取身份时，才无法签发对应链接。
- 图表沿用 Matplotlib 静态 PNG/JPEG，不新增 Plotly 或交互图协议。
- 工作区已有其他修改；实施时只提交本计划对应文件，避免把现有 Office 引擎升级等改动混入提交。

## 原始证据与设计取舍

初版于 2026-11-06 只读核对下列源码。本次修订读取隔离分支提交、未提交管理模块、只读审查结论及现存 JUnit；未重跑应用测试、执行迁移、调用模型或生成报告。续做阶段已有的测试结果在进度文件单列，不当作本次重跑或端到端签收。README 和旧计划只用于定位，不作为验收证据。

| 原始素材及定位 | 已核对事实 | 对计划的影响 |
| --- | --- | --- |
| `smart_reporting/http/identity.py::requires_workspace_capability`、`app.py::create_base_app` | Workspace capability 按路径及请求头触发；公开下载单独放行 | 管理路由必须独立校验 admin，不能假定现有中间件已覆盖 |
| `report_editor/service.py::ReportEditorGrantService`、`report_editor/repository.py` | 编辑器使用随机 session、token 哈希、数据库期限，并绑定报告修订 | 复用会话设计经验，不把报告分享权限升级为管理权限 |
| `report_editor/api.py::_write_session_context` | 编辑写请求校验 Origin 和 CSRF | 管理写请求沿用相同类别检查，使用独立 Cookie 和用途 |
| `reporting/workflow/scope.py::resolve_reporting_workflow_scope` | 未提供组织时补 `default/default`；另可从 MCP claims 获取身份 | database 模式需要可信入口来源；非空组织字符串本身不能证明访问权 |
| `reporting/bootstrap.py::create_report_runtime`、`runtime/base.py::_source` / `_resolve_profile`、`runtime/planning.py::confirm_source` | registry/Profile 在启动时加载，后续步骤仍引用共享 registry | 冻结配置改造必须覆盖后续取数和恢复，不能只替换启动加载器 |
| `reporting/data_source/registry.py`、`reporting/profile/registry.py` | 现有严格配置、继承和 Profile 解析器 | 数据库存储复用这些契约，避免文件模式和后台模式各有一套规则 |
| `reporting/knowledge/index.py::ReportingKnowledgeIndex` | SQLite/FTS5，主要收录静态技术资料和按 workspace 隔离的修复经验 | 业务知识库独立存储和注入，技术经验不混入经营报告依据 |
| 安装环境 `agno/knowledge/knowledge.py::Knowledge.asearch` | 某些 embedding/检索异常被记录后返回空列表 | 不能把空列表直接解释为“检索正常但未命中” |
| 安装环境 `agno/vectordb/pgvector/pgvector.py::_upsert` / `_async_upsert` | 存在按批提交及部分异常处理路径 | 发布前必须读回核对 manifest；一次函数返回不能证明完整写入 |
| `pyproject.toml`、`runtime/database.py`、`docker-compose.yml`、`Dockerfile` | Agno 固定 3.1.2；已有 PostgreSQL/SQLAlchemy/cryptography；PostgreSQL 18 镜像，前端产物放源码挂载外 | 增补密码哈希依赖与 pgvector；独立管理 bundle 沿用现有部署方式 |

路径缩写 `reporting/`、`report_editor/`、`runtime/` 均相对 `smart_reporting/`。安装环境源码可能与重新安装的锁定包存在差异，Task 7 须在 `uv.lock` 对应的干净构建中复核方法签名、错误语义和过滤行为，不修改 site-packages 作为正式实现。

| 选择 | 推荐及理由 | 不采用另一方案的当前依据 |
| --- | --- | --- |
| 登录 | 本地单 admin + 服务端 session | 没有已确认 SSO 提供方，用户未要求多角色管理 |
| 存储 | 单 PostgreSQL，独立管理 schema；文件用现有持久化卷 | 当前部署无需额外数据库服务或对象存储服务 |
| 配置生效 | 发布不可变版本，运行固定引用 | 动态覆盖共享 registry 会让并发/恢复任务口径变化 |
| 索引发布 | Agno 完成解析/向量操作，应用核对后发布 | 文件、索引及业务版本无法假定是一次跨系统原子事务 |

专家方法在本计划中的落实：请求路径追踪形成访问矩阵；账号与文档生命周期形成状态契约；数据库事务和故障切点检验版本一致性；独立真实存储、浏览器和恢复演练提供外部证据。此深度增加验证约束，不增加业务模块。

## 已确认范围

### 首版交付

| 模块 | 功能 |
| --- | --- |
| 管理入口 | 本地 admin 登录、改密、退出、会话失效、操作记录 |
| 数据源 | StarRocks 连接配置、连接测试、启停、默认源、元数据浏览与同步 |
| 业务口径 | 导入现有 Profile、查看生效结果、绑定发布版本；保留现有 JSON 契约 |
| 配置版本 | 草稿、发布、版本差异、从历史版本创建新版本 |
| 知识库 | 建库、文档上传、分类标签、适用机构、生效/失效日期、版本发布和停用 |
| 知识处理 | PDF/DOCX/Markdown/TXT 解析、分块、embedding、任务状态和重试 |
| 检索验证 | 输入问题，查看命中文本、文档版本、页码或章节及检索状态 |
| 报告集成 | 按已验证组织范围读取数据源和知识，冻结依据，显示引用和具体告警 |
| 运维交付 | 配置导入、数据库迁移、文件和密钥备份说明、恢复演练 |

数据源只接入当前已实现的 StarRocks。知识库只支持文本型 PDF、DOCX、Markdown 和 UTF-8 TXT。扫描件无可提取正文时显示“需要 OCR”，不把空内容作为索引成功。

首版不做多数据库适配、可视化指标建模、OCR、网页抓取、知识图谱、多级审批、企业 SSO、多角色/资源 ACL、公开注册或消息队列。分类采用单层分类加标签；不建设任意层级目录系统。

### 页面信息结构

```text
/management/
├─ 数据源：列表 / 连接配置 / 数据目录 / 口径绑定 / 版本
├─ 知识库：库列表 / 文档列表 / 文档版本与预览 / 检索验证
├─ 账号：修改密码 / 退出登录
└─ 运行记录：处理任务 / 操作记录
```

数据源列表展示名称、类型、启停状态、连接状态、最近检查时间；文档列表展示名称、分类、版本、处理状态、发布状态和生效日期。所有列表分页，表单使用中文业务名称。

## 关键设计

### 1. admin 登录与访问边界

**明确的设计假设：** 首版每个部署只有一个本地账号 `admin`，管理该部署已登记的全部组织资源。各资源仍带 database/company 范围，报告只读取调用方所属组织的数据。这个账号是部署管理员，不是某个报告用户；如需要各组织独立管理员，应作为下一阶段变更，不在首版预埋角色体系。

选择本地 admin 是因为用户明确要求管理员登录，项目已有服务端会话存储经验，当前没有已确认的企业身份提供方。复用编辑器的随机令牌、哈希落库和 CSRF 模式，但独立表、Cookie、用途和路由；编辑 grant/会话不获得管理权限。密码校验使用成熟 Argon2id 库，不自制密码算法。

| 生命周期 | 具体契约 |
| --- | --- |
| 初始化 | `python -m smart_reporting.management.cli bootstrap-admin`，交互隐藏输入两次密码；无默认密码，无 HTTP 初始化/注册端点；账号已存在则报错，不覆盖 |
| 密码 | 固定用户名 admin；密码 12–128 个 Unicode 字符，允许空格，不 trim 或静默截断；保存 Argon2id 编码哈希；参数按 pwdlib 推荐值并记录实际参数 |
| 登录 | `POST /management/api/v1/auth/login`，JSON 输入；同源 Origin 校验；正确密码后生成 32 随机字节会话；失败统一“用户名或密码错误” |
| 节流 | PostgreSQL 保存失败窗口：单账号连续 5 次失败暂停 5 分钟，来源地址 5 分钟内 20 次失败返回 429；不永久锁死；仅信任已配置反向代理的来源地址 |
| 会话 | `report_management_session` Cookie，HttpOnly、SameSite=Lax、Path=/management，生产 HTTPS 下 Secure；数据库只存令牌哈希；闲置 30 分钟或绝对 8 小时到期 |
| 退出 | 带 CSRF 的 POST；服务端撤销会话后清除 Cookie。已经无效的会话可幂等清除；数据库故障返回 503，不能宣称撤销成功 |
| 改密 | 输入当前密码与新密码；事务更新 passwordHash、递增 authVersion 并撤销全部会话，成功后重新登录 |
| 忘记密码 | 主机运维执行 `reset-admin-password`，交互隐藏输入；和改密执行相同撤销事务，清理登录锁定；不提供邮件找回体系 |
| 服务重启 | 会话保存在数据库，按原期限继续；不重置密码、不自动延长期限 |
| 数据库恢复 | 恢复后对 admin 执行 CLI 重置并撤销恢复出来的旧会话，再开放管理入口 |

`authVersion` 随账号和会话保存；每次认证检查账号版本、撤销状态和服务端时间。登录写 session 前重新核对密码验证所使用的 authVersion，防止并发改密后签发旧凭据会话。管理写事务提交前再次检查该版本，改密事务与写事务按账号锁顺序串行化；不能只在页面入口检查一次。长任务保存创建者用于审计，已接受的处理任务不会因为管理员正常退出而取消。

登录和其他写入都校验配置的管理公开 Origin；管理会话写入另校验 CSRF。管理 JSON API 不为第三方 Origin 开放凭据 CORS。开发环境允许显式 localhost HTTP，不能自动把生产 Cookie 降级为非 Secure。

| 入口 | 未登录/失效 | 有效 admin | 额外条件 |
| --- | --- | --- | --- |
| GET `/management/login` 与静态资源 | 可访问，无业务数据 | 可访问 | 浏览器不缓存身份和配置响应 |
| GET `/management/` 及页面深链 | 303 到登录页 | 返回页面 | 深链只允许管理路径 |
| POST `/management/api/v1/auth/login` | 校验账号密码 | 可重新登录，轮换当前会话 | Origin、登录节流；新登录不复用旧 token |
| GET `/management/api/v1/me` | 401 | 身份和 CSRF token | 数据库故障为 503，不伪装登录失败 |
| 管理配置/知识/原文/任务/审计 GET | 401 | 读取显式组织范围 | 无隐式默认组织选择 |
| 管理保存/发布/上传/重试/改密 | 401 | 执行操作 | Origin、CSRF；配置 CAS 冲突为 409 |
| 退出 | 幂等清除失效 Cookie | 撤销当前 session | Origin；有效 session 校验 CSRF |
| 现有报告运行、MCP、编辑、下载 | 继续使用各自认证契约 | admin Cookie 不增加权限 | 不把管理认证中间件扩到整个应用 |

所有业务管理路由挂载统一 `require_admin` 依赖，公开认证端点单独注册；上线验收遍历实际注册路由，确认新增端点不会漏保护。缺少 admin 初始化时页面提示由运维初始化；已有报告服务不因此拒绝启动。

报告侧按已验证 Workspace capability 或 MCP 身份取得组织；普通 Console 自动补出的 `default/default` 只用于既有隔离，不是数据库资源授权证明。数据库模式对没有已验证组织的网络调用返回明确取数前错误；CLI 通过主机受控配置显式选择组织。file 模式继续兼容已有入口，不修改其协议。

### 2. 存储与版本

管理模块使用 PostgreSQL 独立 schema `reporting_management`；Agno 的表由 Agno 管理，不纳入自建迁移。

| 数据组 | 主要保存内容 |
| --- | --- |
| admin_account / admin_sessions / login_attempts | 单例 admin、密码哈希、authVersion、会话哈希、登录节流计数 |
| runtime_snapshots | 组织、runId、服务端核验的入口身份绑定、不可变配置引用、引用摘要及创建时间；不存明文连接信息 |
| sources / source_versions | 稳定 sourceId、启停、草稿、发布版本、连接配置、凭据引用和内部既有执行参数快照 |
| profiles / profile_versions | 原始 Profile JSON、修订号、依赖、内容哈希 |
| tenant_settings | 默认 sourceIds、默认知识库 IDs |
| runtime_snapshots | 可信运行身份、不可变配置引用及摘要；不保存明文凭据 |
| knowledge_bases / documents / document_versions | 分类标签、适用范围、原文身份、解析内容、索引代次、生效期间和发布版本 |
| processing_jobs | 类型、版本、步骤、状态、尝试次数、租约、错误和进度 |
| audit_events | 操作者、操作、目标资源、时间、脱敏变更摘要 |
| Agno 管理的内容表和向量表 | 内容索引和带组织/库/版本元数据的分块向量 |

- 稳定资源 ID 在组织范围内唯一；资源业务表、读取和变更显式带组织范围。admin 账号、会话及登录窗口是部署级对象，不强行绑定某个组织。
- 已发布配置和文档版本不原地覆盖；恢复旧配置时复制内容并发布新版本。
- 草稿修改使用整数 `version` 做 CAS，冲突返回 409 和当前版本，页面保留用户输入。
- 配置发布、当前版本指针更新和对应审计写入同一个数据库事务。
- 连接凭据用 cryptography 标准加密组件保存，独立加密密钥从部署环境读取；数据库和普通配置导出不包含该密钥。API、审计和模型上下文均不回显凭据。
- file 模式继续支持 `dsnEnv`；导入 database 模式时将当时解析出的凭据加密保存为不可变版本，`dsnEnv` 名称只保留作导入来源，不再于每次取数时重新解析。
- 文档文件保存在 `data/reporting-knowledge` 对应的容器持久化目录，由服务端分配对象路径；数据库保存 SHA-256、大小及受控读取信息。
- 暂不物理删除已发布或已引用版本；通过停用控制新的使用。备份包含数据库、原始文件和单独保管的密钥。
- 管理新增/导入组织设置时显式填入 database/company，列表只包含已登记范围；admin 切换范围是选择目标资源，不代表报告调用方获得该组织权限。审计区分账号事件与带组织的资源事件。

### 3. 数据源与元数据的权威来源

- 增加 `file` / `database` 两种显式配置模式。部署迁移后选择 `database`，配置只读数据库；数据库为空或不可用时不得偷偷退回文件配置。
- 保留 `file` 模式供已有 CLI 和部署兼容。模式不在每次请求中由调用方选择。
- 文件导入通过现有严格 parser 校验，预先获取并核对目录和凭据，再按组织原子导入；导入包含 Profile 继承闭包、完整源发布版本、既有 `QueryLimits` 和默认源配置，外部预检失败不提交部分配置。重复导入同内容且目录/口径/凭据/执行参数一致返回无变更；仅执行参数变化也创建新版本。
- 管理页面同步现有 metadata 服务的 DDL/terms/measureSemantics，再与真实 Catalog 校对；同步结果形成独立元数据版本。管理后台维护连接配置，现有 metadata 服务继续维护业务目录定义。
- 数据库模式下，报告使用已发布的元数据版本；页面显示目录同步时间和结构差异。真实 Catalog 校验只用于发现变化，不静默扩大可用表范围。
- Profile 继续使用现有模型和继承解析器。首版支持 JSON 导入、验证、预览、发布及绑定，不增加第二套指标口径 DSL。
- 连接测试使用草稿实际连接，记录测试所对应的草稿版本；通过只表示可连接，不表示数据完整或口径正确。
- 数据源发布版本固定 credentialRevision、profileVersionId（含继承闭包）和 metadataVersionId。目录/Profile 单独发布后不会悄悄改变已发布的数据源组合，admin 需要发布新的源版本完成绑定。一次运行在同一数据库一致性读事务中读取默认源和全部版本引用，随后保存冻结记录再取数。
- 修改密码或源连接凭据不改变历史版本引用。旧凭据在数据库侧已经失效时，尚未完成的取数显示凭据失效，不能偷偷使用新连接；已物化的数据集继续使用原身份。环境变量凭据首次导入时解析为加密、不可变的凭据版本，后续更新显式发布；不让可变环境变量破坏数据库模式的冻结保证。
- 停用阻止新运行选用该源；已经物化的数据继续服务原报告。恢复中的任务如还需新取数，重新检查当前组织可用性和启停状态，不能借历史快照扩大权限。

### 4. 知识处理与检索

- 复用 Agno Reader、Chunking、Knowledge 和 PgVector；实现薄适配层保留 PDF 页码、DOCX 标题/段落和文本行号，不自己实现 PDF/DOCX 解析器或向量检索。
- 中文检索首版采用支持中文的 embedding 向量检索，不直接依赖默认英文全文检索配置。embedding 的模型、地址、凭据和维度单独配置，不使用聊天模型代替。
- PostgreSQL 保持 18 同一主版本，部署镜像补充 pgvector 扩展。向量支持不可用时显示知识处理失败，不把未生成索引的文档标为可检索。
- 每个分块附带组织、knowledgeBaseId、documentId、documentVersionId、indexGeneration、定位信息及文本哈希。
- 文件更新生成新版本；解析和索引写入新索引代次。只有全部索引读回核对成功、预览可读，才允许显式发布并原子切换当前版本；失败保留旧版本。
- 任务状态为 queued/running/succeeded/failed；按租约领取任务，带 attempt 身份提交结果。重试重建新索引代次，过期 worker 的结果不能激活为当前版本。
- 任务按版本幂等，重启后重新领取租约已过期任务。手动重试记录原因；异常记录具体步骤，不自动更换 embedding 模型。
- 检索查询先由服务端确定已验证组织、该组织启用的知识库、已发布版本及适用期间，并作为 Agno 检索条件；模型只能给出检索问题，不能调整授权条件。
- 检索命中后，在返回文本前再次核对适用版本、组织和撤回状态，以处理发布与停用变更。未匹配到适用版本时返回具体状态，不自动使用已失效文档。
- 生效日期指知识适用的业务日期，不等于报告生成时间。普通查询默认当前日期；历史报告使用明确的分析日期范围。跨越制度版本的报告分别标注适用区间，存在冲突时软告警。
- “当前版本指针”只表示管理页面默认展示，不排除仍适用于历史期间的已发布版本。文档版本分为 draft/published/withdrawn，处理状态独立为 queued/processing/ready/failed/needs_ocr。新检索选择本次开始时已发布、未撤回且日期相交的版本；同一期间出现多个相互冲突版本时保留候选并告警，不按上传时间猜测哪份正确。
- Agno 检索适配器返回 `ok`、`empty`、`unavailable` 或 `indeterminate`。使用其原生 embedder/PgVector 公共接口，薄封装记录本次 embedding 调用成败；对返回空列表但无法确认底层查询成功的路径返回 `indeterminate`，不宣称无依据。正常非空结果仍核对组织、版本及文本哈希；稳定错误码进入 Loguru 和页面，不从第三方日志文本反推成功状态。Task 7/8 的真实存储故障用例验证具体安装版本的行为。
- 一次索引 generation 固定 embedding 模型标识、维度及文本分块规则；变更模型要创建并核对新代次后切换，不向旧向量空间混写。相同内容跨组织/版本的文档使用包含组织、versionId、generation 的存储身份，避免 Agno 去重覆盖另一份文档。

### 5. 报告接入与引用

- 当前 `bootstrap.py` 启动时加载 registry/Profile；数据库模式改为在 `confirm_source` 阶段解析本次组织可用配置并冻结版本，不给共享 runtime 的 `self.registry` / `self.profiles` 写入运行私有数据。
- 冻结内容包含 source/config/profile/metadata 的版本和哈希，不包含明文连接信息；凭据由服务端依据本次版本引用解析。后续取数步骤和暂停恢复都读取运行快照。
- 知识检索先服务于报告背景和章节解释，不进入数值事实目录，不替换已审核 SQL 结果或现有指标计算规则。
- 正文引用用独立标记 `〔知识1〕`，末尾列出文档名称、版本、生效区间及页码/章节。JSON 状态使用 `knowledgeReferences`，不复用数值引用 `[[citation:*]]`。
- 单条引用保存 documentVersionId、indexGeneration、chunkId、原始文件哈希、定位和实际引用文本及哈希；引用在工作项执行前冻结并持久化。恢复执行复用已冻结的引用文本，不重新检索并悄悄改变依据。
- 数据源中的数值才进入计算证据；知识中出现的历史数字保留其期间和来源，不能成为本期计算事实。检索文本作为业务资料，不能作为工具或系统指令执行。
- 引用原文查看走受控接口并检查当前 admin 会话。知识内容一旦被写入报告，属于该报告分享的正文；管理原文的访问权限不自动授予报告链接持有人。
- 知识库故障、未命中、文档冲突或引用核对失败均产生具体软告警；拒绝使用不合适的片段后继续可完成的报告步骤。已经生成且身份可读的 PDF/Word 仍签发链接。
- 首版不把原始知识文档附加到公开报告下载包；引用依据保留在内部报告快照中。
- 没有成功持久化的知识片段不进入模型正文上下文：引用快照写入失败时改为空知识上下文并告警，继续原报告流程。已经冻结后，即使原文后来停用，也可按原报告访问策略复核冻结的引用文本；新检索遵守停用。系统不能保证已对外分享的正文随原知识撤回自动消失。
- 恢复的目标是“证据与配置不漂移”，不是承诺非确定性模型再次生成逐字相同正文。数值计算使用冻结数据集复算；历史成稿直接读取原修订，不为查看历史重跑模型。

### 6. 一致性与故障切点

| 不变量 | 失败/竞争切点 | 应有结果及验证方式 |
| --- | --- | --- |
| 改密后旧会话无效 | 旧密码验证完成后，新密码事务先提交 | 登录重查 authVersion，不签发旧凭据 session；用两个数据库连接控制顺序 |
| 发布版本指针和审计一致 | 更新指针后、事务提交前失败 | 全部回滚；重试一次只产生一个发布版本/审计事件 |
| 运行固定同一配置组合 | 读默认源时另一事务发布新 Profile | 一致性事务读取旧组合或新组合，不能拼接混合版本 |
| 配置身份可重建 | 名称含首尾空格、数据库名大小写不同 | 先按现有 parser 规范化，再用同一内容落库/哈希/恢复；合法配置发布后可 freeze |
| 导入不改变执行语义 | 非默认 QueryLimits 导入、改值、历史恢复 | 文件解析对象与数据库恢复对象逐字段相等；改值生成新版本，旧运行仍保留旧值 |
| 文件可读才登记处理任务 | 文件落盘后 DB 事务失败 | 无可见文档/任务；受控重试清理该次临时对象，不能把孤立文件当发布文档 |
| 索引完整才 ready | 部分 batch 提交后 worker 退出 | 发布仍指向旧版本；读回不匹配 manifest，不置 ready |
| 过期 worker 不能激活结果 | 租约过期后新 attempt 已领取 | 提交时 CAS attempt/generation/lease；旧 worker 结果不激活 |
| 原文匹配引用 | 原文件丢失或哈希改变 | 不使用该原文；已冻结片段可复核，告警说明原文不可用 |
| 引用写入成功才注入正文 | 冻结写入失败 | 无知识补充继续生成，返回具体告警，不阻断产物下载 |

上述故障测试属于功能正确性验收，不增加审批流或独立审计平台。

## 代码落点

| 路径 | 职责 |
| --- | --- |
| `smart_reporting/management/` | 新增管理身份、会话、审计、设置、路由和迁移入口 |
| `smart_reporting/management/data_sources/` | 连接配置、发布版本和加密凭据 |
| `smart_reporting/management/{profiles,catalog,importer,runtime}.py` | 延续隔离分支已有落点，维护 Profile、元数据、导入和运行快照；不另建同职责模块 |
| `smart_reporting/business_knowledge/` | 新增业务知识库、文件存储、Agno 适配、任务处理及引用 |
| `smart_reporting/report_editor/frontend/src/management/` | 新增独立管理 React 入口和页面；复用现有 npm 构建环境 |
| `smart_reporting/report_editor/frontend/vite.management.config.ts` | 新增管理入口独立构建，避免引入 Office 编辑器依赖 |
| `smart_reporting/reporting/data_source/registry.py` | 复用文件读取和严格解析，不改为动态数据库访问入口 |
| `smart_reporting/reporting/profile/registry.py` | 抽取并复用内存文档校验/继承解析，不修改 Profile 语义 |
| `smart_reporting/reporting/bootstrap.py` | 注入配置 provider 和业务知识检索服务 |
| `smart_reporting/reporting/workflow/runtime/base.py` | 声明新增依赖，修正 `_source`/`_resolve_profile` 的运行配置读取，保留 file 模式兼容 |
| `smart_reporting/reporting/workflow/runtime/planning.py` | 按运行冻结配置、目录与口径 |
| `smart_reporting/reporting/workflow/runtime/datasets.py` | 使用冻结配置构建后续取数依赖 |
| `smart_reporting/reporting/workflow/runtime/sections.py` | 注入知识引用与软告警；整章和分块路径一致 |
| `smart_reporting/app.py`、`runtime/application.py`、`runtime/settings.py` | 挂载页面/API、初始化依赖、管理 worker 生命周期 |
| `Dockerfile`、`docker-compose.yml`、`pyproject.toml`、`uv.lock` | 构建、pgvector、依赖和持久化配置 |

自建 API 使用 `/management/api/v1/*`。现有报告入口、编辑器 API 和公开下载 URL 契约保持兼容。

## 当前执行基线与续做顺序

本轮计划修订以隔离 worktree `/home/junge/.codex/worktrees/dc7b/smart_reporting`、分支 `feat/data-source-knowledge-management` 为实现基线；当前主工作区没有这些管理模块，不能据此声称主工作区已具备后台。主工作区已有 Office 修改不纳入本计划提交。

| 任务 | 实际状态 | 仍需完成的可验收闭环 |
| --- | --- | --- |
| 1 admin | 核心后端已提交 `1ae7200d`；统一业务路由认证补充已提交 | 应用启动、实际路由全覆盖、浏览器登录及部署验收 |
| 2 数据源 | 草稿/发布/凭据已提交；依赖校验与发布幂等补充已提交 | 规范化哈希已修复；连接测试、列表/详情、启停/默认源、差异与历史复制接口 |
| 3 Profile/目录/导入 | 存储/API 已提交 `f3dc0cff`；完整同步、原子导入、CLI、固定祖先闭包补充已提交 | 既有执行参数保真已修复；补旧配置 dry-run 逐源提示；受控外部响应不算真实 StarRocks 验收 |
| 4 运行配置 | 持久化 provider、0006/0007 迁移和跨实例/并发测试已提交 | 配置身份/参数恢复已修复；HTTP/MCP/CLI 可信入口、bootstrap、后续取数接入尚未完成 |
| 5–10 | 未实施 | 页面、知识库、索引、报告引用、部署及独立验收 |

**下一执行批次固定为：**

1. 已完成 Task 2 配置哈希、Task 3 执行参数保真和 Task 4 恢复断言，21 项定点集成与只读复核通过，提交 `ef08213b`。补旧配置 dry-run 逐源提示，不重做已存在的同步/导入/provider。
2. 以已有持久化基础完成 Task 4.2–4.4：可信入口 → 运行登记/恢复授权 → confirm_source → 后续实际取数；database 模式未达到此闭环前不启用。
3. 补齐 Task 2 页面所需 API，再完成 Task 5 的数据源管理闭环；之后顺序推进知识库和报告集成。

各 Task 复选框表示完整交付条件，部分后端存在不等于整项完成。已有证据：管理存储 JUnit 为 37 项、HTTP 回归 JUnit 为 43 项，均无失败/跳过；另有 26 项元数据/Profile 回归的交接记录。历史批次未覆盖上述两项问题；新增 21 项定点结果已覆盖修复，但仍未证明页面、真实数仓、知识或上线完成。完整记录见同目录 `2026-11-05-data-source-knowledge-management-progress.md`。

## 实施任务

目标依赖顺序为 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10，续做按上面的实际基线补齐缺口。前五项形成可用的数据源后台；第六至八项形成可独立验收的知识库；第九项完成报告接入；第十项上线验收。

新增或修正行为先写失败测试，再完成最小实现；以下代码表示目标契约，已存在能力以当前 service 签名为准，尚未满足的目标在任务中继续收口。使用仓库现有 `pytest.mark.anyio` 模式，不新增另一套异步测试插件。

### Task 1：admin 登录、会话、数据库迁移与审计

**Files:** 新增 `smart_reporting/management/{__init__,models,auth,repository,api,cli}.py`、`smart_reporting/management/migrations/`、`alembic-management.ini`；修改 `smart_reporting/runtime/{settings,application}.py`、`smart_reporting/app.py`、`pyproject.toml`、`uv.lock`；新增 `smart_reporting/tests/test_management_access.py`、`test_management_persistence.py`。

**Interfaces:** `ManagementScope(database, company_id)` 标识资源组织；`ManagementActor(account_id, username, scope, auth_version)` 是有效 admin 加已选组织，不含角色。`require_admin(request)` 只校验管理员，`require_management_scope(request)` 在其后校验显式选择的已登记组织。`AdminAuthService.login(username, password, client_address)` 返回仅供设置 Cookie 的原 token 与会话；`authenticate(raw_session)` 返回账号；`logout(raw_session)` 撤销；`change_password(raw_session, current_password, new_password)` 改密并撤销全部会话。CLI 初始化/恢复调用同一 service 的主机入口。

- [ ] 先按访问矩阵写测试，覆盖未初始化、正确/错误密码、Cookie 属性、未知/到期/撤销会话、退出幂等、CSRF、登录节流、改密和并发旧密码登录。使用可注入时钟，避免测试实际等待 30 分钟。
- [ ] Alembic 只迁移管理 schema，建立单例账号约束、session tokenHash 唯一约束和 expiresAt 索引；加入组织设置、审计和登录窗口表。Agno 既有表不进入本迁移。
- [ ] 使用 pwdlib[argon2] 保存/验证密码哈希；CLI 无密码命令行参数、无密码日志。session 使用 secrets 随机值和 SHA-256 哈希，参考编辑器实现但不直接导入其报告授权服务。
- [ ] 按生命周期表实现会话及事务撤销；认证状态、配置写入和审计持久化错误返回具体失败，日志只记录动作和稳定错误码。密码哈希开销在部署机器验证，不阻塞 async 事件循环。
- [ ] API 的 login 公开但检查 Origin 和节流，logout 按矩阵允许失效会话幂等清除；password/me 和全部业务路由带 `require_admin`。已登录写入检查 CSRF。提供账号锁定恢复和数据库恢复后全会话撤销的 CLI 流程。
- [ ] 执行 `.venv/bin/python -m pytest -q -m integration smart_reporting/tests/test_management_access.py smart_reporting/tests/test_management_persistence.py`；真实事务和并发验证标记 integration，在独立 PostgreSQL 显式执行。

```python
# 同文件 fixture 提供 auth、已初始化 admin 和可推进的 clock。
first = await auth.login("admin", old_password, "127.0.0.1")
second = await auth.login("admin", old_password, "127.0.0.1")
await auth.change_password(first.raw_token, old_password, new_password)
for session in (first, second):
    with pytest.raises(AdminSessionInvalid):
        await auth.authenticate(session.raw_token)
assert (await auth.login("admin", new_password, "127.0.0.1")).raw_token
```

`AdminSessionInvalid` 定义于 `management/models.py`，HTTP 映射为 401；数据库不可用是另一错误并映射为 503。通过后只提交本任务文件。

**验收：** 浏览器和直接 HTTP 调用均受保护；改密后所有旧 session 不能继续读取或提交管理操作；既有报告下载/编辑入口没有被套上 admin 登录。

### Task 2：数据源草稿、凭据与发布版本

**Files:** 新增 `smart_reporting/management/data_sources/{__init__,models,repository,secrets,service,api}.py`；新增该模块数据库迁移；新增 `smart_reporting/tests/test_management_sources.py`。

**Interfaces:** 沿用现有 `SourceService.create_draft(raw_session, scope, source_id, payload)`、`save_draft(raw_session, scope, source_id, payload, expected_version)`、`publish(raw_session, scope, source_id, expected_version)`，返回脱敏字典；不为统一示例批量改写现有接口。`SourceDraft` 只包含 sourceId、name、type、database、credentialRef/连接写入参数、reportingProfileVersionId、metadataVersionId；`SourceVersion` 增加 revision、contentHash、publishedAt。`resolve_credentials(scope, source_id, revision)` 只供服务端调用。Task 2 测试使用已登记的 Profile/目录版本 fixture，真实版本导入与页面操作由 Task 3 完成。

```python
# 已登记 scope，payload 绑定同组织已发布的 Profile 与目录；fixture 使用真实独立 PG。
draft = await service.create_draft(raw_session, scope, "operations", payload)
published = await service.publish(raw_session, scope, "operations", draft["version"])
assert published["revision"] == 1
assert "credential_ref" not in published
assert published["contentHash"]
```

- [ ] 写出上面的发布行为测试，并增加旧版本不变、CAS 冲突及版本恢复生成新 revision 的用例。
- [ ] 实现 StarRocks 配置校验，复用现有 adapter/parser；连接凭据只在 adapter 初始化时解析。使用 cryptography.Fernet/MultiFernet 和外置密钥，支持按 key ID 轮换并保留解密旧版本所需密钥。
- [ ] 实现草稿保存、版本差异、发布和启停；加密值不参与公开哈希，使用凭据版本引用参与配置身份。发布指针和审计在同一事务。
- [ ] **先修复已确认的规范化哈希问题：** `name=" 数仓 "`、`database="WAREHOUSE"` 保存和发布后必须可以 freeze/load_pinned；规范化必须先于存储与哈希，并复用同一内容构造规则。对正常配置、大小写/空白输入、导入/管理 API 两种入口逐项断言恢复结果与内容哈希一致。历史发布记录不原地重写、不绕过身份校验；无法从已存内容验证的旧版本在 dry-run 中明确列出，经管理员复制为新草稿重新发布后才用于新运行；已有快照保留并明确返回恢复失败原因。
- [ ] 源发布时在同一事务验证 Profile、目录和凭据引用属于同组织、同数据源且确已发布；多源报告必须绑定兼容的同一有效 Profile。缺少依赖的草稿可保存，发布返回 422，不产生新 revision/指针/审计；更新 Profile 或目录必须显式发布新源版本。
- [ ] 补齐受保护的列表/详情、分页版本记录、启停、默认源、版本差异和从历史复制草稿接口；默认源更新做 CAS，并校验同组织已启用、已发布的 sourceId。复制历史版本后仍经草稿发布，不覆盖原版本。
- [ ] 实现连接测试，调用草稿的实际连接与 Catalog 接口并关闭连接；只返回状态、耗时、对应草稿版本和脱敏原因。测试完成前草稿已变化时，保留测试对应版本，不显示为新草稿已通过。
- [ ] 执行 `.venv/bin/python -m pytest -q -m integration smart_reporting/tests/test_management_sources.py`，通过后提交对应文件。

**验收：** 页面未来可完成一次连接配置发布；业务模型、API 和数据库字段均没有负责人或可编辑查询限额。

### Task 3：元数据、Profile 与现有配置导入

**Files:** 延续已存在的 `smart_reporting/management/{catalog,profiles,importer}.py` 及 `{catalog_api,profile_api,import_api}.py`；扩展前述 repository/api；为内部执行参数快照补管理迁移（接在已有 `0006_runtime_snapshots` 后），不为目录 JSON 包装单独建迁移；修改 `smart_reporting/reporting/profile/registry.py` 以复用内存解析；新增 `smart_reporting/tests/test_management_source_import.py`、`test_management_catalog.py`。

**Interfaces:** 沿用 `ConfigurationImporter.import_configuration(raw_session, scope, directory, dry_run, environ)` 返回脱敏差异字典；`CatalogService.synchronize(raw_session, scope, source_id, expected_draft_version)` 使用草稿连接返回未发布的元数据版本，`publish(raw_session, scope, source_id, revision)` 发布目录；`ProfileService.preview(raw_session, scope, payload)`、`save_draft(raw_session, scope, payload, expected_version)`、`publish(raw_session, scope, profile_id, expected_version)` 复用现有模型与继承校验。草稿允许暂未绑定目录/Profile，源发布要求引用已有效，避免“发布源才可同步目录”的循环依赖。

```python
first = await importer.import_configuration(raw_session, scope, config_dir, False, environ)
second = await importer.import_configuration(raw_session, scope, config_dir, False, environ)
assert first["changed"] is True
assert second["changed"] is False
# 独立 SQL 读回 source_versions、默认源和绑定引用，不能仅断言返回值。
```

- [ ] 为配置导入准备脱敏临时 JSON 和完整 Profile 父子示例，验证幂等、默认源解析和整批事务；测试元数据同步失败时现有发布目录不变。
- [ ] CLI 增加 `import-config --dry-run` 和正式导入；先校验所有源、Profile 继承依赖和默认源，再预检元数据/Catalog、解析凭据，最后一次提交目录、Profile、源版本和默认源。dry-run 不写入或返回凭据；正式导入重新预检，失败不留下半批发布配置。
- [ ] 同步 API 由服务端用指定草稿连接调用现有 `ReportingMetadataClient` 与真实 Catalog，不能把浏览器上传的 `catalog` 列表视作已完成真实同步。外部 I/O 在写事务之外，提交前 CAS 再查草稿版本，保存同步所针对的版本和差异。
- [ ] 目录版本复用已有 JSON 列，保存 `{tables, metadata, sourceDraftVersion}`，其中 metadata 为完整 `ModelTermsResponse`；内容哈希排除仅用于并发校验的 sourceDraftVersion。旧 list 格式可展示，但发布/运行前必须重新同步完整元数据，不伪造空口径；不为此新增表或迁移。展示结构差异与同步时间，不自动扩大表范围。
- [ ] 导入不能只创建源草稿或跳过所有同名资源：同内容且依赖/凭据一致为无变更；内容变化创建新版本；Profile 按继承依赖拓扑预检并固定父版本闭包。预检所有连接和元数据后一次提交发布版本、引用、默认源与审计，任一失败全部不生效；dry-run 同样先校验 admin 和组织。
- [ ] **先修复已确认的导入保真问题：** 将现有 parser 得到的完整 `QueryLimits` 作为内部 JSON 快照保存在草稿/发布版本，纳入同一内容哈希，并由 provider 原样传回 parser。管理 API 不接收可编辑限额；编辑其他字段、历史复制时保留内部值，新建源采用 parser 默认值。测试导入 `statementTimeoutSeconds=9,maxRows=100,maxBytes=2048` 后恢复值逐字段相等；只改其中一项必须生成新版本，重复相同文件不变，旧运行恢复旧值。旧记录缺失自定义值时不猜测：迁移明确标记来源，切换前从原文件重新导入并对账；不得把缺失值静默写成已验证兼容。
- [ ] 提供 Profile JSON 上传/校验/生效结果预览/发布，发布时固定父 Profile 的版本闭包；数据源绑定明确的 Profile 版本。祖先独立发布不得改变固定父版本闭包，冲突明确拒绝。一次报告所选源仍遵守相同 Profile 约束。
- [ ] 执行 `.venv/bin/python -m pytest -q -m integration smart_reporting/tests/test_management_source_import.py smart_reporting/tests/test_management_catalog.py smart_reporting/tests/test_management_profiles.py`，另跑普通回归 `.venv/bin/python -m pytest -q smart_reporting/reporting/tests/test_reporting_profile_source_binding.py`，通过后提交对应文件。

**验收：** 当前部署配置可以先预览再导入；旧业务口径模型继续生效，目录和 Profile 都有可追溯版本。

### Task 4：持久化运行配置、可信组织与恢复

**Files:** 完善已有 `smart_reporting/management/runtime.py`，不另建 `data_sources/provider.py`；修改 `management/repository.py`，新增迁移 `management/migrations/versions/0006_runtime_snapshots.py`；修改 `reporting/bootstrap.py`、`reporting/workflow/runtime/{base,planning,datasets}.py`、`runtime/settings.py`、`http/identity.py`、`reporting_mcp/identity.py`、`reporting/workflow/scope.py`，并核对 `prepare_run/start_run` 的实际落点；新增 `reporting/tests/test_managed_source_runtime.py`，扩展 `tests/test_managed_runtime.py` 和 `tests/test_management_migration.py`。

**当前基础与缺口：** 已提交的 provider 已移除内存权威缓存，具有 `register_run/assert_identity/freeze/load_pinned`、当前发布指针选版、目录/Profile/凭据核对和持久化快照；已有跨实例/并发定点测试。它尚未接入报告入口与实际后续取数，配置哈希和执行参数恢复已修复；不能据此启用 database 模式。

**Interfaces：** 沿用已有 `register_run(run_id, scope, *, user_id, thread_id, entrypoint)`、`assert_identity(run_id, scope, *, user_id, thread_id)`、`freeze(run_id, scope, source_ids=None) -> ManagedRunSnapshot` 和 `load_pinned(scope, references) -> ManagedRunSnapshot`。`ManagedRunSnapshot` 包含服务端 sources、有效 profile、已发布 metadata 和 `references`；`public_state()` 只返回组织、公开展示及 references。file 模式沿用原 registry/Profile 加载路径，不强制为其复制数据库生命周期。

**持久化契约：** `runtime_snapshots` 唯一键 `(scope_id, run_id)`，保存经验证的入口绑定、版本引用、引用摘要与创建时间。`start_run` 从服务端已核验身份登记运行；配置引用初始为空，仅首次 freeze 可原子写入，之后禁止改写。references 包含 runId、各 sourceId/revision/contentHash、credentialRevision、Profile 版本/继承闭包/哈希及 metadata 版本/哈希；不包含 DSN、密码、会话或 capability token。`load_pinned` 必须先找到该运行的可信记录，再核对传入引用完全一致，不能把可编辑 Workflow state 当作授权或版本选择的权威。

#### 4.1 复核已有持久化基础与补充兼容断言

- [ ] 复用已有真实 PG 的跨实例/并发 fixture；新增规范化配置和非默认执行参数的恢复反例后再修复，不重复创建 provider。以下用例是已有能力的目标契约，增加新断言时仅重跑受影响用例。

```python
# fixture 注册可信 run-1，并为 run-2 提供同一组织的合法调用身份。
first = await provider.freeze("run-1", scope)
await publish_second_source_revision()  # fixture 明确发布 revision=2，连接与目录均变化
restarted = ManagedConfigurationProvider(scopes, vault)
restored = await restarted.load_pinned(scope, first.references)
assert restored.references == first.references
assert restored.source_versions == {"operations": 1}
assert restored.sources["operations"].connection_dsn() == original_dsn
second = await restarted.freeze("run-2", scope)
assert second.source_versions == {"operations": 2}
# 独立 SQL 读取 runtime_snapshots，逐字段检查引用/哈希且没有 original_dsn/密码。
```

- [ ] 保留已有 `0006_runtime_snapshots` 及保留账号/会话/旧目录的升级测试；内部执行参数迁移接在其后，迁移 head 断言跟随实际新迁移。增加发布版本和运行引用不被重写的断言；重复 upgrade 不变。测试库使用项目 `psycopg` 驱动。
- [ ] freeze 在管理配置写事务同一锁顺序下读取默认源、当前发布指针及全部不可变依赖，并持久化；目前写事务使用同一 advisory lock，先沿用以保证一致性，不额外设计锁服务。外部取数不占用该事务；未来放松锁时必须保留并发一致性测试。
- [ ] 同 run 重试读回原记录；换源参数与原引用冲突时明确报错，不覆盖。同组织多运行、同 sourceId 跨组织和两个实例并发首次 freeze 均不串配置。恢复验证每个版本和哈希，缺失或不匹配时返回明确错误，不选择“最新”补位。

#### 4.2 可信入口与恢复授权

- [ ] HTTP 只从已验签 capability 的服务端上下文取得组织/用户/thread；MCP 从验证后的 token claims 取得；受控 CLI 从主机配置显式取得组织。由这些入口写入服务端运行身份记录，客户端 JSON、dependencies 或 `verified=true` 不能创建可信记录。
- [ ] 恢复必须同时匹配可信运行记录和当前合法调用身份/既有运行访问契约；工作流后台续跑按已接受的服务端运行记录执行。普通 Console 的 `default/default`、伪造组织字符串、admin Cookie 均不能授权 database 模式取数。
- [ ] load_pinned 只重建原记录对应的配置；停用后禁止新运行选源，恢复如需新增取数重新检查启停/范围，已物化数据继续沿用原身份；旧凭据失效明确报错，不改用新凭据。

#### 4.3 接入所有实际取数路径

- [ ] 增加部署级 `file/database` 选择并在 bootstrap 注入 provider；database 模式不调用文件加载器，也不因空库、连接失败或缺少发布依赖回退文件。
- [ ] `confirm_source` 冻结配置成功后将公开引用写入现有持久化状态；数据库模式读取已发布 metadata，不临时调用实时 metadata 替换其业务口径。实时 Catalog 只发现差异，不能扩大允许表范围。
- [ ] 检索 `_source`、`_sources`、`_resolve_profile`、`_adapter` 及 `self.registry/self.profiles` 的真实调用点，为运行显式传递配置/上下文；需要异步加载时同步修改调用链。共享 runtime 不保存“当前运行”或覆盖共享 registry；内存缓存最多是优化，清空缓存仍能恢复。
- [ ] 缺少依赖、可信组织或持久化失败均为取数前错误；这不改变报告产物签发软告警契约。存在可读历史成稿时仍按原授权读取，不为查看重跑取数。

#### 4.4 定点验收并提交

- [ ] 覆盖新运行用新版本、旧运行跨实例恢复旧版本、发布竞争只得到完整旧组合或新组合、跨组织拒绝、篡改引用拒绝、多源不兼容 Profile 拒绝、停用、旧凭据失效、数据库失败无文件回退，以及 file 模式兼容。
- [ ] 在 `confirm_source` 及后续实际物化调用上验证使用冻结连接和目录；只测试 provider 返回对象不算报告接入验收。运行状态、公开 API 和审计均检查没有明文凭据。
- [ ] 执行普通定点回归 `.venv/bin/python -m pytest -q smart_reporting/reporting/tests/test_report_data_sources.py`；真实存储用 `REPORTING_MANAGEMENT_TEST_DB_URL` 显式执行 `.venv/bin/python -m pytest -q -m integration smart_reporting/tests/test_managed_runtime.py smart_reporting/tests/test_management_migration.py smart_reporting/reporting/tests/test_managed_source_runtime.py`，按文件实际 mark 拆分单元/集成用例，不能漏跑或以 skip 计通过。保存结果后仅提交本任务文件。

**验收：** 两个独立 provider 实例及报告后续取数均保持版本固定；新运行无需重启即可读取新发布配置；伪造范围和公开引用不能选择数据库资源。

### Task 5：管理前端和数据源页面

**Files:** 新增 `smart_reporting/report_editor/frontend/management.html`、`vite.management.config.ts`、`src/management/main.tsx`、`src/management/App.tsx`、`src/management/api.ts`、`src/management/types.ts`、`src/management/pages/{Login,Account,Sources,SourceDetail,Activity}.tsx` 和 `src/management/management.css`；修改前端 `package.json`、`smart_reporting/management/api.py`、`Dockerfile`；新增 `src/management/management.test.tsx`。

**Interfaces:** React 从 `/management/api/v1/me` 获取当前身份；已登录的管理写请求带 CSRF，login 按访问矩阵执行；资源草稿与发布写请求另带 expectedVersion；后端 API 返回分页对象 `{items, nextCursor}`，错误对象 `{code, message, currentVersion?}`。管理静态资源构建到独立目录，生产复制到 `/opt/report-management-static`，不受源码只读挂载遮蔽。

```typescript
// 在页面测试中 mock API，验证真实用户操作对应的结果。
expect(screen.getByRole('button', { name: '测试连接' })).toBeVisible()
expect(screen.queryByLabelText('负责人')).toBeNull()
expect(screen.queryByLabelText('查询限额')).toBeNull()
```

- [ ] 写连接保存/测试/发布和冲突保留输入的页面测试；缺少测试渲染工具时仅增加 React Testing Library 的开发依赖。
- [ ] 新增独立管理入口，复用 React/Vite 构建，不引入 Milkdown、Office 引擎或可视化编辑器依赖。新增 admin 用户名/密码登录页、改密和退出入口；密码不进 URL、本地存储或操作日志。401 统一回到登录页，403 显示具体拒绝原因。
- [ ] 完成数据源列表、配置、目录、Profile 绑定和版本页；连接状态、目录同步状态和发布状态分别显示。
- [ ] 完成账号页、组织范围选择和审计分页页；表单提交成功刷新版本，409 时提示刷新/对比并保留输入，不自动覆盖。
- [ ] 执行 `npm --prefix smart_reporting/report_editor/frontend run test -- src/management/management.test.tsx` 和 `npm --prefix smart_reporting/report_editor/frontend run build:management`，通过后提交对应文件。

**验收：** 管理员通过页面发布数据源，并用该数据源完成一次现有报告取数；桌面和窄屏页面均可操作。

### Task 6：知识库、文档版本与原文存储

**Files:** 新增 `smart_reporting/business_knowledge/{__init__,models,repository,storage,service,api}.py`；新增数据库迁移；修改 `smart_reporting/app.py`；新增 `smart_reporting/tests/test_business_knowledge_documents.py`。

**Interfaces:** `KnowledgeBaseService.create(actor, payload)` 建库；`DocumentService.upload(actor, knowledge_base_id, file, metadata, *, document_id=None)` 返回包含 job ID 的 `DocumentVersion`，传入 document_id 时为已有文档追加版本；`DocumentStorage.read(scope, version_id)` 读取已登记文件。版本含 fileSha256、size、mediaType、category、tags、applicability 和 effectiveFrom/effectiveTo，不含负责人。

```python
old = await documents.upload(actor, kb.id, first_file, metadata)
new = await documents.upload(actor, kb.id, changed_file, metadata, document_id=old.document_id)
assert new.document_id == old.document_id
assert new.version_id != old.version_id
assert await storage.read(actor.scope, old.version_id) == first_file.content
```

- [ ] 为普通文本、带标题 DOCX、两页文本 PDF 和 Markdown 准备小型正常 fixture；验证版本更新保留旧文件、内容哈希、日期范围和文件可读性。
- [ ] 实现受控上传：单文件沿用项目 24 MiB 上限，流式接收并校验允许格式，服务端分配文件 ID，先暂存后原子落盘，落盘成功再登记处理任务。
- [ ] 实现库和文档分页、分类标签、适用范围、生效日期、版本详情及停用接口；停用后不进入新检索，历史版本和引用快照保留。
- [ ] 原文预览与下载均通过带当前 admin 会话校验的接口；复用 Task 1 的 admin 会话校验；报告检索则使用经验证的运行组织范围。
- [ ] 执行 `.venv/bin/python -m pytest -q smart_reporting/tests/test_business_knowledge_documents.py`，通过后提交对应文件。

**验收：** 新版本不会覆盖旧文档；文件随容器重建保留；页面可准确知道“已上传”与“已可检索”的区别。

### Task 7：Agno 索引、持久化处理任务与发布

**Files:** 新增 `smart_reporting/business_knowledge/{agno_backend,processing,worker}.py`；扩展 repository/service 和迁移；修改 `smart_reporting/runtime/{application,settings}.py`、`docker-compose.yml`、`pyproject.toml`、`uv.lock`；新增 `smart_reporting/tests/test_business_knowledge_processing.py`。

**Interfaces:** `KnowledgeBackend.index_version(scope, version_id, generation)`、`search(scope, allowed_versions, query)`；`ProcessingWorker.run_once()` 领取一个任务；`DocumentService.publish(actor, document_id, version_id, expected_version)` 仅接受索引 ready 的版本。

```python
await worker.run_once()  # fixture backend 返回确定性的分块及 embedding。
ready = await documents.get_version(actor, version.version_id)
assert ready.processing_status == "ready"
assert (await documents.get(actor, version.document_id)).published_version_id is None
await documents.publish(actor, version.document_id, version.version_id, expected_version=1)
assert (await documents.get(actor, version.document_id)).published_version_id == version.version_id
```

- [ ] 用确定性 backend 验证解析定位、全部分块完成才 ready、发布前不可检索、embedding 失败保留旧发布版本、租约过期恢复和重复处理幂等；再用真实 PgVector 适配器验证部分 batch 提交、相同正文跨组织/版本不覆盖、manifest 数量及哈希核对。
- [ ] 通过 Agno Reader/Chunking 保留段落定位，创建 Knowledge/PgVector 适配；显式传入中文 embedding 配置和维度。缺少 embedding 配置时任务失败并显示原因，不回退聊天模型。
- [ ] 处理任务按数据库租约、attempt 和 generation 提交；先写入新 generation，再读回 chunk ID 集合、数量、内容哈希、非空向量维度并与 manifest 比较，全匹配才将版本置为 ready。Agno 调用返回、日志没有异常均不能代替此检查。手动发布在数据库事务中切换当前版本；索引中的旧分块由服务端有效版本过滤排除。
- [ ] 应用生命周期启动/停止 worker，停止领取后等待当前操作有界退出，释放连接；首版不扩展现有 Coding TaskExecution 的执行语义。
- [ ] 在保持 PostgreSQL 18 的镜像中安装匹配的 pgvector，新增持久化知识目录。先检查当前卷和备份，禁止删除或用空卷替换已有数据库。
- [ ] 执行 `.venv/bin/python -m pytest -q smart_reporting/tests/test_business_knowledge_processing.py`；真实 PostgreSQL/pgvector 另跑标记 integration 的同文件用例，使用固定向量验证存取，不消耗真实模型调用。通过后提交对应文件。

**验收：** 重启能恢复待处理任务；旧文档在新版本处理失败时仍可用；明确发布后新版本才参与检索。

### Task 8：知识库页面与检索验证

**Files:** 新增 `smart_reporting/business_knowledge/retrieval.py`；扩展该模块 api；新增 `src/management/pages/{KnowledgeBases,KnowledgeDocuments,KnowledgeSearch,ProcessingJobs}.tsx` 和 `src/management/knowledge.test.tsx`；新增 `smart_reporting/tests/test_business_knowledge_search.py`。

**Interfaces:** `KnowledgeSearchService.search(actor, knowledge_base_ids, query, applicability)` 返回 `KnowledgeSearchResult`，包含 status、warnings、references；reference 包含文档标题、version ID、生效区间、位置、片段和哈希。请求里的库 ID 只表达选择，不构成授权。

```python
result = await search.search(actor, (kb.id,), "收入确认依据", applicability)
assert result.status == "ok"
assert all(ref.document_version_id == published.version_id for ref in result.references)
assert all(ref.location for ref in result.references)
```

- [ ] 测试正常组织集合、已发布有效版本、旧版本停用、未来生效文档、历史期间选版、无结果和后端不可用/状态无法确认的结果分类；使用确定性 embedding，但真实适配器故障测试不得只 mock 高层搜索返回值。
- [ ] 检索前确定组织、适用期间及有效 published-version 集合，作为强制条件传给 Agno；返回前再次核对当前组织和撤回状态，不允许模型修改范围过滤器。
- [ ] 完成建库、上传、文档列表、版本预览、处理步骤、失败重试、发布/停用页面；明确展示需要 OCR 或 embedding 未配置等原因。
- [ ] 完成检索验证页，查看命中来源并跳转原文定位；不把相似度显示成“事实正确率”。
- [ ] 执行 `.venv/bin/python -m pytest -q smart_reporting/tests/test_business_knowledge_search.py`、`npm --prefix smart_reporting/report_editor/frontend run test -- src/management/knowledge.test.tsx` 和管理入口构建；通过后提交对应文件。

**验收：** admin 能独立上传并发布一份制度文档，通过检索验证查看版本和定位。

### Task 9：报告知识检索、冻结引用与非阻断告警

**Files:** 新增 `smart_reporting/business_knowledge/report_context.py`；修改 `smart_reporting/reporting/bootstrap.py`、`smart_reporting/reporting/workflow/runtime/{base,sections}.py` 及 `smart_reporting/reporting/workflow/checkpoint.py` 中的 `SectionWorkItem`；新增 `smart_reporting/reporting/tests/test_business_knowledge_report.py`。引用来源展示先采用普通 Markdown 附录，不改造编辑器数值引用协议。

**Interfaces:** `ReportKnowledgeService.freeze_for_work_item(scope, run_id, work_item_id, query, applicability)` 返回 `FrozenKnowledgeContext`，含 knowledgeReferences 和 warnings；`read_frozen(scope, run_id, work_item_id)` 恢复同一快照。已冻结后不再次检索；引用记录和任务关联以原子写入或唯一键 upsert 保证幂等。

```python
first = await report_knowledge.freeze_for_work_item(scope, run_id, item_id, query, applicability)
await documents.publish(actor, document_id, newer_version_id, expected_version=2)
replayed = await report_knowledge.read_frozen(scope, run_id, item_id)
assert replayed.references == first.references
assert replayed.context_hash == first.context_hash
```

- [ ] 测试引用版本冻结、整章/分块一致、恢复不重复检索，以及历史知识数字不进入当前数值事实目录。用固定生成响应和正常文档案例验证，不调用真实模型；来源不匹配、历史数字及失败降级也必须覆盖。
- [ ] 在章节执行前检索并冻结少量相关段落，加入独立 `knowledgeContext`；明确与 frozenNumbers/指标证据分开，不修改工具权限和取数口径。
- [ ] 成稿引用使用 `〔知识N〕`，服务端基于冻结记录生成来源附录；缺少引用记录、文档冲突或索引不可用时添加具体软告警，不能伪造已通过状态。
- [ ] 检索异常或引用冻结失败后继续无知识补充的现有报告流程，未持久化片段不能进入模型上下文；原文查看需要当前 admin 会话，历史报告正文和引用依据按原报告访问策略保留。
- [ ] 执行 `.venv/bin/python -m pytest -q smart_reporting/reporting/tests/test_business_knowledge_report.py smart_reporting/reporting/tests/test_reporting_completion_content.py`，通过后提交对应文件。

**验收：** 一份报告同时展示数据计算依据和知识文档依据；知识库不可用时报告仍能按已有数据完成，并明确披露缺失依据。

### Task 10：部署、迁移演练与最终验收

**Files:** 新增 `docs/runbooks/data-source-knowledge-management.md`、`scripts/check_management.sh`；完善 `Dockerfile`、`docker-compose.yml`、`README.md`、`smart_reporting/README.md`；新增 `smart_reporting/tests/test_management_postgres.py` 和管理后台浏览器冒烟脚本。

**Interfaces:** Runbook 规定迁移、导入、切换、备份和恢复顺序；`scripts/check_management.sh` 默认执行本功能定点检查，显式 integration 参数才连接 `REPORTING_MANAGEMENT_TEST_DB_URL` 指向的独立测试库。

```bash
# 本节命令在实施收尾执行；本次仅出计划，不运行这些检查。
.venv/bin/python -m smart_reporting.management.cli import-config --help
npm --prefix smart_reporting/report_editor/frontend run build:management
bash scripts/check_management.sh
# 所有阶段完成、工作区整合后执行一次完整检查。
bash scripts/check_agentos.sh
```

- [ ] Runbook 列出 admin 初始化/改密/CLI 恢复、会话期限和管理公开地址、配置存储模式、凭据密钥、embedding 模型/维度、pgvector 和文件目录的部署参数，明确哪些是管理入口配置、哪些是报告运行配置。
- [ ] 在独立环境演练：备份现有数据库/文件 → 同主版本补充 pgvector → 迁移管理表 → 建立管理员 → dry-run 导入 → 正式导入 → 对账 → 显式切换 database 模式。
- [ ] 对账 sourceId、默认源、Profile 生效 hash、表目录和凭据版本引用；导入输出不得显示凭据值。切换前后用同一冻结数据验证现有报告数值一致。
- [ ] 浏览器冒烟执行登录、配置测试/发布、文档上传/重试/发布、检索验证、改密/退出/会话过期和版本冲突；保留操作结果及截图，普通 fixture 不冒充真实后端验收。
- [ ] 使用实际部署的 embedding 服务执行少量中文问题验收，记录问题、期望文档、实际命中和来源定位；这项真实集成验收不替代离线确定性测试。
- [ ] 恢复演练同时恢复数据库、文件和对应密钥；索引支持从原文件重建，检查已引用历史版本仍可读取。数据库备份与文件备份采用同一维护窗口或一致性快照。
- [ ] 执行本功能集成测试和下面的发布回归，再运行一次 `scripts/check_agentos.sh`。已有不相关工作区失败单独记录，不把未执行或跳过的集成测试计为通过。
- [ ] 完成一次“页面配置数据源 → 发布知识 → 生成报告 → 核对引用 → 下载 PDF/Word”的真实验收后，记录版本和结果并提交本任务文件。

### 发布回归要求

本计划优先在章节生成前冻结引用，避免向签发链路增加外部知识检索依赖。若实现确需改变发布/导出链路，必须执行 AGENTS.md 列出的全部非阻断契约；新增可能失败的签发步骤必须登记到 `test_http_publication_lineage.py` 的既有故障注入矩阵，新签发函数登记到 `_SIGNING_CHAIN`。

本功能必须新增普通故障用例：知识索引不可用、引用存储暂时不可用或文档处理失败时，已生成且身份可读的 PDF/Word 仍返回下载链接，并在结果中披露原因。

## 独立验收证据与复现方式

下表是端到端签收标准，**目前均未完成独立签收**。Task 1–4 的部分后端及定点存储测试已存在，详见进度文件；不得将这些局部证据升级为整行验收通过。本次更新只核对源码、审查结论和现存 JUnit，未重跑应用测试。

| 编号 | 要证明的结论 | 独立于实现者判断的证据 | 对应任务 |
| --- | --- | --- | --- |
| A1 | 所有管理入口都受保护 | 遍历实际 FastAPI route 列表；除访问矩阵明确列出的 login/logout 例外，逐个业务读取/写入 API 在无会话时为 401；请求参数有效，不能把 422 当认证通过 | 1、5 |
| A2 | 登录与撤销真实生效 | 真实数据库保存 Argon2id 哈希/会话哈希；两个 session 在改密、CLI 恢复后均被 HTTP 拒绝；退出后直接重放旧 Cookie 被拒绝 | 1 |
| A3 | 会话过期与重启符合契约 | 注入时钟验证 30 分钟/8 小时边界；重启服务后未过期 session 仍可用且绝对期限不延长 | 1、10 |
| A4 | admin 不影响既有报告授权 | 现有有效下载 grant、编辑 session、MCP 身份回归通过；这些凭据访问管理 API 仍不获得权限 | 1、10 |
| D1 | 发布配置与运行快照一致 | 真实 PostgreSQL 并发发布/取快照的双连接测试；记录旧运行和新运行各自的配置、Profile、目录哈希 | 2–4 |
| D2 | 迁移后执行参数与计算口径一致 | 独立读取原文件 parser 结果和数据库发布快照，对照完整 QueryLimits/Profile/目录；同一冻结数据计算对账；仅修改执行参数必须改变源版本，旧运行不漂移 | 2–4、10 |
| K1 | 索引完整且可恢复 | chunk manifest 与向量库读回的 ID/哈希/维度集合相等；进程中止、租约恢复后只激活一次正确 generation | 6、7 |
| K2 | 搜索有来源且状态真实 | 固定资料集、固定问题及期望定位；真实 embedding/pgvector 结果保存；查询故障不能显示“正常未命中” | 7、8 |
| R1 | 旧报告引用不漂移 | 更新/撤回原文后读取原报告：冻结文本、位置和哈希不变；原文失效有明确说明 | 9 |
| R2 | 知识异常不会阻断可下载产物 | 故障注入结果含具体告警；实际 GET PDF/Word 链接成功，文件大小及哈希匹配，验收失败不能标为通过 | 9、10 |
| O1 | 备份可恢复 | 独立恢复环境读回账号、配置、原文和历史引用；CLI 重置后旧会话失效；文件清单与备份 hash 对账 | 10 |

**资料集：** 准备 6 份脱敏小文档，覆盖文本 PDF 页码、DOCX 标题、TXT 行号、同义词表达、同一制度前后版本及相同正文的不同组织副本。业务人员从原文标注 12 个问题的期望：8 个可回答问题对应的文档/段落，2 个适用期间排除问题，2 个不同组织隔离问题。8 个可回答问题的期望段落均进入 top-5，期间与组织排除项不得返回不适用原文；引用定位逐一人工对照原文。测试不证明所有企业问题的通用准确率，失败项必须保留并修正，不能事后删除题目使结果达标。

**工具与输出：** pytest/HTTPX 记录接口断言；真实 PostgreSQL 记录事务结果；Playwright 记录桌面/窄屏操作及截图；SHA-256 对账文件和片段；容器重启与独立库恢复验证持久化。统一保存到 `/tmp/smart-reporting-management-acceptance/<run-id>/`，含 `manifest.json`、测试 JUnit、脱敏 HTTP 摘要、资料集版本、embedding 模型/维度、迁移版本、前端构建版本和恢复记录。manifest 明确 passed/failed/skipped/not_run 及原因，不保存密码、Cookie 或连接字符串。

**执行分层：** 各任务只运行自己的定点测试；管理模块 PostgreSQL 测试统一使用 `REPORTING_MANAGEMENT_TEST_DB_URL` 指向专用可清空独立库；SQLAlchemy URL 使用 `postgresql+psycopg://`，不切换为 asyncpg。知识模块集成 fixture 沿用同一测试变量并显式 `-m integration`；正常 pytest 默认排除 integration，不能据此宣称数据库验收完成。最后按任务清单合并定点结果，再执行一次 `bash scripts/check_agentos.sh`；不重复完整测试。真实模型报告验证使用本项目 `smart-reporting-real-os-test` 技能规定的原生运行方式，并记录实际执行结果。

**迁移回退：** 在新环境预演，确认 pgvector、schema 与旧服务兼容后才切换 database 模式。保留原文件配置和切换点备份；切换失败时停止接收新数据库模式任务，保存故障现场并恢复旧服务及 file 模式。数据库模式已经开始的运行不改写为文件模式运行，留待恢复数据库 provider 后继续。数据库账号/文件恢复使用同一备份窗口，恢复出来的管理会话一律撤销。本文未声称回退或恢复演练已通过。

**交付复核：** 另一位工程师应能凭 runbook、脱敏资料集、锁定依赖和上述 manifest 在独立环境复现 A1–O1；不能仅根据作者或模型的“通过”结论签收。

## 里程碑与完成标准

| 里程碑 | 对应任务 | 可验收结果 |
| --- | --- | --- |
| M1 数据源后台可用 | 1–5 | 页面发布配置后，无需重启即可按新版本取数；旧运行可恢复 |
| M2 知识库可用 | 6–8 | 上传、处理、发布、检索、定位形成闭环；失败可重试 |
| M3 报告集成与上线 | 9–10 | 报告依据可追溯，知识故障为软告警，迁移和恢复可执行 |

最终交付必须同时满足：

- [ ] 管理页面和 API 没有负责人或查询限额配置项。
- [ ] 数据源配置、Profile 和文档发布版本可读取、可对比、可追溯。
- [ ] 全部管理 API 均检查有效 admin 会话；报告资源范围来自服务端验证的调用身份，不能借用 admin 会话或自动补出的 default 值。
- [ ] 数据库模式只有一个配置权威来源，页面发布不依赖服务重启；规范化输入能重建配置身份，迁移保留现有执行参数且不增加可编辑限额。
- [ ] 文档索引失败不影响上一发布版本；任务重启恢复不会重复激活错误代次。
- [ ] 中文业务问题能够命中预期文档，并显示可靠的页码/章节来源。
- [ ] 恢复报告沿用冻结的数据配置、知识片段和版本，不重新解释历史依据。
- [ ] 知识异常或业务验收失败明确披露，已生成且身份可读的 PDF/Word 仍可下载。
- [ ] 完成真实管理操作、报告生成及备份恢复验收，记录实际执行与未执行项目。

## 执行顺序与提交建议

按 Task 顺序逐项实施、定点验证、定点提交；只暂存本任务文件。Task 5、8、10 分别进行页面或完整链路验收。实施中只有遇到与本计划冲突的现有契约才调整计划，不顺带重构 Office 引擎、数值引用体系或 Coding Agent 协议。
