# Reporting 模块边界整理设计

## 目标

在不改变 Reporting 对外行为、持久化协议和 Agno 工具契约的前提下，删除 Workflow Controller
的无锁降级，并将三个超大实现文件按业务职责拆分为可独立理解、测试和维护的包。

## 当前问题

- `smart_reporting/reporting/workflow/runtime.py` 约 8,820 行，同时负责请求规划、数据画像、
  数据集物化、分析执行、章节生成、产物验收和发布。
- `smart_reporting/reporting/tools.py` 约 3,900 行，同时负责工具注册、Profile 查询、分析写入、
  证据校验、图表注册和章节渲染。
- `smart_reporting/reporting/delivery/report_runtime.py` 约 2,191 行，同时负责 Markdown、PDF、
  DOCX、manifest 验收和 CLI。
- `ReportWorkflowController._execution_lock()` 在 `workflow_execution_lock` 缺失时无锁放行，
  但 `WorkflowThreadOwnership` 协议已经要求该方法，生产仓储也始终实现它。

## 稳定契约

本次整理必须保持以下事实不变：

- `create_report_agent`、`create_report_runtime` 等应用装配入口。
- HTTP API、Workflow ID、14 个 step ID、步骤顺序和恢复语义。
- PostgreSQL 表、数据库 schema、状态键、持久化 artifact schema 和错误码。
- Agno 工具名称、参数 JSON schema、阶段工具集、完成门禁和 callable-tools cache 语义。
- Reporting 请求、Markdown、PDF、DOCX、manifest 和下载接口的输入输出。
- 当前公开的包级导出；仓内私有深层导入和 monkeypatch 路径随迁移一次更新。

旧单文件实现迁移完成后直接删除，不保留仅转发到新路径的兼容空壳。

## 架构

采用同名文件改同名包、包级稳定导出和职责 Mixin 的机械迁移方式。Mixin 只承载现有实例方法，
共享同一个 Facade 实例状态，不增加新的领域协议或依赖注入层。Facade 负责构造和流程装配，能力
模块不反向导入 Facade。

### Workflow Runtime

```text
smart_reporting/reporting/workflow/runtime/
├── __init__.py
├── facade.py
├── models.py
├── validation.py
├── planning.py
├── datasets.py
├── analysis.py
├── sections.py
└── publication.py
```

- `__init__.py` 至少导出当前装配使用的 `ReportWorkflowRuntime`；其余内部类型由迁移后的子模块按需导入。
- `facade.py` 负责构造、Workflow 装配、公共步骤入口和通用状态访问。
- `models.py` 保存仅属于 Workflow Runtime 的 Pydantic 模型和类型。
- `validation.py` 保存无实例状态的规范化与校验函数。
- `planning.py` 负责请求、数据范围、指标语义、提纲、分析计划和 SQL 候选。
- `datasets.py` 负责数据画像、数据集物化和分析上下文准备。
- `analysis.py` 负责 checkpoint、分析任务、证据绑定和确定性事实。
- `sections.py` 负责章节 WorkItem、章节执行、返工和正文汇总。
- `publication.py` 负责渲染、双格式验收、发布门禁和 manifest。

### Reporting Toolkit

```text
smart_reporting/reporting/tools/
├── __init__.py
├── toolkit.py
├── profile.py
├── analysis.py
├── sections.py
├── validation.py
└── factory.py
```

- `__init__.py` 至少导出当前装配使用的 `ReportWorkspaceTaskToolkit` 和 `build_report_worker_tools`。
- `toolkit.py` 负责 Toolkit 初始化、阶段门禁、公共调用入口和受控 Kernel 委托。
- `profile.py` 负责 Profile、analysis context 和 analysis facts 查询工具。
- `analysis.py` 负责分析文件写入、完成提交和持久化证据绑定。
- `sections.py` 负责图表检查/注册、章节渲染和分析返工。
- `validation.py` 负责 JSON Pointer、schema、输出路径和证据校验。
- `factory.py` 负责按 Reporting phase/task kind 构造最小工具集。

### Delivery Runtime

```text
smart_reporting/reporting/delivery/report_runtime/
├── __init__.py
├── markdown.py
├── pdf.py
├── docx.py
├── validation.py
├── runtime.py
└── cli.py
```

- `__init__.py` 导出当前 CLI/Workflow 使用的运行入口、`ReportFailure` 和视觉常量；其余渲染细节由子模块拥有。
- `markdown.py` 负责 Markdown 规范化、标题锚点和语义文档准备。
- `pdf.py` 负责 PDF 渲染、页面装饰、页码、链接和版面检查。
- `docx.py` 负责 DOCX 渲染、后处理和结构检查。
- `validation.py` 负责输入路径、图片、manifest 和产物边界校验。
- `runtime.py` 负责 `ReportRuntime` 的渲染与验收流程编排。
- `cli.py` 负责 `main` 和进程退出码。

## 依赖方向

应用装配依赖从 Facade/factory 流向具体能力模块，具体能力模块再依赖私有模型、纯校验函数和既有
领域包。下图的箭头表示 Workflow 的业务数据流，不要求对应模块形成链式 Python 导入：

```text
bootstrap / agent
        ↓
Facade / factory
        ↓
planning → datasets → analysis → sections → publication
        ↓
models / validation / existing domain packages
```

跨阶段数据继续通过现有 Pydantic 模型、checkpoint、artifact 和 durable state 传递。私有纯函数
按唯一消费者归属；只有存在至少两个真实消费者且语义稳定时才下沉，不创建含混共享模块。

## 执行锁失败关闭

`WorkflowThreadOwnership.workflow_execution_lock` 是强制协议。Controller 直接调用该方法并进入
异步上下文：

- 方法缺失或对象不符合协议时立即失败，不允许无锁继续。
- 返回值不是异步上下文管理器时失败，不做静默降级。
- `ReportingStateError` 继续转换为同 code/message 的 `ReportingError`。
- 先增加缺失 lock 方法的失败测试，确认当前实现会无锁通过，再删除兼容分支。

## 迁移顺序

四个阶段分别形成独立提交：

1. 收紧 Controller 执行锁，先测试后实现。
2. 拆分 Workflow Runtime，按 `models/validation`、`planning/datasets`、
   `analysis/sections`、`publication/facade` 的顺序迁移。
3. 拆分 Reporting Toolkit，先冻结工具名称与 JSON schema，再迁移 Profile、分析和章节能力。
4. 拆分 Delivery Runtime，先冻结 Markdown、PDF/DOCX 验收结构与 CLI 返回码，再迁移实现。

每个旧单文件只在所有实现、导入、字符串模块路径和 monkeypatch 目标迁移完成后删除。若某个方法
无法在不引入循环依赖或行为变化的情况下归属到能力模块，则暂时保留在 Facade，不为追求文件大小
强行抽象。

## 测试与验证

每阶段执行以下验证：

- 新行为或边界测试先失败，再做最小实现使其通过。
- 运行对应的 planner、state、section concurrency、tool contracts、report runtime、Controller 测试。
- 对改动文件运行 Ruff format、Ruff lint 和 Mypy。
- 验证包级公共符号可独立导入。
- 扫描旧模块路径、字符串模块路径和 monkeypatch 目标，要求旧路径清零。
- 运行 `git diff --check` 并确认 Git 将迁移识别为 rename 或可解释的移动。

全部阶段完成后运行 `bash scripts/check_agentos.sh`。目录整理不以全量测试代替每阶段定点测试。

## 风险与控制

- **循环导入：** 先移动叶子模型和纯函数；能力模块不导入 Facade。
- **工具 schema 漂移：** 迁移前增加工具名称与参数 schema 契约测试，迁移后比较完全相等。
- **monkeypatch 失效：** 全仓迁移字符串目标，并执行直接使用 monkeypatch 的测试文件。
- **Mixin 方法依赖隐式状态：** 保持现有属性名和构造顺序，不新增平行状态；Mypy 和定点测试覆盖。
- **PDF/DOCX 输出漂移：** 使用现有 Markdown 字节、PDF 页面、DOCX 结构和 manifest 测试验收。
- **改动过大难以回滚：** 四阶段独立提交，每阶段在进入下一阶段前保持完整测试通过。

## 成功标准

1. Controller 不再存在缺少执行锁时的无锁降级。
2. 三个旧单文件实现被同名职责包替代，不保留内部兼容空壳。
3. 稳定契约、工具 schema、工作流步骤、状态和持久化结构不变。
4. 仓内导入、字符串路径和 monkeypatch 目标全部迁移到当前权威路径。
5. 每阶段定点测试、Ruff、Mypy 和最终 `scripts/check_agentos.sh` 通过。
