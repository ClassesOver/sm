# Dynamic Narrative Chapters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让报告在原子分析完成后，依据真实管理发现、影响和证据动态生成叙事章节，同时保留现有事实、追溯、编辑器和非阻断发布契约。

**Architecture:** 保留现有分析计划、数据集、确定性 facts 和补证流程，新增服务端 `FindingCard` 发现层与 `NarrativeOutline` 章节层。分析阶段先独立完成原子事实，再由发现图谱生成最终章节；旧提纲仅作为过渡期内部分析执行分区，最终目录和正文使用叙事提纲。

**Tech Stack:** Python 3.12、Pydantic、Agno Workflow、loguru、pytest、现有 Reporting checkpoint/reducer、Markdown/PDF/Word 发布链路。

**Spec:** [docs/superpowers/specs/2026-10-14-dynamic-narrative-chapters-design.md](/home/junge/pros/smart_reporting/docs/superpowers/specs/2026-10-14-dynamic-narrative-chapters-design.md)

## Global Constraints

- 语义业务校验只需要软告警。
- 报告验收或发布门禁失败不得暂停/阻断工作流或阻止下载链接签发；已生成且身份可读取的 PDF/Word 必须继续签发，并明确返回失败原因和告警。
- 应用代码日志系统使用 loguru。
- 运行产物、CSV、日志、截图、token 和其他临时文件不得提交 Git。
- 不改变现有 facts、dataset lineage、citation、chart identity 和报告编辑器追溯协议。
- 不把相关性升级为因果，不引入预测、外推、年化或自动改变指标口径。
- 禁止重复完整测试；每个任务先运行对应定向测试，最后只运行必要的回归集合。

---

### Task 1: 建立管理发现与叙事章节数据契约

**Files:**
- Create: `smart_reporting/reporting/hospital_operation/findings.py`
- Create: `smart_reporting/reporting/hospital_operation/narrative_outline.py`
- Modify: `smart_reporting/reporting/hospital_operation/__init__.py`
- Test: `smart_reporting/reporting/tests/test_dynamic_narrative_contracts.py`

**Interfaces:**
- Produces `FindingCard`, `FindingGraph`, `NarrativeSectionCandidate`, `NarrativeOutline` and `freeze_narrative_outline()`。
- `FindingCard` 使用字段 `findingId`、`analysisIds`、`kind`、`title`、`summary`、`metricCodes`、`periodRoles`、`grain`、`priority`、`evidenceLevel`、`impactValue`、`impactUnit`、`actionability`、`citationIds`、`relatedFindingIds`、`limitations`。
- `FindingGraph` 使用字段 `version`、`snapshotHash`、`findings`、`relations`、`warnings`。
- `NarrativeSectionCandidate` 使用字段 `title`、`findingIds`、`narrativeRole`、`priority`、`objective`、`groupingReason`、`maxCharts`、`maxBlocks`；`analysisIds` 由服务端依据 finding 反推，不由模型提交。
- `NarrativeSection` 在冻结后增加 `code`、`sectionNumber` 和服务端派生的 `analysisIds`；`NarrativeOutline` 使用字段 `version`、`title`、`sections`、`appendixFindingIds`、`omittedFindings`、`snapshotHash`。
- `freeze_narrative_outline(candidate, graph, analyses)` 服务端生成连续 `section_001` 等身份，检查引用、覆盖和快照哈希。

- [ ] **Step 1: 写契约失败测试**

  在 `test_dynamic_narrative_contracts.py` 覆盖：

  ```python
  def test_finding_card_requires_evidence_level_and_identity():
      with pytest.raises(ValidationError):
          FindingCard.model_validate({"findingId": "finding_001"})

  def test_freeze_outline_rejects_unknown_or_duplicate_findings():
      graph = _graph(findings=[_finding("finding_001")])
      candidate = _candidate(("收入变化", ["finding_001"]), ("重复", ["finding_001"]))
      with pytest.raises(ValueError, match="重复"):
          freeze_narrative_outline(candidate, graph=graph, analyses=_analyses())

  def test_freeze_outline_allows_dynamic_titles_and_roles():
      outline = freeze_narrative_outline(
          _candidate(("收入增长与业务量贡献", ["finding_001"])),
          graph=_graph(findings=[_finding("finding_001")]),
          analyses=_analyses(),
      )
      assert outline.sections[0].code == "section_001"
      assert outline.sections[0].finding_ids == ("finding_001",)
  ```

- [ ] **Step 2: 运行定向测试确认失败**

  Run: `pytest smart_reporting/reporting/tests/test_dynamic_narrative_contracts.py -q`

  Expected: FAIL because the new models and freeze function do not exist。

- [ ] **Step 3: 实现最小契约**

  在两个新模块中使用现有 `HospitalOperationSchema`、`StrictModel` 和 Pydantic validator：

  - `findingId` 必须匹配 `finding_[0-9a-f]{3,64}`，稳定摘要使用小写十六进制；
  - `analysisIds`、`citationIds` 和 `relatedFindingIds` 不得重复；
  - `impactValue` 允许为空，不能把缺失值转换成 0；
  - `evidenceLevel` 和 `priority` 使用受控枚举，标题和摘要使用中文自然语言；
  - `freeze_narrative_outline()` 必须拒绝未知 finding、重复 finding、跨快照 finding 和没有任何发现的章节；
  - 低优先级发现可以出现在 `appendixFindingIds`，但不能无理由丢失；
  - 服务端生成章节 code、编号和最终 `analysisIds`，模型不提交这些派生字段。

- [ ] **Step 4: 运行定向测试确认通过**

  Run: `pytest smart_reporting/reporting/tests/test_dynamic_narrative_contracts.py -q`

  Expected: PASS。

- [ ] **Step 5: 提交契约变更**

  ```bash
  git add smart_reporting/reporting/hospital_operation/findings.py \
    smart_reporting/reporting/hospital_operation/narrative_outline.py \
    smart_reporting/reporting/hospital_operation/__init__.py \
    smart_reporting/reporting/tests/test_dynamic_narrative_contracts.py
  git commit -m "feat: add dynamic narrative finding contracts"
  ```

### Task 2: 从已冻结 facts 投影管理发现图谱

**Files:**
- Modify: `smart_reporting/reporting/workflow/runtime/analysis.py`
- Modify: `smart_reporting/reporting/hospital_operation/deterministic_analysis.py`
- Create: `smart_reporting/reporting/hospital_operation/finding_projection.py`
- Test: `smart_reporting/reporting/tests/test_finding_projection.py`

**Interfaces:**
- Produces `build_finding_graph(fact_bundles, supplemental_evidence, metric_definitions, snapshot_hash) -> FindingGraph`。
- `project_analysis_findings(analysis_id, deterministic_facts, supplemental_evidence, metric_definitions) -> tuple[FindingCard, ...]` 只读取已验证事实。
- `FindingGraph.snapshotHash` 必须绑定本轮事实快照，供后续章节冻结校验。

- [ ] **Step 1: 写投影失败测试**

  在测试文件顶部定义 `_fact_bundle()`、`_supplemental_evidence()` 和 `_metric_definitions()` fixture factory，分别返回现有 `DeterministicAnalysisBundle`、补证模型和指标定义模型。覆盖以下事实：

  ```python
  def test_projection_creates_trend_finding_from_registered_period_values():
      facts = _fact_bundle(period_values=[{"period": "2025-01", "value": 100}, {"period": "2025-02", "value": 130}])
      findings = project_analysis_findings("analysis_001", facts, None, _metric_definitions())
      trend = next(item for item in findings if item.kind == "trend")
      assert trend.metric_codes
      assert trend.citation_ids

  def test_projection_creates_direct_attribution_only_when_reconciliation_passes():
      facts = _fact_bundle(reconciliations=[{"name": "贡献合计", "passed": True}])
      evidence = _supplemental_evidence(kind="attribution", passed=True)
      findings = project_analysis_findings("analysis_001", facts, evidence, _metric_definitions())
      attribution = next(item for item in findings if item.kind == "attribution")
      assert attribution.evidence_level == "direct_decomposition"

  def test_projection_marks_correlation_as_statistical_relation():
      facts = _fact_bundle(correlation_method="pearson")
      findings = project_analysis_findings("analysis_001", facts, None, _metric_definitions())
      relation = next(item for item in findings if item.kind == "impact")
      assert relation.evidence_level == "statistical_relation"

  def test_projection_keeps_missing_impact_as_none():
      facts = _fact_bundle(period_values=[])
      findings = project_analysis_findings("analysis_001", facts, None, _metric_definitions())
      limited = next(item for item in findings if item.kind == "data_quality")
      assert limited.impact_value is None

  def test_projection_uses_stable_id_for_same_fact_path():
      facts = _fact_bundle(period_values=[{"period": "2025-01", "value": 100}])
      first = project_analysis_findings("analysis_001", facts, None, _metric_definitions())
      second = project_analysis_findings("analysis_001", facts, None, _metric_definitions())
      assert [item.finding_id for item in first] == [item.finding_id for item in second]
  ```

  断言归因对账失败时不得生成 `evidenceLevel="direct_decomposition"`，缺失金额不得变成零。

- [ ] **Step 2: 运行定向测试确认失败**

  Run: `pytest smart_reporting/reporting/tests/test_finding_projection.py -q`

  Expected: FAIL because projection functions do not exist。

- [ ] **Step 3: 实现确定性发现投影**

  - 读取 `metrics`、`derivedMetrics`、`comparisons`、`reconciliations`、`periodValues`、`topGroups`、`bottomGroups` 和补证表；
  - 为趋势、异常、贡献、经营影响和数据限制生成发现；
  - 贡献发现只有在事实范围、粒度和对账状态满足条件时才标记为直接分解；
  - 相关性只生成统计关系发现；
  - 通过事实路径、分析 ID 和快照哈希生成稳定 finding ID；
  - 按影响金额、变化率、异常严重度和数据质量影响计算优先级；
  - 将来源引用和限制原样绑定，不在投影阶段改写数值。

- [ ] **Step 4: 在分析阶段持久化 FindingGraph**

  在 `run_reporting_analysis` 的分析事实完成、章节成稿开始之前调用 `build_finding_graph()`，把图谱写入受信 workspace 文件，并通过 durable command 保存文件身份和 `snapshotHash`。不要把完整图谱直接塞进 Workflow session state。

- [ ] **Step 5: 运行定向测试确认通过**

  Run: `pytest smart_reporting/reporting/tests/test_finding_projection.py -q`

  Expected: PASS。

- [ ] **Step 6: 提交发现投影变更**

  ```bash
  git add smart_reporting/reporting/hospital_operation/finding_projection.py \
    smart_reporting/reporting/hospital_operation/deterministic_analysis.py \
    smart_reporting/reporting/workflow/runtime/analysis.py \
    smart_reporting/reporting/tests/test_finding_projection.py
  git commit -m "feat: project verified facts into management findings"
  ```

### Task 3: 将分析执行与最终章节编排解耦

**Files:**
- Modify: `smart_reporting/reporting/workflow/orchestration.py`
- Modify: `smart_reporting/reporting/workflow/runtime/analysis.py`
- Modify: `smart_reporting/reporting/workflow/state.py`
- Modify: `smart_reporting/reporting/workflow/checkpoint.py`
- Modify: `smart_reporting/reporting/workflow/runtime/base.py`
- Test: `smart_reporting/reporting/tests/test_dynamic_chapter_workflow.py`
- Test: `smart_reporting/reporting/tests/test_reporting_cli.py`

**Interfaces:**
- Produces `run_analysis_evidence()`：只完成原子分析、补证和 FindingGraph，不生成用户可见章节。
- Produces `generate_narrative_outline()`：读取 FindingGraph，返回冻结的 `NarrativeOutline`。
- Produces `run_report_draft()`：读取最终 NarrativeOutline，复用现有可视化和章节正文流程。
- Durable phase 在 `ANALYSIS_FREEZING` 与 `SECTIONS` 之间增加 `NARRATIVE_PLANNING`，旧状态可通过确定性迁移或兼容读取恢复。

- [ ] **Step 1: 写工作流顺序失败测试**

  ```python
  async def test_analysis_finishes_before_narrative_outline(monkeypatch):
      calls = []
      # 使用现有 executor fake 记录步骤顺序
      assert calls == [
          "run-analysis-evidence",
          "generate-narrative-outline",
          "run-report-draft",
      ]

  async def test_final_outline_is_not_bound_to_analysis_item_count(monkeypatch):
      runtime = _workflow_runtime(monkeypatch, analysis_count=12, finding_count=3)
      outline = await runtime.generate_narrative_outline(_step_input(), _run_context())
      assert len(outline.sections) < 12
      assert all(section.finding_ids for section in outline.sections)

  async def test_resume_from_narrative_planning_reuses_finding_graph(monkeypatch):
      runtime = _workflow_runtime(monkeypatch, durable_phase="narrative_planning")
      await runtime.generate_narrative_outline(_step_input(), _run_context())
      assert runtime.read_finding_graph.await_count == 1
      assert runtime.run_analysis_evidence.await_count == 0
  ```

- [ ] **Step 2: 运行定向测试确认失败**

  Run: `pytest smart_reporting/reporting/tests/test_dynamic_chapter_workflow.py smart_reporting/reporting/tests/test_reporting_cli.py -q`

  Expected: FAIL because the current workflow still calls `generate-outline` before analysis and has no narrative planning phase。

- [ ] **Step 3: 提取分析证据阶段**

  从现有 `run_reporting_analysis()` 中抽出分析项、补证、facts 和 checkpoint 收口逻辑，形成 `run_analysis_evidence()`。该阶段的每个分析任务使用自己的 `managementQuestion` 作为执行目标，不依赖最终章节的 `sectionGoal`。

  分析项必须继续保留：

  - 原子 `analysisId`；
  - 确定性 fact 文件身份；
  - 补证文件身份；
  - citation 和 dataset lineage；
  - 现有 retry、rework 和 durable command。

- [ ] **Step 4: 增加 Narrative Planning 状态和步骤**

  - 在 `ReportingPhase`、状态迁移表和 checkpoint reducer 中加入 `NARRATIVE_PLANNING`；
  - 将 FindingGraph 文件身份、图谱哈希和最终 NarrativeOutline 哈希写入 durable state；
  - 恢复时校验 FindingGraph 与 Profile coverage、revision 和事实快照一致；
  - 章节规划失败只记录结构化 issue，不删除已生成 facts 或下载产物。

- [ ] **Step 5: 修改 Workflow 顺序**

  将生产 Workflow 调整为：

  ```text
  ... → generate-detailed-analysis-plan
  → run-analysis-evidence
  → generate-narrative-outline
  → run-report-draft
  → assemble-report → validate-report → finalize-publication
  ```

  旧的 `ReportOutline` 在过渡期只作为兼容输入，不得再用于生成用户可见目录。

- [ ] **Step 6: 运行定向测试确认通过**

  Run: `pytest smart_reporting/reporting/tests/test_dynamic_chapter_workflow.py smart_reporting/reporting/tests/test_reporting_cli.py -q`

  Expected: PASS。

- [ ] **Step 7: 提交工作流拆分**

  ```bash
  git add smart_reporting/reporting/workflow/orchestration.py \
    smart_reporting/reporting/workflow/runtime/analysis.py \
    smart_reporting/reporting/workflow/state.py \
    smart_reporting/reporting/workflow/checkpoint.py \
    smart_reporting/reporting/workflow/runtime/base.py \
    smart_reporting/reporting/tests/test_dynamic_chapter_workflow.py \
    smart_reporting/reporting/tests/test_reporting_cli.py
  git commit -m "refactor: separate evidence analysis from narrative planning"
  ```

### Task 4: 实现基于发现关系的动态章节规划

**Files:**
- Create: `smart_reporting/reporting/hospital_operation/narrative_planner.py`
- Modify: `smart_reporting/reporting/workflow/runtime/planning.py`
- Modify: `smart_reporting/reporting/workflow/runtime/base.py`
- Modify: `smart_reporting/reporting/hospital_operation/outline.py`
- Test: `smart_reporting/reporting/tests/test_dynamic_narrative_planner.py`
- Test: `smart_reporting/reporting/tests/test_reporting_planner_contracts.py`

**Interfaces:**
- `build_narrative_planning_context(graph, report_goal, profile_coverage, content_budget) -> dict[str, Any]`。
- `score_finding_relation(left, right) -> float`：只使用共享指标、期间、粒度、关联关系、管理动作和证据状态。
- `rank_finding(finding) -> tuple[int, int, int]`：按优先级、证据等级和可行动性生成稳定排序键。
- `cluster_findings(graph, content_budget) -> tuple[tuple[str, ...], ...]`：确定性分组，保证不可兼容发现不合并。
- `plan_narrative_sections(candidate, graph, analyses) -> NarrativeOutline`：模型提出候选，服务端冻结和校验。

- [ ] **Step 1: 写动态分组失败测试**

  ```python
  def test_income_and_workload_findings_can_share_management_question():
      graph = _graph([_finding("finding_001", metric_codes=("income",), related=("finding_002",)), _finding("finding_002", metric_codes=("workload",), related=("finding_001",))])
      groups = cluster_findings(graph, _content_budget())
      assert {"finding_001", "finding_002"} in [set(group) for group in groups]

  def test_different_period_or_grain_findings_do_not_merge():
      graph = _graph([_finding("finding_001", period_roles=("current",), grain=("院区",)), _finding("finding_002", period_roles=("yoy",), grain=("科室",))])
      groups = cluster_findings(graph, _content_budget())
      assert all(set(group) != {"finding_001", "finding_002"} for group in groups)

  def test_no_budget_data_does_not_create_budget_section():
      graph = _graph([_finding("finding_001", metric_codes=("income",))])
      outline = plan_narrative_sections(_candidate_for(graph), graph, _analyses())
      assert all("预算" not in section.title for section in outline.sections)

  def test_low_priority_findings_are_sent_to_appendix_with_reason():
      graph = _graph([_finding("finding_001", priority="low")])
      outline = plan_narrative_sections(_candidate_for(graph), graph, _analyses())
      assert outline.appendix_finding_ids == ("finding_001",)
      assert outline.omitted_findings[0].reason

  def test_large_atomic_analysis_count_does_not_force_one_section_per_analysis():
      graph = _graph([_finding(f"finding_{index:03d}", analysis_ids=(f"analysis_{index:03d}",)) for index in range(1, 13)])
      outline = plan_narrative_sections(_candidate_for(graph), graph, _analyses(count=12))
      assert len(outline.sections) < len(graph.findings)

  def test_direct_attribution_ranks_above_statistical_relation():
      direct = _finding("finding_001", evidence_level="direct_decomposition")
      statistical = _finding("finding_002", evidence_level="statistical_relation")
      assert rank_finding(direct) > rank_finding(statistical)
  ```

- [ ] **Step 2: 运行定向测试确认失败**

  Run: `pytest smart_reporting/reporting/tests/test_dynamic_narrative_planner.py -q`

  Expected: FAIL because relation scoring and clustering do not exist。

- [ ] **Step 3: 实现确定性候选分组**

  - 先选择高优先级且可行动的发现作为章节锚点；
  - 按共享管理问题、指标、期间、粒度、已登记关系和行动责任计算关系分数；
  - 发现之间存在期间、粒度、口径或证据边界冲突时强制分开；
  - 按内容预算限制每组的 finding 数、事实字节数、图表数和正文块数；
  - 低影响发现合并进相关章节或附录，不按领域强制创建章节；
  - 记录每次合并、拆分、附录和忽略的理由。

- [ ] **Step 4: 改造 Outline Planner 输入和输出**

  `generate_narrative_outline()` 的模型输入必须包含：

  - FindingGraph 的紧凑投影；
  - 每个发现的影响、证据等级和引用身份；
  - 可用数据领域和数据限制；
  - 候选分组及其不可变约束；
  - 报告目标和内容预算。

  模型只返回动态标题、发现分组、章节目标和管理动作，不返回数值、事实、citation、section code 或领域空章。

- [ ] **Step 5: 增加服务端纠错和冻结**

  复用现有 planner correction 机制，但将错误路径扩展到 `findingIds`、`sections` 和 `appendixFindingIds`。连续纠错失败后，采用最后一次结构有效候选的确定性分组，并把具体 issue 写入软告警。

- [ ] **Step 6: 运行定向测试确认通过**

  Run: `pytest smart_reporting/reporting/tests/test_dynamic_narrative_planner.py smart_reporting/reporting/tests/test_reporting_planner_contracts.py -q`

  Expected: PASS。

- [ ] **Step 7: 提交动态章节规划**

  ```bash
  git add smart_reporting/reporting/hospital_operation/narrative_planner.py \
    smart_reporting/reporting/workflow/runtime/planning.py \
    smart_reporting/reporting/workflow/runtime/base.py \
    smart_reporting/reporting/hospital_operation/outline.py \
    smart_reporting/reporting/tests/test_dynamic_narrative_planner.py \
    smart_reporting/reporting/tests/test_reporting_planner_contracts.py
  git commit -m "feat: plan narrative chapters from verified findings"
  ```

### Task 5: 让章节成稿消费发现边界并保留追溯

**Files:**
- Modify: `smart_reporting/reporting/workflow/checkpoint.py`
- Modify: `smart_reporting/reporting/workflow/runtime/sections.py`
- Modify: `smart_reporting/reporting/workflow/runtime/analysis.py`
- Modify: `smart_reporting/reporting/workflow/runtime/reporting_draft_workflow.py`
- Modify: `smart_reporting/reporting/delivery/draft_v1.py`
- Test: `smart_reporting/reporting/tests/test_dynamic_section_rendering.py`
- Test: `smart_reporting/reporting/tests/test_trace_server_tables.py`

**Interfaces:**
- `SectionWorkItem` 新增 `findingIds`、`findingSummaries`、`narrativeRole` 和 `groupingReason`，保留原有 `analysisIds`、evidence、citations 和 factFiles。
- `_build_section_work_item()` 改为先读取 finding IDs，再投影对应分析项和事实文件。
- `_section_claim_authoring_contract()` 将允许的 finding 引用和管理问题绑定到当前章节。

- [ ] **Step 1: 写章节输入失败测试**

  ```python
  def test_section_work_item_contains_only_assigned_findings():
      item = _section_work_item(finding_ids=("finding_001",))
      assert tuple(item.finding_ids) == ("finding_001",)
      assert "finding_002" not in item.finding_ids

  def test_section_claim_cannot_reference_finding_from_another_section():
      item = _section_work_item(finding_ids=("finding_001",))
      with pytest.raises(ReportingError, match="finding"):
          validate_section_claim(item, finding_id="finding_002")

  def test_section_trace_keeps_analysis_ids_and_fact_file_identities():
      item = _section_work_item(finding_ids=("finding_001",), analysis_ids=("analysis_001",))
      assert item.analysis_ids == ("analysis_001",)
      assert item.fact_files[0].sha256

  def test_appendix_findings_are_rendered_without_becoming_main_sections():
      draft = render_narrative_outline(_outline_with_appendix("finding_002"))
      assert "finding_002" not in tuple(section.finding_ids for section in draft.sections)
      assert draft.appendix_finding_ids == ("finding_002",)
  ```

- [ ] **Step 2: 运行定向测试确认失败**

  Run: `pytest smart_reporting/reporting/tests/test_dynamic_section_rendering.py smart_reporting/reporting/tests/test_trace_server_tables.py -q`

  Expected: FAIL because SectionWorkItem has no finding projection。

- [ ] **Step 3: 扩展 SectionWorkItem 并实现发现投影**

  - 按 NarrativeOutline 的 finding 顺序构造章节输入；
  - 只加载章节分配的 facts、evidence、charts 和 citations；
  - 保留分析项顺序，保证旧的事实身份和回放接口继续可用；
  - finding 缺失时生成软告警并保留章节其他有效内容；
  - 章节正文提示明确要求“结论 → 证据 → 影响 → 动作”，不得新增事实或因果。

- [ ] **Step 4: 修改报告目录、图表和编辑器映射**

  - 封面和目录使用 NarrativeOutline 的最终标题和编号；
  - 图表按 finding 的指标、期间和章节预算选择；
  - 编辑器章节详情同时显示章节发现和原子分析追溯；
  - 旧 revision 没有 finding graph 时继续使用旧 `analysisIds` 兼容路径。

- [ ] **Step 5: 运行定向测试确认通过**

  Run: `pytest smart_reporting/reporting/tests/test_dynamic_section_rendering.py smart_reporting/reporting/tests/test_trace_server_tables.py -q`

  Expected: PASS。

- [ ] **Step 6: 提交章节成稿改造**

  ```bash
  git add smart_reporting/reporting/workflow/checkpoint.py \
    smart_reporting/reporting/workflow/runtime/sections.py \
    smart_reporting/reporting/workflow/runtime/analysis.py \
    smart_reporting/reporting/workflow/runtime/reporting_draft_workflow.py \
    smart_reporting/reporting/delivery/draft_v1.py \
    smart_reporting/reporting/tests/test_dynamic_section_rendering.py \
    smart_reporting/reporting/tests/test_trace_server_tables.py
  git commit -m "feat: render sections from assigned findings"
  ```

### Task 6: 加入质量指标、降级路径和发布回归

**Files:**
- Modify: `smart_reporting/reporting/workflow/runtime/validation.py`
- Modify: `smart_reporting/reporting/workflow/runtime/publication.py`
- Modify: `smart_reporting/reporting/presentation.py`
- Modify: `smart_reporting/reporting/workflow/state.py`
- Test: `smart_reporting/reporting/tests/test_dynamic_narrative_quality.py`
- Test: `smart_reporting/reporting/tests/test_publication_nonblocking.py`
- Test: `smart_reporting/reporting/tests/test_http_publication_lineage.py`
- Test: `smart_reporting/reporting/tests/test_report_editor_lineage_export.py`

**Interfaces:**
- Produces `NarrativeQualityMetrics`，字段包括 `findingCoverageRate`、`highPriorityCoverageRate`、`duplicateFindingCount`、`unassignedFindingCount`、`sectionCount`、`emptySectionCount`、`evidenceCoverageRate` 和 `groupingConflictCount`。
- `validate_narrative_quality(outline, graph, draft) -> tuple[dict[str, Any], ...]` 返回结构化软告警，不抛出发布门禁异常。

- [ ] **Step 1: 写质量和非阻断失败测试**

  ```python
  def test_quality_reports_unassigned_high_priority_finding():
      issues = validate_narrative_quality(_outline_without("finding_001"), _graph([_finding("finding_001", priority="high")]), _draft())
      assert any(issue["code"] == "finding_unassigned" for issue in issues)

  def test_quality_reports_duplicate_finding_without_blocking_artifacts():
      issues = validate_narrative_quality(_outline_with_duplicate("finding_001"), _graph([_finding("finding_001")]), _draft())
      assert any(issue["code"] == "finding_duplicate" for issue in issues)

  def test_quality_accepts_appendix_assignment_for_low_priority_finding():
      issues = validate_narrative_quality(_outline_with_appendix("finding_001"), _graph([_finding("finding_001", priority="low")]), _draft())
      assert not any(issue["code"] == "finding_unassigned" for issue in issues)

  async def test_publication_keeps_pdf_and_word_when_narrative_quality_fails():
      result = await publish_with_quality_issue("finding_unassigned")
      assert result["formalReleaseAllowed"] is False
      assert result["pdfDownloadUrl"]
      assert result["wordDownloadUrl"]
  ```

- [ ] **Step 2: 运行定向测试确认失败**

  Run: `pytest smart_reporting/reporting/tests/test_dynamic_narrative_quality.py smart_reporting/reporting/tests/test_publication_nonblocking.py -q`

  Expected: FAIL because narrative quality metrics and checks do not exist。

- [ ] **Step 3: 实现质量计算和软告警**

  - 计算发现覆盖、证据覆盖、重复、遗漏、空章节和合并冲突；
  - 质量问题写入 `validation.issues` 或 `publicationGate.issues`；
  - 不得用 `raise` 阻断已经生成且身份可读取的 PDF/Word 下载；
  - 完成消息给出具体章节、发现 ID、原因和建议动作。

- [ ] **Step 4: 保留旧状态和旧导出兼容**

  - 旧报告没有 FindingGraph 时回退到旧提纲和 analysisId 校验；
  - 新报告发布清单登记 FindingGraph 和 NarrativeOutline 文件身份；
  - 编辑器导出验收失败、追溯缺失和溯源故障继续按现有非阻断契约签发链接。

- [ ] **Step 5: 运行定向回归测试确认通过**

  Run:

  ```bash
  pytest smart_reporting/reporting/tests/test_dynamic_narrative_quality.py \
    smart_reporting/reporting/tests/test_publication_nonblocking.py \
    smart_reporting/reporting/tests/test_http_publication_lineage.py \
    smart_reporting/reporting/tests/test_report_editor_lineage_export.py -q
  ```

  Expected: PASS。

- [ ] **Step 6: 提交质量与降级路径**

  ```bash
  git add smart_reporting/reporting/workflow/runtime/validation.py \
    smart_reporting/reporting/workflow/runtime/publication.py \
    smart_reporting/reporting/presentation.py \
    smart_reporting/reporting/workflow/state.py \
    smart_reporting/reporting/tests/test_dynamic_narrative_quality.py \
    smart_reporting/reporting/tests/test_publication_nonblocking.py \
    smart_reporting/reporting/tests/test_http_publication_lineage.py \
    smart_reporting/reporting/tests/test_report_editor_lineage_export.py
  git commit -m "feat: add dynamic narrative quality gates"
  ```

### Task 7: 真实医院运营报告验收

**Files:**
- Create: `smart_reporting/reporting/tests/fixtures/dynamic_narrative_hospital_cases.json`
- Test: `smart_reporting/reporting/tests/test_dynamic_narrative_hospital_cases.py`

**Interfaces:**
- 使用固定测试 fixture 描述收入、工作量、预算、全成本、费控和资金的事实卡片，不读取真实运行产物。
- 端到端断言只检查章节结构、发现覆盖、证据等级、追溯身份和发布结果，不把具体运行时文件加入 Git。

- [ ] **Step 1: 写六类业务场景测试**

  覆盖：

  1. 收入和工作量共同解释增长时合并为同一管理主题；
  2. 收入增长但成本增速更高时形成经营影响发现；
  3. 回款、应收和现金余额共同形成资金风险主题；
  4. 没有预算数据时不生成预算空章；
  5. 只有相关性时显示统计关系，不显示确定原因；
  6. 数据质量限制影响结论时提升为风险或限制发现。

- [ ] **Step 2: 运行场景测试**

  Run: `pytest smart_reporting/reporting/tests/test_dynamic_narrative_hospital_cases.py -q`

  Expected: PASS；章节数量由 fixture 中的发现关系决定，不能通过固定六域目录得到相同结果。

- [ ] **Step 3: 做一次必要的报告级回归**

  Run:

  ```bash
  pytest smart_reporting/reporting/tests/test_report_runtime_full_render.py \
    smart_reporting/reporting/tests/test_report_editor.py \
    smart_reporting/reporting/tests/test_publication_nonblocking.py -q
  ```

  Expected: PASS；PDF/Word 下载、编辑器导出、追溯和发布失败保留产物契约不变。

- [ ] **Step 4: 提交验收 fixture 与文档**

  ```bash
  git add smart_reporting/reporting/tests/fixtures/dynamic_narrative_hospital_cases.json \
    smart_reporting/reporting/tests/test_dynamic_narrative_hospital_cases.py
  git commit -m "test: verify dynamic hospital narrative chapters"
  ```

## 实施顺序与回滚

先完成 Task 1、Task 2，再做 Task 3 的流程拆分；Task 4 和 Task 5 必须在新的 NarrativeOutline 契约稳定后实施。Task 6 和 Task 7 是发布前门槛。

每个阶段都保留旧 `ReportOutline` 和 `analysisIds` 读取能力。若新章节规划失败，报告可以回退到内部确定性分组并继续生成已验证内容；若新版本无法读取 FindingGraph，则只允许回退到同一 revision 的旧提纲和已核验 facts，不重新计算或伪造章节发现。

## 完成判定

- 章节规划在真实 facts 和补证之后执行；
- 章节数量不再由原子分析项数量直接决定；
- 没有数据的领域不生成空章节；
- 跨域发现可以合并，口径冲突的发现不会合并；
- 每个高优先级发现都有正文或附录去向；
- 每个正文数字和结论仍可追溯到同一事实快照；
- 质量失败保留可读取的 PDF/Word 下载链接，并明确返回原因；
- 定向测试和必要发布回归全部通过。
