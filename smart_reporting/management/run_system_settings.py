"""可信任务系统快照的消费解析；不重放当前服务授权、日志与进程资源策略。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

from ..runtime.settings import AgentSettings
from .configuration_catalog import (
    CONFIGURATION_CATALOG,
    resolve_system_settings,
    validate_system_values,
)
from .models import ManagementError

# 只在已有任务执行对象中有明确消费者的字段才允许历史回放；定义仍来自唯一清单。
EXECUTION_SYSTEM_KEYS = frozenset({
    'AGENT_MODEL_FAST', 'AGENT_MODEL_STANDARD', 'AGENT_MODEL_STRONG',
    'AGENT_MODEL_TIMEOUT_SECONDS', 'AGENT_MODEL_VLLM_REASONING',
    'AGENT_MODEL_VLLM_THINKING_BUDGET', 'AGENT_MODEL_LITELLM_PROXY', 'OPENAI_BASE_URL',
    'AGENT_MODEL_FAST_STRUCTURED_MODE', 'AGENT_MODEL_STANDARD_STRUCTURED_MODE',
    'AGENT_MODEL_STRONG_STRUCTURED_MODE', 'AGENT_MODEL_STRUCTURED_STRICT',
    'AGENT_ENABLE_TOOL_RESULT_COMPRESSION', 'AGENT_ENABLE_SESSION_SUMMARIES',
    'AGENT_REPORT_CODING_ENABLE_THINKING', 'AGENT_REPORT_CODING_TEMPERATURE',
    'AGENT_REPORT_CODING_REASONING_EFFORT', 'AGENT_REPORT_CODING_THINKING_BUDGET',
    'AGENT_REPORT_ENABLE_THINKING', 'AGENT_REPORT_PLANNER_REASONING_EFFORT',
    'AGENT_REPORT_PLANNER_THINKING_BUDGET', 'AGENT_REPORT_ENABLE_VISION', 'AGENT_REPORT_VISION_MODEL',
    'AGENT_REPORT_CONTEXT_TOKEN_BUDGET', 'AGENT_REPORT_OUTPUT_TOKEN_RESERVE',
    'AGENT_REPORT_ANALYSIS_CONCURRENCY', 'AGENT_REPORT_SECTION_CONCURRENCY',
    'AGENT_REPORT_CODING_EXECUTION_MODE', 'AGENT_REPORT_SECTION_WHOLE_GENERATION',
    'AGENT_REPORT_CODEX_ENABLED', 'AGENT_REPORT_VISUALIZATION_SECTION_DEADLINE_SECONDS',
    'AGENT_REPORT_VISUALIZATION_TOTAL_DEADLINE_SECONDS', 'AGENT_REPORT_STANDARD_SUPPLEMENTAL_ENABLED',
})
_ITEMS = {item.key: item for item in CONFIGURATION_CATALOG}


@dataclass(frozen=True)
class FrozenRunSystemSettings:
    settings: AgentSettings = field(repr=False)
    issues: tuple[dict, ...] = ()
    credential_source: str = 'current_startup'
    snapshot: dict | None = field(default=None, repr=False)


def invalid_run_system_configuration():
    return ManagementError('management_run_system_configuration_invalid',
        '报告冻结系统配置校验失败，未使用当前系统值替代，请核对该运行的配置版本。', 409)


def resolve_run_system_settings(startup: AgentSettings, snapshot: dict | None) -> FrozenRunSystemSettings:
    """仅供已核验数据库身份及哈希的快照使用，不接受模型会话值作为授权来源。"""
    revision, digest = (snapshot or {}).get('systemRevision'), (snapshot or {}).get('systemHash')
    if ((revision is None) != (digest is None)
            or revision is not None and (type(revision) is not int or revision < 1
                or not isinstance(digest, str) or re.fullmatch('[0-9a-f]{64}', digest) is None)):
        raise invalid_run_system_configuration()
    if snapshot is None or 'systemValues' not in snapshot or snapshot['systemValues'] is None:
        return FrozenRunSystemSettings(startup, ({'code': 'management_run_system_configuration_legacy',
            'message': '历史运行没有系统执行值快照，继续使用当前启动配置，未声称已恢复历史系统参数。'},),
            snapshot=snapshot)
    values = snapshot['systemValues']
    if not isinstance(values, dict) or any(not isinstance(key, str) for key in values):
        raise invalid_run_system_configuration()
    issues, normalized, unknown = [], {}, []
    for key, value in values.items():
        item = _ITEMS.get(key)
        if item is None:
            unknown.append(key)
            continue
        if item.activation != 'restart' or item.sensitive:
            raise invalid_run_system_configuration()
        # 首版快照会保留未配置的None；只为该字段兼容，不丢弃其余已冻结值。
        if value is None and not item.nullable:
            continue
        normalized[key] = value
    try:
        validated = validate_system_values(normalized)
        selected = {key: value for key, value in validated.items() if key in EXECUTION_SYSTEM_KEYS}
        resolved = resolve_system_settings(startup, selected)
    except (TypeError, ValueError):
        raise invalid_run_system_configuration() from None
    missing = sorted(EXECUTION_SYSTEM_KEYS - selected.keys())
    if missing:
        issues.append({'code': 'management_run_system_configuration_partial',
            'message': '历史系统快照缺少部分执行值，这些字段使用当前启动值，其余字段继续使用已冻结值。', 'keys': missing})
    if unknown:
        issues.append({'code': 'management_run_system_configuration_unknown_keys',
            'message': '快照包含当前版本不识别的系统字段，未用于执行。', 'keys': sorted(unknown)})
    issues.append({'code': 'management_run_system_credentials_current',
        'message': '本运行未恢复可核验的历史凭据引用，认证使用当前启动凭据，不代表历史凭据已冻结。'})
    return FrozenRunSystemSettings(replace(resolved, managed_system_revision=revision, managed_system_hash=digest),
        tuple(issues), snapshot=snapshot)
