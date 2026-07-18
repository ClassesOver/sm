# -*- coding: utf-8 -*-
import datetime
import hashlib
import json
import time
import uuid

import requests
from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.tools.safe_eval import safe_eval

from .agui_chat_mention import MentionTokenError
from .agui_chat_tool import canonical_json, register_business_command
from .agui_chat_workspace import issue_thread_capability


COMMAND_NAME = "odoo.business.report.filters"
MAX_FILTERS = 5
MAX_DETAIL_ROWS = 5000
MAX_GROUPS = 5000
MAX_DETAIL_FIELDS = 30
MAX_DIMENSIONS = 2
MAX_METRICS = 5
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
FORBIDDEN_FIELD_TYPES = {"binary", "many2many", "one2many"}
NUMERIC_FIELD_TYPES = {"float", "integer", "monetary"}
ORDERABLE_FIELD_TYPES = NUMERIC_FIELD_TYPES.union({"date", "datetime"})
DATE_FIELD_TYPES = {"date", "datetime"}
DATE_GRANULARITIES = {"day", "week", "month", "quarter", "year"}
AGGREGATIONS = {"count", "sum", "avg", "min", "max"}


class ReportError(ValueError):
    def __init__(self, code, message=None):
        super(ReportError, self).__init__(message or code)
        self.code = code


def _safe_filter_value(env, value, expected_type, label):
    if isinstance(value, expected_type):
        return value
    if not isinstance(value, str):
        raise ReportError("invalid_filter", "%s格式无效。" % label)
    namespace = {
        "context": dict(env.context),
        "context_today": lambda: fields.Date.context_today(env.user),
        "current_date": fields.Date.context_today(env.user),
        "datetime": datetime,
        "relativedelta": relativedelta,
        "time": time,
        "uid": env.uid,
        "user": env.user,
    }
    try:
        result = safe_eval(value, namespace, mode="eval", nocopy=True)
    except Exception:
        raise ReportError("invalid_filter", "%s无法在受限环境中解析。" % label)
    if not isinstance(result, expected_type):
        raise ReportError("invalid_filter", "%s格式无效。" % label)
    return result


def _policy_for_model(env, model_name):
    groups = set(env.user.groups_id.ids)
    policies = env["agui.chat.tool.policy"].sudo().search([
        ("active", "=", True),
        ("tool_name", "=", COMMAND_NAME),
        ("access_level", "=", "read"),
        ("model_name", "=", model_name),
    ], order="sequence, id")
    return next((
        policy for policy in policies
        if not policy.group_ids or groups.intersection(policy.group_ids.ids)
    ), False)


def _allowed_fields(env, model_name):
    policy = _policy_for_model(env, model_name)
    if not policy:
        raise ReportError("policy_denied", "当前用户没有该筛选模型的报表策略。")
    names = [
        item.strip() for item in (policy.field_names or "").split(",") if item.strip()
    ]
    sensitive = set(
        env["agui.chat.config"].sudo().get_active_config().sensitive_fields()
    )
    model = env[model_name]
    allowed = [
        name for name in names
        if name in model._fields and
        model._fields[name].type not in FORBIDDEN_FIELD_TYPES and
        name not in sensitive
    ]
    if not allowed:
        raise ReportError("policy_denied", "报表策略没有可用字段。")
    return allowed


def _field_name(value):
    return str(value or "").split(":", 1)[0]


def _domain_fields(domain):
    result = set()

    def visit(value):
        if isinstance(value, (list, tuple)):
            if (
                len(value) >= 3 and isinstance(value[0], str) and
                value[0] not in ("&", "|", "!")
            ):
                result.add(value[0])
                return
            for item in value:
                visit(item)

    visit(domain)
    return result


def _normalize_group_by(value):
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)) and all(isinstance(item, str) for item in value):
        return list(value)
    raise ReportError("invalid_filter", "筛选分组格式无效。")


def _normalize_sort(value):
    if not value:
        return []
    if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) for item in value):
        raise ReportError("invalid_filter", "筛选排序格式无效。")
    return list(value)


def _sort_parts(value):
    value = str(value or "").strip()
    if value.startswith("-"):
        parts = value[1:].split()
        direction = "desc"
        if len(parts) != 1:
            raise ReportError("invalid_filter", "筛选排序格式无效。")
    else:
        parts = value.split()
        direction = parts[1].lower() if len(parts) == 2 else "asc"
    if len(parts) not in (1, 2) or direction not in ("asc", "desc"):
        raise ReportError("invalid_filter", "筛选排序格式无效。")
    return parts[0], direction


def _sort_field(value):
    return _sort_parts(value)[0]


def _validate_field_set(env, model_name, names, allowed, code="field_not_allowed"):
    model = env[model_name]
    for raw_name in names:
        name = _field_name(raw_name)
        if not name or "." in name or name not in allowed or name not in model._fields:
            raise ReportError(code, "字段 %s 不在报表策略白名单中。" % (name or raw_name))
        if model._fields[name].type in FORBIDDEN_FIELD_TYPES:
            raise ReportError(code, "字段 %s 的类型不可用于报表。" % name)


def _normalize_binding(env, binding):
    model_name = binding.get("model")
    if not model_name or model_name not in env:
        raise ReportError("invalid_filter", "筛选业务模型无效。")
    allowed = _allowed_fields(env, model_name)
    domain = _safe_filter_value(env, binding.get("domain") or [], (list, tuple), "筛选条件")
    context = _safe_filter_value(env, binding.get("context") or {}, dict, "筛选上下文")
    sort = _safe_filter_value(env, binding.get("sort") or [], (list, tuple), "筛选排序")
    group_by = binding.get("group_by") or context.get("group_by") or []
    group_by = _normalize_group_by(group_by)
    sort = _normalize_sort(sort)
    domain_names = _domain_fields(domain)
    order_names = {_sort_field(item) for item in sort}
    group_names = {_field_name(item) for item in group_by}
    _validate_field_set(
        env, model_name, domain_names.union(order_names).union(group_names), allowed,
        code="filter_field_not_allowed",
    )
    return {
        "label": binding.get("label") or "筛选",
        "kind": binding.get("kind"),
        "model": model_name,
        "domain": list(domain),
        "context": {
            "active_test": context.get("active_test", True),
            "tz": env.user.tz or "UTC",
        },
        "group_by": group_by,
        "sort": sort,
        "allowed_fields": allowed,
    }


def _requested_fields(env, mode, request_item, binding):
    if mode == "describe":
        if set(request_item) != {"token"}:
            raise ReportError("invalid_report_request", "描述模式每个筛选只能提交 token。")
        return list(binding["allowed_fields"])
    if mode == "detail":
        if set(request_item) - {"token", "fields"}:
            raise ReportError("invalid_report_request", "明细模式不接受聚合参数。")
        fields_list = request_item.get("fields")
        if not isinstance(fields_list, list) or not 1 <= len(fields_list) <= MAX_DETAIL_FIELDS:
            raise ReportError("invalid_report_request", "明细报表必须选择 1 至 30 个字段。")
        if not all(isinstance(name, str) for name in fields_list):
            raise ReportError("invalid_report_request", "明细字段格式无效。")
        _validate_field_set(
            env, binding["model"], fields_list,
            binding["allowed_fields"],
        )
        return list(fields_list)
    if set(request_item) - {"token", "dimensions", "metrics"}:
        raise ReportError("invalid_report_request", "聚合模式不接受明细字段参数。")
    dimensions = request_item.get("dimensions")
    metrics = request_item.get("metrics")
    if not isinstance(dimensions, list) or len(dimensions) > MAX_DIMENSIONS:
        raise ReportError("invalid_report_request", "聚合维度最多 2 个。")
    if not isinstance(metrics, list) or not 1 <= len(metrics) <= MAX_METRICS:
        raise ReportError("invalid_report_request", "聚合指标必须为 1 至 5 个。")
    if not all(isinstance(name, str) for name in dimensions):
        raise ReportError("invalid_report_request", "聚合维度格式无效。")
    if len(set(dimensions)) != len(dimensions):
        raise ReportError("invalid_report_request", "聚合维度不能重复。")
    names = list(dimensions)
    metric_keys = set()
    for metric in metrics:
        if not isinstance(metric, dict) or set(metric) - {"field", "aggregation"}:
            raise ReportError("invalid_report_request", "聚合指标格式无效。")
        aggregation = metric.get("aggregation")
        field_name = metric.get("field")
        if aggregation not in AGGREGATIONS or not isinstance(field_name, str):
            raise ReportError("invalid_report_request", "聚合指标不受支持。")
        metric_key = (field_name, aggregation)
        if metric_key in metric_keys:
            raise ReportError("invalid_report_request", "聚合指标不能重复。")
        metric_keys.add(metric_key)
        names.append(field_name)
    _validate_field_set(
        env, binding["model"], names, binding["allowed_fields"],
    )
    model = env[binding["model"]]
    definitions = model.fields_get([_field_name(item) for item in dimensions])
    for dimension in dimensions:
        parts = dimension.split(":", 1)
        if len(parts) == 2 and (
                (definitions.get(parts[0]) or {}).get("type") not in DATE_FIELD_TYPES or
                parts[1] not in DATE_GRANULARITIES):
            raise ReportError("invalid_date_granularity", "日期维度粒度无效。")
    for metric in metrics:
        aggregation = metric["aggregation"]
        field_name = metric["field"]
        field = model._fields.get(field_name)
        if aggregation in ("sum", "avg") and field.type not in NUMERIC_FIELD_TYPES:
            raise ReportError(
                "invalid_aggregation", "字段 %s 不支持 %s。" % (field_name, aggregation),
            )
        if aggregation in ("min", "max") and field.type not in ORDERABLE_FIELD_TYPES:
            raise ReportError(
                "invalid_aggregation", "字段 %s 不支持 %s。" % (field_name, aggregation),
            )
    return names


def _binding_resolver(env, payload, context):
    mode = payload.get("mode")
    requests_list = payload.get("requests")
    if mode not in ("describe", "detail", "aggregate"):
        raise ReportError("invalid_report_request", "报表模式无效。")
    if not isinstance(requests_list, list) or not 1 <= len(requests_list) <= MAX_FILTERS:
        raise ReportError("invalid_report_request", "每次必须提供 1 至 5 个筛选。")
    selected = context.get("selectedMentionTokens")
    selected = selected if isinstance(selected, list) else []
    tokens = [item.get("token") for item in requests_list if isinstance(item, dict)]
    if (
        len(tokens) != len(requests_list) or len(set(tokens)) != len(tokens) or
        any(not isinstance(token, str) or token not in selected for token in tokens)
    ):
        raise ReportError("mention_not_selected", "报表筛选必须来自当前消息选择。")

    mention_tokens = env["agui.chat.mention.token"]
    session_key = env.context.get("agui_session_key") or ""
    bindings = []
    policy_bindings = []
    for request_item, token in zip(requests_list, tokens):
        bound = mention_tokens._load_token(token, "bound", session_key)
        if bound.resource_kind not in ("saved_filter", "current_filter") or bound.bound_action != "read":
            raise MentionTokenError("mention_action_mismatch", "报表命令只接受绑定为引用数据的筛选。")
        raw = mention_tokens._resolved_binding(
            token, bound.resource_kind, "read", session_key,
        )
        binding = _normalize_binding(env, raw)
        requested = _requested_fields(env, mode, request_item, binding)
        bindings.append(binding)
        policy_bindings.append({
            "model": binding["model"],
            "field_names": sorted(set(
                requested + list(_domain_fields(binding["domain"])) +
                [_sort_field(item) for item in binding["sort"]] +
                [_field_name(item) for item in binding["group_by"]]
            )),
        })
    return {
        "policy_bindings": policy_bindings,
        "handler_context": {"filter_bindings": bindings},
        "audit_details": {
            "filter_count": len(bindings),
            "models": sorted(set(item["model"] for item in bindings)),
            "mode": mode,
        },
    }


def _field_metadata(env, binding):
    definitions = env[binding["model"]].fields_get(binding["allowed_fields"])
    result = []
    for name in binding["allowed_fields"]:
        definition = definitions.get(name) or {}
        field_type = definition.get("type")
        aggregations = ["count"]
        if field_type in NUMERIC_FIELD_TYPES:
            aggregations.extend(["sum", "avg", "min", "max"])
        elif field_type in DATE_FIELD_TYPES:
            aggregations.extend(["min", "max"])
        result.append({
            "name": name,
            "label": definition.get("string") or name,
            "type": field_type,
            "aggregations": aggregations,
            "dateGranularities": sorted(DATE_GRANULARITIES) if field_type in DATE_FIELD_TYPES else [],
        })
    return result


def _order_clause(sort):
    return ", ".join(
        "%s %s" % _sort_parts(item) for item in sort
    )


def _json_value(value):
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    return value


def _currency_rules(env, binding, request_item):
    model = env[binding["model"]]
    dimension_fields = {_field_name(item) for item in request_item.get("dimensions") or []}
    currencies = []
    for metric in request_item.get("metrics") or []:
        field = model._fields[metric["field"]]
        if field.type != "monetary":
            continue
        currency_field = getattr(field, "currency_field", None) or "currency_id"
        if currency_field not in dimension_fields:
            raise ReportError(
                "currency_dimension_required",
                "金额字段 %s 必须按币种字段 %s 分组。" % (metric["field"], currency_field),
            )
        currencies.append({"field": metric["field"], "currencyField": currency_field})
    return currencies


def _aggregate(env, binding, request_item):
    model = env[binding["model"]].with_context(**binding["context"])
    dimensions = request_item.get("dimensions") or []
    definitions = model.fields_get([_field_name(item) for item in dimensions])
    for dimension in dimensions:
        parts = dimension.split(":", 1)
        definition = definitions.get(parts[0]) or {}
        if len(parts) == 2 and (
            definition.get("type") not in DATE_FIELD_TYPES or parts[1] not in DATE_GRANULARITIES
        ):
            raise ReportError("invalid_date_granularity", "日期维度粒度无效。")
    currency_rules = _currency_rules(env, binding, request_item)
    fields_list = [_field_name(item) for item in dimensions]
    metric_aliases = []
    for index, metric in enumerate(request_item.get("metrics") or []):
        field = model._fields[metric["field"]]
        aggregation = metric["aggregation"]
        if aggregation in ("sum", "avg") and field.type not in NUMERIC_FIELD_TYPES:
            raise ReportError("invalid_aggregation", "字段 %s 不支持 %s。" % (metric["field"], aggregation))
        if aggregation in ("min", "max") and field.type not in ORDERABLE_FIELD_TYPES:
            raise ReportError("invalid_aggregation", "字段 %s 不支持 %s。" % (metric["field"], aggregation))
        alias = "metric_%s" % index
        fields_list.append("%s:%s(%s)" % (alias, aggregation, metric["field"]))
        metric_aliases.append((alias, metric))
    groups = model.read_group(
        binding["domain"], fields_list, dimensions, limit=MAX_GROUPS + 1, lazy=False,
    )
    if len(groups) > MAX_GROUPS:
        raise ReportError("aggregation_too_large", "聚合结果超过 5000 组。")
    rows = []
    for group in groups:
        item = {}
        for dimension in dimensions:
            key = dimension if dimension in group else _field_name(dimension)
            item[dimension] = _json_value(group.get(key))
        for alias, metric in metric_aliases:
            item["%s:%s" % (metric["field"], metric["aggregation"])] = _json_value(
                group.get(alias)
            )
        rows.append(item)
    return rows, currency_rules


def _metadata(env, binding, mode, row_count, request_item, currency_rules, generated_at):
    return {
        "filterLabel": binding["label"],
        "model": binding["model"],
        "fields": request_item.get("fields") or sorted(set(
            [_field_name(item) for item in request_item.get("dimensions") or []] +
            [item["field"] for item in request_item.get("metrics") or []]
        )),
        "rowCount": row_count,
        "mode": mode,
        "dimensions": request_item.get("dimensions") or [],
        "metrics": request_item.get("metrics") or [],
        "originalGroupBy": binding["group_by"],
        "timezone": env.user.tz or "UTC",
        "currencyRules": currency_rules or [{"rule": "不做隐式汇率换算"}],
        "generatedAt": generated_at,
        "domainFingerprint": hashlib.sha256(
            canonical_json(binding["domain"]).encode("utf-8")
        ).hexdigest(),
    }


def _upload_files(env, thread_id, odoo_session, files_to_upload):
    config = env["agui.chat.config"].sudo().get_active_config()
    internal_url = config.internal_agentos_url()
    if not internal_url or not thread_id:
        raise ReportError("workspace_unavailable", "报表工作区不可用。")
    session = env["agui.chat.session"].search([
        ("thread_id", "=", thread_id), ("active", "=", True),
    ], limit=1)
    if not session:
        raise ReportError("workspace_unavailable", "报表对话已失效。")
    capability, _claims = issue_thread_capability(
        env, thread_id, odoo_session,
    )
    headers = {
        "X-AGUI-Capability": capability,
        "X-AGUI-Thread": thread_id,
    }
    uploaded = []
    try:
        for path, content, mime_type in files_to_upload:
            if len(content) > MAX_UPLOAD_BYTES:
                raise ReportError("report_file_too_large", "单个报表文件超过 10 MB。")
            response = requests.post(
                "%s/workspace/upload" % internal_url,
                data={"threadId": thread_id, "path": path},
                files={"file": (path.rsplit("/", 1)[-1], content, mime_type)},
                headers=headers,
                timeout=30,
            )
            response.raise_for_status()
            value = response.json()
            if not value.get("ok"):
                raise ReportError("workspace_upload_failed", "报表文件上传失败。")
            uploaded.append(path)
    except Exception as error:
        for path in reversed(uploaded):
            try:
                requests.delete(
                    "%s/workspace/file" % internal_url,
                    json={"threadId": thread_id, "path": path},
                    headers=headers,
                    timeout=10,
                )
            except Exception:
                pass
        if isinstance(error, ReportError):
            raise
        raise ReportError("workspace_upload_failed", "报表文件上传失败。")


def _handler(env, payload, handler_context):
    mode = payload["mode"]
    requests_list = payload["requests"]
    bindings = handler_context.get("filter_bindings") or []
    if len(bindings) != len(requests_list):
        raise ReportError("business_binding_invalid", "报表筛选绑定无效。")
    generated_at = fields.Datetime.to_string(fields.Datetime.now())
    if mode == "describe":
        reports = []
        for binding in bindings:
            model = env[binding["model"]].with_context(**binding["context"])
            reports.append({
                "filterLabel": binding["label"],
                "model": binding["model"],
                "rowCount": model.search_count(binding["domain"]),
                "fields": _field_metadata(env, binding),
                "originalGroupBy": binding["group_by"],
                "timezone": env.user.tz or "UTC",
                "currencyRule": "多币种金额必须按币种字段分组，不做隐式汇率换算",
                "generatedAt": generated_at,
            })
        return {"mode": mode, "reports": reports}

    files_to_upload = []
    reports = []
    for request_item, binding in zip(requests_list, bindings):
        model = env[binding["model"]].with_context(**binding["context"])
        currency_rules = []
        if mode == "detail":
            row_count = model.search_count(binding["domain"])
            if row_count > MAX_DETAIL_ROWS:
                raise ReportError(
                    "aggregation_required",
                    "筛选“%s”超过 5000 行，必须改用聚合模式。" % binding["label"],
                )
            records = model.search(
                binding["domain"], order=_order_clause(binding["sort"]),
                limit=MAX_DETAIL_ROWS + 1,
            )
            if len(records) > MAX_DETAIL_ROWS:
                raise ReportError(
                    "aggregation_required",
                    "筛选“%s”超过 5000 行，必须改用聚合模式。" % binding["label"],
                )
            row_count = len(records)
            rows = [
                {name: _json_value(row.get(name)) for name in request_item["fields"]}
                for row in records.read(request_item["fields"])
            ]
        else:
            rows, currency_rules = _aggregate(env, binding, request_item)
            row_count = len(rows)
        identifier = str(uuid.uuid4())
        data_path = "reports/data/%s.jsonl" % identifier
        meta_path = "reports/data/%s.meta.json" % identifier
        data = b"\n".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            for row in rows
        )
        if data:
            data += b"\n"
        metadata = _metadata(
            env, binding, mode, row_count, request_item, currency_rules, generated_at,
        )
        meta = json.dumps(
            metadata, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
        ).encode("utf-8")
        files_to_upload.extend([
            (data_path, data, "application/x-ndjson"),
            (meta_path, meta, "application/json"),
        ])
        reports.append({
            "filterLabel": binding["label"],
            "model": binding["model"],
            "rowCount": row_count,
            "mode": mode,
            "dataPath": data_path,
            "metadataPath": meta_path,
            "timezone": env.user.tz or "UTC",
            "currencyRules": metadata["currencyRules"],
            "generatedAt": generated_at,
        })
    _upload_files(
        env, handler_context.get("thread_id"), handler_context.get("odoo_session"),
        files_to_upload,
    )
    return {"mode": mode, "reports": reports}


REPORT_SCHEMA = {
    "type": "object",
    "required": ["mode", "requests"],
    "additionalProperties": False,
    "properties": {
        "mode": {"type": "string", "enum": ["describe", "detail", "aggregate"]},
        "requests": {
            "type": "array", "minItems": 1, "maxItems": MAX_FILTERS,
            "items": {
                "type": "object", "required": ["token"], "additionalProperties": False,
                "properties": {
                    "token": {"type": "string", "minLength": 1, "maxLength": 160},
                    "fields": {
                        "type": "array", "maxItems": MAX_DETAIL_FIELDS,
                        "items": {"type": "string", "minLength": 1, "maxLength": 128},
                    },
                    "dimensions": {
                        "type": "array", "maxItems": MAX_DIMENSIONS,
                        "items": {"type": "string", "minLength": 1, "maxLength": 140},
                    },
                    "metrics": {
                        "type": "array", "maxItems": MAX_METRICS,
                        "items": {
                            "type": "object", "required": ["field", "aggregation"],
                            "additionalProperties": False,
                            "properties": {
                                "field": {"type": "string", "minLength": 1, "maxLength": 128},
                                "aggregation": {"type": "string", "enum": sorted(AGGREGATIONS)},
                            },
                        },
                    },
                },
            },
        },
    },
}


register_business_command(
    COMMAND_NAME,
    REPORT_SCHEMA,
    _handler,
    description="批量描述、导出或聚合当前消息明确引用的 Odoo 筛选数据。",
    access_level="read",
    binding_resolver=_binding_resolver,
)
