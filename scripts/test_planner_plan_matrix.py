"""完整AnalysisBundle的语义提示配对测试，不执行报告或SQL。"""
# ruff: noqa: E402
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import statistics
import sys
from copy import deepcopy
from pathlib import Path
from time import perf_counter
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agno.run import RunContext
from loguru import logger

from scripts.planner_matrix_support import _runtime, json_text, validate_plan
from smart_reporting.reporting.structured_output.execution import StructuredOutputCallBudget
from smart_reporting.runtime.settings import AgentSettings


def coverage_issues(plan, case):
    issues = []
    requirements = {r['requirementId']: r for r in plan.get('requirements', [])}
    for expected in case['required']:
        covered = False
        for analysis in plan.get('analyses', []):
            if not set(expected['roles']) <= set(analysis.get('periodRoles', [])):
                continue
            if expected.get('monthly') and analysis.get('seriesGranularity') != 'month':
                continue
            for ident in analysis.get('requirementIds', []):
                requirement = requirements.get(ident)
                if not requirement or not set(expected['dimensions']) <= set(requirement.get('dimensionColumns', [])):
                    continue
                comparisons = set(expected['roles']) - {'current'}
                if not comparisons <= set(requirement.get('comparisonRoles') or []):
                    continue
                refs = {f"{requirement['sourceId']}.{table['table']}.{column}"
                        for table in requirement['tables'] for column in table['measureColumns']}
                covered |= expected['ref'] in refs
        if not covered:
            issues.append(f"任务覆盖不足:{expected['ref']}:{','.join(expected['dimensions'])}:{','.join(expected['roles'])}")
    for requirement in requirements.values():
        if len(requirement['tables']) > 1:
            issues.append(f"应独立取数却生成多表需求:{requirement['requirementId']}")
    return issues


def build_cases(source):
    income = 'rj.rj.dwd_hdc_income_summary_view.indicator_value'
    cost = 'rj.rj.dwd_hdc_cost_table_view.indicator_value'
    workload = 'rj.rj.dm_hdc_gongzuoliang_view.mantime_outpatient'
    expenditure = 'rj.rj.dwd_expenditure_budget_view.actual_expenditure'
    def expectation(ref, dimensions=('area',), roles=('current', 'yoy'), monthly=False):
        return {'ref': ref, 'dimensions': list(dimensions), 'roles': list(roles), 'monthly': monthly}
    return [
        {'id': 'whole_hospital', 'goal': source['reportGoal'],
         'required': [expectation(ref) for ref in (income, cost, workload, expenditure)]},
        {'id': 'income_workload_link', 'goal': '分析2025年1—9月各院区收入汇总指标income_summary_total与门诊人次outpatient_visits的同比变化及月度趋势；分别取数后对比，不将相关性解释为因果。',
         'required': [item for ref in (income, workload) for item in
                      (expectation(ref), expectation(ref, ('area', 'data_date'), ('current',), monthly=True))]},
        {'id': 'budget_gap_keeps_income', 'goal': '分析2025年1—9月各院区收入汇总指标income_summary_total的同比规模变化；另分析实际收入/全年收入预算的执行率，全年预算挂载与可加性未核实时保留该缺口，仍完成独立收入分析。',
         'required': [expectation(income)]},
        {'id': 'unmapped_line_keeps_area', 'goal': '分析2025年1—9月收入汇总指标income_summary_total的院区、条线结构并同比。条线没有批准字段映射时保留缺口，不用预算类型或科室类型替代，院区分析继续。',
         'required': [expectation(income)]},
        {'id': 'unobserved_yoy', 'goal': '规划2025年1—9月收入汇总指标income_summary_total的逐月同比。2024年同期尚无观测覆盖记录，仍规划独立查询，不预先声称数据齐全或无数据。',
         'required': [expectation(income, ('data_date',), monthly=True)]},
        {'id': 'surplus_gap_keeps_components', 'goal': '分析2025年1—9月各院区收入汇总指标income_summary_total与total_cost的规模及同比变化，分别取数。另要求正式科室收支余排名；收入成本归属与分摊可比性没有证据时保留结余缺口，不影响收入成本各自分析。',
         'required': [expectation(ref) for ref in (income, cost)]},
    ]


def load_candidate_instructions(path):
    instructions = json.loads(path.read_text())
    if not isinstance(instructions, list) or not instructions or any(
        not isinstance(item, str) or not item.strip() for item in instructions
    ):
        raise ValueError('候选指令文件必须为非空字符串数组')
    return instructions


async def run(args):
    candidate_instructions = load_candidate_instructions(args.candidate_instructions)
    os.environ['AGENT_ENV_FILE'] = str(args.env_file)
    settings = AgentSettings.from_environment()
    source = json.loads(args.input.read_text())
    cases = build_cases(source)
    args.output.mkdir(parents=True, exist_ok=False)
    logger.add(args.output / 'matrix.log')
    def write(name, value):
        (args.output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str))
    improved = _runtime(settings)._analysis_agent
    baseline = _runtime(settings)._analysis_agent
    improved.instructions = [*improved.instructions, *candidate_instructions]
    agents = {'baseline': baseline, 'semantic': improved}
    for agent in agents.values():
        agent.model.retries = 0
    runtime = _runtime(settings)
    write('input.json', source)
    write('manifest.json', {'model': settings.model_standard_id, 'api': 'chat_completions',
        'repetitions': args.repetitions, 'cases': cases,
        'inputSha256': hashlib.sha256(json_text(source).encode()).hexdigest(),
        'scriptSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'instructions': {key: agent.instructions for key, agent in agents.items()},
        'limitations': '冻结真实DDL；完整规划输出；无SQL执行、无工作流纠错、无端到端报告'})
    semaphore = asyncio.Semaphore(3)
    results = []
    async def call(case, variant, repetition):
        payload = deepcopy(source)
        payload['reportGoal'] = case['goal']
        label = f"{case['id']}-{variant}-{repetition}"
        result = {'label': label, 'case': case['id'], 'variant': variant,
                  'requestSha256': hashlib.sha256(json_text(payload).encode()).hexdigest()}
        metrics = {}
        def record(output, count):
            metric = getattr(output, 'metrics', None)
            metrics.update(metric.to_dict() if metric else {})
            metrics['modelRequestCount'] = count
        async with semaphore:
            started = perf_counter()
            logger.info('plan_matrix_started label={}', label)
            try:
                output = await asyncio.wait_for(runtime._run_planner(agents[variant], payload,
                    RunContext(run_id=str(uuid4()), session_id=str(uuid4()),
                               user_id='plan-semantic-matrix', session_state={}),
                    call_budget=StructuredOutputCallBudget(max_model_calls=1),
                    model_metrics_recorder=record), timeout=300)
                plan = output.model_dump(mode='json', by_alias=True)
                result['output'] = plan
                result['contract'] = validate_plan(plan, payload)
                result['coverageIssues'] = coverage_issues(plan, case)
                result['passed'] = result['contract']['valid'] and not result['coverageIssues']
            except Exception as error:
                result['error'] = {'type': type(error).__name__, 'code': getattr(error, 'code', None)}
                result['passed'] = False
            result.update(metrics=metrics, seconds=round(perf_counter() - started, 3))
            write(label + '.json', result)
            results.append(result)
            write('progress.json', results)
            logger.info('plan_matrix_finished label={} passed={}', label, result['passed'])
    for repetition in range(1, args.repetitions + 1):
        variants = ('baseline', 'semantic') if repetition % 2 else ('semantic', 'baseline')
        await asyncio.gather(*(call(case, variant, repetition) for case in cases for variant in variants))
    summaries = []
    for case in cases:
        for variant in agents:
            group = [r for r in results if r['case'] == case['id'] and r['variant'] == variant]
            tokens = [r['metrics']['input_tokens'] for r in group if 'input_tokens' in r['metrics']]
            summaries.append({'case': case['id'], 'variant': variant,
                'passes': sum(r['passed'] for r in group), 'runs': len(group),
                'meanInputTokens': statistics.mean(tokens) if tokens else None})
    write('results.json', {'summaries': summaries, 'runs': results})
    logger.info('plan_matrix_complete calls={} passes={}', len(results), sum(r['passed'] for r in results))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--env-file', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--candidate-instructions', type=Path, required=True,
                        help='候选提示的JSON字符串数组，仅追加到实验组，不修改生产指令')
    parser.add_argument('--repetitions', type=int, choices=range(1, 4), default=3)
    asyncio.run(run(parser.parse_args()))
