"""报告选项浏览器回归：真实 Console Renderer + SDK + Agno HITL，固定模型夹具。

先在 agno-admin-console/frontend 启动 npm run dev，然后运行本脚本。
不调用生产模型、数据库或报告导出；产出截图和机器可读的验收结果。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--console-root', type=Path, default=Path.home() / 'pros/agno-admin-console')
    parser.add_argument('--frontend', default='http://127.0.0.1:5173')
    parser.add_argument('--port', type=int, default=18765)
    parser.add_argument('--output', type=Path, default=Path('/tmp/report-options-console-e2e'))
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    os.environ['AGENT_TRACING_ENABLED'] = 'false'
    os.environ.setdefault('MPLCONFIGDIR', '/tmp/report-options-mpl')
    sys.path.insert(0, str(args.console_root))
    sys.path.insert(0, str(args.console_root / 'sdk/python/src'))

    import httpx
    import uvicorn
    from agno.agent import Agent
    from agno.db.in_memory import InMemoryDb
    from agno.models.response import ModelResponse
    from agno.run import RunContext
    from agno.run.base import RunStatus
    from agno.run.requirement import RunRequirement
    from agno.workflow.types import StepInput
    from backend.app.chat.gateway import _resolve_tool_execution
    from dingyi_agno.chat.protocol import tool_requirement_block
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from playwright.sync_api import expect, sync_playwright

    from smart_reporting.context_management import ProjectedOpenAIChat
    from smart_reporting.reporting.agent import ReportFacadeOpenAIChat
    from smart_reporting.reporting.workflow.controller import ReportWorkflowToolkit
    from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime
    from smart_reporting.reporting.workflow.runtime.models import NormalizedReportPrompt

    args.output.mkdir(parents=True, exist_ok=True)
    records: dict[str, dict] = {}
    scenarios = {
        'prefilled': {
            'prompt': '按上下文生成报告',
            'period_start': '2025-02-01', 'period_end': '2025-03-31',
            'domains': ['income', 'workload'], 'analysis_dimensions': ['院区', '科室'],
        },
        'missing_period': {'prompt': '生成预算报告', 'domains': ['budget']},
    }
    app = FastAPI()
    app.add_middleware(CORSMiddleware, allow_origins=[args.frontend], allow_methods=['*'], allow_headers=['*'])

    @app.get('/health')
    async def health():
        return {'ok': True}

    @app.post('/start')
    async def start(payload: dict):
        key = uuid4().hex
        scenario = dict(scenarios[payload['scenario']])
        prompt = scenario.pop('prompt')
        state = {'submitted': [], 'options': scenario, 'completed': False}
        records[key] = state

        async def begin(workflow_input, context):
            runtime = object.__new__(ReportWorkflowRuntime)
            runtime._request_normalizer = object()
            runtime._run_planner = AsyncMock(return_value=NormalizedReportPrompt(
                reportType='topic', domains=('income',),
                period={'start': '2024-01-01', 'end': '2024-12-31'},
            ))
            normalized = await runtime.normalize_report_request(
                StepInput(input=workflow_input.model_dump(mode='json', by_alias=True, exclude_none=True)),
                RunContext(run_id=context.run_id, session_id=key, session_state={}),
            )
            state['submitted'].append(normalized.content)
            return {'ok': True, 'status': 'completed'}

        agent = Agent(
            model=ReportFacadeOpenAIChat(id=key, api_key='fixture'),
            tools=[ReportWorkflowToolkit(SimpleNamespace(start=begin))],
            db=InMemoryDb(), telemetry=False,
        )
        state['agent'] = agent
        paused = await agent.arun(prompt, session_id=key, run_id=key)
        assert paused.status is RunStatus.paused and not state['submitted']
        state['paused'] = paused
        requirement = paused.active_requirements[0].to_dict()
        state['requirement'] = requirement
        block = tool_requirement_block(requirement['tool_execution'])
        block['interactionKey'] = key
        return {'id': key, 'block': block, 'started': 0}

    @app.post('/continue/{key}')
    async def resume(key: str, payload: dict):
        state = records[key]
        # 使用中台真实 continuation 映射，将浏览器表单值写回 Agno 原始调用身份。
        _resolve_tool_execution(state['requirement']['tool_execution'], {
            'payload': {'pauseType': 'user_input'}, 'result': {'values': payload},
        })
        requirement = RunRequirement.from_dict(state['requirement'])
        completed = await state['agent'].acontinue_run(
            run_id=key, session_id=key, requirements=[requirement],
        )
        state['completed'] = completed.status is RunStatus.completed
        assert state['completed'] and len(state['submitted']) == 1
        return {'completed': True, 'request': state['submitted'][0]}

    @app.get('/state/{key}')
    async def state(key: str):
        record = records[key]
        return {'started': len(record['submitted']), 'completed': record['completed']}

    async def provider(model, messages, *_args, **_kwargs):
        if any(item.role == 'tool' for item in messages):
            return ModelResponse(content='已确认报告选项')
        options = records[model.id]['options']
        return ModelResponse(tool_calls=[{
            'id': 'options-' + model.id, 'type': 'function',
            'function': {'name': 'report_workflow_start', 'arguments': json.dumps(options, ensure_ascii=False)},
        }])

    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=args.port, log_level='warning'))
    fixture = f'http://127.0.0.1:{args.port}'
    report = {'mode': 'controlled-model-fixture', 'checks': [], 'screenshots': []}
    with patch.object(ProjectedOpenAIChat, 'ainvoke', provider):
        worker = threading.Thread(target=server.run, daemon=True)
        worker.start()
        try:
            for _ in range(100):
                if server.started:
                    break
                time.sleep(0.1)
            assert server.started, 'fixture server did not start'
            with sync_playwright() as browser_api:
                executable = Path(browser_api.chromium.executable_path)
                if not executable.exists():
                    executable = next((Path.home() / '.cache/ms-playwright').glob('chromium-*/chrome-linux/chrome'))
                browser = browser_api.chromium.launch(executable_path=str(executable), headless=True)
                page = browser.new_page(viewport={'width': 1280, 'height': 1000}, locale='zh-CN')
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('console', lambda message: errors.append('console '+message.text) if message.type == 'error' else None)
                page.goto(args.frontend, wait_until='domcontentloaded')
                page.evaluate('''async ({fixture}) => {
                    const React = (await import('/node_modules/.vite/deps/react.js')).default;
                    const {createRoot} = (await import('/node_modules/.vite/deps/react-dom_client.js')).default;
                    const {ChatMessageRenderer} = await import('/src/shared/chat/renderer.tsx');
                    const {AppProviders} = await import('/src/app/providers/AppProviders/index.tsx');
                    document.getElementById('root').style.display = 'none';
                    const container = document.createElement('main');
                    container.style.cssText = 'max-width:1000px;margin:20px auto;padding:16px';
                    document.body.appendChild(container);
                    const root = createRoot(container);
                    window.mountReportOptions = async scenario => {
                        const response = await fetch(fixture+'/start', {
                            method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scenario})
                        });
                        const data = await response.json();
                        window.reportFixture = data; window.reportResult = null;
                        root.render(React.createElement(AppProviders,{},React.createElement(ChatMessageRenderer,{
                            key:data.id,locale:'zh-CN',
                            message:{id:data.id,role:'assistant',content:'请确认报告选项',status:'waiting',
                                blocks:[data.block],interactions:{[data.id]:{key:data.id,status:'pending',action:'resume'}}},
                            onSubmitInteraction:async (_block,values)=>{
                                const response=await fetch(fixture+'/continue/'+data.id,{
                                    method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(values)
                                });
                                const result=await response.json();
                                if(!response.ok)throw Error(JSON.stringify(result));
                                window.reportResult=result;
                            }
                        })));
                        return data;
                    };
                }''', {'fixture': fixture})

                errors.clear()
                data = page.evaluate("window.mountReportOptions('prefilled')")
                page.locator('#period_start').wait_for(timeout=5000)
                expect(page.get_by_role('heading', name='报告设置', exact=True)).to_be_visible()
                expect(page.locator('.dingyi-chat-form-block')).not_to_contain_text('report_workflow_start')
                expect(page.locator('#period_start')).to_have_value('2025-02-01')
                expect(page.locator('#period_end')).to_have_value('2025-03-31')
                expect(page.locator('.dingyi-chat-form-block .ant-select').nth(0)).to_contain_text('收入')
                expect(page.locator('.dingyi-chat-form-block .ant-select').nth(0)).to_contain_text('工作量')
                expect(page.locator('.dingyi-chat-form-block .ant-select').nth(1)).to_contain_text('简要版')
                expect(page.locator('.dingyi-chat-form-block .ant-select').nth(2)).to_contain_text('院区')
                expect(page.locator('.dingyi-chat-form-block .ant-select').nth(2)).to_contain_text('科室')
                assert httpx.get(fixture+'/state/'+data['id'], trust_env=False).json()['started'] == 0
                report['checks'].append('all known fields prefilled; no workflow before confirmation')
                page.screenshot(path=str(args.output/'01-prefilled-desktop.png'), full_page=True)
                report['screenshots'].append('01-prefilled-desktop.png')

                page.locator('#period_end').fill('2025-04-30')
                page.locator('#report_length').click()
                page.get_by_title('详细版', exact=True).last.click()
                page.locator('#domains').click()
                page.get_by_title('成本', exact=True).last.click()
                page.keyboard.press('Escape')
                page.locator('#analysis_dimensions').click()
                page.get_by_title('类型', exact=True).last.click()
                page.keyboard.press('Escape')
                page.locator('.dingyi-chat-form-block button[type=submit]').click()
                page.wait_for_function('window.reportResult?.completed === true')
                result = page.evaluate('window.reportResult')
                assert result['request']['period'] == {'start':'2025-02-01','end':'2025-04-30'}, result
                assert result['request']['reportLength'] == 'detailed', result
                assert set(result['request']['domains']) == {'income','full_cost','workload'}, result
                assert result['request']['analysisDimensions'] == ['院区','科室','类型'], result
                report['checks'].append('date, length, metric and dimension edits survive real gateway and Agno continuation')

                page.set_viewport_size({'width':390,'height':844})
                page.evaluate("window.mountReportOptions('missing_period')")
                page.locator('#period_start').wait_for()
                expect(page.locator('#period_start')).to_have_value('')
                expect(page.locator('.dingyi-chat-form-block .ant-select').nth(0)).to_contain_text('预算')
                page.locator('.dingyi-chat-form-block button[type=submit]').click()
                expect(page.get_by_text('请填写此字段', exact=True).first).to_be_visible()
                missing_id = page.evaluate('window.reportFixture.id')
                assert httpx.get(fixture+'/state/'+missing_id, trust_env=False).json()['started'] == 0
                page.screenshot(path=str(args.output/'02-missing-period-mobile.png'), full_page=True)
                report['screenshots'].append('02-missing-period-mobile.png')
                page.locator('#period_start').fill('2025-01-01')
                page.locator('#period_end').fill('2025-12-31')
                page.locator('.dingyi-chat-form-block button[type=submit]').click()
                page.wait_for_function('window.reportResult?.completed === true')
                result = page.evaluate('window.reportResult')
                assert result['request']['domains'] == ['budget'], result
                assert result['request']['reportLength'] == 'brief', result
                assert not result['request'].get('analysisDimensions'), result
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                report['checks'].append('missing period alone needs input; optional dimensions stay empty; default brief; mobile fits')
                assert not errors, errors
                browser.close()
            report['ok'] = True
        finally:
            server.should_exit = True
            worker.join(timeout=5)
            (args.output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
