# Reporting Worker 稳定型 Patch 闭环设计

## 目标

面向分析项和图表章节的脚本修改，提供单一、受限、可恢复的 `apply_analysis_patch` 工具，优先保证报表产出稳定，不建设通用 Coding Agent。

## 范围

- 分析项和图表章节统一只暴露 `apply_analysis_patch`；`create_analysis_file` 与 `overwrite_analysis_file` 不再兼容。
- 输入使用标准 unified diff；不维护自研 hunk 应用算法。
- 在临时 staging tree 中初始化隔离 Git 仓库，再调用 `git apply --check` / `git apply`；不要求用户 Daytona 工作区存在 `.git`，也不修改用户工作区的 Git 状态。
- 在临时副本中完成检查和应用，再通过现有 WorkspaceService 原子提交。
- 保留现有路径隔离、文件大小/数量、Python 语法和写入意图幂等语义。
- 选择性增强图表检查：`inspect_chart` 回执记录检查时文件 SHA，提交图表时核对当前 SHA，拒绝旧检查结果。

## 非目标

- 不改通用 `read_file` / `query_analysis_context` / `query_analysis_facts` 回执协议。
- 不增加通用 revision、查询回执过期机制或新的终态门禁。
- 不引入 `patch-ng`，除非后续独立验证明确证明 Daytona 无法可靠执行 `git apply`。

## 数据流

`apply_analysis_patch`：校验 schema 与目标路径 → 读取基线 SHA → 复制目标文件到临时副本 → `git apply --check` → `git apply` → 校验路径、文件数量、大小、UTF-8/Python 语法 → 通过 WorkspaceService 原子写入 → 记录 before/after SHA 与已有 mutation/write-intent 状态。

`inspect_chart`：检查当前图表文件并返回其 SHA；`submit_visualization_charts` 使用回执中的路径和 SHA 重新哈希当前文件，任何不一致均失败关闭。

## 错误与恢复

- diff 语法错误、冲突、越界路径、基线 SHA 不匹配、超限或校验失败均不写入用户工作区。
- 相同 patch 意图重放沿用现有 durable write intent，返回已提交结果，不重复产生副作用。
- Git 或临时 staging 初始化不可用时明确失败关闭，不静默退回自研 patch 算法。

## 验证标准

- 修改、新建、删除和冲突 unified diff 有定点测试。
- 旧 SHA 被拒绝且工作区无半写入。
- 多文件 patch 失败时所有目标保持原状。
- 旧 inspect 回执在图表文件变化后不能提交；当前 SHA 回执可以提交。
- 工具面不再暴露两个旧 analysis 写入工具。
