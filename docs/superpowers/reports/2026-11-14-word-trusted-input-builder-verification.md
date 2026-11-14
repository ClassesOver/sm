# Trusted Word builder verification: historical local and independent cloud evidence
Base: 0ce3aa10. No production registration/task submission/provider startup.
TDD: first focused node failed with AssertionError trusted Word input builder missing (1 failed,0 errors). Expanded initial contract file failed15 with same expected missing-module assertion before implementation. The initial attempt importing full service failed collection due missing data_profiling; this was NOT counted as RED.
Local command: PYTHONPATH=/tmp/sm-review-deps:/tmp/sm-receipt-deps python /tmp/run_word_builder_tests.py smart_reporting/reporting/tests/test_native_word_task_builder.py -q -o addopts=''
Actual:15passed exit0. Bootstrap suppresses application package assembly and stubs only report_editor.service.ReportEditorSession type for native_ai import. Actual builder, native models, selected_word_objects, NativeAIService._snapshot and task DTO normalization run unchanged. This is controlled-service unit evidence, NOT actual NativeEditorService/engine/registered-session/PG integration.
Ruff3files, compileall and diff-check passed. 1 pytest-asyncio fixture-loop default deprecation warning in local bootstrap.
Actual synthetic DOCX/NativeEditorService/grant integration tests and disposable PG test written but NOT RUN locally: complete app dependency graph/data_profiling and doc_engine unavailable. Await independent cloud locked-dependency run; cannot count negative tests passing due environmental exception as proof.
Historical full-project run at earlier phase failed collection with780 errors, not rerun here; no full-suite pass claimed. Real Codex, trusted production request integration and worker UID/host read isolation remain absent.

Astra found final-context-await expiry/removal window. Added two deterministic behavioral tests, each actually failed DID NOT RAISE before the fix (2failed/15deselected; no collection errors). Minimal builder-only change adds one final registered-session lookup/identity comparison and a fresh UTC expiry check after all awaits. Local focused suite now17passed; same bootstrap limitations apply. Actual DOCX failure-injection tests assert injection occurred, and authority-negative tests first execute a successful native preview so missing engines cannot count as valid rejection. Added two real DOCX final-context variants. These real-engine tests remain pending cloud execution. Re-observation is not linearizable cross-service revocation; later tools/commit/acceptance must reauthorize.

## 独立真实云链：三个执行轮次，123个唯一节点最终通过

本节覆盖上文真实引擎/PG尚未运行的本地历史状态，不把bootstrap单测外推为真实链。
精确受验源提交 `cad1f039228757c4c860bb32f83be32e7144db74`，tree
`6d5f0fadc0c3ebc1a77585fce9e2bac2ebd0501a`，base为 `0ce3aa10`。
原始bundle13293字节，SHA256
`0951b31a698c3b2530ad9f7312dc3e9e97a900a631b2afdb5a08834b8959f55e`，
15块、完整包、前置和精确HEAD/tree均独立核验。

云端使用真实锁定Python依赖、实际DOCX Node引擎/NativeEditorService及全新可丢弃
PostgreSQL18，正常模块导入，没有bootstrap替换服务类型。builder的17项受控单测
仍是受控场景，不替代其14项真实DOCX正反例与PG原子create接缝。

### 环境修正，不是产品RED或首次全绿

初始Node引擎缺tsx/编译桥接，因此pytest尚未启动，未计任何通过、skip或RED。
经明确授权，在隔离副本中将原锁绝对resolved URL临时映射官方npm，保留版本及
integrity、禁安装脚本。安装包和缓存tarball摘要经核验，仓库package/lock未修改。
随后原定七文件实际执行如下：

| 执行 | passed | failed | setup errors | skipped | pytest exit |
| --- | ---: | ---: | ---: | ---: | ---: |
| 首次全部123节点 | 62 | 11 | 50 | 0 | 1 |
| 仅重跑上述61个失败/error节点 | 45 | 0 | 16 | 0 | 1 |
| 仅重跑剩余16个PDF节点 | 16 | 0 | 0 | 0 | 0 |

第一次隔离doc_engine副本漏带其真实相对引用的frontend源码
`docx-table-alt-text-core`，文件实际存在于候选树；不能把引擎加载失败算作权限拒绝。
补齐真实相对布局后，第二次真实DOCX **14/14通过（含真实PG原子create）**，原Word AI
11个失败也通过；其余16项是PDF fixture静态导入兄弟workbook_engine的chart-add相对
路径及依赖缺失。经授权仅修隔离布局/原锁依赖，真实PDF inspect探针后，这16项通过。
三轮均未修改生产源码、仓库测试或仓库锁；没有将环境错误包装成安全RED。

逐node合并其最新结果为 **123个唯一节点最终全部通过**，不是一次123 passed：
原62个已通过节点未重跑，第二轮45个已通过节点亦未再跑。七文件为：

- `reporting/tests/test_native_word_task_builder.py`
- `reporting/tests/test_native_word_task_builder_docx.py`
- `reporting/tests/test_native_ai.py`
- `reporting/tests/test_native_word_ai.py`
- `reporting/tests/test_native_word_ai_wiring.py`
- `task_execution/tests/test_native_word_contracts.py`
- `task_execution/tests/test_native_word_repository.py`

上述路径均在smart_reporting/下。真实DOCX故障注入与正常预览、注册会话、来源/授权
选择正反例均实际执行；PG接缝不是skip。新增3个Python文件Ruff、diff-check通过。
每轮保留真实命令、stdout、JUnit、节点结果、source/tree/lock身份及清理记录。

### 警告、清理及边界

唯一pytest警告仍为第三方visions/utils/monkeypatches/imghdr_patch.py:2的
DeprecationWarning：imghdr将在Python3.13移除。安全负例预期产生
`native_ai_failed ... ReportingError` WARNING，原日志保留，不称warning/error-log-free。
使用的全新PG18容器及匿名卷均删除并核实，未访问业务库、业务凭据或实际用户文档。

独立Astra实际读取三轮云验收记录并核精确源树/六文件范围后，认可本限定builder可与
Normal rail按独立commit组成阶段候选。实际组合仍需精确树与两侧source/hash核对及
必要最小smoke，不能用两个来源分别通过代替组合验证。该整合不启用生产注册、调度、
provider或Codex；builder不提供跨服务线性化撤权保证，后续tools/commit/采纳须重新授权。
真实PPTX导入保存、OS IME、整个前端build、完整项目suite、生产鉴权/worker隔离及完整
四格式AI继续不在本验证范围。历史780全项目collection errors未重跑或改称通过。
