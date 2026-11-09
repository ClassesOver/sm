# 假设与实验矩阵

## 预登记规则

- 本研究只评估 Flint 的语义维度 registry、typed compile/diagnostic、家具占用布局三类机制。
- 不把增加图种、renderer、交互或降低验收门槛算作收益。
- 优先选择本项目最小修补；若本地显式 metadata 已解决目标问题，不以 Flint 架构相似为引入理由。
- 只有正确性先通过的配对样本才能谈成本。当前没有生产 trace，也没有 10 组以上固定配对，成本结论为 `unknown`。
- 业务语义需业务 owner 确认；视觉要两名独立盲评。缺席时不以开发者判断替代。

## 机制假设

| ID | 可证伪假设 | 支持观测 | 反例/停止条件 | 风险 | 独立验收 |
|---|---|---|---|---|---|
| S1 语义 registry | 将可视化相关属性集中到正交维度，能让“类型、加总角色、显示格式、零基线”变化有单一可追踪源。 | 同一类型在同一编译路径上驱动相容的 domain/format/aggregation 决策，测试对边界逐项断言。 | 派生业务意义仍需外部猜测；不同规则消费者不一致；登记类型错误但编译仍静默成功。 | 把启发式包装成“类型真理”，过度自信。 | 独立 oracle、source metadata 和针对变更的属性/负例测试。 |
| S2 显式 annotation | 显式单位和 temporal semantic 能比从标签/字段猜测更可追溯。 | 缺 annotation 时不推断展示单位；invalid typed temporal 值拒解析；本项目 metadata/绑定也能回溯。 | annotation 错仍可产生看似合理图；本项目已有冻结来源和显示单位限制。 | 元数据缺失后增加人工成本，不能自动修复业务事实。 | 独立数据字典/业务 owner 对声明确认，Decimal/Fraction 验证换算。 |
| C1 compile 诊断 | 将输入 normalization、语义、layout、emit 分开，可让非法映射以稳定阶段诊断定位。 | 同输入只改变一个字段导致一个稳定诊断码/字段路径，阶段可复现。 | 上游依赖不可安装；本项目已有逐图结构化预检与软 warning；缺少直接映射业务证明。 | 诊断码泛化或推断仍隐藏错误来源。 | 注错 mutation tests、identity assertions、外部审阅诊断含义。 |
| L1 furniture reserve | 在画图前估算家具空间可减少标签/图例挤压，并将占用决定解释为数值。 | label 长度/图例变化产生可预测 reserve/step 调整，PNG 确实更少碰撞且不改数据域。 | Matplotlib renderer 的实际字号/后端与 Flint 估计不同；只靠 canvas bounds 通过。 | 过度缩小绘图区，改善边界指标却损伤可读性。 | Agg PNG 图元测量 + 两位盲评；验证几何和数值/语义不变。 |

## 单因素矩阵与本次状态

| 案例 | 对照维度 | 锁定输入/预期 | 当前实现 | 最小修补 | Flint 机制 adapter | 结果状态 |
|---|---|---|---|---|---|---|
| A1 单位 | 元→万元 | `250000元 = 25万元`，Fraction/Decimal oracle | 项目已有显式单位、换算支持；定向项目测试 354 passed | 未实现实验分支 | 未实现运行 adapter；Flint `unit-display` 是展示单位，不是通用换算器 | oracle 通过；没有形成 A0/A1/A2 对比 |
| A2 比率/百分点 | 1/8 对 1/10 | 比率 `12.5%`；差值 `2.5pp` | 项目标注使用 isPercent、推导需显式操作 | 无新生产代码 | 不复刻语义 registry | 精确 oracle 通过；业务“同比”口径未审阅 |
| B1 比较期间 | 正基期、负基期、缺失比较值 | 缺失保留 null；公式独立计算；展示期间/计算期间应分开 | 项目现有 transform/period alignment 定向测试通过 | 无新生产代码 | Flint parser 只用于 typed date parsing，不负责本项目比较期语义 | 算术计算通过；负基期含义未裁决，日期 Flint tests 未运行 |
| C1 中文布局 | 中文标签、负值、缺失、金额单位 | PNG 画布内文字边界；缺失不绘数值 bar | 生成 PNG；首版发现负数标注与 y tick 过近，修正后复看 | 样例内负数标注放入负柱中心 | 未 adapter；Flint reserve 机制针对自身 measure/renderer | 当前样例自查可读；非独立视觉验收；不做总体效果推断 |
| D1 分页修订 | 数据快照跨页边界变化 | 新快照须重算映射、range、身份 | 源码存在全表共享值域和 atomic expansion；离线回放验证 3 类按每页 2 类生成 2 页、共享 max 从 3.4 变 11.1、SHA 改变；项目分页/身份测试已包含定向节点 | 不改生产代码 | 没有 Flint page/revision 接入实验 | 当前函数级 replay 通过；未做状态化重绘/四格式实验，保持未验证 |

## 重新运行与反例

```bash
.venv/bin/python \
  docs/superpowers/reports/2026-11-09-flint-standard-visualization/fixtures/run_synthetic_checks.py
```

脚本用 Decimal/Fraction 计算换算、比率与差异百分点，保留缺失值为 `None`，然后通过 Matplotlib Agg 输出中文 PNG，执行画布边界断言，并写入 `evidence/synthetic-check.json`。该脚本没有调用生产变换函数，也没有调用 Flint。

本次实际反例：首版中文图的文字边界均在画布内，但负值标签和 `-50000` 刻度靠得过近。通过查看 PNG 发现后，将负值标签放进柱体并复渲染。它证明 canvas-bound 测试会漏掉重叠，不证明修正版不存在所有视觉问题。脚本目前没有完整文本交叠、语义错绑或分页旧回执 mutation 检测。

## 运行和裁决记录

- 项目定向回归命令由项目现有测试节点组成，9 个文件，`354 passed`，1 个第三方 `imghdr` 弃用 warning，117.62 秒。未运行完整测试套件。
- 上游 Flint 测试未运行：`npm ci` 被 `EALLOWREMOTE` 阻止。因此没有 `upstream_tested` 或 `locally_reproduced` 级别的 Flint 结论。
- 本次无线上绘图 spans、模型调用/Token 和人工审查时长，不报告 median/P95、Coding 回退率或重绘耗时。
- `fixtures/replay_current.py` 运行结果：6 个案例通过，包含 ratio/mom 独立 oracle、错单位/丢单位、分页值域与 SHA 变化、伪造旧 SHA 诊断；证据为 `evidence/current-replay.jsonl`。它不是生产任务回放，也不是独立业务或视觉审查。
- 没有独立业务 reviewer 和盲法视觉 reviewer；第三方复核及计划最终验收尚未完成。
