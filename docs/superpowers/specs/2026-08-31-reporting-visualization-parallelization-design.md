# 可视化阶段按章节并行化设计

- 日期:2026-08-31
- 状态:已确认(用户批准五节设计;2026-08-31 评审 7 条意见已全部采纳并修订;后续明确不考虑历史 task/checkpoint)
- 背景:`/tmp/reporting_cli_20260831_112806/cli.log` 真实运行分析

## 1. 问题

真实 CLI 运行中,`run-coding-analysis` 步骤总耗时 53 分钟,其中可视化阶段单 worker 串行占 29.6 分钟,比 20 个并行 analysis_item(15.6 分钟)还长,最终整个工作流因 section 阶段 `tool_no_progress` 失败,未产出 PDF。

根因(按证据定位):

1. **单请求输出打满 64K 上限的长生成**:可视化 worker 4 次请求输出恰好 65,536 tokens(`_REPORT_VISUALIZATION_OUTPUT_TOKEN_LIMIT = 64*1024`,`agent.py:161`),每次以 140-206 tok/s 耗 5-8 分钟,合计 24.4 分钟,占可视化耗时 82.6%。模型一次性生成覆盖 18 张图表的 49KB `charts.py`。
2. **截断-被拒-全量重试恶性循环**:64K 截断导致 unified diff 无效/路径冲突被拒,每次重试又全新生成 65K,上下文从 69K 膨胀到 146K。
3. **注册不存在的图表**:模型在 `register_report_charts` 中提交了 5 张因数据缺失 SKIP 未生成的 PNG,`_inspect_chart_file`(`sections.py:705`)->`_avalidate_existing_path`(`workspace.py:1042`)抛 `WorkspaceError`,引发 error continuation 再注入全量任务。
4. **结构性无并行**:visualization 是"扇入汇聚点"--N 个并行 analysis_item 的全部产出(摘要+事实目录+提纲+引用)压进一条 user message 交给单个 worker,不经任何并发调度器;产出(图表注册)再被 M 个并行 section worker 以只读投影消费。

## 2. 目标

- 可视化阶段耗时从 ~30 分钟降到 5-8 分钟(并发度 4 时理论上限)。
- 单章失败只重跑该章(成本 3-5 分钟),不再全量重试。
- `register_report_charts` 契约、durable `charts` registry、`_finalize_reporting_sections` 物理搬运、section 的 `SectionWorkItem.charts` 派生**全部保持不变**。
- 消除注册不存在图表导致的 `WorkspaceError` 炸 run。

## 3. 非目标

- 不修复 facts 数据中"解析不到行/院区无金额"导致的 5 张 SKIP 图表本身(数据质量问题另行处理)。
- 不修复 section 阶段 `tool_no_progress` 死循环(独立问题,另行任务)。
- 不改变 `register_report_charts` 的整批注册语义、durable 写入语义、幂等键。
- 不引入图表跨域归属的人为规则。
- 不改变"全局至少一张已注册图表"的既有产品约束(见 6.6)。

## 4. 设计总览

`_run_analysis_phase`(`analysis.py:968`)中的单 visualization 任务(1080-1652 行)重构为两段:

```
冻结提纲 sections (每章 analysisIds)
        │
        ▼
┌─ 章节图表 worker × M (并行, Semaphore+TaskGroup) ─┐
│ taskKind = visualization_section                    │
│ 输入: 该章 analysisIds 的 facts catalog 子集        │
│       (跨域章自动获得多域 catalog,纯元数据)         │
│ 产出: charts-{sectionCode}.py 执行后的图表文件      │
│       写入 charts/{sectionCode}/attempt-{n}/       │
│ 终态: submit_visualization_charts (元数据草案)      │
│ durable: visualizationSections:{sectionCode}        │
└──────────────────────┬─────────────────────────────┘
                       │ 全章收口
                       ▼
┌─ 汇总 worker (串行) ────────────────────────────┐
│ taskKind = visualization_finalize                  │
│ 输入: durable 汇集的全部章节图表草案(仅元数据)    │
│       + 语义目录 + 完整 outline(ReportBrief)     │
│ 动作: register_report_charts (整批,契约不变)      │
│       + ReportBrief + finalize_report_analysis    │
└───────────────────────────────────────────────────┘
                       │
                       ▼
     section 阶段 (SectionWorkItem.charts 派生,不变)
```

**按章节分组而非按分析域**:日志证据显示 18 张图中 3 张跨域(`chart_income_cost_monthly.png`、`chart_income_cost_cum_gap.png`、`chart_income_workload_validation.png`)。提纲章节已冻结绑定 `analysisIds`(`hospital_operation/outline.py:33`),跨域章的 worker 自动获得多域 catalog,无需人为归属规则。

## 5. 任务身份、Schema 与调度

### 5.1 checkpoint Schema 升级(显式 schema 变更)

本次设计修改以下持久化 schema,属于同一交付内的显式协议升级:

- `ContextTrace.work_kind` 与 `CheckpointError.work_kind` 的 Literal 仅新增并保留当前协议所需的 `visualization_section`、`visualization_finalize`;不保留旧 `visualization` 值。
- 章节身份**不写入 `analysisId`**(其 pattern 仅允许 `analysis_[0-9]{3,6}`,`checkpoint.py:622`),而是使用两模型**已有的** `sectionCode` 字段;`visualization_finalize` 的 trace 不设 sectionCode。
- `ReportingCheckpoint` 新增 `visualization_section_errors: dict[str, CheckpointError]`(按 sectionCode 保存失败与 retryUsage,见 5.4);`last_error` 保留给汇总 worker 的全局终态失败。

### 5.2 章节图表 worker

- **粒度**:每个提纲 sectionCode 一个 Task。
- **task key**:`reporting_phase_task_key(run, revision, "analysis", section_code=sectionCode, task_kind="visualization_section", attempt)`;章节身份只写入 `sectionCode`,不复用 `analysisId`。
- **trace**:`phase="analysis"`、`workKind="visualization_section"`、`sectionCode=sectionCode`、`analysisId=None`。
- **调度**:复用 `_run_bounded`(`analysis.py:1891`,Semaphore+TaskGroup)的调度器,新写 `_run_pending_visualization_sections`(与 `_run_pending_analysis_items`:1922 同构):单章失败不取消兄弟章,收口后仅失败章 fresh attempt。
- **并发度**:新配置 `AGENT_REPORT_VISUALIZATION_CONCURRENCY`,默认 1,上限 4。配置校验、env 解析、bootstrap 装配与 `analysis_concurrency`(`settings.py:254-259`、`workflow/runtime/base.py:404,422-423,434`、`bootstrap.py:70`)完全同构。
- **durable 幂等**:payload 新增 `completedVisualizationSections: list[sectionCode]`;恢复时跳过已完成章。

### 5.3 汇总 worker

- **触发**:全部章节收口(含零图章,见 6.6)后。
- **task key**:`reporting_phase_task_key(run, revision, "analysis", task_key="viz-finalize", task_kind="visualization_finalize", attempt)`。
- **trace**:`workKind="visualization_finalize"`。
- **执行**:`register_report_charts`(整批,契约不变)+ 编写 ReportBrief + `finalize_report_analysis`;沿用现有全局收口链(`analysis.py:1532-1547` 的 durable 命令、1555-1580 的 checkpoint 迁移到 sections 阶段)。

### 5.4 失败恢复与账本

- **章节失败账本**(替代对单 `lastError` 的复用):并发章节失败全部写入 `checkpoint.visualization_section_errors[sectionCode]`(含 code/message/attempt/retryUsage);checkpoint merge(`analysis.py:361` 现覆盖标量 `last_error`)对 map 做按键合并,不丢任何章的账目。`_checkpoint_retry_error`(`analysis.py:1972`)新增按 sectionCode 查询的分支;双章同时失败时各自恢复各自的 retryUsage。
- **章节恢复**:fresh attempt(≤ `MAX_REPORT_SECTION_PHASE_ATTEMPTS=2`)只重建失败章 task;已完成章产物在 durable `visualizationSections`,重试章 instruction 以 `registeredCharts` 复用既有产物。`_visualization_recovery_required`(`analysis.py:2166`)的"只复用不重算"判断按章匹配。
- **汇总失败**:写 `checkpoint.last_error`(全局唯一);注册被拒时 error continuation 一次(现有 `MAX_REPORT_WORKER_CONTINUATIONS=1` 语义);仍失败则 fresh attempt 只重跑汇总,章节产物不动。`chartsRegistered` 标志位(`analysis.py:1125-1127`)语义不变。
- **动态预算**:`_visualization_dynamic_budget`(`analysis.py:2252`)按章拆分:每章 read units/fact query/tool limit 以该章 `analysisIds` 的 fact 文件为基数,总预算=各章之和;沿用失败关闭(同一路径不同身份即拒)。每章预算经各自 acceptance contract 注入;no-progress 的阶段失败计数(`agent.py:1373`)按 task 实例计数,与分析项同构,不再共享全局 visualization 计数。

## 6. worker 输入与输出契约

### 6.1 章节 worker instruction

`taskKind="visualization_section"`;字段为现有整包 payload(1314-1360 行)的按章投影:

- 该章 `analysisIds` 对应的 `visualizationFacts` 子集(1151-1305 行的 catalog 构造逻辑按章过滤;跨域章自动含多域)。
- 该章 outline 节点(完整冻结提纲的单个 section)。
- 该章 citationIds(`_visualization_analysis_citation_ids`:2077 按章过滤)。
- `visualizationWorkspace` 按章签发:`scriptPath = analysis/charts-{sectionCode}.py`;`chartOutputRoot = analysis/charts/{sectionCode}/attempt-{n+1}/`(见 6.5);terminal 白名单 `python3 .../charts-{sectionCode}.py`。
- `chartRegistrationRules`、`visualTheme`、`sourceWarnings`、`reviewFeedback` 照现有逻辑按章投影。
- 仍受 `MAX_REPORT_INSTRUCTION_BYTES`(512KiB)硬上限约束;按章子集远小于整包(本例 20 项 catalog -> 2-4 项)。

### 6.2 章节 worker 终态:submit_visualization_charts

新工具,仅 `visualization_section` taskKind 可调(`_require_phase_tool` 白名单):

- **输入**:`sectionCode: str` + `charts: list[ReportChartRegistration]`(字段与 `draft_v1.py:71-118` 完全一致;允许空列表,见 6.6)。
- **服务端校验**:逐项 `_inspect_chart_file`(存在性/大小/Pillow 解码,复用 `sections.py:808-862`);文件缺失返回失败回执 `report_chart_file_missing`(见 6.4);校验通过存入 durable `visualizationSections:{sectionCode}`(含图表元数据+文件身份)。
- **终态协议**:`submit_visualization_charts` 成为 `visualization_section` 的终态工具(与 `complete_analysis_item` 同构):工具成功即驱动 Task 进入 FINISHING,由 task_runner 收口。
- **vision 模式**:章节 worker 继续 `inspect_chart`(回执 durable,绑定 sha256);汇总注册时校验回执绑定(现有 `sections.py:1171-1208` 逻辑不变)。

### 6.3 汇总 worker instruction

`taskKind="visualization_finalize"`;字段:

- 服务端从 durable `visualizationSections` 汇集的全部章节图表草案(仅元数据,数 KB)。
- 各章产物文件身份。
- **语义目录(服务端确定性投影,非模型猜测)**:`analysisPlans`(dataset 覆盖来源)、`deterministicFactFiles`、`analysisCitationIds`、`citationDatasetIds`、`chartRegistrationRules.allowedMetricCodes`、`chartRegistrationRules` 全量规则。这些是 `finalize_report_analysis` 必填参数 `datasetSemantics`/`metricDefinitions`(`tools/analysis.py:848-852`,校验精确覆盖 evidence dataset,`checkpoint.py:355`)的受信输入;汇总 worker 与今天的 visualization worker 承担相同提交义务,但输入由服务端从冻结目录投影,不从图表元数据猜测。
- 完整 outline(ReportBrief 需要全局视角)+ `reportGoal` + `visualTheme`。
- 工具白名单:`register_report_charts` + `finalize_report_analysis` + 只读工具(`read_file`、`read_tool_output`、`get_skill_instructions`)。

### 6.4 register_report_charts 契约变化与 WorkspaceError 修复

- `_require_phase_tool` 白名单从 `{"visualization"}` 收紧为 `{"visualization_finalize"}`。
- 整批注册、`ReportChartRegistration` schema、`_apply_durable(name="register_charts", command_id=f"charts:{digest}")` 幂等键、`_finalize_reporting_sections` 消费逻辑全部不变。
- **WorkspaceError 修复(两入口共用)**:`_inspect_chart_file`(`sections.py:808-862`)捕获 `_avalidate_existing_path` 抛出的 `WorkspaceError("工作区路径不存在")`,转为失败回执:新错误码 `report_chart_file_missing`(稳定英文标识),`retryable: True`,requiredActions 指示"该图表未生成,从提交清单中移除或先生成再提交"。适用于 `submit_visualization_charts` 与 `register_report_charts`。效果:字段级可恢复错误,不再触发 error continuation 注入全量上下文,不再滚入 `tool_no_progress` 8 连败终态。

### 6.5 图表输出目录(按章按尝试隔离)

- 章节契约的 `chartOutputRoot` = `analysis/charts/{sectionCode}/attempt-{n+1}/`:隔离跨章同名文件冲突与 fresh attempt 的陈旧文件(旧 attempt 目录不清理,只作废:该章重试从新 attempt 目录开始,durable 账本只认最新 attempt 的文件身份)。
- 汇总契约的 `chartOutputRoot` = `analysis/charts/`(前缀覆盖所有章子目录);`register_report_charts` 的 `_require_chart_output_path`(`sections.py:796`)用汇总契约的 root 校验,`sourcePath` 由 submit 时存入 durable(含章与 attempt 子目录)并原样进入注册批次。
- **durable reducer 全局唯一性**:`submit_visualization_charts` 的 state reducer(state.py 新增分支)跨章节校验 `chartId` 与 `sourcePath` 全局唯一(与现有 `register_charts` 批内去重同构的 `report_chart_registration_duplicate` 语义),冲突章收到可恢复回执后自行改名重提。

### 6.6 零图表章节

- `submit_visualization_charts` 允许 `charts: []`:durable `visualizationSections:{sectionCode}` 存在且 charts 为空,即"已完成且零图",与"尚未提交"(key 不存在)可区分;`completedVisualizationSections` 收口判定只看 key 存在,不看图表数量。
- 全局零图维持既有约束:`register_report_charts` 拒绝空批次(state.py:515),`finalize_report_analysis` 要求至少一张已注册图表(`report_visualization_charts_not_registered`)。即:个别章零图合法,全部章零图在汇总处失败(现有产品约束,不在本设计范围改变)。
- 恢复语义:已完成零图章同样跳过重建;重试章被允许从零图改为有图(新 attempt 重新提交)。

## 7. 协议迁移矩阵(新 taskKind 全链路)

新 taskKind `visualization_section`/`visualization_finalize` 必须同步以下全部触点,任一遗漏都会导致新 worker 被解析为无 taskKind、工具全被过滤或终态不收口:

| 触点 | 文件:位置 | 变更 |
|---|---|---|
| 类型定义 | `reporting/phase.py:16` | `ReportingTaskKind` 仅保留 `analysis_item`、`visualization_section`、`visualization_finalize`、`section` |
| contract 解析 | `reporting/phase.py:218` | `reporting_task_kind_from_acceptance_contract` 白名单 += 两值 |
| run-context 解析 | `reporting/phase.py:585` | `reporting_task_kind_from_run_context` 白名单 += 两值 |
| 能力矩阵 | `reporting/tools/capabilities.py` | 新增 `REPORTING_VISUALIZATION_SECTION_TOOL_NAMES`(含 `submit_visualization_charts`、`write_analysis_files`、`terminal`、`inspect_chart`、只读工具;**不含** `register_report_charts`/`finalize_report_analysis`)与 `REPORTING_VISUALIZATION_FINALIZE_TOOL_NAMES`(见 6.3);`tools_for_task` 只保留当前 taskKind 分支 |
| 终态工具 | `reporting/workflow/execution.py:493` | `visualization_section` -> `("submit_visualization_charts",)`;`visualization_finalize` -> `("finalize_report_analysis",)` |
| 恢复指令 | `reporting/workflow/execution.py:505-530` | 新增两 kind 的 error-continuation 文案(章节:只补该章缺失动作后提交;汇总:只注册+冻结) |
| 指令模板 | `reporting/instructions.py` | 新 kind 的指令/完成条件模板;现有 visualization 模板删除(见第 8 节) |
| 输出限额 | `reporting/agent.py:160-162,2217-2232` | 见 7.1 |
| no-progress 计数 | `reporting/agent.py:1373` | 阶段失败计数按 task 实例隔离(与分析项同构) |
| acceptance contract | `reporting/workflow/runtime/analysis.py:1369-1415` | 章节契约 `taskKind="visualization_section"` + 按章 `visualizationWorkspace`/预算;汇总契约 `taskKind="visualization_finalize"` |
| budget 依赖注入 | `reporting/phase.py:28-59` | visualization 预算依赖键按 task 注入(现有机制,值按章/汇总区分) |

### 7.1 输出限额

- 新增 `_REPORT_VISUALIZATION_SECTION_OUTPUT_TOKEN_LIMIT = 16 * 1024`(章节 worker:每章 2-4 图+脚本约 12KB,与分析项同档)。
- `_REPORT_VISUALIZATION_OUTPUT_TOKEN_LIMIT = 64 * 1024` 改名/复用给汇总 worker(ReportBrief+整批注册参数+语义目录提交)。
- `_phase_request_model` 分支:`visualization_section` -> 16K、`visualization_finalize` -> 64K;`visualization` 分支删除(无新 run 携带,见第 8 节)。
- 同步更新 `test_reporting_agent_projection.py:2954-2989` 参数化断言表。

## 8. 旧协议边界

**选择:不考虑历史。** 服务不支持旧 `visualization` taskKind、旧 `workKind="visualization"` checkpoint trace 或旧单 worker 任务恢复。升级后仍持有旧状态的 run 必须重新发起。

- 删除 `ReportingTaskKind`、checkpoint `workKind` Literal、能力矩阵、指令模板、终态工具映射和恢复指令中的旧 `visualization` 分支。
- 不读取、不迁移、不重建旧 in-flight task;遇到旧 checkpoint 数据按当前 schema 的未知值失败关闭。
- 章节 attempt 只按同一 `sectionCode` 的 `visualization_section` trace 续号。

## 9. 与现有架构约束的对齐

- **AGENTS.md「Report Agent 与纯 Coding Agent 解耦」**:改动全部在 `smart_reporting/reporting/` 内部,不触碰 Coding Agent 边界。
- **「每项能力只有一个权威实现」**:`_run_pending_visualization_sections` 复用 `_run_bounded` 调度器;`submit_visualization_charts` 复用 `ReportChartRegistration` schema 与 `_inspect_chart_file` 校验链。
- **失败关闭**:`_visualization_dynamic_budget` 身份不一致仍拒绝;配置缺失沿用现有装配失败路径。
- **协议不变量**:`register_report_charts` durable 写入、幂等键、section 派生链路不变;错误码只增不改;checkpoint schema 只接受当前 workKind 值。

## 10. 测试与验证

### 10.1 契约测试(定点)

- `submit_visualization_charts` schema、phase 白名单、终态工具映射;`register_report_charts` 白名单收紧(`test_reporting_tool_contracts.py`)。
- `report_chart_file_missing` 错误契约(文件缺失返回可恢复回执,不抛 WorkspaceError)。
- 三类 taskKind 的 `max_tokens` 投影(`test_reporting_agent_projection.py` 参数化表)。
- 协议迁移矩阵的解析测试:contract/run-context 对新 kind 的解析、能力矩阵两 frozenset、`tools_for_task` 分支。

### 10.2 调度与恢复测试(定点)

- 章节并发:Semaphore+TaskGroup、单章失败不取消兄弟章(与 `test_reporting_section_concurrency.py` 同构)。
- **双章节同时失败**:`visualization_section_errors` 账本不丢账;两章各自恢复各自的 retryUsage。
- **同章 fresh retry**:旧 attempt 图表目录作废,新 attempt 重新提交;已完成章跳过重建。
- **文件名冲突**:两章同名 PNG 隔离在不同 `charts/{sectionCode}/attempt-n/`;durable reducer 拒绝跨章重复 chartId/sourcePath。
- **零图表章节**:空 charts 提交标记完成;与未提交可区分;全局零图在汇总处按既有错误码失败。
- 汇总只在全章收口后执行;汇总失败重跑不影响章节产物。
- **旧协议拒绝**:旧 `visualization` taskKind 和 checkpoint workKind 不被解析或恢复。
- 按章预算拆分与失败关闭(身份不一致拒绝)。
- **汇总语义冻结**:汇总 worker 的 `datasetSemantics`/`metricDefinitions` 从服务端投影目录提交,evidence dataset 精确覆盖校验通过。

### 10.3 回归与静态检查

- 定点运行 `test_reporting_agent_projection.py`、`test_reporting_tool_contracts.py`、`test_reporting_state.py`、`test_reporting_section_concurrency.py`。
- Ruff format、Ruff lint、Mypy 对改动文件。

### 10.4 真实验证

- 跑一次 CLI 工作流(同类医院年度运营报告请求),对照本次日志:
  - 可视化段耗时目标 5-8 分钟;
  - 单章输出不再出现 65,536 打满;
  - 图表注册无 WorkspaceError;
  - 最终产出 PDF。

## 11. 风险

| 风险 | 缓解 |
|---|---|
| 章节数多于并发上限时排队退化 | 上限 4 对齐 analysis 并发;章节 worker 输入小,排队总时长仍远小于现状 |
| 汇总 worker 成为新的单点长生成 | 其输出主要是注册参数+ReportBrief+语义提交(数 KB-十几 KB),远小于 64K;实测监控 |
| 升级时仍有旧单 worker run | 当前版本明确不支持恢复;重新发起报告运行 |
| vision 模式回执跨 worker 校验 | 回执绑定 sha256 的校验逻辑不变,章节 worker 提交时已校验,汇总时复核 |
| 旧单 worker run 无法恢复 | 当前版本明确不考虑历史;重新发起报告运行 |
