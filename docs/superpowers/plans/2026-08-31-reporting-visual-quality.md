# Reporting Visual Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不阻断图表发布、不改变事实与血缘契约的前提下，提高图表可读性并改善 PDF、Word 章节中的图片尺寸和分页。

**Architecture:** 图表生成规则继续由现有 Skill 与 Worker 指令负责；像素和有效 DPI 检查继续归属 `RuntimeSectionsMixin._inspect_chart`，只追加既有 warnings；文档展示只调整现有 CSS 和 DOCX 等比缩放。改动不新增公共 Schema，不改变 `visualInspectionMode`、Markdown、`chartIds`、文件哈希或 Manifest。

**Tech Stack:** Python 3.12、pytest、Pillow、MarkdownIt、WeasyPrint、python-docx、Ruff、Mypy

---

### Task 1: 图表生成可读性协议

**Files:**
- Modify: `smart_reporting/reporting/builtin_skills/report-visualization/SKILL.md`
- Modify: `smart_reporting/reporting/instructions.py`
- Test: `smart_reporting/reporting/tests/test_reporting_agent_projection.py`

- [ ] **Step 1: 写入失败测试**

把现有 instructions 导入扩展为：

```python
from smart_reporting.reporting.instructions import (
    REPORT_VISUALIZATION_AGENT_INSTRUCTIONS,
    build_report_agent_instructions,
)
```

```python
def test_visualization_instructions_require_readable_chart_layouts() -> None:
    instructions = "\n".join(REPORT_VISUALIZATION_AGENT_INSTRUCTIONS)
    assert "最短业务名称" in instructions
    assert "1200 x 675" in instructions
    assert "横向条形图" in instructions
    assert "动态调整画布高度" in instructions
    assert "紧凑对比图" in instructions
```

Skill 文档属于同一生成协议，随生产指令同步修改；最终用 `git diff --check` 检查 Markdown。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd smart_reporting && pytest reporting/tests/test_reporting_agent_projection.py::test_visualization_instructions_require_readable_chart_layouts -q`

Expected: FAIL，当前指令缺少短标签、尺寸和布局要求。

- [ ] **Step 3: 最小修改 Skill 和 Worker 指令**

```python
(
    "分类轴只使用能唯一识别对象的最短业务名称；完整组织层级、日期、Dataset 路径和血缘信息"
    "放入正文、表格、脚注或图表说明，不得直接放入坐标轴。TopN 或长标签优先横向条形图，"
    "按项目数量动态调整画布高度并对过长标签做语义缩写或换行；只有两个或少量指标时优先"
    "紧凑对比图、哑铃图或表格。保存图表的目标像素尺寸不低于 1200 x 675，并为标题、坐标轴、"
    "图例和数据标签保留安全边界；这些规则不限制选择其他更合适的图形。"
),
```

`SKILL.md` 同步表达该原则，不增加模板、图表数量或类型白名单。

- [ ] **Step 4: 验证并提交**

Run: `cd smart_reporting && pytest reporting/tests/test_reporting_agent_projection.py::test_visualization_instructions_require_readable_chart_layouts reporting/tests/test_reporting_agent_projection.py::test_deterministic_visualization_instructions_forbid_inspect_chart -q`

Expected: 2 passed；确定性模式行为不变。

```bash
git add smart_reporting/reporting/builtin_skills/report-visualization/SKILL.md smart_reporting/reporting/instructions.py smart_reporting/reporting/tests/test_reporting_agent_projection.py
git commit -m "feat: improve reporting chart readability guidance"
```

### Task 2: 非阻断分辨率与有效 DPI 告警

**Files:**
- Modify: `smart_reporting/reporting/tools/sections.py`
- Test: `smart_reporting/reporting/tests/test_reporting_tool_contracts.py`

- [ ] **Step 1: 写入像素边界失败测试**

增加导入和两个小型测试构造，再参数化调用 `_inspect_chart`：

```python
from smart_reporting.reporting.delivery.draft_v1 import ReportChartRegistration


def _chart_registration() -> ReportChartRegistration:
    return ReportChartRegistration(
        chartId="income",
        sourcePath="analysis/charts/income.png",
        title="收入趋势",
        altText="收入趋势图",
        citationIds=("citation-1",),
        metricCodes=("income",),
        currentPeriod="2026-01",
        comparisonPeriod="2025-01",
        comparisonType="yoy",
        sourceDatasetId="dataset-1",
        aggregationGrain="month",
        comparability="strict",
    )


def _chart_image_identity(width: int, height: int) -> dict[str, Any]:
    return {
        "sourcePath": "analysis/charts/income.png",
        "size": 1024,
        "sha256": "a" * 64,
        "format": "PNG",
        "mediaType": "image/png",
        "extension": ".png",
        "width": width,
        "height": height,
    }
```

```python
@pytest.mark.anyio
@pytest.mark.parametrize("width,height", [(1199, 675), (1200, 674)])
async def test_inspect_chart_warns_below_target_resolution_without_rejecting(
    width: int, height: int
) -> None:
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit._inspect_chart_file = AsyncMock(return_value=_chart_image_identity(width, height))
    identity, warnings = await toolkit._inspect_chart(
        thread_id="thread-1", registration=_chart_registration()
    )
    assert identity["width"] == width
    warning = next(item for item in warnings if item["code"] == "chart_low_resolution")
    assert warning["minimumWidth"] == 1200
    assert warning["minimumHeight"] == 675
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd smart_reporting && pytest reporting/tests/test_reporting_tool_contracts.py::test_inspect_chart_warns_below_target_resolution_without_rejecting -q`

Expected: FAIL，当前阈值仍为 `800 x 450`。

- [ ] **Step 3: 最小提高告警阈值**

```python
MIN_REPORT_CHART_WIDTH = 1200
MIN_REPORT_CHART_HEIGHT = 675
MIN_REPORT_CHART_EFFECTIVE_DPI = 150
REPORT_BODY_WIDTH_INCHES = 174 / 25.4
```

174 mm 来自 A4 宽 210 mm 减去现有左右各 18 mm 页边距；在代码中用中文注释注明只作质量估算。更新现有 `chart_low_resolution` 字典，增加 `minimumWidth`、`minimumHeight`，消息明确为非阻断告警，不抛异常。

- [ ] **Step 4: 验证像素边界通过**

Run: `cd smart_reporting && pytest reporting/tests/test_reporting_tool_contracts.py::test_inspect_chart_warns_below_target_resolution_without_rejecting -q`

Expected: 2 passed。

- [ ] **Step 5: 写入有效 DPI 失败测试**

```python
@pytest.mark.anyio
async def test_inspect_chart_warns_for_low_effective_dpi_without_rejecting() -> None:
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit._inspect_chart_file = AsyncMock(return_value=_chart_image_identity(1000, 700))
    identity, warnings = await toolkit._inspect_chart(
        thread_id="thread-1", registration=_chart_registration()
    )
    assert identity["sha256"] == "a" * 64
    warning = next(item for item in warnings if item["code"] == "chart_low_effective_dpi")
    assert warning["minimumDpi"] == 150
    assert warning["effectiveDpi"] == 146
```

- [ ] **Step 6: 运行测试确认失败**

Run: `cd smart_reporting && pytest reporting/tests/test_reporting_tool_contracts.py::test_inspect_chart_warns_for_low_effective_dpi_without_rejecting -q`

Expected: FAIL，当前没有 `chart_low_effective_dpi`。

- [ ] **Step 7: 实现非阻断有效 DPI 告警**

```python
effective_dpi = round(width / REPORT_BODY_WIDTH_INCHES)
if effective_dpi < MIN_REPORT_CHART_EFFECTIVE_DPI:
    warnings.append(
        {
            "code": "chart_low_effective_dpi",
            "chartId": registration.chart_id,
            "width": width,
            "height": height,
            "effectiveDpi": effective_dpi,
            "minimumDpi": MIN_REPORT_CHART_EFFECTIVE_DPI,
            "message": "图表正文有效 DPI 偏低，已记录非阻断质量告警。",
        }
    )
```

- [ ] **Step 8: 验证登记链路并提交**

Run: `cd smart_reporting && pytest reporting/tests/test_reporting_tool_contracts.py -k 'inspect_chart or register_report_charts' -q`

Expected: 全部通过；低质量图仍返回 identity，登记成功并携带 warnings。

```bash
git add smart_reporting/reporting/tools/sections.py smart_reporting/reporting/tests/test_reporting_tool_contracts.py
git commit -m "feat: warn on low quality reporting charts"
```

### Task 3: 章节图片尺寸与分页策略

**Files:**
- Modify: `smart_reporting/reporting/delivery/report_runtime/markdown.py`
- Modify: `smart_reporting/reporting/delivery/report_runtime/docx.py`
- Test: `smart_reporting/reporting/tests/test_reporting_heading_numbers.py`
- Test: `smart_reporting/reporting/tests/test_report_runtime.py`

- [ ] **Step 1: 写入 PDF/HTML CSS 失败测试**

扩展 `test_document_context_and_manifest_share_heading_number_contract`：

```python
assert "max-height:180mm" in pdf_html
assert "object-fit:contain" in pdf_html
assert "p:has(>img)+p{break-before:avoid;break-after:avoid" in pdf_html
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd smart_reporting && pytest reporting/tests/test_reporting_heading_numbers.py::test_document_context_and_manifest_share_heading_number_contract -q`

Expected: FAIL，当前没有最大正文高度，图注没有 `break-after:avoid`。

- [ ] **Step 3: 最小调整图片与分页 CSS**

```python
"img{display:block;max-width:100%;max-height:180mm;width:auto;height:auto;"
"object-fit:contain;margin:12px auto;break-inside:avoid}"
"p:has(>img){break-after:avoid;margin-bottom:1mm}"
"p:has(>img)+p{break-before:avoid;break-after:avoid;margin-top:0;text-align:center;color:"
```

通过宽、高双边界自然适配横向、超宽和偏高图片，不向 Markdown 增加 class 或尺寸字段。

- [ ] **Step 4: 验证 CSS 测试通过**

Run: `cd smart_reporting && pytest reporting/tests/test_reporting_heading_numbers.py::test_document_context_and_manifest_share_heading_number_contract -q`

Expected: 1 passed。

- [ ] **Step 5: 写入 DOCX 高图缩放失败测试**

在 `test_report_runtime.py` 中仿照 `test_postprocess_docx_uses_section_page_count_field` 创建带三个分节 marker 的最小文档；用 Pillow 生成 `600 x 1800` PNG，在 `__REPORT_BODY_START__` 后通过 `document.add_picture` 加入正文。增加 `from docx.shared import Mm`，调用 `_postprocess_docx` 后重新打开文档并读取唯一 inline shape：

```python
assert shape.width <= Mm(174)
assert shape.height <= Mm(180)
assert abs((shape.width / shape.height) - source_ratio) < 0.01
```

- [ ] **Step 6: 运行测试确认失败**

Run: `cd smart_reporting && pytest reporting/tests/test_report_runtime.py -k 'docx and tall_image' -q`

Expected: FAIL，当前 DOCX 只限制图片宽度。

- [ ] **Step 7: 实现 DOCX 等比双边界缩放**

```python
available_width = sections[-1].page_width - sections[-1].left_margin - sections[-1].right_margin
maximum_chart_height = Mm(180)
for shape in document.inline_shapes:
    scale = min(1, available_width / shape.width, maximum_chart_height / shape.height)
    if scale < 1:
        shape.width = int(shape.width * scale)
        shape.height = int(shape.height * scale)
```

- [ ] **Step 8: 验证章节渲染并提交**

Run: `cd smart_reporting && pytest reporting/tests/test_reporting_heading_numbers.py reporting/tests/test_report_runtime.py -q`

Expected: 全部通过；Markdown 路径、HTML 内联和 DOCX 图片计数行为不变。

```bash
git add smart_reporting/reporting/delivery/report_runtime/markdown.py smart_reporting/reporting/delivery/report_runtime/docx.py smart_reporting/reporting/tests/test_reporting_heading_numbers.py smart_reporting/reporting/tests/test_report_runtime.py
git commit -m "feat: improve reporting chart layout in documents"
```

### Task 4: 综合验证

**Files:**
- Verify only; no new files expected

- [ ] **Step 1: 运行直接相关测试**

Run: `cd smart_reporting && pytest reporting/tests/test_reporting_agent_projection.py reporting/tests/test_reporting_tool_contracts.py reporting/tests/test_reporting_heading_numbers.py reporting/tests/test_report_runtime.py -q`

Expected: 全部通过，无失败或错误。

- [ ] **Step 2: 格式和静态检查**

```bash
cd smart_reporting && ruff format --check reporting/instructions.py reporting/tools/sections.py reporting/tests/test_reporting_agent_projection.py reporting/tests/test_reporting_tool_contracts.py reporting/delivery/report_runtime/markdown.py reporting/delivery/report_runtime/docx.py reporting/tests/test_reporting_heading_numbers.py reporting/tests/test_report_runtime.py
cd smart_reporting && ruff check reporting/instructions.py reporting/tools/sections.py reporting/tests/test_reporting_agent_projection.py reporting/tests/test_reporting_tool_contracts.py reporting/delivery/report_runtime/markdown.py reporting/delivery/report_runtime/docx.py reporting/tests/test_reporting_heading_numbers.py reporting/tests/test_report_runtime.py
cd smart_reporting && mypy reporting/instructions.py reporting/tools/sections.py reporting/delivery/report_runtime/markdown.py reporting/delivery/report_runtime/docx.py
```

Expected: 全部退出 0，无新增格式、lint 或类型错误。

- [ ] **Step 3: 检查最终差异边界**

```bash
git diff --check HEAD~3..HEAD
git status --short
git diff --stat HEAD~3..HEAD
```

Expected: 只有计划内文件；既有未跟踪文件未提交；仓库内没有 PDF、日志、截图或临时产物。
