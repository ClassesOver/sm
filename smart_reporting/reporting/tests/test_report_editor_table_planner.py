"""自由改表复用公共结构化协议能力策略，不把供应商400当作用户输入错误。"""

import json
from types import SimpleNamespace

import anyio
import httpx
import pytest

from smart_reporting.report_editor.table_ai import create_report_editor_table_ai_service
from smart_reporting.reporting.agent import ReportingPhaseOpenAIChat
from smart_reporting.reporting.models import ReportingError


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
@pytest.mark.parametrize('model_id,endpoint,mode', [
    ('deepseek-v4.1-flash', 'https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1', 'json_object'),
    ('deepseek-v4-flash-0731', 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'json_object'),
    ('qwen3.8-flash', 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'json_schema'),
])
@pytest.mark.parametrize('valid', [True, False, 'recover'])
async def test_table_planner_uses_provider_policy_and_bounded_domain_correction(model_id, endpoint, mode, valid):
    requests = []
    candidate = {'spec': {'kind': 'comparison', 'rows': [{'factId': 'fact-0123456789abcdef'}],
                         'selectors': ['currentTotal', 'baselineTotal'], 'caption': '收入同比对比'}}

    async def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        expected_mode = 'json_object' if mode == 'json_schema' and valid is not True and len(requests) > 1 else mode
        if body.get('response_format', {}).get('type') != expected_mode:
            return httpx.Response(400, json={'error': {'message': 'This response_format type is unavailable now',
                'type': 'invalid_request_error', 'code': 'invalid_parameter'}})
        content = candidate if valid is True or valid == 'recover' and len(requests) == 2 else {**candidate, 'unregisteredValue': 100}
        return httpx.Response(200, json={'id': 'chatcmpl-table-fixture', 'object': 'chat.completion',
            'created': 1, 'model': model_id, 'choices': [{'index': 0, 'finish_reason': 'stop',
            'message': {'role': 'assistant', 'content': json.dumps(content, ensure_ascii=False)}}],
            'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = create_report_editor_table_ai_service(editor=SimpleNamespace(),
            model=ReportingPhaseOpenAIChat(id=model_id, api_key='fixture-key', base_url=endpoint, http_client=client))
        with anyio.fail_after(15):
            if valid:
                plan = await service._plan('table-analysis_001', '精简标题，保持登记值不变', {},
                    current_columns=['本期', '同期'], current_rows=['收入'], base_spec=None)
                assert plan.spec.caption == '收入同比对比'
                assert plan.spec.rows[0].fact_id == 'fact-0123456789abcdef'
                assert plan.spec.selectors == ('currentTotal', 'baselineTotal')
            else:
                with pytest.raises(ReportingError) as failed:
                    await service._plan('table-analysis_001', '精简标题', {},
                        current_columns=[], current_rows=[], base_spec=None)
                assert failed.value.code == 'report_phase_output_invalid'
    assert len(requests) == (1 if valid is True else 3 if mode == 'json_schema' and valid is False else 2)
    assert requests[0]['response_format']['type'] == mode
    assert all(body['response_format']['type'] == 'json_object' for body in requests[1:])
    if valid == 'recover':
        assert 'unregisteredValue' in json.dumps(requests[1]['messages'])


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
async def test_table_planner_does_not_downgrade_authentication_errors():
    requests = []

    async def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(401, json={'error': {'message': 'Unauthorized response_format request',
            'type': 'authentication_error', 'code': 'invalid_api_key'}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = create_report_editor_table_ai_service(editor=SimpleNamespace(),
            model=ReportingPhaseOpenAIChat(id='qwen3.8-flash', api_key='fixture-key',
                base_url='https://dashscope.aliyuncs.com/compatible-mode/v1', http_client=client))
        with pytest.raises(ReportingError) as failed:
            await service._plan('table-analysis_001', '精简标题', {},
                current_columns=[], current_rows=[], base_spec=None)
        assert failed.value.code == 'report_editor_table_ai_plan_failed'
    assert len(requests) == 1
