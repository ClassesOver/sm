"""Office 文件内 AI 的模型装配：结构化 wire schema 收发与思考配置。

只保留无工具结构化候选所需能力：请求参数归一、wire schema 替换与响应解码校验、
按 RunContext 路由模型档位，以及运行错误记录供结构化执行器纠错。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextvars import ContextVar
from copy import copy, deepcopy
from dataclasses import fields
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlparse

from agno.models.message import Message
from agno.models.openai import OpenAIChat
from agno.models.response import ModelResponse
from dingyi_agno import PlatformModel
from loguru import logger
from pydantic import ValidationError

from ..context_management import (
    TASK_EXECUTION_CONTEXT_TOKEN_LIMIT,
    TASK_EXECUTION_OUTPUT_TOKEN_RESERVE,
    ProjectedOpenAIChat,
    projected_task_execution_model,
)
from ..integrations.model_config import (
    OPENAI_COMPATIBLE_ROLE_MAP,
    normalize_openai_chat_output_limit,
    normalize_openai_chat_reasoning,
    openai_compatible_extra_body,
    uses_dashscope_qwen_thinking_protocol,
)
from ..model_routing import build_model_profiles
from ..reporting.model_policy import (
    REPORTING_VLLM_THINKING_BUDGET_MODEL_ATTR,
    ReportingReasoningEffort,
    ReportingThinkingProfile,
    apply_reporting_thinking_profile,
    clamp_reporting_output_tokens,
    reporting_thinking_profile_from_model,
)
from ..reporting.structured_output.policy import (
    REPORTING_STRUCTURED_MODES_MODEL_ATTR,
    REPORTING_STRUCTURED_REQUEST_MODEL_ATTR,
)
from ..reporting.structured_output.wire_schema import (
    REPORTING_WIRE_DECODER_MODEL_ATTR,
    REPORTING_WIRE_DIALECT_MODEL_ATTR,
    REPORTING_WIRE_DOMAIN_SCHEMA_MODEL_ATTR,
    REPORTING_WIRE_FINGERPRINT_MODEL_ATTR,
    REPORTING_WIRE_SCHEMA_MODEL_ATTR,
)
from .run_context import current_reporting_run_context, reporting_model_route_from_run_context

if TYPE_CHECKING:
    from ..runtime.settings import AgentSettings

_CUMULATIVE_STREAM_USAGE_HOSTS = frozenset({"api.siliconflow.cn"})
_MODEL_TIMEOUT_CAP_SECONDS = 900

_MODEL_RUN_ERROR: ContextVar[tuple[int, Exception] | None] = ContextVar(
    "office_model_run_error",
    default=None,
)


class StructuredResponseValidationError(ValueError):
    """领域校验失败越过 Agno run 边界时的脱敏替身，不携带模型候选原文。"""

    def __init__(self, error: ValidationError) -> None:
        issues = error.errors(include_url=False, include_context=False, include_input=False)
        summary = ", ".join(
            f"{'.'.join(str(part) for part in item.get('loc', ())) or '$'}:{item.get('type')}"
            for item in issues[:8]
        )
        if len(issues) > 8:
            summary += f", …(+{len(issues) - 8})"
        super().__init__(
            f"结构化响应未通过 {error.title} 校验（{len(issues)} 项，已回灌纠错）：{summary}"
        )


class OfficeOpenAIChat(ProjectedOpenAIChat):
    """Office 结构化候选请求：wire schema 收发、档位路由与运行错误登记。"""

    def get_request_params(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        params = super().get_request_params(*args, **kwargs)
        endpoint = str(self.base_url) if self.base_url is not None else None
        params = normalize_openai_chat_output_limit(
            params,
            endpoint=endpoint,
            structured_output=bool(getattr(self, REPORTING_STRUCTURED_REQUEST_MODEL_ATTR, False)),
        )
        params = normalize_openai_chat_reasoning(params, endpoint=endpoint)
        extra_body = params.get("extra_body")
        if (
            params.get("reasoning_effort") is not None
            and isinstance(extra_body, dict)
            and isinstance(extra_body.get("thinking_budget"), int)
            and uses_dashscope_qwen_thinking_protocol(self.id, endpoint)
        ):
            # 百炼 Qwen 拒绝同时提交顶层 reasoning_effort 与 thinking_budget。
            params.pop("reasoning_effort", None)
        wire_schema = getattr(self, REPORTING_WIRE_SCHEMA_MODEL_ATTR, None)
        response_format = params.get("response_format")
        json_schema = (
            response_format.get("json_schema") if isinstance(response_format, dict) else None
        )
        if (
            not isinstance(wire_schema, dict)
            or not isinstance(response_format, dict)
            or not isinstance(json_schema, dict)
        ):
            return params
        # output_schema 仍是领域模型；这里只替换发往兼容端点的 wire schema，
        # 响应回到进程后由同一契约解码，再执行领域校验。
        adapted_format: dict[str, Any] = deepcopy(response_format)
        adapted_json_schema = deepcopy(json_schema)
        adapted_json_schema["schema"] = wire_schema
        adapted_format["json_schema"] = adapted_json_schema
        params["response_format"] = adapted_format
        logger.bind(
            model_id=self.id,
            dialect=getattr(self, REPORTING_WIRE_DIALECT_MODEL_ATTR, None),
            schema_fingerprint=getattr(self, REPORTING_WIRE_FINGERPRINT_MODEL_ATTR, None),
        ).debug("office_structured_wire_schema_applied")
        return params

    def _request_model(self) -> OfficeOpenAIChat:
        """为单次请求复制模型，按 RunContext 档位路由，禁止并发请求修改共享实例。"""

        request_model = copy(self)
        route = reporting_model_route_from_run_context(current_reporting_run_context())
        if route is not None:
            request_model.id = route[1]
        request_model.max_tokens = clamp_reporting_output_tokens(
            request_model.max_tokens, request_model.id
        )
        return apply_reporting_thinking_profile(
            request_model, reporting_thinking_profile_from_model(self)
        )

    @staticmethod
    def _validated_response(model: OfficeOpenAIChat, response: ModelResponse) -> ModelResponse:
        decoder = getattr(model, REPORTING_WIRE_DECODER_MODEL_ATTR, None)
        validator = getattr(model, "_report_response_validator", None)
        if callable(decoder) and response.content is not None:
            # content 保持 provider 原始 JSON 字符串，解码结果只写入 parsed，
            # 否则 Agno 会把有效 strict 响应误判为非字符串内容。
            candidate = decoder(response.content)
            if callable(validator):
                response.parsed = validator(candidate)
            else:
                domain_schema = getattr(model, REPORTING_WIRE_DOMAIN_SCHEMA_MODEL_ATTR, None)
                domain_validator = getattr(domain_schema, "model_validate", None)
                response.parsed = (
                    domain_validator(candidate) if callable(domain_validator) else candidate
                )
        elif callable(validator):
            response.content = validator(response.content)
        return response

    def _clear_report_run_error(self) -> None:
        _MODEL_RUN_ERROR.set(None)

    def _record_report_run_error(self, error: Exception) -> None:
        _MODEL_RUN_ERROR.set((id(self), error))

    def report_run_error(self) -> Exception | None:
        recorded = _MODEL_RUN_ERROR.get()
        return recorded[1] if recorded is not None and recorded[0] == id(self) else None

    def _failed(self, error: BaseException) -> BaseException:
        if isinstance(error, Exception):
            self._record_report_run_error(error)
        if isinstance(error, ValidationError):
            return StructuredResponseValidationError(error)
        return error

    def response(self, messages: list[Message], *args: Any, **kwargs: Any) -> ModelResponse:
        request_model = self._request_model()
        self._clear_report_run_error()
        try:
            response = ProjectedOpenAIChat.response(request_model, messages, *args, **kwargs)
            return self._validated_response(request_model, response)
        except BaseException as error:
            replacement = self._failed(error)
            if replacement is error:
                raise
            raise replacement from error

    async def aresponse(
        self, messages: list[Message], *args: Any, **kwargs: Any
    ) -> ModelResponse:
        request_model = self._request_model()
        self._clear_report_run_error()
        try:
            response = await ProjectedOpenAIChat.aresponse(request_model, messages, *args, **kwargs)
            return self._validated_response(request_model, response)
        except BaseException as error:
            replacement = self._failed(error)
            if replacement is error:
                raise
            raise replacement from error

    def response_stream(self, messages: list[Message], *args: Any, **kwargs: Any) -> Iterator[Any]:
        request_model = self._request_model()
        self._clear_report_run_error()
        try:
            yield from ProjectedOpenAIChat.response_stream(request_model, messages, *args, **kwargs)
        except Exception as error:
            self._record_report_run_error(error)
            raise

    async def aresponse_stream(
        self, messages: list[Message], *args: Any, **kwargs: Any
    ) -> AsyncIterator[Any]:
        request_model = self._request_model()
        self._clear_report_run_error()
        try:
            async for item in ProjectedOpenAIChat.aresponse_stream(
                request_model, messages, *args, **kwargs
            ):
                yield item
        except Exception as error:
            self._record_report_run_error(error)
            raise


def _base_model(settings: AgentSettings, *, enable_thinking: bool, timeout_seconds: int) -> OpenAIChat:
    profiles = build_model_profiles(
        fast_model_id=settings.model_fast_id,
        standard_model_id=settings.model_standard_id,
        strong_model_id=settings.model_strong_id,
    )
    standard_profile = profiles["standard"]
    extra_body = openai_compatible_extra_body(
        enable_thinking=enable_thinking,
        use_vllm_reasoning=settings.model_vllm_reasoning,
    )
    if settings.model_litellm_proxy:
        extra_body = dict(extra_body or {})
        # LiteLLM 只透传 allowlist 中的 OpenAI 原生参数；vLLM 扩展参数经二层 extra_body。
        extra_body["allowed_openai_params"] = ["reasoning_effort"]
        if settings.model_vllm_reasoning and settings.model_vllm_thinking_budget:
            extra_body["extra_body"] = {}
    options: dict[str, Any] = dict(
        timeout=timeout_seconds,
        max_retries=0,
        role_map=OPENAI_COMPATIBLE_ROLE_MAP,
        extra_body=extra_body,
        temperature=1.0,
        top_p=1.0,
        collect_metrics_on_completion=(
            urlparse(settings.openai_base_url).hostname in _CUMULATIVE_STREAM_USAGE_HOSTS
        ),
        strict_output=settings.model_structured_strict,
        retries=2,
        exponential_backoff=True,
    )
    if settings.platform_settings is not None:
        model: OpenAIChat = PlatformModel.for_agent(
            "smart-reporting",
            settings=settings.platform_settings,
            model_profile_key=standard_profile.model_id,
            **options,
        )
    else:
        model = OpenAIChat(
            id=standard_profile.model_id,
            base_url=settings.openai_base_url,
            api_key=settings.openai_api_key,
            **options,
        )
    setattr(
        model,
        REPORTING_STRUCTURED_MODES_MODEL_ATTR,
        {
            "fast": settings.model_fast_structured_mode,
            "standard": settings.model_standard_structured_mode,
            "strong": settings.model_strong_structured_mode,
        },
    )
    setattr(
        model,
        REPORTING_VLLM_THINKING_BUDGET_MODEL_ATTR,
        settings.model_vllm_reasoning and settings.model_vllm_thinking_budget,
    )
    return model


def create_office_model(settings: AgentSettings) -> OfficeOpenAIChat:
    """按部署配置创建 Office 文件内 AI 共用模型（标准档位，结构化候选专用）。"""

    output_token_reserve = settings.report_output_token_reserve
    input_token_budget = max(
        1,
        min(settings.report_context_token_budget, TASK_EXECUTION_CONTEXT_TOKEN_LIMIT)
        - max(TASK_EXECUTION_OUTPUT_TOKEN_RESERVE, output_token_reserve),
    )
    base = _base_model(
        settings,
        enable_thinking=settings.report_phase_enable_thinking,
        timeout_seconds=min(settings.model_timeout_seconds, _MODEL_TIMEOUT_CAP_SECONDS),
    )
    projected = projected_task_execution_model(base, input_token_budget=input_token_budget)
    model = OfficeOpenAIChat(
        **{field.name: getattr(projected, field.name) for field in fields(projected)}
    )
    budget = getattr(projected, "_task_execution_input_token_budget", None)
    if isinstance(budget, int) and budget > 0:
        model._task_execution_input_token_budget = budget
    for attribute in (REPORTING_STRUCTURED_MODES_MODEL_ATTR, REPORTING_VLLM_THINKING_BUDGET_MODEL_ATTR):
        setattr(model, attribute, getattr(base, attribute))
    model.max_tokens = output_token_reserve
    profile = (
        ReportingThinkingProfile.on(
            reasoning_effort=cast(ReportingReasoningEffort, settings.report_phase_reasoning_effort),
            thinking_budget=settings.report_phase_thinking_budget,
            temperature=settings.report_phase_temperature,
        )
        if settings.report_phase_enable_thinking
        else ReportingThinkingProfile.off(temperature=settings.report_phase_temperature)
    )
    apply_reporting_thinking_profile(model, profile)
    model.top_p = 0.95
    return model


__all__ = ["OfficeOpenAIChat", "StructuredResponseValidationError", "create_office_model"]
