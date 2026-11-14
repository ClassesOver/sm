# 多 Harness 实时同步可行性分析

结论：技术可行，属于核心边界迁移，不是追加 A2A 或 WebSocket 即完成。固定工作流按用户确认弃用；DSH 是首个适配器，不是唯一外部执行者。

## 核查依据

核查本地代码及远端 origin/code（ca091c57）的 MCP 和事件实现。reporting_mcp/tools.py 仍只有 start/get/review/cancel，adapter.py 直接依赖 ReportWorkflowController。agent_event_streams.py 是容量128的进程内事件列表，无法证明跨进程文档恢复。编辑器已有 SHA 冲突检查与修订服务，可复用但尚非协同合并。#226 已交付协程守卫，不证明外部进程停止或同步成功。

DSH 官方 Session Controller 支持 prompt、follow、历史与会话控制，live assistant stream 与持久 Session event 分开；未验证本项目实际部署版本，也未证明其原生 A2A 接入。A2A v1.0.1 支持 TaskArtifactUpdateEvent，append/lastChunk 可传产物分块，规范明确断开重连可能漏过状态更新；它不提供报告对象版本、并发合并或无损事件重放保证。

来源：
- https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/api/session-controller/README.md
- https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/llm-streaming.md
- https://a2a-protocol.org/v1.0.1/specification/

## 推荐边界

Harness 规划、选择能力和修复；报告服务维护文档、业务事实和操作回执；浏览器呈现并提交用户变更。任一适配器将自身 session/run/tool 身份映射到项目执行身份，不能把 DSH Session 当所有系统共享权限。新报告从独立能力工具开始，不再启动固定阶段编排。

A2A 适合任务互操作，MCP 适合工具调用；两者可选适配。文档版本与领域操作必须由报告服务定义。HTTP提交+SSE下行已经能支持双向业务同步；WebSocket适合高频交互但不是必须。避免要求所有外部 harness 实现同一私有长连接。

文本、表格、图表同步可行；同段任意并发编辑更复杂，先采用稳定对象ID和baseVersion冲突检查。Yjs/CRDT需要与编辑器、存储、Undo和来源信息共同验证，不能承诺一次接入覆盖五格式。PDF/Office二进制采用固定修订异步导出，页面实时更新对象或预览；不承诺每个token完整重排全部文件。

真实难点是把已有计算与编辑服务从workflow运行上下文解耦，以及变更提交/事件落库的原子性。已收到通知不代表模型正在生成的请求已经吸收用户修改；必须在后续操作检查版本，必要时取消当前动作后重规划。多harness允许跨对象并行，同对象初版限制单agent写入者，用户编辑可使其基线失效。

## 验证顺序

1. 一个真实DSH会话修改正文或图表，浏览器显示服务端已提交对象；用户修改后DSH下次动作读取新版本。
2. 注入重复事件、乱序、断线、进程重启及迟到写入，检查最终状态、回执和无静默覆盖。
3. 接第二个真实harness，复用同一文档与工具合同，验证未绑定DSH消息格式。
4. 覆盖结构冲突、取消、来源失效、静态图与固定修订导出；按格式扩展。

延迟预算先测服务端提交至前端呈现，建议测试网络下P95<500ms；模型推理和导出单独计量。当前无实测延迟，无真实双向联调证据。本轮仅代码/文档分析，没有运行新测试或变更生产执行代码。

详细待办已写入唯一计划入口的M0–M7（含N0–N8映射）。最新确认：内置助手也是自主执行入口，外部可委托它或显式直接操作；常用入口为委托。固定工作流仍弃用，内置助手不固定绑定Codex。
