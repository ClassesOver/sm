# 移除 Coding 产品入口设计

## 目标

仓库只对外保留 Reporting 产品，删除 `smart_reporting/coding/` 的生产入口、CLI 和专属测试，且不改变现有 Reporting 工作流、持久化协议和部署行为。

## 范围

- 删除 `smart_reporting/coding/` 下全部生产代码和测试。
- 从 pytest 收集路径中移除 `smart_reporting/coding/tests`。
- 删除 README 中失效的 Coding CLI 启动说明。
- 将 Coding 测试中唯一直接覆盖 `ReportWorkspaceTaskToolkit` 的 Reporting 行为迁入 `smart_reporting/reporting/tests/`。
- 补充静态边界检查，确保仓库入口和文档不再引用 `smart_reporting.coding`。

## 非目标

- 不重命名 `task_execution/` 中现有 `Coding*` 内部类型或状态键。
- 不迁移或重命名 `agentos_coding_*` PostgreSQL schema/table。
- 不修改 Reporting 内部已有的 `run-coding-analysis`、`report-coding-*` 等持久化或工作流标识。
- 不删除 Reporting 仍使用的上下文投影、Sandbox Skill、验收、受控终端和工作区工具能力。
- 不顺带清理 SQLite 路径、大文件或其他架构债务。

## 实施设计

先把 `smart_reporting/coding/tests/test_coding_execution.py` 中使用 `ReportWorkspaceTaskToolkit` 的报表输出保留测试迁移到 Reporting 测试目录。迁移后的测试继续通过已有 Reporting fake 和任务执行 fixture 验证大输出可通过 `outputHandle` 完整读取，不复用 Coding 测试模块。

测试接管后，整体删除 `smart_reporting/coding/`，同步更新 `pyproject.toml` 和 `smart_reporting/README.md`。生产装配不需要改动：`smart_reporting/application.py` 当前只向 AgentOS 注册 `report_agent`，Reporting 运行时通过 `task_execution` 使用受控执行底座，并不导入 `smart_reporting.coding`。

最后通过全仓引用扫描、Reporting 定点测试、pytest 收集、Ruff、Mypy 和现有非集成检查验证删除没有留下失效导入或入口。任何涉及数据库迁移或 Reporting 协议改名的问题都留给后续独立变更。

## 成功标准

1. `smart_reporting/coding/` 不再存在。
2. 全仓没有 `smart_reporting.coding`、`smart_reporting/coding` 或 `python -m smart_reporting.coding.cli` 引用。
3. Reporting 相关测试不从 Coding 测试目录导入 fixture 或实现。
4. Reporting 定点测试、测试收集、Ruff 和 Mypy 通过。
5. Git 差异只包含 Coding 产品移除、必要的 Reporting 测试接管、测试配置和文档更新。

## 风险与回滚边界

主要风险是 Coding 测试此前隐式承担了共享执行底座的覆盖。通过先迁移 Reporting 专属行为测试、再删除目录控制风险。现有数据库对象和内部任务标识保持不变，因此部署不需要数据迁移；若验证失败，可以按独立提交回退产品入口删除，而不影响数据库状态。
