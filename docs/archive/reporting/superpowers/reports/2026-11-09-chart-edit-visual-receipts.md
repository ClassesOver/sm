# 首次改图登记的视觉回执身份核验

日期：2026-11-09。分支：`fix/chart-edit-visual-receipts`。
基线：`28649e9c56b1aa7e96f0c363e8eec8accd0175b7`（本地 `code`）。

## 原因与修改

`report_editor/chart_ai.py::_run_edit` 原实现为分页按路径选回执，
不核验 SHA；主图直接取执行结果第一条回执。全组 `reviewed` 只检查
返回回执是否全部 reviewed，没有验证回执覆盖每张当前输出图。

最小修复：

- 在已有登记阶段读取各输出图片的当前身份，匹配回执的路径和 SHA。
- 仅匹配回执写入登记；主图按主图路径选择，回执顺序不再决定主图归属。
- 身份不匹配的回执丢弃并软告警；返回了部分回执但未覆盖所有页时另记软告警。
- 全组 `reviewed` 要求每张输出图都有匹配且 reviewed 的 `vision` 回执；
  确定性图检和缺页回执不能代表独立视觉审查完成。
- 完全没有回执时沿用空登记及 `reviewed=False`，不新增告警。
- 告警去重后最多保留最近 100 条，避免新告警触发登记长度校验；原告警过多时可能淘汰旧告警。
- 图片、完整分页、改图登记和预览继续交付；复用各页登记所需的文件身份读取，不增加签发步骤。

不修改旧模板 apply、视觉自动修复策略、发布/导出函数及跨修订迁移。
本分支独立于 PR #202，二者分别修复首次登记和跨修订迁移。

## 验证证据

使用项目虚拟环境 Python 和受控合成输入，没有业务数据库或真实模型调用。

- RED：实现前运行 `test_report_editor_standard_charts.py`
  的 `-k 'drops_receipts or registers_only_receipt'`，**7 failed**。
  覆盖回执顺序变化、分页错误 SHA/错误路径/缺页，以及单图错误路径、
  错误 SHA、旧回执排在有效回执之前。
- GREEN：相同选择 **7 passed**。
- 五个编辑相关模块定向回归先得到 **85 passed, 1 failed, 10 deselected**：
  `test_report_editor_standard_charts.py`、`test_report_editor_chart_ai.py`、
  `test_report_editor_standard_edits.py`、`test_report_editor_standard_native.py`、
  `test_report_editor_standard_observability.py`。
  唯一失败的既有测试用固定假路径和 `sha256(b"img")` 却要求 `reviewed=True`。
  已改为让 runner 生成真实图片身份后附加原视觉问题，保留“一次修复、软告警、成功交付”全部断言。
- 修正夹具后补跑该失败用例及相关回归 **104 passed, 3 deselected**：
  - `test_report_editor_chart_ai.py::test_chart_ai_visual_issues_are_soft_warnings_and_trigger_one_repair`
  - `test_report_editor_chart_pages.py`
  - `test_editor_single_page_continuation.py`
  - `test_report_editor_lineage_export.py`
  - `test_publication_nonblocking.py`
  - `test_report_artifact_persistence.py::test_publication_gate_exception_preserves_download_input_and_failed_validation`
  - `test_http_publication_lineage.py::test_http_publication_never_blocks_links_on_lineage_faults`
  - `test_http_publication_lineage.py::test_http_publication_drops_hash_registered_foreign_index_but_still_issues_links`
  - `test_report_editor.py::test_editor_export_creates_new_revision_without_overwriting_published_markdown`
  - `test_reporting_completion_content.py::test_completed_report_content_states_the_specific_validation_reasons`

共 **189 个不同定向用例通过**，不重复计入早先七项 GREEN；没有运行完整测试套件。
最终三个变更 Python 文件的 Ruff 与 `git diff --check` 通过。
独立只读代码审查未发现可报告缺陷。

测试出现依赖已有的 `imghdr` 弃用告警。合成 runner 不提供完整标准执行证明，
相关回放会记录 `report_standard_chart_proof_unavailable`；这些回放仅验证改图登记契约，
不代表真实模型审查、生产运行或标准执行证明通过。

## 边界

路径/SHA 匹配只能证明回执所指图片与当前输出一致，不能证明回执来源可信、
业务数值正确、审查意见正确或用户视觉验收通过。
本项未重新绘制生产报告，不实现四格式同修订联动，不引入新渲染器或依赖。
交付至独立 PR，未合并或部署。
