# pros/chat 开发规范

## 适用范围与执行原则

- 本文件适用于仓库全部目录；更深层目录若有自己的 `AGENTS.md`，以更具体的规则为准。
- 沟通、交付说明、用户可见文案和新增业务注释使用中文；代码标识符、协议字段、稳定错误码和日志检索标识使用英文。
- 新增复杂业务逻辑、跨阶段状态转换、失败关闭校验或非显然协议约束时，必须添加详细中文注释，说明事实来源、执行边界、拒绝原因及不可绕过的不变量；自解释的赋值、分支和调用不做逐行复述，注释必须随实现同步维护。
- 修改前先阅读相关实现、测试和文档，明确假设、影响范围与可验证的成功标准；存在会改变方案的歧义时先询问。
- 只修改完成任务所需的代码。不要顺带重构、改名、格式化无关文件，也不要删除既有但与任务无关的代码。
- 优先复用现有实现；不为单次使用增加抽象、配置项、兼容层或推测性的错误处理。
- Coding Agent 在设计、编码、修复和评审时必须遵循强反馈、强契约、强工具和强规范化；涉及 Agno 时必须优先使用锁定版本的官方公共实现，不得重复造轮子。
- 修复缺陷时先添加或确认能复现问题的测试，再做最小修复；每一处改动都应能追溯到任务或对应测试。
- 工作区可能包含用户的未提交改动。不得覆盖、回退或清理这些改动；发现无关问题时只在交付说明中指出。

## Skills 使用

- 修改 Agno、AgentOS 或 AG-UI 时使用 `agno`，涉及 API 名称、参数、版本或升级时同时使用 `agno-docs` 核对官方文档。
- 编写或评审 React 代码时使用 `vercel-react-best-practices`；做明确的 UI、UX 或可访问性审查时再使用 `web-design-guidelines`。
- 编写 Python 测试或调整 pytest 结构时使用 `python-testing-patterns`。
- 仅在用户明确要求安全审查、安全报告或 secure-by-default 实现时使用 `security-best-practices`。
- 修改跨端浏览器流程、Playwright 配置或用例时使用 `playwright-best-practices`。
- 只加载与当前任务直接相关的 skill；项目现有实现、锁定版本和本文件约束优先于通用示例。

## 架构边界与事实来源

- `agui_chat/` 是 Odoo 12 核心模块，负责配置、权限、会话、页面宿主、业务命令和授权审计。
- `agui_chat/react_widget/` 是 React 18、TypeScript strict、Vite 的 AG-UI 客户端。
- `agentos_dev/` 是 Python 3.12、FastAPI、Agno 2.8.2 的 AgentOS 服务，负责智能体、AG-UI、持久化和 Daytona 工作区。
- `agui_chat_test/` 是本地 Odoo 集成测试夹具，不是产品业务实现。
- 纯 Coding Agent 定位为领域无关的通用软件工程执行能力，只依据用户目标、当前工作区和通用工具完成编码、运行与验证；可以按任务编写任意领域代码，但不得内置特定业务领域的流程、知识、工具或验收规则。
- Report Agent 与纯 Coding Agent 是独立产品边界，必须保持解耦。两者不得相互导入或复用对方的领域指令、工具集、状态机、控制器、验收契约、运行入口或持久化状态；纯 Coding Agent 中禁止加入报表、取数、数据源或特定任务类型的规则。
- 两类 Agent 仅可依赖领域无关且接口稳定的底层能力，例如模型适配、工作区原语、通用执行记录和可观测性。共享能力应下沉到中立模块并由双方单向依赖，不得通过条件分支、反向导入或兼容层把两条运行链路重新耦合；相关测试和入口必须能够独立运行。
- Odoo `BasicModel` 是当前业务页面状态的唯一权威来源。React 和 AgentOS 只能消费宿主快照与 token，不得维护可绕过宿主的新业务真相。
- 生产环境中，浏览器通过同源 AgentOS 端点运行 AG-UI SSE；Odoo 不代理 SSE。跨域 HTTP(S) 绝对地址仅限显式启用 `allow_cross_origin_dev` 的开发环境。不要新增绕过现有握手、鉴权或恢复流程的第二条传输链路。
- 协议以实现、类型和 `docs/agui_odoo_protocol.md` 共同约束。修改事件、请求头、工具 schema、错误码、状态机或版本握手时，必须同步前后端、测试和协议文档。
- 根目录 AgentOS Compose 与 `docker/` Daytona Compose 相互独立，不得假设共享网络、项目名、凭据或数据卷。

## Odoo 与导入模块

- 不开放通用 RPC、任意模型 CRUD 或 Agent 直接操作 ORM。新增业务能力必须走注册命令、启用配置、精确策略、准备/确认、一次性授权和幂等执行链路。
- 页面读取与写入继续使用当前控制器和 `BasicModel` 原生行为，保留 onchange、dirty state、modifiers、字段解析、校验、保存和丢弃语义；不得增加通用 RPC fallback。
- 所有 token、授权和命令必须继续绑定当前数据库、用户、公司、会话、thread、run、tool call、控制器、记录、快照及 payload 中适用的部分。
- 使用 `sudo()` 前后仍须显式保留用户、公司、所有权、ACL、record rule 或精确策略校验。`sudo()` 只能用于已验证后的必要系统操作，不能代替授权。
- 控制器入口必须校验输入类型、长度、数量、所有权和状态；对外返回稳定 `code`，不要暴露 traceback、内部路径或敏感值。
- 修改模型、访问权限、XML 数据或前端资源时，检查对应 `__manifest__.py` 版本、依赖、加载顺序和迁移影响。

## React 客户端

- 保持 TypeScript strict，不通过放宽 `tsconfig`、扩大 `any` 或复制后端模型来规避类型问题；协议类型集中维护并复用现有 runtime API。
- 派生值优先在渲染阶段计算；`useEffect` 只用于与外部系统同步，并保持完整依赖和清理逻辑。不要默认增加 `memo`、`useMemo` 或 `useCallback`，应以实际渲染成本为依据。
- 不复制 Odoo 页面状态。命令完成、工具续跑、断线恢复、切换 thread 或 branch 后，必须以最新宿主快照和 AgentOS run 状态为准，禁止复用旧 token。
- UI 延续现有紧凑工作台风格。交互控件使用语义化元素和可访问名称，支持键盘、可见焦点、长文本、空/加载/失败状态、窄屏和 `prefers-reduced-motion`。
- 图标优先使用现有 `lucide-react`，不手绘重复 SVG；不为说明功能添加可见帮助文案，必要说明使用可访问标签或 tooltip。
- Markdown 保持 `react-markdown` 默认禁用 raw HTML。外部链接必须限制安全协议并使用 `noopener noreferrer`；附件上传、下载和预览必须保留所有权、MIME、大小及 URL 校验。
- 包管理统一使用 `pnpm` 和现有 `pnpm-lock.yaml`。不要混用 npm/yarn，也不要无理由刷新锁文件。
- `agui_chat/static/lib/agui-chat-react/` 是 Vite 构建产物，禁止手工编辑。修改源码后运行构建并审查生成差异；调整资源版本时同步 `package.json`、模块 manifest、Vite 文件名和所有静态资源引用。

## AgentOS 与 Agno

- 依赖版本以 `agentos_dev/requirements.in` 和锁定的 `requirements*.txt` 为准；不要凭记忆套用其他 Agno 版本的 API。
- 优先使用 Agno 公共 API。`agentos_dev/app.py` 当前使用 `agno.os.interfaces.agui.router.run_entity` 等内部接口；修改相关代码或升级 `agno`、`ag-ui-protocol` 时，必须核对官方文档和源码并补充契约测试。
- 保持 `AgentOS`、`AGUI`、`PostgresDb` 的现有职责，不自行复制运行历史、会话持久化或协议路由。结构化输入输出使用明确的 Pydantic/schema 模型，不手工拼接可结构化的数据。
- FastAPI 异步入口不得直接执行阻塞 I/O；沿用线程池或异步客户端边界，并覆盖取消、超时和依赖失败路径。
- Agent 工具坚持最小能力和显式 schema。不得增加任意 Shell、任意 Python、任意文件系统或未注册 Odoo 操作；有副作用的覆盖、删除和技能执行继续要求确认。
- Daytona 工作区保持每个 thread 隔离，并继续限制目录穿越、绝对路径、符号链接、文件类型、文件数量、总大小、单文件大小和执行超时。
- 配置缺失、鉴权失败或依赖不可用时失败关闭，不使用弱默认密钥、跳过校验或静默降级。

## 安全与协议不变量

- 不提交 `.env`、密钥、令牌、数据库、备份、缓存或本地运行产物；示例配置只能包含安全占位值。
- capability 必须校验签名、算法、受众、签发/过期时间、数据库、用户、公司、会话和 thread 绑定；source/target branch 还必须校验身份一致性。失败时拒绝请求。
- 在读取大型请求体、访问附件、执行命令或创建工作区前完成适用的身份、大小、所有权和状态检查。
- 命令授权必须保持 payload hash、一次性状态转换和幂等键语义；重放只能返回已存结果或明确冲突，不能再次产生副作用。
- 前端输入不得放宽 Odoo ACL、record rule、命令白名单、字段策略、AgentOS 工具限制或文件边界。
- 日志、异常、审计事件和 Agent 上下文不得泄露 Cookie、令牌、密钥、密码、原始 capability 或敏感业务字段；敏感预览继续使用脱敏值。

## 测试与验证

- 新增行为覆盖正常路径和与改动直接相关的失败路径。鉴权、幂等、重放、过期、跨用户/公司/thread 和输入边界变更必须有负向测试。
- 默认先运行与改动直接对应的定点测试节点或最小测试文件，不得用整个目录、全部单元测试或端到端测试代替定点验证。只有定点测试无法覆盖跨模块契约、改动确实跨越完整服务流程或用户明确要求时，才按风险逐级扩大测试范围。
- 修改 `agentos_dev/` 的 Python 实现、测试或依赖时，默认运行定点 pytest，并对改动文件运行 Ruff format、Ruff lint 和必要的 Mypy；只有跨模块影响需要完整非集成回归或用户明确要求全量检查时，才在仓库根目录运行 `bash scripts/check_agentos.sh`。
- 沙箱内运行异步 SQLite 测试时，若 `aiosqlite` worker 已完成操作但 asyncio self-pipe 唤醒报 `PermissionError: [Errno 1] Operation not permitted`，表现为首次连接或 fixture 假死，应将其识别为沙箱限制而非业务死锁；在获得权限后于沙箱外重跑相同检查，不得为绕过该环境限制修改业务实现。
- Python 单元测试使用小而明确的 fixture、`tmp_path`、`monkeypatch`/mock 和异步测试；不得访问真实网络或共享用户目录。外部 PostgreSQL/Daytona 场景标记为 `integration`。
- 修改 React 组件、状态或协议适配时，在 `agui_chat/react_widget/` 运行 `pnpm typecheck`、`pnpm test` 和 `pnpm build`。组件状态、渲染和纯协议逻辑优先用 Vitest 与 Testing Library。
- 只有修改 Odoo 宿主交互、AG-UI/SSE 契约、断线恢复、关键浏览器流程或视觉布局时，才运行对应 Playwright：`pnpm test:e2e:odoo` 或 `pnpm test:visual`。
- Playwright 优先使用 role/label 等用户可见 locator、web-first assertions 和自动等待；禁止用 `waitForTimeout` 掩盖竞态。自有 Odoo/AgentOS 集成不 mock，第三方边界可稳定 mock。
- 修改 Odoo 模型、控制器、权限、数据或宿主 JS 时，运行对应 Odoo Python/QUnit 测试；无法运行时说明未验证项、原因和建议命令。
- 修改根目录 Compose 或环境变量时运行 `docker compose config`；修改 Daytona Compose 时运行 `docker compose --env-file docker/.env -f docker/docker-compose.yaml config`。同步相应 `.env.example` 和部署文档。
- 纯文档改动至少运行 `git diff --check -- <文件>` 并人工检查最终差异，不需要运行业务测试。

## 依赖、文档与交付

- 修改直接依赖时同步输入文件和锁定文件，说明兼容性原因；不要手改生成锁文件，也不要顺带升级无关依赖。
- 修改公共接口、配置项、协议字段、持久化结构或部署行为时，更新对应 README、`docs/`、示例配置及迁移说明。
- 完成前检查工作区和最终差异，确保没有密钥、调试代码、临时文件、无关格式化或被误改的生成产物。
- 交付说明必须列出实际改动、实际执行的检查及结果、未执行测试及原因，以及仍存在的兼容性或部署风险；不要声称运行过未执行的检查。
