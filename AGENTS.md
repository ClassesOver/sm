- 语义业务校验只需要软告警
- 应用代码日志系统使用loguru
- 禁止重复完整测试
- 子agent使用与root一样的模型
- 不要自己造轮子，agno框架内支持优先

## CodeMode free-form 协议事实

- 2026-09-16 真实探针确认：DashScope Token Plan Responses API 上的 `deepseek-v4-flash-0731` 和 `qwen3.8-flash` 均支持 `type: custom` + Lark grammar，并能完成 `custom_tool_call -> custom_tool_call_output -> 最终回复` 闭环。
- DashScope free-form custom tool 使用 `tool_choice: "auto"`；命名 custom tool choice、`allowed_tools` 包含 custom tool 均会返回 400，`required` 在思考模式下也不可依赖。
- 2026-09-17 真实运行确认：即使设置 `parallel_tool_calls=False`，provider 仍可能在一次响应中返回多个结构化工具调用。不得把该请求参数当成“每轮必定只有一次调用”的保证，也不得仅因调用数量大于 1 就拒绝整轮响应。
- 多调用响应必须先整体校验工具声明、类型和调用身份，再按 provider 返回顺序逐个委托 Agno 执行。Agno 3.0.9 的异步工具执行器默认会并行执行整批调用，不能仅靠 `parallel_tool_calls=False` 保证执行顺序；前序调用失败或成功提交后，后续调用只补齐匹配原调用身份的未执行回执，不再执行。
- 协议回归测试必须覆盖同一响应中混合多个 custom/function 调用的顺序执行、失败后停止、提交后停止和结果回放，不能把“多调用必定报错”固化为测试契约。
- `write_script` 和 `run_snippet` 必须保持 provider wire 层的原生 free-form custom tool，不得静默降级为 JSON function tool。
- 只有 provider 返回的结构化 `custom_tool_call` 可执行；不得解析或执行 assistant 正文中的 Markdown code fence、DSML 或伪工具调用。
- vLLM 当前只完成源码调查，未对真实 endpoint 完成 free-form 闭环探针；不得默认标记为支持，必须以同等真实探针验证。
