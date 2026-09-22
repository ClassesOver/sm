"""真实 Responses reasoning 回放探针；仅返回固定算术结果，不执行模型代码。"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
MODELS = ("deepseek-v4-flash-0731", "qwen3.8-flash")
TOOL = {
    "type": "custom",
    "name": "run",
    "description": "Return the result of the fixed arithmetic expression. Input must be exactly 17 * 23, without quotes, print(), JSON or Markdown.",
    "format": {
        "type": "grammar",
        "syntax": "lark",
        "definition": 'start: "17 * 23"',
    },
}


def _shape(items: list[dict[str, Any]]) -> dict[str, Any]:
    reasoning = [item for item in items if item.get("type") == "reasoning"]
    return {
        "types": [item.get("type", item.get("role")) for item in items],
        "custom_calls": [
            {
                "name_matches": item.get("name") == "run",
                "has_call_id": bool(item.get("call_id")),
                "arithmetic_input": item.get("input")
                if re.fullmatch(r"[0-9\s*+]{1,100}", item.get("input", ""))
                else "not_an_allowed_arithmetic_string",
                "input_chars": len(item.get("input", "")),
            }
            for item in items if item.get("type") == "custom_tool_call"
        ],
        "reasoning": [
            {
                "keys": sorted(item),
                "summary_chars": sum(len(part.get("text", "")) for part in item.get("summary", [])),
                "encrypted_content_present": "encrypted_content" in item,
                "encrypted_content_chars": len(item.get("encrypted_content") or ""),
            }
            for item in reasoning
        ],
    }


def _text(items: list[dict[str, Any]]) -> str:
    return "".join(
        part.get("text", "")
        for item in items
        if item.get("type") == "message"
        for part in item.get("content", [])
    ).strip()


def _tool_output(items: list[dict[str, Any]], expected: str, value: str) -> list[dict[str, str]]:
    calls = [item for item in items if item.get("type", "").endswith("tool_call")]
    # 本探针要求每步一条特定调用；不是生产协议对多调用的限制。
    if len(calls) != 1:
        raise ValueError("unexpected_tool_call_count")
    call = calls[0]
    if (
        call.get("type") != "custom_tool_call"
        or call.get("name") != "run"
        or call.get("input", "").strip() != expected
        or not isinstance(call.get("call_id"), str)
        or not call["call_id"]
    ):
        raise ValueError("unexpected_tool_call_identity_or_input")
    return [{"type": "custom_tool_call_output", "call_id": call["call_id"], "output": value}]


async def _probe(model: str, config: dict[str, Any], timeout: int) -> dict[str, Any]:
    endpoint = config["OPENAI_BASE_URL"].rstrip("/") + "/responses"
    report: dict[str, Any] = {"model": model, "host": urlsplit(endpoint).hostname, "rounds": [], "passed": False}
    base = {
        "model": model,
        "store": False,
        "include": ["reasoning.encrypted_content"],
        "reasoning": {"effort": "high", "summary": "auto"},
        "max_output_tokens": 2048,
        # 允许 provider 返回多个结构化调用；探针仍校验每个阶段的调用身份。
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [TOOL],
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        async def request(label: str, history: list[dict[str, Any]], **overrides: Any) -> list[dict[str, Any]]:
            payload = {**base, "input": history, **overrides}
            evidence: dict[str, Any] = {
                "stage": label,
                "store": payload["store"],
                "include": payload["include"],
                "input": _shape(history),
            }
            report["rounds"].append(evidence)
            response = await client.post(
                endpoint, headers={"Authorization": "Bearer " + config["OPENAI_API_KEY"]}, json=payload
            )
            evidence["http_status"] = response.status_code
            if response.status_code != 200:
                # 只记录固定错误字段，不回显可能包含请求内容的 provider message。
                try:
                    error = response.json().get("error", {})
                    evidence["provider_error"] = {key: error.get(key) for key in ("type", "code", "param")}
                except (ValueError, AttributeError):
                    evidence["provider_error"] = "non_json_or_unexpected_error"
                raise ValueError("provider_http_error")
            body = response.json()
            output = body.get("output", [])
            evidence["response_status"] = body.get("status")
            evidence["output"] = _shape(output)
            usage = body.get("usage") or {}
            evidence["usage"] = {key: usage.get(key) for key in ("input_tokens", "output_tokens", "total_tokens")}
            if body.get("status") != "completed":
                raise ValueError("response_not_completed")
            return output

        try:
            first_prompt = {"role": "user", "content": "Call run exactly once with 17 * 23. Wait for its result."}
            first = await request("first_custom_call", [first_prompt])
            first_result = _tool_output(first, "17 * 23", "391")
            second_prompt = {"role": "user", "content": "The first calculation is complete. Verify it by calling run exactly once again with the raw input 17 * 23 (no quotes, no print function, no Markdown). Wait for its result."}
            second = await request("raw_reasoning_replay", [first_prompt, *first, *first_result, second_prompt])
            second_result = _tool_output(second, "17 * 23", "391")
            report["pruned_complete_rounds"] = 1
            # 删除第一轮完整 reasoning/call/output 组，保留第二轮原始项和匹配回执。
            state = {"role": "user", "content": "Prior completed calculation: 17 * 23 = 391. The verification call is now complete. Reply with only its result number. Do not call another tool."}
            final = await request("replay_after_complete_round_pruning", [state, *second, *second_result])
            report["final_matches_391"] = _text(final) == "391"
            report["final_has_reasoning"] = any(item.get("type") == "reasoning" for item in final)
            if any(item.get("type", "").endswith("tool_call") for item in final):
                raise ValueError("unexpected_final_tool_call")
            plain = await request(
                "final_without_reasoning",
                [{"role": "user", "content": "Reply with only the number 391. Do not explain."}],
                # DashScope Responses 省略 reasoning 会使用 provider 默认思考；
                # 标准关闭方式是显式 effort=none，enable_thinking=false 单独无效。
                reasoning={"effort": "none"},
                tools=[],
                tool_choice="none",
            )
            report["plain_final_matches_391"] = _text(plain) == "391"
            report["plain_final_has_reasoning"] = any(item.get("type") == "reasoning" for item in plain)
            report["reasoning_replayed"] = all(any(item.get("type") == "reasoning" for item in items) for items in (first, second))
            report["passed"] = (
                report["reasoning_replayed"]
                and report["final_matches_391"]
                and report["plain_final_matches_391"]
                and not report["plain_final_has_reasoning"]
            )
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            report["exception_type"] = type(exc).__name__
            if isinstance(exc, ValueError) and str(exc) in {
                "unexpected_tool_call_count", "unexpected_tool_call_identity_or_input", "provider_http_error",
                "response_not_completed", "unexpected_final_tool_call",
            }:
                report["failure"] = str(exc)
    return report


async def _run(args: argparse.Namespace) -> int:
    config = {**dotenv_values(args.env_file), **os.environ}
    if not all(config.get(key) for key in ("OPENAI_BASE_URL", "OPENAI_API_KEY")):
        raise SystemExit("需要 OPENAI_BASE_URL 和 OPENAI_API_KEY；不会输出凭据。")
    evidence = {
        "created_at": datetime.now(UTC).isoformat(),
        "scope": "live_provider_wire_only; no generated code execution; no encrypted payloads saved",
        "models": [],
    }
    for model in args.model or MODELS:
        report = await _probe(model, config, args.timeout)
        evidence["models"].append(report)
        print(json.dumps(report, ensure_ascii=False), flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if all(report["passed"] for report in evidence["models"]) else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--model", action="append", help="可重复；默认探测 DeepSeek 和 Qwen")
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--output", type=Path, default=Path("/tmp/reporting-reasoning-replay.json"))
    args = parser.parse_args()
    if not 1 <= args.timeout <= 300:
        parser.error("--timeout 必须在 1 到 300 之间")
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
