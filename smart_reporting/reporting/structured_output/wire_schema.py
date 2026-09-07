"""Reporting 结构化输出的 provider wire schema 适配。"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from typing import Any

from agno.utils.json_schema import inline_pydantic_schema
from pydantic import BaseModel

REPORTING_WIRE_SCHEMA_MODEL_ATTR = "_reporting_wire_schema"
REPORTING_WIRE_DECODER_MODEL_ATTR = "_reporting_wire_decoder"
REPORTING_WIRE_DOMAIN_SCHEMA_MODEL_ATTR = "_reporting_wire_domain_schema"
REPORTING_WIRE_DIALECT_MODEL_ATTR = "_reporting_wire_dialect"
REPORTING_WIRE_FINGERPRINT_MODEL_ATTR = "_reporting_wire_fingerprint"

_ROOT_UNION_DISCRIMINATOR = "kind"
_SCALAR_JSON_SCHEMA = {
    "anyOf": [
        {"type": "string"},
        {"type": "number"},
        {"type": "boolean"},
        {"type": "null"},
    ]
}


class StructuredOutputSchemaDialect(StrEnum):
    """当前模型端点接受的 JSON Schema 方言。"""

    NATIVE = "native"
    INLINE_STRICT = "inline_strict"


@dataclass(frozen=True, slots=True)
class StructuredOutputWireContract:
    """领域 Schema 对应的单次 provider 传输契约。"""

    dialect: StructuredOutputSchemaDialect
    domain_fingerprint: str
    wire_fingerprint: str
    cache_key: str
    schema: dict[str, Any] | None = None
    map_paths: tuple[tuple[str, ...], ...] = ()
    json_map_paths: tuple[tuple[str, ...], ...] = ()
    union_fields: dict[str, frozenset[str]] | None = None
    instruction: str | None = None

    def decode(self, content: Any) -> Any:
        """把 provider DTO 恢复成领域模型接收的 JSON 形状。"""

        if self.dialect is StructuredOutputSchemaDialect.NATIVE:
            return content
        candidate = _json_candidate(content)
        if candidate is None:
            return content
        if isinstance(candidate, dict) and self.union_fields is not None:
            candidate = _unwrap_root_union_dto(candidate, self.union_fields)
            kind = candidate.get(_ROOT_UNION_DISCRIMINATOR)
            allowed = self.union_fields.get(kind) if isinstance(kind, str) else None
            if allowed is not None:
                transport_fields = frozenset().union(*self.union_fields.values())
                # strict wire 为保持根对象且要求全部 properties 必填，会同时携带
                # 其他联合分支的字段；kind 是唯一分支事实，因此这些字段只是传输
                # padding，必须在领域校验前移除。非联合字段不能在此静默丢弃，仍交
                # 给原始 Pydantic 模型按 extra=forbid 失败关闭。
                candidate = {
                    key: value
                    for key, value in candidate.items()
                    if key in allowed or key not in transport_fields
                }
        for path in self.map_paths:
            candidate = _decode_map_path(candidate, path)
        for path in self.json_map_paths:
            candidate = _decode_json_map_path(candidate, path)
        return candidate


def _unwrap_root_union_dto(
    candidate: dict[str, Any],
    union_fields: dict[str, frozenset[str]],
) -> dict[str, Any]:
    """只展开能唯一、完整匹配一个联合分支的单键传输包装。"""

    declared_kind = candidate.get(_ROOT_UNION_DISCRIMINATOR)
    wrapper_items = [
        (key, value) for key, value in candidate.items() if key != _ROOT_UNION_DISCRIMINATOR
    ]
    if len(wrapper_items) != 1 or not isinstance(wrapper_items[0][1], dict):
        return candidate
    _, payload = wrapper_items[0]
    payload_fields = frozenset(payload)
    matching_kinds = [
        kind
        for kind, fields in union_fields.items()
        if payload_fields == fields - {_ROOT_UNION_DISCRIMINATOR}
    ]
    if isinstance(declared_kind, str):
        if declared_kind not in matching_kinds:
            return candidate
        kind = declared_kind
    elif len(matching_kinds) == 1:
        kind = matching_kinds[0]
    else:
        return candidate
    # 包装名不是业务事实，只有 payload 的完整字段集合和可选显式 kind 共同决定
    # 分支；任何缺字段、额外字段或歧义都保持原值，由领域 Pydantic 失败关闭。
    return {_ROOT_UNION_DISCRIMINATOR: kind, **payload}


class StructuredOutputWireSchemaResolver:
    """按 endpoint、模型和领域 Schema 指纹选择稳定的传输方言。"""

    def resolve(
        self,
        schema: Any,
        *,
        model_id: str,
        endpoint: str | None,
    ) -> StructuredOutputWireContract:
        domain_schema = _domain_schema(schema)
        domain_fingerprint = _schema_fingerprint(domain_schema)
        dialect = (
            StructuredOutputSchemaDialect.INLINE_STRICT
            if _is_qwen_model(model_id)
            else StructuredOutputSchemaDialect.NATIVE
        )
        endpoint_fingerprint = sha256((endpoint or "").encode()).hexdigest()[:12]
        if dialect is StructuredOutputSchemaDialect.NATIVE:
            cache_key = ":".join(
                (
                    endpoint_fingerprint,
                    model_id.casefold(),
                    domain_fingerprint,
                    domain_fingerprint,
                    dialect.value,
                )
            )
            return StructuredOutputWireContract(
                dialect=dialect,
                domain_fingerprint=domain_fingerprint,
                wire_fingerprint=domain_fingerprint,
                cache_key=cache_key,
            )

        inlined = inline_pydantic_schema(deepcopy(domain_schema))
        map_paths: set[tuple[str, ...]] = set()
        json_map_paths: set[tuple[str, ...]] = set()
        normalized = _normalize_inline_strict_schema(
            inlined,
            (),
            map_paths,
            json_map_paths,
        )
        normalized, union_fields = _flatten_root_discriminated_union(normalized)
        _assert_inline_strict_schema(normalized)
        wire_fingerprint = _schema_fingerprint(normalized)
        cache_key = ":".join(
            (
                endpoint_fingerprint,
                model_id.casefold(),
                domain_fingerprint,
                wire_fingerprint,
                dialect.value,
            )
        )
        instructions: list[str] = []
        field_names = sorted({path[-1] for path in map_paths if path})
        if field_names:
            instructions.append(
                "当前端点的严格传输契约把对象映射字段 "
                + "、".join(field_names)
                + ' 表示为 [{"key":"字段名","value":"字段值"}]；空映射返回 []。'
            )
        json_field_names = sorted({path[-1] for path in json_map_paths if path})
        if json_field_names:
            instructions.append(
                "任意 JSON 映射字段 "
                + "、".join(json_field_names)
                + ' 表示为 [{"key":"字段名","valueJson":"合法 JSON 字符串"}]；'
                "valueJson 必须包含该值的完整 JSON 编码，空映射返回 []。"
            )
        return StructuredOutputWireContract(
            dialect=dialect,
            domain_fingerprint=domain_fingerprint,
            wire_fingerprint=wire_fingerprint,
            cache_key=cache_key,
            schema=normalized,
            map_paths=tuple(sorted(map_paths)),
            json_map_paths=tuple(sorted(json_map_paths)),
            union_fields=union_fields,
            instruction="\n".join(instructions) or None,
        )


def _domain_schema(schema: Any) -> dict[str, Any]:
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        # Agno 的 OpenAI provider 归一化会把 dict[str, Any] 提前收窄为
        # additionalProperties=false，使 wire adapter 无法再识别开放映射。
        # 领域指纹和 Qwen DTO 必须以原始 Pydantic Schema 为事实来源；native
        # 请求仍由 Agno 在真正发起调用时执行其 provider 归一化。
        return schema.model_json_schema()
    if isinstance(schema, dict):
        return deepcopy(schema)
    adapter = getattr(schema, "model_json_schema", None)
    return adapter() if callable(adapter) else {}


def _schema_fingerprint(schema: dict[str, Any]) -> str:
    encoded = json.dumps(
        schema,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    return sha256(encoded).hexdigest()[:16]


def _is_qwen_model(model_id: str) -> bool:
    normalized = model_id.strip().casefold()
    return any(part.startswith("qwen") for part in re.split(r"[/\\:_-]+", normalized))


def _normalize_inline_strict_schema(
    value: Any,
    path: tuple[str, ...],
    map_paths: set[tuple[str, ...]],
    json_map_paths: set[tuple[str, ...]],
) -> Any:
    if isinstance(value, list):
        return [
            _normalize_inline_strict_schema(item, path, map_paths, json_map_paths) for item in value
        ]
    if not isinstance(value, dict):
        return value

    current = {
        key: deepcopy(item) for key, item in value.items() if key not in {"default", "title"}
    }
    current.pop("discriminator", None)
    properties = current.get("properties")
    additional = current.get("additionalProperties")
    if (
        current.get("type") == "object"
        and not properties
        and (isinstance(additional, dict) or additional is True)
    ):
        arbitrary_json = additional is True or additional == {}
        (json_map_paths if arbitrary_json else map_paths).add(path)
        value_properties = (
            {
                "valueJson": {
                    "type": "string",
                    "minLength": 1,
                    "description": "映射值的完整合法 JSON 编码。",
                }
            }
            if arbitrary_json
            else {
                "value": _normalize_inline_strict_schema(
                    additional,
                    (*path, "*"),
                    map_paths,
                    json_map_paths,
                )
            }
        )
        entry = {
            "type": "object",
            "properties": {
                "key": {"type": "string", "minLength": 1},
                **value_properties,
            },
            "required": ["key", *value_properties],
            "additionalProperties": False,
        }
        mapped: dict[str, Any] = {"type": "array", "items": entry}
        if isinstance(current.get("minProperties"), int):
            mapped["minItems"] = current["minProperties"]
        if isinstance(current.get("maxProperties"), int):
            mapped["maxItems"] = current["maxProperties"]
        if isinstance(current.get("description"), str):
            mapped["description"] = current["description"]
        return mapped

    if isinstance(properties, dict):
        current["properties"] = {
            name: _normalize_inline_strict_schema(
                item,
                (*path, name),
                map_paths,
                json_map_paths,
            )
            for name, item in properties.items()
        }
        current["required"] = list(current["properties"])
        current["additionalProperties"] = False
    elif current.get("type") == "object":
        current["additionalProperties"] = False

    if "items" in current:
        current["items"] = _normalize_inline_strict_schema(
            current["items"],
            (*path, "*"),
            map_paths,
            json_map_paths,
        )
    for keyword in ("anyOf", "allOf", "oneOf"):
        if isinstance(current.get(keyword), list):
            current[keyword] = [
                _normalize_inline_strict_schema(item, path, map_paths, json_map_paths)
                for item in current[keyword]
            ]
    if not any(key in current for key in ("type", "anyOf", "allOf", "oneOf", "const", "enum")):
        description = current.get("description")
        current = deepcopy(_SCALAR_JSON_SCHEMA)
        if isinstance(description, str):
            current["description"] = description
    return current


def _flatten_root_discriminated_union(
    schema: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, frozenset[str]] | None]:
    branches = schema.get("oneOf")
    if not isinstance(branches, list) or not branches:
        return schema, None
    if not all(
        isinstance(branch, dict) and isinstance(branch.get("properties"), dict)
        for branch in branches
    ):
        return schema, None

    union_fields: dict[str, frozenset[str]] = {}
    property_variants: dict[str, list[dict[str, Any]]] = {}
    branch_count = len(branches)
    for branch in branches:
        properties = branch["properties"]
        kind_schema = properties.get(_ROOT_UNION_DISCRIMINATOR)
        kind = kind_schema.get("const") if isinstance(kind_schema, dict) else None
        if not isinstance(kind, str):
            return schema, None
        union_fields[kind] = frozenset(properties)
        for name, property_schema in properties.items():
            property_variants.setdefault(name, []).append(property_schema)

    merged: dict[str, Any] = {}
    for name, variants in property_variants.items():
        if name == _ROOT_UNION_DISCRIMINATOR:
            merged[name] = {"type": "string", "enum": list(union_fields)}
            continue
        unique = _unique_schemas(variants)
        if len(variants) < branch_count:
            unique.append({"type": "null"})
        merged[name] = unique[0] if len(unique) == 1 else {"anyOf": unique}
    return (
        {
            "type": "object",
            "properties": merged,
            "required": list(merged),
            "additionalProperties": False,
        },
        union_fields,
    )


def _unique_schemas(schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for schema in schemas:
        fingerprint = json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if fingerprint not in seen:
            seen.add(fingerprint)
            unique.append(schema)
    return unique


def _assert_inline_strict_schema(schema: dict[str, Any]) -> None:
    """在发起模型调用前验证 Qwen 端点已验证过的 strict 子集。"""

    if schema.get("type") != "object" or not isinstance(schema.get("properties"), dict):
        raise ValueError("Reporting inline strict wire schema 根节点必须是对象")
    pending: list[tuple[str, Any]] = [("$", schema)]
    while pending:
        path, value = pending.pop()
        if isinstance(value, list):
            pending.extend((f"{path}[{index}]", item) for index, item in enumerate(value))
            continue
        if not isinstance(value, dict):
            continue
        forbidden = {"$defs", "$ref", "default", "oneOf", "allOf"}.intersection(value)
        if forbidden:
            raise ValueError(
                f"Reporting inline strict wire schema {path} 包含不支持的关键字："
                + ",".join(sorted(forbidden))
            )
        properties = value.get("properties")
        if value.get("type") == "object":
            if value.get("additionalProperties") is not False:
                raise ValueError(f"Reporting inline strict wire schema {path} 必须拒绝额外字段")
            if isinstance(properties, dict) and set(value.get("required", [])) != set(properties):
                raise ValueError(
                    f"Reporting inline strict wire schema {path} 必须声明全部字段为 required"
                )
        pending.extend((f"{path}.{key}", item) for key, item in value.items())


def _json_candidate(content: Any) -> Any | None:
    if isinstance(content, str):
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return None
    return deepcopy(content) if isinstance(content, dict | list) else None


def _decode_map_path(value: Any, path: tuple[str, ...]) -> Any:
    if not path:
        if not isinstance(value, list):
            return value
        decoded: dict[str, Any] = {}
        for item in value:
            if not isinstance(item, dict) or set(item) != {"key", "value"}:
                return value
            key = item.get("key")
            if not isinstance(key, str) or key in decoded:
                return value
            decoded[key] = item.get("value")
        return decoded
    head, *tail = path
    if head == "*":
        if isinstance(value, list):
            return [_decode_map_path(item, tuple(tail)) for item in value]
        return value
    if isinstance(value, dict) and head in value:
        updated = dict(value)
        updated[head] = _decode_map_path(updated[head], tuple(tail))
        return updated
    return value


def _decode_json_map_path(value: Any, path: tuple[str, ...]) -> Any:
    if not path:
        if not isinstance(value, list):
            return value
        decoded: dict[str, Any] = {}
        for item in value:
            if not isinstance(item, dict) or set(item) != {"key", "valueJson"}:
                return value
            key = item.get("key")
            encoded = item.get("valueJson")
            if not isinstance(key, str) or key in decoded or not isinstance(encoded, str):
                return value
            try:
                decoded[key] = json.loads(encoded)
            except json.JSONDecodeError:
                return value
        return decoded
    head, *tail = path
    if head == "*":
        if isinstance(value, list):
            return [_decode_json_map_path(item, tuple(tail)) for item in value]
        return value
    if isinstance(value, dict) and head in value:
        updated = dict(value)
        updated[head] = _decode_json_map_path(updated[head], tuple(tail))
        return updated
    return value


__all__ = [
    "REPORTING_WIRE_DECODER_MODEL_ATTR",
    "REPORTING_WIRE_DIALECT_MODEL_ATTR",
    "REPORTING_WIRE_DOMAIN_SCHEMA_MODEL_ATTR",
    "REPORTING_WIRE_FINGERPRINT_MODEL_ATTR",
    "REPORTING_WIRE_SCHEMA_MODEL_ATTR",
    "StructuredOutputSchemaDialect",
    "StructuredOutputWireContract",
    "StructuredOutputWireSchemaResolver",
]
