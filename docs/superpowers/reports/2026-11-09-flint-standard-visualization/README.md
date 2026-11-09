# Flint 与中文标准可视化研究

## 结论

Flint 值得参考的是三项工程机制：把类型属性分解为正交决策维度、把显式语义注释传入有阶段边界的编译链、按文本/图例实际占用估计画布 reserve。当前证据支持“参考设计方法”，不支持引入 Flint runtime，也不支持声称它已改善本项目图表正确率或效率。

最适合本项目的后续动作是先补强可核验的本地契约：让单位/量纲/期间的来源字段身份与软诊断一起留在图表证据中；中文 Agg 图像继续做渲染后几何和独立视觉复核。Flint 的 registry 可作为规则建模参考，不应替换现有冻结输入、单位转换或 Matplotlib 路由。

## 本次完成与限制

- 固定 Microsoft Flint 源码提交、版本、license、lockfile 身份；阅读编译入口、语义、单位/时间、domain、布局 reserve 和对应测试源码。
- 从当前项目 HEAD 跟踪 chart draft / frozen chart-input / preflight / per-chart route / pagination / static Matplotlib 实现，并运行已有定向回归。
- 增加只含合成数字的 Decimal/Fraction oracle、PNG、几何边界探针和 JSON 证据记录。
- 用当前生产变换、分页和值域、来源 SHA 对同一组合成输入做 6 个离线回放案例；结果写入 `evidence/current-replay.jsonl`。
- 项目定向回归 `354 passed`；测试清单见 `source-map.md` 的链路引用，完整命令可从 shell history/本次执行记录复现；未跑全套。
- Flint 上游测试未能运行：锁定依赖安装被当前环境的 `EALLOWREMOTE` 拦截。不能把 Flint 源码测试标为通过。
- 没有访问真实业务数据、生产回执、线上 trace，也没有两名独立视觉审阅人或外部业务审阅人。业务正确性、独立视觉结论和生产收益保持未裁决。

## 三项机制裁决

| Flint 机制 | 值得参考 | 不宜直接移植 | 当前证据 |
|---|---|---|---|
| 语义 registry | 将 aggregation、domain、format、zero baseline 等拆成独立且可查规则，有利于审计规则改动和覆盖边界。 | Flint registry 的 type 名与语义假设不能直接作为中文业务数据字典；隐式类型推断只能作为提示，不能覆盖来源元数据。 | Flint 源码可定位，测试源码覆盖显式单位展示与 typed temporal parsing；项目侧单位/期间定向回归通过。没有独立业务裁决。 |
| compile/diagnostics | 分阶段保留输入规范化、字段语义、channel 决策和 emit 边界，诊断可以绑定阶段/字段。 | 不另造完整 compiler，也不让语义 warning 阻断工作流；项目已具备冻结输入、预检和逐图 Coding 回退。 | 项目侧 354 个相关测试通过；Flint tests 未执行，所以 Flint 的运行行为仍未复现。 |
| 布局 reserve | 把轴标签、标题、图例占用量显式建模，能提供“空间去哪了”的解释。 | 不直接复用 Flint 的像素预算/fit 阈值，它基于自身 text measurer 和 Vega-Lite 输出，与 Matplotlib Agg 中文字体度量不同。 | Flint 有源码与测试断言；中文 PNG 只通过画布边界检查并经一次自查修正。独立视觉判断缺失。 |

## 实验摘要

独立 oracle 确认 `250000 元 = 25 万元`、`1/8 = 12.5%`、`(1/8 - 1/10) × 100 = 2.5` 个百分点，并保留缺失值为空。同比样例按 `(本期-同期)/同期` 纯算术得到 `[20%, 50%, null, 25%]`；其中负基期案例只校验公式，不将正的 50% 解释为通用的业务同比口径。

Matplotlib Agg 图像展示长中文期间标签、负值和缺失标签。画布边界检查发现 0 项越界；第一次查看图片发现负值标注挨近 y 轴 tick，故把标注移入柱内重绘。最终 PNG SHA256：`24407d89ebb2468445ca97e83098a50e6442392b3e24c2f4284ea858b09ceed5`。这不是独立视觉评审，也没有完成文字交叠算法或多样本盲评。

没有运行三路 A0/A1/A2 反事实、Flint adapter、服务端 revision/export 状态回放、四格式联动或 10 组性能实验。因此不得从本报告推出正确率、回退率、速度、P95 或生产收益。当前回放只证明当前函数对合成输入的技术行为：比率零分母/缺失保留空值、错单位/丢单位被拒绝、分页修改会改变全表值域和文件 SHA、伪造旧 SHA 被拒绝。

## 建议清单

1. **优先补充本地语义证据契约。** 对派生指标保留源字段、来源文件 SHA、单位、isPercent/量纲、period 与计算窗口身份；对不一致信息生成可追踪软告警。验收应使用独立 Decimal/Fraction oracle、错单位/丢单位/period 错绑注入，且检查 warning 不阻断图片链接签发。
2. **布局只引入本地测量与验证接口。** 先在 Matplotlib Agg PNG 测量文字 bbox、轴/图例占用、裁切与实际文本相交，保留数据域、标签映射和顺序；之后由两名盲评员复核中文长标签、负值、百分比和复合单位。不要照抄 Flint fit 阈值。
3. **分页快照联动另设小实验。** 固定一个分页计划与图表输入身份，修改单格并验证影响图的新 revision、页映射/共享域及回执失效；失败时旧版本继续可追溯。完成前不宣称 Excel/Word/PDF/PPTX 都引用同一核验修订。

不建议引入 Flint 依赖；不建议仅凭其架构新建通用类型系统。若本地最小契约已覆盖错误案例，研究目标即达成，无需扩大图形范围或改变 renderer。

## 状态

- 已证明：固定 SHA 和测试结果；列出的项目定向测试通过；合成算术 oracle 通过；图中文字未越画布；源码所示机制与测试断言的边界。
- 未验证：Flint Vitest 运行结果、A0/A1/A2 的因果对比、分页 revision 失效链、四格式复用同一 Matplotlib PNG、外部业务口径、盲法视觉质量、生产收益。
- 材料不足：真实冻结业务输入、历史 spans / tokens / 模型调用和失败回执，独立审阅人员。
- 无关项：Flint 图种数量、多 renderer / Plotly / 交互部署不属于本项目本轮问题。

详细可追踪材料：[`source-map.md`](source-map.md)、[`experiment-matrix.md`](experiment-matrix.md)、[`fixtures/run_synthetic_checks.py`](fixtures/run_synthetic_checks.py)、[`fixtures/replay_current.py`](fixtures/replay_current.py)、[`evidence/synthetic-check.json`](evidence/synthetic-check.json)、[`evidence/synthetic-chinese-chart.png`](evidence/synthetic-chinese-chart.png)、[`evidence/current-replay.jsonl`](evidence/current-replay.jsonl)。

项目定向回归实际命令：

```bash
.venv/bin/python -m pytest -q \
  smart_reporting/reporting/tests/test_chart_input_group_units.py \
  smart_reporting/reporting/tests/test_chart_input_projection.py \
  smart_reporting/reporting/tests/test_standard_chart_domains.py \
  smart_reporting/reporting/tests/test_standard_chart_presentation.py \
  smart_reporting/reporting/tests/test_standard_chart_transform.py \
  smart_reporting/reporting/tests/test_standard_chart_pagination.py \
  smart_reporting/reporting/tests/test_standard_visualization.py \
  smart_reporting/reporting/tests/test_standard_visualization_diagnostics.py \
  smart_reporting/reporting/tests/test_standard_chart_routing.py
```
