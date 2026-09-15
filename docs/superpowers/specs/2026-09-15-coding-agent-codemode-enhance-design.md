# Reporting Coding Agent 增强：知识库、LSP 与交互式工具型大脑设计

## 目标

在 `feat/matplotlib-code-mode-host` 的宿主机 Workspace + CodeMode 基线上，为 Reporting Coding Agent 补齐编程能力三要素：项目知识库、语言服务器（LSP）静态信息、以及让大脑在签发前自主查询这些信息的交互式工具调用。外层 Code Agent 从"单轮直签"升级为"多轮只读探索 + 单次签发"；服务端签发门禁（shape → compile+authorizedPaths → patch → hash CAS）完全不变；CodeMode Kernel 按任务隔离、任务结束关闭的现有语义不变。

## 已确认约束

- 大脑形态选定为**交互式工具型大脑**：code agent 在签发前可多轮调用只读知识/LSP 工具，再一次性 `submit_python_source`。单次提交契约（`wrapped_source` calls>1 防护、`stop_after_tool_call=True`）保留，相关既有测试按新契约更新。
- 知识库与 LSP 工具同时注入两层：外层 code agent（按当前任务 workspace 显式绑定）与 CodeMode Kernel 内（resolver 按 kernel session 解析 workspace）。
- 离线环境：不依赖外部 SaaS 向量库、不做 embedding 检索。知识库使用 SQLite FTS5（stdlib 自带，trigram 分词支持中英文子串，bm25 打分）。LSP 使用 `python-lsp-server`（纯 Python，pip 可装；pyright 需 node 运行时，放弃）。
- LSP 能力全部只读；`lsp_format`、`lsp_apply_edit`、`lsp_rename`、`lsp_workspace_symbols` 不开放。文件修改只走 `submit_python_source` → 服务端 patch 门禁。
- LSP root 与知识库动态记录都必须绑定当前任务 Workspace，绝不回退或访问宿主机其他目录；解析不到即报错。
- 不采用 Agno `Knowledge`/`KnowledgeTools`：其检索依赖 embedder，本环境无离线 embedder；自建部分仅是薄 Toolkit（继承 agno `Toolkit` 基类）+ FTS5 索引器，符合"agno 框架内支持优先"（工具注册、CodeMode bridge、Toolkit 语义全部复用 agno）。
- 应用日志使用 Loguru；语义业务校验只软告警；禁止重复完整测试。
- 新增依赖仅 `python-lsp-server`。

## 范围

本次包含：

- `ReportingKnowledgeToolkit`：FTS5 索引、静态知识文档、动态修复知识、`search_knowledge` 只读工具；
- `ReportingLspToolkit`：pylsp stdio 薄客户端、6 个只读工具、按 workspace root 的进程管理；
- code agent 装配改造：`_configure` 多轮工具、`tool_choice="auto"`、`tool_call_limit` 1→6、instructions 追加；
- CodeMode Kernel 注入双 Toolkit（session→workspace resolver 注册表）；
- 动态知识 recorder 挂接 repair 成功与修复耗尽点；
- 新增定点测试三组及受影响既有测试的契约更新。

本次不包含：

- 交互式工具的流式 UI 或 AgentOS 展示改动；
- Workspace 目录结构、签发/patch/hash 门禁、修复循环次数（analysis 2 次 / visualization 3 次）的任何变更；
- 语义 embedding、跨会话动态知识共享、外部向量库；
- LSP 写能力、workspace 级符号搜索；
- 修复耗尽后的降级策略调整（visualization 仍按零图降级）。

## 方案选择

大脑接入方式在"确定性管线注入（服务端检索进 prompt + LSP 短路）"与"交互式工具型大脑"之间选择，确认为后者：模型在签发前的多轮里自主决定查什么、查几次，签发行为本身仍受单次提交与 stop_after_tool_call 约束。风险是既有单轮契约测试需要更新，已在范围中列明。

知识检索在 agno `KnowledgeTools` 与自建薄 Toolkit 之间，因离线 embedder 不可用而选择自建：索引器 + 单工具 Toolkit，注册与 bridge 语义完全走 agno `Toolkit`。

## 组件设计

### 1. ReportingKnowledgeToolkit

**存储**：`<REPORTING_HOST_WORKSPACE_ROOT>/knowledge/index.sqlite3`，FTS5 trigram 表。进程内单例，异步锁串行写入。

**静态知识**：包内 `smart_reporting/reporting/knowledge_docs/*.md`（首版四篇：`matplotlib.md`、`data-contract.md`、`codemode.md`、`common-errors.md`），按内容哈希增量重索引；markdown 按标题分块 + 40 行滑窗（8 行重叠），记录精确 `startLine`/`endLine`。

**动态知识**：修复成功记录 `{kind:"repair", workspaceKey, taskId, scriptSha256, errorCode, 有界 diagnostic, 最终源码摘要(≤64KB)}`；修复耗尽记录失败样本 `outcome=failed`。写入点：`ReportingCodeGenerationRunner.repair` 成功返回处与两个 workflow 的修复耗尽处；recorder 为可选注入依赖（None = 不记录）。动态知识检索**仅限当前 workspace_key**，静态全局共享。

**工具契约**（单工具，模型与 Kernel 均可见）：

```json
search_knowledge(query, kind="all"|"static"|"dynamic", limit<=5)
→ {"ok":true,"matches":[
    {"source":"static","path":"knowledge_docs/matplotlib.md","startLine":42,"endLine":68,"snippet":"≤1200B","score":0.91},
    {"source":"dynamic","kind":"repair","errorCode":"…","scriptSha256":"…","snippet":"…"}],
   "truncated":false}
```

只返回检索片段，不整篇注入；`truncated` 标志 snippet 截断。

### 2. ReportingLspToolkit

**引擎**：`python -m pylsp`（默认 stdio 模式，Content-Length framing 已验证）。每个 session workspace root 一个子进程，懒启动，idle TTL 10 分钟自动关闭；进程死亡下次调用重启；LSP 不可用时工具返回 `{"ok":false,"code":"report_lsp_unavailable"}` 软降级，不阻塞签发。`close_execution_resources` 统一回收。

**薄客户端**：asyncio 子进程 + JSON-RPC framing；`initialize`（只开 hover/definition/references/documentSymbol/diagnostics 能力）→ `initialized` → 按需 `didOpen`/`didClose`；`publishDiagnostics` 通知缓存，按 id 关联请求响应。

**只读工具面**（root 绑当前任务 workspace；入参只收 workspace 相对路径，服务端拼 root；绝对路径与 `..` 拒绝）：

| 工具 | 用途 |
| --- | --- |
| `lsp_check_draft(source)` | 签发前自查：draft 以目标 script_path didOpen 进 LSP 内存态，返回 error/warning 分组诊断后 didClose，不落盘 |
| `lsp_diagnostics(path)` | 已落盘脚本的一次性诊断 |
| `lsp_hover(path, line, character)` | 符号类型与 docstring |
| `lsp_definition(path, line, character)` | 跳定义，只读返回片段 |
| `lsp_references(path, line, character)` | 引用列表 ≤10 条 |
| `lsp_document_symbols(path)` | 文档符号树 |

**返回有界**：hover ≤800B、snippet ≤400B、references ≤10、diagnostics ≤50 条 + truncated 标志；错误以工具结果返回不抛异常，码风格与 ReportingError 对齐。

**不做服务端短路**：draft 的 error 不自动拦截签发；模型自主决策，服务端门禁仍只管 shape/compile/patch/hash。

### 3. 大脑接线

- `create_reporting_code_agent`（agent.py）新增可选 `knowledge_toolkit`/`lsp_toolkit`（None 不挂，向后兼容）。
- `_configure`（code_generation.py）：`tools=[knowledge, lsp, submit]`、`tool_choice="auto"`、`tool_call_limit` 1→6；单次提交契约不动。
- `ReportingCodeGenerationRunner.generate/repair` 支持按当前任务 workspace 构造新 Toolkit 实例（随轮丢弃）；workflow 侧在 analysis.py 的 `workspace_for` 解析处传入。
- Kernel 侧：`runtime/execution.py` 的 `CodeMode(tools=[…], tools=…)` 注入 resolver 实例；`ReportingCodeModeRuntime` 新增 `{kernel_session_id → workspace}` 注册表，`execute_script` 时登记、`shutdown` 时清理。
- instructions 追加：优先查知识库规范、不确定 API 先 `lsp_hover`、签发前必须 `lsp_check_draft`、不访问 workspace 外绝对路径；KnowledgeToolkit 自带检索引导 `add_instructions`。

### 4. Kernel 现场回收（修复盲修对策）

执行失败后 Kernel 在任务结束前仍存活，且 CodeMode 原生提供 `avariables(session_id)`。在 `execute_script` 失败与 workflow 捕获之间新增 best-effort `capture_state`：

- 变量摘要：`avariables`，有界 2KB；
- 执行开始后新增/修改的 workspace 文件列表（≤10 条）；
- 以 `kernelState` 并入 repair diagnostic；Kernel 已死则降级 `kernelState:"unavailable"`。

零新架构，纯用现有 CodeMode API，不改变修复循环结构。

### 5. 修复轮 diagnostic 预置静态发现

服务端对失败脚本做一次性 `lsp_diagnostics`，结果以 `staticFindings` 并入 repair diagnostic。模型省一轮工具调用预算，未定义名/坏导入类静态错一轮修掉。这不是签发短路——门禁不变，只是喂给模型的输入更富。

### 6. 全局脱敏错误模式表

repair 成功时额外写一行全局模式记录：`exceptionType + 脱敏 message 头`（剥离引号串、路径、业务词的确定性脱敏）+ 修复次数，不含源码与路径。`search_knowledge` 结果以 `source:"pattern"` 合并（如"此错误模式历史出现 4 次，均在 1 轮内修复"）。业务源码仍限 workspace_key，模式先验全局共享。

### 7. 动态知识 recorder

repair 成功后与修复耗尽后写入动态知识（含最终源码/失败 diagnostic，有界）；recorder 可选注入，测试以假实现替换。检索按 workspace_key 过滤。

### 8. 其他

- `tool_call_limit` 定为 8（修复轮含 `kernelState` 调查预算）。
- FTS5 查询对 MATCH 特殊字符转义为 trigram 短语，避免查询语法报错。
- instructions 明确：修复轮与生成轮签发前都必须 `lsp_check_draft`。

## 测试计划

新增独立文件，聚焦运行，禁止重复完整测试：

- `test_reporting_knowledge_toolkit.py`：结果带 path/startLine/endLine/snippet/score；snippet 有界（不返回整篇）；动态知识仅限当前 workspaceKey；索引增量重建；并发读写安全。
- `test_reporting_lsp_toolkit.py`：root 不越界（绝对路径/`..` 拒绝）；`lsp_check_draft` 不落盘（执行后 workspace 无该文件）；诊断/引用有界；进程死亡后重启软降级；TTL 回收。
- Kernel 隔离：两 kernel session 变量不共享（复用现有 CodeMode 测试模式），resolver 路由正确、解析失败报错。
- 生命周期：kernel 异常仍 shutdown；resolver 注册表清理；LSP 进程随 `close_execution_resources` 回收。
- Kernel 现场回收：失败后 `kernelState` 有界并入 diagnostic；Kernel 已死降级 unavailable；不阻塞修复流程。
- 静态发现：repair diagnostic 含 `staticFindings`；LSP 不可用时省略该字段（软降级）。
- 模式脱敏：全局模式记录不含源码/路径/业务词；确定性脱敏可单测。
- 契约更新：多轮工具探索 + 单次 submit 的既有对齐测试（thinking budget、multiple_sources 防护、tool_choice、tool_call_limit=8）按新契约更新。

## 落地顺序

1. `ReportingKnowledgeToolkit` + FTS5 索引 + 静态文档 + 测试；
2. `ReportingLspToolkit` + pylsp 客户端 + 测试；
3. Kernel 现场回收（`capture_state`）+ 修复轮 `staticFindings` 预置 + 测试；
4. `_configure`/runner 接线 + instructions + 受影响测试更新；
5. CodeMode 注入 resolver 双 Toolkit + 注册表 + 测试；
6. 动态知识 recorder 与全局模式表挂接 + 测试。

每步独立可验证；1、2 无行为耦合可并行。
