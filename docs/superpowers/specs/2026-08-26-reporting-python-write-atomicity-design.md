# Reporting Python 写入原子性设计

## 目标

防止 Reporting 分析阶段的 `write_analysis_files` 将 Python 脚本写成语法无效状态后仍提交写入意图，
避免错误延迟到后续 `terminal` 执行预检才暴露。

## 范围与不变量

- 仅修改 `smart_reporting/reporting/tools/analysis.py` 的分析文件写入链路及其定点契约测试。
- 仅检查本次写入涉及的 `.py` 文件；非 Python 文件不增加行为。
- 保持已有工具名、入参 JSON schema、写入意图 hash、持久化 schema 和错误码不变。
- 不修改纯 Coding 产品、Workspace 通用 patch 语义或后续 Python 依赖预检。

## 设计

当前写入完成后立即计算 artifact 身份并提交 `commit_write_intent`。调整为：在 Workspace patch
成功后、读取 artifact 身份和提交写入意图前，下载本次涉及的每个 Python 文件，使用 `ast.parse`
和 `compile` 验证语法。

任一文件无法解析时：

1. 使用写入前保存的原始内容恢复本次涉及的文件；新建文件则删除。
2. 不调用 `commit_write_intent`，使该 intent 保持可恢复的 pending 状态。
3. 返回稳定的 Reporting 错误回执，指出被拒绝的脚本路径，但不输出完整源码。

恢复失败时，将恢复失败作为明确的写入错误暴露，不能伪造已回滚状态。有效 Python 写入和所有非 Python
写入沿用已有成功路径。

## 备选方案

在内存中复刻 overwrite、replace 和 unified patch 三类 Workspace 语义，再在实际写入前校验结果。该方案
可避免短暂的无效远端状态，但需要复制底层 patch 实现，容易与其冲突、匹配和路径语义漂移，因此不采用。

## 测试与验收

- 先增加回归用例：`replace_text` 将已有有效 Python 改为无效 Python 时，工具返回失败，文件内容恢复，
  且不提交 `commit_write_intent`。
- 增加有效 Python 写入仍成功并提交的测试，防止过度拒绝。
- 执行对应 pytest 节点、改动文件 Ruff format/lint、Mypy 和 `git diff --check`。

## 风险

写入与恢复之间会有极短暂的无效 Workspace 状态，但写锁限制并发写入，且本次修改不复制底层 patch 语义。
后续执行在同一工具调用完成前不会并发进入。若未来 Workspace 提供事务式 patch API，可将这一补偿机制替换为
该 API，而不改变 Reporting 工具契约。
