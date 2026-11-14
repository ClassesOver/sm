# Agno 3.1.12、Harness 双模式与五格式交付统一计划

> 实施者：执行恢复后，使用 `superpowers:executing-plans` 按任务推进；需要独立子 agent 实施/复核时使用 `superpowers:subagent-driven-development`，子 agent 与 root 同模型。先读本计划与适用的 AGENTS.md，再核当前源码。本文件包含执行所需的设计和验收要求，不依赖另行提交旧计划或 brief。

**更新日期：** 2026-11-14。**实施目标状态：paused。** 本次提交独立验证的基础代码和最新计划；不恢复后续 Harness 实施、不启用生产 Codex。

**目标：** 在 Agno 3.1.12 基线上，让用户通过同一逻辑频道的站内或外部原生会话完成报告；默认外部 harness 间接控制内置 Codex harness，显式直接接管时只运行选定的一个执行 harness；交付 MD、XLSX、PPTX、PDF、DOCX，并最终移除 CodeMode。

**架构：** 会话入口负责双向交流，harness 负责规划与执行，现有服务端负责任务身份、工具权限、持久状态、租约和产物核验。受控数据库计算、Office、标准可视化和模板作为共享工具；复用 AgentOS、原生 MCP、现有 TaskSession 与 Agno 本地工作区，不新增通用调度平台或另一套模型执行循环。

**技术基线：** `agno[mcp,codex]==3.1.12`、`dingyi-agno==0.5.4`、`openai-codex==0.163.0`；CLI 0.163.0 已有历史验证记录，后续部署须记录实际版本。`uv.lock` 是开发和镜像安装的同一依据。

**唯一计划入口：** 本文件已合并 Harness 双模式设计、架构风险验收与原 Task42 受控计算细则。提交 Git 只需这一份计划；旧计划、拆分设计和 brief 不再作为执行依赖。历史任务编号仅用于识别已有成果，不代表新增任务已完成。

**本次 PR 范围：** 只包含 Agno 3.1.12 与 Codex SDK/CLI 0.163.0 锁定、元数据客户端直接注入、Task21 协程级租约/取消守卫及本计划。下文 Task17–41 的其他历史实现未随本 PR 提交；部分 Codex、五格式和管理端前置模块在此分支不存在。恢复实施时必须先核当前源码与精确归属，独立引入并验证必要前置，不能把历史成果表当成本 PR 已交付清单。

**历史证据说明：** 本机保留此前测试、审查、失败记录和精确补丁，未随本次计划提交。第 3 节记录的是历史结论及其限制，不冒充新环境已验证；接手者须先核当前源码及可获得证据，缺证据标记未验证，不将本地路径当成仓库必备文件。

## 1. 已确认约束

1. **默认间接控制。** 未指定 `executionMode` 固定为 `delegated`；外部 DSH/Codex/Claude 等负责交互与委派，内置智能报告 Codex harness 负责详细规划、受控取数调用、分析、编程、生成与修复。外部不重复执行同一报告。
2. **直接接管显式选择。** `executionMode=direct` 时由选定的一个 harness 调共享工具，不隐含再启动内置 Codex 报告任务。“一个”指唯一报告主执行入口，不禁止其范围明确的原生子 agent。
3. **正式事实只来自受控数据库计算和登记。** 文件、模板和模型数字只能作参考，不能填补或替换业务事实；制度阈值、定义由已发布口径管理。没有数据库证据的问题标为不可回答/未核验，不转为纯文件取数。
4. **保留可信边界，精简固定步骤。** 标准算子、标准可视化与模板可作为按需工具/库，不要求每次报告必经；受控查询权限、确定性计算、来源登记、独立回读不能因统一 harness 而删除。不重写公式或 SQL 计算引擎，不移除 `fg-data-profiling`，不恢复旧业务 Profile。
5. **五格式单目标。** `deliveryFormat=md|xlsx|pptx|pdf|docx`，新任务默认 PDF，Word 显示为 Word、内部 docx。只交付实际生成且身份可核验的目标格式；保留旧 `document`、`word`、历史产物与下载兼容。
6. **CodexAgent 禁 DockerSandbox。** 复用工作流已登记的 Agno 本地工作区，服务端解析 cwd，`sandbox=None`，保留原生 `workspace-write`；不自动 full-access，不恢复已删除 Docker 专用代码，不引入替代容器/自制沙箱。工作区路径和环境净化不代表宿主文件隔离；实际权限须验证。该禁令不扩展为删除其他功能已有 Docker 用途。
7. **框架基线不回退。** `[tool.uv]` 保留显式 Agno 3.1.12 override；不使用 `--no-deps` 或改 site-packages，不顺带升级业务依赖。当前已有 `packaging==25.0` override 保留其历史兼容依据，不能为简化计划直接删掉。
8. **服务端掌握执行权。** 冻结租户、用户、任务、controller/executor、修订、输入/模板摘要、工作区、目标格式和权限；租约与最终版本检查不能由模型口头保证替代。业务 DB 凭据不进入任何 harness。
9. **子 agent 协作有边界。** 内置 Codex 的子 agent 同模型，权限收窄，预算归父，取消/超时/恢复覆盖子任务；只并行无依赖且写范围不冲突的任务。外部异构 harness 接入与内置同模型子 agent 是不同概念。
10. **真实能力未通过不启用。** 当前 provider 不自动更换；请求次数硬帽缺口不得用 timeout、工具调用次数、一次 arun 或不完整 usage 冒充。生产保持 disabled；服务端与离线验证可以独立推进，不能把局部通过算作生产能力。
11. **验收失败不阻断可信下载。** 验收/溯源问题写入 issues 并如实显示；仅拒用越权数据、身份不符或不存在的目标，不阻断合法用户下载已核验身份的实际文件。新签发故障点登记 HTTP 故障注入，新签发函数登记 `_SIGNING_CHAIN`。
12. **当前没有业务人员。** `businessApproval=not_performed`；独立计算预期、文件回读和技术审查不冒充业务签字，不新增人工发布阻断门禁。语义业务校验使用消歧和软告警，减少固定措辞依赖。
13. **当前工作区实施。** 直接 `/home/junge/pros/smart_reporting`，不新建 worktree。修改前保存完整当前基线、exists/mode/SHA，以精确任务补丁区分贡献，不覆盖、回滚或提交其他任务改动。只运行受影响测试及一次必要组合，不重复完整测试。日志用 loguru；新图只用 Matplotlib PNG/JPEG。

## 2. 执行模式与完整流程

| 项目 | 默认 `delegated` | 显式 `direct` |
|---|---|---|
| 拓扑 | 外部 harness → 内置报告 Codex → 共享工具 | 选定的一个 harness → 共享工具 |
| controller | 外部已授权 harness；站内发起可无外部 controller | 与 executor 相同 |
| executor | 内置智能报告 Codex harness | 已验证能力的选定 harness |
| 同报告计算/写入 | 仅 executor 及其获授权子任务 | 仅选定 executor 及其获授权子任务 |
| 用户交互 | DSH 等原生会话与站内均可追加要求、回答追问、看进度和取消 | 相同 |
| 事实与交付核验 | 服务端受控计算、文件身份与独立回读 | 相同 |

创建时冻结模式与身份。仅因用户在 DSH 说话不切成 direct；内置能力不可用时明确返回原因，不静默换模型或改模式。运行中禁止热切换；换主先停止/对账旧执行、撤销旧租约，再建立关联新任务。不能确认旧执行停止时，不授予相同输出范围的新执行权。

目标流程由 executor 主导：登记需求/目标格式/材料 → 先读参考与模板结构 → 绑定已发布数据源/目录/指标/口径 → 分析规划与受控计算 → 冻结事实及来源 → 按目标格式生成 → 服务端独立回读 → 修订登记与非阻断下载。新事实需求回到受控计算，不从附件猜数。现有仅在 facts 后启动 generation 的链是迁移基础，不是最终“主导规划”完成状态。

### 2.1. 同一频道、双向会话与任务路由

用户可始终在真实 DSH 原生会话交流，也可从站内入口查看、追加要求、回答追问和取消。同一逻辑频道可包含多个独立根任务，不设置永久垄断频道的主 agent；DSH 的会话入口和执行能力分别验证。不同租户或用户的原生会话不能按名称自动合并。

以下为最小业务语义，优先落在现有数据模型中，不要求新建同名平台或每项单独一张表：

| 对象 | 必须登记的语义 |
|---|---|
| Channel | 逻辑频道、租户/用户可见范围、参与者及绑定入口 |
| EndpointBinding | 原生会话 ID、适配器、认证身份、订阅范围及重连代次 |
| Message | messageId、origin 与原生 messageId、可信角色、replyTo/causation、taskId、正文或授权附件引用 |
| InteractionRequest | requestId、taskId、目标用户、问题/选项、状态和版本 |
| Task | 根/父子关系、冻结模式与 controller/executor、原生 run/thread 映射、输入合同、工具授权、预算及租约 |
| Event | eventId、任务与流代次、稳定序号、来源、类型、时间、摘要及获授权产物引用 |

适配器认证后登记用户消息，按服务端命令顺序投递给责任 harness。原发端不重复制造用户消息；其他端显示关联副本，origin+messageId 去重防止回声。agent 输出和附件文本不能升级为用户命令或批准。同一追问由任一授权入口回答一次，按 requestId、版本及目标用户核验，其他端同步已处理状态；普通聊天不自动启动计算/Office 写入。

首版沿用确定性 FIFO、每租户/用户并发限制与现有租约：依赖未完成则等待，写入范围冲突则排队；用户编辑不被长时间锁住，提交时原子核文档版本/目标对象与租约代次。只读复核可用冻结快照，发现问题反馈当前 executor；不能因外部拥有其他工具权限就在同一报告重复写入。

### 2.2. 内置报告 Harness 对外接口与真实进度

委派优先验证并复用锁定 Agno 原生 A2A；仅支持 MCP 的客户端可通过同一 Task 服务的薄适配提交、查询、补充/回答和取消。没有原生会话回传能力时，只标示任务调用/查询可用，不宣称双向聊天已接通；不复制任务执行循环、不迁移 DB 凭据或原生 thread 状态到对方进程。

| 对外能力 | 必须返回或保留的合同 |
|---|---|
| 发现 | 支持格式、材料/模板要求、已验证交互/恢复/预算能力；未知明确标示 |
| 提交 | clientRequestId 幂等、taskId、冻结模式与身份、状态及授权事件引用；单目标默认 PDF |
| 追加/回答 | 原 taskId、requestId/interactionId 与版本；继续原任务，不重建报告 |
| 进度/恢复 | cursor、任务快照、实际阶段、等待原因、最近活动、工具回执与具体问题 |
| 产物/修订 | 实际文件身份、修订、来源/验收结果和逐接收端下载授权 |
| 取消 | 持久取消请求、传播到 executor/子任务、实际停止或待确认/unknown 状态 |

外部 threadId 仅是来源引用，不是本地授权；父子关系由服务端登记。外部 controller 收集需求和向用户收口，详细执行规划由内置 Codex 完成。委派重试返回同任务，同键改输入拒绝；任务控制与工具执行使用不同用途权限。整套报告可以由外部会话控制，不要求用户进入站内页面。

必要事件先持久后推送，重连按稳定 cursor 补发；过旧回读快照。界面区分排队、等待依赖/资源/用户、运行、取消请求/确认、失败、完成及结果未知，映射既有 Task 状态和原因，不造第二套冲突状态机。失联不等于失败或取消完成；Office applied、回读 verified、保存修订和业务核验分别展示，不编造进度百分比。

仅同步用户可见摘要及授权内容，不复制私有推理、凭据或完整内部轨迹；加入频道不自动获得历史全文、附件和下载 bearer。撤销阻止后续投递/读取，不承诺收回已发数据。外部 HTML 不直接执行；如使用 postMessage，严格核 origin/source/schema；callback/产物 URL 由服务端限制目的地和重定向，避免内部地址访问。不能将这些待实施要求表述为已修复的漏洞。

## 3. 已有工作、证据与缺口

本表复用历史报告，不表示本次重新运行了这些测试；各批增量测试不相加冒称一次完整套件。

| 能力 | 当前可复用成果 | 尚未证明/完成 |
|---|---|---|
| Agno 基线、低风险清理 | 依赖与锁文件固定 3.1.12；历史实施记录记载元数据直接注入及旧备用提纲清理 | 新接入造成的受影响兼容回归、部署同锁验收仍须覆盖 |
| 本地 Codex | Task17/19/21/22/24 的构造、真实 provider、持久绑定、取消及环境边界证据 | 不是宿主秘密隔离、恶意后代回收或跨 harness 全链证明 |
| 材料与模板 | Task23/25/27：内部 20 份参考加独立模板、五格式定位、冻结与跨进程恢复 | 外部 MCP `ReportingStartInput.attachments` 当前仍 max_length=4；入口容量未统一，不能归为 Agno 全局限制 |
| 原生子 agent | Task30/31：协作事件、spawn/wait、有限恢复和合作脚本取消 | resolved 模型遥测与总体验收存在限制；不能宣称完整父子预算/恢复已通过 |
| 标准图 | Task33/34：可信材料准备与真实 Agno MCP 消费、静态 PNG 独立回读 | 其余算子/模板/编辑器消费者迁移，非所有标准工具完成 |
| generation 生命周期 | Task35/36：耐久身份、真实 MD 生成与完成回执；Task37：共同下载 | 全面规划迁移、五格式真实模型全链、生产硬预算与完整 ACTIVE 恢复 |
| 编辑与修订 | Task38 四原生格式；Task39 MD 文字编辑；旧 Task6–12 的保存稿冻结/刷新及 UI | generation 正式 DB 刷新、MD 图片/空 MD、完整 GUI 与五格式新链回归 |
| 受控初始计算 | Task41：真实服务消费者、耐久 intent、唯一领取、unknown 不重查；隔离 PG 验证 | 不是 StarRocks、MCP、模型或完整工作流验收 |
| 原 Task42 | 只读接口调查与技术要求已并入本计划 P3；未据此宣称应用已接入 | 暂停，恢复后按 P3 实现和验证，不依赖旧 brief |
| Harness 外接 | 双模式设计及风险验收已合并到本计划 | 真实 DSH 版本/原生会话 API、A2A 装配、双向进度/追问/取消尚未验证 |

本机可查的历史证据包括 Task34 标准图回读、Task35 独立任务身份、Task36 原生 MD、Task37 下载、Task38/39 编辑和 Task41 受控计算报告。接手时先核证据覆盖及源码漂移，缺证据不勾选通过；已有可信证据不机械重跑。历史证据用于复核，不构成本计划之外的执行指令。

## 4. 实施顺序与任务边界

恢复实施后的顺序：**P0 基线/能力核对 → P1 默认模式与任务授权 → P2 默认间接 Office 双向闭环 → P3 受控计算与 facts 前主导 → P4 五格式/模板/修订 → P5 完整生命周期与预算验收 → P6 显式直接接管及第二外部 harness → P7 移除 CodeMode 与最终验收。**

取消、租约、权限和幂等从 P1 起随每个有副作用的入口实现；P5 是跨链补齐和故障验收，不能成为前面跳过安全边界的理由。所有任务下列复选项均为待实施要求，不能据历史局部记录直接勾选。

### P0：确认当前基线与真实接入能力

**范围：** `pyproject.toml`、`uv.lock`、`smart_reporting/runtime/application.py`、`smart_reporting/reporting/codex_agent.py`、`smart_reporting/reporting/codex_local_environment.py` 只读核对；必要差异适配按受影响路径单列，不再升级依赖。

- [ ] 核锁文件/安装环境/CLI 版本、AgentOS/Workflow/事件/模型适配，复用原基线证据；当前已有的版本不重做升级。
- [ ] 定位真实 DSH 版本、会话/插件接口、认证和事件/继续/取消/恢复能力；外部模型 API 可调用不能算会话已接入。核 Agno 原生 A2A/MCP 适配，当前 `interfaces=[]` 不算已装配。
- [ ] 出具逐适配器能力表及实证路径：双向消息、任务委派、追加输入、取消确认、恢复、用量和硬预算分别标明已验证/未知/不支持。无真实 DSH 接口时继续服务端合同与隔离测试，真实双向验收保持未完成，不换成模型后端冒充。

**验收：** 清楚区分现有代码、历史探针、计划能力；不启用生产。新增干净环境验证确有需要时用 `uv sync --locked --group dev`，不得读取业务 `.env` 或改锁解决无关依赖。

### P1：冻结默认模式、唯一执行权与最小任务控制契约

**候选修改面：** `smart_reporting/reporting_mcp/contracts.py`、`adapter.py`、`identity.py`、`smart_reporting/reporting/workflow/controller.py`、`smart_reporting/task_execution/models.py`、`repository.py`/`repository_impl.py`、`session.py`。复用现有合同与存储，只在明确缺口处分出小模块。

**输入/输出：** 已认证用户/入口、clientRequestId、目标格式与已登记输入 → 持久 taskId、冻结 executionMode/controllerHarnessId/executorHarnessId、输入摘要、状态与授权结果引用。字段是本项目拟实施合同，不是厂商 SDK 同名 API。

- [ ] 先写参数化反例，再最小实现：缺省模式为 delegated；direct 必须显式选择已授权 executor；同请求重试返回同任务，同键改输入冲突；旧请求不改历史 hash，旧任务不被补写新执行身份。
- [ ] 将任务控制权与计算/Office 写入权分开；controller 仅提交、查询、订阅、补充/回答、取消及获授权结果读取。服务端冻结身份，拒用跨租户/修订/输入/旧租约及错误用途 token。
- [ ] 复用现有租约和提交 CAS；模型不得 claim 他人租约或伪报完成。验证取消与旧 worker 迟到提交的竞态；新任务不能复活旧 thread。
- [ ] 定向通过后独立复核精确补丁，记录兼容旧请求与生产禁用开关的结果。

**计划新增测试：** `smart_reporting/reporting_mcp/tests/test_harness_execution_contract.py`；扩展现有 `test_contracts.py`、`test_identity.py`、`smart_reporting/task_execution/tests/test_task_cancel_lease_fence.py` 中直接受影响 case。

验收用例数据（待新增测试直接参数化使用）：

```json
[
  {"case":"mode_omitted","expectedMode":"delegated","expectedExecutor":"builtin_codex"},
  {"case":"explicit_direct_authorized","expectedMode":"direct","builtinRunCount":0},
  {"case":"controller_writes_same_report","allowed":false},
  {"case":"same_request_retry","createdTaskCount":1},
  {"case":"same_key_changed_inputs","allowed":false},
  {"case":"builtin_unavailable","fallbackToDirect":false},
  {"case":"stale_lease_commit","allowed":false}
]
```

其中 builtin_codex 是验收中的角色标识，具体适配器 ID 由服务端登记，不能由请求随意指定。P1 用执行替身验证路由合同，不宣称真实 harness 已运行。

### P2：默认间接模式的真实 Office 双向闭环

**候选修改面：** `smart_reporting/runtime/application.py`、`smart_reporting/reporting_mcp/tools.py`/`adapter.py`、`smart_reporting/report_editor/agent_event_streams.py`、`frontend/src/office-assistant-panel.ts` 及现有 Office 服务；外部 DSH 适配文件须在 P0 定位实际插件接口后给出精确归属，不预造另一套平台。

**输入/输出：** DSH 原生消息与已授权 Office 对象 → 同一 taskId 的追问、用户回答、工具回执、实际对象回读和两端可见进度。

- [ ] 先验证消息来源/角色、origin+messageId 去重、requestId+版本一次性回答；只同步获授权内容，不把 agent 或附件正文升级为用户指令。
- [ ] 以现有任务仓储持久登记必要控制/进度事件，再投递 SSE/原生入口；稳定 cursor 断线补发，过旧回读快照。内存 `AgentEventLog` 不能当跨进程恢复证据。
- [ ] 走 DSH → 内置 Codex → Office 读取/定点修改 → 原生 DSH 追问/回答 → 继续/独立回读；站内查看同任务。当前宿主按实际连接选择，不同时重建两套 Office 引擎。
- [ ] 加入追加要求和取消；服务端先停新授权，再取消真实执行者/子任务并记录确认。验证人工修改版本冲突、迟到写入拒绝、撤销接收端不再获得事件/链接。

**计划新增测试：** `smart_reporting/reporting_mcp/tests/test_harness_channel_roundtrip.py`（去重/权限/断线合同）与 `test_harness_office_live.py`（显式 opt-in 真实纵切片）；现有 `office-assistant-panel.test.ts` 定向覆盖展示。实际网络/原生会话证据单列，ASGI/模拟事件不能代替。

**验收：** 默认只有内置 executor 写入；用户始终可在真实 DSH 会话交流。外部消息 HTML/URL/postMessage 按可信边界处理；不暴露未授权正文、凭据或广播下载 bearer。

### P3：受控计算 MCP 与 facts 前的主执行 Harness（承接 Task42）

**复用：** 当前 `calculate_initial_metrics` 受控计算服务及其耐久 intent/unknown 行为。原 Task42 的必需技术合同已完整归入下节，无需旧 brief；先核 TaskSession/runner/watcher、HTTP MCP 请求上下文、鉴权与 generation 接缝的实际方法和逐文件归属，再写反例实施。

**候选修改面：** `smart_reporting/reporting_mcp/identity.py`/`tools.py`、`smart_reporting/reporting/codex_agent.py`、`workflow/execution.py`、`workflow/runtime/codex_inputs.py`、现有 runtime 消费者。`smart_reporting/management/report_initial_calculations.py` 作为既有服务复用，不改公式和 SQL 引擎。

- [ ] 先写新旧 capability 用途隔离、空参数工具、旧租约/错修订/输入篡改/取消/unknown 反例；再将原生 HTTP MCP 的 `reporting_calculate_selected_metrics` 接入 Task41 真实服务，不能接 SQL、DSN、原始数字、任意路径或模型自报 scope。
- [ ] executor 从 facts 前任务开始读取模板与已发布依据、提出分析需求；正式指标选择/口径仍按现有发布和登记规则形成可信输入。第一步可复用既有选择，但须明确尚未完成全部规划迁移。
- [ ] 主 harness 持有受限工具引用，服务端核已登记 selection/basis，计算后回读实际 CSV/回执并冻结 facts；需要新事实时明确补证。不能回填/修改已冻结的旧 generation 合同来伪造同 thread 恢复。
- [ ] 用真实 HTTP 客户端和隔离管理/测试业务 PG 验证服务、重复请求、唯一领取、unknown 不重查及取消；再在能力与预算允许的有界诊断下验证原生模型消费者。真实 StarRocks 留作专项，不以 PG 替代。

**计划新增测试：** `smart_reporting/reporting_mcp/tests/test_task_controlled_calculation.py`、`test_task_controlled_calculation_http.py`。原 `smart_reporting/tests/test_report_initial_calculations_postgres.py` 仅在受影响时选相关 case，不重做 Task41 已通过全组。

**验收：** 正式结果由真实服务生成，附件 999 不能覆盖登记事实 300；外部 controller 无同报告计算执行权；原生消费者、HTTP、数据库三层证据分别标记，不能以工具发现代替执行。

#### P3 接口、授权与真实服务消费者细则

1. **原生工具入口：** 复用 AgentOS/FastMCP Streamable HTTP；`reporting_calculate_selected_metrics` 严格空参数，服务端从已登记 basis/selection 派生计算集合并调用 `calculate_initial_metrics`。拒绝 SQL、任意指标/期间/数值/DSN/路径和模型自报 scope；不新造 transport、动态 callback RPC 或通用执行平台。
2. **短期 task capability：** 由服务端签发，与旧 workspace/DSH workflow token 用途和受众隔离；绑定 database/company/user、callerThread、reportRun、planningTask、reportRevision、workspace、冻结输入 SHA、完整 acceptance contract、当前 internalRun、lease owner/epoch、action 和 exp。旧 token 不能计算，计算 token 不能借用 workflow/lifecycle 权限。P6 的 direct executor 获得服务端核验的受限执行授权，不能自签 token 或冒充内置身份。
3. **每调用验证：** 读取真实 Task、租约、deadline/cancel、报告耐久修订、输入及 registry；执行前后核合同，最终提交仍须原子核租约/版本。不 claim 他人租约，不把 MCP 注入的空业务 RunContext 当正式上下文。HTTP 工具协程及 SQL 的取消需实际传播和对账，不能只取消 Codex 会话便声称计算停止。
4. **facts 前合同：** 由请求/已发布 basis/目录/指标/登记 selection/模板材料形成不可变初始合同，不伪造 facts 或回填旧 generation 清单/thread。可以先复用既有指标选择让原生 Codex 调已批准计算，但必须明确全部规划/选择迁移仍待；真实回执交给后续 facts 消费者。
5. **生命周期与完成：** 复用 runner、TaskSession、watcher 与现有回执。服务端独立核 receipt/CSV，模型 final 不是完成依据；重复请求恢复原结果，unknown 不重查，部分结果保留。内部诊断不能通过任意 HTTP 开关启用生产。
6. **工厂与秘密：** 仅允许服务端固定 HTTP URL、专用 bearer 配置与单工具 allowlist；kwargs/config/client overrides 不能绕过限制。短期 token 不入 prompt、manifest、回执、日志或普通 shell 环境，业务 DB 凭据不传给 harness。继续本地 Agno 工作区、sandbox=None/workspace-write。
7. **最小改动范围：** P3 不顺带改发布/下载/编辑、公式/SQL 引擎、Profile 或无关管理端。若发现确需新增签发步骤，在实施前核具体调用链与非阻断故障注入/静态守卫；不能通过扩大范围绕过原合同。
8. **验证分层：** 新旧 token 双向用途隔离、严格空参数、跨租户/任务/修订/输入/旧租约/过期/取消、unknown/CSV 篡改及秘密泄漏均有反例。真实 FastMCP HTTP 客户端连接实际认证路由，隔离管理/业务 PG 完成发布依据→服务→compiler/adapter→CSV/receipt，并验证恢复与取消；直接 handler/ASGI 模拟不算真 HTTP，PG 不算 StarRocks。
9. **诊断协调：** 若使用实施子 agent，它只编写 opt-in 测试；root 在独立审查后统一安排真实服务/模型/数据库探针，避免并发重复运行。未运行模型时明确“服务端计算通过、原生模型消费者未验证”，不换 provider/model、不静默放宽原次数硬帽，不将工具列表发现当任务完成。

### P4：五格式、模板、编辑与正式刷新闭环

**候选修改面：** `smart_reporting/reporting/contract.py`、`reporting_mcp/contracts.py`/`adapter.py`/`url_materializer.py`、`reporting/codex_generation.py`/`codex_delivery.py`、`delivery/templates.py`、`report_editor/generation_markdown.py`/`native_api.py`/`recalculation.py` 及对应现有测试。

- [ ] 统一新入口的五格式材料与独立模板登记；内部现有 20 参考+1 模板与外部 MCP 当前 4 份限制逐层对齐，配置/校验/解析预算一致。不是把 16 项/512 KiB 宣称为本地文件或 Agno 全局限制；保留大小/权限/定位校验及旧请求兼容；分别保留 Markdown 行号、Excel 单元格、幻灯片对象、PDF 页码和 Word 段落/表格位置，来源文件、模板、冻结结果、输出产物分开登记。
- [ ] 模板在详细分析计划前读取：Office 使用同格式副本；PDF 采用既有生成器或已验证 Office 转换；MD 可参考章节，不承诺 Office 布局。原件与未目标对象保持，不支持对象明确警告；中间 Office 文件不自动多交付。
- [ ] 按格式复用可信生成器/编辑器，不强制先转 MD、不强制每次工具都调用模型；补剩余标准算子/模板及编辑器改图消费者，禁止把 CodeMode 藏进 MCP 实现。
- [ ] 接完 MD 图片/空 MD 和 generation 正式 DB 刷新；“分析当前修订”先保存并冻结，重分析/再生成创建新修订；人工数值改写使原绑定失效，恢复正式数值须数据库重算。
- [ ] 每格式验证生成→独立回读→编辑→新修订→进程恢复→授权下载，冻结原件不变；任何验收/溯源失败保留身份可信目标并返回具体原因，错误目标不借另一格式冒充。

**测试入口：** `smart_reporting/reporting/tests/test_codex_generation_delivery.py`、`test_report_templates.py`、`test_http_publication_lineage.py`、`test_publication_nonblocking.py` 与各 generation editor 的既有定向测试；计划新增 `smart_reporting/reporting/tests/test_harness_five_format_lifecycle.py` 汇集五种目标的 opt-in 真实链证据。不得将替身生命周期结果标成真实模型全链。

### P5：取消、恢复、预算与本地权限的全链验收

**候选修改面：** `smart_reporting/task_execution/session.py`/`execution.py`/`repository_impl.py`、`reporting/workflow/execution.py`、`reporting/codex_agent.py`/`codex_local_environment.py`、已有事件/回执消费路径；发现缺口按最小故障修复，不加私有 supervisor/网关。

- [ ] 对外部 controller、内置 executor、原生子 agent、HTTP 计算、SQL、脚本和 Office 提交分别注入取消/超时/丢回复/重启；先封新动作，再对账实际停止情况，unknown 不伪报 cancelled 或自动重放。
- [ ] 核父子身份、输入/模板/修订/工作区绑定和恢复幂等；已完成计算/签发不得因线程恢复重复执行。防循环委派与双重写入；完成回执由服务端核验，不接受模型自报完成。
- [ ] 明确根预算及子额度、实际可计量范围与硬上限；外部自有会话费用和内置受管用量分别记录，unknown 不当 0。原次数硬帽无法满足时记录能力缺口并保持生产禁用，不能自行换契约。
- [ ] 用合成哨兵验证实际运行账号/目录权限、符号链接、跨任务读取和正式目录写入边界；不读取真实秘密，不恢复 DockerSandbox，不把环境净化当隔离证明。

**计划新增测试：** `smart_reporting/reporting_mcp/tests/test_harness_lifecycle_faults.py`；现有 Task 租约/取消测试和 Codex 本地环境/原生取消探针按受影响路径补反例。所有真实有界探针保留原始 exit、run/thread/进程身份、回执和清理证据。

### P6：显式直接接管与第二外部 Harness

**修改面：** P1 合同/鉴权与 P2 会话适配器，复用同一共享工具、Task 和回执；按 P0 实证接入第二客户端，不另建执行服务。

- [ ] 先用替身确认 direct 只创建选定 executor，内置 Codex run 数为 0；随后在选定外部 harness 的真实原生会话验证取数→分析→生成→修订→恢复→下载。
- [ ] 默认 delegated 全部保持；仅请求方显式选择且服务端授权/能力满足才进入 direct。模式切换创建关联新任务，旧任务取消和文件对账前不能授予冲突输出权。
- [ ] 第二外部 harness 默认只获其任务/复核范围；同频道不等于共享所有附件、历史或下载权限。无依赖只读可并行，同文档写按租约和版本串行。

**计划新增测试：** `smart_reporting/reporting_mcp/tests/test_harness_direct_execution.py`；复用 P2 的双向与 P5 的故障矩阵，新增 direct 特有反例，不复制整套测试。

**验收：** 单执行者可审计；DSH 会话身份不冒充服务端授权；两模式没有隐藏的旧 CodeMode 执行依赖，外部失败不自动回退内置。

### P7：退役 CodeMode、部署与最终组合验收

**候选修改面：** `smart_reporting/reporting/code_mode.py`、`smart_reporting/runtime/application.py`、报告/分析脚本/标准图表/工作簿汇编/编辑器改图重绘的真实消费者、专用 kernel 管理及仅为它存在的依赖。先扫描实际引用，不能按名称整段删除共享分析函数。

- [ ] 先列全消费者与替代证据，停止创建旧链任务，处理在途旧任务；旧 kernel 不伪装成 Codex thread 恢复。旧链只保必要兼容/修复，不再增加专属消费者。
- [ ] 替代链通过后移除旧 free-form 协议、运行时与专用 kernel；通用依赖仅在无其他使用时移除。原 free-form 多调用顺序、失败后停止/提交后停止契约在旧链退役前继续回归，不能提前改坏以迫使迁移。
- [ ] 保留旧 document/word、历史文件/回执/下载兼容；真实隔离 StarRocks 验证受控权限、口径、参数与指标，绝不读业务 `.env` 或用生产库替代。资源未具备时如实保留未验收。
- [ ] 开发/部署均同锁安装，确认只有 Agno 3.1.12；仅对最终受影响路径做一次必要组合回归及实际部署验证。技术发布条件通过前不启用生产，不将默认 delegated 当启用开关。

**验收：** 静态引用扫描确认执行路径无 CodeMode；真实新任务使用选定唯一 harness；五格式/模板/双向会话/取消恢复与非阻断下载具备分层证据。业务签认保持 not_performed，不声称原六阶段业务验收完成。

## 5. 风险与验收的追踪关系

以下是架构风险和待验证要求，不是已证实可利用漏洞清单。已核源码边界：`reporting_mcp/identity.py` 的原 token 仅覆盖现有 workflow/thread 用途；`report_editor/agent_event_streams.py` 是容量 128 的内存列表，不能单独证明跨进程重放；`reporting/codex_local_environment.py` 明确不提供宿主文件读取隔离；`runtime/application.py` 的 `interfaces=[]` 不能当 A2A 已接通。未来接入须以真实探针补证，不把现有窄用途实现缺少新能力误报成当前漏洞。

| 风险/目标 | 对应任务 | 独立于模型声明的证据 |
|---|---|---|
| H-01 权限放大 | P1/P3/P6 | token 用途隔离、跨租户/任务/修订/旧租约反例与真实服务拒用回执 |
| H-02 重复执行/双主 | P1/P3/P5/P6 | 幂等记录、唯一领取、原子版本提交、迟到 worker 故障注入 |
| H-03 本地绕过 | P0/P5 | 实际运行身份和合成哨兵权限测试，非环境变量推断 |
| H-04 数据扩散 | P2/P6 | 逐接收端过滤、撤销重连、历史/附件/链接授权反例 |
| H-05 消息冒权 | P2 | 来源角色、一次性回答、回声去重及恶意内容测试 |
| M-01 取消/恢复 | P2/P3/P5 | 真实执行/SQL/进程状态与持久回执，不只 HTTP 200 |
| M-02 事件丢失 | P2/P5 | 跨进程 cursor/快照对账、重放不重复副作用 |
| M-03 预算/循环 | P1/P5/P6 | 根子用量与硬帽能力实证、循环委派拒绝、unknown 诚实展示 |
| 数值正确性 | P3/P4/P7 | 固定样例独立预期、已发布公式/口径、数据来源与结果比对；SHA 仅证身份 |
| 模板与五格式 | P4 | 独立 reader/渲染结果、目标与非目标对象对照、原件 SHA、实际授权下载 |
| CodeMode 退出 | P7 | 消费者清单、引用扫描、真实新任务与历史只读兼容证据 |

## 6. 暂缓与范围外

完整 Profile 移除、全量实时目录核对移除、通用流程配置平台、完整 OCR、任意 Office 对象无损处理继续暂缓。数据源确认仍绑定组织身份、已发布目录版本、允许表范围及现有结构核对；不以 harness 接管为由取消这些约束。当前任务不升级其他业务依赖、不重写指标公式、不扩大 Plotly 存量代码。

## 7. 定向验证与交接规则

- 所有变更先保存当前基线，再写反例、确认预期失败、做最小实现、运行新增与直接受影响用例；每项记录执行源码、命令/exit、JUnit、原始失败和独立审查。已有通过证据不重复制造；skip、模拟、离线重判、服务重建、真实进程重启与真实 provider 各自标记。
- 每项使用明确的测试文件/nodeid，不执行无范围 `pytest`。新文件命名为本计划拟新增，不表示已经存在；选定文件后例如 `uv run --locked pytest smart_reporting/reporting_mcp/tests/test_harness_execution_contract.py -q`，只在实施该项时运行。
- 修改签发/导出时，保持 AGENTS.md 所列全部非阻断契约；新步骤在 `test_http_publication_lineage.py` 故障注入登记，新函数在 `test_publication_nonblocking.py` 的 `_SIGNING_CHAIN` 登记。实际身份不可核验与验收失败必须分开。
- 原 Task41 的 97、Task39 的 262、Task40 的 5 项冻结证据保持，不更改旧审查/归档来匹配新结论。Task41 的测试 helper 超时清理与历史依赖告警保留到受影响修复时处理，不能写成已解决。
- 新实施任务使用 P0–P7 与对应旧 Task 编号交叉引用；不新造“已完成”的运行记录。每个完成声明须列证据范围、残余缺口和业务未签认状态。

**当前下一步：** 用户恢复实施后先执行 P0，再按 P1/P2 完成默认间接模式的最小双向闭环；原 Task42 要求已合并进 P3。准备提交这份计划不恢复 paused 目标，也不启用生产或触发模型、数据库和部署。
