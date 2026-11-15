# 标准可视化生产优化：复用单图首次预检

## 问题与实现

研究 PR #197 将重复编译列为需要从实际调用链核对的成本。本次在基线 `28649e9c56b1aa7e96f0c363e8eec8accd0175b7` 确认：单图 `run_standard_chart_routes` 已完成标准预检，随后 `_run_standard_with_layout_retry` 在计划和冻结输入尚未变化时再次编译同一模板。

生产补丁只把该调用刚产生的预检结果交给单图重试函数首轮使用，不使用跨任务缓存。首轮编译耗时仍由外层记录一次；布局失败导致画布扩容时重新编译，成功后的 `create_standard_render_proofs` 继续独立重编译源码并绑定执行回执和图片身份。

| 路径 | 原路由预检次数 | 优化后路由预检次数 | 成功后的独立证明编译 |
|---|---:|---:|---:|
| 单图首轮成功 | 2 | 1 | 保留 1 次 |
| 单图扩容一次后成功 | 3 | 2 | 保留 1 次 |
| 混合多图 | 保持原行为 | 保持原行为 | 保持原行为 |

普通路由和确定性路由都覆盖该变化。首次预检与首轮消费之间没有异步挂起点；执行脚本仍重验磁盘输入 SHA。预检失败、身份失败、非布局错误和取消仍走原有分支，不增加模型回退或布局重试。

## 验证证据

- TDD：新增 4 个用例在原实现失败，均因路由编译计数比预期多 1；补丁后通过。用例实际执行 Matplotlib 源码，核对 PNG 身份，并用真实证明重编译核对最后执行的源码。
- 新增 2 个执行前磁盘输入替换用例：普通和确定性路径都拒用变更输入，不生成图片、不调用模型修复。
- 既有受控时钟测试同步调整：单次失败的总耗时为 3ms 初始编译 + 12ms 执行；扩容后再失败时累计编译为 6ms，而非包含重复首轮编译的 9ms。这些数值为测试时钟预期，不是性能测量。
- 相关定向回归 137 项通过；真实 Agno CodeMode 单图合成烟测及直接执行回归 21 项通过；最终新增测试文件 6 项通过。137 项中已包含该文件原先的 4 项，不把重复运行当作新样本。仅有既有 `imghdr` 弃用告警。
- 一次独立只读代码审查未报告缺陷；这是代码审查，不代替业务口径或视觉质量审阅。

定向回归命令（从工作树根运行，Python 指向项目已有虚拟环境）：

```bash
python -m pytest -q \
  smart_reporting/reporting/tests/test_standard_chart_compile_reuse.py \
  smart_reporting/reporting/tests/test_standard_chart_execution_observability.py \
  smart_reporting/reporting/tests/test_standard_chart_route_warnings.py \
  smart_reporting/reporting/tests/test_standard_chart_routing.py \
  smart_reporting/reporting/tests/test_standard_chart_combinations.py \
  smart_reporting/reporting/tests/test_standard_chart_proof.py \
  smart_reporting/reporting/tests/test_standard_render_proof_signing.py \
  smart_reporting/reporting/tests/test_report_editor_standard_observability.py \
  smart_reporting/reporting/tests/test_publication_nonblocking.py

python -m pytest -q -m 'integration or not integration' \
  'smart_reporting/reporting/tests/test_standard_chart_native_integration.py::test_native_codemode_runs_compiled_family_with_real_receipt[pie-asyncio]' \
  smart_reporting/reporting/tests/test_standard_chart_direct_execution.py
```

## 影响边界

这是研究后的首个生产补丁，证明减少了一次相同输入的路由编译。没有配对性能测量，不报告端到端速度、中位数/P95、模型调用节省或业务正确率提升；没有调用真实模型、访问业务数据、启动线上报告或部署服务。

语义证据契约、中文布局测量、分页修订和四格式联动仍是独立待验证事项。本补丁未修改发布/签发函数，也未新增签发故障点；定向执行发布非阻断守卫用于确认既有契约。回滚可还原此补丁，不涉及数据迁移、依赖变化或历史文件重写。
