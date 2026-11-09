"""仅用安全合成输入比较两个已提交版本的规划指引。"""

# ruff: noqa: E402 -- 研究脚本复用仓库入口。

import argparse
import ast
import asyncio
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from dataclasses import asdict, fields
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

REPORT = Path(__file__).resolve().parent
ROOT = REPORT.parents[3]
sys.path.insert(0, str(ROOT))

from agno.run import RunContext
from loguru import logger
from matplotlib.figure import Figure

from scripts.replay_visualization_task import ReplayObservedOpenAIChat
from smart_reporting.reporting.agent import _report_model
from smart_reporting.reporting.model_policy import (
    ThinkingRequest,
    apply_reporting_thinking_profile,
    select_reporting_thinking,
)
from smart_reporting.reporting.structured_output import (
    ReportingStructuredOutputExecutor,
    StructuredOutputCallBudget,
)
from smart_reporting.reporting.workflow.benchmark_execution import build_benchmark_planner_agent
from smart_reporting.reporting.workflow.benchmark_variants import BenchmarkVariant
from smart_reporting.reporting.workflow.runtime.phase_models import VisualizationPlanDraft
from smart_reporting.reporting.workflow.runtime.standard_chart_contract import (
    standard_chart_capabilities,
)
from smart_reporting.runtime.settings import AgentSettings

COMMITS = {'before': 'b84437eee5cfed9ba808329a853b9b14e107d7aa',
           'after': '0c288333dea39e297e8b337cb154bf722bf8c871'}
ORDER = [('L1', 'before'), ('L1', 'after'), ('U1', 'after'), ('U1', 'before')]
LONG = '合成机构超长中文分类标签用于验证画布边缘完整显示'


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def save(path, value):
    path.write_bytes(encoded(value))


def identity(path):
    raw = path.read_bytes()
    return {'path': str(path.relative_to(REPORT)), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}


def instructions(commit):
    raw = subprocess.check_output(['git', 'show', f'{commit}:smart_reporting/reporting/instructions.py'], cwd=ROOT)
    tree = ast.parse(raw)
    return next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == 'REPORT_VISUALIZATION_SECTION_AGENT_INSTRUCTIONS'
                        for target in node.targets))


def cases():
    binding = {'analysisId': 'synthetic', 'factPath': 'facts.json', 'dataPath': 'rows',
               'fields': ['label', 'value'], 'role': '合成冻结数据'}
    answer = {}
    for case_id, rows, width, height, intent in [
        ('L1', [[LONG, -12]], 4, 3,
         '完整展示一类人次净变化的横向柱图。保留负数和完整中文类别，9pt分类字号，绘图区至少300×200px；不得截断、删行、缩字号或扩大图片。'),
        ('U1', [['普通门诊', 12], ['合成缺失类别', None], ['特需门诊', -3]], 6, 4,
         '逐类横向柱图展示门诊量，保留缺失空位并给出中文缺失说明。value的已确认业务显示名是门诊量；以普通门诊的冻结值画参考线，已确认简称为基准门诊量。所有读者可见文案使用这些中文含义，不能自填参考数值。'),
    ]:
        document = {'columns': ['label', 'value'], 'rows': rows, 'columnMeta': {'value': {'unit': '人次'}}}
        request = {
            'allowedDatasetIds': ['synthetic'],
            'requiredCharts': [{'chartId': 'synthetic', 'sourcePath': 'chart.png'}],
            'visualizationWorkspace': {'chartOutputRoot': '.'},
            'standardChartCapabilities': standard_chart_capabilities(),
            'businessRequest': intent + f'仅一图，固定{width}×{height}英寸、150dpi、canvas裁切、9pt分类字号。期间2025-01，分类粒度category，不比较其他期间。',
            'bindingContract': '逐字复用给定dataBindings、citationIds、metricCodes、数据集和期间；原始数值、类别、缺失均保持不变。',
            'visualizationFacts': [{'analysisId': 'synthetic', 'sourceDatasetId': 'synthetic',
                                    'citationIds': ['synthetic'], 'metricCodes': ['synthetic'],
                                    'currentPeriod': '2025-01', 'aggregationGrain': 'category',
                                    'dataBindings': [binding], 'document': document}],
        }
        answer[case_id] = {'request': request, 'document': document, 'binding': binding,
                           'pixels': [width * 150, height * 150], 'values': [row[1] for row in rows]}
    return answer


def replay_module():
    source = REPORT.parent / '2026-11-09-standard-visualization-counterfactuals/replay.py'
    spec = importlib.util.spec_from_file_location('paired_replay', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def judge(case_id, case, plan, folder, replay):
    result = {'visual_review': 'not_run', 'redraws': 0, 'render_attempts': 0}
    result['identity'] = len(plan.charts) == 1
    if not result['identity']:
        return result
    chart = plan.charts[0]
    result['identity'] = (chart.chart_id == 'synthetic' and chart.source_path == 'chart.png'
        and chart.source_dataset_id == 'synthetic' and chart.current_period == '2025-01'
        and chart.comparison_period is None and chart.comparison_type == 'none'
        and chart.aggregation_grain == 'category' and chart.metric_codes == ('synthetic',)
        and chart.citation_ids == ('synthetic',) and len(chart.data_bindings) == 1
        and chart.data_bindings[0].model_dump(mode='json', by_alias=True) == case['binding'])
    result['custom'] = chart.standard_form == 'custom'
    if not result['identity'] or result['custom']:
        return result
    # 仅执行已通过身份限制的生产标准模板，不执行模型源码。
    state = {'documents': [case['document']], 'plan': plan.model_dump(mode='json', by_alias=True)}
    save(folder / 'frozen.json', state)
    for file in replay.materialize(state).files:
        (folder / file.path).write_bytes(file.content)
    geometry = []
    original_save = Figure.savefig

    def measure(figure, *args, **kwargs):
        output = original_save(figure, *args, **kwargs)
        geometry[:] = [{'bbox_px': list(axis.bbox.bounds), 'xlim': list(axis.get_xlim()),
                        'ylim': list(axis.get_ylim()),
                        'tick_font_sizes': [tick.get_fontsize() for tick in axis.get_yticklabels()]}
                       for axis in figure.axes]
        return output

    try:
        with patch.object(Figure, 'savefig', measure):
            actual = replay.render(state, folder)
    except Exception as error:
        result['render_error'] = type(error).__name__
        return result
    result['actual'] = actual
    result['plot_geometry'] = geometry
    result['render_attempts'] = 1
    result['standard_delivered'] = actual.get('execution') == 'rendered'
    actual_values = replay.normalize(actual.get('bar_values', []))
    expected = [None if value is None else str(Decimal(str(value))) for value in case['values']]
    result['decimal_expected'] = expected
    result['numeric'] = (len(actual_values) == len(expected) and all(
        value is None if oracle is None else value is not None and Decimal(str(value)) == Decimal(oracle)
        for value, oracle in zip(actual_values, expected, strict=True)))
    measured = actual.get('geometry', {})
    texts = [item['text'] for item in measured.get('texts', [])]
    categories = actual.get('category_labels', [])
    result['full_categories'] = [text.replace('\n', '') for text in categories] == [row[0] for row in case['document']['rows']]
    result['geometry'] = (result['standard_delivered'] and result['full_categories']
        and measured.get('canvas_px') == case['pixels'] and not measured.get('missing_glyphs', [])
        and not any(text['outside_canvas'] for text in measured.get('texts', []) if text['text'] in categories)
        and bool(geometry) and all(size == 9 for size in geometry[0]['tick_font_sizes']))
    if case_id == 'L1':
        result['geometry'] = result['geometry'] and geometry[0]['bbox_px'][2] >= 300 and geometry[0]['bbox_px'][3] >= 200
    else:
        aliases = {item.series: item.label for item in chart.standard_style.series}
        result['business_mapping'] = (aliases.get('value') == '门诊量'
            and any(item.kind == 'reference' and item.series == 'value' and item.label == '普通门诊'
                    and item.caption == '基准门诊量' for item in chart.standard_annotations)
            and any('门诊量' in text and '缺失' in text for text in texts)
            and any('基准门诊量' in text for text in texts)
            and not any('value' in text or 'actual' in text for text in texts))
    result['geometry'] = bool(result['geometry'])
    return replay.normalize(result)


async def run(output):
    output.mkdir(parents=True, exist_ok=False)
    settings = AgentSettings.from_environment()
    if not settings.openai_api_key or not settings.openai_base_url:
        save(output / 'blocked.json', {'reason': 'missing_model_configuration', 'calls': 0})
        return
    replay = replay_module()
    frozen = cases()
    profiles, agents, metrics = {}, {}, {}
    for variant, commit in COMMITS.items():
        base = _report_model(settings, enable_thinking=settings.report_enable_thinking, retries=0, timeout_seconds=180)
        profile = select_reporting_thinking(ThinkingRequest(operation='visualization_plan',
            thinking_enabled=settings.report_enable_thinking,
            reasoning_effort=settings.report_planner_reasoning_effort,
            configured_budget_cap=settings.report_planner_thinking_budget))
        apply_reporting_thinking_profile(base, profile)
        profiles[variant] = asdict(profile)
        model = ReplayObservedOpenAIChat(**{field.name: getattr(base, field.name) for field in fields(base)})
        for name, value in base.__dict__.items():
            if name.startswith('_reporting_'):
                setattr(model, name, value)
        model.max_tokens = 8192
        metrics[variant] = model.replay_request_metrics()  # 初始化浅复制模型共享的sink。
        _, agent = build_benchmark_planner_agent(model=model, task_kind='visualization',
            variant=BenchmarkVariant.CANDIDATE, planner_request=frozen['L1']['request'], standard_visualization=False)
        agent.instructions = [*agent.instructions, *instructions(commit)]
        agents[variant] = agent
        save(output / f'{variant}-instructions.json', agent.instructions)
    assert profiles['before'] == profiles['after']
    save(output / 'cases.json', frozen)
    save(output / 'schema.json', VisualizationPlanDraft.model_json_schema(by_alias=True))
    save(output / 'environment.json', {'runtime_commit': replay.git('rev-parse', 'HEAD'),
        'instructions_commits': COMMITS, 'script': identity(Path(__file__)),
        'protocol': identity(REPORT / 'PROTOCOL.md'), 'model': settings.model_standard_id,
        'profile': profiles['before'], 'max_output_tokens': 8192, 'slot_wall_seconds': 180,
        'order': ORDER, 'runtime': replay.environment(), 'visual_review': 'not_run'})
    observations = []
    stopped = False
    original_invoke = ReplayObservedOpenAIChat.ainvoke
    for case_id, variant in ORDER:
        record = {'case': case_id, 'variant': variant, 'status': 'not_run' if stopped else 'started'}
        observations.append(record)
        folder = output / f'{case_id}-{variant}'
        folder.mkdir()
        if stopped:
            save(output / 'results.json', observations)
            continue
        agent = agents[variant]
        start_metrics = len(agent.model.replay_request_metrics())
        raw_calls = []

        async def capture(model, *args, **kwargs):
            messages = args[0] if args else kwargs.get('messages', [])
            call = {'messages': [message.model_dump(mode='json', exclude_none=True) for message in messages]}
            raw_calls.append(call)
            try:
                response = await original_invoke(model, *args, **kwargs)
                call['response'] = {name: getattr(response, name, None)
                                    for name in ('content', 'reasoning_content', 'tool_calls', 'finish_reason')}
                return response
            finally:
                save(folder / 'provider-messages.json', raw_calls)

        started = perf_counter()
        logger.info('paired_planner_started case={} variant={}', case_id, variant)
        try:
            with patch.object(ReplayObservedOpenAIChat, 'ainvoke', capture):
                structured = await ReportingStructuredOutputExecutor(agent, idle_timeout_seconds=180).execute(
                    json.dumps(frozen[case_id]['request'], ensure_ascii=False),
                    routing_context=RunContext(run_id=f'{case_id}-{variant}', session_state={}),
                    session_id=f'paired-{case_id}-{variant}', user_id='synthetic-eval',
                    call_budget=StructuredOutputCallBudget(max_model_calls=1))
            plan = VisualizationPlanDraft.model_validate(structured.content)
            save(folder / 'plan.json', plan.model_dump(mode='json', by_alias=True))
            record['status'] = 'planned'
            record['planner_duration_ms'] = round((perf_counter() - started) * 1000)
            record['judgement'] = judge(case_id, frozen[case_id], plan, folder, replay)
        except Exception as error:
            # 不持久化任意异常正文，避免供应商错误包含地址或凭据。
            record.update(status='failed', error_type=type(error).__name__,
                          error_code=getattr(error, 'code', type(error).__name__))
            stopped = True
        record['duration_ms'] = round((perf_counter() - started) * 1000)
        record['provider_requests'] = agent.model.replay_request_metrics()[start_metrics:]
        save(output / 'results.json', observations)
        logger.info('paired_planner_finished case={} variant={} status={}', case_id, variant, record['status'])
    save(output / 'manifest.json', [identity(path) for path in sorted(output.rglob('*')) if path.is_file()])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    os.environ.setdefault('MPLBACKEND', 'Agg')
    asyncio.run(run(args.output.resolve()))
