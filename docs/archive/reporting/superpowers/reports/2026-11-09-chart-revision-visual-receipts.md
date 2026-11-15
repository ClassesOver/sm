# 跨修订图表视觉回执身份核验

日期：2026-11-09。分支：`fix/chart-revision-visual-receipts`。
基线：`28649e9c56b1aa7e96f0c363e8eec8accd0175b7`（`code`）。

## 问题与最小改动

`report_editor/chart_continuation.py` 原有迁移逻辑直接重写回执的
`sourcePath`，未核对它是否属于原图片，且未核对 `sha256`。
旧图片的 `reviewed: true` 等字段因此可能随新修订沿用。

本补丁只调整跨修订登记迁移：

- 分别核验记录级、分页级回执的 `sourcePath` 和 `sha256`，两者必须精确匹配原图片身份。
- 匹配后复制回执并映射路径，保留 SHA 和原有审查字段，不生成新的审查结论。
- 非空回执身份不匹配或不完整时清空回执，在新登记写入一条去重软告警；空回执不新增告警。
- 告警最多保留最近 100 条，避免触发登记模型的长度限制。
- 保留现有图片、脚本、作图数据及完整分页的身份核验；原登记字节不变，重复迁移幂等。

未增加签发步骤或新的异常路径。调用者现有异常降级策略保持不变。

## 可复现验证

使用项目虚拟环境的 Python，在本分支工作树执行；无真实业务数据或模型调用。

1. RED：实现修改前，运行 `test_report_editor_chart_continuation.py`
   的 `-k 'stale_visual or warning_does_not_overflow'`：
   **9 failed, 1 passed, 13 deselected**。
   8 个失败覆盖记录/第二页的错误路径、错误 SHA、缺路径、缺 SHA；
   另一个失败覆盖 100 条已有告警下的无身份非空回执。失败均因旧回执被保留。
2. GREEN：完整运行该测试文件：**23 passed**。
   正例验证有效回执的路径迁移、SHA 保留、原/目标索引两种输入；
   错误回执用例验证分页保留、软告警、原登记不变及幂等。
3. 相关回归：**111 passed, 3 deselected**，执行集合如下：
   - `test_report_editor_chart_pages.py`
   - `test_report_editor_history_restore.py`
   - `test_editor_single_page_continuation.py`
   - `test_report_editor_lineage_export.py`
   - `test_publication_nonblocking.py`
   - `test_report_artifact_persistence.py::test_publication_gate_exception_preserves_download_input_and_failed_validation`
   - `test_http_publication_lineage.py::test_http_publication_never_blocks_links_on_lineage_faults`
   - `test_http_publication_lineage.py::test_http_publication_drops_hash_registered_foreign_index_but_still_issues_links`
   - `test_report_editor.py::test_editor_export_creates_new_revision_without_overwriting_published_markdown`
   - `test_reporting_completion_content.py::test_completed_report_content_states_the_specific_validation_reasons`
4. 两个变更 Python 文件的 Ruff 检查与 `git diff --check` 通过。
5. 独立只读代码审查未发现可报告的问题；审查者未修改文件或重复运行测试。

两次 GREEN 运行合计 **134 个不同定向用例通过**。未运行完整测试套件。
测试仅出现依赖已有的 `imghdr` 弃用告警。

## 证明边界与后续事项

身份检查只证明回执指向当前迁移图片，不能证明回执来源可信、业务数值正确或独立视觉审查通过。
无身份的历史非空回执会被丢弃；新告警保存在新修订的改图登记中。
告警已满时，追加本次原因可能淘汰最旧告警，原修订仍可追溯。

本项不改变初始改图注册、不重新审查图片、不接入真实 AgentOS 报告运行，
不实现 PDF/Word/PPTX/XLSX 四格式同修订联动。该联动仍是后续独立任务。
本分支独立基于 `code`，不包含 PR #198、#199、#200；本项交付至 PR，不合并或部署。
