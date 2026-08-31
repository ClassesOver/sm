"""Reporting Profile、上下文与事实查询能力。"""

# mypy: disable-error-code="attr-defined"
# 运行时由 toolkit 末尾组合的多重继承提供跨阶段成员；静态检查无法解析该延迟装配。

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

import jmespath
from agno.run import RunContext
from jmespath.exceptions import JMESPathError

from ..models import ReportingError
from ..workflow.checkpoint import ProfileReadReceipt
from .validation import (
    _bound_profile_pointer_value,
    _collect_profile_pointers,
    _decode_json_pointer,
    _encode_json_pointer_token,
    _jmespath_reporting_error,
    _resolve_json_pointer,
)

MAX_PROFILE_POINTER_ITEMS = 200
MAX_PROFILE_POINTER_OUTPUT_BYTES = 16 * 1024
MAX_VISUALIZATION_FACTS_OUTPUT_BYTES = 128 * 1024
ANALYSIS_CONTEXT_QUERY_EXAMPLES = (
    "datasets[].{datasetId: datasetId, rowCount: rowCount, periodCoverage: periodCoverage}",
    "datasets[].{datasetId: datasetId, metrics: metricSemantics[].fieldRef}",
)


def _profile_receipt_command_id(receipt: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return f"profile-receipt:{receipt['receiptId']}:{digest}"


def _analysis_context_projection(
    analysis_context: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    """构造稳定、类型化的分析上下文视图，避免模型枚举大型装配 JSON。"""

    raw_plans = contract.get("analysisPlans")
    plans = raw_plans if isinstance(raw_plans, Mapping) else {}
    current_analysis_id = contract.get("currentAnalysisId")
    current_analysis = (
        plans.get(current_analysis_id)
        if isinstance(current_analysis_id, str)
        and isinstance(plans.get(current_analysis_id), Mapping)
        else None
    )
    task_kind = contract.get("taskKind")
    if task_kind == "analysis_item" and not isinstance(current_analysis, Mapping):
        raise ReportingError(
            "report_analysis_context_invalid",
            "当前 analysis item 缺少受信计划投影。",
        )
    selected_dataset_ids = {
        value
        for value in (
            current_analysis.get("datasetIds", ())
            if isinstance(current_analysis, Mapping)
            else contract.get("datasetIds", ())
        )
        if isinstance(value, str)
    }
    raw_contexts = analysis_context.get("datasetContexts")
    dataset_contexts = raw_contexts if isinstance(raw_contexts, list) else []
    dataset_fields = (
        "datasetId",
        "path",
        "size",
        "sha256",
        "rowCount",
        "columnCount",
        "fields",
        "numericFields",
        "periodCoverage",
        "periodValues",
        "organizationGrain",
        "metricSemantics",
        "sourceWarnings",
        "qualityWarnings",
        "timeSeriesSortField",
        "timeSeriesFields",
    )
    datasets = [
        {key: item[key] for key in dataset_fields if key in item}
        for item in dataset_contexts
        if isinstance(item, Mapping)
        and isinstance(item.get("datasetId"), str)
        and (not selected_dataset_ids or item["datasetId"] in selected_dataset_ids)
    ]
    return {
        "version": 1,
        "taskKind": task_kind,
        "currentAnalysis": dict(current_analysis)
        if isinstance(current_analysis, Mapping)
        else None,
        "datasets": datasets,
        "warnings": [
            value for value in analysis_context.get("warnings", ()) if isinstance(value, str)
        ],
    }


class RuntimeProfileMixin:
    async def read_profile_pointer(
        self,
        datasetId: str,
        profilePointer: str,
        purpose: str,
        maxItems: int = 50,
        _agno_run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """核验三层文件身份后返回有界 Profile 节点。"""
        # Agno 会为名为 run_context 的普通工具入口回传 session_state
        # 快照；并行 Profile 调用按原调用顺序合并结果时，较早完成的旧快照可能覆盖
        # 其他调用已经写入的 receipt。使用框架保留的内部注入名后仍共享同一状态引用，
        # 但不会产生可回放快照，这是并行 checkpoint 写入不可绕过的不变量。
        run_context = _agno_run_context
        if (
            isinstance(maxItems, bool)
            or not isinstance(maxItems, int)
            or not 1 <= maxItems <= MAX_PROFILE_POINTER_ITEMS
        ):
            raise ReportingError(
                "report_profile_pointer_invalid", "maxItems 必须在 1 至 200 之间。"
            )
        scope = await self.kernel.scope(run_context)
        parameters, contract = self._phase_parameters(scope, "analysis")
        self._require_phase_tool(
            scope,
            allowed=frozenset({"analysis"}),
            tool_name="read_profile_pointer",
            run_context=run_context,
            task_kinds=frozenset({"analysis_item"}),
        )
        self._require_current_analysis_dataset(contract, datasetId)
        validation_context = await self._read_trusted_json(
            thread_id=scope.thread_id,
            identity=parameters.get("validationContextFile"),
            identity_code="report_profile_context_changed",
            structure_code="report_profile_context_invalid",
        )
        analysis_context = await self._read_trusted_json(
            thread_id=scope.thread_id,
            identity=validation_context.get("analysisContextFile"),
            identity_code="report_analysis_context_changed",
            structure_code="report_analysis_context_invalid",
        )
        raw_contexts = analysis_context.get("datasetContexts")
        matches = (
            [
                item
                for item in raw_contexts
                if isinstance(item, dict) and item.get("datasetId") == datasetId
            ]
            if isinstance(raw_contexts, list)
            else []
        )
        if len(matches) != 1:
            raise ReportingError(
                "report_profile_dataset_unknown", "datasetId 不属于当前受信分析上下文。"
            )
        dataset_context = matches[0]
        profile_model_view = dataset_context.get("profileModelView")
        if not isinstance(profile_model_view, dict):
            raise ReportingError(
                "report_profile_context_invalid", "Dataset 缺少有界 Profile 索引。"
            )
        indexed_pointers = _collect_profile_pointers(profile_model_view)
        pointer_tokens = _decode_json_pointer(profilePointer)
        fields = dataset_context.get("fields")
        field_names = (
            {item for item in fields if isinstance(item, str)}
            if isinstance(fields, list)
            else set()
        )
        variable_pointer = (
            len(pointer_tokens) in {2, 3}
            and pointer_tokens[0] == "variables"
            and pointer_tokens[1] in field_names
        )
        if profilePointer not in indexed_pointers and not variable_pointer:
            raise ReportingError(
                "report_profile_pointer_unknown",
                "Profile Pointer 未在受信索引登记，或会展开禁止的完整结构。",
            )

        profile = await self._read_trusted_json(
            thread_id=scope.thread_id,
            identity=dataset_context.get("profileFile"),
            identity_code="report_analysis_profile_changed",
            structure_code="report_analysis_profile_invalid",
        )
        value = _resolve_json_pointer(profile, pointer_tokens)
        receipt = ProfileReadReceipt.create(
            dataset_id=datasetId,
            profile_pointer=profilePointer,
            snapshot_hash=str(dataset_context["profileFile"]["sha256"]),
            purpose=purpose,
        )
        serialized_receipt = receipt.model_dump(mode="json", by_alias=True)
        effective_limit = min(maxItems, MAX_PROFILE_POINTER_ITEMS)
        child_pointers = (
            {
                str(key): f"{profilePointer}/{_encode_json_pointer_token(str(key))}"
                for key, child in sorted(value.items(), key=lambda item: str(item[0]))
                if isinstance(child, (dict, list))
            }
            if isinstance(value, dict)
            else {}
        )
        while True:
            bounded_value, truncated = _bound_profile_pointer_value(
                value, max_items=effective_limit
            )
            result = {
                "ok": True,
                "datasetId": datasetId,
                "profilePointer": profilePointer,
                "value": bounded_value,
                "childPointers": child_pointers,
                "truncated": truncated,
                "itemLimit": effective_limit,
                "readReceipt": serialized_receipt,
            }
            encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if len(encoded) <= MAX_PROFILE_POINTER_OUTPUT_BYTES:
                bounded = await self._record_and_bound_profile_result(
                    scope=scope,
                    tool_name="read_profile_pointer",
                    arguments={
                        "datasetId": datasetId,
                        "profilePointer": profilePointer,
                        "purpose": purpose,
                        "maxItems": maxItems,
                    },
                    result=result,
                    run_context=run_context,
                )
                await self._apply_durable(
                    scope,
                    name="record_profile_receipt",
                    payload={"receipt": serialized_receipt},
                    command_id=_profile_receipt_command_id(serialized_receipt),
                )
                return bounded
            if effective_limit <= 1:
                raise ReportingError(
                    "report_profile_pointer_too_large", "Profile Pointer 标量超过工具输出边界。"
                )
            effective_limit = max(1, effective_limit // 2)

    async def query_profile(
        self,
        datasetId: str,
        query: str,
        purpose: str,
        maxItems: int = 50,
        _agno_run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """执行受限 JMESPath 查询，并把表达式绑定到完整 Profile 快照。"""

        run_context = _agno_run_context
        if (
            isinstance(maxItems, bool)
            or not isinstance(maxItems, int)
            or not 1 <= maxItems <= MAX_PROFILE_POINTER_ITEMS
            or not isinstance(query, str)
            or query != query.strip()
            or not query
            or len(query) > 1024
        ):
            raise ReportingError(
                "report_profile_query_invalid", "JMESPath query 或 maxItems 无效。"
            )
        try:
            expression = jmespath.compile(query)
        except (JMESPathError, TypeError, ValueError) as error:
            return self._failure(
                _jmespath_reporting_error(
                    error,
                    code="report_profile_query_invalid",
                    subject="Profile query",
                )
            )
        scope = await self.kernel.scope(run_context)
        parameters, contract = self._phase_parameters(scope, "analysis")
        self._require_phase_tool(
            scope,
            allowed=frozenset({"analysis"}),
            tool_name="query_profile",
            run_context=run_context,
            task_kinds=frozenset({"analysis_item"}),
        )
        self._require_current_analysis_dataset(contract, datasetId)
        validation_context = await self._read_trusted_json(
            thread_id=scope.thread_id,
            identity=parameters.get("validationContextFile"),
            identity_code="report_profile_context_changed",
            structure_code="report_profile_context_invalid",
        )
        analysis_context = await self._read_trusted_json(
            thread_id=scope.thread_id,
            identity=validation_context.get("analysisContextFile"),
            identity_code="report_analysis_context_changed",
            structure_code="report_analysis_context_invalid",
        )
        raw_contexts = analysis_context.get("datasetContexts")
        matches = (
            [
                item
                for item in raw_contexts
                if isinstance(item, dict) and item.get("datasetId") == datasetId
            ]
            if isinstance(raw_contexts, list)
            else []
        )
        if len(matches) != 1:
            raise ReportingError(
                "report_profile_dataset_unknown", "datasetId 不属于当前受信分析上下文。"
            )
        dataset_context = matches[0]
        profile = await self._read_trusted_json(
            thread_id=scope.thread_id,
            identity=dataset_context.get("profileFile"),
            identity_code="report_analysis_profile_changed",
            structure_code="report_analysis_profile_invalid",
        )
        try:
            value = expression.search(profile)
        except (JMESPathError, TypeError, ValueError) as error:
            return self._failure(
                _jmespath_reporting_error(
                    error,
                    code="report_profile_query_invalid",
                    subject="Profile query",
                )
            )
        receipt = ProfileReadReceipt.create_query(
            dataset_id=datasetId,
            query=query,
            snapshot_hash=str(dataset_context["profileFile"]["sha256"]),
            purpose=purpose,
        )
        serialized_receipt = receipt.model_dump(mode="json", by_alias=True)
        effective_limit = min(maxItems, MAX_PROFILE_POINTER_ITEMS)
        while True:
            bounded_value, truncated = _bound_profile_pointer_value(
                value, max_items=effective_limit
            )
            result = {
                "ok": True,
                "datasetId": datasetId,
                "query": query,
                "value": bounded_value,
                "truncated": truncated,
                "itemLimit": effective_limit,
                "readReceipt": serialized_receipt,
            }
            encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if len(encoded) <= MAX_PROFILE_POINTER_OUTPUT_BYTES:
                bounded = await self._record_and_bound_profile_result(
                    scope=scope,
                    tool_name="query_profile",
                    arguments={
                        "datasetId": datasetId,
                        "query": query,
                        "purpose": purpose,
                        "maxItems": maxItems,
                    },
                    result=result,
                    run_context=run_context,
                )
                await self._apply_durable(
                    scope,
                    name="record_profile_receipt",
                    payload={"receipt": serialized_receipt},
                    command_id=_profile_receipt_command_id(serialized_receipt),
                )
                return bounded
            if effective_limit <= 1:
                raise ReportingError(
                    "report_profile_query_too_large", "JMESPath 查询标量超过工具输出边界。"
                )
            effective_limit = max(1, effective_limit // 2)

    async def query_analysis_context(
        self,
        query: str,
        purpose: str,
        maxItems: int = 50,
        _agno_run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """对受信 analysisContextFile 执行有界 JMESPath 查询。

        analysisContextFile 只承载 Dataset/期间/字段等装配事实，不属于 Profile 快照，
        因此这里只记录普通 analysis operation，不创建 ProfileReadReceipt。
        """
        if (
            isinstance(maxItems, bool)
            or not isinstance(maxItems, int)
            or not 1 <= maxItems <= MAX_PROFILE_POINTER_ITEMS
            or not isinstance(query, str)
            or query != query.strip()
            or not query
            or len(query) > 1024
            or not isinstance(purpose, str)
            or not purpose.strip()
            or len(purpose) > 1000
        ):
            raise ReportingError(
                "report_analysis_context_query_invalid",
                "analysisContext JMESPath query、purpose 或 maxItems 无效。",
            )
        try:
            expression = jmespath.compile(query)
        except JMESPathError as error:
            return self._failure(
                _jmespath_reporting_error(
                    error,
                    code="report_analysis_context_query_invalid",
                    subject="analysisContext query",
                )
            )
        run_context = _agno_run_context
        scope = await self.kernel.scope(run_context)
        parameters, contract = self._phase_parameters(scope, "analysis")
        self._require_phase_tool(
            scope,
            allowed=frozenset({"analysis"}),
            tool_name="query_analysis_context",
            run_context=run_context,
            task_kinds=frozenset(
                {"analysis_item", "visualization_section", "visualization_finalize"}
            ),
        )
        validation_context = await self._read_trusted_json(
            thread_id=scope.thread_id,
            identity=parameters.get("validationContextFile"),
            identity_code="report_profile_context_changed",
            structure_code="report_profile_context_invalid",
        )
        analysis_context = await self._read_trusted_json(
            thread_id=scope.thread_id,
            identity=validation_context.get("analysisContextFile"),
            identity_code="report_analysis_context_changed",
            structure_code="report_analysis_context_invalid",
        )
        projection = _analysis_context_projection(analysis_context, contract)
        try:
            value = expression.search(projection)
        except (JMESPathError, TypeError, ValueError) as error:
            return self._failure(
                _jmespath_reporting_error(
                    error,
                    code="report_analysis_context_query_invalid",
                    subject="analysisContext query",
                )
            )
        effective_limit = min(maxItems, MAX_PROFILE_POINTER_ITEMS)
        while True:
            bounded_value, truncated = _bound_profile_pointer_value(
                value, max_items=effective_limit
            )
            result = {
                "ok": True,
                "query": query,
                "value": bounded_value,
                "truncated": truncated,
                "itemLimit": effective_limit,
                "queryExamples": list(ANALYSIS_CONTEXT_QUERY_EXAMPLES),
            }
            encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if len(encoded) <= MAX_PROFILE_POINTER_OUTPUT_BYTES:
                return await self._record_and_bound_profile_result(
                    scope=scope,
                    tool_name="query_analysis_context",
                    arguments={"query": query, "purpose": purpose, "maxItems": maxItems},
                    result=result,
                    run_context=run_context,
                )
            if effective_limit <= 1:
                raise ReportingError(
                    "report_analysis_context_query_too_large",
                    "analysisContext 查询标量超过工具输出边界。",
                )
            effective_limit = max(1, effective_limit // 2)

    async def query_analysis_facts(
        self,
        query: str,
        purpose: str,
        maxItems: int = 50,
        _agno_run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """校验当前任务的不可变 facts 身份后执行有界 JMESPath。"""

        if (
            isinstance(maxItems, bool)
            or not isinstance(maxItems, int)
            or not 1 <= maxItems <= MAX_PROFILE_POINTER_ITEMS
            or not isinstance(query, str)
            or query != query.strip()
            or not query
            or len(query) > 1024
            or not isinstance(purpose, str)
            or not purpose.strip()
            or len(purpose) > 1000
        ):
            raise ReportingError(
                "report_analysis_facts_query_invalid",
                "analysis facts JMESPath query、purpose 或 maxItems 无效。",
            )
        try:
            expression = jmespath.compile(query)
        except (JMESPathError, TypeError, ValueError) as error:
            return self._failure(
                _jmespath_reporting_error(
                    error,
                    code="report_analysis_facts_query_invalid",
                    subject="analysis facts query",
                )
            )
        run_context = _agno_run_context
        scope = await self.kernel.scope(run_context)
        _parameters, contract = self._phase_parameters(scope, "analysis")
        self._require_phase_tool(
            scope,
            allowed=frozenset({"analysis"}),
            tool_name="query_analysis_facts",
            run_context=run_context,
            task_kinds=frozenset(
                {"analysis_item", "visualization_section", "visualization_finalize"}
            ),
        )
        raw_fact_files = contract.get("deterministicFactFiles")
        if not isinstance(raw_fact_files, dict):
            raise ReportingError(
                "report_analysis_facts_invalid", "当前 Task 缺少不可变 facts 注册表。"
            )
        task_kind = contract.get("taskKind")
        current_analysis_id = contract.get("currentAnalysisId")
        if task_kind == "analysis_item":
            analysis_ids = (
                [current_analysis_id]
                if isinstance(current_analysis_id, str) and current_analysis_id
                else []
            )
        else:
            raw_analysis_ids = contract.get("analysisIds")
            analysis_ids = [
                value for value in raw_analysis_ids or () if isinstance(value, str) and value
            ]
        if not analysis_ids or any(
            analysis_id not in raw_fact_files for analysis_id in analysis_ids
        ):
            raise ReportingError(
                "report_analysis_facts_invalid", "当前 Task 的 facts 注册表不完整。"
            )
        durable_items: Mapping[str, Any] = {}
        if (
            task_kind in {"visualization_section", "visualization_finalize"}
            and contract.get("visualizationBudgetVersion") == 1
        ):
            durable = await self._durable_state(scope)
            raw_completed = durable.payload.get("completedAnalysisIds")
            completed_ids = [
                value for value in raw_completed or () if isinstance(value, str) and value
            ]
            if len(completed_ids) != len(analysis_ids) or set(completed_ids) != set(analysis_ids):
                raise ReportingError(
                    "report_analysis_facts_invalid",
                    "visualization facts 查询与 durable 完成集合不一致。",
                )
            raw_items = durable.payload.get("analysisItems")
            if not isinstance(raw_items, Mapping):
                raise ReportingError(
                    "report_analysis_facts_invalid", "durable analysisItems 注册表无效。"
                )
            durable_items = raw_items
        plans = (
            durable.payload.get("analysisPlans")
            if task_kind in {"visualization_section", "visualization_finalize"}
            and contract.get("visualizationBudgetVersion") == 1
            else contract.get("analysisPlans")
        )
        plans = plans if isinstance(plans, Mapping) else {}
        documents = []
        for analysis_id in analysis_ids:
            document = await self._read_trusted_json(
                thread_id=scope.thread_id,
                identity=raw_fact_files[analysis_id],
                identity_code="report_analysis_facts_changed",
                structure_code="report_analysis_facts_invalid",
            )
            projected: dict[str, Any] = {"analysisId": analysis_id, "facts": document}
            if durable_items:
                item = durable_items.get(analysis_id)
                plan = plans.get(analysis_id)
                if not isinstance(item, Mapping):
                    raise ReportingError(
                        "report_analysis_facts_invalid",
                        "durable analysis item 注册表不完整。",
                    )
                projected.update(
                    {
                        "summary": item.get("summary"),
                        "plan": (
                            {
                                key: plan.get(key)
                                for key in (
                                    "analysisId",
                                    "domain",
                                    "step",
                                    "primaryMetricFamily",
                                    "datasetIds",
                                )
                                if key in plan
                            }
                            if isinstance(plan, Mapping)
                            else None
                        ),
                        "evidenceFiles": item.get("evidenceFiles", []),
                        "citationIds": item.get("citationIds", []),
                    }
                )
            documents.append(projected)
        search_value: Any = (
            documents[0]["facts"] if task_kind == "analysis_item" else {"analyses": documents}
        )
        try:
            value = expression.search(search_value)
        except (JMESPathError, TypeError, ValueError) as error:
            return self._failure(
                _jmespath_reporting_error(
                    error,
                    code="report_analysis_facts_query_invalid",
                    subject="analysis facts query",
                )
            )
        effective_limit = min(maxItems, MAX_PROFILE_POINTER_ITEMS)
        output_limit = (
            MAX_VISUALIZATION_FACTS_OUTPUT_BYTES
            if task_kind in {"visualization_section", "visualization_finalize"}
            else MAX_PROFILE_POINTER_OUTPUT_BYTES
        )
        while True:
            bounded_value, truncated = _bound_profile_pointer_value(
                value, max_items=effective_limit
            )
            result = {
                "ok": True,
                "analysisIds": analysis_ids,
                "query": query,
                "value": bounded_value,
                "truncated": truncated,
                "itemLimit": effective_limit,
            }
            encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if len(encoded) <= output_limit:
                bound_options = (
                    {"preview_bytes": MAX_VISUALIZATION_FACTS_OUTPUT_BYTES}
                    if task_kind in {"visualization_section", "visualization_finalize"}
                    else {}
                )
                return await self._record_and_bound_profile_result(
                    scope=scope,
                    tool_name="query_analysis_facts",
                    arguments={"query": query, "purpose": purpose, "maxItems": maxItems},
                    result=result,
                    run_context=run_context,
                    **bound_options,
                )
            if effective_limit <= 1:
                raise ReportingError(
                    "report_analysis_facts_query_too_large",
                    "analysis facts 查询标量超过工具输出边界。",
                )
            effective_limit = max(1, effective_limit // 2)
