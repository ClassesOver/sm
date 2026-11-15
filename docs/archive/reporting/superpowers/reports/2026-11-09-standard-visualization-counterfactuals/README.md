# 标准可视化：反事实证据与优化裁决

本轮完成 **11 对单因素反事实、22 条观测及 8 项定向服务验证**，生产代码没有修改。现有单位、期间、绑定和分页修订机制在这些合成案例中符合既定约束；长中文标签只靠折行仍不能进入固定画布。这支持继续验证布局空间分配，不支持引入 Flint 整体运行库，也不支持宣称线上更快或全面正确。

研究规则先提交为 `ff1da2e9`，生产基线固定 `7550d1da392dcf928e81c3b8478b953c49c433b5`。全部输入合成，沿用原计划而不扩充图种。历史 [Flint研究](../2026-11-09-flint-standard-visualization/README.md) 保留原样；当前证据以本目录为准。[验收清单](checklist.md) 逐项标明边界。

## 证据如何核查

- [protocol.md](protocol.md)：实验前提交的假设、唯一变化、停止规则。
- [replay.py](replay.py)：独立 Decimal/Fraction 预期与当前函数/真实 Matplotlib 回放；拒绝覆盖已有输出目录。
- [results.jsonl](evidence/final/results.jsonl)：每例的业务意图、唯一变化路径、输入/计划/编译脚本/图片 SHA、实际诊断、图元测量。相邻两行构成一对。
- [final/](evidence/final/)：逐例 `frozen.json`、原始输入、`plan.json`、`compiled.py` 和图片。源码只为复现，不作为第二个oracle。
- [environment.json](evidence/final/environment.json)：Python、OS、locale、已安装依赖版本、项目锁和 runtime 源码身份；具体字体与缺字检查在每个绘图观测中。共享虚拟环境的已安装版本并不等于已证明从锁文件干净重建。
- [service_checks.py](service_checks.py) 与 [服务结果](evidence/services-2/result.json)：精确命令、返回码、源码身份和清理前生成的20个文件身份；[pytest原始日志](evidence/services-2/pytest.stdout.txt)、[JUnit](evidence/services-2/junit.xml) 证明8项通过。生成的服务产物在临时目录清理前哈希，未保存其字节；跨格式媒体相等是现有测试运行时断言，可复跑重建，不能仅凭哈希清单再独立提取媒体验证。
- [verify_evidence.py](verify_evidence.py) 与 [核对结果](evidence/integrity-check.json)：仅用标准库核对存档、单因素差异、当前源码身份和8个测试回执；不执行生产变换或模型。它是可核查性工具，不是业务或视觉证明。
- [trial-history.json](evidence/trial-history.json)：三个脚本失败及一次错误nodeid均记录原因；归档保留失败尝试产生的观测与工件。未保存三次原始traceback或历次replay.py正文，不能只靠归档独立重建脚本调试过程。按本次执行记录，修正涉及异常类型、NumPy序列化、分页标签字段和nodeid，生产实现、数值预期及布局第二因素未改；该过程说明不作为独立证据。最终回放与服务测试均退出0，失败尝试不计成功。

## 配对结果

| 对照 | 唯一变化与实际结果 | 结论边界 |
|---|---|---|
| U1 金额显示 | 输入字节相同，displayUnit 元→万元；`250000,-12500,0,null`→`25,-1.25,0,null`；绘图缺失柱为NaN，JSON记null | Decimal oracle和实际柱宽一致，输入未改；不是所有金额精度的证明 |
| U2 复合单位 | 同一输入，元/人次原值可画，轴保留完整单位；仅换displayUnit为万元/人次，`standard_unit_conversion_invalid` | 当前拒绝未登记复合换算；不把拒绝说成支持任意复合换算，也不通过删分母“修复” |
| U3 派生占比 | 1/8×100=12.5%；零分母/缺失null；仅分母unit元→人次后抛`ValueError: Incompatible derivation units` | Fraction oracle独立；这是局部变换拒用，不是终止下载签发的发布门禁 |
| U4 百分比尺度 | `%` 原值0.125不变，仅isPercent true→false；柱宽0.125→12.5 | 显式尺度被执行；不能证明声明本身业务正确 |
| P1 年份 | 来源字节不变，逆序2024来源按月对齐出`01:10/9,02:20/18`；periodYear 2024→2023后`source_period_year_mismatch` | 原始期间metadata保留；未声称任何自动同比口径识别 |
| P2 月份 | 一格2024-02→2024-03，输入SHA改变；`source_label_sets_differ` | 检出集合错配；不能识别日期和值一起被可信来源错误标注的事实 |
| P3 无关备注 | 添加researchNote，SHA改变；数值及期间metadata完全相同 | 仅证明该未知字段被忽略，不把新SHA当旧冻结文件 |
| B1 绑定 | 唯一exact dataPath下，missing.json可修正为supplement.json；仅改factPath为已登记facts.json后保留原绑定并软告警 | 不凭列名选择另一业务表；软告警继续执行不等于语义通过 |
| B2 歧义 | 加入第二个相同dataPath候选；由可修正转为保留missing.json并软告警 | 不证明后续模型一定能消歧；本例没有后续模型 |
| L1 中文布局 | 相同4×3英寸/150dpi画布、manual/canvas、标签和-12；labelWrap 40→8，宽456→152px；左越界400.67→96.67px，两个都拒绝 | 未得到合格候选；零文字bbox相交仍会裁切，不能视为视觉通过；debug图片不是交付图 |
| D1 分页 | 一格30000→100000，3类/每页2类仍2页；共享域`[-1.4,3.4]`→`[-2.1,11.1]`万元，旧SHA被`source_identity_mismatch`拒用 | 原图口径n=1、展开页n=2；函数回放和服务接通分别取证，不当支持率样本 |

单位/期间metadata扰动改变了输入身份，规划参数扰动保持输入字节相同；[核对结果](evidence/integrity-check.json) 逐对给出 `same_input_bytes` 与 `same_plan`。B1/B2没有原始数值文件，测试的是签发描述目录与计划的保守绑定决策，不冒充实际冻结业务表回放。

## 修订与四格式

本轮只重新运行PNG集成单例及必要故障/并发节点，没有重复完整测试。测试在真实本地Agno CodeMode执行标准脚本，禁止绘图模型调用；存储/repository和视觉审查使用测试替身。

1. 合成150→180后，受影响chart_a的两页重绘、执行证明与逐页视觉回执指向新图片；chart_c不变，旧snapshot仍可读。
2. PDF按解码像素核对两页；Word/PPTX/XLSX按媒体原始字节核对；XLSX源映射指向该snapshot与图片SHA，数据单元格为180。JPEG本轮没有重跑，不能拿本轮PNG结果扩大为JPEG新证据。
3. 缺页回执、旧回执和重绘失败不激活候选，父版本和原文件保留。并发修订仅一个CAS成功；编辑版本快照及导出历史独立；再次导出不改变数据快照历史。
4. 这些结论来自既有测试内断言。未运行AgentOS真实模型、授权HTTP全链或Office客户端人工打开；签发链路未修改，上一轮已运行的非阻断契约没有被本轮重新测试。

## Flint可借鉴的范围

固定上游 `microsoft/flint-chart@a794557384adcc3293a77043f6b9aff1c33d152c`，MIT，flint-js1.0.1；[源码身份](evidence/flint-source.json) 记录14份源码/测试/锁及license。`/tmp/flint-chart-full`干净；另一个research副本有大量缺失/未跟踪文件，未作为本轮权威来源。完整副本没有node_modules，本轮没有安装或运行上游测试，没有绕过此前EALLOWREMOTE限制。

| 原始机制 | 本项目证据与裁决 |
|---|---|
| `core/field-semantics.ts`、`type-registry.ts`把单位/类型/聚合角色/零基线分开 | 借鉴“声明和决策来源可追踪”；U1–U4及B1/B2显示已有显式metadata和保守绑定能解决本轮问题。没有漏检证据支持另造registry或接Flint adapter |
| `vegalite/assemble.ts`分prepare/analyze/plan/emit | 借鉴按阶段诊断；P1/P2/U2已有精确原因。不要为结构相似重写编译器，不把源码阅读当运行验证 |
| `furniture-reserve.ts`用文本测量记录各部分占用，`canvas-fit.ts`区分标签占比、缩放、绘图区形状 | L1证明仅折行不够，值得在Matplotlib实际字体/renderer上验证“预留标签空间”的有限候选。Flint阈值和估计器尚未在本项目验证，不能直接搬来作为中文视觉门禁 |
| `unit-display.test.ts`、`temporal-parse.test.ts`等边界测试 | 可参考“无声明不猜单位、typed期间非法就诊断”的测试思想；上游测试未运行，更没有证明Flint数值换算、四格式修订或中文布局优于本项目 |

没有增加图种、交互、Plotly、原生Office图表或宏。没有把Flint显示单位机制误认成通用复合单位算术。

## 优化清单与停止规则

| 优先级 | 最小后续动作 | 原始证据与验收 | 当前状态 |
|---|---|---|---|
| P1 | 单独立项：Matplotlib文本实测后预留分类标签空间的单因素候选 | 从L1相同冻结输入出发，固定字号/画布/裁切/值域，只变布局空间分配策略；全标签完整、负值不变、绘图区尺寸不被压缩到不可读，随后两位盲评。候选失败就停止，不同时缩字号/扩大裁切范围 | 有动机，未实现/未证明收益 |
| P1 | 单独立项：把中文业务名称作为规划输入映射到所有面向读者文本 | U1图片的缺失说明仍出现内部字段`value`；已有`standardStyle.series.label`可用于别名。先证明规划未提供别名还是执行丢别名，再选择最小提示/映射修补；正式实体和必要缩写保留原名 | 已发现样例映射缺口；不宣称生产必现；未修复 |
| P2 | 保留现有显式单位/百分比尺度、期间、保守绑定与新修订机制 | U1–U4/P1–P3/B1–B2/D1及服务8项；新增业务需求先加独立oracle和注错，再扩支持单位；不删分母、不跨表猜绑定、不降验收门槛 | 本轮无补丁必要；不要重构 |
| P2 | 独立业务、视觉及干净环境复核 | 提供冻结材料和oracle给独立审核人；确认负基期/分母口径；两名视觉盲评，记录意见与分歧；按锁重建复跑 | 人员与干净环境尚缺 |
| P3 | 正确性成立后再研究耗时和重复工作 | 至少10组**同候选的成本配对**，记录模型/准备/编译/绘图/审查/重试/导出spans、关键路径及累计量；按原图和展开页分别统计 | 无生产trace、无成本配对，不报中位/P95/收益 |

11对异质技术案例不构成10组性能配对，也不构成生产样本。缺失柱在图中明确保留空位；内部`value`文本仍是中文映射不足，不以数值通过掩盖。U1/U2测量还记录到数值轴范围外自动tick的bbox越出nominal canvas；这些tick不一定被实际绘制，因此不能直接计成导出裁切缺陷。L1则是实际可见分类文字越界并被生产检查拒绝，二者应区分。图元bbox无相交只覆盖文字，不覆盖所有图形/文字遮挡。

## 复现

在仓库根目录执行，Python应具备记录环境中的依赖；输出目录必须全新：

```bash
PYTHON=/path/to/venv/bin/python
REPORT=docs/superpowers/reports/2026-11-09-standard-visualization-counterfactuals
"$PYTHON" "$REPORT/replay.py" --output /tmp/sr-counterfactual-new-run
"$PYTHON" "$REPORT/service_checks.py" --output /tmp/sr-counterfactual-new-services
"$PYTHON" "$REPORT/verify_evidence.py"
```

前两条重建本地合成实验，不调用模型或外部业务服务；第三条检查已提交证据与当前源码是否仍匹配，源码变化后预期可能失败。UUID、临时路径、Office时间戳等会使文件SHA重跑不同；不以全文件SHA相等作跨运行正确性标准，应重验同一运行内的登记身份、媒体与数值关系。没有提供下载文件自动回传或生产部署。
