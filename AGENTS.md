- 语义业务校验只需要软告警
- 报告验收或发布门禁失败不得暂停/阻断工作流或阻止下载链接签发；如 PDF/Word 已生成且实际文件身份可读取，应保留并签发下载链接，同时明确返回验收失败原因和告警，不得标记验收通过。只有产物未生成或无法读取身份时，才无法签发对应链接。
  - 非阻断回归契约（修改发布/导出链路时必须保持通过；新增签发链路中可能失败的步骤，须在 `test_http_publication_lineage.py` 的故障注入用例中登记一条）：
    - `smart_reporting/reporting/tests/test_publication_nonblocking.py::test_render_validation_failure_retains_actual_artifacts`（工作流渲染验收失败保留产物）
    - `smart_reporting/reporting/tests/test_report_artifact_persistence.py::test_publication_gate_exception_preserves_download_input_and_failed_validation`（发布门禁异常不丢产物）
    - `smart_reporting/reporting/tests/test_http_publication_lineage.py::test_http_publication_never_blocks_links_on_lineage_faults`（签发阶段溯源故障注入）
    - `smart_reporting/reporting/tests/test_http_publication_lineage.py::test_http_publication_drops_hash_registered_foreign_index_but_still_issues_links`（伪造索引不被使用但照常签发）
    - `smart_reporting/reporting/tests/test_report_editor.py::test_editor_export_creates_new_revision_without_overwriting_published_markdown`（编辑器导出验收失败照常签发）
    - `smart_reporting/reporting/tests/test_reporting_completion_content.py::test_completed_report_content_states_the_specific_validation_reasons`（完成消息给出具体失败原因）
  - 禁止用 `raise` 表达“验收/门禁未通过”来终止签发；应把原因写入 `validation.issues` 或 `publicationGate.issues` 并继续。安全边界（作用域不一致、身份伪造）只能拒绝使用对应数据，不能拒绝签发已核验身份的 PDF/Word。
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
- `write_script` 和 `run` 必须保持 provider wire 层的原生 free-form custom tool，不得静默降级为 JSON function tool。
- 只有 provider 返回的结构化 `custom_tool_call` 可执行；不得解析或执行 assistant 正文中的 Markdown code fence、DSML 或伪工具调用。
- vLLM 当前只完成源码调查，未对真实 endpoint 完成 free-form 闭环探针；不得默认标记为支持，必须以同等真实探针验证。
