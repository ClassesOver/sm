# 标准补证算子深度审查

日期：2026-11-06。基线提交：4b543a5399d4de1ce786aa8203ad7d98ed6bd80d。
分支：audit/standard-supplemental-depth。
托管 worktree：/home/junge/.codex/worktrees/b554/smart_reporting。

> 状态更新：以下保留初审原始记录（34通过、2失败，不是当前修复结果）。用户随后批准三批实施；修复及当前验收状态见 [三批实施报告](2026-11-06-standard-supplemental-repairs.md)。原 F1/F2 已转绿，R19 真实业务材料暂缺。

## 结论与证据强度

七类算子的手算样本均与实现一致；比率聚合、期间日历配对、中位数不可加性和集中度总体尾部均有可执行证据。本次新增验证36项：34通过、2失败。现有相关回归306项通过（124基线 + 149补充 + 33运行时）。这些结果只覆盖记录的样本与前提，不能视为业务数据或全部输入空间均正确。

发现一项可直接复现的证明缺陷：纯空格成员被当作有效归属，产生无告警的完整总体证明。发现一项条件性防御缺口：当可信父事实把无明细月份声明为零时，证明不独立检查月份覆盖。故障注入另外证实：生产计算与证明共用聚合函数，二者一致不能排除共同计算错误。

本次只新增计划、测试、报告；生产逻辑、公共API和输出类型均未改变。两个失败作为普通失败断言保留，没有skip、xfail或放宽预期。审查交付完成不等于算子通过全部审查。

## 1. 什么才算正确

必须分别成立：

1. 数学正确：输出满足所选公式，单位和小数比例一致。
2. 业务适用：指标能在指定期间、维度和总体内按该公式聚合。
3. 数据完整：授权输入足以覆盖所声称的成员、期间和操作数。
4. 身份可信：实际字节、登记文件、父事实、请求和输出绑定一致。

总额闭合只支持相应等式；哈希支持字节身份；同源复算支持一致性；均不能替代原始业务定义、上游取数正确性和独立计算。

### 七类契约

记 x[g,t] 为授权范围内、同一粒度、有限有效金额；T为所选窗口总额。适用前提是金额可以沿请求维度相加，多期总和还需时间可加；累计快照不可直接跨期求和。生产预检对这些登记前提设限，不由低层执行函数重新推断。

| 算子 | 公式、输出与分母 | 成立条件及边界 | 独立验证节点 |
|---|---|---|---|
| group_summary | G[g]=Σt x[g,t]；share=G/T；金额降序、同值按标签排名 | 同一总体完整分组；T=0时份额为空；负值份额不是概率 | seven_operations；summary_cancellation；summary_row_order |
| group_period_series | 每期独立G[g,t]、份额和排名；可选前期差与变化率 | 前期按日历寻找；缺期/缺组不补零；零前期变化率为空 | seven_operations；series_preserves_missing_period |
| cross_group_summary | 按(g,h)累加，份额除全体；边际份额分别除对应g或h合计 | 重复单元按可加明细求和；缺失组合不凭空补零；重复边际合计不能再次跨行求和 | seven_operations；cross_cells_add |
| period_comparison | Δg=Cg−Bg；rate=Δg/Bg或Δg/abs(Bg)；贡献=Δg/(ΣC−ΣB) | 同指标、单位、范围、日历角色；逐期模式贡献和排名仍按全窗；零总变化贡献为空 | seven_operations；negative_baseline；external_baseline；monthly_comparison |
| group_ratio | N=Σn，D=s×Σd；difference=N−D；ratio=N/D | 登记公式绑定分子分母身份、范围、期间和换算s；不能平均行比率；D=0时ratio为空 | seven_operations；ratio_aggregates；ratio_unit_conversion |
| group_period_comparison | 逐期本期减前期/基准均值/基准中位数；贡献除独立计算的总体变化 | 各组和总体分别计算基准；中位数不可加时保留真实差额，不能配平 | seven_operations；baseline_statistic[mean/median/previous_period] |
| group_concentration | CR5=前五净额/全体净额；HHI=Σ份额²，未乘10000 | 完整分组和期间，正总额；负净组时经典HHI为空；跨期先合并成员再平方 | seven_operations；concentration_reaggregates；declines；negative_net_group |

百分比列的isPercent=False表示原始比例小数；0.1表示10%，不能再次当成0.1%。metadata中的期间、单位和排名范围也是结果契约的一部分。

## 2. 原始材料与实现链路

### 实际检查到的材料

- deploy/agentos/reporting/reporting_profiles/hospitals/ruijin.json:8起的measureSemantics，包含字段身份、单位、可加维度；这里只能证明仓库登记内容，不能证明原业务定义已经获责任人确认。
- profile/models.py:204起的EffectiveMetric及ratio定义约束，支持登记的分子分母和零分母策略。
- hospital_operation/deterministic_analysis.py:262的原始CSV读取，271的精确scope过滤，920的实际观测期间聚合。期间由输入行产生，没有在此函数中补缺期零。
- scripts/fixtures/standard_supplemental_benchmark.csv及配套JSON是人工性能样本，未把它们当业务真实明细。本次手工样本原始字节直接保存在新增测试中。
- standard_supplemental.py:1324核对服务器物化querySql/sqlHash，只信顶层AND中的直接等值范围约束；JOIN、OR和自由文本不能替代范围授权。检查了实际解析实现及相关回归。

未读取生产数据库、真实报告运行的冻结明细、真实查询参数/执行计划或业务责任人签认原件。仓库hospital_operation/schema.py仅是Pydantic基础模型，不是源库DDL。没有使用.env中的凭证，不将合成运行轨迹标成生产实测。因此尚不能判断真实取数是否重复连接、指标原始定义是否合理或真实业务结论是否成立。

### 从路由到证明

1. standard_supplemental.py:1431的catalog以冻结父事实、数据集列和请求窗口构造有界候选；候选缺席不等于算子不支持，仍有显式spec路径。
2. analysis_item_workflow.py:1750起的预检绑定字段、可加性、期间角色、日历、比率登记和scope；1818的supported拒绝非sum及累计策略；1864匹配日历窗口，1880起核对比率有序操作数，1930起核对scope，1960起核对身份。
3. analysis.py:3833的运行时回调使用3224的_read_identity_bytes检查实际长度和sha256；3950附近从父事实取总额、单位、期间与分母换算，不能使用模型自报总额。
4. standard_supplemental.py:427执行授权计算，885读取/筛选行，964至1319实现各公式与对账。多处复用deterministic_analysis.py的additive_group_totals。
5. standard_supplemental.py:822构建完整总体证明，仅支持group_summary且有单位、无未投影查询scope等条件。无法签完整性不代表结果必须被丢弃。
6. analysis.py:4024尝试附加证明，失败捕获后继续；4051登记请求及证明，4057起验证证据并经3296的写入/读回身份检查保存。相关运行时回调回归已执行。
7. trace/table_sources.py:448起验证下游总体引用。其成员检查使用非空字符串条件，未使用strip，故不能独立消除此处空格成员问题；本次没有执行真实报告端到端下载链路。

低层run_standard_supplemental的输入契约明确要求调用方已完成父事实与期间授权。直接调用它成功不能证明生产预检会接受相同请求。下述发现按层级标注。

## 3. 发现、反例及最小建议

### F1：空格归属获得完整总体证明（已证实缺陷，优先处理）

复现节点：test_population_proof_must_not_certify_whitespace_only_member。

原始CSV：

~~~csv
period,department,amount
2025-01,A,60
2025-01,   ,40
~~~

sha256：7915195e41c8d655cad175cf638435f5fdefc4fdfc0c33639f265392018bdfe9。
请求group_summary、本期2025-01、parentTotal=100、元、month；父事实绑定同一CSV哈希和期间。

独立预期：空白成员没有可解释业务归属，不能为“已归属的完整总体”签证。实际：rows为A=60、三个空格=40，总额100闭合，warnings=[]，members包含三个空格，invalidRowCount=0，completePopulation=True。

原因：_read_rows:926附近只检查dimension is None；build_standard_population_proof:854附近只以warnings和复算一致性为条件。对照集中度:509明确使用name.strip()判断未知归属，说明现有模块内对空白归属处理不一致。

影响：不应依据该证明声称所有成员均已具备有效归属。已在证明函数层复现，下游静态检查未发现能拒绝空格的条件；未声称已复现真实报告业务结论。

建议：保留原始键和值，不自动trim合并名称；在完整性判定中拒绝空白标签，对计算产生软告警，仅不签该完整性证明。计算表和已生成文件仍保留，不新增发布阻断。

### F2：零父事实可以掩盖无观测月份（已证实函数层防御缺口，生产可达性未证实）

复现节点：test_population_proof_must_not_infer_missing_month_from_zero_parent。

CSV只有2025-01,A,100；哈希41069afed354aaf82075bb3a422f9c199ca4e6d4105f2a2ce551b0d777ae435c。
请求1—2月；父事实period_values为1月100、2月0，字段/单位/scope/哈希均一致。

独立预期：无行的2月与明确观测到零不同，缺少覆盖证据时不为两个月签完整总体。实际：无告警，completePopulation=True，periods包含1—2月，selectedRowCount=1。

原因：证明检查父事实期间集合与请求相等，但未验证选中原始行确实覆盖请求期间。

证据边界：本例主动注入不一致父事实。正常_period_values:920仅从原始行生成期间，未发现会凭空生成2月零的证据；不能将本例上升为已证实的正常生产路径漏洞。

建议：证明层独立核对期间覆盖；若业务允许零行代表真实零，必须有独立覆盖契约，不能仅用parentTotal或父事实零值推断。无法证明时只撤回证明并软告警。

### L1：共同聚合依赖导致一致性校验盲区（故障注入证实的架构限制）

复现节点：test_population_proof_cannot_detect_common_aggregation_fault。
正常样本A=60、B=40，独立Decimal预期保持60/40。仅在测试期间将共同聚合结果替换为A=40、B=60，保持成员和总额100不变。

实际：金额与独立基准不一致；所有总额对账通过；生产计算和证明复算使用同一聚合函数，仍签completePopulation=True。monkeypatch在用例结束自动恢复，未改生产文件。

这不证明真实聚合器当前有该错误，证明它不是独立正确性判据。应保留本次独立基准作为回归，不为每次运行重新实现另一套生产聚合引擎。

### L2：总额、比率及统计量的解释边界

- A=60/B=40与A=60/A=60/B=-20总额均100；输出分别60/40与120/-20。独立基准能区分，单看总额无法证明业务行唯一；需要上游行键、连接基数或业务定义，不能擅自去重。
- 同组1/1、9/99必须得到10/100=0.1，已通过。分母值更大的行应有更大权重，行比率简单平均约0.54545会改变结论。
- 分子100/分母invalid与分子invalid/分母50可各自汇总为100、50，双总额闭合且当前ratio=2，但带无效数据告警。它只表示各自有效操作数的比值，不能当作同一完整观测总体的已验证比率。业务是否要求同行有效须由指标定义确定。
- A基准(0,0,100)、B基准(0,100,0)，各组中位数均0，总体中位数100；本期各50，则组变化各50而总体变化0。实现保留差额、空贡献和软告警，属于正确处理，不能为了通过对账强行平衡。
- 负基数从-20到-10，signed变化率=-50%，absolute=+50%；两种算法均有显式契约，报告解释必须说明选择，不能按正负号直接判断改善或恶化。
- CR5使用净额，有负净组时可超过1；经典HHI拒绝负份额。本次验证负组场景HHI为空，未把净额指标称为概率分布。
- 缺失月份与真实零分开保留；期间总额为零的对账可能仍通过，必须结合行覆盖和告警。小额有限数验证不能证明极大数值、溢出或消减误差全部受控；现有浮点容差为max(1e-9,1e-12×最大绝对值)。

## 4. 独立证据与测试记录

独立预期来自手写常量、csv.DictReader和Decimal；不使用生产的期间解析、单位换算、分组求和或对账函数计算预期。两个性质测试均采用settings(max_examples=30, derandomize=True, database=None, deadline=None)，共60个确定性生成样本：

- 行序不变、分组与Decimal一致、行分区分别执行再合并等于整体执行。仅对可加有限整数金额适用。
- 分母按1、10、10000缩放后，登记换算还原的比率与Decimal一致。仅验证显式换算比例，不代替业务单位登记验证。

故障注入覆盖同总额成员替换、期间篡改、scope变化、哈希变化：均拒绝完整证明。共同依赖故障注入特意展示校验盲区。正常算例逐单元核对数值、空值、顺序、排名、告警与JSON有限性。

环境：Python3.12.3；pytest9.1.1；Hypothesis6.170.5；Polars1.43.2；Pydantic2.13.5；sqlglot28.10.1；Agno3.1.2。使用现有.venv，无安装或升级依赖。

### 已执行命令与结果

所有命令从上述worktree根目录执行；PY表示/home/junge/pros/smart_reporting/.venv/bin/python。

~~~bash
# 基线（未改生产或测试时）
$PY -m pytest -q smart_reporting/reporting/tests/test_standard_supplemental.py smart_reporting/reporting/tests/test_standard_supplemental_period_comparison.py smart_reporting/reporting/tests/test_standard_supplemental_period_ratio.py smart_reporting/reporting/tests/test_standard_supplemental_concentration.py smart_reporting/reporting/tests/test_standard_population_proof.py smart_reporting/reporting/tests/test_standard_supplemental_boundaries.py
# 124 passed，15.51s，退出0；依赖弃用+缓存只读告警

# 最终新增验证
$PY -m pytest -q -o cache_dir=/tmp/standard-supplemental-depth-pytest smart_reporting/reporting/tests/test_standard_supplemental_independent.py
# 34 passed / 2 failed，18.61s，退出1；两个失败对应F1/F2

# 独立的路由、零分母、基准、领域口径和证明登记回归
$PY -m pytest -q -o cache_dir=/tmp/standard-supplemental-depth-regression smart_reporting/reporting/tests/test_standard_supplemental_routing.py smart_reporting/reporting/tests/test_standard_supplemental_zero_denominator.py smart_reporting/reporting/tests/test_standard_supplemental_generic.py smart_reporting/reporting/tests/test_ruijin_six_domain_semantics.py smart_reporting/reporting/tests/test_population_contexts.py
# 149 passed，13.43s，退出0

# 运行时回调需在允许异步线程回执的执行环境中运行
$PY -m pytest -q -o cache_dir=/tmp/standard-supplemental-depth-callback smart_reporting/reporting/tests/test_standard_supplemental_artifact.py -k single
# 1 passed / 32 deselected，9.27s，退出0
$PY -m pytest -q -o cache_dir=/tmp/standard-supplemental-depth-artifact smart_reporting/reporting/tests/test_standard_supplemental_artifact.py -k 'not single'
# 32 passed / 1 deselected，8.86s，退出0

/home/junge/pros/smart_reporting/.venv/bin/ruff check --no-cache smart_reporting/reporting/tests/test_standard_supplemental_independent.py
# All checks passed
~~~

既有依赖imghdr弃用警告来自第三方visions。初次写入测试时发生字符串换行收集错误，未执行测试，修正后结果如上。中间版本新增测试31通过/1失败；补齐反例后才得到最终34/2。一次运行时批次在4个用例后被人工中止（退出130），单例沙箱内45秒超时（退出124），均未计通过；同一单例经批准在沙箱外9.27秒通过，剩余32例随后同环境通过。不把超时误报为实现缺陷。未运行或重复完整测试。

### 正常样本身份

新增测试文件sha256：8289b32ecee12cc09f3e546d77c07f19965f04d298cc4dedfaad366778441d34。

| 样本 | CSV sha256 |
|---|---|
| group_summary / group_period_series / group_concentration | a794c3c007aa0422bad1cd3a8b71f9cc947e9384717edf2a772ce4e309924622 |
| cross_group_summary | f7ece86209dcecf0710a437d457a051ef09fea4b4e9b6be357868492939ebc76 |
| period_comparison | 1ca7e88010e6b07323fc5233d6f3fc599aae09a15a0aafd4a572bf3791ee2bb7 |
| group_ratio | 210d238b42fce6b85ab72e78c4c7c59e702ed961d84dd2ac11a366ef1d59f2dc |
| group_period_comparison | b425f25bc5e3b3212fde634d572895b56f7e7ca95448911ab63b246728e2699c |

## 5. 验收与后续最小改动

已交付七类手算和边界验证、性质测试、身份故障注入、共因故障演示、两个未掩盖失败、公式契约和复现记录。306项现有回归通过，34项独立验证通过，2项审查契约失败。公开接口无新增。

第三方可在相同基线和测试文件运行以上命令复核。要证明真实业务结果，还需指标责任人定义、原始业务行键/源库DDL、实际SQL与参数、真实冻结明细和覆盖记录；这些不在本次已取得证据范围。

建议优先修F1；随后按父事实信任边界决定F2是否追加覆盖核验；L1保留独立回归即可，不扩大为双引擎。所有修复只影响告警/证明资格，保留计算表及真实差额，不用验收失败raise终止下载签发。当前任务保留审查分支/worktree和失败测试供复核，不自动合并，也未修复生产缺陷。
