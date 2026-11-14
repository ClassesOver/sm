# PR #226 审查：Harness 主导与外接能力

审查日期：2026-11-14。范围：`ac856b81c8c3e556415d61cc88db3051b01a463a` → `a9b55c650c3cc993700ec459a7cb72d31434a359`，13 文件。重点阅读依赖与锁变更、应用装配、workflow/execution.py、task_execution/session.py、repository_impl.py 和新增测试、统一计划。未逐行审查 uv.lock 所有包内容，未执行生产接入。

## 结论

本次范围内未发现可确认的新增阻断缺陷。#226 是框架版本及协程生命周期基础补丁，符合后续 harness 主导的准备方向；不能据此判定外接 harness 或完整迁移完成。

## 代码依据与边界

1. `_run_executor` 在执行前后核状态，并用 watcher 轮询；finally 取消并等待 executor 和 watcher，避免协程清理尚未完成就进入 epoch 清理。`_cancel_and_cleanup` 携带 owner/epoch；旧 worker 被接管后只清理自身资源。
2. `cancel_and_reject` 在修改 run/instruction 前对 task 做 owner/epoch 条件更新；不匹配抛错并回滚。心跳任意普通异常置 lost，避免读取失败仍继续工作。
3. 这不是对每次外部副作用的原子授权。轮询存在检测窗口，真实 SQL/Office/CLI 写入仍需执行与提交边界 fence；已取消协程也不证明外部子进程已停止。
4. 清理等待没有独立截止机制；不响应取消或 finally 挂起的执行者可能拖住收尾。这是外接真实执行者前需验证的条件，未在本次证明为可达产品缺陷；不能用提前释放租约解决。
5. 新租约用例使用真实仓储 SQL 配合 SQLite 同步适配，能验证条件和回滚，不能证明 PostgreSQL 行锁交错安全。保留 PR 已披露的锁顺序观察，不把它写成已复现死锁。
6. 依赖 override 是显式兼容决定；定向用例不能替代 SDK/provider 真实握手、预算硬帽与原生恢复验证。未启用生产 Codex。
7. 用户确认目标是 harness 主导、支持外接。统一计划已有 delegated/direct，但对应 P0–P7 仍待实施；以 facts 后生成替代完整规划、或外部与内置同时写同报告，均不满足目标。

## 本轮验证

使用 `git archive a9b55c65` 导出 `/tmp/sm-pr226-review`，复用本机 `.venv`，从快照目录运行：

```sh
/workspace/sm/.venv/bin/python -m pytest smart_reporting/reporting/tests/test_reporting_task_runtime_guard.py smart_reporting/task_execution/tests/test_task_cancel_lease_fence.py -q
```

结果：**31 passed，1 warning，6.34s**。warning 为第三方 imghdr 弃用。没有新建依赖环境，不宣称复现 PR 作者的完整 117 项证据。首次导出因工作目录错误失败且测试未收集，修正 git 仓库路径后完成上述验证；未运行重复完整套件。

未验证：真实 PostgreSQL 并发、真实模型/CLI 及其后代取消、跨进程恢复、A2A/MCP 外接原生会话、五格式业务闭环。详细后续 checkbox 已更新至 [唯一计划入口](../superpowers/plans/agno3112-followup.md)。本轮不修改执行代码、不提交 Git、不发布 GitHub 评论、不部署。
