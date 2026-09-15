# Reporting Code Agent：Responses API 交互式编程设计

## 目标

将 Reporting Code Agent 重构为基于 OpenAI Responses API 的交互式编程 Agent。主模型在一次任务中持续调用知识库、LSP 和 CodeMode，直接在当前报表会话的正式 Workspace 中编写、执行和修复 Python 脚本；脚本只有在当前内容已成功执行并通过服务端校验后才能签发给固定 Workflow。

目标形态：

```text
Reporting Code Agent
  ├── 大脑：Responses API 主模型 + reasoning/thinking
  ├── 知识库：项目文档、规范、历史成功修复、API 契约
  ├── LSP：符号、定义、引用、诊断、类型信息
  └── CodeMode：Python/Shell 交互执行环境
        └── 会话正式 Workspace
              ├── 写入目标脚本
              ├── 执行并观察结果
              ├── 原地修复
              └── 签发当前成功版本
```

## 已确认约束

- 使用 Agno `OpenAIResponses` 工具循环和 Responses API 混合工具协议：结构化操作使用 JSON function tool，大文本源码与执行 cell 使用 free-form custom tool。
- Agent 可以多轮调用知识库、LSP、Python 和 Shell，直到脚本成功签发或达到工具调用上限。
- CodeMode 直接读写当前报表会话的正式 Workspace，不创建临时 Workspace，不复制数据。
- 交互过程中允许正式 Workspace 暂时存在语法错误脚本、运行失败脚本和中间产物；固定 Workflow 只信任最终签发回执。
- 每个 coding task 使用独立 CodeMode Kernel；同一任务内的生成、执行和修复共享 Kernel，任务结束必须关闭。
- 不兼容旧 `submit_python_source(source)`、单轮直签、patch-before-write 和相关测试契约。
- 不设计中断恢复、草稿恢复或旧 durable state 兼容。进程或任务中断后由上层重新开始该 coding task。
- 宿主机 CodeMode 继承 API 进程权限，不提供恶意代码隔离承诺。本方案面向受信部署环境。
- 语义业务校验继续只产生软告警；路径、源码形状、编译、执行和文件身份错误属于技术失败。
- 应用日志使用 Loguru；验证只运行定点测试，不重复运行完整测试集。
- 优先使用 Agno 原生 Agent、Toolkit、CodeMode 和工具循环，不重新实现模型循环或 Python Kernel。

## 非目标

- 不提供容器、bubblewrap、权限降级或文件系统沙箱。
- 不保证交互期间 Workspace 始终处于可发布状态。
- 不支持跨进程恢复 CodeMode Kernel 或未签发草稿。
- 不实现流式 UI、人工确认或 AgentOS 前端展示。
- 首版 Coding Agent 使用非流式 Responses 调用，不实现 `custom_tool_call_input.delta` 增量解析。
- 不引入 embedding、外部向量库或外部知识 SaaS。
- 不开放 LSP rename、format、applyEdit 或 workspace symbols。

## 核心方案

### 1. 单一 Responses API 混合工具循环

Code Agent 使用 `ReportingCodeOpenAIResponses`，它是 Agno `OpenAIResponses` 的薄协议适配。一次 `Agent.arun` 内仍由 Agno 维护 Responses API 多轮消息、工具执行和停止条件，模型可以按需查询、写入、执行、诊断和修复；适配层不自行实现 Agent 工具循环。

Agent 工具表固定为：

```text
search_knowledge
lsp_diagnostics
lsp_hover
lsp_definition
lsp_references
lsp_document_symbols
read_script
write_script
execute_code
restart_code_mode
run_script
submit_script
```

工具协议按载荷类型固定划分：

- `write_script`、`execute_code` 声明为 `format: {type: "text"}` 的 free-form custom tool，源码或 Python/Shell cell 直接放在 `custom_tool_call.input`，省去 `function_call.arguments` 内层 JSON 对象及其字符串转义；HTTP 请求外层仍由 OpenAI SDK 正常编码；
- 其余工具声明为带 JSON Schema 的普通 function tool；
- custom 与 function 可以出现在同一请求工具表和同一个多轮 run 中，但 `parallel_tool_calls=False` 禁止模型并行发出多个工具调用；
- 不引入 Lark grammar、JavaScript runtime 或 nested-tool broker。这里采用 Codex 的原始文本载荷优势，不复制其 CodeMode 编排运行时。

- `tool_choice="auto"`。
- `parallel_tool_calls=False`，避免写脚本、执行和签发并行发生。
- `tool_call_limit=20`，所有工具调用统一计数。
- 每个 coding task 创建独立 Agent、Toolkit 和 Function 实例，不跨任务复用带 task binding 或可变停止状态的对象。
- `submit_script` 校验失败时返回结构化诊断并继续当前工具循环；沿用现有 Function post-hook 模式，只在 task 独享的 Function 上、且回执 `ok=true` 时将本次调用标记为 `stop_after_tool_call=True`。
- Agent 输出普通文本或达到调用上限但没有成功签发，统一返回 `report_code_generation_no_submission`。

保留并重构现有 `ReportingCodeOpenAIResponses`：删除“custom 工具必须唯一”、单轮源码直签和 custom 请求后立即结束的限制，将其收敛为通用混合协议适配器。适配器负责：

1. 将内部 `write_script(source)` 和 `execute_code(code)` Function 定义转换为 Responses custom tool 定义；
2. 将 `custom_tool_call.input` 转换为 Agno 工具执行器可消费的内部单字符串参数调用，并将 provider item id、call id 和 custom 类型标记保存在对应消息元数据中；
3. 根据消息自带的类型标记，将有界工具结果序列化为 `custom_tool_call_output`；普通 Function 结果仍序列化为 `function_call_output`，历史重放和 `previous_response_id` 两种路径使用同一身份映射；
4. 校验未知 custom 工具、空 input、重复 call identity 和协议类型错配，返回稳定技术错误；
5. 保留 Agno 原有工具 hook、`tool_call_limit`、RunContext、指标和停止语义。

每个 task 独享模型适配器实例；工具类型以消息元数据为权威，不得通过进程级可变全局、跨任务 `ContextVar` 或最近一次请求的工具表反推。reasoning/thinking 参数继续由现有模型策略决定，不再为源码提交单独切换成关闭 thinking 的第二阶段模型请求。

### 2. 任务绑定

新增不可变的 `ReportingCodingTaskContext`，由固定 Workflow 创建，不接受模型提供身份字段：

```text
task_id
task_kind                    analysis | visualization
code_mode_session_id
workspace_key
workspace_root
script_path
authorized_read_paths
authorized_write_paths
declared_output_paths
max_source_bytes
```

工具通过当前 `RunContext` 解析 `ReportingCodingTaskContext`。解析不到、任务身份不一致或 workspace 已释放时直接返回稳定技术错误，不回退到全局目录或其他 Workspace。

同一 `script_path` 同时只能有一个活动 coding task。现有 task coordinator lease 是跨进程并发权威，进程内 task binding registry 负责工具路由和快速防重；本次不新增草稿恢复或第二套分布式锁。

### 3. ReportingCodeModeToolkit

`ReportingCodeModeToolkit` 是 Agno `Toolkit` 的薄适配，内部复用现有共享 `ReportingCodeModeRuntime` 和 Agno `CodeMode`，不自行实现 Kernel。

#### `read_script()`

从绑定的固定 `script_path` 读取当前正式脚本，不接受模型提供路径。文件不存在时返回稳定的空状态；文件存在时校验普通文件、非符号链接、UTF-8 和大小限制，并返回源码、SHA-256 和字节数。

#### `write_script(<free-form source>)`

custom input 就是完整源码。工具将其写入绑定的固定 `script_path`，不接受模型提供路径，也不要求 JSON、Markdown 代码围栏或 patch 包装。写入阶段只校验非空文本、UTF-8 字节数、物理行约束和目标路径属性，允许正式 Workspace 暂时保存语法错误或运行失败的中间稿。

使用 Workspace 现有的原子文件替换能力，避免并发读取到半写文件。原子替换使用的同目录临时文件只是文件写入实现细节，不是临时 Workspace，也不承载可恢复草稿。工具返回逻辑路径、SHA-256 和字节数；源码身份变化后，先前的成功执行回执立即失效。

#### `execute_code(<free-form code>)`

custom input 就是待执行的 Python cell 或以 `%%bash` 开头的 Shell cell。在当前任务 Kernel 中执行该 cell，用于读取数据、试验 API、执行临时计算和检查中间结果。首次调用前由 runtime 将 cwd 设置为当前正式 Workspace root；可视化任务同时设置 `MPLBACKEND=Agg`。

`execute_code` 仍拥有宿主机权限，因此可以直接修改正式 Workspace；模型应优先使用 `write_script` 更新目标脚本，以避免在 Python/Shell cell 中再次嵌套完整源码。无论通过哪个入口修改，`submit_script` 都以当前文件和最近成功执行回执的身份比较为准。

返回 stdout、stderr、traceback、图片和状态的有界结果。文本诊断合计不超过 8KB，变量类型摘要不超过 2KB，图片沿用 CodeMode 实例级数量和字节上限。工具结果不得包含宿主机 Workspace 绝对路径。

#### `restart_code_mode()`

关闭当前 Kernel 并以相同 task binding 启动空 Kernel。重启只清除 Python 变量和进程状态，不回滚已经写入 Workspace 的文件。

#### `run_script()`

服务端从绑定的固定 `script_path` 读取当前脚本，不接受模型提供其他路径，然后执行：

1. 普通文件、非符号链接、UTF-8、大小和物理行约束；
2. `ast.parse`、`compile` 和 `authorizedPaths` 静态校验；
3. 计算执行前 `sourceSha256`，并删除 `declared_output_paths` 中属于本任务的旧输出，避免旧产物被误认为本轮结果；
4. 通过当前 task CodeMode 的 `%%bash` cell 启动固定 Python 解释器子进程，在正式 Workspace root 中运行脚本；解释器、脚本路径、cwd 和环境变量均由服务端构造，不接受模型参数；
5. 执行后重新读取脚本，若 SHA-256 变化则拒绝本次结果；
6. 校验任务声明的输出文件，生成按逻辑路径排序的 `FileIdentity` 清单；
7. 仅当子进程退出码为 0、脚本未自修改且声明输出完整时，记录内存态 `ExecutionReceipt`。

正式脚本必须在干净 Python 子进程中运行，不得直接 `exec` 到交互 Kernel 的全局命名空间。这样探索 cell、先前失败运行留下的变量和 import 不会成为脚本成功执行的隐式前置条件；CodeMode Kernel 仍负责同一任务内的交互状态和 Shell cell 生命周期。

`ExecutionReceipt` 至少包含本次运行 ID、源码 `FileIdentity` 和声明输出的 `FileIdentity[]`。失败运行可以在正式 Workspace 留下部分输出；下一次 `run_script` 会先清理声明输出后重新执行。

执行失败返回有界 stdout、stderr、traceback、LSP 静态发现和变量类型摘要，Agent 在同一 Responses 工具循环中继续修改。`run_script` 不签发文件，也不终止 Agent。

### 4. 直接写正式 Workspace

模型优先通过 `write_script` 创建和修改绑定的目标脚本，也可以在 `execute_code` 的 Python 或 Shell 中直接修改正式 Workspace。数据集、facts、既有脚本和运行产物均使用当前会话 Workspace 的真实相对路径，不再做上传、下载或临时目录映射。

这是运行便利性边界，不是安全边界：

- cwd 和 instructions 引导模型只访问当前 Workspace；
- `run_script` 和 `submit_script` 只接受服务端绑定的目标脚本；
- LSP 工具只接受 Workspace 相对路径；
- 但原生 Python/Shell 继承宿主机权限，主动构造绝对路径仍可能访问 Workspace 外文件。

中间脚本、产物和执行状态不进入 durable state。只有 `submit_script` 返回的源码身份、输出身份和执行回执可以被后续 Workflow 使用。

### 5. 最终签发

`submit_script()` 不接收源码和路径，目标完全来自 `ReportingCodingTaskContext`。服务端执行：

1. 重新读取当前脚本并计算 SHA-256；
2. 要求当前源码 `FileIdentity` 等于最近一次成功运行的 `ExecutionReceipt.source_file`；
3. 重新读取所有声明输出，要求其有序 `FileIdentity` 清单等于 `ExecutionReceipt.output_files`；
4. 重复普通文件、大小、shape、compile 和 `authorizedPaths` 校验；
5. 返回 `CodeGenerationResult(script_file, execution_receipt)`；
6. 仅对 `ok=true` 的回执触发 Agno `stop_after_tool_call`。

如果模型在最后一次成功执行后再次修改脚本，签发返回：

```json
{
  "ok": false,
  "code": "report_code_submission_not_executed",
  "message": "当前脚本内容尚未成功执行。"
}
```

Agent 必须重新调用 `run_script`，成功后才能再次签发。声明输出在成功运行后发生缺失、替换或内容变化时，同样返回可恢复错误并要求重新运行。成功签发后 runner 关闭 task Kernel，并再次核对源码及输出清单；关闭期间任何身份变化都按文件身份冲突失败。

### 6. Workflow 重构

`ReportingCodeGenerationRunner.generate` 和 `repair` 合并为一个交互式入口：

```text
run(task_context, task_facts, diagnostic=None)
  -> CodeGenerationResult(script_file, execution_receipt)
```

首次生成与错误修复使用同一条执行路径。区别只来自输入中是否包含既有脚本身份和 diagnostic，不再维护两套 Agent 装配逻辑。

`run_script` 的最后一次成功子进程执行即本轮权威脚本执行。Workflow 收到签发结果后不重复执行脚本，只读取并核对签发回执中的输出身份，然后继续做领域验收：

- analysis：读取并校验证据 JSON，然后完成分析项；
- visualization：校验图表文件、执行视觉审查并提交图表；
- 领域验收失败时，Workflow 用结构化 diagnostic 再启动一次交互式 coding run；
- 达到现有业务修复上限后，analysis 放弃补证，visualization 按零图降级。

本次允许调整固定 Workflow 内部回调和步骤实现，但不改变最终 accepted/degraded 业务结果。

## 知识库

### 存储与内容

使用 `<REPORTING_HOST_WORKSPACE_ROOT>/knowledge/index.sqlite3`：

- 静态知识来自 `smart_reporting/reporting/knowledge_docs/*.md`；
- 动态知识只记录正式领域验收成功的修复；
- 动态记录包含 `workspaceKey`、任务类型、错误码、最终源码 SHA-256 和有界摘要；
- 动态检索强制过滤当前 `workspace_key`；
- 首版不做跨 Workspace 全局错误模式聚合。

SQLite 使用 WAL、busy timeout 和短事务。进程内异步锁只负责减少本进程写竞争，数据库事务负责跨连接一致性。

### 检索

- 查询长度达到 3 个 Unicode 字符时使用 FTS5 trigram 和 `bm25` 排序；
- 1 至 2 字符查询使用转义后的 `LIKE` 子串回退；
- `MATCH` 特殊字符作为 trigram 短语处理；
- 最多返回 5 条，每条 snippet 不超过 1200 bytes；
- 对外 score 统一为“越大越相关”的归一化值，不直接暴露 SQLite 负向 bm25 值。

## LSP

使用 `python-lsp-server` stdio。`ReportingLspProcessManager` 由 `ExecutionContext` 持有，按正式 Workspace root 复用进程，负责 JSON-RPC id、请求 Future、diagnostic version、死亡重启、10 分钟 idle TTL 和全局关闭。

Toolkit 本身无进程所有权，只按任务绑定解析 manager。所有输入路径通过现有 Workspace path mapper 校验绝对路径、`..`、符号链接和普通文件属性。

开放：

- `lsp_diagnostics(path=None)`：默认检查绑定脚本；
- `lsp_hover(path, line, character)`；
- `lsp_definition(path, line, character)`；
- `lsp_references(path, line, character)`；
- `lsp_document_symbols(path)`。

不再提供 `lsp_check_draft(source)`，因为草稿已经真实写入 Workspace。`lsp_diagnostics()` 直接对当前文件 didOpen/didChange，并等待匹配 document version 的 `publishDiagnostics` 后返回。

definition 和 references 返回的 URI 必须 canonicalize 后仍位于当前 Workspace root；外部 URI 只返回 `outsideWorkspace=true`，不得读取或返回宿主机外部源码片段。

LSP 不可用时返回 `report_lsp_unavailable` 软降级，不阻止 Agent 使用 CodeMode 和 Python compile 完成任务。

## 资源生命周期

- CodeMode：每个 coding task 一个 session，成功、失败、取消或异常都在 runner `finally` 中 shutdown。
- Agent/Toolkit/Function：每个 coding task 独享，run 结束后释放，不进入跨任务缓存。
- task binding：创建 Agent run 前登记，Kernel 关闭后清理；`ExecutionReceipt` 仅保存在 binding 内。
- LSP：按 Workspace root 复用，idle TTL 回收；`close_execution_resources` 关闭剩余进程。
- Knowledge index：ExecutionContext 级单例；关闭时提交当前事务并关闭连接。
- 任一清理失败使用 Loguru warning 记录，不覆盖原始任务结果。

## 错误模型

新增或保留以下稳定错误码：

```text
report_coding_task_context_missing
report_coding_task_conflict
report_code_mode_execution_failed
report_code_mode_unavailable
report_code_source_invalid
report_code_script_modified_during_execution
report_code_submission_not_executed
report_code_output_missing
report_code_output_modified_after_execution
report_code_custom_tool_protocol_error
report_code_generation_no_submission
report_lsp_unavailable
report_knowledge_unavailable
```

工具可恢复错误以 `{ok:false, code, message, details}` 返回给模型；上下文缺失、任务冲突、资源关闭和文件身份冲突作为不可恢复 `ReportingError` 终止本轮。错误详情只包含逻辑路径、有界输出、行列位置、SHA-256 和异常类型，不包含宿主机绝对路径或环境变量。

## 代码删除与替换

允许并要求删除或替换以下旧设计：

- `ReportingCodeOpenAIResponses` 中仅支持唯一 `submit_python_source`、只消费一次 custom call、禁止混合工具的专用逻辑；
- `_tool_parameters("submit_python_source")` 与单轮最终源码直签；
- `_configure` 中强制唯一工具、固定 custom tool choice 和 `tool_call_limit=1`；
- `wrapped_source` 单轮调用计数；
- 服务端构造 unified diff 后再写脚本的 patch-before-write 路径；
- CodeMode Kernel 内注入 Knowledge/LSP 的反向 bridge 方案；
- `generate`/`repair` 两套重复 Agent 配置；
- 与上述行为绑定的兼容测试。

保留现有 custom tool 定义转换、非流式响应解析和稳定错误归一化中的可复用部分，将其泛化为 `write_script`、`execute_code` 与 function tool 共存的多轮协议适配。保留现有 AST、compile、authorizedPaths、文件大小、物理行和 FileIdentity 校验函数；它们迁移到 `run_script` 与 `submit_script` 的共享 validator。

## 测试计划

只运行新增和受影响的定点测试。

### Responses API 工具循环

- 普通知识/LSP function tool、CodeMode custom tool 和最终 submit function tool 可以在同一 Responses run 中顺序发生；
- provider `custom_tool_call` → Agno 内部工具执行 → `custom_tool_call_output` → 下一轮请求的消息形状正确；
- provider `function_call` → 工具结果 → `function_call_output` → 下一轮请求的消息形状正确；
- custom 与 function 的 call identity 分别关联正确，未知 custom 名称、空 input 和输出类型错配被稳定拒绝；
- `parallel_tool_calls=False`；
- submit 失败后继续，成功后停止；
- 文本结束、工具上限耗尽或无签发均失败。

### 交互式写入与签发

- `read_script` 和 `write_script` 只访问服务端绑定路径，完整源码通过 free-form custom input 往返且不进入 `function_call.arguments` 的内层 JSON 包装；
- `write_script` 可将语法错误中间稿原子写入正式 Workspace，CodeMode 也可直接修改目标脚本；
- 运行失败后模型可以在同一 run 中修改并再次执行；
- 探索 cell 中定义的变量不能泄漏为正式脚本的运行依赖；
- 每次运行前清理声明旧输出，失败产生的部分输出不能被下一次运行签发；
- 未执行、执行失败、执行后修改的脚本不能签发；
- 成功执行且源码与声明输出均未变时，返回源码 FileIdentity、输出 FileIdentity 清单和执行回执；
- 成功运行后缺失或修改任一声明输出时不能签发；
- 目标脚本自修改、符号链接、越界路径、未授权路径和并发 task 被拒绝；
- submit 成功后 Kernel 关闭且关闭后源码和输出身份均不变；
- 并发 coding task 不共享 Agent、Toolkit、Function 或动态停止状态。

### Knowledge 与 LSP

- 静态知识分块、增量索引、动态 workspace 过滤和并发读写；
- 1、2、3 字符中英文查询及 MATCH 特殊字符；
- LSP diagnostic version 等待、进程死亡重启、TTL 和关闭；
- definition/reference 的 Workspace 外 URI 不返回源码片段。

### Workflow

- analysis 交互生成并执行脚本后直接进入证据验证，不重复执行；
- visualization 交互生成并执行脚本后进入产物和视觉验证，不重复执行；
- execution diagnostic 和领域验收 diagnostic 都能启动下一轮交互修复；
- 修复知识只在最终领域验收成功后记录；
- 修复耗尽后的 analysis 放弃补证和 visualization 零图降级保持不变；
- 正常、异常和取消路径均无遗留 task Kernel 或 task binding。

## 落地顺序

1. 将现有 `ReportingCodeOpenAIResponses` 重构为非流式混合协议适配器，打通 custom/function 多轮调用及各自 output 消息；
2. 建立 `ReportingCodingTaskContext`、task binding 和 task 独享的 Agent/Toolkit/Function；
3. 实现 `read_script`、`write_script`、共享源码 validator、干净子进程 `run_script` 和源码加输出身份门禁；
4. 合并 generation/repair runner，接入 analysis 与 visualization Workflow；
5. 实现 Knowledge 索引和短查询回退；
6. 实现 LSP process manager 和只读工具；
7. 在领域验收成功点记录动态修复知识；
8. 删除旧单轮源码直签、patch-before-write 和兼容测试，运行相关定点测试。

每一步只运行对应测试文件；不重复运行完整测试集。

## 验收标准

- 同一个 Responses API run 能完成“查询知识 → LSP 检查 → 写脚本 → 执行 → 观察错误 → 原地修复 → 再执行 → 签发”。
- `write_script` 与 `execute_code` 使用 free-form custom tool，其余工具使用 JSON function tool；两类工具在同一非流式多轮 run 中正确共存。
- CodeMode 直接使用当前报表会话正式 Workspace，不存在临时 Workspace 或数据复制。
- 签发脚本及声明输出的 FileIdentity 必须分别等于该任务最后一次成功执行回执中的源码和输出身份。
- 固定 Workflow 不消费未签发文件，不重复执行已经由签发回执证明成功的脚本。
- 多个 coding task 不共享 Agent、Toolkit、Function 或 Kernel；任务结束后无遗留 Kernel 和 task binding。
- LSP 和动态知识不会向其他 Workspace 返回源码或业务内容。
- 相关定点测试全部通过，且不保留旧行为兼容分支。
