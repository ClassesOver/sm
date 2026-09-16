- 语义业务校验只需要软告警
- 应用代码日志系统使用loguru
- 禁止重复完整测试
- 子agent使用与root一样的模型
- 不要自己造轮子，agno框架内支持优先

## CodeMode free-form 协议事实

- 2026-09-16 真实探针确认：DashScope Token Plan Responses API 上的 `deepseek-v4-flash-0731` 和 `qwen3.8-flash` 均支持 `type: custom` + Lark grammar，并能完成 `custom_tool_call -> custom_tool_call_output -> 最终回复` 闭环。
- DashScope free-form custom tool 使用 `tool_choice: "auto"`；命名 custom tool choice、`allowed_tools` 包含 custom tool 均会返回 400，`required` 在思考模式下也不可依赖。
- `write_script` 和 `execute_code` 必须保持 provider wire 层的原生 free-form custom tool，不得静默降级为 JSON function tool。
- 只有 provider 返回的结构化 `custom_tool_call` 可执行；不得解析或执行 assistant 正文中的 Markdown code fence、DSML 或伪工具调用。
- vLLM 当前只完成源码调查，未对真实 endpoint 完成 free-form 闭环探针；不得默认标记为支持，必须以同等真实探针验证。
