"""语义消费者与既有模型档位、无历史结构化代理绑定；不连接模型服务。"""

from dataclasses import replace
from types import SimpleNamespace


def test_scoped_runtime_rebuilds_semantic_consumer_from_task_model_without_history_or_tools():
    from agno.agent import Agent

    from smart_reporting.model_routing import build_model_profiles
    from smart_reporting.reporting.agent import _report_model
    from smart_reporting.reporting.bootstrap import create_run_execution_runtime
    from smart_reporting.reporting.template_semantic_review import (
        SignatureReview,
        create_template_signature_reviewer,
    )
    from smart_reporting.reporting.workflow.execution import ReportingTaskCoordinator
    from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime
    from smart_reporting.runtime.settings import AgentSettings

    settings = AgentSettings.from_environment({'OPENAI_API_KEY': 'engineering-fixture-only'}, load_env_file=False)
    startup = replace(settings, model_standard_id='startup-model', report_enable_vision=False)
    task = replace(startup, model_standard_id='frozen-task-model')
    model = _report_model(startup, enable_thinking=False)
    runner = ReportingTaskCoordinator(object(), object(), model_profiles=build_model_profiles(
        fast_model_id=startup.model_fast_id, standard_model_id=startup.model_standard_id,
        strong_model_id=startup.model_strong_id))
    runtime = ReportWorkflowRuntime(db=None, reporting_agent_template=Agent(model=model),
        template_signature_reviewer=create_template_signature_reviewer(model), task_runner=runner,
        workspace_service=SimpleNamespace(), registry=None, profiles=None, state_repository=object(),
        planner_enable_thinking=False)
    scoped = create_run_execution_runtime(runtime, task)
    agent = scoped.template_signature_reviewer.executor.agent
    assert agent.model.id == 'frozen-task-model'
    assert runtime.template_signature_reviewer.executor.agent.model.id == 'startup-model'
    assert agent.output_schema is SignatureReview and not agent.tools
    assert not agent.add_history_to_context and agent.db is None
    assert agent.model.client is None and agent.model.async_client is None
    assert scoped.workspace_service is runtime.workspace_service
    assert scoped.state_repository is runtime.state_repository
