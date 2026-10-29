"""新版 Console 原生报告表单回归；模型和报告生成使用固定夹具。"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend", default="http://127.0.0.1:5174")
    parser.add_argument("--console-root", type=Path, default=Path.home() / "pros/agno-admin-console")
    parser.add_argument("--output", type=Path, default=Path("/tmp/report-options-console-055"))
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.path.insert(0, str(args.console_root))
    os.environ["AGENT_TRACING_ENABLED"] = "false"
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/report-options-mpl")

    from agno.agent import Agent
    from agno.db.in_memory import InMemoryDb
    from agno.models.response import ModelResponse
    from agno.run.base import RunStatus
    from agno.run.requirement import RunRequirement
    from backend.app.chat.gateway import _resolve_tool_execution
    from dingyi_agno import __version__
    from dingyi_agno.chat.protocol import tool_requirement_block
    from playwright.async_api import async_playwright, expect

    from smart_reporting.context_management import ProjectedOpenAIChat
    from smart_reporting.reporting.agent import ReportFacadeOpenAIChat
    from smart_reporting.reporting.workflow.controller import ReportWorkflowToolkit

    args.output.mkdir(parents=True, exist_ok=True)
    report = {"sdk": __version__, "mode": "controlled-model-fixture", "checks": []}
    start = AsyncMock(return_value={"ok": True, "status": "completed"})
    options = {"period_start": "2025-02-01", "period_end": "2025-03-31",
               "metrics": ["收入", "工作量"], "analysis_dimensions": ["院区", "科室"]}
    provider = AsyncMock(return_value=ModelResponse(tool_calls=[{
        "id": "options", "type": "function", "function": {
            "name": "report_workflow_start", "arguments": json.dumps(options, ensure_ascii=False),
        },
    }]))
    with patch.object(ProjectedOpenAIChat, "ainvoke", provider):
        agent = Agent(model=ReportFacadeOpenAIChat(id="fixture", api_key="fixture"),
                      tools=[ReportWorkflowToolkit(SimpleNamespace(start=start))],
                      db=InMemoryDb(), telemetry=False)
        paused = await agent.arun("按院区和科室分析2025年2至3月收入和工作量", session_id="browser")
        assert paused.status is RunStatus.paused
        requirement = paused.active_requirements[0].to_dict()
        block = tool_requirement_block(requirement["tool_execution"])
        block["interactionKey"] = "options"
        async with async_playwright() as api:
            executable = Path(api.chromium.executable_path)
            if not executable.exists():
                executable = next((Path.home() / ".cache/ms-playwright").glob("chromium-*/chrome-linux/chrome"))
            browser = await api.chromium.launch(executable_path=str(executable), headless=True)
            page = await browser.new_page(viewport={"width": 1280, "height": 1000}, locale="zh-CN")
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            try:
                await page.goto(args.frontend, wait_until="domcontentloaded")
                await page.evaluate("""async block => {
                    const React=(await import('/node_modules/.vite/deps/react.js')).default;
                    const {createRoot}=(await import('/node_modules/.vite/deps/react-dom_client.js')).default;
                    const {ChatMessageRenderer}=await import('/src/shared/chat/renderer.tsx');
                    const {AppProviders}=await import('/src/app/providers/AppProviders/index.tsx');
                    document.getElementById('root').style.display='none';
                    const container=document.createElement('main');
                    container.style.cssText='max-width:760px;margin:24px auto;padding:16px';
                    document.body.appendChild(container);
                    createRoot(container).render(React.createElement(AppProviders,{},React.createElement(ChatMessageRenderer,{
                        locale:'zh-CN',message:{id:'options',role:'assistant',status:'waiting',
                            content:'',blocks:[block],interactions:{options:{key:'options',status:'pending'}}},
                        onSubmitInteraction:async(_block,values)=>{window.submitted=values;}
                    })));
                }""", block)
                await expect(page.locator("#period_start")).to_have_value("2025-02-01")
                await expect(page.locator("#period_end")).to_have_value("2025-03-31")
                form = page.locator(".dingyi-chat-form-block")
                await expect(form.get_by_role("heading", name="确认报告需求", exact=True)).to_be_visible()
                await expect(form).not_to_contain_text("report_workflow_start")
                await expect(form).to_contain_text("开始日期")
                await expect(form).to_contain_text("收入")
                await expect(form).to_contain_text("简要版")
                start.assert_not_awaited()
                await page.screenshot(path=str(args.output / "01-desktop.png"), full_page=True)
                report["checks"].append("新版 SDK 日期和中文多选预填，确认前未启动")

                await page.locator("#period_end").fill("2025-04-30")
                await page.locator("#report_length").click()
                await page.get_by_title("详细版", exact=True).last.click()
                await page.locator("#metrics").click()
                await page.get_by_title("预算", exact=True).last.click()
                await page.keyboard.press("Escape")
                await form.locator(".dingyi-chat-form-title").click()
                await page.locator(".ant-select-dropdown:visible").wait_for(state="hidden")
                await page.set_viewport_size({"width": 390, "height": 844})
                await page.screenshot(path=str(args.output / "02-mobile.png"), full_page=True)
                assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                await form.locator("button[type=submit]").click()
                await page.wait_for_function("window.submitted !== undefined")
                values = await page.evaluate("window.submitted")
                assert values["period_end"] == "2025-04-30"
                assert values["report_length"] == "详细版"
                assert set(values["metrics"]) == {"收入", "工作量", "预算"}
                _resolve_tool_execution(requirement["tool_execution"], {
                    "payload": {"pauseType": "user_input"}, "result": {"values": values},
                })
                provider.return_value = ModelResponse(content="已确认")
                completed = await agent.acontinue_run(run_id=paused.run_id, session_id=paused.session_id,
                                                     requirements=[RunRequirement.from_dict(requirement)])
                assert completed.status is RunStatus.completed
                start.assert_awaited_once()
                confirmed = start.call_args.args[0].request_options
                assert confirmed.period.end.isoformat() == "2025-04-30"
                assert confirmed.report_length == "详细版"
                assert set(confirmed.domains) == {"income", "workload", "budget"}
                report["checks"].append("移动端无溢出，编辑值经新版 gateway 和 Agno 续跑完整保留")
                assert not errors, errors
                report["ok"] = True
            finally:
                await browser.close()
                (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
