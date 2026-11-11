# 智能报告指标、统计口径与知识依据实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 默认顺序实施，不要求子agent。执行时先阅读关联设计及AGENTS.md；本轮已由持续目标授权实施，生产上线仍需独立明确授权。

**Goal:** 替换旧业务Profile，以一类报告和三个关联指标交付可解释、可核对、可追溯的完整报告链路。

**Architecture:** 指标定义、统计口径、业务知识及本报告计算依据各有明确业务契约；PostgreSQL保存权威版本，Agno提供知识读取/检索，现有SQL校验、数据集、报告产物和Editor追溯承载执行证据。新契约一次切换，不提供旧Profile适配或双轨运行。

**Tech Stack:** Python 3.12、当前Agno 3.1.2（执行前复核锁文件）、FastAPI、Pydantic、SQLAlchemy/PostgreSQL、SQLGlot、pytest/Hypothesis、React/Ant Design/TanStack Query/Zod、Vitest/Playwright/axe。向量后端优先验证Agno PgVector，未通过隔离探针前不引入业务环境。

**Spec:** [设计基线](../specs/2026-11-09-report-semantic-evidence-design.md)。该设计及本计划取代本轮早先兼容Profile的方案；旧2026-11-05总计划仅作为历史参考。

**状态：** 实施中。日期2026-11-09。隔离工作区为`/home/junge/.codex/worktrees/68d8/smart_reporting`，进度与验证证据见`../reports/2026-11-09-report-semantic-progress.md`。工作树HEAD为`7ef25eb1`，存在大量管理后台未提交成果，必须保留；执行基线是工作树及其快照，不仅是HEAD。

## 全局约束

- 不兼容：无旧Profile字段别名、自动迁移、兼容代理、旧文件加载回退、双写或双运行轨道；旧运行不得恢复，新运行正常恢复必须支持。
- 历史PDF/Word仅按现有产物授权和身份访问，不新增旧规则解释/编辑/重导出适配；不自动删历史表/产物。
- 单部署admin，沿用组织身份、会话、CSRF和审计；不增加负责人/限额表单，不建设角色平台。
- 语义业务校验软告警，不以固定关键词或强制人工暂停维持正确性；权限/身份失配拒绝使用相应资源。
- 已生成且身份可读取的PDF/Word仍签发下载；新增签发链路失败点登记到`test_http_publication_lineage.py`故障注入。
- loguru；Matplotlib静态PNG/JPEG；不扩展Plotly。
- 原始材料、凭据及业务敏感明细不进入仓库/截图；真实测试只在隔离PG/StarRocks执行，不并行重置同一管理测试schema。
- 不重复完整项目测试。每任务定点失败→实现→通过，最后只补尚未验证的跨层场景。
- UI使用Report Editor样式；登录≤300KiB、列表累计≤500KiB gzip；1440/1280/768/390px无整页溢出，axe严重/关键0。

## 1. 已核实事实与尚缺证据

| 位置 | 当前事实 | 处理 |
| --- | --- | --- |
| `smart_reporting/reporting/profile/models.py`、`registry.py` | 指标/维度/范围/累计/品牌混装，Profile继承和hash | 拆成新契约；算法可提取，旧公共类型和读取路径删除 |
| `smart_reporting/management/profiles.py`、`profile_api.py` | 草稿CAS、发布父版本、读取版本 | 复用事务经验，新建统计口径服务，删除旧路由 |
| `smart_reporting/management/runtime.py` | 服务端可信运行登记和精确配置恢复 | 保留身份边界，改为新计算依据，旧运行明确停用 |
| `smart_reporting/reporting/knowledge/index.py` | SQLite静态文档与workspace修复经验索引 | 留给Coding Agent，不混入业务制度授权和生命周期 |
| `smart_reporting/reporting/workflow/query_pipeline.py` | SQLGlot解析/字段语义校验 | 复用执行前校验，补粒度与关联约束 |
| `smart_reporting/reporting/workflow/runtime/planning.py` | 已消费Profile、目录与候选语义 | 改为新口径/指标/证据上下文 |
| `smart_reporting/reporting/trace/contracts_v1.py`、`dataset_service.py` | 结果CSV身份、授权预览和追溯基础 | 复用结果登记，新增依据伴随记录，不重造文件服务 |
| 管理`features/sources`与Editor`evidence-browser.ts` | 数据源操作和证据查看入口已有 | 添加业务对象页面与计算依据，不重写组件底座 |
| 本地Agno只读探针 | 3.1.2；`Knowledge.ainsert`、`asearch`存在；旧示例`add_content_async`不存在 | 固定实际版本并测试过滤/索引，不从最新README推断安装版能力 |

现有README中有关Profile章节字段和“失败关闭”的说明与当前代码/最新需求存在差异，不能直接当新契约。当前表级权限验收、样式截图只证明相应功能，不证明本计划业务闭环已完成。

## 2. 最小接口及数据关系

### 2.1 新模型（全为待创建类型）

统一放在`smart_reporting/reporting/semantics/models.py`，Pydantic extra=forbid，JSON alias采用camelCase。

```python
# 设计签名；实现时完整声明校验，禁止Any承载业务定义。
MetricDefinition: id, name, scope_id, revision, kind, field_ref, numerator_version, denominator_version,
                  unit, grain, time_field, dimensions, aggregation_policy, aliases
StatisticalPolicy: id, name, scope_id, revision, scenario, valid_from, valid_to,
                   metric_versions, filters, joins, evidence_release_id, decision_notes
MetricRequest: metric_version, basis_id, period, dimensions, filter_values
MetricResult: metric_version, basis_id, calculation_id, fact_id, period, value, unit,
              dimensions, status, issue_codes, dataset_ids
ReportBasis: id, run_id, scope, policy_version, metric_versions, source_versions,
             catalog_refs, evidence_release_id, background_release_id, request_summary,
             build_identity, knowledge_as_of, reproducible_until, registered_at, status
```

`numerator_version/denominator_version`均为`MetricVersionRef(metric_id, revision)`，不能只存ID再运行时选最新版。`scope_id`由服务端已认证组织登记，不接受客户端自报授权。`aliases`仅帮助候选召回，不决定权限或公式；`request_summary`由下述ReportRequestSummary验证。背景集合可为空。

`MetricDefinition.kind`首期限定sum/count/count_distinct/ratio；字段型与比率型互斥，ratio依赖精确版本且禁止循环。`aggregation_policy`表达事件流/累计快照、允许时间汇总方式，不添加任意Python或SQL公式。

`StatisticalPolicy.filters/joins`使用有限结构化表达式：登记字段、比较运算符、类型化值；只允许声明多对一维度关系，注明两端键和输出粒度。服务端解析登记字段，绝不执行上传文本中的SQL。`scenario`用稳定编码，业务显示中文名。

`MetricResult.status`=`computed|unavailable`，不可计算时value=null且有issue_codes。普通空结果与零值不同。`ReportBasis.status`=`registered|completed|partial`；登记部分不可变，后续结果/引用追加到独立回执，不能覆盖所用规则版本。

同组织每一发布版本完整自包含：指标版本被口径版本引用，口径引用证据发布集合，默认绑定引用口径精确版本，运行依据引用全部精确版本。对象创建/修改/发布与默认绑定分开。

### 2.2 持久化

在`management/repository.py`登记新表，以任务2创建的新migration为准。建议迁移号`0009_semantic_assets.py`，执行时检查当前head，冲突则使用下一合法编号并更新计划链接。

| 表 | 关键键与不变量 |
| --- | --- |
| metric_drafts / metric_versions | scope_id+metric_id+draft_version/revision；版本行不可变 |
| statistical_policy_drafts / statistical_policy_versions | scope_id+policy_id+version；口径JSON只引用精确指标/证据版本 |
| reporting_policy_defaults | scope_id+scenario唯一，指向精确口径版本及可选背景集合版本；version用于CAS |
| business_documents / business_document_revisions | scope_id+document_id+revision；原件身份、解析定位、状态 |
| business_evidence_releases | scope_id+release_id，记录已审核文档修订完整集合与索引构建身份 |
| business_ingestion_jobs | job_id唯一；queued/running/failed/ready；lease/retry信息；无正文日志 |
| report_bases / report_basis_receipts | scope_id+run_id唯一；依据和追加执行/引用回执分开，关联既有报告修订 |
| semantic_asset_retirements | scope+asset_type+id+revision；退役理由/替代引用/操作审计，独立于不可变内容 |
| report_issue_reviews | scope+issue_id；报告修订/对象引用/分类/裁定/关联修复版本，沿用admin审计 |

数据库约束+服务层强制scope匹配；不能仅凭前端传scope_id。原件用现有受控持久文件存储模式，DB保存身份与不透明资源ID，公开API不接受路径。

### 2.3 API面

以下统一在`/management/api/v1`，沿用现有auth/CSRF/origin与分页规范：

- `GET /metrics`、`GET /metrics/{id}`、`PUT /metrics/{id}/draft`、`POST /metrics/{id}/publish`。
- `GET /statistical-policies`、`GET /statistical-policies/{id}`、`PUT /statistical-policies/{id}/draft`、`POST /statistical-policies/{id}/preview`、`POST /statistical-policies/{id}/publish`。
- `GET/PUT /report-policy-defaults/{scenario}`；PUT带expectedVersion、精确policyVersion及可选backgroundReleaseId。
- `POST /business-documents`（受限multipart原件）、`GET /business-documents/{id}`、`POST /business-documents/{id}/revisions/{revision}/review`。
- `GET /business-ingestion-jobs/{jobId}`；`POST /business-evidence-releases`（显式文档修订集合）；`POST /business-evidence-releases/{id}/search-preview`。

报告请求新增可选`statisticalPolicyVersion`；不指定时按可信组织+场景读取明确默认绑定，无默认就记录缺配置，不隐式采用其他组织或“最新”。报告依据的读取/原文定位接入Editor已有修订授权路径，不能拿admin API充当普通报告用户API。

旧`/profiles/*`返回410 `management_profile_retired`迁移说明（固定拒绝端点，非代理、不读旧数据），旧JSON字段返回422；运行继续入口对旧契约返回409 `report_contract_retired`。所有拒绝测试保证不执行SQL/模型工具。

## 3. 依赖与里程碑

```text
T1 原始案例与开源决策
 → T2 新业务契约和存储
 → T4 业务知识登记/解析/审核
 → T5 证据集合检索
 → T3 指标/口径发布与默认选择
 → T6 确定性指标计算
 → T7 报告依据和工作流切换
 → T8 管理与报告查看体验
 → T9 独立验收与一次切换演练
```

任务编号保持稳定，实际执行顺序为T1→T2→T4→T5→T3→T6→T7→T8→T9。T3口径发布依赖T5的已发布证据集合，不能把临时空集合当正式成功。T4/T6可独立开发但本计划按上述顺序执行便于审查。T7前不开启新生产运行；临时不可用不是引入旧模型fallback的理由。每任务单独检查差异、只提交自身文件；不自动push/merge/deploy。

## T1 原始案例、独立oracle与开源决策

**Files**
- Create: `docs/superpowers/reports/2026-11-09-report-semantic-source-audit.md`
- Create: `docs/superpowers/reports/2026-11-09-report-semantic-open-source-decision.md`
- Create: `smart_reporting/reporting/tests/semantic_fixtures/cases.json`、`oracle.py`、`budget.csv`、`actual.csv`、`documents/`。
- Read: `deploy/agentos/reporting/reporting_profiles/hospitals/ruijin.json`，只作定位线索，不自动导入。

**Inputs/Outputs：** 输入原始材料与当前实现；输出有来源清单、38个case_id和独立expected值的固定基准集，以及明确采用的Agno版本/后端决定。

- [ ] 建立原件清单：材料来源/定位、版本、生效期、采集时间、授权范围、哈希、冲突与裁定状态；真实明细保留在授权存储，仓库仅脱敏fixture与不透明引用。
- [ ] 选择首期3个指标；若预算专题无可签认材料，记录选题依据并改选等价的3指标链路，执行前同步更新本设计及所有fixture名，不让工程样例变成正式政策。
- [x] 编写独立oracle，只使用Decimal和原始行，不调用新生产计算器/SQL生成器。固定反例：预算A=100、B=200，实际A=90、B=100，总执行率`Decimal(190)/Decimal(300)`；平均90%与50%=70%必须失败。实际重复单据、跨期累计和退款例分别单列。
- [ ] 记录以下固定commit的源码路径、测试/示例、许可和运行依赖：MetricFlow `fe4b8c1ccb72a8ca77494b345777eff20a714119`、Cube `5120fa39267d24b0fbb1cadc22e9c2147c593fac`、OpenMetadata `5e78a88c2080210d8bb580a0891ff02700bb2f09`、Agno `047cf37a47f3f5788faf63ce3437715bd6780123`。这些是前次README核对身份，不代表源码已审计；Agno本地3.1.2单独核对。禁止只列产品宣传链接。
- [ ] 在隔离PG上探测本地`Knowledge.ainsert/asearch(filters=...)`及PgVector实现：跨组织过滤发生在检索候选阶段、中文召回、元数据保存、重复写入、失败恢复。没有服务就保留失败/未执行事实，不能宣称适配。
- [ ] 审查结论：首期用Agno能力和现有SQL解析，复用公开模型理念；如必须引入新的执行引擎，给出其解决的具体失败案例及新增成本，更新后续接口后才进入实现。

**完成条件：** 工程基准完整；实际业务签认单独标注，缺签认不阻止开发但不允许最终业务验收通过。

## T2 新契约、不可变版本和权限存储

**Files**
- Create: `smart_reporting/reporting/semantics/__init__.py`、`models.py`、`validation.py`。
- Modify: `smart_reporting/management/repository.py`。
- Create: `smart_reporting/management/migrations/versions/0009_semantic_assets.py`。
- Create/Test: `smart_reporting/reporting/tests/test_semantic_models.py`、`smart_reporting/tests/test_semantic_assets_persistence.py`。
- Test existing: `smart_reporting/tests/test_management_migration.py`。

**接口：** `validate_policy(policy: StatisticalPolicy, metrics: tuple[MetricDefinition, ...]) -> tuple[SemanticIssue, ...]`。`SemanticIssue`字段code/object_id/message/impact，impact为unavailable/warning；非法结构使用Pydantic校验错误，不把缺业务证据写成HTTP500。

- [x] 先写反例：ratio同时给field_ref与分子、循环依赖、交叉组织指标引用、版本不存在、单位不一致、有效期倒置、缺少粒度；业务意义不明确返回issue而非全局异常。
- [x] 执行`.venv/bin/python -m pytest -q -o addopts= smart_reporting/reporting/tests/test_semantic_models.py`，确认失败源于未实现的新契约。
- [x] 实现上述模型与约束，新增存储表/外键；旧Profile表保持归档，无数据转换；原件只登记身份不存于日志。
- [x] 持久化测试：同名指标跨组织隔离、版本不可覆盖、事务审计失败回滚、并发同expectedVersion只有一个成功、迁移重复执行无变更。运行新增PG测试和受影响迁移节点，显式配置专用管理测试URL。
- [ ] 审查本任务diff并独立提交。后续类型一律从新模型导入，不创建旧Profile alias。

## T3 指标/口径管理、发布及默认绑定

**前置：T2、T5完成。**

**Files**
- Create: `smart_reporting/management/metrics.py`、`metrics_api.py`、`statistical_policies.py`、`statistical_policy_api.py`。
- Modify: `smart_reporting/app.py`、`smart_reporting/management/version_options.py`。
- Create/Test: `smart_reporting/tests/test_management_metrics.py`、`test_management_statistical_policies.py`。

**接口：** 服务方法`save_draft(token, scope, payload, expected_version)`、`publish(token, scope, id, expected_version)`；口径另有`preview(token, scope, payload)`、`set_default(token, scope, scenario, policy_version, expected_version)`。响应含对象版本、状态、issues、依赖差异；发布要求结构/身份有效，语义疑点列出告警与不可计算项。

- [ ] 写HTTP/CAS测试：未登录401、无CSRF403、跨组织404、冲突409，单独指标发布不改口径、口径发布不改默认，设置默认后仅新报告采用。
- [ ] 预览按metric id/版本与字段结构比较公式/粒度/时间/证据变化，不按中文措辞做差异判断。例：分母变更列为“计算规则变化”，文档换版列为“依据变化”。
- [ ] 实现第2.3节API。发布在同一事务验证引用均属于组织且已发布；版本引用不可循环，切默认显式CAS。响应丢失通过GET读回对象与版本，UI不重试写入。
- [ ] 运行`.venv/bin/python -m pytest -q -o addopts= smart_reporting/tests/test_management_metrics.py smart_reporting/tests/test_management_statistical_policies.py`（隔离PG），覆盖发布/默认竞争和读回。
- [ ] 精确移除旧路由在后续T7统一切换完成；本任务新增路由不对生产开放，不构造“旧转新”代理。独立提交服务/测试。

## T4 原始知识的登记、定位、审核及可恢复入库

**Files**
- Create: `smart_reporting/management/business_documents.py`、`business_documents_api.py`。
- Create: `smart_reporting/reporting/business_knowledge/__init__.py`、`models.py`、`ingestion.py`。
- Modify: `smart_reporting/app.py`（生命周期装配），复用既有任务执行设施，不新造通用队列。
- Create/Test: `smart_reporting/tests/test_business_document_ingestion.py`。

**接口：** `register_document(token, scope, upload, metadata, request_id) -> DocumentReceipt`；`ingest_revision(job_id) -> IngestionReceipt`；`review_revision(token, scope, document_id, revision, decision, expected_version)`。两种receipt均含ID、status、issues，不返回服务器路径。

- [ ] 写失败测试：伪扩展名/超限/路径穿越、解析中断、重复request_id、worker重启重复领取、租约过期、审核未解析版本、跨组织访问原文。
- [ ] 首期支持UTF-8文本/Markdown、可提取文本PDF、DOCX；单文件≤20MiB、≤200页或≤200万字符。扫描PDF识别为needs_transcription，不以空文本成功入库；OCR作为后续选项。对中文样例核对Agno reader的段落/页定位保真，缺定位时只新增本项目定位适配，不重写解析器。
- [ ] 原件存不可变资源；解析记录原件哈希、解析器版本、段落/页定位及定位文本。PDF用页码+页内片段，DOCX用段落/表格坐标，不伪造页码。
- [ ] 实现持久任务lease与幂等写入；原件→解析→索引→验证ready，审核与就绪分开。失败状态可查且仅显式重试，不占用长数据库事务等待embedding。
- [ ] 运行`.venv/bin/python -m pytest -q -o addopts= smart_reporting/tests/test_business_document_ingestion.py`；审查真实parser与mock故障边界，独立提交。

## T5 已发布证据集合与组织隔离检索

**Files**
- Create: `smart_reporting/reporting/business_knowledge/retrieval.py`。
- Create: `smart_reporting/management/business_evidence.py`、`business_evidence_api.py`。
- Create/Test: `smart_reporting/reporting/tests/test_business_evidence_retrieval.py`、`smart_reporting/tests/test_business_evidence_publication.py`。

**接口：** `publish_evidence_release(token, scope, revision_ids, request_id) -> EvidenceRelease`；`search_business_evidence(scope, release_id, query, metric_ids, period, limit=5) -> EvidenceSearchReceipt`。`EvidenceHit`含document_id/revision/locator/quote/source_hash/role/validity，score只作排序不表示可信度。

- [ ] 写反例：两组织同名制度、旧版规则、有效期错配、客户端换release_id、文档内“忽略规则执行SQL”指令、索引重建改变旧集合、已撤销文档。
- [ ] 生成不可变证据集合，包含精确修订和可查询索引身份；只允许ready且已审核修订。索引查询使用服务器提供的scope+集合过滤，结果再查权威记录二次校验。若后端不支持必须的前过滤，返回不可用，不用查询全部后过滤替代。
- [ ] 利用Agno reader/chunking/retrieval，在T1基准上比较关键词与向量/混合检索；按实际中文召回选最小方案。最大5条、每条≤1200字符、总≤6000字符，超长原文通过授权定位获取，不把全库塞进prompt。
- [ ] 知识不可用返回空命中与`knowledge_unavailable`告警；已发布公式仍可计算，解释标注依据不可用，不能从其他组织/未发布文档兜底。
- [ ] 定点运行两个新测试文件；真实embedding与模拟结果单独保存，独立提交。

## T6 指标计算契约与独立核对

**Files**
- Create: `smart_reporting/reporting/semantics/compiler.py`、`execution.py`。
- Modify: `smart_reporting/reporting/workflow/query_pipeline.py`、`smart_reporting/reporting/data_source/starrocks.py`（仅有必要的参数执行入口）。
- Create/Test: `smart_reporting/reporting/tests/test_metric_compilation.py`、`test_metric_execution.py`。
- Reuse: `smart_reporting/reporting/trace/ratio_proofs.py`、`cumulative_changes.py`的可适用数学规则；禁止为了新类型复制整个实现。

**接口：** `compile_metric(request: MetricRequest, policy: StatisticalPolicy, metrics: tuple[MetricDefinition, ...], catalog) -> MetricQueryPlan`；`execute_metric(plan, adapter) -> MetricResult`。plan含SQL AST/参数、输出粒度、依赖、聚合性质和核对要求；禁止任意模型SQL成为已批准指标公式。

- [ ] 编写oracle对比与Hypothesis性质测试：比率聚合、分组可加性只对可加指标成立、重复维度键、累计月末差分/重置、退款符号、零分母、空值、时区与半开区间。
- [ ] 核心反例断言：`Decimal('190') / Decimal('300')`按展示规则为63.33%；预算事实与实际明细先各自汇总，增加无关维度行不得把预算300放大。
- [ ] 生成有限SQLGlot AST，按登记维度/时间字段和类型值构建；执行前走既有只读、白名单与组织过滤验证。参数不打印敏感值。
- [ ] 预算缺少细维度时返回`grain_not_supported`，维度键非唯一返回`join_fanout`，快照重置无规则返回`cumulative_reset_unresolved`。受影响metric无值并保留原因，不中止整个报告。
- [ ] 将查询结果登记到现有数据集机制；记录提取时间、SQL/参数身份、水位（可得时），核对结果单列，不把hash当业务正确证据。
- [ ] 定点运行新计算测试与触及的SQL校验节点；真实StarRocks在T9执行。独立提交。

## T7 新计算依据、工作流接入与旧契约移除

**Files**
- Create: `smart_reporting/reporting/semantics/basis.py`、`selection.py`。
- Modify: `smart_reporting/management/runtime.py`、`data_sources/models.py`、`data_sources/service.py`、`data_sources/releases.py`、`importer.py`。
- Modify: `smart_reporting/reporting/bootstrap.py`、`contract.py`、`data_source/registry.py`、`workflow/orchestration.py`、`workflow/runtime/base.py`、`planning.py`、`datasets.py`、`publication.py`。
- Modify: `smart_reporting/reporting/trace/index_builder.py`、`smart_reporting/report_editor/trace_sources.py`、`trace_revisions.py`。
- Delete after callers replaced: `smart_reporting/management/profiles.py`、`profile_api.py`；`smart_reporting/reporting/profile/`业务模块。
- Create/Test: `smart_reporting/tests/test_report_basis_persistence.py`、`smart_reporting/reporting/tests/test_report_semantic_workflow.py`、`test_retired_profile_contract.py`。

**接口：** `register_report_basis(trusted_run, policy_version=None) -> ReportBasis`、`load_report_basis(trusted_run) -> ReportBasis`、`select_metric_candidates(question, basis) -> MetricSelection`、`append_basis_receipt(trusted_run, receipt)`。trusted_run来自现有服务端验证，不接受浏览器自报组织/运行身份。MetricSelection含候选、理由、未解决项；身份选项由服务端验证，模型不更新规则。

- [ ] 写端到端失败测试：请求→口径→指标→证据→SQL→结果→解释引用；换默认后旧的新模型run仍原版本；篡改session_state和证据ID不能扩大权限；旧run继续入口返回停用且无I/O。
- [ ] 建立新依据登记和恢复，事务唯一约束防同run并发不同选择。登记规则/引用不可变，结果及引用追加形成报告revision证据。来源撤销时不读取正文，保留原因。
- [ ] 将既有用途筛选、能力解析、单位与范围算法提取到`semantics/selection.py`及`validation.py`；用新类型重写调用，不能把EffectiveReportingProfile改个别名继续使用。
- [ ] 从原业务Profile拆出的品牌/版式落入现有交付设置；如不存在独立设置则新增`reporting/delivery/settings.py`及显式部署配置，不从旧JSON转换。删除数据源Profile绑定、新契约中统计口径与连接解耦。
- [ ] 旧路由固定拒绝；删除旧加载入口、启动回退、旧state字段消费和旧Profile配置示例。旧表只归档，新代码不得查。替换旧业务测试fixture；保留旧输入拒绝用例，删除仅证明旧功能仍可用的测试。
- [ ] 新依据与计算事实加入现有trace登记；原文引用读取使用Editor当前修订授权，不因已知文档ID直接放行。用户改写结论后重新检查引用关系，变化的引用标为待核对，不能沿用原“已核对”状态。
- [ ] 知识、登记、核对故障都写入validation/issues并继续已有产物签发。为新增失败点在`test_http_publication_lineage.py`增加参数例，覆盖文件已生成场景。
- [ ] 执行新工作流测试及AGENTS.md列出的全部非阻断契约节点（只这些节点，不整个项目）。搜索业务旧符号零运行引用；迁移历史、归档说明和拒绝测试允许保留。独立提交。

## T8 管理体验与报告查看依据

**Files**
- Create: `smart_reporting/report_editor/frontend/src/management/features/metrics/{list,editor,detail}.tsx`。
- Create: `smart_reporting/report_editor/frontend/src/management/features/policies/{list,editor,detail,release}.tsx`。
- Create: `smart_reporting/report_editor/frontend/src/management/features/knowledge/{list,detail,upload}.tsx`。
- Modify: `src/management/app/{router,shell}.tsx`、`api/contracts.ts`、`api/query-keys.ts`、`features/sources/{editor,detail,release}.tsx`、`styles/layout.css`。
- Create: `smart_reporting/report_editor/frontend/src/report-basis.ts`。
- Modify: `smart_reporting/report_editor/frontend/src/evidence-browser.ts`、`evidence-pages.ts`及其既有测试。
- Create/Test: `src/management/features/policies/policy-flow.test.tsx`、`src/report-basis.test.ts`、`e2e/management/semantic-workflow.spec.ts`。

**接口：** 使用T3/T4/T5 DTO；新页面懒加载，query key含scope+对象+版本。report-basis.ts仅消费服务端授权的报告修订依据，不直接调用admin API。

- [ ] 首先写交互用例：创建指标→登记依据→发布口径→设为默认→报告采用→查看数字明细和原文；冲突409、响应丢失、组织切换、未保存离开保留草稿；不引入自动保存重试。
- [ ] 页面导航按任务展示“指标”“统计口径”“知识依据”；不增加空仪表盘。数据源表单移除旧业务口径/Profile选择；默认口径在报告场景设置，不藏在数据库连接里。
- [ ] 指标编辑器按基础/派生区分字段，公式中文预览；口径详情展示适用范围、生效期、精确指标版本、制度来源、未解决项；发布对比分开计算变化、依据变化、默认绑定变化。
- [ ] 报告数字旁“查看计算依据”：定义/公式、输入与结果、期间/提取时间、来源原文、核对状态。不可计算、不可比较、推断、依据不可访问分别给可操作说明，不显示通用“失败”。
- [ ] 运行相关Vitest、构建、管理资源预算；Playwright覆盖4尺寸和原文弹层键盘/焦点/axe，并留存同数据集截图。新增非关键页面加载不得使登录/数据源列表超预算。
- [ ] 邀请未参与开发的业务人员完成3项任务：解释执行率、定位依据、解释改版差异。记录原始操作/耗时/误解；没有参与者只记工程走查。独立提交。

## T9 独立验收、切换演练与交付

**Files**
- Create: `smart_reporting/tests/test_semantic_starrocks_integration.py`、`smart_reporting/reporting/tests/test_semantic_acceptance.py`。
- Create: `scripts/management/verify_semantic_delivery.py`。
- Create: `docs/superpowers/reports/2026-11-09-report-semantic-acceptance.md`、`docs/report-semantic-cutover.md`。
- Modify: `README.md`、`smart_reporting/management/README.md`、部署配置示例，仅修改本次新契约入口。

- [ ] 实现38案例的manifest：case_id、输入/期望身份、独立oracle、实际数值/引用/拒绝、环境类型、证据文件、状态passed/failed/not_run。脚本不将skip转换成passed。
- [ ] 在唯一隔离StarRocks库创建预算/实际/维度/视图fixture，跑真实SQL和物化；越权JOIN/CTE/子查询/跨库在DB前拒绝；记录执行事件差值。finally只删除本次创建库，验证不存在。
- [ ] 在隔离PG测试迁移、索引恢复、服务重启和运行恢复；不同组织同指标/同文档无泄漏；同一新run恢复不换规则；证据重索引不改引用；旧Profile请求/旧run拒绝且不发生DB取数。
- [ ] 使用真实Agno/model/embedding执行一次试点报告，遵循`smart-reporting-real-os-test`技能；与独立oracle和固定证据核对。无原始签认数据只证明合成端到端，不证明业务上线。
- [ ] 保留PDF/Word实际身份与链接、原文定位、数值回执、告警、浏览器截图和资源预算。故障注入在隔离环境中证明下载不被业务核对/知识故障阻断。
- [ ] 切换演练：备份与清单→停止旧运行入口→等旧任务完成或明确结束→新表迁移→人工重新登记/核对新规则→发布证据/指标/口径→设置默认→同版本服务/UI上线→验收新入口和旧契约拒绝。该步骤先写演练结果；业务上线需要独立明确授权。
- [ ] 回退仅为部署/数据库备份回退决策，不是应用内兼容模式；新契约已产生运行后不能把旧服务接到新运行继续执行。演练失败保持新入口不可用并报告，不悄悄读取旧Profile。
- [ ] 独立审查通过后交付；没有真实业务签认、模型/向量服务或备份恢复证明的项目明确保留not_run，不把代码完成等同上线完成。

## 4. 固定验收案例（38项）

| ID | 输入/反例 | 期望证据 |
| --- | --- | --- |
| C01 | 同粒度预算与实际 | 与独立Decimal汇总一致 |
| C02 | 90/100、100/200 | 总执行率63.33%，不能70% |
| C03 | 预算一行关联多条实际 | 先聚合，预算不放大 |
| C04 | 维度键不唯一 | join_fanout，无伪值 |
| C05 | 请求未有分摊规则的细维度预算 | grain_not_supported |
| C06 | 两个月累计快照 | 按声明策略差分，不能累加快照 |
| C07 | 年初累计重置且缺政策 | 无值+具体原因 |
| C08 | 跨组织同名数据 | 无跨组织计入/检索 |
| C09 | 退款冲销负值 | 按已确认规则核对净额 |
| C10 | 时区月底边界 | 半开区间无重复/漏计 |
| C11 | 分母0 | 无值/披露，不能填0% |
| C12 | NULL或无数据 | 与合法0区分 |
| C13 | 两个同义候选指标 | 候选+差异，无静默择一 |
| C14 | 问题换说法 | 相同语义映射，同指标身份 |
| C15 | 已过期制度 | 不作本期正式依据 |
| C16 | 中途规则生效 | 分段有依据，否则不可比告警 |
| C17 | 两份制度冲突 | 保留冲突、来源与未解决状态 |
| C18 | 背景文档提出另一公式 | 不覆盖正式指标定义 |
| C19 | 文档提示注入 | 不执行文本指令，不扩权 |
| C20 | 未发布文档或伪造集合 | 不进入模型上下文 |
| C21 | 原文定位/哈希错误 | 引用不可用，不谎称支持 |
| C22 | 索引中断/服务重启 | 幂等恢复，无半发布状态 |
| C23 | 口径发布但未设默认 | 新报告仍明确原默认 |
| C24 | 切默认后恢复新模型旧run | 本报告依据不漂移 |
| C25 | session_state/请求替换版本 | 按可信登记拒绝越界 |
| C26 | 旧Profile输入/旧run恢复 | 明确停用、零取数 |
| C27 | 原数仓数据变化 | 结果快照复核一致，重查差异披露 |
| C28 | 文档撤销访问 | 不读原文，报告披露不可访问 |
| C29 | 编辑正文或数字 | 新修订，原核对状态不能无条件沿用 |
| C30 | 已生成PDF/Word后知识/追溯故障 | 仍签发、返回真实失败原因 |
| C31 | 三个问题只能回答两个 | 问题逐项映射，第三项显示未解决；不标全部完成 |
| C32 | 缺月/迟到数据/未匹配事实/基期不可比 | 不解释为下降，未匹配金额披露，无误导增长率 |
| C33 | 新背景事件但公式未变 | 独立背景集合发布；旧run不漂移，后知事件不伪装当时依据 |
| C34 | 正文/表格/图表/导出同一指标 | 同事实身份、范围/单位/舍入一致；相关性不冒充原因 |
| C35 | 重算响应丢失且图表未完成 | 幂等任务，新修订不混旧图；旧核对结果按依赖失效 |
| C36 | 用户报告计算错误并经核实 | 反馈→裁定→反例→新发布→新修订形成关联，不自动改正式规则 |
| C37 | 错误指标版本退役且为默认依赖 | 展示受影响口径/报告；新选用拒绝，无静默最新回退 |
| C38 | 清理/备份恢复后原件缺失或到期 | 保留期保护有效；不可复现明确披露，产物下载不新增阻断 |

检索基准对C13–C21及其固定措辞变体建立至少20个有标准依据的问题；另设无答案样本。开发样本与保留验收样本分开，报告Top-5召回分子/分母和无答案误引用率，禁止用同一模型生成期望再自评通过。

## 5. 闭环审查补充：并入现有任务，不新增平台阶段

**审查结论：** 原计划已覆盖定义、发布、取数和引用，但尚未对问题覆盖、数据充分性、当期背景、跨产物一致性、编辑重算、纠错反馈、退役影响和资源保留给出可验收契约。以下条目是实施任务的必要增补，不宣称现有代码全无这些能力；先复用已实现的coverage、finding、trace和revision。

### 5.1 契约补全（T2）

在`semantics/models.py`补充以下严格类型；嵌套引用不得使用无结构dict。纠错引用使用CorrectedVersionRef(asset_type, asset_id, revision)，覆盖指标、口径、原件修订及不可变证据集合，不能只接受指标引用：

```python
MetricVersionRef: metric_id, revision
ReportRequestSummary: goal, scenario, organization, period, comparison_period,
                      display_unit, requested_outputs, questions, assumptions
QuestionCoverage: question_id, status, finding_ids, subject_ids, issue_codes
DataReadiness: metric_version, requested_period, observed_period, extracted_at,
               source_watermark, checks, unmatched_groups, issue_codes
ClaimSupport: subject_id, kind, fact_refs, evidence_refs, support_status
ReportIssueReview: issue_id, report_revision, object_refs, category, description,
                   status, decision_reason, corrected_versions, regression_case_ids
```

`questions`使用含稳定ID与文本的记录；question status为answered/partial/unavailable，claim kind为fact/inference/recommendation，support_status为supported/unverified/conflicted。DataReadiness.checks逐项记录检查名、pass/fail/unknown和事实依据。ReportIssueReview的status为open/needs_evidence/accepted/rejected/resolved，只有修复证据或明确裁定齐全才能resolved；accepted不等于已解决。

- [ ] 增加T2验证：比率依赖精确版本；状态与空值一致；有问题必须有状态；未验证解释不得显示supported；结果/图表/正文引用使用同一fact身份。
- [ ] 当前`MetricResult`为单指标结果，分组返回有明确维度值的结果列表；ratio依赖图中的同名指标不同版本不得混用。

### 5.2 请求覆盖与数据充分性（T6/T7）

**Modify:** `smart_reporting/reporting/contract.py`、`workflow/runtime/analysis_coverage.py`、`evidence_coverage.py`、`finding_evidence.py`，以及T6/T7已列文件。
**Test:** 在`test_report_semantic_workflow.py`和`test_metric_execution.py`增加C31/C32。

- [ ] 报告入口形成ReportRequestSummary，记录显式条件/默认条件；完成时由coverage链逐问题给出证据和缺项原因，不以有PDF等同分析完整。
- [ ] 增加`evaluate_data_readiness(request, policy, observations) -> DataReadiness`，单位/时区/粒度对齐、源水位、期间覆盖和未匹配组有具体规则；必须读数据的检查走授权查询，目录发现仍不扫描业务数据。
- [ ] C32使用真实fixture：当期只有1–9月，问题要求1–12月；预算有A/B，实际有A/C。输出缺月和未匹配B/C，不能用INNER JOIN只剩A后称总体下降。
- [ ] 无可比基期时不输出增长率，报告仍可显示已核实绝对值和限制。运行对应case节点，保留完整回执。

### 5.3 背景知识与解释支持（T4/T5/T7）

**Modify:** T4/T5业务知识模块、T7新selection，以及`workflow/runtime/finding_evidence.py`。
**Test:** 新增C33/C34到已有业务检索/工作流测试。

- [ ] 文档元数据增加event_time、recorded_at、applies_to（指标/项目/组织引用）；字段缺失时不做未经证实的精确事件归因。
- [ ] 发布集合区分rule_evidence/background；口径只绑定规则依据，ReportBasis另外登记可选背景集合。默认背景绑定与政策默认一起CAS更新，但仅换背景不创建假公式版本。
- [ ] 创建报告时确定knowledge_as_of（默认创建时间，历史“当时视角”必须显式指定）；按事件适用期及当时可知性检索，不通过修改时间冒充事件时间。
- [ ] 解释输出ClaimSupport：数据事实用fact_refs，制度/原因材料用evidence_refs；推断/建议明确标注。来源真实但不支持结论的负例必须作为unverified/conflicted，不能仅凭引用存在判通过。

### 5.4 修改、重算、导出一致性（T7/T8）

**Modify:** `smart_reporting/report_editor/revisions.py`、`trace_revisions.py`、`trace_sources.py`和T7 publication、T8 `report-basis.ts`。
**Test:** C34/C35、既有`test_report_editor_lineage_export.py`相关节点；新增签发失败步骤同时登记HTTP故障注入。

- [ ] 增加`assess_revision_impact(previous_basis, revision_change) -> RevisionImpact`，返回受影响fact/subject/artifact身份及stale原因；依赖关系复用trace，不建新的图数据库。
- [ ] 文字润色只复核支持关系；数字重算使依赖图表/结论/导出过期；人工数值覆盖明确标manual_override，不能继承SQL核对通过。
- [ ] 重算请求登记request_id+input_hash+parent_revision，返回task_id；同ID同输入读回，同ID异输入409。身份仍绑定既有报告会话，不用request_id替代权限。
- [ ] PDF/Word展示计算说明与来源摘要；引用/核对故障有具体说明，已生成产物照常签发，不把未更新的旧图标为新版本已核对。

**2026-11-10实施状态：** 已接入精确登记事实的修订影响与Editor人工改数/文字修改提示，并实现原快照复核的持久requestId/inputHash/parentRevision、HTTP会话/CSRF、409冲突、未知响应读回及来源目录入口。verify_snapshot当前在请求内完成只读复核，明确不重新取数/不业务批准；真实refresh_data/adopt_policy执行器、后台重算与新修订落库尚未实现，因此本节重算闭环不勾选完成。详见[HTTP契约](../reports/2026-11-10-snapshot-verification-http-contract.md)及进度记录。

**同日后续：** 内部`ReportBasisService.refresh_calculation`已能从可信父回执按原依据重新取数，并在既有不可变回执表登记刷新意图、新计算与CSV；结果未知时拒绝自动重复查询，尚未接入公开refresh_data任务及新报告修订。任务查询已补齐`GET recalculations/{taskId}`；未知响应另用`GET recalculation-requests/{requestId}`读回，两者不猜测身份。

**同日修订恢复增量：** 已以不可变BasisRefreshRevisionReceipt登记分析修订所用的完整计算清单及父链，并支持服务重建、连续刷新、并发冲突和未知响应读回。每次真正使用分析时重新核验目标CSV，历史登记成功不等于当前可复现。该清单尚未绑定完成的新正文/静态图、Editor或导出，整报告新修订及后台重算仍未完成，本节保持未勾选。

**同日原生生成增量：** 已登记分析修订可经服务端显式参数进入原生事实写入和发现引用生成，实际文件及ReportingStateRepository登记已用隔离PG验证；原运行checkpoint/phase和初始文件保持冻结。标准图的正式MetricResult投影仍缺，后台任务、新正文、完整Editor修订及导出仍待接通，不把facts/finding文件生成计为整报告刷新闭环。

**同日正式图表增量：** 正式MetricResult现可经精确选择器进入现有chart-input和Matplotlib标准图；Decimal原值保留、百分比不重复乘100、未提供结果保留null，图表/Editor只采用完整已登记数据集。实际PNG、标准证明重编译、质量与精确fact归属已用合成fixture验证，见进度记录和静态图证据目录。此处仅证明已登记事实的图表投影；后台修订执行身份、新正文及完整Editor/PDF/Word刷新仍未接通，本节保持未完成。

**同日整批取数增量：** 新内部`ReportBasisService.refresh_revision`在第一条SQL前以既有不可变回执和审计固定完整父分析及全部目标计算，串行复用逐项刷新，再登记完整分析清单；已完成项读回、未启动项可继续、结果未知项停止且不自动重查。整批与手动登记使用同一修订事务锁并提交前复核。已验证本期/基期部分完成恢复、同批并发、审计回滚及父版本冲突；仍没有后台调度、独立生成检查点、完整新正文或交付，公开refresh_data保持未启用。

**同日独立执行增量：** 已登记分析清单可创建独立原生ReportingRunState，执行身份固定原授权作用域、依据、分析摘要及交付编号。编号沿用Editor CAS预留且持久恢复幂等；新事实/发现/检查点可显式写入独立状态，原阶段/检查点/产物登记不变。已用隔离PG验证响应丢失恢复、旧事实和伪造编号拒绝。此处是内部执行基础；尚未接入后台controller、完整新正文/图表生成编排或Editor交付，公开refresh_data不启用。

**四格式范围补充（用户确认）：** 刷新及采用新口径后的新修订必须覆盖现有document（PDF/Word）、PPTX、XLSX三类交付流程。保持原报告明确选择的requestedOutputs，不把PPTX/XLSX隐式转为文档，也不要求每次同时生成四格式。独立执行、断点恢复和新事实依据共用同一契约，格式专用生成/编辑/签发继续复用现有链路。验收分别覆盖三类运行的新产物身份、原版本不变、响应丢失恢复与下载；已生成且身份可读取的授权产物继续非阻断签发，质量失败如实披露。不得只完成PDF/Word就把§5.4刷新闭环勾选完成。

**原生后台恢复增量：** 已增加独立只读read_refresh_run，查询不启动计算；原生派发响应丢失后读回同一runId，核对输入摘要及用户/会话/工作流身份。SQLite与隔离异步PostgreSQL后台契约通过；文档、PPTX、XLSX均已执行持久Editor任务到新文件与下载的内部执行器验收。完整原生后台跨格式串联结果见进度记录；公开App/HTTP接线仍缺，不将内部验收计为§5.4闭环，采用新口径及真实业务验收继续待完成。

**只读交付HTTP增量：** App已注入既有runtime，新增GET recalculations/{taskId}/delivery，沿用报告会话授权/no-store，仅恢复已登记最终文件并签发链接，不触发取数/分析/生成。完成登记缺失保持pending/告警且照常提供可核验格式。文档、PPTX、XLSX三格式实际HTTP恢复3 passed，AGENTS非阻断及重算契约129 passed、1 skipped。POST刷新及原生状态投影尚未接通；初次公共请求端到端、采用新口径、含图与业务验收仍缺，§5.4不勾选。

**公开刷新及状态增量：** POST refresh_data已从可信来源登记请求并委托Agno原生后台，待完成202；App注入既有异步PG。两种任务GET增加execution运行状态，后台结束不冒充完成交付；同请求读回不等待执行长锁，错误/取消/暂停/未知不自动重启。公开HTTP鉴权/202/重复/409契约与四格式公开Service生成分别通过。受控模型fixture派发前仍准备目标执行/画像，首次公共HTTP全链路、后台生命周期/进程中断恢复、UI及采用新口径尚待完成，不勾选§5.4。详见HTTP契约与进度记录。

**首次HTTP及前端增量：** 四格式测试已移除目标执行/画像预建，由首次HTTP POST自行进入后台取数、画像、分析及交付，三个参数均通过，原版本不变。Editor来源目录已接入刷新确认/请求缓存/读回/显式恢复/四格式下载，组件与来源目录测试通过；新增组件四尺寸与axe证据已保存。尚不证明真实模型/业务取数；后台生命周期、全编辑器浏览器、采用新口径、含图和其余§5要求仍待完成，不勾选§5.4。

**同日任务及大纲增量：** document/PPTX/XLSX独立执行现可内部委托原生analysis-item Task入口，子检查点、计划、正式事实、引用与任务合同保持一致；完成响应丢失恢复同Task回执。完整大纲不可变登记，任务委托和证据汇编核对实际文件及检查点摘要，拒绝替换标题/章节。三格式隔离PG端口测试3 passed，大纲篡改XLSX追加节点通过；这是Task端口替身证据，尚未执行真实lease/model，也不证明五阶段内部上下文和最终产物链路完成。最终PDF/Word/PPTX/XLSX刷新、编辑、下载仍待接通，公开refresh_data/adopt_policy保持503，§5.4不勾选完成。

**四格式执行与真实画像增量：** ReportRevisionExecution现在明确冻结原请求的requestedOutputs，文档/PPTX/XLSX分别经过隔离PG的执行恢复、事实/发现/检查点测试；篡改目标格式被拒绝。新修订可使用原生fg-data-profiling生成真实CSV画像并登记独立上下文，事实写入仅接受该执行登记结果。此项没有生成四种最终文件，不替代各格式完整刷新/编辑/下载验收。

**同日分析准备增量：** 三格式共用的内部prepare_revision_analysis已可将详细计划、真实CSV画像、正式事实和发现装配为独立原生检查点；覆盖记录来自真实画像。逐数据集画像登记后的中断可恢复，不再重跑已完成画像。仍缺上游刷新计划编排、后台调度、新正文/幻灯片/工作簿与最终交付，不能据此勾选整报告刷新完成。

**同日计划保真增量：** 原生set_analysis_plan现保存并核对完整DetailedAnalysisPlan，不允许同一状态改绑完整计划。新增纯函数按完整MetricRequest对应新数据集，保留问题、动作、完成条件，清除旧画像证据摘要；部分来源、共享来源歧义、旧数据集与缺字段明确要求重新规划。该函数尚未接入可信父计划恢复及后台执行编排，不能称上游刷新计划已完成；PPTX/XLSX最终产物仍待验收。

**同日可信计划恢复增量：** prepare_revision_analysis可自动从原Reporting持久完整计划或父独立执行登记的不可变计划恢复，经可信父/新计算及新CSV真实字段校验后生成新计划；会话自报计划不参与。历史登记上下文读取单独说明不验证旧CSV当前可复现，真正分析始终核验新CSV；连续刷新可在父CSV失效时承接意图，父计划损坏或缺失则拒绝猜测。文档/PPTX/XLSX均已用隔离PG跑通连续两次分析准备，后台调度及最终产物仍未接通，本节保持未完成。

**同日XLSX正式结果增量：** 工作簿汇总现在采用正式MetricResult及精确事实指针，不再遗漏正式结果或混入同文件旧数组。精度超界保留文本并说明，空值不补零，无数据集的不可计算结果不回填其他来源。现有引擎生成实际XLSX、独立读回、来源登记/缓存公式及LibreOffice逐页渲染均有合成技术证据；后台新修订到完整交付仍未接通，不能据此勾选XLSX刷新验收完成。

**同日冻结证据增量：** 新执行现持久保存完整计划、问题映射与原格式；原生证据汇编可显式读取子执行并核对新CSV/事实/引用/完成回执，独立AnalysisArtifact可不可变落盘及检查点恢复。正式证据目录已投影精确指标版本/定义/半开期间和计算输出粒度。未自动完成业务分析，不把fixture完成回执当真实模型分析；后台与最终四格式交付仍未接通，本节保持未完成。

**同日真实Task执行增量：** 三格式测试现使用真实隔离PG任务仓储/租约/coordinator/原生分析五阶段及Toolkit完成提交，只替代结构化模型响应。已发现并修复完成Task恢复前误领租约的问题，完整作用域匹配后恢复正式回执，响应丢失不重跑executor；coordinator/CLI定点7 passed，文档/PPTX/XLSX三参数3 passed。此例不需脚本补证，两个条件阶段跳过；不视为真实网络模型或最终产物验收。章节规划、格式专用最终生成/Editor/下载与后台控制器仍缺，本节不勾选完成，公开refresh_data/adopt_policy继续503。

**同日章节规划增量：** 原生generate_narrative_outline现可显式消费子执行冻结证据、完整计划和新发现图谱，章节文件及阶段/检查点仅写子状态，原报告会话不变；load_revision_outline从登记章节与图谱核对最终摘要。章节已登记但检查点未提交、检查点已提交但响应丢失均能恢复，避免重复规划，告警持久保留，文件变化拒绝使用。文档/PPTX/XLSX三参数PG通过，追加双中断/篡改XLSX通过，原章节流程20项回归通过；规划器返回仍为受控测试fixture，真实模型和最终正文/幻灯片/工作簿生成编辑下载待验收，§5.4保持未完成。

**同日PPTX提纲增量：** generate_slide_outline/_slide_checkpoint现接受显式新执行，核对PPTX选择、子冻结证据/图谱/大纲，将幻灯片提纲隔离写入子执行并登记检查点；响应丢失可恢复，文件篡改与非PPTX误入拒绝。三格式PG3 passed、原PPTX21 passed、追加恢复篡改PPTX节点通过。最终assemble_slides、manifest/trace及渲染仍读原上下文，尚须贯通新修订身份与含图证据生成；不能以提纲生成代替最终PPTX/编辑/下载验收，§5.4保持未完成。

**同日PPTX组装及追溯增量：** 新修订assemble_slides显式读取子提纲/冻结证据/新CSV，生成隔离Markdown与权威清单/trace，登记子状态并恢复完成后的响应丢失；清单核对完整数据集/事实及输出命名空间，追溯读取子问题与本修订知识回执，质量告警只写子执行。真实PG三格式节点通过（仅PPTX走组装）、PPTX21项回归通过；AGENTS非阻断签发契约74项通过，新增质量告警登记失败HTTP注入链接仍可用。尚无最终新.pptx或编辑下载证据，正式明细下钻、含图证据重冻结、各格式渲染及后台控制器等仍待补齐，§5.4不勾选完成。

**PDF/Word独立最终渲染增量（2026-11-10）：** 文档装配后可显式创建本修订原生job，冻结新CSV身份/页面/品牌/期间/章节及引用，以独立目录实际生成PDF和Word并登记子结果。已登记文件恢复先于来源读取，渲染/完成响应丢失不重跑；验收回执缺失/串用软失败，文件身份漂移仅隔离对应格式，另一有效格式保留。原生渲染真实文件、隔离PG恢复与HTTP新增故障签发已有定点证据，文档HTTP已补齐返回验收原因。受控章节fixture不代表真实模型，Editor/后台controller及完整刷新/采用口径仍缺；公开refresh_data/adopt_policy继续503，§5.4不勾选完成。详见进度记录及revision-document-render技术证据。

**统一交付续跑增量（2026-11-10）：** 内部continue_revision_delivery现按可信子检查点衔接既有分析/规划/格式汇编/渲染/发布，优先恢复已登记最终文件。同次渲染故障保留告警，不被立即恢复抹为通过。隔离PG已验证三格式最终恢复及XLSX汇编/首次渲染；未完成从请求到后台调度及全分析链的一次完整执行，公开refresh_data/adopt_policy仍未开放，§5.4保持未完成。详见进度记录。

**可信刷新准备增量（2026-11-10）：** 原运行首次分析登记不可变approvedOutline；新执行准备从原登记/父执行文件恢复大纲，无登记明确拒绝，不做旧报告回退。内部prepare_refresh_delivery已串联原授权核验、整批刷新与首次独立分析准备，重复调用保留已生成检查点；隔离PG覆盖三格式及父CSV失效后创建新批次。公开持久请求到原生后台任务仍未接通，采用新口径及其余验收未完成，§5.4继续保持未勾选。

**刷新请求绑定增量（2026-11-10）：** 内部刷新任务可持久绑定父计算修订及由taskId唯一派生的目标计算修订，区别于交付revision；相同输入读回、改绑冲突、响应丢失恢复与PG服务重建已有证据。后台调度与执行/完成结果尚未接入，公开refresh_data/adopt_policy仍503，不把pending登记当完成。§5.4保持未完成。

**父计算权威解析增量（2026-11-10）：** Editor自动刷新登记可从实际来源事实与管理回执恢复精确父计算修订；三格式PG验证交付编号与计算修订区分、来源字节及管理记录匹配，损坏时不登记虚假任务。已登记请求支持来源后续失效时读回。实际后台调度和完成交付结果仍缺，公开刷新入口保持关闭，§5.4未完成。

**刷新执行与后台派发增量（2026-11-10）：** 内部run_refresh_request可委托现有刷新准备/原生交付并登记严格实际产物结果；XLSX已验证第三批真实刷新、完成记录与HTTP下载。完成登记未知仍保留文件与原因，单格式身份漂移隔离该格式。内部dispatch_refresh_request复用Agno原生后台Workflow和持久独立会话，重复读取同一运行，轮询不等待执行来源锁；后台测试执行端口受控，不冒充真实完整后台刷新。App/HTTP接线、全部格式任务闭环与恢复策略仍缺，公开refresh_data/adopt_policy继续关闭，§5.4未完成。

**持久队列增量（2026-11-10）：** 生产App的refresh_data现委托Agno原生持久队列，任务决定稳定runId/去重键，max_attempts=1；接受响应丢失且run未准备时仍能只读恢复票据，重复POST不重派发。通用工作流从登记上下文及完整输入摘要恢复，并核对原用户/会话。内部worker不注册公共工作流，停止顺序先于Agno数据库及执行资源关闭。生产dispatch后数据库/工作流对象重建、原生worker执行中停止及不再派发、生命周期异常顺序有测试证据；XLSX首次HTTP至实际新工作簿/下载已走durable路径。操作系统硬杀/真实多副本、其他格式的新队列验收、adopt_policy、含图与其余§5要求仍未完成；对象重建及worker停止不代替进程kill验收，不勾选§5.4。详见进度记录及HTTP契约。

**四格式队列及硬退出验收增量（2026-11-10）：** PDF/Word和PPTX首次HTTP完整生成/只读下载已补接生产同配置的原生持久队列，两参数通过；结合前轮XLSX技术验收，四格式路径均有实际文件证据，仍为受控模型/查询fixture。另完成独立worker进程SIGKILL及原生真实租约扫描：已进入受控执行的同一runId最终error/failed，attempt=1，重复POST不重新执行；不把可见失败称为中断后续跑完成。当前Agno发行版核对为锁定的3.1.2。真实多副本、采用新口径、含图、真实业务及其余§5要求未完成，详见进度记录。

**采用新口径预检增量（2026-11-10）：** 已新增严格只读PolicyAdoptionPreview和可信管理服务：显式已发布/未退役目标、原目录及期间/基期编译、精确指标版本与口径字段差异，固定not_recalculated及必须确认问题映射，不改原依据/默认/计算/审计。Editor新增受会话/CSRF保护的POST policy-adoption-preview，原basis/组织/用户由服务端来源恢复，正文/父修订变化409。隔离PG三个场景及HTTP绑定/旧刷新两节点通过。尚无预检UI、确认登记、新basis父链或adopt_policy执行/四格式交付，预检不等于采用闭环完成，§5.4继续未勾选。详见HTTP契约与进度记录。

**新口径确认登记增量（2026-11-10）：** 内部register_policy_adoption现按完整预检hash与逐题显式映射，原子登记独立ReportBasis、可信runtime身份、不可变父链回执及审计；保留原请求/格式/数据源/目录/背景，旧依据不改。请求身份稳定、同输入恢复、异输入冲突；新read_policy_adoption只读恢复未知响应。隔离PG已验证并发唯一、审计整笔回滚、服务重建、严格映射/unavailable、退役前后及回执篡改；语义模型/规划/旧注册受影响31项通过。尚未绑定Editor确认任务、新Reporting状态/工作区、新计算/规划和四格式交付，公开adopt_policy继续未启用，整体不勾选完成。

**新口径独立执行准备增量（2026-11-10）：** 已登记确认可内部登记新Reporting run/state及独立scope/workspace，用现有Editor CAS预留唯一新编号；新basis的初始选择只来自确认回执，不复制旧结果/画像/计划/检查点。文档/PPTX/XLSX三参数验证选择审计回滚、state写前/提交后故障、仓储/服务重建、旧basis/编号/格式/run-owner失配拒绝，最终3项通过，查询次数0。尚无新口径实际取数/规划/分析/四格式生成或Editor后台确认任务，准备不是交付完成，§5.4继续未完成。详见进度记录。

**新口径正式计算增量（2026-11-10）：** 已从可信新依据确认及初始选择派生本期/基期取数，在现有不可变回执中先登记每项查询意图及审计，再复用授权SQL、CSV和正式计算；已完成项核验后恢复，结果未知项不自动重查。原生calculate_report_metrics也接入此路径，已验证新政策过滤实际改变结果、并发、部分完成/未知响应、CSV身份失效及明确unavailable。新依据独立重新规划、静态图/正文、四格式交付与Editor确认/后台任务仍未接通，公开adopt_policy保持未启用，§5.4不勾选。详细证据见进度记录。

**新口径重新规划增量（2026-11-10）：** 已从新计算CSV运行原生画像与新规划，详细计划及依赖文件登记到独立Reporting运行；原报告仅提供已登记报告类型，不复制旧分析/章节。文档/PPTX/XLSX三种交付类型的新准备、服务重建、PPTX登记后响应丢失及画像身份变更拒绝已定点验证。此处尚非分析Task或最终文件交付；准备中间状态的显式恢复、后续生成job/检查点、四格式交付及Editor采用新口径仍待完成，§5.4保持未完成。

**新口径原生分析执行增量（2026-11-11）：** 已委托现有ReportingTaskCoordinator/TaskExecutionKernel实际执行新分析并写新事实、检查点和发现图谱；响应丢失后重建仓储读取同Task，不重复查询或执行。文档/PPTX/XLSX三类分析阶段定点验证通过，q-rate仍为partial、原报告不变。尚未生成新口径下最终图表、正文和四格式文件，公开adopt_policy后台及Editor UI仍待接线，§5.4不勾选。

**新口径章节规划增量（2026-11-11）：** 已从新发现图谱委托原生章节规划，不复用原章节。提纲文件先登记，检查点提交前中断或提交后响应丢失均恢复同一提纲；隔离PG仓储重建后模型调用仍一次、查询仍一次，文件篡改拒绝且不重跑。文档/PPTX/XLSX三参数3 passed，原生章节回归17 passed。本阶段不含静态图/正文及四格式最终交付，公开adopt_policy后台和Editor UI仍待实现；§5.4保持未完成。

**新口径文档准备增量（2026-11-11）：** PDF/Word已通过原生WorkspaceReportService用新CSV创建真实文档job，绑定新提纲与部署版式，登记不可变job快照。隔离PG测试证明登记后响应丢失、仓储重建恢复同job及文件篡改拒绝；不重复取数或创建job。正文/静态图/最终四格式交付和公开后台/UI仍未完成，写文件后未登记的中间状态仍需显式恢复；不勾选§5.4。

**新口径正文执行增量（2026-11-11）：** 已从新事实/图谱/提纲构造原生章节Task，实际生成引用新basis预算200的正文；未回答的执行率及语义未知保留限制。Task完成响应丢失、章节登记响应丢失后重建仓储恢复同Task，执行/查询各一次；无效章节及完成文件篡改拒绝。文档节点与原生大输入/多章节恢复定点通过。尚非整份报告装配、静态图或四格式最终交付；公开后台/UI及中间状态显式恢复仍缺，§5.4继续未完成。

**新口径正文装配增量（2026-11-11）：** 已委托原生链路完成全部章节的Markdown、服务端表格、权威manifest及新依据追溯索引，并恢复真实job的最终标题编号。完成登记响应丢失后仓储重建恢复同产物，模型/章节Task/查询不重跑；Markdown和事实文件篡改拒绝。正式聚合无下钻操作数时不读旧Profile、不签发明细能力。文档定点及规定非阻断回归通过（75 passed、1 skipped；skip不算通过）。尚缺静态图与四格式最终文件/下载、公开后台/UI及其他明确验收项，§5.4不勾选。

**新口径PDF/Word生成增量（2026-11-11）：** 原生新修订渲染器已识别并核验真实PolicyAdoptionExecution，使用新basis/initial正式回执和独立目标目录生成实际PDF/Word。渲染后响应丢失保持具体失败原因及文件身份；仓储重建、来源CSV/Markdown失效仍只读恢复已登记产物，PDF损坏只撤回PDF、保留Word。新口径实际生成、旧刷新文档、格式损坏HTTP及规定非阻断定点通过。尚缺静态图/PPTX/XLSX最终交付和公开采用新口径后台/Editor链路，导出视觉及真实环境验收仍待完成，§5.4不勾选。

**新口径XLSX增量（2026-11-11）：** 内部新口径已通过既有工作簿装配/CodeGenerationRunner实际生成XLSX；汇总和明细200及来源映射精确对应新basis/fact/calculation。装配和验收检查点响应丢失可恢复同文件、不重新取数/生成；来源CSV失效不阻断已登记文件，验收回执损坏保留文件并撤回无法核验的来源声明。新节点1 passed、原刷新XLSX1 passed、正式工作簿及规定非阻断100 passed/1 skipped，详见进度记录。公开采用口径后台/UI、PPTX、含图及真实环境/视觉验收仍缺，§5.4不勾选。

**新口径PPTX增量（2026-11-11）：** 已复用原生幻灯片提纲/组装/manifest与实际PPTX引擎完成内部新口径交付，页面XML预算200；装配和渲染完成响应丢失均恢复，已登记文件恢复优先于来源读取，不重跑生成/SQL，提纲篡改拒绝使用。恢复时精确读取冻结最终标题，未放宽证据校验。新节点1 passed、原刷新PPTX1 passed、PPTX及规定非阻断/HTTP故障131 passed/1 skipped，详见进度记录。四格式内部实际生成不等于公开采用口径闭环；持久后台/UI、含图/视觉/真实业务验收和其他§5仍待完成，§5.4不勾选。

**新口径四格式交付恢复与HTTP增量（2026-11-11）：** 内部可信新执行已可经统一发布恢复入口和既有issue_http_publication取得四格式实际HTTP下载及新Editor授权；精确核对目标run/revision/basis/上下文，不借父报告身份。来源清单或分析准备快照失效撤回相应来源/编辑，实际可核验文件继续下载；签发释放绑定后重复恢复已修复。最终三格式PG/文件/HTTP/Editor节点3 passed、规定非阻断及新增HTTP故障84 passed/1 skipped，详见进度与HTTP契约。尚未接通公开采用口径确认及原生持久后台/UI，亦非真实模型/StarRocks或完整浏览器/业务验收，§5.4不勾选。

**新口径统一续跑增量（2026-11-11）：** 新内部continue_policy_adoption_delivery已能按可信执行从原生分析、提纲/章节、三类装配接续到四格式渲染/发布，已登记最终文件优先恢复；同次渲染失败原因不被随后恢复抹去。实际PG三格式阶段续跑3 passed、规定非阻断/静态守卫/HTTP故障84 passed/1 skipped。尚非公开确认首次POST到持久后台的一次完整执行，模型仍受控且分析准备仍预登记；公开任务/UI、含图/视觉、真实环境与其他§5要求待完成，§5.4不勾选。

**Editor确认任务与原生Workflow增量（2026-11-11）：** 内部严格PolicyAdoptionRequest及持久pending登记已接父修订/正文SHA/预检摘要，支持相同请求读回、异输入409及并发；执行器从冻结确认登记新依据，委托统一新口径交付，完成记录校验完整来源scope及实际格式身份，登记故障保留可读文件。新增可重建原生Workflow及输入/user/session边界，7项通过；隔离PG原生Workflow到内部执行器1项通过，但管理/生成端口受控。规定非阻断/静态守卫/HTTP故障99 passed、1 skipped。公开adopt_policy POST、原生持久队列/resolver、只读交付目标scope签发与UI尚未接通，不能将内部任务计为§5.4产品闭环；真实连续执行与其余验收仍待完成。



**公开采用口径与持久队列增量（2026-11-11）：** POST recalculations现接受严格PolicyAdoptionRequest并返回pending/202，复用会话/Origin/CSRF，预检变更及异输入409，缺完整确认422；管理错误按具体code/status披露。新口径Workflow与刷新共用既有Agno单次尝试持久队列，启动resolver恢复两种组件；任务GET只读投影实际运行/票据，不自动重启。交付GET从已登记执行恢复并使用目标新scope签发，完成记录缺失保持pending及告警、不阻断实际文件。HTTP、PG队列/状态和内部交付scope定点证据见进度；仍需首次公共采用POST到真实管理/全原生生成/四格式下载的连续集成、Editor UI及其余含图/视觉/真实环境验收，§5.4不勾选。



**Editor采用口径界面增量（2026-11-11）：** 来源目录已接候选分页、具体前后差异、逐题显式指标/null与原因、确认提交/只读状态恢复、四格式下载和新报告入口；未知响应不自动重提，切换选择忽略旧预检，正文变化/缓存不可用不POST。新增会话授权的只读policy-adoption-options，仅原组织/场景最新发布候选，排除草稿/退役且不回落；preview增加严格原问题/目标可选精确指标及before/after差异，纳入hash。前端受影响55项通过，补正文/存储测试后新组件5项通过；四尺寸独立组件axe严重/关键0与截图已留存。修复独立加载新口径执行模块时的Editor循环导入，独立进程回归通过；新口径实际三类交付生成恢复3 passed。生产构建通过但Editor工作簿引擎资源块697.4 KiB超396 KiB门槛，不放宽预算。以上仍为组件及分阶段集成证明，首次公开确认到真实管理/全原生四格式连续路径、完整Editor/图表视觉、真实模型/StarRocks/业务签认和其余§5要求继续待完成，§5.4不勾选。


**采用新口径保留业务范围增量（2026-11-11）：** 原请求的domains现纳入不可变ReportRequestSummary和explicit/default条件记录，新口径从可信摘要恢复，不再硬编码全部六域。严格代码/非空/去重及独立导入契约有定点证据；原预算专题三类真实文件生成/恢复/内部HTTP均核对规划payload和恢复请求仍仅budget，3 passed（66.38秒），隔离数据库清理成功。此为受控模型/SQLite及真实PG技术验收，不替代首次公开确认连续全链路、真实StarRocks/模型与业务签认；其他未完成项保持原范围。详见进度记录。

**首次公开采用口径的连续交付增量（2026-11-11）：** 从实际父Editor首次HTTP预检/POST，经真实管理新依据确认、Agno持久队列、正式计算/画像、原生分析Task/章节及格式生成，连续到四格式HTTP下载和对应新Editor路由授权，三参数3 passed（183.42秒），隔离库清理成功；没有预建目标执行/准备或阶段间更换模型端口。原300与新口径过滤后的200、单次查询/Task、重复确认不重跑及原报告不变均有断言。修复Step默认自动重试和PPTX同次恢复的提纲/哈希不一致；图表核验失败告警与告警存储异常仍非阻断签发，故障证据见进度记录。四格式样例/哈希见artifacts/2026-11-11-policy-adoption-public-flow。模型/SQLite仍受控；准备未知状态显式恢复、含图/完整浏览器/导出视觉、真实模型/StarRocks/业务签认、资源预算及其余§5保持未完成，不勾选整体闭环。

**准备未知状态核对增量（2026-11-11）：** 新口径分析准备及文档job新增内部显式身份确认参数；默认继续拒绝文件已落盘但未登记的状态。确认固定路径/size/sha256后，重新验证可信执行、正式计算/CSV、持久详细计划及已登记画像依赖，文档另外核对最终提纲与精确CSV集合，全部通过才补登记原文件。核对不重新规划、画像、取数或创建job；补登记成功响应丢失仍可按原登记恢复。此为内部能力，公开只读核对、显式恢复HTTP/队列续跑与Editor按钮尚未接入，不能计为产品恢复闭环；§5.4及整体目标保持未完成。定点证据见进度记录。

**准备只读核对HTTP增量（2026-11-11）：** 已增加会话授权的GET recalculations/{taskId}/preparation，读取可信已登记执行并核对实际分析/文档准备文件，区分未生成、已登记、待确认、无法核验及格式不适用。读取不登记或派发、不查询业务库/调用模型；不完整身份读取不视为文件不存在。实际图谱/章节重建最终提纲后核对文档job。三类真实PG准备/恢复3 passed（71.08秒），HTTP授权/路由1 passed，任务解析/服务委托5 passed，静态签发守卫1 passed；证据分层及受控端口边界见进度记录。显式确认HTTP、终态核验/后台续跑及Editor恢复按钮尚缺，整体仍未完成。

**准备文件显式确认HTTP增量（2026-11-11）：** 已接写会话/Origin/CSRF的POST preparation/confirm，使用GET返回的目标stateVersion及精确文件身份，重验原生执行/持久队列终态后单次CAS补登记。观察失败、活动票据、状态并发变化和文件身份变化均不补登记；已提交响应丢失先GET读回，同身份幂等，响应明确executionResumed=false。三类真实生成恢复3 passed（72.21秒），新增真实CAS并发/未知提交XLSX节点1 passed（23.43秒）；HTTP/服务委托/原生票据与终态保护集合10 passed（10.48秒），隔离库清理成功，受控端口边界见进度记录。后续原生持久派发/恢复读回与Editor按钮仍缺，不能将补登记当作后台续跑完成；其他§5及整体完成判据保持不变。

**确认后原生持久续跑增量（2026-11-11）：** 新增独立原生Workflow票据及公开resume/恢复票据GET，输入绑定原任务/上下文/文件，原failed票据不修改；worker启动resolver可重建，Step和队列均单次尝试。候选在提交前提供稳定recoveryId，未知派发先读回，同文件重复提交不重跑，不同准备文件不能并行续跑；后台状态不冒充交付完成。真实隔离PG队列重建/响应丢失及HTTP/身份保护有分层证据，最终定点11 passed、队列/作用域3 passed和启动生命周期1 passed，详见进度记录。业务执行端口仍受控；真实准备故障到公开续跑/四格式实际交付连续验收、Editor恢复按钮和其他中间状态尚缺，整体闭环不勾选。

**公开准备故障与Editor恢复增量（2026-11-11）：** 保留正常三例并增加三类准备文件写后登记前故障，最终六例6 passed（364.61秒），真实隔离PG清理成功。公开GET精确核对、resume、worker重建及PPTX派发响应丢失后GET原票据，连续到四格式实际下载/内容独立核对、新Editor授权，原报告不变，业务SQL及分析阶段不重复。实际文件及身份见[恢复样例](../reports/artifacts/2026-11-11-policy-recovery-public-flow/README.md)。Editor已接准备状态/明确续跑/固定身份缓存/未知结果只读恢复/冲突后显式重新确认，恢复组件7例及四宽度独立浏览器检查通过（axe严重/关键为零），见[HTTP契约](../reports/2026-11-10-snapshot-verification-http-contract.md)与进度记录。模型/SQLite仍受控；独立组件不等同完整Editor及导出视觉。其他中间未知状态、同文件后续失败再次显式恢复、含图四格式一致性、资源预算、真实集成/业务签认和其他§5保持未完成，不勾选整体闭环。

### 5.5 错误反馈与发布影响（T3/T7/T8）

**Create:** `smart_reporting/management/report_issue_reviews.py`（复用现有admin审计），必要路由放T3路由模块；前端反馈置于T8依据面板，不增加独立工单平台。
**Test:** 新建`smart_reporting/tests/test_report_issue_reviews.py`覆盖C36/C37。

- [ ] 报告用户通过现有报告修订授权提交问题，服务器绑定修订和对象；管理员读取/裁定使用管理会话，公开下载链接不能用于提交管理修改。
- [ ] 提交、裁定、发布、重算用显式关联ID贯穿；accepted生成候选变更与反例，正式规则必须显式发布。AI只能建议，不直接更新指标或关闭问题。
- [ ] 新增`GET /statistical-policies/{id}/impact`和`POST /metrics/{id}/versions/{revision}/retire`、`POST /statistical-policies/{id}/versions/{revision}/retire`，均在管理API前缀下；影响查询读取精确依赖和ReportBasis，无企业级全局扫描。
- [ ] 退役事件独立保存；默认引用退役对象时新请求明确缺可用规则，无静默回退；已有新模型run按登记版本完成并披露已知问题，安全撤销仍禁止读取对应资源。
- [ ] C36复用C02错误均值反例，闭环必须能从原问题查到修复测试、新口径和新报告修订。仅展示“已收到反馈”不算完成。

**反馈授权与裁定增量（2026-11-11）：** 复用既有问题表及管理审计，已接报告修订会话下GET/POST issue-reviews和管理GET report-issue-reviews/POST decision。运行/依据/用户/线程与对象由服务器核对，同ID幂等及精确读回、组织/修订隔离、单次管理CAS、accepted候选改动与反例均有实际隔离PG证据；反馈不发布规则或改写原报告。客户端声明回归case ID不足以证明修复，resolved当前明确409，未开放伪关闭。最终反馈/Editor分层7 passed（15.94秒），管理鉴权回归2 passed、导入回归1 passed；日志见[反馈证据](../reports/artifacts/2026-11-11-report-issue-reviews/README.md)，[HTTP契约](../reports/2026-11-11-report-issue-review-http-contract.md)说明边界。反馈UI、Editor到PG同次连续链、正式修复版本/实际回归与新报告父链关联、可核验关闭及C36/C37仍未完成，本节与全目标不勾选。

**Editor反馈UI增量（2026-11-11）：** 已接入依据浏览器“反馈报告问题”，候选取本修订来源目录，显式选择对象/类型/描述；确认前缓存，响应未知及重开只读原issueId，GET明确为空后才允许同内容显式重提。问题列表保留分页，中文状态将accepted展示为“已采纳，待修复”，同时显示理由/候选改动/反例；业务名优先，登记ID折叠。反馈+来源浏览器53例通过，新增实际浏览器装配候选1例通过；四宽度独立组件axe严重/关键零、无溢出、键盘焦点/单POST有截图及日志，见[反馈UI证据](../reports/artifacts/2026-11-11-report-issues-ui/README.md)。管理裁定UI、Editor至PG连续验收、正式修复/回归/新报告与关闭链仍缺，本节保持未完成。

**管理裁定UI增量（2026-11-11）：** 已增加工作台“报告问题”与认证深链，沿用组织与既有反馈接口。逐项核对原反馈，显式登记理由/候选改动/反例；提交前缓存，未知响应及重开先读原问题，版本未变才可明确重提，其他更新保留原内容并显式重新核对。组织切换隔离缓存，采纳仍为待修复，不提供伪关闭。ManagementApp受影响十例通过，路由隔离PG鉴权一例通过且清理成功；四宽度实际ManagementApp加受控HTTP验证焦点/单POST/组织隔离、无溢出、axe严重/关键零。最终TypeScript与管理构建、登录291.8 KiB/列表428.7 KiB gzip预算通过，见[管理裁定UI证据](../reports/artifacts/2026-11-11-management-issue-reviews-ui/README.md)。尚缺Editor至真实PG连续链、正式修复版本/实际回归/新报告关联及C36/C37可核验关闭；Editor工作簿预算及其他§5/T1–T9原范围保持，本节不勾选。

**正式修复版本关联增量（2026-11-11）：** 既有accepted决定可关联精确已发布指标/口径/原件/证据集合，复用现有字段/表/CAS/审计。核验原依据身份、组织、内容哈希、退役/撤销及口径指标依赖一致性；原报告已有同版本不可冒充新修复。未提供关联保留旧值，显式空数组解除；已修正HTTP默认值展开导致的清除。10例反馈、1例真实PG提交丢响应/审计回滚、6例口径发布回归通过并清理成功。两端可读正式修复引用；四宽度管理实际App及报告独立组件无溢出、axe严重/关键零。见[修复关联证据](../reports/artifacts/2026-11-11-report-issue-fix-links/README.md)。状态仍为待修复；尚缺界面发布版本选择、实际回归执行/可读取证据、新报告父链/不重算裁定核验及关闭C36/C37，不勾选本节。Editor工作簿预算仍失败，真实集成/业务签认和全部T1–T9/§5原范围保持。

**实际快照回归增量（2026-11-11）：** 已有严格预期断言、冻结CSV原生复算与不可变核验回执；服务端核对组织/可信工作区、精确修复依赖、查询与文件身份、完整根指标分组断言。回执保留成功/失败、预期与实际、哈希/构建，提交及精确GET/历史分页沿用管理认证与CSRF/CAS，实际PG证明审计回滚和提交响应丢失读回。原生190/300及六类篡改、预期契约、服务和HTTP有定点证据，见[回归核验证据](../reports/artifacts/2026-11-11-report-issue-regressions/README.md)。verificationLevel为snapshot_recomputed、businessApproval仍not_performed；PG/HTTP用预算合计300，不冒充C02业务纠错。问题仍accepted，resolved继续409；尚缺版本选择/回归界面、新报告父链或不重算核验、当前证据保留检查及C36/C37连续关闭链，本节不勾选。全部§5/T1–T9、工作簿预算和真实集成/业务签认要求保留。

**正式版本选择界面增量（2026-11-11）：** 管理采纳表单已增加指标/口径/已发布原件/证据集合候选，按问题组织读取历史正式版本，搜索和游标分页保留选择；原已用/退役/撤销等禁选原因可读。同对象只保留一个精确版本，完整目标引用在POST前缓存，未知响应重开按目标引用读回。新增fix-options复用原正式修复核对器，完整组合保存时重新核验；四类型隔离PG两节点通过、受影响管理前端五例通过，证据见[正式版本选择](../reports/artifacts/2026-11-11-report-issue-fix-picker/README.md)。回归提交/历史UI、新报告父链或明确不重算裁定、当前证据可读核验及C36/C37可核验关闭仍缺，本节保持未完成；其他§5/T1–T9及Editor预算/真实集成要求不变。

**回归操作与历史界面增量（2026-11-11）：** 既有问题详情新增可信计算选择、全部分组独立预期表单、提交/精确读回及成功失败历史；目标GET不返实际答案，不读CSV，POST仍执行实际核验。完整请求先缓存、未知重开按requestId精确读取，未登记先核对问题/修复引用，未变才允许显式重提，变化保留本地预期。新增目标隔离PG节点及受影响提交/HTTP两节点通过；前端空预期/缓存失败/丢响应/并发变更/失败差异两例通过。四宽度实际ManagementApp加受控HTTP验证两分组、单POST、组织隔离、焦点及无溢出/axe严重关键零；修正新增失败标签对比度，最终构建通过。见[回归界面证据](../reports/artifacts/2026-11-11-report-issue-regression-ui/README.md)。尚缺Editor至真实PG连续链、新报告父链或明确不重算裁定、关闭前文件保留核验、C36/C37及业务签认，本节不勾选，全部§5/T1–T9与资源预算等原范围保留。

**回归当前证据核验增量（2026-11-11）：** 已增加显式选择原问题回归回执的只读检查，核对当前问题/修复版本、可信目标及原回执哈希并复用原生计算器实际重读冻结CSV；历史passed在文件删除后返回不可复核，旧记录不改写。所选通过证据并集覆盖全部显式修复指标；复算前后版本核对、防止并发签认旧结论。隔离PG快照一例、并发/鉴权两例、受影响原提交两例及应用装配一例通过；界面可读检查时间及具体原因，四宽度无溢出/axe严重关键零。见[当前回归证据](../reports/artifacts/2026-11-11-report-current-regression-evidence/README.md)。regressionEvidenceReady只是当次回归CSV可复核，不是关闭许可，businessApproval仍not_performed/issueClosed=false。新报告父链/不重算裁定、原件当前可读/保留、业务签认与可核验关闭、C36/C37等尚缺，§5.5及全目标不勾选。

**原件与可信父链核验增量（2026-11-11）：** resolution-evidence-check先实际复核CSV，使用原生新口径不可变登记核对新旧依据父链，不接受同组织独立报告。原报告/目标依据及修复引用所需业务原件实际读取，核验登记身份并在IO后重读审核状态版本；删除实际原件与并发审核、HTTP授权/CSRF/跨组织/服务缺失及受影响回归有隔离PG证据。管理端分别显示CSV、原件及父链状态，businessApproval仍not_performed/issueClosed=false。浏览器ariaSnapshot确认loading图标使按钮可访问名称漂移；固定标签后四宽度键盘/组织隔离/刷新不重查、无溢出/axe严重关键零。见[原件与父链证据](../reports/artifacts/2026-11-11-report-resolution-evidence/README.md)。父链不等于最终交付，正式关闭、C36/C37和全计划其余要求继续未完成，本节不勾选。

**新报告当前文件交付核验增量（2026-11-11）：** 同一检查接口现恢复原生新口径执行及原编辑修订任务，复用身份/完成读取器核对完整输入、父链/预留编号、completed状态、成稿清单/正文及全部请求格式实际文件SHA/size，IO后重读父子stateVersion。PDF/Word、PPTX、XLSX原生持久队列三个定点节点通过（250.43秒），含真实文件篡改拒绝/其他格式保留、无新增业务查询及不改报告状态；管理缺服务/原件/父链两节点通过。界面将文件身份与原验收结果分别显示，四宽度各3POST、无溢出/axe严重关键零，最终管理构建及292.5/429.4KiB预算通过。见[交付核验证据](../reports/artifacts/2026-11-11-report-issue-delivery-checks/README.md)。这不证明纠错计算完整进入新报告正文或业务预期正确；业务签认、明确不重算裁定/正式关闭、C02/C36/C37连续链及所有其他原范围继续未完成，本节不勾选。

### 5.6 保留、恢复与验收（T7/T9）

**Modify:** `smart_reporting/report_editor/trace_retention.py`、T7 basis及T9验收脚本。
**Test:** C38加入`test_report_basis_persistence.py`与恢复演练。

- [ ] 通过既有保留机制登记ReportBasis引用，reproducible_until按实际部署策略/资源期限计算；无策略返回unknown，不硬编码永久保留。
- [ ] 定点测试清理不误删有效引用；显式到期/撤销后UI显示不可复现原因；证据到期/撤销不自动撤销独立的产物下载授权，下载仍核验当前产物授权与身份。
- [ ] PG+原件/CSV联合备份恢复演练，分别模拟仅索引丢失和原件丢失：前者可重建，后者明确不可复现，不能都显示恢复成功。
- [ ] 验收manifest增加问题覆盖、数据充分性、ClaimSupport、revision依赖一致性、反馈闭环和资源可用状态，38例逐项记录结果。

### 5.7 修正原计划的实施精度

- 执行顺序改为T1→T2→T4→T5→T3→T6→T7→T8→T9，确保口径引用真实已发布证据。
- 比率引用由只有指标ID改成精确`MetricVersionRef`，避免口径号不变、分母定义却漂移。
- 原计划要求“单组织全部业务Profile切换”但只验收3指标，存在覆盖断层。T1必须清点现有报告场景；本次上线只开放已验证试点场景，其余新请求明确“尚未登记新统计口径”，不走旧fallback、不假装支持全部报告。若业务要求保留所有场景可用，必须先逐场景重新登记并验收，再执行整体切换。

### 5.8 执行契约审查补充（2026-11-09）

以下要求并入原任务和C01–C38子场景，不新增平台阶段。

- [ ] **T2/T6，C24/C34：** MetricRequest与MetricResult使用精确metric_version，并关联basis_id；结果登记calculation_id及既有trace fact身份。期间、维度、筛选和单位参与事实身份，禁止同名不同版本串用。
- [ ] **T2/T6，C12/C32：** 统计口径增加严格类型DataReadinessPolicy，声明预期期间/对象集合、数据更新依据和允许延迟；缺规则为unknown。合法零交易、未同步与未结账必须有独立反例；不得仅凭无记录判断完整或下降。
- [ ] **T7/T8，C13/C14/C31：** MetricSelection登记resolved/ambiguous/unavailable、候选差异、选择理由及来源（explicit/scenario/clarified）；会改变结论且无法消歧时该问题保持未解决，其余继续。用户修正选择后按依赖失效，不能仅保存候选而不说明实际选用。
- [ ] **T5/T7，C21/C28：** EvidenceSearchReceipt包含hits、status及issue_codes，区分无命中、服务不可用、不适用和撤销。恢复时对保存片段/缓存重验当前授权，再进入模型上下文；撤销内容不能经缓存重新注入。
- [ ] **T7/T8，C27/C35：** 重算明确verify_snapshot/refresh_data/adopt_policy三种模式；前两者固定原规则，后一种显式选新规则并登记新依据。固定规则复核用原快照，重新取数登记新计算批次；规则/数据变化分别披露。任务绑定父修订，重试读回不覆盖旧依据。
- [ ] **T3/T7/T8，C36：** 报告修订授权下提供POST/GET issue-reviews及POST recalculations、GET recalculations/{taskId}；管理会话提供GET report-issue-reviews及POST report-issue-reviews/{issueId}/decision。路径分别沿用既有报告路由前缀与管理API前缀，实施时登记HTTP契约。关闭时有裁定、修复版本、回归证据和新修订或未重算理由，不能以accepted代替resolved。

**2026-11-10 实施增量（非闭环完成）：** 固定原依据的刷新计算已可按可信父回执/意图完整装配为原生MetricPlanningContext；同组织管理库与实际CSV核验后，原生事实和表格绑定使用新fact身份，本期/基期不允许混用旧批次。已完成隔离PG/SQLite与定点原生分析测试，详情见进度账本“T7 新计算接入原生分析与表格”。整报告修订持久登记、后台调度、正文/静态图及Editor/PDF/Word新交付仍待接入，不据此勾选重算闭环或真实StarRocks验收。

## 6. 完成判据和停止条件

- **工程完成：** T1–T9对应工程证据齐全，38例均有真实结果；目标函数测试不再失败；未引入旧Profile运行适配；新模型恢复、权限及非阻断签发通过。
- **业务完成：** 原始材料与计算定义签认，真实报告对账差异可解释，独立用户完成任务；未执行不得标完成。
- **上线准备完成：** 真实服务探针、部署同版、备份/切换演练、配置重新登记检查全部完成；实施计划不是上线授权。
- **局部停止条件：** 正式业务定义缺失时不发布为正式口径；Agno过滤探针失败时不开放业务检索；粒度/关联未定义时不计算该指标；旧配置不得成为默认兜底。可继续不依赖该条件的工程任务。

## 7. 计划自检

- [x] 最新“不做兼容”已覆盖模型、API、默认选择、运行恢复、配置加载及UI；历史文件保留与旧契约兼容区分清楚。
- [x] 指标/口径/知识/计算依据分别有任务与接口，不再把Profile改显示名作为交付。
- [x] 六项缺口映射：业务理解T3/T8，计算T6，知识T4/T5，恢复T7，证据支持T5/T7/T8，独立验收T1/T9。
- [x] 开源README核对与实际源码/探针验证分开，Agno安装版接口写明。
- [x] 历史工作树和产物不自动删除；不误删其他含profile名称的模型设置/数据画像功能。
- [x] 语义告警不阻断报告，安全失配不使用对应资源，PDF/Word签发回归明确。
- [x] 原始材料/真实业务签认未取得时的事实边界明确，不伪造上线验收。

- [x] 本轮闭环审查：新增C31–C38，按原任务补齐问题覆盖、数据就绪、背景依据、产物一致性、重算、反馈、退役与保留；未新增平台阶段。
- [x] 已修正T3/T5执行依赖、比率精确版本以及三指标试点与全业务停旧之间的范围断层。

#### 2026-11-10接续：新修订PPTX最终渲染进展

- 已接通显式子执行的原生PPTX渲染，实际文件及最终回执只登记子执行；目标期间明确使用[start,end)。真实引擎/独立python-pptx、PG恢复及原状态隔离节点通过；生成完成响应丢失不重新渲染，缺失验收记录保留文件并返回未通过，文件身份变化拒绝使用。
- 技术证据见`../reports/artifacts/2026-11-10-revision-pptx/`及进度台账。受影响PPTX与全部规定非阻断节点99 passed、1显式skip；最终PG新增故障节点1 passed；未重复全项目测试。
- 仍需：中文限制提示代替正文技术码；冻结主题契约；含图重冻结；PDF/Word/XLSX最终编排；新修订Editor/HTTP/controller及采用新口径。PPTX此次是合成技术fixture，不能替代真实模型/业务/专家验收；公开refresh/adopt继续503，整体未完成。

#### 2026-11-10接续：新修订XLSX汇编与Office恢复

- 已接通显式子执行的XLSX固定汇编：正式新事实/数据集→原CodeMode脚本→原Node工作簿引擎→真实文件/独立结构验收→子执行登记。计算窗口、事实身份、精度/空值及来源映射沿用既有正式契约，不借用旧会话或正文数值。
- 不可变receipt绑定实际工作簿、spec、脚本、执行回执和子执行；响应丢失按登记恢复，缺失/篡改回执保留文件并未通过，未知文件不自动重建。XLSX及PPTX已生成文件恢复不依赖原CSV/Markdown重新可读，源身份与交付身份分别核验；跨修订/已替换交付仍拒绝使用。
- 技术证据见`../reports/artifacts/2026-11-10-revision-xlsx/`和进度台账。已生成真实XLSX并由openpyxl/LibreOffice读取；这不等于新修订公共HTTP/Editor/controller完成，也不是业务/模型/真实StarRocks验收。
- 剩余完整目标不缩减：PDF/Word编排/交付、含图重冻结、XLSX修订完成登记及全部格式Editor/HTTP/controller、采用新口径、问题重规划/反馈闭环和真实验收；限制信息中文化与来源布局亦待处理。公开refresh/adopt继续503。

- 最终定点续记：Office恢复顺序反例修复后，PPTX及规定非阻断/两格式HTTP故障集合101 passed、1显式skip；新修订XLSX真实源文件损坏恢复PG1 passed（24.71秒），PPTX对应PG1 passed（25.28秒）。所有隔离库清理成功；当前目标Ruff和diff检查通过，仍未满足整体完成判据。

#### 2026-11-10接续：新修订文档正文装配

- 已接通显式子执行的已登记章节→原生Markdown/确定事实表格→清单及追溯→子完成回执；使用登记大纲、新数据上下文及精确引用，不修改原job的标题编号或原会话。
- 装配完成回执冻结待提交checkpoint，提交前中断和提交后响应丢失可恢复，重复读取不改写产物或累加告警；部分文件已登记但尚无完成回执的更早中断只返回未知结果，controller/管理员核对路径仍需补齐。
- 受影响9文件及规定非阻断集合503 passed、1显式skip；空引用反例修复后最终真实PG节点1 passed（24.60秒），隔离库已清理。技术样例见`../reports/artifacts/2026-11-10-revision-document/`及台账。
- 章节内容来自明确“解释不可用”的受控原生SectionArtifact，不是真实章节模型；实际装配已产生带本次FactRef的Markdown/表格，尚无新PDF/Word。后续仍须原生章节Task、文档job/最终渲染、含图重冻结、Editor/HTTP/controller及全目标业务验收；不据此勾选刷新闭环，公开refresh/adopt继续503。


#### 2026-11-11接续：精确计算到纠错内容与PPTX绑定

- 关闭准备核验已将当前通过回归的精确计算与本执行trace、可见正文/冻结表格相连；basis/revision/receiptId/完整结果和根指标全部分组必须一致。factPresentationReady独立于文件交付和原验收，不构成业务签认或关闭许可。
- 连续链首轮PDF/Word及XLSX通过、PPTX缺绑定失败；修复后PPTX单节点通过（43.08秒，隔离PG清理成功），页面与归档正文共用精确来源投影，并明确标registered_result_projection_v1。已归档分次运行的实际四格式及HTTP证据，见../reports/artifacts/2026-11-11-report-issue-content-binding。来源和指针错误/改数均失效，内容失败不丢独立交付文件。
- 受影响PPTX/HTTP故障/静态守卫及测试替身修正定点通过，规定非阻断其余75 passed/1 skipped，前端四来源展示例/TypeScript及目标检查通过。真实模型/StarRocks、C02执行率纠错、业务签认、正式关闭事务及其他§5/T1–T9仍未完成；不勾选§5.5或整体闭环。


#### 2026-11-11接续：C02管理纠错与实际HTTP装配补缺

- C02现有真实隔离PG管理/反馈/正式发布/原生采用依据与DuckDB原始行证据：原rate@1项目均值70，显式rate@2合计实际190/预算300，HTTP预期70失败、63.33/两位通过且CSV可复算；原定义/依据/回执不重写。C37同源HTTP影响、精确旧版本退役及默认不可用/拒绝新请求、不静默回退均有证据。
- 实际create_base_app此前未装配指标/口径路由，真实404反例后已复用既有服务装配；真实应用鉴权/CSRF及C02/C37最终两节点通过，受影响既有HTTP三节点通过，隔离库清理成功。16份真实证据及日志见../reports/artifacts/2026-11-11-c02-managed-ratio。
- 此案例尚未从实际父Editor首次反馈，经原生持久队列完成新报告与四格式内容核验；关闭准备如实deliveryReady/factPresentationReady=false，问题仍accepted，业务未签认。C36完整闭环、C37完整用户体验及全部其他§5/T1–T9继续未完成，不勾选完成。


### 2026-11-11 C02纠错结果进入四格式的原生执行增量（整体仍未完成）

- C02真实70/63.33反例现使用原生采用选择及calculate_adoption_metrics计算意图/结果；新原生分析、正文/幻灯片/工作簿及渲染消费同一精确回执，不重复业务查询。三个格式节点最终3 passed，实际四格式SHA/size、HTTP下载、新Editor上下文与trace根事实覆盖均已核对并归档至../reports/artifacts/2026-11-11-c02-native-formats。
- 严格关联红例揭示表头单位核对误拒绝精确循环小数，已加Decimal精确比较，保留单位和舍入边界；受影响表格84 passed，规定非阻断76 passed/1 skipped。PDF/PPTX实际渲染检查无截断，XLSX按现有精度保护保留精确文本。三次独立交付不是单次四格式运行；不证明静态图或所有内容等价。
- 父报告状态/类型仍为夹具，未从完整原70报告的Editor首次反馈经过整个公开持久队列；关闭准备仍缺该问题的正式完成任务，deliveryReady/factPresentationReady=false、businessApproval=not_performed、issueClosed=false。下一步须沿真实公开流程接通，不手工补完成回执。§5.5/C36/C37及全§5/T1–T9、资源预算、真实集成/业务签认/备份保留等原范围全部保留，不勾选完成。

### 2026-11-11 C02实际原报告、公开反馈及持久队列连续验收（整体仍未完成）

- 已实际生成原70报告，并从其Editor授权HTTP首次提交问题，经管理裁定、正式发布rate@2/monthly-budget@3、公开采用确认202、实际Agno持久QueueWorker和全原生生成，连续完成新63.33报告、HTTP下载及新Editor上下文；未预建此目标执行或手工补完成任务。三个独立格式请求覆盖PDF/DOCX、PPTX、XLSX。
- 最终追加带日期原始行、精确规则留存与退役后新请求拒绝的三参数3 passed（108.59秒），共用helper原三个节点3 passed（59.99秒），全部隔离库清理成功。回归70失败/63.33通过，关闭准备四项机械ready均true，原依据/正文/checkpoint/实际文件不变，重复POST不重查；业务未签认/问题未关闭，resolved仍409。C37精确影响/默认不可用/新请求拒绝及历史原新报告可读均有断言。
- 证据见../reports/artifacts/2026-11-11-c02-public-flow，含原/新文件、正式规则/原始行/CSV、实际完成任务、正反回归、trace/Markdown和离线归档字节复核脚本。模型响应和数据库执行端口分别为受控fixture/DuckDB，种子类型仍为fixture；不代表真实模型/StarRocks或最初自然语言入口。四格式实际渲染已查看，PDF及Word转换PDF独立提取文本均确认封面半开期间与正式请求一致；不勾选完整Editor及整体视觉验收。
- 正式关闭事务/业务预期来源与签认/明确不重算裁定、C36/C37完整用户体验、静态图与四格式等价、其他恢复、工作簿资源预算、真实集成/中文业务检索及保留备份与全部§5/T1–T9仍保持原范围未完成。§5.5不勾选，没有签发链新增步骤、业务库修改、提交或部署。

### 2026-11-11 回归预期来源及显式签认后端（整体仍未完成）

- 管理HTTP已可显式签认所选精确回归的预期值，要求逐回归的已审核/发布原件修订、定位和原文摘录及推导说明。真实字节和解析位置核验后复算当前CSV，在既有不可变依据回执表登记问题版本、修复引用、原回归哈希、原件/审核/解析身份及可信登录账号；不新增审批平台/表/迁移。签认仅限regression_expected_values，不修改原机械回归的not_performed或问题accepted状态。
- 同ID同输入恢复/异输入409、真实并发唯一、审计失败回滚/提交丢响应读回、实际不可变触发器拒绝UPDATE、伪造来源/失败回归/原件缺失及IO并发变化已有隔离PG证据。HTTP鉴权/CSRF/组织、禁止伪造签认账号和撤销后历史不返回摘录通过。证据见../reports/artifacts/2026-11-11-report-business-expectations；合成管理员签认只是机制验收，不是实际业务专家签认。
- 签认UI、关闭准备显式消费签认及当前有效性重验、正式关闭CAS/审计/未知结果读回、明确不重算裁定仍待接入。历史签认HTTP明确currentEvidenceStatus=not_checked，不据此自动批准报告或关闭问题；resolved仍409。全部§5/T1–T9及真实环境/资源预算/保留备份等原范围保留，§5.5不勾选。

### 2026-11-11 关闭准备显式选择签认及当前有效性（整体仍未完成）

- resolution-evidence-check新增可选businessApprovalRequestId，仅显式选中才恢复签认；重验当前问题版本/精确修复/完全相同回归集合及完整hash、预期原件审核与解析身份，将其来源纳入同次真实文件读取。IO后重读问题/原件及签认身份，变化409；历史签认不被自动继承或改写。
- businessApprovalReady和businessApprovalCheck分别表示本次就绪与具体原因；选中且当前可复核才explicitly_approved。来源删除/撤销、CSV失效、签认未知/问题更新、同值不同回归均不得通过；有效签认不能代替交付或关闭。红例后首轮7 passed，最终新增9场景与既有2节点11 passed（30.81秒），隔离库清理成功；证据../reports/artifacts/2026-11-11-report-current-business-approval。
- 管理签认/来源选择及关闭准备UI尚未接入，现UI不提交签认选择、不会自动批准。正式关闭事务/明确不重算、业务实际签认及所有§5/T1–T9原范围仍未完成，resolved仍409、§5.5不勾选。未改签发链、业务库、提交或部署。

### 2026-11-11 管理端显式签认与恢复增量（整体仍未完成）

- 上轮为进度核对，无实施增量。本轮收尾已有签认界面，增加已发布原件候选契约和证据归档；来源按业务标题搜索/分页、读取精确修订及人类可读定位。可使用原报告引用过的规则再次独立核对，不改变正式修复候选语义。
- 管理员明确选择当前通过回归、独立来源/摘录及推导理由并确认后才POST。完整输入先按账号/组织/问题缓存；缓存失败不发请求。丢响应重开仅精确GET；404先核对当前问题版本及修复引用，变化保留输入不重签。规范化完整requestHash防止同ID异输入误用，历史签认不代表当前可用。
- 明确采用签认才向关闭准备发送businessApprovalRequestId及相同回归集合，变更回归选择清除签认。来源候选真实隔离PG节点1 passed（9.96秒）且清理成功；受影响管理端20 passed、扩展签认组件最终7 passed（4.36秒）。实际ManagementApp加受控HTTP四宽度各1次签认/1次检查，键盘、重开读回、组织切换、刷新不重签、无溢出及axe严重关键零，390截图已查看；不冒充真实PG连续业务签认。
- 最终TypeScript/管理构建通过（6.67秒），gzip登录292.5/列表429.5KiB通过；git diff检查通过，专用5188 Vite停止。归档artifacts/2026-11-11-report-business-approval-ui含原始日志、截图、浏览器记录和离线身份复核。没有重复完整测试、业务库修改、签发链变更、提交或部署。
- resolved仍409；正式关闭CAS/审计/未知结果恢复、明确不重算裁定、实际业务签认、C36/C37完整连续体验、真实集成、静态图四格式、工作簿697.4KiB>396KiB、其他恢复/保留备份及全部§5/T1–T9继续未完成，§5.5不勾选。

### T3/T7/T8 正式关闭与明确不重算裁定（2026-11-11，接续）

- 上轮签认界面归档为有效进展。本轮新增原生不可变BasisIssueResolutionReceipt及resolutions POST/精确GET，复用现有回执表/问题CAS/审计，不加表或迁移。关闭明确选择recalculated或not_recalculated，两者均需当前正式修复、完整通过回归、原件和显式业务签认；前者另需交付/精确事实就绪并绑定真实输出修订，后者须明确理由且保留原报告，不能冒充新交付。
- 文件IO在管理事务外，最终写入锁问题和原件审核行，重验问题/正式修复/签认/原件审核身份。回执保存精确回归及签认hash、核验原件身份和实际新文件SHA/size/原验收结果，与状态/审计原子写入。旧decision手填resolved仍409，新入口才可核验关闭；关闭不改变验收或下载。
- 缺模块红例后首批两节点2 passed（12.57秒）；HTTP缺路由红例后，首次审计故障未注入路由独立ScopeService，查明后改类级定点注入，实际HTTP/回滚1 passed（10.61秒）。丢提交响应/不可变UPDATE拒绝及检查后撤销两节点2 passed（12.33秒）。并发首次后一请求在检查尾部因已关闭报409，修正为仅精确读回已提交的同请求，3个定点节点通过（13.93秒）。
- C02新增合成签认关闭连续链：完整旧70报告Editor反馈→正式发布→公开采用202→Agno耐久队列completed→新63.33 PPTX→独立原件签认→关闭version4→精确读回/重复POST，旧原件/依据/Markdown/checkpoint/报告文件不变、业务查询仍4次。最终含交付快照及精确文件断言、HTTP/并发/旧decision防伪关闭4 passed（33.04秒），隔离库清理成功；其余定点结果与原始证据见artifacts/2026-11-11-report-issue-resolutions。
- 本次模型受控、业务端口隔离DuckDB、独立材料及管理员签认合成；仅PPTX完成新的签认关闭连续链，不冒充真实专家/StarRocks/模型或其他三格式正式关闭。管理关闭表单及未知结果恢复UI、C36/C37完整连续浏览器、真实业务验收、静态图四格式等价/完整Editor视觉、其他恢复、工作簿697.4KiB>396KiB、中文检索/保留备份和全§5/T1–T9仍未完成，§5.5不勾选。没有签发链变更、业务库修改、完整项目测试重复、提交或部署。

### T3/T7/T8 管理关闭与报告侧状态（接续）

- 管理员明确选定签认和回归，完成当前核验后选择已交付新报告或本次不重算；关闭理由和保留原报告需明确确认。请求先缓存；未知响应只读回，明确未登记且版本和修复引用不变才允许重提；冲突保留原输入，坏缓存不覆盖。
- 关闭事务内在问题记录保存精确关闭请求标识，授权详情可直接读取历史回执。报告侧显示裁定、回归案例、是否重算及新修订，原报告保留。已关闭不表示报告验收通过。
- 管理关闭组件10项通过，前期受影响管理端24项通过，隔离PG重开关联1项通过并清理。实际ManagementApp使用受控HTTP验证1440/1280/768/390，每尺寸一次签认、一次核验、一次关闭、两次关闭读回（未知恢复、历史详情）；无溢出、axe严重/关键零。管理构建通过，gzip登录292.5/列表429.4KiB。证据见artifacts/2026-11-11-report-issue-resolution-ui。
- 尚未完成真实PG与浏览器同次C36/C37、真实模型/StarRocks/专家业务签认、四格式静态图及完整Editor视觉、工作簿预算、备份恢复和完整T1–T9验收；不勾选整体。

### T3/T7/T8 四格式正式关闭连续验收（2026-11-11，接续）

- 将 C02 正式关闭验收扩展为三个独立请求：PDF/Word、PPTX、XLSX。实际从原70报告反馈，正式发布修复，经 Agno 耐久队列交付新63.33报告，再签认、关闭并精确读回；原报告内容、依据、检查点与产物不变，重复操作不增业务查询。
- 逐一读取实际交付文件验证纠错结果，关闭回执的格式、哈希、大小与下载文件完全一致；关闭的问题记录可用精确请求ID读回，并关联真实新修订。三项定点用例通过（119.57秒），隔离库清理成功。归档见 artifacts/2026-11-11-c02-resolution-formats。
- 受控模型、隔离DuckDB及合成独立原件；不代表真实模型、StarRocks或专家签认，也不代替同次真实PG浏览器C36/C37、四格式静态图一致性、完整Editor视觉、工作簿预算、备份保留及全计划验收。未改生产逻辑或业务库。

### Editor 工作簿引擎重复打包修复（2026-11-11）

- 当前构建模块调查发现包名从共享node_modules指向主工作区，相对bridge从当前worktree加载，重复打包引擎、JSZip及Zod。Vite为xlsx-engine包根及子路径增加当前工作区源码别名，统一与bridge的身份，不拆分预算或删功能。
- 使用生产Vite配置的临时诊断包装构建（仅输出目录改至/tmp并记录模块）。基线708610字节约692.0KiB，修复400427字节约391.0KiB，小于原396KiB；所有JavaScript分包按原预算检查无失败。注意此门槛按构建后JS字节，不是gzip，先前文字混称已纠正。
- 单元格插删、公式计算、保护三文件6项定点通过（11.19秒）。第三方已有循环分包和pure注释提示保留。模块清单与日志见artifacts/2026-11-11-workbook-budget；诊断临时配置已移除。生产static未覆盖，实际浏览器保存回归仍需后续完成，不据此完成整个Editor视觉/资源验收。
- 真实模型/StarRocks/专家业务签认、C36/C37同次数据库浏览器、四格式静态图、其他恢复/备份与完整§5/T1–T9目标继续未完成。

### Editor优化后实际浏览器保存验收（2026-11-11，接续）

- 上轮统一引擎源码别名且预算通过。本轮复用原浏览器保存脚本，提供显式Python路径和已有生产构建目录选项，解决隔离worktree未安装虚拟环境及验证压缩分包的问题。
- 开发服务格式/自动求和、草稿恢复各一次通过；再用上轮实际生产构建Vite preview验证恢复/撤销重做、保存503失败后重开、同内容保持requestId、修改后新requestId及最终保存。实际下载XLSX由openpyxl独立核对原值12.34、修改值3、原公式=1+1、自动求和=SUM(A1:A2)、字体/加粗/小数格式，浏览器脚本错误为空。服务按脚本finally退出。
- 文件及日志归档到artifacts/2026-11-11-workbook-budget，新增离线verify.py核对预算/原始与下载哈希/三次真实XLSX。页面与保存HTTP受控，后端用原生patch_office；不代表真实报告PG、模型或桌面Excel。未重复完整测试或重建，未修改签发链/业务库/部署。
- 工作簿引擎预算与对应浏览器保存缺口本次已有证据；完整Editor视觉、四格式静态图、C36/C37浏览器到隔离PG同次闭环、真实模型/StarRocks/业务签认、资源保留/联合备份及全§5/T1–T9仍未完成。

体积口径补正：模块诊断中的400427是JS字符串长度，最终预算脚本使用实际文件字节404035，即394.6KiB，仍低于396KiB；以budget-check.json及verify.py为准。

### T3/T7/T8 真实管理HTTP与隔离PG同次浏览器关闭（2026-11-11）

- 复用已发布修复/真实CSV回归/已发布合成原件夹具，浏览器通过实际ManagementApp依次选择回归/独立原文/摘录及推导、签认、当前证据核验、明确不重算裁定和关闭。Vite只桥接真实FastAPI端口，无业务响应替身；同一异步测试持有实际隔离PG、原件和CSV服务。
- 两次未知响应分别在实际签认200及关闭200返回后中断客户端。重开只读原签认/关闭，关闭后再次进入详情按服务器登记ID读取。1次签认POST、1次关闭POST、2次关闭GET；数据库问题resolved/version3、精确签认回执与关闭回执绑定，两个审计动作各一次，实际不重算不冒充交付。
- 首次启动因测试未显式开启本机HTTP而失败；修正隔离测试设置后1 passed（22.49秒），隔离数据库清理成功。390px真实浏览器无溢出、axe严重/关键零，关闭截图已查看；服务退出。记录HTTP时不保留me接口的CSRF值，归档见artifacts/2026-11-11-report-issue-postgres-browser。
- 本次从已采纳且已登记通过回归开始，合成独立预算100+200=300；不是C02完整原70至63.33报告浏览器闭环，也未覆盖C37退役浏览器、真实模型/StarRocks/专家业务签认。四格式静态图、完整Editor视觉、其他恢复/联合备份及全§5/T1–T9保持未完成。没有生产逻辑、签发链、业务库、提交或部署变更。

### T3/T7/T8 C02原报告至原生队列及真实PG浏览器关闭（2026-11-11）

- 在已有连续C02案例中接同一应用的真实浏览器：HTTP完成实际旧70报告Editor反馈、管理正式发布/关联、新口径采用及Agno耐久队列，新PPTX实际63.33、精确CSV回归；浏览器完成独立原件选择、合成签认、当前全部证据复核、已生成新报告裁定与关闭。原报告/依据/检查点/文件不变，业务查询仍4次。
- 浏览器桥接真实管理HTTP和同次隔离PG；原应用测试Origin为https://reports.test，传输桥接保留该测试来源约束，不替换业务响应。签认/关闭200后各模拟一次客户端未知响应，重开精确恢复；各1次POST，关闭2次GET（恢复及再进详情）。可信输出修订3、问题resolved/version4与PPTX实际SHA/size一致。
- 首次脚本因同名C02失败70/通过63.33两条历史匹配而失败；保留原记录，仅让脚本选择可用的通过项。原有不重算PG浏览器节点在首次批次通过；C02修正后定点1 passed（43.53秒），隔离库清理成功。390px无溢出/axe严重关键零，截图已查看。证据见artifacts/2026-11-11-c02-postgres-browser。
- 不将HTTP前段冒充浏览器：首次反馈、规则编辑发布、新报告采用及回归登记仍通过实际HTTP执行；浏览器仅覆盖签认到关闭。真实模型/StarRocks及专家签认、C37退役完整浏览器、四格式静态图/完整Editor视觉、其他恢复/保留备份和全§5/T1–T9仍未完成。此轮新报告浏览器关闭仅PPTX，不扩大到其他格式；无业务库修改、生产逻辑、签发链或部署变更。


### T8/C37 统计口径精确版本影响与退役界面（2026-11-11）

- 上轮只核对进度，没有实施增量。本轮补实际管理导航、口径目录及已发布版本选择；精确版本影响分页读完并明确确认/填写原因才可提交。退役请求先按账号/组织/口径/版本缓存，缓存失败/损坏不写，未知响应只读精确版本；同内容确认、异内容保留，尚无记录且定义hash相同才可重新确认后显式重提。不自动选择替代或迁移默认。
- 组件7项和原App16项通过（25.30秒）；管理TypeScript/构建通过（6.92秒），gzip登录292.6/列表430.0KiB。四尺寸实际ManagementApp加受控HTTP每尺寸1次POST，分页门禁、键盘提交/恢复焦点、刷新读回和组织切换隔离通过；无溢出/脚本错误，axe严重关键零，390截图已查看。
- 同次真实管理HTTP/隔离PG浏览器退役200后模拟丢响应，刷新精确读回；定义不变、审计恰一次、默认仍指向原版本并标明unavailable，重新绑定退役版本被拒。首轮测试错误使用不存在available键；核对现有get_default契约，改核对policyVersion及issues，定点1 passed（14.57秒）。原退役读回/冲突/跨组织节点另1 passed（6.69秒）；两次均隔离库清理成功。证据见artifacts/2026-11-11-policy-retirement-ui及离线verify.py，原失败保留。
- 本轮只补统计口径退役；指标入口、替代选择/默认编辑、完整C37仍缺。未将既有历史报告HTTP读取混作本次浏览器同次验收。真实模型/StarRocks/专家签认、四格式静态图/完整Editor、其他恢复/保留联合备份与全§5/T1–T9保持未完成。不改生产签发、业务数据库或部署，不勾选整体。


### T8/C37 场景默认口径显式调整与原请求恢复（2026-11-11，接续）

- 上轮补退役入口并有实际PG浏览器证据。本轮接当前选择的精确已发布版本场景，展示当前默认/目标/配置CAS/保留背景，明确确认后才PUT；退役目标不可选，不自动迁移或移除背景。未知结果只GET当前绑定；版本恰+1且目标/背景一致只说明当前状态一致，不假称独立请求回执。原配置未变才可重新确认重提；其他变化保留/显式归档原输入再按最新默认核对。
- 新默认组件8项加退役组件7项15 passed（3.78秒）；新增保存后语义告警被隐藏的红例后修正为重新读取当前可用性。缓存失败/损坏、版本冲突、响应丢失重开及原输入重提均覆盖。退役后刷新目标与默认，默认调整后刷新版本影响。管理TypeScript/构建通过（6.87秒），gzip登录292.6/列表430.0KiB通过原预算。
- 四尺寸真实ManagementApp加受控HTTP每尺寸1次PUT，未知响应刷新只读、键盘/恢复焦点、长背景标识和组织隔离通过；无溢出/脚本错误/axe严重关键。另在同次真实管理HTTP/隔离PG浏览器，实际退役旧版、读回旧默认仍不可用后，显式迁移新版并恢复第二次未知响应；独立非空背景原样保留、旧定义不变，退役/迁移各一次写与审计。最终1 passed（19.10秒）且隔离库清理成功。首次脚本误点Ant隐藏ARIA选项，改点可见选项后通过，未改产品。证据见artifacts/2026-11-11-policy-default-ui及离线verify.py。
- 退役时可选替代版本选择器、指标入口、完整规则编辑发布及全部C37仍待补齐；真实模型/StarRocks/专家签认、静态图四格式/完整Editor、其他恢复/保留联合备份及完整§5/T1–T9不缩减、不勾选完成。无业务库、生产签发链或部署变更。此轮复用原有HTTP/存储，不新增后端接口。


### T8/C37 退役时明确选择替代版本建议（2026-11-11，接续）

- 原默认调整已验证。本轮补同组织口径分页候选和显式发布版本选择，默认不选新版；建议未完整选择、自身或已退役目标不可提交。回执/缓存按完整替代引用核对，原因相同但替代不同仍保留冲突。未登记原退役且原替代后来退役时，可显式归档原输入再重选并确认；不自动调整目标或默认。
- 退役12项和默认8项20 passed（50.65秒）；管理TypeScript/构建通过（19.94秒），gzip登录292.6/列表430.0KiB满足原预算。四尺寸实际ManagementApp/受控HTTP跨口径选择、分页、丢响应恢复/组织隔离均通过，每尺寸1POST，无溢出/脚本错误/axe严重关键；390截图已查看。
- 同次真实HTTP/隔离PG浏览器明确将版本2登记为退役版本1的替代，第一次未知响应精确恢复；旧默认仍为不可用版本1，再另行确认迁移版本2并恢复第二次未知响应，独立非空背景不变、旧定义不变、退役审计1次、默认审计2次（含初始设置）。1 passed（98.56秒），清理成功。首次定位隐藏同名下拉项失败，改可见项后定点通过；四尺寸首次端口冲突等待现有PG服务退出后再执行，没有重复PG。证据见artifacts/2026-11-11-policy-replacement-ui及verify.py。
- 指标入口、完整规则编辑/发布、C37历史报告同次浏览器读取仍缺；真实模型/StarRocks/中文知识检索、四格式静态图/完整Editor、其他恢复/保留联合备份及全§5/T1–T9保持未完成。没有生产签发链、业务库或部署变更，不标记整体完成。


### T8/C37 指标精确版本定义与影响入口（2026-11-11，接续）

- 上轮替代建议为有效进展。本轮增加业务指标管理导航/分页目录/URL版本选择及计算定义，新增GET metrics/{id}/impact按组织/精确版本递归不可变依赖，查询受影响派生指标、精确口径、场景默认；历史报告仅读取ReportBasis完整冻结指标引用，不按当前口径推断。数据库分页，零业务SQL，无新存储。
- 服务隔离PG传递依赖/去重分页/同名组织/版本区分/退役不变1 passed（6.84秒）；HTTP会话/作用域/必填版本/no-store1 passed（6.54秒）。加入实际ManagementApp/真实HTTP/同次PG浏览器后最终1 passed（16.28秒）且清理成功：390px仅GET，历史深链刷新、版本切换/返回、键盘横滚及组织切换清除详情通过；无脚本错误/溢出/axe严重关键。首次axe滚动容器不可聚焦已修复，后续脚本DOM/网络等待修正后定点通过，原失败保留且会话脱敏。证据artifacts/2026-11-11-metric-impact-ui及verify.py。
- 组件3 passed（3.60秒），管理TypeScript/构建通过（7.46秒），gzip登录293.8/列表431.4KiB通过预算，Ruff/diff通过。390截图已查看。
- 当前指标入口只读，退役操作表单/编辑发布及其他尺寸仍缺，不把冻结引用夹具当真实报告生成。完整C37、真实模型/StarRocks/中文检索、静态图四格式/完整Editor、其他恢复/保留联合备份及全§5/T1–T9保持未完成。无业务库、签发链、部署变更。


### T8/C37 指标退役操作与未知提交恢复（2026-11-11，接续）

- 新增指标精确版本退役表单，读完全部影响/原因/明确确认才提交，缓存失败或损坏不写。请求先完整缓存，未知响应只读hash/精确版本/原因/替代引用，冲突保留；未登记时刷新影响并重新确认后显式重提。当前不登记替代建议，不自动迁移默认/依赖/历史报告。
- 退役6项与详情3项9 passed（3.99秒）；重提刷新影响后定点1 passed（3.13秒）。TypeScript/管理构建通过（7.44秒），gzip登录292.6/列表430.3KiB通过。磁盘满首轮失败后只清理可重建临时预算构建和npm下载缓存；详情会话由页面显式传入。浏览器途中热更新导致扩展失败，源码不变后定点通过，未降低验收。
- 同次真实HTTP/隔离PG/浏览器节点1 passed（22.79秒）且清理成功：实际退役200后丢响应、刷新精确恢复，1POST/1审计，旧冻结引用与影响不变，原默认绑定未改且因退役依赖明确不可用。390完成操作/恢复/版本切换与组织隔离，恢复后四宽度布局/axe通过；非其他宽度各自操作闭环。390截图已查看。证据artifacts/2026-11-11-metric-retirement-ui及verify.py。
- 指标替代选择/规则编辑发布及C37历史文件实际读取仍缺；全§5/T1–T9、真实模型/StarRocks/中文知识、四格式静态图/完整Editor、其他恢复/保留联合备份不缩减，不标记完成。无业务库、生产签发链或部署变更。


### T8/C37 指标退役的明确替代建议（2026-11-11，接续）

- 新增同组织指标候选与精确已发布版本选择，不自动最新或改写依赖/默认。候选显示名称及标识；自替代、已退役或未完整选择不可提交。缓存及未知读回核对完整替代引用；原请求未登记且替代后来不可用时，须明确归档原输入再重选。
- 退役11项与详情3项共14 passed（6.37秒）；候选标签修改后定点1 passed（3.72秒）。管理TypeScript/构建通过（7.07秒），gzip登录292.6/列表430.3KiB通过。
- 同次真实HTTP/隔离PG/浏览器1 passed（21.49秒），清理成功：budget/1退役、budget/2替代，服务器200后丢响应并精确恢复，1POST/1审计；旧默认及历史引用未改，默认因退役依赖不可用。390实际操作/恢复，恢复后四宽度布局与axe通过，不冒充四套完整流程。390表单截图已查看；初次同名候选定位失败后补产品标识，第二次退出请求未完成后改等待明确组织响应。原失败日志保留并会话脱敏。归档artifacts/2026-11-11-metric-replacement-ui，离线verify.py核验哈希、HTTP、数据库事实与预算。
- 仍缺指标/口径完整编辑发布、C36全程浏览器、C37历史报告实际文件浏览器、真实模型/StarRocks/中文知识及专家签认、静态图四格式/完整Editor、其他恢复/资源保留联合备份及全§5/T1–T9；合成冻结引用不当实际报告生成。无业务库、生产签发链、部署变更，整体保持未完成。


### T8 指标定义编辑、保存与发布初步入口（2026-11-11）

- 指标目录新增创建/编辑入口，按账号/组织/指标隔离缓存，页面懒加载。表单覆盖求和/非空计数/去重计数/精确比率、维度与粒度、完整字段引用、时区、累计快照聚合/重置和别名。保存与发布分开，版本由服务端确定，不发送scopeId/revision；未保存不得发布，不自动替换口径/默认。
- 请求先缓存；未知结果只读回。草稿精确下一CAS版本且定义一致，只陈述状态相同、不冒称唯一请求回执；发布核对精确revision/hash/定义。首次保存404、首次发布404补读原草稿后才允许重新确认重提；冲突保留输入，坏缓存/缓存失败禁止写，恢复按钮可聚焦。
- 先运行缺编辑器红例；首次发布未落库及首次保存不存在两条恢复红例后修正。指标编辑10项、详情3项、退役11项共24 passed（5.94秒）；TypeScript/管理构建通过（7.48秒）。四宽度实际ManagementApp加受控HTTP分别创建/保存200未知模拟/发布未知/重开只读恢复，均各1PUT/1POST、无溢出或脚本错误、axe严重关键零；390截图已查看。证据artifacts/2026-11-11-metric-editor-ui，原失败与最终日志保留。
- 这是编辑发布初步入口：尚缺发布前与当前版本逐字段差异、比率依赖可选目录、冲突对照采纳及本轮真实PG浏览器写入；现用手填完整字段/精确依赖版本，不冒充完整业务编辑体验。未做新后端/签发链/业务库/部署变更。口径完整编辑、C36/C37全闭环、真实模型/StarRocks/专家、四格式静态图/完整Editor、恢复保留联合备份及全§5/T1–T9继续未完成。


### T8 指标发布差异、依赖选择及同次PG浏览器写入（2026-11-11）

- 补已发布定义与已保存草稿的逐字段中文对比，含计算方法、字段、单位、精确分子/分母、维度粒度、聚合、时区和别名；未保存输入不混入目标。首次发布显示新增；无变化明确说明。滚动对比区域可聚焦，技术hash不充当业务说明，不自动迁移口径/默认。
- 比率改为同组织分页候选及明确版本选择，显示名称/标识/单位/粒度；不自动最新。读取精确身份，已退役/读取失败保留选择，未核验可用前可保存但不能发布。仍由服务端核验完整依赖，不把两个单位不一致变成额外业务硬门禁。
- 发布对比两红例后补说明，选择器缺模块红例后4项通过；最终受影响四文件30 passed（9.37秒），管理TypeScript/构建通过（10.95秒），Ruff/diff通过，资源预算通过。
- 同次真实管理HTTP/隔离PG/浏览器先验证基础指标修改/发布1 passed（18.77秒）；后扩展明确选择actual/1与budget/2创建比率，最终1 passed（25.52秒），两次均隔离库清理成功。后者2PUT/2POST，各服务端200后中断客户端并刷新只读恢复，数据库精确依赖/5次保存及5次发布审计（含3次初始化）、旧版及另一组织同名数据不变。390完成写入恢复；基础指标发布前四宽度axe严重关键零/无溢出；比率390另axe通过。390截图均已查看，不冒充四套独立写入或真实报告取数。
- 比率首次浏览器失败为创建新对象时未等新编辑器挂载就填入旧字段，诊断确认空名称/单位；仅修脚本等待明确标题，原失败脱敏保留。证据artifacts/2026-11-11-metric-release-ui及离线verify.py。
- 当前仍缺冲突左右核对/采纳、数据目录字段辅助选择、口径完整编辑及知识管理；C36/C37全程真实报告浏览器、真实模型/StarRocks/中文检索/专家、静态图四格式/完整Editor、其他恢复/保留联合备份及全§5/T1–T9保持未完成。本次合成管理定义不代表业务数据或报告生成，无生产签发链/业务库/部署变更。


### T8 统计口径编辑、规则维护与发布恢复（2026-11-11）

- 新增统计口径目录创建/编辑及URL入口，懒加载编辑页，账号/组织/对象隔离本地草稿与原请求。名称、场景、半开生效期、精确指标、制度集合、决策说明可编辑；沿用已有MetricDependencyPicker，不自动最新。制度集合按明确标识读取修订及标题，拒绝背景集合；集合目录选择仍待补。
- 新增类型明确的筛选（文本/数字/布尔/空值）、多对一成对关联键与输出粒度、预期期间/分组、水位/最大延迟及空数据规则。结构校验涵盖字段、比较值数量、成对关联、真实日期/期间重叠、分组重复与水位前置；只约束结构，不把语义疑点改成硬门禁。未修改项完整保留，期间/类型不静默归一。
- 保存和发布分开；发布必须先对已保存草稿调用现有结构预览，展示计算/指标引用/依据变化和具体告警，任何本地修改清除预览。发布不改默认；响应未知只核对原草稿CAS或精确发布revision/hash/定义，不自动写重试。缓存失败/损坏禁止写，409保留输入。首次保存/发布未落库走明确读回后确认重提。原发布核对告警随原请求保存，刷新恢复后仍显示，明确不代表当前可用性。
- 缺模块及告警丢失红例已保留。最终受影响口径五文件40 passed（35.49秒），TypeScript/管理构建通过（7.39秒），Ruff/diff通过，gzip登录292.6/列表430.2KiB满足原预算。不是完整项目测试。
- 同次真实HTTP/隔离PG/浏览器初步只改名称和说明1 passed（19.95秒）；加入规则编辑后1 passed（20.95秒），均清理成功。390实际筛选A改B、新增全年预期期间/项目B分组，保存200后丢响应、刷新只读恢复、预览确认filters/readiness变化、明确发布200后丢响应再只读恢复。数据库保存/发布各2次审计（含初始各1），默认仅初始1次；旧版本、原指标/制度、默认1版、水位/延迟/空数据规则未变。发布前1440/1280/768/390布局无溢出、axe严重关键零，390截图已查看；非四套独立写入，非真实模型/StarRocks/业务签认。
- 证据artifacts/2026-11-11-policy-editor-ui及verify.py。仍缺制度集合目录与原文选择/知识完整管理、冲突对照采纳、完整字段目录辅助、完整变更前后业务对比、C36/C37完整报告浏览器、真实模型/StarRocks/中文检索/专家签认、四格式静态图/完整Editor、其他恢复/保留联合备份与全§5/T1–T9验收。整体保持未完成；无生产签发链/业务库/部署变更。


### T8 制度依据目录选择与精确原文预览（2026-11-11）

- 新增同组织已发布集合目录API，支持用途、字面搜索、游标分页和当前审核状态；保持requestId读回契约。真实隔离PG两项测试通过（8.38秒），涵盖同名组织隔离、撤销、分页、认证/参数/no-store。目录不读取业务数据或原件，不把登记状态称业务正确性。
- 口径编辑接目录选择，选择前重新读取当前状态及精确集合用途/成员身份；不自动选最新。原文抽屉显示明确修订解析片段、真实行/页/段/表格位置，核验解析与原件hash；已撤销/缺修订/身份不符不回退。首屏20片段/每片段10000字，长文提示。Esc关闭下一帧返回触发按钮焦点。
- 受影响三文件20 passed（7.17秒），焦点修复后选择器4 passed（3.59秒）；最终TypeScript/管理构建通过（6.94秒），gzip登录292.6/列表430.5KiB满足预算，Ruff/diff通过。保留依赖/jsdom/分包警告，不宣称零警告。
- 同次真实HTTP/隔离PG/浏览器1 passed（23.65秒），清理成功：390实际选择budget-rules修订2、预览行号/正文、键盘关闭恢复、项目B规则保存和发布，两次200后客户端丢响应再刷新只读恢复。各1次保存/预览/发布；保存/发布审计各2含初始化，默认审计仅初始1，旧原文修订及口径1版/默认1版不变。原文抽屉与发布前1440/1280/768/390无溢出/axe严重关键零；非四套独立写入，390截图已查看。
- 首次脚本错误预期两行合并，核对真实逐行解析后修正；随后发现焦点恢复缺口，同步恢复仍被卸载覆盖，改下一帧后定点通过。最终构建DOM类型错误改HTMLElement后通过。原失败日志保留。证据artifacts/2026-11-11-evidence-catalog-ui及verify.py。
- 知识上传/审核/发布完整管理、冲突对照、字段辅助和完整口径差异、C36/C37完整报告浏览器、真实模型/StarRocks/中文检索/专家签认、四格式完整视觉一致性、恢复保留联合备份及全§5/T1–T9仍未完成。无生产签发链/业务库/部署变更，整体不勾选完成。


### T8 业务知识原件目录与精确审核（2026-11-11）

- 上轮制度依据选择及原文预览已有验证与归档，本轮属于有效实施进展。新增组织原件目录GET，最新修订摘要/字面搜索/用途/审核筛选和游标分页；无原文/路径/业务数据读取。2项真实隔离PG测试通过（7.50秒），含同名组织、最新修订、分页、认证/参数/no-store。
- 新增业务知识导航及URL精确修订详情、适用期/事件/对象/当前状态、显式原件下载。管理审核模式允许解析完成但待审内容，撤销仍拒绝；默认口径预览仍要求已批准和ready。沿用已有审核API，完整缓存理由/决定/CAS/原件hash，缓存失败/错身份禁止写，未知只读核对，冲突保留，未写且版本未变须再次确认才重提。不发布集合或改历史报告。
- 审核组件缺模块红例后5项通过；补错缓存身份红例后修正。受影响审核7项/知识页1项/原App16项共24 passed（26.11秒），管理预览7项通过。最终TypeScript/构建7.19秒通过，gzip登录292.7/列表430.8KiB，Ruff/diff通过；保留依赖/jsdom/分包警告。命令序列化错误修正未作为产品失败掩盖。
- 同次真实HTTP/隔离PG/浏览器1 passed（18.32秒），清理成功：390实际待审修订2预览/原件下载、批准200后丢响应、刷新读回，恰1审核POST/1审计；原hash/解析、旧修订及另一组织同名原件不变。预览和审核前四宽度无溢出/axe严重关键零，键盘Esc焦点恢复，切组织清除详情通过；不是四次独立审核，390截图已查看。初次浏览器失败发现切组织跳数据源，已修知识导航后定点通过。
- 证据artifacts/2026-11-11-knowledge-review-ui及离线verify.py。当前只完成原件目录和审核初步入口；上传/新修订、任务失败重试、审核撤销影响、集合显式发布/恢复及背景选择还缺。C36/C37完整报告浏览器、真实模型/StarRocks/中文检索/专家、四格式完整视觉、恢复保留联合备份和全§5/T1–T9保持未完成。无生产签发链/业务库/提交/部署变更。


### T4/T8 原件上传、新修订与原请求恢复（2026-11-11）

- 上轮原件目录审核为有效实施进展。本轮新增按组织/requestId读取登记事实GET，校验不可变修订hash及原上传input hash，返回精确登记条件/原件hash/任务，不返回路径/原文。缺方法/路由红例后2项隔离PG测试通过（7.21秒），含解析后读回、跨组织、认证/参数/no-store。
- 管理HTTP复用FormData直传，保留原会话代次/CSRF/401/协议错误处理；序列化成JSON红例后修正。知识页支持新原件及从明确修订预填元数据登记下一版，使用最新登记CAS而非覆盖旧修订。用途/适用期/事件/对象可填；文件≤20MiB，先hash并缓存请求条件，不保存字节。缓存失败禁止写，未知按requestId只读精确核对；未登记再查当前版本，未变才允许同文件重新确认显式重提，有其他修订禁止覆盖。
- 任务进入URL并可手动读取解析状态，匹配job/document/revision；不自动重跑。上传6项/HTTP4项/知识页1项共11 passed（5.36秒），管理TypeScript/构建6.94秒通过，gzip登录292.7/列表430.7KiB预算通过，Ruff/diff通过；依赖/jsdom/分包警告保留。
- 同次真实HTTP/隔离PG/BusinessIngestionWorker/浏览器1 passed（21.84秒），清理成功：390从原件1版明确上传2版，201后丢响应并刷新读回，真实后台解析一次，再实际原文预览/下载和审核200未知恢复。1上传/1审核，登记审计3含两组织初始化、审核1，旧修订及另一组织同名原件不变。恢复后审核页/原文抽屉四宽度布局axe严重关键零，非四次独立上传；上传前390截图已查看，不冒称上传前全宽度axe覆盖。证据artifacts/2026-11-11-knowledge-upload-ui及verify.py。
- 解析失败重试界面、撤销影响、证据集合管理发布与背景选择、C36/C37完整报告浏览器、真实模型/StarRocks/中文知识/专家、四格式完整视觉、恢复保留联合备份与全§5/T1–T9继续未完成，无生产签发链/业务库/提交/部署变更。


### T4/T8 解析失败显式重试与任务恢复（2026-11-11）

- 上轮上传/解析/审核是有效实施进展。本轮复用现有retry API补失败任务界面，任务精确身份/expectedAttempt/明确确认才POST；needs_transcription不提供重复解析。账号/组织/job隔离缓存先存请求，损坏/失败不写，响应未知只读取原任务；已推进仅陈述状态不冒充唯一回执，仍原失败需重新确认才能显式重提。不改原件修订/审核/集合。
- 缺模块红例后首轮5过1失败，原因fixture复用一次性Response被并发初读消费；修复独立Response后组件6项/知识页1项共7 passed（5.28秒）。管理TypeScript/构建7.03秒通过，gzip登录292.7/列表430.8KiB满足预算，Ruff/diff通过。依赖/jsdom/分包警告保留。
- 同次隔离PG/真实HTTP/worker/浏览器1 passed（16.81秒），清理成功：首轮解析器控制失败，恢复真实解析器后390显式retry200客户端丢响应，刷新原任务只读恢复，最终parsed/attempt2；仅1POST/1重试审计，原登记1/审核0，原字节/修订1/待审不变。提交前四宽度布局无溢出/axe严重关键零，390截图已查看；非四次独立重试，不是模型/StarRocks。证据artifacts/2026-11-11-ingestion-retry-ui及verify.py。
- 仍缺按原件找历史任务入口（当前上传回执/URL可恢复）、撤销影响、集合管理发布及背景选择；C36/C37完整报告浏览器、真实模型/StarRocks/中文知识/专家、四格式完整视觉、恢复保留联合备份和全§5/T1–T9继续未完成。无生产签发链/业务库/提交/部署变更。


### T4/T8 制度与背景集合的明确发布及原请求恢复（2026-11-11）

- 知识页接现有集合发布/目录/requestId读回，按组织用途搜索分页，逐份读取全部修订后明确选定；新待审版不自动加入。精确原文预览/键盘关闭焦点恢复，最多200份，搜索翻页不丢所选。
- 发布前重读审核/用途/元数据/hash，完整缓存才POST；新增重复成员、用途与原件身份错配三条红例后拒绝损坏缓存，解析异常留在受控恢复路径。响应未知只GET原请求，未登记且原件仍有效需重新确认才能显式重提。回执核对用途和全部成员，不改口径/默认/历史报告。
- 最终组件10项加知识页1项11 passed（6.14秒），TypeScript/管理构建7.52秒，gzip登录292.7/列表430.8KiB通过，Ruff/diff通过。真实HTTP/隔离PG/Agno PgVector/浏览器1 passed（23.64秒）且清理成功：390明确发布制度budget-rules/1与背景budget-background/1，两次201后丢响应刷新只读恢复，2POST/2审计，实际索引非空；待审修订2/旧原件解析审核/另一组织同名原件不变，默认仍空。固定合成向量和原文，不当真实中文召回、模型、StarRocks或专家签认。
- 发布前1440/1280/768/390无溢出/axe严重关键零，390实际两次操作，不冒称四套独立发布；恢复截图已查看。初次瞬态导航动画溢出在禁动画截图后消失、全DOM无越界，脚本改等待有限原生动画完成后再检查，未改产品隐藏溢出。开发热更新中断另次浏览器，源码稳定后定点通过，失败日志保留。证据artifacts/2026-11-11-evidence-release-ui含manifest和verify.py，离线验证通过。
- 背景集合默认选择/报告接入、历史任务发现、撤销影响、冲突对照/字段辅助/完整差异、C36/C37完整报告浏览器、真实模型/StarRocks/中文知识/专家、四格式完整视觉、其他恢复保留联合备份及全§5/T1–T9继续未完成。无业务库、生产签发链、提交或部署变更，整体不标完成。


### T4/T7/T8 新报告默认背景集合选择与冻结依据核对（2026-11-11）

- 上轮明确集合发布为有效进展。本轮复用选择器按background用途展示同组织集合、重新核对可用性/精确成员、原文预览及焦点恢复；选择、不使用、保留当前均显式操作并重置确认。默认更新沿用精确口径版本和配置CAS，只换背景不创建公式版本；移动长标识按钮换行。
- 未知响应只读完整绑定，原配置未变才核对口径与背景后可重提；背景已撤销保留原请求并要求显式归档重选。4条缺功能红例加恢复前撤销红例后实现，最终默认12/选择器6/预览7/口径编辑10共35 passed（9.52秒）。TypeScript/构建8.48秒，gzip登录292.7/列表430.8KiB通过，Ruff/diff通过，依赖/jsdom/分包警告保留。
- 同次真实HTTP/隔离PG/Agno PgVector/浏览器最终1 passed（22.22秒），清理成功：390仅1PUT背景默认，200后丢响应刷新只读恢复；默认CAS1至2且monthly-budget/1不变。旧ReportBasis服务重建读回完全相同且无背景，新登记Basis采用背景，指标/来源/目录/制度不变；口径草稿及发布审计各1（初始），默认审计2含初始，另一组织同名原件不变。不当完整报告生成/业务取数/模型/StarRocks/中文召回/业务负责人确认。
- 操作前1440/1280/768/390无页面及按钮文本溢出、axe严重关键零，390原文Esc焦点恢复，截图已查看；非四套独立更新。首次PG浏览器通过后针对撤销与移动体验完善定点复测，未重复全项目。证据artifacts/2026-11-11-background-default-ui及manifest/verify.py离线核验通过。
- C33报告级背景解释/事件可知性仍需完整验收，历史任务入口/撤销影响、冲突对照/字段辅助/完整差异、C36/C37完整报告浏览器、真实模型/StarRocks/中文知识/业务负责人确认、四格式完整视觉、其他恢复保留联合备份及全§5/T1–T9继续未完成。无业务库、生产签发链、提交或部署变更，整体保持未完成。


### T4/T7/C33 公开历史知识截止时间与采用口径保留（2026-11-11）

- 上轮背景默认绑定为有效进展。本轮查明内部支持截止时间但公开输入缺字段，补ReportingWorkflowInput/Envelope的knowledgeAsOf，带时区且拒绝数字时间戳/日期/无时区，prompt不得混用。原生payload/请求上下文/摘要记录明确或默认；未来时间422且事务无部分依据，同运行改截止409；恢复执行核对冻结截止时间。
- 新口径采用原来重置now，本轮对明确历史视角保留原截止时间并还原子Envelope；未指定的既有新登记行为不变。请求及采用红例、顶层数字隐式转换红例先失败后修复。请求/知识支持58 passed（16.88秒），追加运行时防篡改等定点5 passed（8.46秒，有重叠不累计独立数）；6种背景因果支持验证时间/指标/期间/语义，不把引用存在当通过。Ruff/diff通过。
- 真实隔离PG公开截止/未来回滚/历史排除3 passed（10.70秒），采用口径历史保留/原幂等2 passed（9.09秒），最终历史回执留存及原公开请求/默认冻结3 passed（9.79秒，有重叠）；均隔离库清理成功。实际公开历史请求在向量排序前排除后补登记背景，零查询；另建当前运行相同口径/背景命中原文，恰1索引查询，旧Basis不变。合成固定向量非中文召回、完整报告、模型、StarRocks或业务负责人确认。证据artifacts/2026-11-11-knowledge-cutoff含manifest/verify.py。
- 当前仅结构化原生请求可明确指定历史截止，未新增报告创建UI日期控件。全报告C33及其他C36/C37完整浏览器、历史任务入口/撤销影响/冲突对照/字段辅助、真实模型/StarRocks/中文知识/业务负责人确认、四格式完整视觉及恢复保留联合备份和全§5/T1–T9继续未完成。无业务库、生产签发链、提交或部署变更。


### T4/T8 从精确原件修订找回解析任务（2026-11-11）

- 上轮公开历史知识截止为有效进展。本轮先核查创建入口，仓库无独立创建表单，原生AgentOS承载；不虚构新页。继续既有闭环缺口，新增修订任务GET，沿用组织会话认证、修订存在校验、分页与公开回执，不返回租约/路径/原文。详情明确展开并打开任务URL；切修订清旧job，读目录不创建/重跑。
- 后端缺方法/路由红例后隔离PG2 passed（7.12秒），涵盖同名组织/修订/认证/404/参数/no-store。前端缺入口红例后接通，测试误以aria-label为正文改核对区域；修复新增重复key。目录3/任务6/页面2共11 passed（6.93秒）；追加切修订页面3 passed（8.10秒，有重叠不累计）。TypeScript/管理构建7.40秒，gzip登录292.7/列表430.8KiB满足预算，Ruff/diff通过。
- 真实HTTP/隔离PG/worker/浏览器从详情找到原失败任务（初始无job），390明确retry1次200后丢响应，刷新只读恢复parsed/attempt2；原修订1/待审核/原字节不变，1重试审计0审核。四宽度无溢出/axe严重关键零，非四次独立操作。初次浏览器夹具缺集合路由有无关错误，接真实空目录后定点1 passed（20.42秒）清理成功，390截图已查看；合成原件首轮控制失败非模型/StarRocks。证据artifacts/2026-11-11-revision-task-directory/manifest/verify.py。
- 完整C33/C36/C37报告浏览器、撤销影响/冲突对照/字段辅助/完整差异、真实模型/StarRocks/中文知识/业务负责人确认、四格式完整视觉及恢复保留联合备份等全§5/T1–T9继续未完成；历史时间控件需对实际外部创建入口核对，不擅自另建平台。无业务库、生产签发链、提交或部署变更。
