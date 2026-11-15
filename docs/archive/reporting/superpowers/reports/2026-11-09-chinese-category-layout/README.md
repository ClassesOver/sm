# 中文长标签：复用原生布局的最小优化

PR [#204](https://github.com/ClassesOver/sm/pull/204) 已于2026-11-09合并，提交 `b84437eee5cfed9ba808329a853b9b14e107d7aa`。本轮从该提交继续，复用其L1冻结合成输入，验证现有Matplotlib布局，再调整规划指引。没有新布局算法、依赖、图种、参数schema或发布链路变更。

## 结论与实际修改

原生`tight`/`constrained`已经会按实际字体为标签预留空间，**无需新增Flint adapter或自建测量器**。但完整显示标签不等于绘图区可读：同一张600×450图片，labelWrap=40会把原生布局的绘图区挤到69/86px宽；labelWrap=8时可保留373/382px宽，完整标签、9pt字号、-12和数值域均不变。

生产修改仅在 `smart_reporting/reporting/instructions.py`：

- 长中文分类优先使用既有tight/constrained，说明manual按声明边距放置，不自动为长标签让位；保持完整标签并同时检查绘图区。
- 固定尺寸下优先调整折行；不靠缩字号、截标签或crop=tight扩大导出边界掩盖空间不足。
- 纠正“series.label仅改图例”的错误说明：已有实现也将其用于缺失说明及部分默认系列标注；参考线等仍须显式提供`standardAnnotations.caption`，不能假设label覆盖全部文字。要求按已确认的业务含义提供中文显示名，series仍引用冻结列，正式实体与必要缩写保留原名。

此前U1样例出现`value 缺失`是未提供显示别名；现有已登记别名的实现和回归可覆盖中文缺失说明。没有证据需要改渲染器。指引的真实模型效果、回退率或视觉质量提升本轮均未验证。

## 2×3参数矩阵

原始冻结输入来自 [L1/wrap8/manual](../2026-11-09-standard-visualization-counterfactuals/evidence/final/L1/counterfactual/frozen.json)。所有6个变体都使用相同原始字节、相同字体、4×3英寸/150dpi、canvas裁切、同标题与类别、同-12和数值域`[-13.2,0]`。矩阵改变两个参数维度，但下述配对各只改变一个参数。

| labelWrap | layout | 执行 | 标签越界 | 绘图区宽×高(px) | 技术裁决 |
|---|---|---|---|---|---|
| 8 | manual | 拒绝 | 是 | 492×333 | 字号和数据不变，但边距不足 |
| 8 | tight | 成图 | 否 | 373.17×237.36 | 满足本合成案例300×200绘图区约束 |
| 8 | constrained | 成图 | 否 | 382.33×256.11 | 满足同一约束 |
| 40 | manual | 拒绝 | 是 | 492×333 | 单行标签越界 |
| 40 | tight | 成图 | 否 | 69.17×237.36 | 不满足本案例绘图区约束，不能称为可读 |
| 40 | constrained | 成图 | 否 | 85.83×256.11 | 不满足同一约束 |

可用的单因素配对：wrap8/manual→wrap8/tight或constrained，仅变layout；同为tight或constrained时wrap40→wrap8，仅变labelWrap。**不把wrap40/native相对原wrap8/manual的两处变化称为单因素实验**。300×200是观察本次结果后设定的工程回归下限，不是预注册指标、普遍视觉定律或新增生产门禁；像素约束也不能替代独立视觉审查。

## 验证与证据

- [probe.py](probe.py) 复用已合并的绘图回放，拒绝覆盖已有输出目录。[最终结果](evidence-final-v2/results.json) 保存6变体完整图元、实际绘图区、字号、数值域、输入/冻结状态/编译脚本/PNG身份；各变体子目录保留原始输入、计划状态、编译脚本和图片。manual拒用图仅为debug，不能作为交付图。
- [环境身份](evidence-final-v2/environment.json) 区分旧冻结输入代码基线 `7550d1da` 和本轮运行基线 `b84437ee`；当前指引文件及定向测试身份另见 [verification.json](evidence-final-v2/verification.json)。绘图实验不调用规划模型，因此指引文字不参与数值/图形计算。
- 最终指引修正后的定向验证 **12 passed，15.47秒**，[JUnit](evidence-final-v2/junit-final.xml)及[原始日志](evidence-final-v2/pytest-final.stdout.txt)。包含6项分类边界/原生布局、2项已有中文别名、3项固定像素、1项已有规划入口指引接入测试。后者仅检查接入未断，不证明模型学会新建议；不以源文本匹配测试冒充模型效果测试。早期12项记录另保留，修正说明后重跑这组定向节点，没有重复完整测试。
- 两个新增布局回归在指引修改前已通过，属于对已有能力的特征测试，**不是新算法修复的红绿测试**。保留已有manual裁切拒用与tight裁切扩边测试，未放宽检查。中文别名复用既有测试，没有增加重复用例。
- 最终6变体的字节身份和输入一致性已经核对；新旧最终测量版只因环境基线字段区分修正而复跑，图片身份相同。前两次成功探索输出和字段修正前结果保存在本机/tmp，不作为交付证据。最终交付包含可复现所需脚本与六变体，而不声称保存了全部探索历史。
- Ruff及git差异检查通过。未重复完整测试；渲染/导出/签发代码未改，没有新增签发故障点。未运行真实AgentOS、上游Flint或Office人工打开，视觉未盲评；不作线上正确率、耗时或回退减少推断。

在仓库根目录复现，输出目录必须尚不存在：

```bash
/path/to/venv/bin/python \
  docs/superpowers/reports/2026-11-09-chinese-category-layout/probe.py \
  --output /tmp/sr-chinese-layout-new
```

后续最小验收是对规划模型进行固定输入配对评估，检查是否主动声明完整中文别名、选原生布局和合理折行，并由独立审阅人判断可读性。该评估尚未执行；在缺少它时，本轮交付应称“生产规划指引修正与已有能力验证”。
