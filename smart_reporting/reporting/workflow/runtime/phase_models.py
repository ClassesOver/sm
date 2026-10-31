"""固定 Reporting 阶段的模型生成契约。"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from typing import Annotated, Any, Literal

from loguru import logger
from markdown_it import MarkdownIt
from pydantic import ConfigDict, Field, RootModel, TypeAdapter, field_validator, model_validator

from ...contract import StrictModel, safe_relative_posix_path
from ...delivery.draft_v1 import (
    _ATX_HEADING,
    _MANUAL_HEADING_NUMBER,
    REPORT_HEADING_TITLE_MAX_LENGTH,
    ReportDraftBlock,
    _inline_heading_text,
    normalize_model_block_markdown,
    validate_report_block_markdown,
)
from ...models import ReportingError
from ...trace.contracts_v1 import ClaimInterpretationV1
from ..checkpoint import FileIdentity, SectionClaimSubmission
from .standard_chart_contract import SourceLabelMode, StandardChartForm, SummaryAggregation

MAX_SECTION_BLOCK_MARKDOWN_CHARS = 8_000
_DEFAULT_SECTION_CHART_COUNT = 3


def _section_chart_count_from_environment() -> int:
    """每章图表上限允许用环境变量在进程启动时覆盖；非法值软告警并回退默认。"""

    raw = os.environ.get("AGENT_REPORT_MAX_SECTION_CHART_COUNT", "").strip()
    if not raw:
        return _DEFAULT_SECTION_CHART_COUNT
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if not 1 <= value <= 100:
        logger.warning(
            "AGENT_REPORT_MAX_SECTION_CHART_COUNT={} 无效，每章图表上限回退默认值 {}",
            raw,
            _DEFAULT_SECTION_CHART_COUNT,
        )
        return _DEFAULT_SECTION_CHART_COUNT
    return value


# 在模块导入时解析：charts 字段的 max_length 与指令文案都绑定该常量。
MAX_SECTION_CHART_COUNT = _section_chart_count_from_environment()
_CJK_TEXT_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_SUBORDINATE_HEADING_RE = re.compile(r"^(?P<indent> {0,3})#{5,6}(?P<spacing>[ \t]+)")
_RUNON_HEADING_BREAK_RE = re.compile(r"[。！？；：]")


def _normalize_setext_headings(markdown: str) -> str:
    """把模型误触发的 setext 标题还原为段落。

    段落下一行紧跟 `---` 时 CommonMark 会解析为 H2（`===` 为 H1），模型本意几乎总是
    分隔线；不处理会被判为 H1/H2 越级且反馈难以自愈。`---` 前补空行变成分隔线，
    `===` 下划线直接删除；只处理顶层块，避免破坏列表或引用容器。
    """

    lines = markdown.splitlines(keepends=True)
    underline_lines: dict[int, str] = {}
    for token in MarkdownIt("commonmark").parse(markdown):
        if (
            token.type != "heading_open"
            or token.level != 0
            or token.markup not in {"-", "="}
            or token.map is None
        ):
            continue
        underline_lines[token.map[1] - 1] = token.markup
    if not underline_lines:
        return markdown
    for line_index in sorted(underline_lines, reverse=True):
        if underline_lines[line_index] == "=":
            del lines[line_index]
        else:
            lines.insert(line_index, "\n")
    logger.bind(normalized_heading_count=len(underline_lines)).warning(
        "report_section_setext_heading_normalized"
    )
    return "".join(lines)


def _normalize_subordinate_heading_levels(markdown: str) -> str:
    """将模型过度细分的 H5/H6 提升到正文协议允许的 H4。"""

    lines = markdown.splitlines(keepends=True)
    normalized_count = 0
    for token in MarkdownIt("commonmark").parse(markdown):
        if token.type != "heading_open" or token.tag not in {"h5", "h6"} or token.map is None:
            continue
        line_index = token.map[0]
        normalized, replacements = _SUBORDINATE_HEADING_RE.subn(
            r"\g<indent>####\g<spacing>",
            lines[line_index],
            count=1,
        )
        if replacements:
            lines[line_index] = normalized
            normalized_count += 1
    if normalized_count:
        logger.bind(normalized_heading_count=normalized_count).warning(
            "report_section_heading_level_normalized"
        )
    return "".join(lines)


def _normalize_runon_heading_lines(markdown: str) -> str:
    """把正文混入标题行的超长标题按首个句末标点拆分为短标题和正文段。

    标题行契约要求可见文本不超过上限且不得包含正文；弱模型常把标题和整段正文
    写在同一行，导致纠错反馈无法自愈。句末标点（。！？；：）不可能出现在合规
    短标题内，因此按首个句末标点拆分是内容零丢失的确定性收敛；标点前缀仍超
    上限或没有句末标点时不猜测拆分点，保留原值由严格校验失败关闭。
    """

    lines = markdown.splitlines(keepends=True)
    normalized_count = 0
    for token in MarkdownIt("commonmark").parse(markdown):
        if token.type != "heading_open" or token.map is None or token.tag not in {"h3", "h4"}:
            continue
        line_index = token.map[0]
        if line_index >= len(lines):
            continue
        raw_line = lines[line_index].rstrip("\r\n")
        match = _ATX_HEADING.fullmatch(raw_line)
        if match is None:
            continue
        title = match.group("title").strip()
        visible_title = _inline_heading_text(_MANUAL_HEADING_NUMBER.sub("", title).strip())
        if len(visible_title) <= REPORT_HEADING_TITLE_MAX_LENGTH:
            continue
        inline_tokens = MarkdownIt("commonmark").parseInline(title)
        inline_children = inline_tokens[0].children if inline_tokens else ()
        if any(item.type != "text" for item in inline_children or ()):
            # 不在成对的行内 Markdown 中间拆分，交给严格校验纠错。
            continue
        break_match = _RUNON_HEADING_BREAK_RE.search(title)
        if break_match is None:
            continue
        prefix = title[: break_match.start()].strip()
        visible_prefix = (
            _inline_heading_text(_MANUAL_HEADING_NUMBER.sub("", prefix).strip()) if prefix else ""
        )
        if not visible_prefix or len(visible_prefix) > REPORT_HEADING_TITLE_MAX_LENGTH:
            continue
        remainder = title[break_match.end() :].strip()
        marker = "#" * int(token.tag.removeprefix("h"))
        ending = lines[line_index][len(raw_line) :]
        rebuilt = (
            f"{marker} {prefix}\n\n{remainder}{ending}"
            if remainder
            else f"{marker} {prefix}{ending}"
        )
        lines[line_index] = rebuilt
        normalized_count += 1
    if normalized_count:
        logger.bind(normalized_heading_count=normalized_count).warning(
            "report_section_runon_heading_normalized"
        )
    return "".join(lines)


_OVERLONG_HEADING_PREVIEW_CHARS = 50


def _overlong_heading_diagnostics(markdown: str) -> tuple[dict[str, Any], ...]:
    """定位可见文本超限的 H3/H4 标题行，为结构化纠错反馈提供可行动事实。

    与 _normalize_runon_heading_lines 使用同一长度判定：可按句末标点拆分修复的
    超长标题行已在 before 校验阶段收敛，这里报告的必然是归一化放弃修复、
    需要模型按反馈缩短的原始超长标题。
    """

    lines = markdown.splitlines(keepends=True)
    diagnostics: list[dict[str, Any]] = []
    for token in MarkdownIt("commonmark").parse(markdown):
        if token.type != "heading_open" or token.map is None or token.tag not in {"h3", "h4"}:
            continue
        line_index = token.map[0]
        if line_index >= len(lines):
            continue
        match = _ATX_HEADING.fullmatch(lines[line_index].rstrip("\r\n"))
        if match is None:
            continue
        visible = _inline_heading_text(
            _MANUAL_HEADING_NUMBER.sub("", match.group("title").strip()).strip()
        )
        if len(visible) > REPORT_HEADING_TITLE_MAX_LENGTH:
            preview = visible[:_OVERLONG_HEADING_PREVIEW_CHARS]
            if len(visible) > _OVERLONG_HEADING_PREVIEW_CHARS:
                preview = f"{preview}…"
            diagnostics.append(
                {
                    "lineNumber": line_index + 1,
                    "actualLength": len(visible),
                    "preview": preview,
                }
            )
    return tuple(diagnostics)


def _block_validation_feedback(markdown: str, error: ReportingError) -> str:
    """把正文块协议错误转成模型可定位、可修复的纠错消息。

    结构化执行器回灌 issues 时只保留 path/type/message（validation 上下文与
    input 都会被裁剪）。消息是唯一能送达模型的通道，因此把行号、实际长度和
    具体修正动作并入消息；其他错误码沿用原始 message，行为不变。
    """

    message = str(error)
    if error.code != "report_draft_heading_title_too_long":
        return message
    segments = [message]
    for item in _overlong_heading_diagnostics(markdown):
        segments.append(
            f"第 {item['lineNumber']} 行标题可见文本 {item['actualLength']} 个字符"
            f"（上限 {REPORT_HEADING_TITLE_MAX_LENGTH}）：『{item['preview']}』。"
        )
    segments.append(
        "请缩短超限标题行的可见文本；若标题行混入了正文，"
        "改写为『### 短标题』后接空行，正文另起段落。"
    )
    return "".join(segments)


class ChartDataBinding(StrictModel):
    analysis_id: str = Field(alias="analysisId", min_length=1, max_length=128)
    fact_path: str = Field(alias="factPath", min_length=1, max_length=1024)
    data_path: str = Field(alias="dataPath", min_length=1, max_length=512)
    fields: tuple[str, ...] = Field(min_length=1, max_length=100)
    role: str = Field(min_length=1, max_length=200)

    @field_validator("fact_path")
    @classmethod
    def validate_fact_path(cls, value: str) -> str:
        path = safe_relative_posix_path(value, "图表事实路径必须是安全工作区相对路径")
        return path.as_posix()

    @field_validator("analysis_id", "data_path", "role")
    @classmethod
    def validate_nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("图表数据绑定文本不能为空")
        return value

    @field_validator("fields")
    @classmethod
    def validate_fields(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item.strip() for item in value) or len(value) != len(set(value)):
            raise ValueError("图表数据绑定字段必须非空且不能重复")
        return value


class StandardChartAnnotation(StrictModel):
    kind: Literal['values', 'peak', 'trough', 'point', 'reference', 'range']
    series: str | None = Field(default=None, max_length=200)
    label: str | None = Field(default=None, max_length=200)
    end_label: str | None = Field(default=None, alias='endLabel', max_length=200)
    row_label: str | None = Field(default=None, alias='rowLabel', max_length=200)
    end_row_label: str | None = Field(default=None, alias='endRowLabel', max_length=200)
    color: str | None = Field(default=None, pattern=r'^#[0-9a-fA-F]{6}$')
    highlight: bool = False
    position: Literal['auto', 'above', 'below', 'left', 'right'] = 'auto'
    caption: str | None = Field(default=None, max_length=60, description='参考线或重点标注的业务简称；数值仍从冻结数据生成')


class StandardChartAxisDomain(StrictModel):
    minimum: float | None = Field(default=None, alias='min', strict=True, allow_inf_nan=False)
    maximum: float | None = Field(default=None, alias='max', strict=True, allow_inf_nan=False)
    ticks: tuple[Annotated[float, Field(strict=True, allow_inf_nan=False)], ...] = Field(default=(), max_length=16)
    tick_format: Literal['auto', 'number', 'scientific'] = Field(default='auto', alias='tickFormat')
    decimals: int | None = Field(default=None, ge=0, le=6)
    out_of_range: Literal['reject', 'annotate'] = Field(default='reject', alias='outOfRange',
        description='默认拒绝裁切数据；annotate显式允许缩小显示范围，并注明超界图形端点数量；底层值保持不变。')

    @model_validator(mode='after')
    def validate_domain(self) -> StandardChartAxisDomain:
        if self.minimum is not None and self.maximum is not None and self.minimum >= self.maximum:
            raise ValueError('轴范围min必须小于max')
        if len(set(self.ticks)) != len(self.ticks) or any(a >= b for a,b in zip(self.ticks,self.ticks[1:])):
            raise ValueError('数值刻度须严格递增且唯一')
        if any(self.minimum is not None and value < self.minimum or self.maximum is not None and value > self.maximum for value in self.ticks):
            raise ValueError('刻度必须在声明范围内')
        if self.minimum is None and self.maximum is None and not self.ticks and self.tick_format == 'auto' and self.decimals is None:
            raise ValueError('轴参数至少指定范围、刻度或格式')
        return self


class StandardChartAxisBreak(StrictModel):
    lower: StandardChartAxisDomain = Field(description='低值段完整显示范围，纵向在下、barh在左；必须同时给min/max；只使用ticks/tickFormat/decimals，不设置段内outOfRange。')
    upper: StandardChartAxisDomain = Field(description='高值段完整显示范围，纵向在上、barh在右；min须严格大于低值段max；均使用最终显示单位。')
    omitted_values: Literal['reject', 'annotate'] = Field(default='reject', alias='omittedValues',
        description='默认不允许真实数据/绘图边界落入省略开区间；annotate显式允许并注明数量。')
    out_of_range: Literal['reject', 'annotate'] = Field(default='reject', alias='outOfRange',
        description='默认不允许数据越过整体上下界；annotate仅裁切显示并注明。')
    gap: float = Field(default=.08, ge=.03, le=.3, strict=True, allow_inf_nan=False,
        description='两个子图之间的Matplotlib间距比例：纵向hspace、barh横向wspace。')
    lower_fraction: float = Field(default=.5, alias='lowerFraction', ge=.25, le=.75, strict=True, allow_inf_nan=False,
        description='低值段的尺寸份额：纵向为下段高度、barh为左段宽度。')
    mark_size: float = Field(default=.012, alias='markSize', ge=.006, le=.025, strict=True, allow_inf_nan=False,
        description='断轴斜线在Axes相对坐标中的半长。')

    @model_validator(mode='after')
    def validate_intervals(self) -> StandardChartAxisBreak:
        if any(domain.minimum is None or domain.maximum is None for domain in (self.lower,self.upper)):
            raise ValueError('断轴上下两段必须同时声明min/max')
        assert self.lower.maximum is not None and self.upper.minimum is not None
        if self.lower.maximum >= self.upper.minimum:
            raise ValueError('断轴两段须严格分离且有正的省略区间')
        if any(domain.out_of_range != 'reject' for domain in (self.lower,self.upper)):
            raise ValueError('断轴的范围策略使用顶层omittedValues/outOfRange，不在单段设置')
        return self


class StandardChartPanelDomain(StrictModel):
    series: str = Field(min_length=1, max_length=200)
    domain: StandardChartAxisDomain


class StandardChartDomains(StrictModel):
    left: StandardChartAxisDomain | None = Field(default=None, description='单轴/左轴值域；横向图作用于数值X轴；panels作为各面板默认值域。均使用换算后的显示单位。')
    right: StandardChartAxisDomain | None = Field(default=None, description='仅dual右侧值轴，使用右轴显示单位。')
    x: StandardChartAxisDomain | None = Field(default=None, description='仅scatter/bubble的数值X轴；类别轴不可设数值范围。')
    zoom: StandardChartAxisDomain | None = Field(default=None, description='仅zoom局部子图的值轴；不改变主图。')
    panels: tuple[StandardChartPanelDomain, ...] = Field(default=(), max_length=8,
        description='仅panels按冻结系列名覆盖独立值域。')

    @model_validator(mode='after')
    def validate_targets(self) -> StandardChartDomains:
        if not any((self.left,self.right,self.x,self.zoom,self.panels)):
            raise ValueError('至少声明一个数值轴参数')
        if len({item.series for item in self.panels}) != len(self.panels):
            raise ValueError('同面板不能重复设置值域')
        return self


class StandardChartAxes(StrictModel):
    mode: Literal['single', 'dual', 'panels', 'zoom'] = 'single'
    scale: Literal['linear', 'log', 'symlog'] = 'linear'
    linear_threshold: float = Field(default=1, alias='linearThreshold', gt=0, allow_inf_nan=False,
                                    description='symlog在显示单位下零点附近的线性区间阈值。')
    zero_baseline: bool = Field(default=False, alias='zeroBaseline')
    right_fields: tuple[str, ...] = Field(default=(), alias='rightFields', max_length=8)
    allow_nulls: bool = Field(default=False, alias='allowNulls', description='折线/普通柱图保留null为空位，不补零；堆叠不支持。')
    left_display_unit: str | None = Field(default=None, alias='leftDisplayUnit', max_length=30)
    right_display_unit: str | None = Field(default=None, alias='rightDisplayUnit', max_length=30)
    panel_limit: int | None = Field(default=None, alias='panelLimit', ge=1, le=60,
                                   description='仅barh+panels，各系列独立按数值排序取前N项。')
    panel_descending: bool = Field(default=True, alias='panelDescending')
    zoom_start: str | None = Field(default=None, alias='zoomStart', max_length=200)
    zoom_end: str | None = Field(default=None, alias='zoomEnd', max_length=200)
    zoom_bounds: tuple[
        Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)],
        Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)],
        Annotated[float, Field(ge=.15, le=.8, allow_inf_nan=False)],
        Annotated[float, Field(ge=.15, le=.8, allow_inf_nan=False)],
    ] = Field(default=(.56, .5, .4, .4), alias='zoomBounds', description='局部图在主图内的相对位置与尺寸[left,bottom,width,height]，可调整以避开重点标注。')

    @model_validator(mode='after')
    def validate_zoom_bounds(self) -> StandardChartAxes:
        left, bottom, width, height = self.zoom_bounds
        if left + width > 1 or bottom + height > 1:
            raise ValueError('局部放大画布须位于主图内')
        return self


class StandardChartSource(StrictModel):
    source_index: int = Field(alias='sourceIndex', ge=0, le=7)
    label_field: str = Field(alias='labelField', min_length=1, max_length=200)
    value_field: str = Field(alias='valueField', min_length=1, max_length=200)
    series_name: str = Field(alias='seriesName', min_length=1, max_length=200)
    category_field: str | None = Field(default=None, alias='categoryField', max_length=200)
    category_value: str | None = Field(default=None, alias='categoryValue', max_length=200)
    label_mode: SourceLabelMode = Field(default='exact', alias='labelMode',
        description='exact精确标签；month保留年份归一为YYYY-MM；跨年同月比较显式用month_of_year，并声明periodYear，映射为01至12。')
    period_year: int | None = Field(default=None, alias='periodYear', ge=1, le=9999,
        description='month_of_year的唯一来源年份；不允许把多个年份静默合并为同一月份。')
    excluded_labels: tuple[str, ...] = Field(default=(), alias='excludedLabels', max_length=60)

    @model_validator(mode='after')
    def validate_period_year(self) -> StandardChartSource:
        if (self.label_mode == 'month_of_year') != (self.period_year is not None):
            raise ValueError('month_of_year必须且只能声明periodYear')
        return self


class StandardChartScalarRef(StrictModel):
    """标量只能选择本图原始有序冻结来源，不接受模型常数。"""
    source_index: int = Field(alias='sourceIndex', ge=0, le=99, strict=True)
    field: str = Field(min_length=1, max_length=200)
    label_field: str | None = Field(default=None, alias='labelField', min_length=1, max_length=200)
    label: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode='after')
    def complete_selector(self) -> StandardChartScalarRef:
        if (self.label_field is None) != (self.label is None):
            raise ValueError('标量labelField与label必须同时出现')
        return self


class StandardChartDenominator(StrictModel):
    mode: Literal['bound_sum', 'reference'] = 'bound_sum'
    ref: StandardChartScalarRef | None = None

    @model_validator(mode='after')
    def reference_only(self) -> StandardChartDenominator:
        if (self.mode == 'reference') != (self.ref is not None):
            raise ValueError('reference必须且只能声明冻结ref')
        return self


class StandardChartComposition(StrictModel):
    denominator: StandardChartDenominator = Field(default_factory=StandardChartDenominator)


class StandardChartRadarScale(StrictModel):
    field: str = Field(min_length=1, max_length=200)
    minimum: StandardChartScalarRef = Field(alias='min')
    maximum: StandardChartScalarRef = Field(alias='max')


class StandardChartRadar(StrictModel):
    scales: tuple[StandardChartRadarScale, ...] = Field(default=(), max_length=8)


class StandardChartFunnel(StrictModel):
    ratio_base: Literal['none', 'first', 'previous'] = Field(default='none', alias='ratioBase')


class StandardChartSankeyNodes(StrictModel):
    source_index: int = Field(alias='sourceIndex', ge=0, le=99, strict=True)
    id_field: str = Field(alias='idField', min_length=1, max_length=200)
    label_field: str | None = Field(default=None, alias='labelField', min_length=1, max_length=200)
    stage_field: str | None = Field(default=None, alias='stageField', min_length=1, max_length=200)


class StandardChartSankey(StrictModel):
    nodes: StandardChartSankeyNodes | None = None


class StandardChartView(StrictModel):
    """Explicit transformations of identity-checked rows, never model supplied data."""
    kind: Literal['group', 'pivot']
    label_field: str = Field(alias='labelField', min_length=1, max_length=200)
    value_fields: tuple[str, ...] = Field(alias='valueFields', min_length=1, max_length=8)
    series_field: str | None = Field(default=None, alias='seriesField', max_length=200)
    series_values: tuple[str, ...] = Field(default=(), alias='seriesValues', max_length=8)
    group_by: tuple[str, ...] = Field(default=(), alias='groupBy', max_length=2,
                                     description='group的附加维度，与labelField组成最多三维分组；保留各维度原列，不拼接标签。')
    aggregation: Literal['sum', 'mean', 'weighted_mean'] = 'sum'
    weight_field: str | None = Field(default=None, alias='weightField', max_length=200)

    @model_validator(mode='after')
    def validate_aggregation(self) -> StandardChartView:
        if (self.aggregation == 'weighted_mean') != bool(self.weight_field):
            raise ValueError('加权平均必须且只能指定冻结权重字段')
        if self.kind == 'pivot' and (self.group_by or self.aggregation != 'sum' or self.weight_field):
            raise ValueError('pivot仅透视唯一单元，不声明分组聚合')
        if len(set((self.label_field, *self.group_by))) != 1 + len(self.group_by):
            raise ValueError('分组维度不能重复')
        return self


class StandardChartDerivation(StrictModel):
    kind: Literal['ratio_percent', 'difference', 'mom_percent', 'yoy_percent',
                  'cumulative_sum', 'rolling_sum', 'rolling_mean']
    name: str = Field(min_length=1, max_length=200)
    numerator: str = Field(min_length=1, max_length=200)
    denominator: str | None = Field(default=None, max_length=200)
    label_field: str | None = Field(default=None, alias='labelField', max_length=200)
    group_by: tuple[str, ...] = Field(default=(), alias='groupBy', max_length=3)
    window: int | None = Field(default=None, ge=1, le=60)
    min_periods: int | None = Field(default=None, alias='minPeriods', ge=1, le=60)
    reset: Literal['none', 'year'] = 'none'

    @model_validator(mode='after')
    def validate_window(self) -> StandardChartDerivation:
        rolling = self.kind in {'rolling_sum', 'rolling_mean'}
        if rolling != (self.window is not None):
            raise ValueError('滚动运算必须且只能指定window')
        if self.min_periods is not None and (not rolling or self.min_periods > (self.window or 0)):
            raise ValueError('minPeriods仅适用于滚动运算且不能大于window')
        if self.reset != 'none' and self.kind != 'cumulative_sum':
            raise ValueError('按年重置仅适用于累计')
        if self.kind in {'ratio_percent', 'difference'} and (self.group_by or self.label_field):
            raise ValueError('同行二元运算不能指定时间或分组维度')
        if self.kind not in {'ratio_percent', 'difference'} and (not self.label_field or self.denominator):
            raise ValueError('时间运算须指定labelField且不能指定denominator')
        if len(set(self.group_by)) != len(self.group_by) or self.label_field in self.group_by:
            raise ValueError('时间分组维度重复或包含期间列')
        return self


class StandardChartStep(StrictModel):
    view: StandardChartView | None = None
    derivation: StandardChartDerivation | None = None

    @model_validator(mode='after')
    def validate_step(self) -> StandardChartStep:
        if (self.view is None) == (self.derivation is None):
            raise ValueError('每步必须且只能声明view或derivation')
        return self


class StandardChartWaterfall(StrictModel):
    value_field: str = Field(alias='valueField', min_length=1, max_length=200)
    absolute_labels: tuple[str, ...] = Field(alias='absoluteLabels', min_length=1, max_length=60,
        description='绑定绝对值起点/小计/终点的冻结标签；必须含首项，后续绝对值须与前项累计对账。其他项视为有符号增减。')
    increase_color: str = Field(default='#36856b', alias='increaseColor', pattern=r'^#[0-9a-fA-F]{6}$')
    decrease_color: str = Field(default='#b55d68', alias='decreaseColor', pattern=r'^#[0-9a-fA-F]{6}$')
    absolute_color: str = Field(default='#3066a3', alias='absoluteColor', pattern=r'^#[0-9a-fA-F]{6}$')
    connectors: bool = True


class StandardChartBoxOutliers(StrictModel):
    source_index: Literal[1] = Field(alias='sourceIndex', description='本图第二个绑定chart-input；第一个必须为分组分位数汇总表。')
    group_field: str = Field(alias='groupField', min_length=1, max_length=200)
    value_field: str = Field(alias='valueField', min_length=1, max_length=200)


class StandardChartBoxSummary(StrictModel):
    group_field: str = Field(alias='groupField', min_length=1, max_length=200)
    q1_field: str = Field(alias='q1Field', min_length=1, max_length=200)
    median_field: str = Field(alias='medianField', min_length=1, max_length=200)
    q3_field: str = Field(alias='q3Field', min_length=1, max_length=200)
    lower_whisker_field: str = Field(alias='lowerWhiskerField', min_length=1, max_length=200)
    upper_whisker_field: str = Field(alias='upperWhiskerField', min_length=1, max_length=200)
    count_field: str | None = Field(default=None, alias='countField', min_length=1, max_length=200,
        description='可选的冻结原始样本量字段；不提供则明确n未提供，不能使用汇总行数代替。')
    outlier_source: StandardChartBoxOutliers | None = Field(default=None, alias='outlierSource',
        description='可选的独立长表异常点来源，每行一个登记异常点，允许同值重复观测；不提供须注明异常点未提供。')
    group_labels: tuple[str, ...] = Field(default=(), alias='groupLabels', max_length=24)
    orientation: Literal['vertical', 'horizontal'] = 'vertical'
    show_fliers: bool = Field(default=True, alias='showFliers')

    @model_validator(mode='after')
    def validate_summary_fields(self) -> StandardChartBoxSummary:
        fields=[self.group_field,self.q1_field,self.median_field,self.q3_field,self.lower_whisker_field,self.upper_whisker_field]
        if self.count_field is not None:
            fields.append(self.count_field)
        if len(fields)!=len(set(fields)):
            raise ValueError('分组、五个统计值及样本量须引用不同字段')
        return self


class StandardChartDistribution(StrictModel):
    value_field: str = Field(alias='valueField', min_length=1, max_length=200)
    group_field: str = Field(alias='groupField', min_length=1, max_length=200)
    group_labels: tuple[str, ...] = Field(default=(), alias='groupLabels', max_length=24,
        description='当前全部分组的显式顺序，保留组内所有绑定样本。')
    orientation: Literal['vertical', 'horizontal'] = 'vertical'
    whisker_iqr: float = Field(default=1.5, alias='whiskerIqr', gt=0, le=5, allow_inf_nan=False)
    show_fliers: bool = Field(default=True, alias='showFliers')


class StandardChartEncoding(StrictModel):
    x_field: str = Field(alias='xField', min_length=1, max_length=200)
    y_field: str = Field(alias='yField', min_length=1, max_length=200)
    value_field: str | None = Field(default=None, alias='valueField', max_length=200)
    size_field: str | None = Field(default=None, alias='sizeField', max_length=200)
    color_field: str | None = Field(default=None, alias='colorField', max_length=200)
    group_field: str | None = Field(default=None, alias='groupField', max_length=200)
    x_labels: tuple[str, ...] = Field(default=(), alias='xLabels', max_length=60,
                                    description='热力图当前全部X标签的显式顺序，不能隐式丢弃类别。')
    y_labels: tuple[str, ...] = Field(default=(), alias='yLabels', max_length=60,
                                    description='热力图当前全部Y标签的显式顺序，不能隐式丢弃类别。')
    x_caption: str | None = Field(default=None, alias='xCaption', max_length=60)
    y_caption: str | None = Field(default=None, alias='yCaption', max_length=60)
    color_caption: str | None = Field(default=None, alias='colorCaption', max_length=60)
    size_caption: str | None = Field(default=None, alias='sizeCaption', max_length=60)
    x_display_unit: str | None = Field(default=None, alias='xDisplayUnit', max_length=30)
    y_display_unit: str | None = Field(default=None, alias='yDisplayUnit', max_length=30)
    color_display_unit: str | None = Field(default=None, alias='colorDisplayUnit', max_length=30)
    x_scale: Literal['linear', 'log', 'symlog'] = Field(default='linear', alias='xScale')
    x_linear_threshold: float = Field(default=1, alias='xLinearThreshold', gt=0, allow_inf_nan=False)
    color_map: Literal['viridis', 'cividis', 'Blues', 'RdBu_r', 'YlGnBu'] = Field(default='viridis', alias='colorMap')
    color_scale: Literal['linear', 'log', 'symlog'] = Field(default='linear', alias='colorScale')
    color_linear_threshold: float = Field(default=1, alias='colorLinearThreshold', gt=0, allow_inf_nan=False)
    color_center: float | None = Field(default=None, alias='colorCenter', allow_inf_nan=False,
                                       description='线性色标的显示单位中点，如正负值RdBu_r设0；必须位于实际最小/最大值之间。')
    max_area: float = Field(default=600, alias='maxArea', ge=100, le=1600, allow_inf_nan=False,
                            description='气泡最大面积，单位points²；面积与冻结sizeField成比例，零值面积为0。')
    show_values: bool = Field(default=False, alias='showValues', description='热力图显示已有单元值，最多60项；缺失单元保持空白。')


class StandardChartBand(StrictModel):
    series: str = Field(min_length=1, max_length=200)
    lower_field: str = Field(alias='lowerField', min_length=1, max_length=200)
    upper_field: str = Field(alias='upperField', min_length=1, max_length=200)
    label: str | None = Field(default=None, max_length=60)
    alpha: float = Field(default=.18, ge=.05, le=.5, allow_inf_nan=False)
    color: str | None = Field(default=None, pattern=r'^#[0-9a-fA-F]{6}$')


class StandardChartSeriesStyle(StrictModel):
    series: str = Field(min_length=1, max_length=200)
    label: str | None = Field(default=None, max_length=200)
    geometry: Literal['auto', 'line', 'bar'] = 'auto'
    color: str | None = Field(default=None, pattern=r'^#[0-9a-fA-F]{6}$')
    line_style: Literal['-', '--', '-.', ':'] = Field(default='-', alias='lineStyle')
    line_width: float = Field(default=2, alias='lineWidth', ge=.5, le=6, allow_inf_nan=False)
    marker: Literal['o', 's', '^', 'D', 'x', '.', 'none'] = 'o'
    marker_size: float = Field(default=5, alias='markerSize', ge=1, le=12, allow_inf_nan=False)
    alpha: float = Field(default=1, ge=.2, le=1, allow_inf_nan=False)
    hatch: Literal['', '/', '//', '\\', 'x', '.', '+', '-'] = ''


class StandardChartPointStyle(StrictModel):
    series: str = Field(min_length=1, max_length=200)
    label: str = Field(min_length=1, max_length=200)
    color: str = Field(pattern=r'^#[0-9a-fA-F]{6}$')
    marker_size: int = Field(default=8, alias='markerSize', ge=3, le=16)


class StandardChartOrder(StrictModel):
    mode: Literal['source', 'reverse', 'label', 'value', 'max_abs', 'explicit'] = 'source'
    fields: tuple[str, ...] = Field(default=(), max_length=8)
    field: str | None = Field(default=None, max_length=200)
    descending: bool = False
    labels: tuple[str, ...] = Field(default=(), max_length=60)
    limit: int | None = Field(default=None, ge=1, le=60)
    exclude_missing: bool = Field(default=False, alias='excludeMissing')

    @model_validator(mode='after')
    def validate_order(self) -> StandardChartOrder:
        if (self.mode == 'max_abs') != bool(self.fields):
            raise ValueError('最大绝对值排序必须且只能指定冻结字段集合')
        if (self.mode == 'value') != (self.field is not None):
            raise ValueError('数值排序必须且只能指定一个冻结字段')
        if self.exclude_missing and self.mode != 'value':
            raise ValueError('排除空值仅适用于明确的数值排序')
        if (self.mode == 'explicit') != bool(self.labels):
            raise ValueError('显式排序必须且只能提供标签顺序')
        if self.descending and self.mode not in {'value', 'label', 'max_abs'}:
            raise ValueError('降序仅适用于数值或标签排序')
        return self


class StandardChartLabelFormat(StrictModel):
    field: str | None = Field(default=None, max_length=200)
    numerator: str | None = Field(default=None, max_length=200)
    denominator: str | None = Field(default=None, max_length=200)
    caption: str | None = Field(default=None, max_length=40)
    display_unit: str | None = Field(default=None, alias='displayUnit', max_length=30)
    decimals: int = Field(default=2, ge=0, le=6)
    show_sign: bool = Field(default=False, alias='showSign')
    series: tuple[str, ...] = Field(default=(), max_length=8, description='辅助标注限定系列；空表示全部系列')

    @model_validator(mode='after')
    def validate_value_binding(self) -> StandardChartLabelFormat:
        if self.field is not None:
            if self.numerator is not None or self.denominator is not None:
                raise ValueError('标注只能选择冻结字段或显式分子/分母之一')
        elif not self.numerator or not self.denominator:
            raise ValueError('比率标注必须指定冻结分子和分母')
        return self


class StandardChartSummary(StandardChartLabelFormat):
    label: str | None = Field(default=None, max_length=200, description='多行表中唯一冻结标签；单行表可省略')
    aggregation: SummaryAggregation = Field(default='row',
        description='row绑定一条冻结输入行；sum显式汇总本绑定输入全部行的已登记金额、人次或床日，仅代表绑定输入范围，不按caption猜测合计；复合比率、未知量纲、缺失或布尔值不求和。')
    color: str = Field(default='#475569', pattern=r'^#[0-9a-fA-F]{6}$')

    @model_validator(mode='after')
    def validate_summary_aggregation(self) -> StandardChartSummary:
        if self.aggregation == 'sum' and (self.label is not None or self.field is None):
            raise ValueError('sum摘要须显式绑定可加字段，不能混用单行标签或比率')
        return self


class StandardChartPresentation(StrictModel):
    subtitle: str | None = Field(default=None, max_length=300)
    source_note: str | None = Field(default=None, alias='sourceNote', max_length=500)
    label_mode: Literal['source', 'month', 'month_of_year'] = Field(default='source', alias='labelMode')
    order: StandardChartOrder = Field(default_factory=StandardChartOrder)
    label_formats: tuple[StandardChartLabelFormat, ...] = Field(default=(), alias='labelFormats', max_length=3)
    summaries: tuple[StandardChartSummary, ...] = Field(default=(), max_length=4)


class StandardChartStyle(StrictModel):
    palette: Literal['report', 'tab10', 'Set2', 'Dark2', 'Paired', 'viridis', 'cividis'] = 'report'
    theme: Literal['report', 'classic'] = 'report'
    series: tuple[StandardChartSeriesStyle, ...] = Field(default=(), max_length=8)
    points: tuple[StandardChartPointStyle, ...] = Field(default=(), max_length=60)
    background: str = Field(default='#ffffff', pattern=r'^#[0-9a-fA-F]{6}$')
    grid: Literal['none', 'x', 'y', 'both'] = 'y'
    grid_alpha: float = Field(default=.2, alias='gridAlpha', ge=0, le=.8, allow_inf_nan=False)
    title_font_size: int = Field(default=14, alias='titleFontSize', ge=10, le=24)
    axis_font_size: int = Field(default=10, alias='axisFontSize', ge=8, le=18)
    label_rotation: int = Field(default=45, alias='labelRotation', ge=-90, le=90)
    legend_columns: int = Field(default=1, alias='legendColumns', ge=1, le=8)
    legend_font_size: int = Field(default=9, alias='legendFontSize', ge=8, le=16)
    legend_location: Literal['auto', 'best', 'upper left', 'upper right', 'lower left', 'lower right', 'upper center', 'lower center'] = Field(default='auto', alias='legendLocation')
    decimals: int = Field(default=2, ge=0, le=6)
    annotation_font_size: int = Field(default=8, alias='annotationFontSize', ge=8, le=16)
    annotation_offset_x: int = Field(default=8, alias='annotationOffsetX', ge=-120, le=120)
    annotation_offset_y: int = Field(default=8, alias='annotationOffsetY', ge=-120, le=120)
    value_margin: float = Field(default=.1, alias='valueMargin', ge=0, le=.5, allow_inf_nan=False)
    bar_group_width: float = Field(default=.64, alias='barGroupWidth', ge=.3, le=.9, allow_inf_nan=False)
    annotation_leader: bool = Field(default=False, alias='annotationLeader')
    annotation_color: Literal['series', 'neutral'] = Field(default='series', alias='annotationColor')

    @model_validator(mode='after')
    def unique_series(self) -> StandardChartStyle:
        if len({item.series for item in self.series}) != len(self.series):
            raise ValueError('系列样式名称不能重复')
        if len({(item.series, item.label) for item in self.points}) != len(self.points):
            raise ValueError('同一系列标签的样式不能重复')
        return self


class StandardChartCanvas(StrictModel):
    size_mode: Literal['auto', 'fixed'] = Field(default='auto', alias='sizeMode')
    width: float = Field(default=12, ge=4, le=20, allow_inf_nan=False, description='英寸')
    height: float = Field(default=7, ge=3, le=24, allow_inf_nan=False, description='英寸')
    dpi: int = Field(default=150, ge=72, le=240)
    layout: Literal['tight', 'constrained', 'manual'] = 'tight'
    crop: Literal['canvas', 'tight'] = 'canvas'
    padding: float = Field(default=.25, ge=0, le=1, allow_inf_nan=False)
    left: float = Field(default=.12, ge=0, le=.45, allow_inf_nan=False)
    right: float = Field(default=.94, ge=.55, le=1, allow_inf_nan=False)
    bottom: float = Field(default=.16, ge=0, le=.45, allow_inf_nan=False)
    top: float = Field(default=.90, ge=.55, le=1, allow_inf_nan=False)
    label_wrap: int = Field(default=14, alias='labelWrap', ge=6, le=40)
    tick_font_size: int = Field(default=9, alias='tickFontSize', ge=8, le=16)
    max_category_ticks: int = Field(default=18, alias='maxCategoryTicks', ge=4, le=60,
                                    description='纵向图横轴标签过密时显示的最大标签数；所有数据点仍完整绘制')
    legend_position: Literal['auto', 'inside', 'outside'] = Field(default='auto', alias='legendPosition')

    @model_validator(mode='after')
    def validate_pixel_budget(self) -> StandardChartCanvas:
        if self.width * self.height * self.dpi ** 2 > 24_000_000:
            raise ValueError('标准画布不能超过2400万像素')
        return self


class StandardChartPagination(StrictModel):
    page_size: int = Field(alias='pageSize', ge=1, le=60, strict=True,
        description='每页冻结类别数；宿主展开为独立登记图，覆盖全部绑定类别，不截掉末页。')
    max_pages: int = Field(default=20, alias='maxPages', ge=1, le=20, strict=True,
        description='允许生成的最多页数；超限整图回退，不只保留前几页。')


class ChartDraft(StrictModel):
    chart_id: str = Field(alias="chartId", min_length=1, max_length=128)
    source_path: str = Field(alias="sourcePath", min_length=1, max_length=1024)
    title: str = Field(
        min_length=1,
        max_length=200,
        description="图表用户可见标题，必须使用简体中文表达业务含义。",
    )
    alt_text: str = Field(
        alias="altText",
        min_length=1,
        max_length=200,
        description="图表用户可见图注，必须使用简体中文说明图表内容。",
    )
    citation_ids: tuple[str, ...] = Field(alias="citationIds", min_length=1, max_length=100)
    metric_codes: tuple[str, ...] = Field(alias="metricCodes", min_length=1, max_length=100)
    current_period: str = Field(alias="currentPeriod", min_length=1, max_length=200)
    comparison_period: str | None = Field(default=None, alias="comparisonPeriod", max_length=200)
    comparison_type: Literal["none", "yoy", "mom", "period"] = Field(
        default="none", alias="comparisonType"
    )
    source_dataset_id: str = Field(alias="sourceDatasetId", min_length=1, max_length=256)
    aggregation_grain: str = Field(alias="aggregationGrain", min_length=1, max_length=128)
    comparability: Literal["strict", "reference_only"] = "strict"
    visual_form: str = Field(alias="visualForm", min_length=1, max_length=200,
        description='业务图形意图与展示说明；不用于解析机器类型。新计划必须另填standardForm。')
    standard_form: StandardChartForm | None = Field(default=None, alias='standardForm',
        description='标准图机器类型，必须显式选择枚举；自然语言说明放visualForm。无法由标准参数表达时选custom交由Coding。null只兼容旧计划，不得从说明猜测类型。')
    standard_value_fields: tuple[str, ...] = Field(
        default=(), alias="standardValueFields", max_length=8,
        description="标准静态图明确选择的数值列，必须来自绑定的chart-input；可排除同表辅助排名/占比列。空数组按全部数值列预检。",
    )
    standard_annotations: tuple[StandardChartAnnotation, ...] = Field(
        default=(), alias='standardAnnotations', max_length=10,
        description='标准图标注：values数值、peak峰值、trough谷值、point重点、reference以冻结点值为参考线、range重点区间。series必须是已选数值列或长表分类；label/endLabel逐字引用标签。不接受模型编写数值。',
    )
    standard_axes: StandardChartAxes = Field(
        default_factory=StandardChartAxes, alias='standardAxes',
        description='显式轴策略：dual用rightFields指定右轴系列；panels逐系列共享横轴分面；log只允许严格正数折线；zoom用冻结标签zoomStart/zoomEnd选择局部放大，主图保持完整。',
    )
    standard_domains: StandardChartDomains | None = Field(default=None, alias='standardDomains',
        description='数值轴显示范围/刻度/格式，数值按显示单位填写；left/right/x/zoom/panels显式定位，默认不得裁切数据，缩小显示须outOfRange=annotate且说明超界。')
    standard_break: StandardChartAxisBreak | None = Field(default=None, alias='standardBreak',
        description='线性单值轴双区间断轴，显式省略区间并画断轴标记；保留完整数据，默认不隐藏省略区间或外界数据。支持纵向柱线/堆叠/范围带和barh横向分组柱图；不与standardDomains或多轴组合。')
    standard_pagination: StandardChartPagination | None = Field(default=None, alias='standardPagination',
        description='宽表单轴bar/barh按完整冻结类别顺序自动拆页；宿主生成每页独立身份、图片与报告引用，统一数值范围/系列颜色。不可在单图模板中忽略该参数；超限或不支持组合整图回退。')
    standard_canvas: StandardChartCanvas = Field(
        default_factory=StandardChartCanvas, alias='standardCanvas',
        description='统一画布：width/height单位英寸，dpi、自动/固定尺寸、布局、裁切、留白、换行、字号及图例位置。固定尺寸且crop=canvas时导出像素由尺寸乘DPI确定。',
    )
    standard_style: StandardChartStyle = Field(
        default_factory=StandardChartStyle, alias='standardStyle',
        description='可自由组合的标准表现参数：调色板、按冻结系列名称设置颜色/线型/线宽/点型/透明度/柱纹理、网格、字号、标签旋转、图例列数与位置、数值精度、标注偏移和值轴留白；不改变冻结数据。可与画布、双轴、分面、局部放大和标注组合。超出标准能力使用Coding路线。',
    )
    standard_presentation: StandardChartPresentation = Field(
        default_factory=StandardChartPresentation, alias='standardPresentation',
        description='报告排版：subtitle副标题/sourceNote来源说明；labelMode=month简写月份；order明确排序、前N项及缺失值排除；labelFormats为冻结辅助字段指定单位/简称/精度，或按同单位冻结numerator/denominator计算百分比；summaries绑定冻结行的字段生成摘要徽章，不接受模型编造数值。',
    )
    standard_sources: tuple[StandardChartSource, ...] = Field(
        default=(), alias='standardSources', max_length=8,
        description='多来源显式选择：sourceIndex按chart-input顺序从0计数，labelField/valueField来自冻结列；对齐后数值列名为seriesName，standardValueFields须引用这些系列名。跨年同月用month_of_year和各自periodYear；同年日期格式归一用month。',
    )
    standard_source_labels: tuple[str, ...] = Field(default=(), alias='standardSourceLabels', max_length=60,
        description='各来源归一后共同输入标签的交集，不是原始日期并集；month为YYYY-MM，month_of_year为01至12。须包含计算历史；standardLabels只选择最终展示窗口。')
    standard_label_field: str | None = Field(default=None, alias='standardLabelField', max_length=200,
                                           description='显式标签列；忽略未选择的其他文本辅助列，视图转换后仍须存在。')
    standard_view: StandardChartView | None = Field(default=None, alias='standardView',
        description='group按labelField及可选groupBy分组，对valueFields做sum/mean/weighted_mean（须weightField）；只处理绑定输入行。pivot以seriesField的seriesValues将一个度量透视为系列，不合并重复单元或填零。')
    standard_derivations: tuple[StandardChartDerivation, ...] = Field(
        default=(), alias='standardDerivations', max_length=8,
        description='视图后计算新列：同单位ratio_percent/difference；按labelField及groupBy计算mom_percent/yoy_percent/cumulative_sum/rolling_sum/rolling_mean。滚动须window，minPeriods默认完整窗口；累计reset=year显式按年重置。name不得覆盖原列，缺失保留null。',
    )
    standard_steps: tuple[StandardChartStep, ...] = Field(default=(), alias='standardSteps', max_length=8,
        description='按顺序执行最多8步view/derivation，可多维分组→分组累计/同比/滚动→透视；不能与standardView/standardDerivations混用。')
    standard_encoding: StandardChartEncoding | None = Field(default=None, alias='standardEncoding',
        description='scatter/bubble显式绑定数值xField/yField，可用groupField或colorField、sizeField；heatmap用文本xField/yField及数值valueField。单位来自冻结元数据。')
    standard_composition: StandardChartComposition | None = Field(default=None, alias='standardComposition',
        description='pie/donut分母：bound_sum为展示筛选前完整绑定可加类别合计；reference引用原始冻结标量。不得归一化补足扇区。')
    standard_radar: StandardChartRadar | None = Field(default=None, alias='standardRadar',
        description='雷达逐轴显式冻结min/max；异量纲或任何负径向值必须提供全部轴尺度，不从观测值推断评分。')
    standard_funnel: StandardChartFunnel | None = Field(default=None, alias='standardFunnel',
        description='漏斗默认原阶段顺序，ratioBase仅选none/first/previous，结果称阶段值比，不暗称转化率。')
    standard_sankey: StandardChartSankey | None = Field(default=None, alias='standardSankey',
        description='桑基source/target/weight用standardEncoding的xField/yField/valueField，nodes可选原始辅助来源及唯一id/显示名/非负整数stage。')
    standard_waterfall: StandardChartWaterfall | None = Field(default=None, alias='standardWaterfall',
        description='waterfall绑定有符号valueField及absoluteLabels起点/小计/终点；后续绝对值必须与累计对账，禁止补造或截取贡献项。')
    standard_distribution: StandardChartDistribution | None = Field(default=None, alias='standardDistribution',
        description='boxplot绑定长表groupField及原始样本valueField；最多480样本、24组，由Matplotlib计算线性四分位和IQR须，不从汇总均值伪造分布。')
    standard_box_summary: StandardChartBoxSummary | None = Field(default=None, alias='standardBoxSummary',
        description='boxplot直接读取第一个绑定输入的冻结分位数/中位数/须，每组一行；可声明原始样本量及第二个绑定输入的异常点长表。未知n或异常点必须说明，不推断IQR，不与原始样本模式混用。')
    standard_bands: tuple[StandardChartBand, ...] = Field(default=(), alias='standardBands', max_length=8,
        description='折线范围带：series绑定中心值，lowerField/upperField绑定同单位冻结上下界；只显示已有范围，不自动估算置信区间。')
    standard_label_fields: tuple[str, ...] = Field(
        default=(), alias='standardLabelFields', max_length=3,
        description='数值标注附带的冻结辅助列，如占比、差额、预算；必须为同表已登记单位的有限数值列，不改变坐标轴。',
    )
    standard_display_unit: str | None = Field(
        default=None, alias='standardDisplayUnit', max_length=30,
        description='单轴图显示单位，如元转亿元；必须由服务端登记单位换算，不能提交自由倍率。',
    )
    standard_labels: tuple[str, ...] = Field(
        default=(), alias='standardLabels', max_length=60,
        description='显式选择的冻结横轴标签，必须唯一且全部存在；按原输入顺序显示，不从标题推断窗口。',
    )
    standard_total_field: str | None = Field(
        default=None, alias='standardTotalField', max_length=200,
        description='stacked-total指定独立总额系列；须与每个标签的其他分项合计对账，不能重复计入堆叠。',
    )
    data_bindings: tuple[ChartDataBinding, ...] = Field(
        alias="dataBindings", min_length=1, max_length=100
    )

    @field_validator("title", "alt_text")
    @classmethod
    def validate_chinese_display_text(cls, value: str) -> str:
        # 这里只检查用户可见元数据至少包含汉字；简繁体词汇、业务术语和图片内
        # 的坐标轴/图例由 Agent 指令与绘图主题负责，不能用正则或 OCR 可靠判定。
        if not _CJK_TEXT_RE.search(value):
            raise ValueError("图表 title 和 altText 必须包含简体中文用户可见文字")
        return value

    @model_validator(mode="before")
    @classmethod
    def normalize_reference_comparison(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        comparison_type = value.get("comparisonType", value.get("comparison_type"))
        if value.get("comparability") != "reference_only" or comparison_type not in {
            "yoy",
            "mom",
        }:
            return value
        # reference_only 仍可展示两个期间，但不能把不可严格比较的数据标记为同比或
        # 环比。转换为普通期间对比只收窄结论强度，不改写数值、期间或证据绑定。
        normalized = dict(value)
        key = "comparisonType" if "comparisonType" in value else "comparison_type"
        normalized[key] = "period"
        return normalized

    @field_validator("source_path")
    @classmethod
    def validate_source_path(cls, value: str) -> str:
        path = safe_relative_posix_path(value, "图表源路径必须是安全工作区相对路径")
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            raise ValueError("图表源文件必须是 PNG 或 JPEG")
        return path.as_posix()

    @model_validator(mode="after")
    def validate_comparison(self) -> ChartDraft:
        if self.comparison_type != "none" and not self.comparison_period:
            raise ValueError("比较图表必须声明 comparisonPeriod")
        if self.comparability == "reference_only" and self.comparison_type in {"yoy", "mom"}:
            raise ValueError("reference_only 图表不得声明严格同比或环比")
        if len(self.citation_ids) != len(set(self.citation_ids)):
            raise ValueError("图表 citationIds 不能重复")
        binding_keys = [
            (
                item.analysis_id,
                item.fact_path,
                item.data_path,
                item.fields,
                item.role,
            )
            for item in self.data_bindings
        ]
        if len(binding_keys) != len(set(binding_keys)):
            raise ValueError("图表 dataBindings 不能重复")
        return self


class VisualizationPlanDraft(StrictModel):
    charts: tuple[ChartDraft, ...] = Field(max_length=MAX_SECTION_CHART_COUNT)
    warnings: tuple[str, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def validate_unique_charts(self) -> VisualizationPlanDraft:
        chart_ids = [item.chart_id for item in self.charts]
        paths = [item.source_path for item in self.charts]
        if len(chart_ids) != len(set(chart_ids)) or len(paths) != len(set(paths)):
            raise ValueError("图表 ID 和输出路径不能重复")
        return self


class SectionEvidenceFile(StrictModel):
    identity: FileIdentity
    content: str = Field(min_length=1, max_length=10 * 1024 * 1024)


class SectionEvidenceBundle(StrictModel):
    section_code: str = Field(alias="sectionCode", min_length=1, max_length=128)
    files: tuple[SectionEvidenceFile, ...] = Field(min_length=1, max_length=200)
    fact_summaries: tuple[str, ...] = Field(default=(), alias="factSummaries", max_length=200)


class AnalysisReworkDecision(StrictModel):
    kind: Literal["rework"] = "rework"
    section_code: str = Field(alias="sectionCode", min_length=1, max_length=128)
    analysis_ids: tuple[str, ...] = Field(alias="analysisIds", min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=4000)
    missing_evidence: tuple[str, ...] = Field(alias="missingEvidence", min_length=1, max_length=100)


class SectionBlockPlan(StrictModel):
    block_id: str = Field(alias="blockId", min_length=1, max_length=128)
    objective: str = Field(min_length=1, max_length=2000)
    claim_ids: tuple[str, ...] = Field(alias="claimIds", min_length=1, max_length=100)

    @field_validator("claim_ids")
    @classmethod
    def validate_unique_claim_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("block 规划的 claimIds 不能重复")
        return value


class RenderSectionPlan(StrictModel):
    kind: Literal["render"] = "render"
    section_code: str = Field(alias="sectionCode", min_length=1, max_length=128)
    blocks: tuple[SectionBlockPlan, ...] = Field(min_length=1, max_length=12)
    claims: tuple[SectionClaimSubmission, ...] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_references(self) -> RenderSectionPlan:
        block_ids = [item.block_id for item in self.blocks]
        claim_ids = [item.claim_id for item in self.claims]
        if len(block_ids) != len(set(block_ids)):
            raise ValueError("章节规划 blockId 不能重复")
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("章节规划 claimId 不能重复")
        referenced = {claim_id for block in self.blocks for claim_id in block.claim_ids}
        known = set(claim_ids)
        if referenced != known:
            raise ValueError("章节规划的每个 claim 必须存在且由至少一个 block 引用")
        return self


SectionPlanDecision = Annotated[
    RenderSectionPlan | AnalysisReworkDecision,
    Field(discriminator="kind"),
]


class SectionPlanOutput(RootModel[SectionPlanDecision]):
    model_config = ConfigDict(frozen=True)

    @model_validator(mode="before")
    @classmethod
    def normalize_single_decision_wrapper(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        if len(value) == 1:
            kind, payload = next(iter(value.items()))
            if kind in {"render", "rework"} and isinstance(payload, Mapping):
                declared_kind = payload.get("kind")
                if declared_kind in {None, kind}:
                    value = {**payload, "kind": kind}
        if value.get("kind") != "render":
            return value

        normalized = dict(value)
        for field in ("blocks", "claims"):
            items = value.get(field)
            if not isinstance(items, list | tuple):
                continue
            decoded_items: list[Any] = []
            changed = False
            for item in items:
                decoded = item
                if isinstance(item, str):
                    try:
                        candidate = json.loads(item)
                    except json.JSONDecodeError:
                        pass
                    else:
                        if isinstance(candidate, Mapping):
                            decoded = candidate
                            changed = True
                decoded_items.append(decoded)
            if changed:
                normalized[field] = (
                    tuple(decoded_items) if isinstance(items, tuple) else decoded_items
                )
        return normalized


class SectionBlockContent(StrictModel):
    markdown: str = Field(min_length=1, max_length=MAX_SECTION_BLOCK_MARKDOWN_CHARS)

    @field_validator("markdown", mode="before")
    @classmethod
    def normalize_protocol_residuals(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        markdown = normalize_model_block_markdown(value)
        if not markdown:
            raise ValueError("章节正文清洗后不能为空。")
        # 确定性清洗必须先于 Pydantic 长度和业务校验。否则大段内部 repair comment
        # 会让本可接受的正文先触发 max_length，并错误消耗模型业务纠错额度。
        markdown = _normalize_setext_headings(markdown)
        markdown = _normalize_subordinate_heading_levels(markdown)
        return _normalize_runon_heading_lines(markdown)

    @field_validator("markdown")
    @classmethod
    def validate_markdown(cls, markdown: str) -> str:
        try:
            # 单块生成阶段没有前序块上下文，因此这里只拒绝可独立判定的协议错误；
            # H4 的父级关系仍由整章提交校验跨 block 判定。
            validate_report_block_markdown(markdown)
        except ReportingError as error:
            raise ValueError(_block_validation_feedback(markdown, error)) from error
        return markdown


class SectionContentBlock(SectionBlockContent):
    block_id: str = Field(alias="blockId", min_length=1, max_length=128)


class SectionContent(StrictModel):
    blocks: tuple[SectionContentBlock, ...] = Field(min_length=1, max_length=12)


class SectionSemanticReview(StrictModel):
    interpretations: tuple[ClaimInterpretationV1, ...] = Field(default=(), max_length=500)


class RenderSectionDecision(StrictModel):
    kind: Literal["render"] = "render"
    section_code: str = Field(alias="sectionCode", min_length=1, max_length=128)
    blocks: tuple[ReportDraftBlock, ...] = Field(min_length=1, max_length=200)
    claims: tuple[SectionClaimSubmission, ...] = Field(min_length=1, max_length=500)


SectionDecision = Annotated[
    RenderSectionDecision | AnalysisReworkDecision,
    Field(discriminator="kind"),
]
SectionDecisionAdapter: TypeAdapter[SectionDecision] = TypeAdapter(SectionDecision)


class SectionDecisionOutput(RootModel[SectionDecision]):
    """Agno output_schema 只接受 BaseModel 类型，根 JSON 仍保持原判别联合形状。"""

    model_config = ConfigDict(frozen=True)

    @model_validator(mode="before")
    @classmethod
    def normalize_single_decision_wrapper(cls, value: Any) -> Any:
        """展开模型偶发生成的单键决策包装，随后仍由原判别联合完整校验。"""

        if not isinstance(value, Mapping) or len(value) != 1:
            return value
        kind, payload = next(iter(value.items()))
        if kind not in {"render", "rework"} or not isinstance(payload, Mapping):
            return value
        declared_kind = payload.get("kind")
        if declared_kind not in {None, kind}:
            return value
        return {**payload, "kind": kind}


__all__ = [
    "AnalysisReworkDecision",
    "ChartDraft",
    "RenderSectionDecision",
    "RenderSectionPlan",
    "SectionBlockContent",
    "SectionBlockPlan",
    "SectionContent",
    "SectionContentBlock",
    "SectionDecision",
    "SectionDecisionAdapter",
    "SectionDecisionOutput",
    "SectionEvidenceBundle",
    "SectionEvidenceFile",
    "SectionPlanOutput",
    "VisualizationPlanDraft",
]
