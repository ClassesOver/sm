# Reporting Coding Agent 脚本生成设计

## 背景

当前分析项把 Python 放在 `AnalysisScriptDraft.script`，可视化把 Python 放在
`VisualizationScriptDraft.pythonSource`。两者都要求模型先把源码编码进 JSON，再由固定
Workflow 把字符串转换为 patch。该边界会同时放大三类失败：模型可能返回 JSON 字符串而不是
schema 对象；转义后的代码可能退化为单个物理行；长输出可能在结构化纠错前被截断。

日志中的“第 1 行，第 262140 列”接近当前 `pythonSource` 的 262144 字节上限，不是正常的
Python 列号增长，而是超长单行源码在限制附近被截断后产生的语法错误。继续调大 JSON 字段或
追加“必须换行”的提示不能消除这类边界问题。

## 目标

- 分析项补证脚本和可视化脚本都采用 Coding Agent 风格生成：代码通过文件 patch 写入工作区，
  不作为 JSON 字段返回。
- 业务判断和元数据继续使用严格结构化输出，并由固定 Workflow 控制写入、执行、校验和终态提交。
- 初次代码生成只看到 `apply_analysis_patch(patch)`；修复按“先 `read_file`、再
  `apply_analysis_patch(patch)`”两阶段执行，且不再生成或传递 `expected_sha256`。
- 保留服务端内部的乐观并发控制、durable write intent、路径隔离、幂等恢复和有界重试。
- 对最终脚本设置明确的字节和物理行上限，使单行膨胀在执行前以稳定错误结束。

## 非目标

- 不建设通用 Coding Agent、交互式 shell、任意文件编辑器或新的通用 patch 协议。
- 不向代码生成 Agent 暴露 `run_python_script`、图表检查或终态提交工具。
- 不允许模型选择脚本路径、证据路径、图表输出根目录或执行命令。
- 不修改补充证据、图表元数据、引用绑定和业务语义校验规则；业务语义差异继续只形成软告警。
- 不保留把长 Python 源码塞回结构化 JSON 的兼容或降级路径。
- 不引入数据库结构变更，也不改变 Daytona 工作区隔离模型。

## 设计原则

系统按内容类型分离通道：JSON 只承载短小、可验证的业务决策和元数据；Python 只通过
unified diff 进入签发文件；工具回执只承载文件身份和执行状态。模型负责写代码，固定 Workflow
负责决定何时写、执行、修复、验收和提交。

用于写入的 OpenAI 工具调用底层仍然使用 JSON，但该 JSON 只承载一次 `patch` 参数。传输层解码后保留 patch
中的换行；源码不再和 `charts` 等业务字段竞争同一个结构化输出空间。

这与常见 Coding Agent 的交互边界一致：Agent 基于当前文件生成 patch，冲突由文件系统或 patch
应用层发现，并发正确性由宿主维护。内容哈希可以是内部实现细节，但不应成为模型必须复制的工具
参数。删除模型可见的 `expected_sha256` 既减少无意义 token，也避免旧哈希、大小写和字段遗漏造成
与代码质量无关的失败。

## 组件边界

### 结构化决策 Agent

分析项使用 `AnalysisEvidenceDecision`，只返回：

- `requiresSupplementalEvidence`
- `reason`
- `missingFacts`

可视化使用新的 `VisualizationPlanDraft`，只返回 `charts` 和 `warnings`。`charts` 继续使用现有
`ChartDraft`，保存图表 ID、签发输出路径、标题、图注、引用、指标和期间等元数据。
`VisualizationPlanDraft` 不包含 `scriptPath` 或 `pythonSource`。

这些 Agent 继续使用 `ReportingStructuredOutputExecutor`。结构化纠错仅处理决策和元数据，不再接触
Python 源码。

### 代码生成 Agent

Bootstrap 为分析补证和可视化分别装配专用代码 Agent。两者可复用一个最小构造函数，但提示词、
签发路径、输入事实和脚本限制分别配置。代码 Agent 的契约为：

- `output_schema=None`，不要求也不解析 JSON、Markdown code fence 或普通文本源码；
- 初次生成只暴露并强制一次 `apply_analysis_patch` 调用；
- 修复分为两个受控调用阶段：第一阶段只暴露 `read_file`，第二阶段只暴露并强制一次
  `apply_analysis_patch`；
- 没有已提交脚本时必须用 `/dev/null` 到签发脚本路径的 create diff；
- 已有已提交脚本时必须针对 Workflow 提供的现有内容生成 update diff；
- patch 只能影响当前签发的一个 `.py` 文件。
- patch 成功后当前 Agent 调用立即结束，不继续解释、执行或提交。
- 每个 Agent 调用最多产生一次写入副作用。

Agent 的普通文本响应不代表成功。Workflow 只接受受控工具调用产生的唯一 `FileIdentity`；未调用、
调用失败、多次调用、写入其他路径或没有唯一回执都按本次代码生成失败处理。初次生成或修复阶段
出现无工具调用时，服务端启动 fresh Coding Agent retry；不得把文本源码转交给结构化解析器。

### `apply_analysis_patch`

模型可见 schema 只保留必填字符串 `patch`，删除 `expected_sha256`。Reporting Toolkit 的公开
入口也不再要求调用者传入该字段。

模型看到的调用参数等价于：

```json
{"patch": "diff --git a/... b/...\\n..."}
```

服务端仍执行内部 CAS，且源码门禁发生在任何真实 Workspace mutation 之前：

1. 解析 unified diff 并读取所有现有目标文件；
2. 在临时 Git tree 中执行 `git apply --check` 和 `git apply`，构造候选变更；
3. 对候选 Python 文件统一检查 UTF-8、LF 换行及末尾换行、脚本路径、字节大小、物理行长度、
   `ast.parse`/`compile` 和脚本策略；失败则不写入真实 Workspace；
4. 从实际基线内容派生每个 update/delete 的 `before_sha256`，并记录候选结果的
   `after_sha256`；
5. 将包含 before/after 身份的规范化操作写入 durable write intent；
6. `aapply_changes` 在 workspace lock 内重新读取目标，核对内部 `before_sha256` 后原子提交；
7. 若读取和提交之间发生变化，返回 CAS 冲突，不覆盖新内容，并要求重新读取后 fresh retry。

因此移除的是模型提供哈希的责任，不是并发保护。幂等键继续由规范化写入意图派生；已提交意图
重放时必须核对当前文件身份，pending 意图继续走现有恢复逻辑。

### 固定 Workflow

固定 Workflow 是代码生命周期的唯一控制器。它负责签发路径、构造 Agent 输入、验证工具回执、
读取已提交文件、执行确定性校验、运行脚本、校验证据或图表并调用终态工具。代码 Agent 永远不
获得 `run_python_script`、`inspect_chart`、`submit_visualization_charts` 或
`complete_analysis_item`。

## 分析项流程

```text
读取并验证 deterministic facts
  -> AnalysisEvidenceDecision
  -> facts 足够：跳过补证脚本
  -> facts 不足：分析代码 Agent -> apply_analysis_patch(supplement.py)
  -> Workflow 读取并验证 supplement.py
  -> Workflow 调用 run_python_script 执行固定 supplement.py
  -> Workflow 读取并验证 supplement.json
  -> 失败时读取当前脚本并进行有界 patch 修复
  -> AnalysisSummaryDraft
  -> complete_analysis_item
```

`AnalysisEvidencePlan.script` 和 `AnalysisScriptDraft` 被移除。决策 Agent 不生成代码；代码 Agent
收到冻结 facts、数据集身份、`missingFacts`、签发的 `supplement.py` / `supplement.json` 路径及
最小输出协议。

初次 patch 成功后，Workflow 按唯一回执重新读取脚本并核对路径、大小和 SHA。执行或 evidence
校验失败时，修复 Coding Agent 的第一步只读取当前签发脚本；读取回执交给第二步 patch Agent，
后者只提交局部 update patch。修复不得改写 `requiresSupplementalEvidence` 或绕过事实缺口。

若 patch 在提交前因 diff、路径或硬限制被拒绝，Workflow 不假定文件已经存在；下一次尝试仍使用
create diff。只有 durable write intent 证明脚本已提交且当前身份一致时，修复才读取该脚本并使用
update diff；否则下一次尝试使用 create diff。`read_file` 回执中的哈希仅供服务端校验，模型不需要
保存或回传。

保留 `MAX_ANALYSIS_SCRIPT_REPAIRS = 2` 的语义，即一次初始生成加最多两次修复。耗尽后继续沿用
现有补证放弃与软告警逻辑，不把业务缺口升级为不可恢复的全局报表失败。

## 可视化流程

```text
VisualizationPlanDraft(charts, warnings)
  -> charts 为空：Workflow 直接 submit_visualization_charts([])
  -> charts 非空：可视化代码 Agent -> apply_analysis_patch(charts.py)
  -> Workflow 读取并验证固定 charts.py
  -> Workflow 调用 run_python_script 执行固定 charts.py
  -> 校验签发图表文件和元数据绑定
  -> vision inspect_chart 或确定性检查
  -> 失败时读取当前脚本并进行一次 patch 修复
  -> submit_visualization_charts
```

现有 `VisualizationScriptDraft` 替换为 `VisualizationPlanDraft`。脚本路径固定为
`visualizationWorkspace.scriptPath`，不再由模型回传。结构化图表计划在进入代码生成前完成 schema
校验，并在代码修复期间保持冻结；脚本必须生成计划中声明的全部输出，不能借修复增删图表或改变
引用元数据。

现有单次可视化恢复预算保持不变。脚本执行失败、缺少图表、确定性检查失败或视觉检查要求修订时，
修复 Agent 第一步只暴露 `read_file` 读取已提交的 `charts.py`，第二步只暴露并强制一次局部
update patch。恢复后从脚本校验和执行阶段重新开始。租约冲突、取消、超时、capability 无效、
工作区不可用和文件身份变化继续直接失败关闭。

如果首次可视化 patch 在提交前被拒绝，恢复尝试按同一签发路径重新生成 create diff；不得用不存在
的文件构造 update，也不得放宽路径或脚本限制。

## 失败与恢复矩阵

| 失败 | 固定行为 |
| --- | --- |
| 无工具调用 | 丢弃普通文本，启动 fresh Coding Agent retry |
| 工具参数 JSON 截断 | 不写入真实 Workspace，带短诊断启动 fresh retry |
| unified diff 无效 | 临时 tree 校验失败，不写入，启动 fresh retry |
| 路径、语法、行长或大小不合规 | 源码门禁在 mutation 前拒绝，返回 `report_python_source_shape_invalid` 及短诊断后重试 |
| 文件在提交期间变化 | 内部 CAS 拒绝，不覆盖并发内容；重新读取后 fresh retry |
| 脚本运行失败 | 读取当前脚本，进入局部代码修复流程 |
| evidence/chart 验收失败 | 保留文件身份，进入有界代码修复流程 |
| 达到修复上限 | 分析项使用现有固定事实降级和软告警；可视化沿用章节失败策略 |

fresh retry 不把上一次的普通文本或完整源码复制进结构化输出；只携带短错误码、位置、大小和受限
上下文。已提交脚本的修复严格执行“read_file 一步、apply_analysis_patch 一步”，未提交脚本则
重新使用 create diff。

## 脚本校验和限制

Patch 适配器先对临时 tree 中的候选文件执行校验，Workflow 在提交后再按唯一回执重新读取并核对
身份；任何一步都不信任模型返回的源码文本：

- 分析补证脚本最大 128 KiB；
- 可视化脚本保持现有 64 KiB 上限；
- 任一物理行按 UTF-8 编码后最大 8 KiB；
- 脚本必须包含正常的多行结构，不能把整个程序压成单一物理行；
- 文件必须是 UTF-8、普通文件、签发路径下的单一 Python 文件；
- 在执行前完成 `ast.parse` 和 `compile`；
- 禁止把 CSV、facts 或图片数据直接嵌入源码；
- 可视化继续执行现有导入、绘图库、输出路径和禁用编排符号检查；
- 执行命令和超时由服务端固定，不能从源码或模型文本中派生。

大小、长行、语法或策略失败均在 Workspace mutation 前产生短的机器可读诊断
`report_python_source_shape_invalid`，并启动 fresh Coding Agent retry；不会触发结构化输出
downgrade。诊断至少包含 `path`、`size`、`lineCount` 和 `maxLineLength`，不记录或回显完整源码。
物理行限制直接阻断日志中出现的 26 万列单行源码。

典型门禁回执保持短小且机器可读：

```json
{
  "code": "report_python_source_shape_invalid",
  "details": {
    "path": "...",
    "size": 65536,
    "lineCount": 1,
    "maxLineLength": 65536
  }
}
```

## 恢复与可观测性

每个阶段继续使用现有 Task lease、checkpoint 和 durable state。若进程在 patch 提交后中断，恢复时
优先核对 durable write intent 和当前 `FileIdentity`；身份一致则从脚本校验/执行继续，不要求模型
重新生成。身份不一致按现有 artifact changed / write conflict 规则失败，不猜测哪个版本正确。

阶段日志使用 loguru，并区分 `decision`、`code-generate`、`script-validate`、`script-execute`、
`artifact-validate`、`submit`。诊断只记录大小、行号、错误码和截断后的执行输出，不记录整段源码。

## 迁移范围

- `analysis_item_workflow.py`：删除脚本型结构化 schema 和字符串转 diff；接入代码 Agent 回执、脚本
  校验和修复流程。
- `phase_models.py`：用无源码的 `VisualizationPlanDraft` 替换 `VisualizationScriptDraft`，把依赖
  `pythonSource` 的确定性校验迁移到文件校验函数。
- `visualization_section_workflow.py` 与 `analysis.py`：从“生成源码草案再代写 patch”改为“生成计划、
  调代码 Agent、验收已写文件”。
- `bootstrap.py` 与 `agent.py`：装配两个无 output schema 的代码 Agent，限制并强制 patch 工具；删除
  已无消费者的自由编排提示、动态 `patch -> run -> inspect -> submit` 工具投影和
  `expected_sha256` 回执提示。
- `analysis_item.py`、`validation.py` 和 `task_execution/tools.py`：收窄模型工具 schema，内部生成
  CAS 身份并保留 durable intent。
- 更新真实模型 probe，使成功条件是唯一 patch 回执，不再检查长源码 JSON 或模型生成哈希。

迁移为一次性切换。生产路径、恢复路径和 probe 都不得保留 `script` / `pythonSource` 长源码 fallback；
遗留 payload 出现这些字段时由严格 schema 拒绝，便于尽早发现未迁移调用方。

## 测试策略

只运行与本改造相关的定点测试，不重复完整测试套件：

- schema 测试：决策/计划可通过；`script`、`scriptPath`、`pythonSource` 和模型可见
  `expected_sha256` 被拒绝。
- Agent 装配测试：无 `output_schema`；初次只暴露并强制 `apply_analysis_patch`，修复严格按
  `read_file` 后 `apply_analysis_patch` 两步执行；普通文本、零调用、失败调用和多调用都不能推进
  Workflow。
- patch/CAS 测试：create、update、冲突和幂等重放；证明模型未提供哈希时，提交锁内仍能拒绝陈旧
  基线且不发生覆盖。
- 分析项流程测试：facts 足够时不生成脚本；缺口场景按固定顺序执行；语法、执行和 evidence 失败
  最多修复两次；耗尽后保留软告警。
- 可视化流程测试：计划冻结，固定脚本路径，执行/缺图/视觉失败只修复代码一次，成功后才能提交。
- 边界测试：128 KiB、64 KiB 和 8 KiB 行长的边界值通过，超出一个字节失败；262140 列式单行在
  mutation 前返回 `report_python_source_shape_invalid`，且超长单行永不执行。
- 恢复测试：committed/pending write intent、进程重启、文件身份变化和非恢复错误保持现有语义。
- 真实模型 probe：分析补证与可视化各覆盖初次生成和修复，确认模型只提交多行 unified diff，不返回
  Python JSON，不调用执行或终态工具。

## 验收标准

- 分析项和可视化的任何结构化输出 schema 都不再包含 Python 源码字段。
- 两类代码 Agent 均只能通过一次 `apply_analysis_patch(patch)` 产生候选脚本；普通文本不会被当作
  代码或成功结果。
- 模型工具 schema、提示词和工具回执不再要求 `expected_sha256`，并发测试仍证明陈旧写入被拒绝。
- 固定 Workflow 是唯一能执行脚本、校验证据/图表和提交终态的组件。
- 超限、单行、语法、执行和产物失败均在既定重试预算内得到明确诊断，不再进入长源码结构化纠错。
- 分析项补证耗尽时保持业务软告警；可视化继续遵守现有不可恢复错误和终态门禁。
- 相关定点测试与真实模型 probe 通过，且没有长源码 JSON fallback 或已失效的动态工具投影消费者。
