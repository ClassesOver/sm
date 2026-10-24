"""数据口径只在影响结论时写一次：画像描述性告警不交给写作模型，模型自写待核实类提示交回改写。"""

import json
import re

import pytest

from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    writer_relevant_warning,
)
from smart_reporting.reporting.trace.review_readability import prose_hedge_warnings
from smart_reporting.reporting.workflow.runtime import sections


@pytest.mark.parametrize('warning,relevant', [
    ('[area] is highly overall correlated with [stlevel_analytic_unit] and 1 other fields', False),
    ('[indicator_value] has 1418 (2.1%) zeros', False),
    ('[income_type] is highly imbalanced (68.2%)', False),
    ('[company] has a constant value', False),
    ('[indicator_value] is highly skewed (γ1 = 25.3)', False),
    ('同一月份有多条科室或项目明细记录，未在明细层面做趋势与季节性检验；趋势判断须以按月及科室汇总后的数据为准。', False),
    # 字段缺失与归属缺失改变排名、占比的读法，仍交给写作模型。
    ('[rdlevel_analytic_unit] 19323 (78.6%) missing values', True),
    ('indicator_value 的分组字段 rdlevel_analytic_unit 有 19323 行归属缺失；确认归属前，该维度的排名、占比和贡献仅作参考。', True),
    ('收入明细含负值记录260笔。', True),
])
def test_only_warnings_that_can_change_a_conclusion_reach_the_writer(warning, relevant):
    assert writer_relevant_warning(warning) is relevant


def test_evidence_projection_drops_descriptive_alerts_but_keeps_material_ones():
    bundle = {
        'analysisId': 'analysis_001',
        'warnings': ['[company] has a constant value', '收入明细含负值记录260笔。'],
        'metrics': [{'factId': 'fact-1', 'warnings': ['[area] is highly overall correlated with [unit]',
                                                      '[unit] 12 (1.0%) missing values']}],
    }
    projected = sections._project_json_evidence(
        json.dumps(bundle, ensure_ascii=False), re.compile('收入|负值|missing|correlated|constant'),
        token_budget=10_000,
    )
    assert projected is not None
    content, _view = projected
    assert '负值记录260笔' in content and 'missing values' in content
    assert 'constant value' not in content and 'correlated' not in content


def test_model_written_hedges_are_returned_once_per_block():
    markdown = ('实际收入{{value:fact-aaaaaaaaaaaaaaaa:total:元}}，含17条负值明细，其性质待核实。\n\n'
                '### 口径限制与待确认事项\n\n科室排名待复核。\n\n```\n待核实\n```\n')
    [warning] = prose_hedge_warnings(markdown)
    assert '3 处' in warning and '仅作参考' in warning and '{{value' not in warning
    assert prose_hedge_warnings('实际收入{{value:fact-aaaaaaaaaaaaaaaa:total:元}}，科室排名仅作参考。') == []
