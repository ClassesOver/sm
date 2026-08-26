# Reporting 可视化引用交接 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让可视化 Analysis Task 在普通和恢复模式下都能按分析项取得服务端签发的 citation ID 映射。

**Architecture:** 在 `analysis.py` 添加一个仅派生稳定 ID 的纯函数，并在可视化任务指令中调用它。图表登记仍只依赖签名 phase contract 内现有的全量 `citationIds`，不会扩大工具权限或暴露引用正文。

**Tech Stack:** Python 3.12、Pydantic 模型、pytest、Ruff、Mypy。

---

**文件结构：**

- 修改：`smart_reporting/reporting/workflow/runtime/analysis.py`，定义按冻结分析计划和受信引用绑定生成映射的私有纯函数，并把映射投影进可视化任务指令。
- 修改：`smart_reporting/reporting/tests/test_reporting_tool_contracts.py`，覆盖映射的归属、稳定顺序和最小数据边界。

### Task 1: 为可视化引用映射建立失败回归测试

**Files:**
- Modify: `smart_reporting/reporting/tests/test_reporting_tool_contracts.py:64-70`
- Modify: `smart_reporting/reporting/tests/test_reporting_tool_contracts.py`（在可视化辅助函数测试区域新增用例）

- [ ] **Step 1: 导入模型和待实现的映射函数**

```python
from smart_reporting.reporting.delivery.artifacts_v1 import Citation
from smart_reporting.reporting.hospital_operation.detailed_analysis import (
    DetailedAnalysisItem,
    DetailedAnalysisPlan,
)
from smart_reporting.reporting.workflow.runtime.analysis import (
    _visualization_analysis_citation_ids,
)
```

- [ ] **Step 2: 写入失败测试**

```python
def test_visualization_analysis_citation_ids_only_projects_bound_ids() -> None:
    plan = DetailedAnalysisPlan(
        datasetIds=("dataset-income", "dataset-budget", "dataset-unused"),
        analyses=(
            DetailedAnalysisItem(
                analysisId="analysis_001", domain="income", managementQuestion="收入趋势",
                primaryMetricFamily="收入", datasetIds=("dataset-income",), fields=(),
                metrics=(), periods=(), actions=("趋势",), evidenceSummary="固定事实",
                suggestedSection="收入", completionConditions=("完成",),
            ),
            DetailedAnalysisItem(
                analysisId="analysis_002", domain="budget", managementQuestion="预算执行",
                primaryMetricFamily="预算", datasetIds=("dataset-budget", "dataset-income"),
                fields=(), metrics=(), periods=(), actions=("对比",), evidenceSummary="固定事实",
                suggestedSection="预算", completionConditions=("完成",),
            ),
        ),
    )
    citations = (
        Citation(citationId="citation-income", datasetId="dataset-income", requirementId="r1", snapshotHash="a" * 64),
        Citation(citationId="citation-budget", datasetId="dataset-budget", requirementId="r2", snapshotHash="b" * 64),
        Citation(citationId="citation-unused", datasetId="dataset-unused", requirementId="r3", snapshotHash="c" * 64),
    )

    assert _visualization_analysis_citation_ids(plan, citations) == {
        "analysis_001": ["citation-income"],
        "analysis_002": ["citation-income", "citation-budget"],
    }
```

- [ ] **Step 3: 运行测试，确认其因缺少函数而失败**

Run: `.venv-agent/bin/python -m pytest smart_reporting/reporting/tests/test_reporting_tool_contracts.py::test_visualization_analysis_citation_ids_only_projects_bound_ids -q`

Expected: FAIL，错误指向无法导入 `_visualization_analysis_citation_ids`。

### Task 2: 投影最小受信引用索引

**Files:**
- Modify: `smart_reporting/reporting/workflow/runtime/analysis.py:1059-1080`

- [ ] **Step 1: 实现纯映射函数**

在 `_coding_detailed_analysis_plan` 附近新增：

```python
def _visualization_analysis_citation_ids(
    plan: DetailedAnalysisPlan,
    citations: tuple[Citation, ...],
) -> dict[str, list[str]]:
    return {
        analysis.analysis_id: [
            citation.citation_id
            for citation in citations
            if citation.dataset_id in analysis.dataset_ids
        ]
        for analysis in plan.analyses
    }
```

- [ ] **Step 2: 将映射加入可视化任务指令**

在 `instruction_payload` 中、`registeredCharts` 后插入：

```python
"analysisCitationIds": _visualization_analysis_citation_ids(
    detailed_plan, citation_bindings
),
```

不得加入 `citationRegistry`、`snapshotHash`、引用正文、事实正文或新的工具权限。`phase_contract["citationIds"]` 保持原样。

- [ ] **Step 3: 运行定点测试，确认转绿**

Run: `.venv-agent/bin/python -m pytest smart_reporting/reporting/tests/test_reporting_tool_contracts.py::test_visualization_analysis_citation_ids_only_projects_bound_ids -q`

Expected: PASS。

- [ ] **Step 4: 运行受影响测试与静态检查**

Run:

```bash
.venv-agent/bin/python -m pytest smart_reporting/reporting/tests/test_reporting_tool_contracts.py -q
.venv-agent/bin/python -m ruff format --check smart_reporting/reporting/workflow/runtime/analysis.py smart_reporting/reporting/tests/test_reporting_tool_contracts.py
.venv-agent/bin/python -m ruff check smart_reporting/reporting/workflow/runtime/analysis.py smart_reporting/reporting/tests/test_reporting_tool_contracts.py
.venv-agent/bin/python -m mypy smart_reporting/reporting/workflow/runtime/analysis.py
```

Expected: 全部命令以退出码 0 结束。

- [ ] **Step 5: 检查差异并提交实现**

```bash
git diff --check
git status --short
git add smart_reporting/reporting/workflow/runtime/analysis.py smart_reporting/reporting/tests/test_reporting_tool_contracts.py
git commit -m "fix(reporting): project visualization citation mappings"
```
