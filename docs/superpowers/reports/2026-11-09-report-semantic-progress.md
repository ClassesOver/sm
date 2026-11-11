# 智能报告语义闭环实施记录

日期：2026-11-09。目标仍为实施计划第5节及其前置T1–T9，尚未闭环。

工作区：`/home/junge/.codex/worktrees/68d8/smart_reporting`；基线HEAD `7ef25eb1`。
管理后台未提交基线详见`2026-11-09-semantic-workspace-baseline.json`。Word/Excel并行改动未带入，原目录保持原实现。

| 任务 | 状态 | 已有证据与缺项 |
| --- | --- | --- |
| T1 | in_progress | 合成CSV/4项独立oracle、原材料hash、场景清点、38例manifest、20正例+4无答案检索标签已建；外部源码/许可/测试审计仅部分取得；真实pgvector/embedding及业务签认未完成 |
| T2 | code_verified | 新严格类型、17张组织外键表、10类不可变触发器、0009迁移及指标草稿CAS/审计已实现；独立提交/最终审查仍待完成 |
| T4 | in_progress | 原件持久化、受限multipart HTTP、修订审核、lease worker及应用装配已实现；解析、审核、索引ready分离；索引阶段交由T5验证 |
| T5 | in_progress | 隔离真实PgVector配合成向量协议探针及索引适配已有定点验证；发布集合、权威检索回执及真实中文召回未完成，不开放生产业务检索 |
| T3 | in_progress | 指标/口径草稿、列表、发布、精确版本读回、默认CAS、结构化对比、退役及影响分页已有隔离定点验证；生产路由未装配，反馈/报告切换仍待完成；T5真实中文检索未验收 |
| T6 | pending | 确定性SQL计算、数据就绪评估及实际结果登记 |
| T7 | pending | 新报告依据工作流、停旧、恢复、重算、签发回归 |
| T8 | pending | 管理/编辑器界面及浏览器验收 |
| T9 | pending | 38项跨层验收、真实服务、切换与联合备份演练 |

## 本轮验证事实

均为定点测试，未运行完整项目套件。PG每次新建唯一semantic_test_*库，finally dropdb，命令输出确认清理成功。

- test_semantic_oracle.py：4 passed。独立原始行验证63.33%而非70%、去重/退款、零分母与累计重置。
- test_semantic_models.py及test_semantic_identity_limits.py：14 passed。精确版本、组织、期间、无值状态、问题覆盖、证据支持、纠错关闭与字段长度。
- test_semantic_assets_persistence.py：6个节点均已定点通过。组织依赖、不可变、CAS、审计回滚、旧字段/伪造身份拒绝、非法输入在SQL前422。失败修复仅复测受影响节点。
- test_management_migration.py：1 passed。0005升级到0009、重复head、旧账号/目录/运行记录保持原值；新表与触发器存在。
- test_business_document_parsing.py：14 passed。中文Markdown、DOCX正文/表格、PDF物理页及原始数字、扫描/空PDF、伪类型、路径与201页限制。
- 新文件ruff定点检查通过；git diff --check通过。第三方visions的imghdr弃用提示仍在，未改无关依赖。

上述39个定点测试不是38项业务验收案例通过。cases.json仍为not_run。

## 审查发现及已修复

- 指标ID长于DB字段时原模型未拦截，已在进入存储前限制；恶意对象型ID曾触发503，改为先做严格结构验证再查询，现为422。
- 纠错引用不能仅限指标：制度修订也有精确资产类型/版本及回归证据。
- Agno PDF reader会把页首业务数字当页码删除。真实反例先失败，定位适配现保留pypdf提取文本与物理页，未修改依赖包。
- Agno DOCX reader不保留表格/定位，使用同一python-docx依赖作定位适配；嵌套表格明确拒绝。页眉/页脚/脚注等仍需登记支持边界，不能宣称全部DOCX结构已验收。

## T4后续实施证据（2026-11-09）

- 原件服务层12个唯一节点已定点通过：上传幂等、跨组织、审核CAS、租约抢占、失败显式重试、审计回滚、响应丢失读回，以及原件缺失/篡改/符号链接、读取/解析期间撤销。
- HTTP 4个唯一节点通过：鉴权/CSRF、真实大于64KiB上传、20MiB与流式封套限制、应用路由装配及后台解析/原件回读。
- worker 5个节点通过：启动/替代实例恢复、失败不自动重试、长解析续租、关闭后过期重领、管理事务串行防止续租身份被覆盖。并发测试曾未考虑既有advisory lock而等待，修正调度后通过；未改变现有事务锁。
- DOCX页眉/页脚/脚注及正文内容控件不再静默漏读，标需要转录，不能审核为完整依据。4个新增节点通过，普通DOCX相关节点定点回归通过。脚注反例暴露lxml命名空间差异，已按限定标签迭代。
- parsed状态CHECK修改后，0005→0009及重复head迁移已重新验证，1 passed。
- Ruff知识模块/服务/API/worker/相关测试通过。PG测试均在唯一临时数据库执行并确认清理，未执行全套测试。
- 上述结果不是38例业务验收完成；T5真实索引、工作流和UI仍未完成。

## 接续实施入口

1. 完成T1剩余源码/测试/许可审计与真实embedding/中文召回；真实PG加固定非语义向量的Agno协议探针已完成，不能替代业务检索验收。
2. T4原件、HTTP及生命周期worker已接入；索引构建/验证ready由T5完成，不把parsed当ready。
3. 独立pgvector:pg16容器协议探针已确认组织/集合前过滤、幂等与故障保留；Knowledge故障可表现为空结果，T5需明确故障回执。
4. DOCX正文之外未支持内容显式需要转录，不宣称全格式无损解析。
5. 旧Profile调用尚待T7全部替换，不能将当前阶段称为不兼容切换完成。
6. 接续T5→T3→T6→T7→T8→T9；已生成且可核验的PDF/Word非阻断签发契约不可破坏。

当前尚未达到工程、业务或上线完成条件。目标保持active；没有用户输入阻塞，外部探针缺项仍有其他独立工程可继续。

## T5索引适配实施证据（2026-11-09）

- 新增business_knowledge/index.py，复用Agno FixedSizeChunking/PgVector；只覆写空白清洗以保留逐字原文。组织/构建/文档过滤通过Agno DSL在同一SQL的排序/LIMIT前执行。
- 11个唯一索引节点已定点通过：原文与隔离、幂等/冲突、两类embedding失败、查询故障/缺表、空向量损坏、回执恢复与长引用、并发内容冲突、单次过滤查询、embedding身份变化，以及取消等待者。改变代码后只复测受影响节点，未运行项目全套。
- 取消反例曾使数据库锁等待占住清理；已在本次唯一隔离库内取消对应等待语句并确认数据库清理。该次117秒结果不作为取消时效证明；改用try-advisory-lock及既有complete_cleanup后，取消与并发两节点6.41秒通过，无外部干预。
- 每个回执携带精确元数据清单；向量存在性/维度/有限值、原文及manifest均校验。回执属于内部派生身份，不作为客户端授权凭据。
- 本层仍未接入发布、当前授权和适用期复核；不代表T5或38项业务验收完成。

## T5发布/检索服务接续证据（2026-11-09）

- 新增business_evidence.py、business_evidence_api.py及business_knowledge/retrieval.py。发布绑定已审核精确修订，构建前核对原件身份，索引外部执行后短事务再次核对修订状态；创建不可变集合、成员、ready状态与审计同事务。request_id派生稳定发布身份，提供GET按requestId读回；不自动重试发布。
- 索引12个唯一节点已定点通过；新增结果转换故障反例先失败，适配层以实际SQL返回行数核对Agno结果，避免吞错后误报no_match。
- 发布/检索服务14个节点通过。磁盘曾耗尽，apply_patch写入使本次新测试文件截断；只清理本任务3个临时测试目录后恢复全部用例，并重跑受损文件确认14 passed。未清理其他项目文件。
- 覆盖审核/索引失败不发布、审计回滚、构建/查询期间撤销、组织隔离、过期/历史不可知/指标/项目适用性、缓存引用篡改/撤销、提交响应丢失、真实空结果及原件缺失。
- 查询索引前后都按当前允许修订过滤；已撤销成员的解析正文在管理SQL层置空，索引完整性读取也限于允许修订，不能为了校验整集合而读回撤销正文。
- HTTP4个唯一节点通过，含鉴权/Origin/CSRF/严格输入、发布/读回/预览、跨组织拒绝和实际应用装配。应用当前显式无索引backend，返回503；尚未配置生产embedding或加入pgvector部署依赖，不能称生产检索已开放。
- 服务侧缓存复核已实现，但T7普通报告修订授权/恢复接入尚未完成；规则/背景冲突解释和中文召回仍需后续验收。

## T3独立指标基础接续（2026-11-09）

- 指标发布固定精确依赖、组织身份、草稿CAS和不可变版本；审计同事务。依赖不存在/跨组织/自身循环拒绝；业务单位/粒度疑点返回逐指标unavailable issue，不作为全局发布异常。保存与发布不触碰口径或默认绑定。
- 管理服务5个唯一节点通过：精确分母不漂移、缺依赖/自身拒绝、竞争/审计回滚、单位告警及响应丢失读回。独立HTTP路由2个节点通过：会话/CSRF/旧字段拒绝、路径身份、发布、读回、组织隔离和分页。
- 为复用定义级检查，将validate_policy内部图校验提取为validate_metric_graph；原语义模型13个节点定点回归通过。未运行完整项目测试。
- metrics_api.py尚未加入应用生产路由，按计划待T7切换；T3整体及T5真实业务检索尚未完成。

## T3口径、退役与影响接续证据（2026-11-09）

- 新增statistical_policies.py、statistical_policy_api.py、semantic_retirements.py。口径引用同组织真实已发布制度集合及精确指标依赖；草稿CAS、发布、审计及默认绑定分别事务化。发布不改变默认，默认竞争409；写响应丢失可GET读回。
- 口径服务10个唯一节点已定点通过：发布/默认分离及CAS、跨组织/缺指标拒绝、结构化预览、退役指标传导、退役记录幂等/冲突/审计回滚、同公式改名换版不误报计算变化、发布审计失败及默认丢响应、撤销背景拒绝及读回、默认/报告依据影响分页、语义告警在默认读回保留。
- 口径HTTP5个唯一节点已定点通过：会话/Origin/CSRF/服务端身份字段拒绝、发布/分页/默认读回、受保护退役、精确版本影响查询、退役历史版本及替代建议读回。
- 指标新增退役约束与精确版本读取；传递依赖退役阻止新发布，历史定义保持原值。指标服务7个、HTTP3个唯一节点均已通过。受影响组合11 passed及详情读回/退役组合4 passed；只复测触及节点，未运行完整项目套件。
- 业务单位疑点仍可发布，受影响指标unavailable issue在默认读取保留；不把业务疑点变成全局发布异常。背景安全撤销不允许重新绑定，已有绑定保留身份和具体中文告警。
- 影响查询读取同组织精确默认/ReportBasis引用并服务端分页，不用加载数量冒充总数；测试登记的basis行只用于影响SQL验证，不代表T7工作流实现。
- Ruff定点检查及git diff --check通过；隔离数据库每次唯一创建并finally清理成功。仅第三方imghdr弃用警告。新指标/口径路由未装配生产，真实中文embedding、报告接入及UI仍未验收，T3整体不标完成。


## 2026-11-11 台账恢复说明

磁盘耗尽时非原子重写导致本工作树增量台账丢失。当前恢复以主工作区2026-11-09原始台账为基线，以下从现存证据目录重建索引；不宣称逐字恢复丢失的过程描述，也不把证据目录存在视为全部要求通过。代码、计划、测试及证据文件未因本次台账故障被清除。完整目标仍是实施计划§5及T1–T9，尚未完成。

### 现存证据索引（恢复记录）
- `artifacts/2026-11-10-knowledge-citations`；需逐项检查实际回执。
- `artifacts/2026-11-10-registered-metric-chart`；需逐项检查实际回执。
- `artifacts/2026-11-10-registered-workbook`；需逐项检查实际回执。
- [新修订文档装配技术证据](artifacts/2026-11-10-revision-document/README.md)；需逐项检查实际回执。
- [新修订文档渲染技术证据](artifacts/2026-11-10-revision-document-render/README.md)；需逐项检查实际回执。
- `artifacts/2026-11-10-revision-native-section`；需逐项检查实际回执。
- [新修订PPTX技术证据](artifacts/2026-11-10-revision-pptx/README.md)；需逐项检查实际回执。
- [新修订XLSX技术证据](artifacts/2026-11-10-revision-xlsx/README.md)；需逐项检查实际回执。
- `artifacts/2026-11-10-snapshot-verification`；需逐项检查实际回执。
- [新报告默认背景集合的明确选择](artifacts/2026-11-11-background-default-ui/README.md)；核验脚本：`verify.py`。
- [C02精确纠错回归与C37默认依赖退役](artifacts/2026-11-11-c02-managed-ratio/README.md)；需逐项检查实际回执。
- [C02正式执行率进入四格式原生交付](artifacts/2026-11-11-c02-native-formats/README.md)；需逐项检查实际回执。
- [C02 原生报告与真实PG浏览器关闭](artifacts/2026-11-11-c02-postgres-browser/README.md)；核验脚本：`verify.py`。
- [C02原70报告到公开纠错队列及新63.33报告](artifacts/2026-11-11-c02-public-flow/README.md)；核验脚本：`verify.py`。
- [C02 四格式正式关闭验收](artifacts/2026-11-11-c02-resolution-formats/README.md)；核验脚本：`verify.py`。
- [原件撤销前登记影响核对（2026-11-11）](artifacts/2026-11-11-document-revocation-impact/README.md)；核验脚本：`verify.py`。
- [制度依据目录选择与精确原文预览](artifacts/2026-11-11-evidence-catalog-ui/README.md)；核验脚本：`verify.py`。
- [制度与背景集合明确发布及恢复](artifacts/2026-11-11-evidence-release-ui/README.md)；核验脚本：`verify.py`。
- [C37 PPTX/XLSX 历史报告依据与下载](artifacts/2026-11-11-historical-report-native-formats/README.md)；核验脚本：`verify.py`。
- [C37 指标退役后历史报告浏览器验收](artifacts/2026-11-11-historical-report-retirement/README.md)；核验脚本：`verify.py`。
- [解析失败显式重试与任务状态恢复](artifacts/2026-11-11-ingestion-retry-ui/README.md)；核验脚本：`verify.py`。
- [历史知识截止时间的公开请求与检索边界](artifacts/2026-11-11-knowledge-cutoff/README.md)；核验脚本：`verify.py`。
- [业务知识原件目录和审核入口](artifacts/2026-11-11-knowledge-review-ui/README.md)；核验脚本：`verify.py`。
- [原件上传、新修订与原请求恢复](artifacts/2026-11-11-knowledge-upload-ui/README.md)；核验脚本：`verify.py`。
- [管理工作台报告问题裁定证据](artifacts/2026-11-11-management-issue-reviews-ui/README.md)；需逐项检查实际回执。
- [指标冲突分组核对与明确采纳（2026-11-11）](artifacts/2026-11-11-metric-conflict-resolution/README.md)；核验脚本：`verify.py`。
- [指标编辑初步入口验收](artifacts/2026-11-11-metric-editor-ui/README.md)；核验脚本：`verify.py`。
- [指标已发布字段目录选择（2026-11-11）](artifacts/2026-11-11-metric-field-picker/README.md)；核验脚本：`verify.py`。
- [指标定义及精确版本影响入口](artifacts/2026-11-11-metric-impact-ui/README.md)；核验脚本：`verify.py`。
- [指标发布及依赖选择验收](artifacts/2026-11-11-metric-release-ui/README.md)；核验脚本：`verify.py`。
- [指标退役替代建议验收](artifacts/2026-11-11-metric-replacement-ui/README.md)；核验脚本：`verify.py`。
- [指标退役管理操作](artifacts/2026-11-11-metric-retirement-ui/README.md)；核验脚本：`verify.py`。
- [新口径首次公开交付技术样例](artifacts/2026-11-11-policy-adoption-public-flow/README.md)；需逐项检查实际回执。
- `artifacts/2026-11-11-policy-adoption-ui`；需逐项检查实际回执。
- [统计口径冲突逐项核对与明确采纳（2026-11-11）](artifacts/2026-11-11-policy-conflict-resolution/README.md)；核验脚本：`verify.py`。
- [场景默认口径调整与未知结果核对](artifacts/2026-11-11-policy-default-ui/README.md)；核验脚本：`verify.py`。
- [统计口径编辑发布与规则维护验收](artifacts/2026-11-11-policy-editor-ui/README.md)；核验脚本：`verify.py`。
- [口径筛选、关联键及水位字段目录选择（2026-11-11）](artifacts/2026-11-11-policy-field-picker/README.md)；核验脚本：`verify.py`。
- [新口径准备故障后的公开恢复技术样例](artifacts/2026-11-11-policy-recovery-public-flow/README.md)；需逐项检查实际回执。
- [新口径准备恢复组件验收](artifacts/2026-11-11-policy-recovery-ui/README.md)；需逐项检查实际回执。
- [统计口径完整发布前后差异（2026-11-11）](artifacts/2026-11-11-policy-release-diff/README.md)；核验脚本：`verify.py`。
- [退役口径的显式替代版本建议](artifacts/2026-11-11-policy-replacement-ui/README.md)；核验脚本：`verify.py`。
- [统计口径版本影响与退役界面](artifacts/2026-11-11-policy-retirement-ui/README.md)；核验脚本：`verify.py`。
- [业务预期签认界面验收（2026-11-11）](artifacts/2026-11-11-report-business-approval-ui/README.md)；核验脚本：`verify.py`。
- [回归预期的业务来源与显式签认](artifacts/2026-11-11-report-business-expectations/README.md)；核验脚本：`verify.py`。
- [关闭准备中的显式签认当前核验](artifacts/2026-11-11-report-current-business-approval/README.md)；核验脚本：`verify.py`。
- [回归证据当前可复核检查](artifacts/2026-11-11-report-current-regression-evidence/README.md)；需逐项检查实际回执。
- [C36 完整报告 Editor 反馈至原生修复报告](artifacts/2026-11-11-report-feedback-native/README.md)；核验脚本：`verify.py`。
- [关闭准备：精确回归计算到正文或冻结附表](artifacts/2026-11-11-report-issue-content-binding/README.md)；需逐项检查实际回执。
- [关闭准备：新报告原生完成与当前文件交付](artifacts/2026-11-11-report-issue-delivery-checks/README.md)；需逐项检查实际回执。
- [问题到正式修复版本的关联证据](artifacts/2026-11-11-report-issue-fix-links/README.md)；需逐项检查实际回执。
- [管理端正式修复版本选择](artifacts/2026-11-11-report-issue-fix-picker/README.md)；需逐项检查实际回执。
- [真实PG管理浏览器验收](artifacts/2026-11-11-report-issue-postgres-browser/README.md)；核验脚本：`verify.py`。
- [管理端回归核验与历史](artifacts/2026-11-11-report-issue-regression-ui/README.md)；需逐项检查实际回执。
- [报告问题的实际快照回归核验](artifacts/2026-11-11-report-issue-regressions/README.md)；需逐项检查实际回执。
- [正式关闭界面验收](artifacts/2026-11-11-report-issue-resolution-ui/README.md)；需逐项检查实际回执。
- [当前证据核验后的正式关闭（2026-11-11）](artifacts/2026-11-11-report-issue-resolutions/README.md)；核验脚本：`verify.py`。
- [报告反馈与裁定技术证据](artifacts/2026-11-11-report-issue-reviews/README.md)；需逐项检查实际回执。
- [报告问题反馈界面证据](artifacts/2026-11-11-report-issues-ui/README.md)；需逐项检查实际回执。
- [关闭准备：原件当前可读与新依据可信父链](artifacts/2026-11-11-report-resolution-evidence/README.md)；需逐项检查实际回执。
- [从精确原件修订找回解析任务](artifacts/2026-11-11-revision-task-directory/README.md)；核验脚本：`verify.py`。
- [工作簿重复模块优化](artifacts/2026-11-11-workbook-budget/README.md)；核验脚本：`verify.py`。

### 最近已验证增量（从本轮实际回执恢复）

- C37 document：退役rate/1后完整Markdown Editor仍显示旧70/原版本/Basis，原PDF/Word大小及SHA-256不变；四宽无溢出、axe严重关键零。1 passed（88.19秒），清理成功。关系图原生辅助名称修复，受影响页面109 passed（6.64秒）。证据 historical-report-retirement。
- C37 PPTX/XLSX：新增两格式节点2 passed（68.47秒），清理成功；同样的历史Markdown Editor依据及原文件真实下载核验通过。这不证明原生幻灯片画布/工作簿网格。证据 historical-report-native-formats。
- C36：完整Editor真实对象反馈，POST200后丢响应，刷新明确GET读回，仅1次提交；同随机issueId进入管理HTTP修复发布/公开采用202/Agno队列，产生63.33新PPTX，旧70不变，反例70失败/63.33通过，总SQL4次。1 passed（36.67秒），清理成功。证据 report-feedback-native。后续管理发布/采用/回归仍为HTTP客户端，并非全程浏览器。
- 本轮失败日志保留：缺入口红例；反馈浏览器关闭前仍有只读route.fetch，已以unrouteAll(wait)修复并定点通过。Ruff/node语法/diff及证据verifier通过。

### 剩余完整目标

完整C33/C36浏览器、真实模型/StarRocks/中文知识及业务负责人确认、四格式静态图与原生编辑器视觉、进程恢复/资源保留/联合备份、38案例与全§5/T1–T9逐要求审查仍待完成。合成受控模型/DuckDB和目录组件测试不替代真实业务验收；不重写旧版本、不扩权限、不阻断可核验产物下载。无业务数据库/生产签发链/提交/部署变更。


### T7/T8/C36 完整Editor逐题采用新口径及未知响应恢复（2026-11-11）

- 上轮原生格式历史与反馈浏览器为有效进展。本轮缺browser_adoption参数红例后，接入真实已发布候选/差异预检/逐题指标选择和理由/明确确认。真实202后主动丢响应，刷新仅GET读回同一随机requestId/taskId；一次采用POST，不重派发/不重复SQL。反馈也从完整Editor真实提交且未知读回，同随机问题身份继续真实管理HTTP正式修复发布。
- Agno耐久队列生成63.33%实际PPTX，旧70正文/Basis/文件/检查点不变；独立63.33回归通过且70反例失败，总业务SQL4次。最终定点1 passed（40.24秒），隔离PG清理成功。首轮测试读候选过早、后续匹配嵌套两条状态提示，分别以等待真实控件、精确主状态定位修复；未放宽产品契约，失败日志保留。Ruff/node语法/diff通过。
- 实际1440确认截图已查看；证据artifacts/2026-11-11-report-adoption-browser含真实HTTP/请求/任务/旧新文件/回归/截图、manifest及verify.py，离线核验通过。本轮仅反馈与采用为完整Editor浏览器，管理修复发布/回归仍HTTP客户端；不宣称C36全程、四尺寸采用页、真实模型/StarRocks/中文检索或业务负责人确认。
- 其余完整C33/C36、四格式静态图/原生画布视觉、真实环境、恢复保留/联合备份和全§5/T1–T9仍待完成，目标active。无业务库/生产签发链/提交/部署变更。磁盘容量仍紧张，本轮台账写入临时文件fsync后原子替换，现有台账恢复说明保留。


### T7/T8/C36 真实管理页修复指标、发布口径并由报告采用（2026-11-11）

- 上轮完整Editor采用为有效进展。本轮缺browser_repair参数红例后，把同次70报告反馈后的实际修复写入换成完整管理页：明确actual/1÷budget/1与预算project字段，rate草稿CAS1→2及发布2；口径明确rate/2，草稿CAS2→3并预检发布3。保存/发布各1次，不改默认。实际新报告所用完整定义与浏览器发布返回逐字结构匹配，离线verifier核对。
- 同随机问题经完整Editor反馈/丢响应读回、真实管理页修复发布、完整Editor预检逐题采用/202丢响应读回、Agno队列实际63.33%新PPTX；旧70正文/Basis/文件不变，总业务SQL4次。定点1 passed（48.58秒），隔离PG清理成功；Ruff/node语法/diff通过，1440指标发布截图已查看。新增smoke初稿正则传输丢转义导致语法失败，改明确页面glob后复测，日志保留。
- 证据artifacts/2026-11-11-report-management-repair含同次真实HTTP/定义/原始行/查询/问题/回归/实际文件/截图、manifest/verify.py，离线核验通过。问题采纳/修复关联/回归和关闭准备仍HTTP客户端；不宣称C36全程浏览器、四屏宽修复、原生PPTX画布或真实模型/StarRocks/中文知识/业务负责人确认。
- 全§5/T1–T9、完整C33/C36、四格式静态图/原生画布、真实环境与恢复保留/联合备份仍未完成，目标active。无生产行为/业务数据库/签发链/提交/部署变更。进度台账继续临时文件fsync后原子替换，保留恢复说明。


### T7/T8/C36 浏览器采纳问题与关联正式修复版本（2026-11-11）

- 上轮管理编辑发布为有效进展。本轮缺browser_decisions参数红例后，同次完整管理页先采纳随机issueId并记录反例，真实POST200后丢响应/刷新GET核对CAS1→2；发布rate/2和monthly-budget/3后，从正式候选明确选择这两个版本，再次裁定200丢响应/刷新GET核对CAS2→3。共2裁定POST、2未知只读恢复，不自动重试。
- 同问题串联完整Editor反馈、管理采纳/编辑发布/修复关联、Editor采用/202读回、Agno队列实际63.33%新PPTX，原70正文/依据/文件不变，总SQL4次。最终定点1 passed（60.84秒），隔离PG清理成功；Ruff/node语法/diff通过，1440关联读回截图已查看。证据artifacts/2026-11-11-report-decision-browser及manifest/verify.py，离线核验通过。
- 回归登记/后续关闭检查仍HTTP客户端，不宣称C36全过程浏览器、四宽度裁定或业务负责人确认。受控模型/DuckDB非真实模型/StarRocks/中文知识；完整C33/C36、四格式静态图/原生编辑器、真实环境、恢复保留/联合备份及全§5/T1–T9继续未完成，目标active。无生产行为/业务数据库/签发链/提交/部署变更。台账原子替换，保留恢复说明。


### T7/T8/C36 浏览器回归接续合成签认与关闭（2026-11-11）

- 上轮浏览器裁定/精确修复关联为有效进展。本轮新增browser_regressions及连续节点，缺参数红例后，接入同次真实管理页的70负例和63.33独立预期；各POST200后丢响应、刷新明确GET读回，各只提交一次。失败记录保留，通过回归仍not_performed/问题未关闭；随后既有真实浏览器选择独立合成原件、显式签认、核对新交付并关闭，签认/关闭同样各一次提交并验证未知结果只读恢复。
- 同次完整Editor反馈/采用、管理采纳/修复发布/精确关联、Agno耐久队列新PPTX、浏览器回归与合成关闭在真实HTTP/隔离PG串联。新增节点test_c36_browser_regressions_continue_to_signed_resolution最终1 passed（97.71秒），隔离数据库清理成功；原70正文/依据/文件不变，新63.33，总业务SQL4次。回归结果页1440/1280/768/390均无页面溢出、axe严重/关键0，1440/390截图已查看；不是所有步骤四宽度验收，签认/关闭为既有390流程。
- 首轮无障碍检查发现管理按钮加载+悬停对比度2.95。等待网络稳定仍失败；独立真实Ant组件复现opacityLoading=0.65叠加悬停色。先保存红例，仅管理端Button主题改opacityLoading=1，保留加载图标；组件与完整流程转绿。两个失败日志及组件红/绿证据归档，不将失败当作测试噪声。管理构建/TypeScript通过，gzip登录292.8KiB、列表430.8KiB，低于300/500预算；Ruff/Node语法/diff通过，未重复完整项目测试。
- 证据artifacts/2026-11-11-report-regression-browser含实际HTTP/两种预期/原始行/独立合成原件/新旧实际文件/最终关闭/四宽度截图；manifest及verify.py离线核验通过。旧/tmp runner丢失，本轮恢复随机专用pgvector Docker容器创建/销毁脚本并随证据归档，不读取业务.env、不重置业务库。台账继续临时文件fsync+原子替换，保留恢复说明。
- 受控模型/DuckDB合成原始行/协议向量/合成签认不代表真实模型、StarRocks、中文召回或业务负责人批准。PPTX仍为关联Markdown Editor，不证明原生幻灯片画布。C33、四格式静态图与原生编辑器视觉、真实环境、进程恢复/保留/联合备份、38案例与完整§5/T1–T9逐要求审查继续待完成，目标active。唯一生产变更是管理端一个样式token，无提交或部署。


### T4/T5/T7/T8/C33 历史知识进入完整报告与浏览器支持复核（2026-11-11）

- 上轮状态核对未增加实现；本轮继续实际 C33 流程。新增历史背景原件登记/审核/集合发布、原依据公开登记/采用、原生报告生成与完整 Editor 浏览器的三参数节点。集合同时含截止前已知材料与截止后补录材料，实际 plan/content/semantics 只收到前者，采用新口径保留截止时间与背景集合；每组分子SUM/分母COUNT各查询一次，原文和页面校验不增加业务查询。
- 真实发现句末引用指纹绑定空串问题，针对 citation、三类标点、同段/跨段后句建立12组回归；修改本句失效、修改相邻句不失效。相关135项通过；知识支持及非阻断55项通过，原失败日志保留。未放宽缺少观察事实的因果守卫。
- 完整页面失败进一步定位到正式计算Decimal进入来源校验返回，JSONResponse实际500，页面无法得到支持判断。先新增真实精确值/授权/CSRF HTTP回归，3 failed；仅在来源校验返回边界使用Pydantic原生JSON转换，保留精确字符串300.123456789123456789，3 passed（9.44秒）。受影响来源读取、编辑、非阻断下载102 passed（21.69秒）；不重复完整项目测试。诊断保存原也曾因Decimal失败，修复归档序列化后保留该失败记录。
- C33三个完整浏览器节点最终3 passed（136.29秒），隔离pgvector容器清理成功。真实原文支持建议=有依据；真实但无关=待核实；有事件材料但无登记观察事实的因果解释=待核实/registered_observation_unavailable。各组1440/1280/768/390无溢出、axe严重关键0，原文鼠标与Enter展开/收起/重开通过；实际PDF/Word真实HTTP200且SHA/size与登记一致。已查看正例1440/390及因果反例1440截图。数字70为知识fixture，不是C02总体比率正确预期，数字声明仍有数据充分性与语义未核实告警。
- 证据artifacts/2026-11-11-background-report-browser含三组独立正文/实际文件/计算/索引/模型输入/真实HTTP/截图、红绿日志、实现测试快照、manifest与verify.py；离线核验通过。初稿verifier误把两次分子分母查询写成一次，已对照实际SQL修正为两条不同授权聚合，不改实际证据。Ruff/Node语法/diff通过。
- 新发现导出缺口：已读取因果反例实际PDF，总览有总体限制，但正文因果句旁未标逐句待核实。完整Editor正确不能替代导出读者提示。原生fixture来源附录准备仍有report_source_appendix_unavailable，文件可下载但附录完备未验收。下一步应复用既有ClaimSupport/trace渲染投影补齐逐句解释状态，同时保留原正文/引用身份并维持非阻断签发，不以强制固定措辞替代语义消歧。
- 三组使用受控模型、协议向量、DuckDB合成数据，不证明真实模型/StarRocks/中文语义召回/业务负责人批准。生成后编辑及撤销的完整浏览器、四格式静态图/原生编辑器、恢复保留/联合备份、38案例及全§5/T1–T9审查继续未完成，目标active。无业务数据库/生产签发/提交/部署变更。台账继续临时文件fsync后原子替换，保留原恢复说明。


### T4/T5/T7/T8/C33 PDF/Word 逐声明支持提示与非阻断签发（2026-11-11）

- 补齐上轮实际导出缺口：复用当前 ClaimSupport，在同一确定性渲染投影添加推断/建议及待核实/反证标识，不改冻结 Markdown、引用或历史来源哈希，不依赖来源附录开关。首次/新计算修订读取登记索引、原文和文件身份并复核当前知识授权；Editor 导出复用当前正文实际来源校验，失配载荷不继承历史支持状态。
- 投影缺参数红例11 failed后相关29 passed（22.50秒）；首次实际双格式三组3 failed定位为 _load_job 深拷贝载荷未 _store_job。修正写回后正例1 passed（52.53秒）、无关原件与无观察事实因果两负例2 passed（93.60秒），隔离PG清理均成功。实际PDF/Word正文分别显示建议、建议待核实、推断待核实，原文不含新增标签；完整Editor四宽无溢出、axe严重/关键零、实际HTTP字节身份一致。
- 新增HTTP故障注入：展示复核OSError只调用一次，交付 validation.ok=false且保留 claim_support_projection_unknown；两格式实际文件有明确限制说明并继续签发下载。定点1 passed（53.02秒）、清理成功，登记静态签发链。来源身份/预算/报告依据修订失配与当前知识撤回9 passed（10.55秒）；最终非阻断签发/持久化/完成消息/静态守卫16 passed（13.19秒）。受影响集初次90 passed/10 failed/3 deselected，10项测试桩旧job预期修正后仅定点10 passed（13.10秒），不重复全项目测试、不将初次结果写成全绿。
- 已查看实际PDF正例正文、故障提示页及实际Word经LibreOffice转换的正文/落款页；标签可读无截断覆盖。Word落款另起一页在改造前证据同样存在，前后均四页，仍有版式优化空间，未宣称整体视觉验收通过。新增文件Ruff及diff检查通过；HTTP测试原存两处import排序/四处分号lint保留，本次顶端新增import已单独修正。
- 证据 [PDF/Word逐声明支持提示与非阻断下载](artifacts/2026-11-11-claim-support-export/README.md) 含四次独立文件/计算/索引/浏览器/HTTP/文本、前后视觉、红绿及故障日志、源码快照、manifest与verify.py；离线身份及场景核验通过。归档核验初稿对正例尚未引入的projectionFailure字段直接索引，修为缺省false后通过，原始证据未改写。数字70仍为知识合成fixture，不是C02正确总体比率预期。
- 本轮只覆盖PDF/Word；PPTX/XLSX采用独立冻结发现构建，逐解释展示尚待接入。生成后编辑及原件撤销的完整浏览器导出、来源附录完备、四格式含图与原生编辑器、真实模型/StarRocks/中文知识和业务负责人确认、进程恢复/资源保留/联合备份、38案例及全§5/T1–T9逐项审查继续未完成，目标active。无业务库重置、提交、部署；使用临时文件fsync并原子替换保留已有台账恢复说明。


### T4/T5/T7/T8 原生PPTX/XLSX结论支持披露及范围隔离（2026-11-11）

- 上轮PDF/Word逐声明提示为有效进展。本轮检查发现PPTX直接使用发现摘要、XLSX汇总直接使用分析摘要，不能借文档提示证明原生文件同等披露。新增原生整段文字绑定：复用登记索引、来源身份、当前知识授权及质量复核，只有完整声明及章节/分析身份相符才继承当前支持状态；数值相同、相邻句、重复声明身份和被省略的前段/章节语境均不背书。未登记文字显示支持关系待核实，不按固定业务词猜类型。
- PPTX页文字与逐页validation.claimSupport同源；XLSX结论格提示与来源包逐格绑定同源，数值/公式/精确文本保持原样。新增读取/复核故障写native_claim_support_unavailable、validation.ok=false，实际文件仍生成登记和HTTP下载；结构验收ok=true不表示声明supported或业务批准。
- 原生缺口红例3 failed及工作簿参数红例3 failed后，相关渲染/正式工作簿/静态守卫35 passed（17.99秒）。范围/省略语境红例4 failed后相关投影28 passed（8.76秒）；自查同一claimId多subject歧义反例1 failed后拒绝继承，最终18 passed（8.10秒）。当前知识可用/撤回经文档/原生共享读取及工作簿定点9 passed/30 deselected（9.91秒），不把单元测试代替原生产物验收。
- 正常及新增支持复核OSError的PPTX/XLSX实际生成、签发、ASGI HTTP字节身份共4 passed（55.21秒）；收紧章节/分析绑定后仅复测受影响正常节点2 passed/2 deselected（33.58秒）。故障调用各1次、失败回执及文件提示同时存在，下载不阻断。刷新两个原生格式追加本修订登记清单和支持读取断言，2 passed（90.00秒），包含原报告保留、失响应恢复及真实文件/下载检查，隔离PG均清理成功。均为受控模型/向量、DuckDB原始行和真实隔离PG，不是真实模型/StarRocks/业务批准。
- AGENTS非阻断契约首次66 passed/9 failed/2 deselected（47.78秒）；9项同一旧Editor job测试桩不接受上一轮新增展示字段。新增不可用载荷的精确断言且其他字段仍逐项保持不变，仅定点复测9 passed（9.88秒），失败日志保留，没有重复全项目测试。当前其他改动文件Ruff及diff通过；HTTP文件原存两处import排序/四处分号lint保留。
- 已查看scoped正常文件真实LibreOffice转换的PPTX正文与XLSX汇总截图，支持提示可读且无截断覆盖，63.333…精确小数文本保持。证据 [PPTX/XLSX原生结论支持提示及故障交付](artifacts/2026-11-11-native-claim-support/README.md) 含四组产物/计算/索引/支持回执、前后失败及定点通过日志、视觉、源码快照、manifest与verify.py，离线核验通过。实际PPTX因数据充分性未核实仍显示事实陈述待核实，与当前Editor结果一致；本例无图，不证明含图或原生编辑器视觉。
- 明确剩余：XLSX来源正文当前为计算附表，分析摘要尚无整段声明登记，本轮如实待核实，不把统一提示计为业务知识驱动工作簿叙述完成；支持建议/因果反证进入实际PPTX/XLSX的生成、编辑、撤销仍要补验。四格式编辑撤销后重导出、附录完备、含图/原生编辑器、真实模型/StarRocks/中文检索、业务负责人确认、恢复保留/联合备份、全§5/T1–T9及38案例继续未完成，目标active。无业务库重置、提交、部署；台账临时文件fsync后原子替换，保留已有恢复说明。


### T4/T5/T7/T8 XLSX 摘要声明登记与当前知识撤销（2026-11-11）

- 上轮原生提示为有效进展；本轮落实口径采用及刷新修订 XLSX 的真实分析摘要登记。新增独立不可变摘要文件，绑定 basis/revision/period/section/analysis，进入原检查点和登记账本；实际摘要进入来源 Markdown 与 subject bindings，复用现有正文语义复核、知识回执和当前授权。数值、公式、CSV不改，不把计算成功作为解释支持。直接首次普通XLSX入口仍待接入核验。
- 6项首次单元失败定位声明指纹契约，相关24 passed；修订缺登记红例后，首轮实现误选narrative-outline agent，改为既有section generator及不可用软降级。仅XLSX修订节点最终1 passed（52.75秒），含失响应/恢复、原报告不变、原生文件。结构红例1 failed/1 passed，期间及遗漏绑定红例2 failed/4 passed，加入显式期间和完整声明覆盖。旧检查点写回保留已冻结摘要，另一身份或文件账本覆盖均拒绝。
- 三组完整知识/XLSX首次3 failed：发现initial计算修订与正文交付编号差异导致知识依赖被拒绝，另有逐格回执数量旧假设。修正后3 passed；最终契约更新后，相关原文支持建议、无关材料不支持、缺观察事实因果不支持，加C02正常/复核故障交付共5 passed（79.78秒）。真实管理接口撤销原件后，三组当前Editor/原生支持均unverified且不再使用原件支持引用；冻结正文不变，既有XLSX再次HTTP200且字节同一。
- 前句变化仍能借旧叙述回执的红例1 failed，原生展示追加完整语义回执核对；相关44 passed（10.13秒），只复测受影响完整known节点1 passed（24.82秒）。新增摘要知识登记读取OSError的HTTP故障注入1 passed（22.51秒）：调用1次，索引明确unavailable，实际文件仍生成签发下载。既有SIGNING_CHAIN覆盖登记函数，最终静态守卫1 passed（9.78秒）。上述隔离PG均清理成功。
- 相关正文/来源/状态/签发守卫99 passed/12 deselected；检查点集合另有19 passed/5 failed，5项图谱测试桩缺_metric_planning_context，位于本轮未改函数；保留失败、不改无关生产逻辑或掩称全绿。最初精确HTTP节点遗漏asyncio参数ID为收集失败，不计功能红例；旧“所有XLSX摘要无登记”断言实际失败后改为逐格与Editor实际支持核对。仅受影响集合，不重复完整项目测试。
- 已查看实际XLSX经LibreOffice转换的建议正例与因果反例汇总页，标签可读无截断；现有摘要逐事实行重复及留白仍有版式优化空间，不宣称原生编辑器或整体视觉验收。受影响文件Ruff/diff通过；HTTP原存2处import/4处分号问题保留。证据[工作簿摘要、知识撤销及非阻断下载](artifacts/2026-11-11-workbook-summary-knowledge/README.md)含120份文件身份清单、实际产物/登记/撤销前后/HTTP/故障/红绿日志/源码/截图，verify.py离线核验通过。
- 历史已签发文件保持当时标签，本轮不证明撤销后编辑/新修订重导出。三组70为知识报告合成夹具；C02总体正确预期仍190/300=63.33。受控模型/向量、DuckDB合成行、隔离PG不等于真实模型/StarRocks/中文语义召回/业务批准。直接首次普通XLSX、PPTX知识叙述、四格式编辑重导出、附录、含图/原生编辑器、真实环境/业务确认、恢复保留/联合备份及全计划审查继续未完成，目标active。无业务.env/业务库重置/提交/部署；台账临时文件fsync后原子替换，保留旧恢复说明。


### T4/T5/T7/T8 普通 XLSX 装配摘要登记与声明冲突消歧（2026-11-11）

- 上轮已完成采用/刷新 XLSX 摘要登记，本轮接入普通 execution=None 的 run_report_draft→assemble_report→_render_and_validate→publish_report。共用不可变摘要冻结/恢复；来源正文、索引、原生结论格与当前 Editor 支持同源。修复普通 XLSX 渲染/发布重复+1，实际文件目录、清单、发布与 Editor 修订一致。此测试借用采用夹具准备正式计算/知识，交付修订为5、计算修订initial；不冒称公开首次创建 revision=1 完整入口已验收。
- 同章节正文/摘要依赖保留各自真实 reportRevision，以(section, revision)唯一且receipt仍全局唯一；原生摘要指定analysis时拒借无analysis正文支持。3项红例后相关64 passed。helper缺实现红例后原摘要/恢复15 passed。早期包装器/版本/可视化/import/deliveryFormat测试桩失败和实际XLSX修订、空摘要生产红例分别归档，不混算成生产缺陷证据。
- 首轮采用/普通装配三场景6 passed（89.56秒），真实隔离PG、真实知识原件登记/审核/集合与撤销、原生XLSX、Editor校验、HTTP字节一致；刷新恢复与知识登记OSError签发2 passed（67.04秒）。相关163 passed/1 failed/6 deselected（59.43秒），失败为既有章节测试桩缺allowed_metric_codes，位于未改函数；保留且不改无关逻辑。补充AGENTS HTTP故障/伪造索引/Editor不覆盖旧文导出38 passed（11.42秒），与前述集合有重叠，不累加唯一总数、不重复完整项目测试。
- 按requesting-code-review技能委派同模型独立只读复核，发现正文与摘要拼接可能块重名/超200，以及首尾空白恢复不一致；再确认同blockId+全文导致claimId冲突。红例3 failed与2 failed后，改装配器独立服务端叙述输入，原draft与图表/表格定位不动；仅当前render/index共用确定性声明别名投影，冻结原件/原文/analysisId/指纹/知识回执不改。有效语义回执映射前后校验，失效者不得重新支持；恢复采用既有strip规则。
- 审查修复后摘要/标题/图表/表格装配100 passed（11.05秒）；映射后二次核验及越界补充输入拒绝仅定点6 passed/17 deselected（9.59秒）。最终普通三场景刻意正文使用analysis_001且摘要全文相同，实际触发声明碰撞，断言别名/原ID/上下文hash/当前授权及撤销后旧下载3 passed/3 deselected（54.25秒）。独立最终复核无尚未解决Critical/Important。所有隔离PG清理成功。
- 证据[普通XLSX装配与声明冲突消歧](artifacts/2026-11-11-workbook-standard-assembly/README.md)含171份归档文件身份、前后实际XLSX/正文/计算/索引/撤销/HTTP、红绿日志、源码快照、独立复核和最终实际文件视觉；manifest/verify.py离线核验通过。正例与因果反例汇总页已查看，标签无截断；逐事实重复摘要、留白/期间换行仍需优化，不宣称整体视觉或原生Editor完成。修改文件Ruff/diff通过。
- 三组70为历史知识合成夹具，不是C02正确总体比率190/300=63.33。受控模型/协议向量/DuckDB/隔离PG非真实模型、StarRocks、中文检索或业务批准。公开首次完整入口、PPTX知识叙述、四格式编辑/撤销重导出、完整附录、含图/原生编辑器、真实环境/业务签认、恢复保留/联合备份与全38案例/§5/T1–T9继续未完成，目标active。无业务.env/业务库重置/提交/部署；台账临时文件fsync后原子替换，保留已有内容与磁盘恢复说明。


### T4/T5/T7/T8 空报告首次原生 XLSX 与正式事实发布核对（2026-11-11）

- 上轮普通装配证据借用采用夹具，本轮新建空报告，从真实 runtime.workflow().arun 执行规范化、默认口径/背景冻结、指标选择/计算、受限画像、SQL审核/物化、分析/动态提纲/成稿、XLSX渲染/发布/签发。报告/清单/Editor均revision1，无采用口径API、无采用回执或预置检查点。正常入口保留默认同比；政策不适用的基期仍unavailable、不补零，数据充分性unknown不改为通过。可信CLI身份的原生首跑及ASGI HTTP下载，不冒称公开HTTP首次创建入口已验收。
- 首跑定位实际生产缺口：发布核对仅枚举旧事实数组，误报已登记metricContext.calculations[].results的正式fact未知。复用现有read_fact_document核验正式上下文及依据/回执/版本/期间/单位/重复身份，再纳入原事实集合；存在factId不等于数值/业务验收通过。6 failed/4 passed有效红例后，相关门禁/trace/静态守卫15 passed（9.31秒）。
- 按requesting-code-review技能委派同模型独立只读复核：确认固定测试run_id造成联合库冲突，改UUID并保留空状态断言；另复现提取阶段非标准字段KeyError会丢具体诊断。该反例1 failed/10 deselected后，解析及整份提取统一原except Exception，成功才合并，避免局部错误/部分纳入；相关16 passed（9.37秒），先合法后非标准的整份拒用再定点1 passed/11 deselected（8.58秒）。最终无未解决Critical/Important，Minor已解决。
- 新签发事实读取故障登记到test_http_publication_lineage.py及_SIGNING_CHAIN：只在发布核对注入一次OSError，具体file_unreadable/unknown issue与formalReleaseAllowed=false保留，实际XLSX继续签发并HTTP200下载。最终正常/故障首跑2 passed（40.57秒），同时验证下载哈希/大小/ZIP/source mapping、真实登记文件/摘要/检查点、Editor知识supported、真实管理服务撤销后unverified且不借证据引用、旧正文及历史下载字节不变。隔离向量管理库清理true。
- AGENTS指定产物保留、HTTP溯源故障、Editor导出、完成原因精确节点74 passed/2 deselected（44.32秒）；静态守卫在上述gate集合验证。集合重叠不累加唯一总数，仅本轮受影响集合，没有重复完整项目测试。早期integration漏标、tokenizer/测试模型装配取消、期间/上下文字段/函数映射/CodeMode/候选/工作区读回等测试夹具失败，以及固定run_id联合失败均保留日志，不当作产品红例；生产缺口由独立fact回归确认。
- 证据[首次原生工作流XLSX与正式事实发布核对](artifacts/2026-11-11-first-workbook-workflow/README.md)共70份文件约2.2MB，含两份实际交付/全部源登记文件/回执/知识撤销/HTTP/红绿日志/源码/独立复核及实际LibreOffice转换PDF/汇总PNG；manifest/verify.py离线核验通过。已查看正常/故障首张汇总，标签可读无截断；逐事实重复分析摘要、基期同摘要、留白与期间换行仍需优化，不冒称整体版式、含图、原生Editor或四宽度完成。修改生产/新测试Ruff与diff通过；HTTP大测试文件既有3处import/4处分号问题保留。
- 70为本例明确选择的历史项目均值(0.9+0.5)/2×100，不是C02总体正确值190/300=63.33。受控模型/向量、DuckDB原始合成行与真实隔离PG不等于真实模型/StarRocks/中文检索或业务签认。公开首次HTTP创建、PPTX知识叙述、四格式编辑撤销重导出、完整附录、含图/原生Editor、真实环境/业务确认、恢复保留/联合备份及全38案例/§5/T1–T9继续未完成，目标active。未使用业务.env/业务库重置，无提交/部署；台账临时文件fsync后原子替换，保留先前全部内容及磁盘恢复说明。


### T4/T5/T7/T8 公开 HTTP 首次 XLSX 身份贯穿与非阻断交付（2026-11-11）

- 补齐上一轮明确未完成的公开首次入口：生产 require_workspace_capability + 安装的 Agno 3.1.2 原生 /workflows/enterprise-reporting-workflow-v1/runs，实际工作流从空状态计算、取数、成稿、摘要冻结、签发和交付第1版XLSX，无预置检查点/采用回执。依赖版本和安装路由源码哈希留档，不把ASGI入口测试当真实网络部署。
- 新增HTTP正常/发布事实读取故障两例。101/102正整数组织夹具不放宽验签；向实际scope dependency及原生表单提交伪造数据库/组织/用户/线程，回执和两仓储读回均为可信warehouse/101/7/thread-basis。运行传输类型agentos、配置可信入口http-capability分别核对。
- 缺capability、签名损坏、线程不匹配分别401，具体错误capability_invalid / capability_signature_invalid / capability_thread_mismatch，无报告状态、零业务数据查询；核对状态仍访问隔离PG，不称零数据库访问。正常/故障各8次授权查询，文件大小/SHA/ZIP/source mapping/初始回执核对。真实管理服务撤销原件后，Editor当前知识支持降为unverified并清除引用；冻结正文及历史XLSX下载字节不变。
- 发布故障仅注入一次read_fact_document OSError，保留report_claim_fact_file_unreadable / report_claim_fact_unknown、formalReleaseAllowed=false，仍签发和下载实际XLSX，不把下载成功标作验收通过。本轮无生产修改、新签发步骤、提交或部署。
- 共享helper增加可选入口回调、入口证据及HTTP独立目录。独立复核指出同PID的CLI/HTTP证据覆盖风险后，已用http-前缀分离；联合四目录/四run_id各自独立。最终复核无Critical/Important，Minor已修复。
- 受影响联合4 passed，81.19秒，隔离数据库清理True；覆盖HTTP正常/发布故障及既有CLI正常/发布故障。Ruff、diff通过，未重复完整项目测试。前三次缺隔离密钥、wire状态枚举比较、混淆两仓储入口字段均为测试装配失败，不计产品红例；正常首过和最终联合日志留档。
- 证据[公开HTTP首次XLSX](artifacts/2026-11-11-first-http-workbook/README.md)共57文件、1,684,049字节，含两份实际HTTP产物、全部登记源文件/依据/初始回执/摘要/索引/可信身份/知识撤销/拒绝请求/日志/源码/依赖/独立复核，及本次XLSX转PDF/首张PNG。manifest/verify.py离线通过，源快照与对应当前文件一致。两张首页已查看：文字标签可读无截断；重复建议、日期换行、留白及事实行次序待优化，不冒称整体美化、原生Editor、四宽度或含图完成。
- 历史项目均值仍为(0.9+0.5)/2×100=70，不等于C02总体正确值190/300=63.33；不可用同比未补零、充分性unknown保留。受控模型/向量、DuckDB与隔离PG不是实际模型/StarRocks/中文召回或业务签认，未使用业务.env/业务库重置。
- 公开HTTP首次XLSX正常/发布读取故障合约已补证；PPTX知识叙述、四格式编辑撤销重导出、完整附录、含图/原生Editor视觉、真实环境/业务确认、恢复保留/联合备份及全38案例/§5/T1–T9最终审计继续未完成，目标active。台账临时文件fsync后原子替换并读回，保留全部旧内容及磁盘恢复记录。

- 状态读回补注：本轮起始get_goal为active，末次读回为blocked；本轮未调用update_goal设置阻塞或完成。上条active是工程继续推进意图，不能覆盖系统最新状态；本轮已取得新增通过证据，仍有上述可执行缺口，不将blocked标记解释为工程完成或真实环境验收完成。


### T4/T5/T7/T8 首次 PPTX 分析说明与知识支持（2026-11-11）

- 首次实际原生PPTX工作流发现分析摘要未成为narrative subject；真实首跑红例后，将XLSX已有摘要模型/消歧提取为共享AnalysisSummarySection，PPTX冻结大纲、原文、依据/期间/分析/章节/知识回执身份；每项分析仅呈现一次。恢复读回同一摘要，不重跑语义模型；未知写入不自动覆盖。
- 既有知识登记与原生渲染消费冻结摘要，沿用trace subject及支持关系，不建第二份知识白名单。多段原文各自保留支持/反证标签；段落解析异常保留原文、具体issue及实际文件。封面date对象repr红例已改为可读ISO期间。
- 同模型独立只读复核无Critical/Important；两项Minor（整块丢多段支持、恢复测试空view未覆盖生成分支）已按真实PPTX红绿与非空view/builder仅调用1次修正。精确定点3 passed（10.67秒）、共享摘要13 passed（9.14秒）。
- 集成8 passed（127.98秒），包括首次PPTX正常、知识登记/段落解析故障，以及既有XLSX CLI/公开HTTP正常与发布故障；随机隔离向量管理库清理true。AGENTS必需非阻断节点75 passed/2 deselected（46.21秒）。集合重叠不累加总数，未重复完整项目测试。
- 知识登记故障使说明unverified/建议待核实、当前businessKnowledge unavailable，但现有软语义政策下版式validation.ok及formalReleaseAllowed仍true，不冒称该故障触发版式失败。段落解析故障validation.ok=false、pptx_narrative_paragraphs_unavailable及formalReleaseAllowed=false，实际PPTX仍签发/HTTP200。两故障已登记test_http_publication_lineage.py；既有_SIGNING_CHAIN守卫通过。
- 三次初始运行均revision1/无采用回执；真实管理服务撤销后当前说明unverified且无evidenceRefs，原Markdown及历史PPTX下载字节保持不变。历史rate@1仍为(0.9+0.5)/2×100=70.00%，不是C02总体190/300=63.33；数字陈述、充分性、粒度和基期不可用告警保持，不冒称业务批准。
- [PPTX证据](artifacts/2026-11-11-first-pptx-knowledge/README.md)104份文件约3.14MB，含实际三份交付/登记源/初始回执/冻结大纲/红绿日志/源码/独立复核/离线校验。实际LibreOffice转换及Poppler共17页PNG已逐页查看：日期及建议/反证/待核实可读，未见截断重叠；页次序差异、留白、重复/泛化基期说明、完整来源附录仍待优化。混合两段只是实际原生渲染器单元证据，不是完整首次混合工作流。manifest/verify.py及当前源快照一致性通过；受影响Ruff/diff通过。
- 本轮仍为可信CLI首次工作流+ASGI HTTP下载，未完成公开HTTP首次PPTX创建。受控模型/向量、DuckDB与隔离PG不替代真实模型/StarRocks/中文召回/业务签认；未用业务.env、未重置业务库、无提交/部署。四格式编辑撤销重导出、完整附录、含图/原生Editor/四宽度、真实环境、恢复保留/联合备份及全38案例/§5/T1–T9最终审计仍未完成。沿用上轮系统goal=blocked记录，不将其冒称工程完成；用户已授权继续可执行工作。


### T4/T5/T7/T8 公开 HTTP 首次 PPTX 与格式对应故障（2026-11-11）

- 进一步补齐公开首次PPTX入口：生产require_workspace_capability与Agno3.1.2原生POST /workflows/enterprise-reporting-workflow-v1/runs从空报告生成第1版PPTX，实际规范化/依据/计算/画像/SQL/CSV/分析/组稿/发布/签发/下载；无预置报告、采用回执。ASGI不冒称真实网络部署。安装原生路由源码SHA重新核验与上轮相同。
- 三PPTX case均验证缺capability/坏签名/线程不符在业务查询前401、未创建状态；伪造实际dependency及原生表单组织/数据库/用户/线程均由可信warehouse/101/7/thread-basis覆盖，两仓储分别核对agentos与http-capability。三个正常/故障回执及XLSX两回归runId/证据目录各自独立。
- 初次PPTX定点1 passed/1 failed/2 deselected（42.85秒）：正常入口通过；把XLSX SectionClaim事实读取故障用于PPTX时未触发，精确fault_calls断言失败。同模型独立只读复核指出该Important，确认是测试装配缺陷，不能计作有效PPTX故障。改为xlsx正常/事实读取故障、pptx正常/知识登记故障/段落解析故障五个明确case，未放宽共享helper断言或改生产路径；二次复核确认解决，无新增Critical/Important/Minor。
- 只定点复测剩余四例4 passed/1 deselected（72.01秒），隔离向量管理库清理true；已通过且行为不变的PPTX正常入口不重复。两日志合计覆盖五个成功case，不掩盖首次装配失败。本轮没有生产代码修改、新签发步骤、完整项目测试、提交或部署。
- PPTX知识登记故障真实触发一次，当前knowledge unavailable/说明unverified，版式及软语义formalReleaseAllowed仍true；段落解析故障真实触发一次，具体pptx_narrative_paragraphs_unavailable及validation.ok=false/formalReleaseAllowed=false保留。实际授权PPTX均继续签发与HTTP200下载。真实原件撤销后当前支持关系unverified/无evidenceRefs，历史Markdown与下载字节不变。XLSX正常及发布事实读取故障两例也保留完整实际产物。
- [公开HTTP首次PPTX证据](artifacts/2026-11-11-first-http-pptx/README.md)109份文件、2,861,154字节，含三PPTX/两XLSX完整产物、可信/拒绝入口、初始回执、全部登记源/冻结摘要/索引、日志、最终源快照、独立复核及离线校验；manifest/verify.py通过。三份实际HTTP PPTX转PDF，各查看封面及首说明页共6页，日期/建议/待核实可读，未见截断重叠；没有宣称全部页或原生Editor/含图完成。
- 历史70.00%仍是rate@1项目均值，不是C02总体63.33%；数值充分性unknown、粒度及无基期状态保持。隔离PG/DuckDB/受控模型不能替代真实模型/StarRocks/中文检索/业务签认，未读业务.env或重置业务库。公开HTTP首次PPTX这项缺证已补齐；四格式编辑撤销重导出、完整计算来源附录、原生Editor/静态图/四宽度、真实环境、恢复保留/联合备份、全38案例及§5/T1–T9最终审计仍未完成。沿用系统goal=blocked差异记录，继续工程推进不等于目标完成。台账fsync后原子追加并核对全部旧前缀。


### T4/T7/T8 四格式编辑后撤销知识与新交付（2026-11-11）

- 本轮真实复现XLSX新修订继承旧supported/evidenceRefs：编辑及operations=[]均须将现存来源映射改为待核验，保留父SHA/事实身份/原值并清空支持引用。读取/标记失败后增加独立ZIP删除映射；双重故障仍保留可读文件，明确workbook_source_mapping_unavailable，不冒称旧元数据已移除。故障注入与_SIGNING_CHAIN均登记，知识异常不得阻断实际文件签发。
- 新增四场景集成：XLSX标题编辑、XLSX未改重新导出、Markdown草稿编辑后真实PDF/Word导出、PPTX原生HTTP标题编辑。均先由实际管理服务撤销原件，新修订=父+1、实际下载身份/编辑内容/父文件字节不变；PDF/Word正文建议待核实且新Editor追溯unverified，原生XLSX映射unverified，PPTX新Editor明确pending，未假冒精确重审。父报告为采用口径夹具+原生交付，不是首次公开工作流；文档用Service导出，XLSX/PPTX用真实ASGI HTTP/cookie/CSRF。
- 真正红例xlsx-red-2、xlsx-unit-red及mapping-fallback-red-2后修复；授权轮换误判与未收集节点为装配错误另记。最终四场景4 passed（120.58秒）且隔离库清理true；最终强化签发故障/映射单测/守卫19 passed（29.34秒）；AGENTS指定非阻断节点75 passed/2 deselected（49.37秒，独立删除helper前），最终19项覆盖新增helper。集合重叠不累计独立数，未重跑完整项目。Ruff/diff通过。同模型只读复核Important已解决，无新增Critical/Important。
- 新修订签发按现有策略轮换同报告旧下载授权；原件撤销本身不使旧授权失效。测试分别核对两事实，不能宣称新签发后旧URL仍有效。双重映射故障仍可能留旧标记但明确告警，属于已记录限制。
- [编辑撤销证据](artifacts/2026-11-11-edit-withdrawal/README.md)含四场景实际PDF/Word/PPTX/XLSX、完整注册源文件/父与新清单索引/当前支持、红绿日志/源码/复核/离线校验。归档helper重序列化改变索引字节后已改读取原始身份，仅补未编辑XLSX1 passed/3 deselected（22.90秒）清理true；其余从保留测试工作区按登记size/SHA找回十份原始清单/索引，记录恢复来源，不重构登记哈希。
- 实际渲染26页（PDF7/Word7/PPTX4/两XLSX各4），联系图均查看，进一步单页核对Word3/PDF4/PPTX2/两XLSX1。正文建议待核实可读；原生XLSX/PPTX旧可见建议标签仍冻结，XLSX打印列窄折行密，最小文档夹具来源附录信息缺项，不登记完整视觉或来源附录验收。
- 本轮修复XLSX支持元数据与新增四格式交付证据，不等于四格式精确语义编辑闭环。仍缺原生可见标签同步、人工改数重算、完整公开报告至浏览器编辑导出、来源附录、原生Editor/静态图/四宽度、真实模型/StarRocks/中文召回/业务确认、恢复保留联合备份及完整38案例/§5/T1–T9审计。历史70%仍rate@1项目均值而非C02总体63.33%；隔离PG/受控向量/合成DuckDB不冒充真实环境；未读业务.env、未改业务库、无提交部署。沿用系统goal差异记录，不以本轮工程进展冒称目标完成。


### T7/T8 XLSX/PPTX 人工修订可见核验说明（2026-11-11）

- Ruling: 沿用人工修订整体待核验规则，在原生文件开头加入明确修订说明，而不按“建议”等固定词替换正文。原因是原生任意文本修改未完成精确语义重新绑定；代价是仍保留逐段重审缺口，不能声称原段落标签已同步重算。用户持续授权继续，未另建审核平台或自动推断业务意义。
- 新增revision_notice.py以专用ZIP部件路径和内部身份新增/更新首张XLSX说明表、PPTX说明页，显示本修订待核验、当前/父版本、数值解释建议未重新核验及旧标签仅供追溯。复用python-pptx生成单一说明部件，再补目录关联，不重存原业务对象；XLSX不移单元格，局部定义名称随表索引更新。实际原生引擎改名/重排后重复保存仍复用同一部件，同名业务内容不覆盖，原公式/打印范围与非目录部件字节保持。
- workbook/slides保存仅在分配版本后、写入/身份核验前加入说明。失败返回workbook_revision_notice_unavailable或pptx_revision_notice_unavailable，保留原已生成文件继续签发；两种精确故障注入在test_http_publication_lineage登记且调用各1次，_SIGNING_CHAIN增加helper。无前端依赖/权限/查询/迁移变化。
- 两项缺模块红例；独立helper首轮A5/A6测试行误判另记，不充当产品红例。隔离PG真实未改XLSX导出红例1 failed/3 deselected，接入保存后XLSX编辑/未改导出与PPTX编辑三场景3 passed/1 deselected（52.18秒），清理true；真实管理服务先撤销原件，ASGI HTTP/cookie/CSRF保存/下载、文件身份/编辑内容/父字节/新修订和unverified支持均核对。仍为采用口径夹具原生交付，不冒称首次公开完整报告或浏览器。
- 相关helper/两保存服务/新增HTTP故障/守卫40 passed（15.80秒）；AGENTS指定非阻断节点及旧原生保存故障93 passed/2 deselected（68.73秒）。强化所有原ZIP非目录部件保留断言后仅定点2 passed（12.75秒）。集合有重叠不累加独立数，未重复完整项目测试，依赖弃用警告保留。Ruff/diff通过，同模型既有reviewer只读无Critical/Important/Minor。
- [原生核验说明证据](artifacts/2026-11-11-native-revision-notice/README.md)96文件约1.79MB，含三份实际新文件、精确父清单/索引及全部注册源、当前支持、红绿日志、源码与环境、独立复核和离线verify.py。两XLSX与PPTX各5页，共15页联系图查看，三首页进一步单页查看：中文/精确版本/待核验说明可读，受检页未见明显重叠越界。原XLSX结论列窄、留白、重复文字及业务页码保持，不冒称整体视觉、原生浏览器或四宽度验收。
- 全修订可见状态已补证，逐对象语义重审、人工改数重算/证据换绑、完整公开报告→浏览器编辑导出、完整来源附录、原生Editor/静态图/四宽度、真实模型/StarRocks/中文召回/业务负责人确认、恢复保留联合备份、38案例和§5/T1–T9最终审计继续未完成。隔离PG/pgvector、合成DuckDB与受控模型不替代真实业务；未读业务.env、未重置业务库，历史70%仍rate@1项目均值不是C02总体63.33%。无提交部署，不改变既有goal差异记录或宣称目标完成。
