"""使用原生 Responses API 复测冻结规划输入，不回退 Chat Completions。"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from loguru import logger
from openai import AsyncOpenAI
from openai.lib._pydantic import to_strict_json_schema

from scripts.benchmark_planner_input import (
    COMPREHENSION_PROMPT, Comprehension, _runtime, build_variants, json_text, validate_plan,
)
from smart_reporting.reporting.workflow.runtime.models import AnalysisBundle
from smart_reporting.runtime.settings import AgentSettings


async def main() -> None:
    os.environ["AGENT_ENV_FILE"] = ".env"
    settings = AgentSettings.from_environment()
    baseline = json.loads(Path(sys.argv[1]).read_text())
    target = Path(sys.argv[2])
    target.mkdir(parents=True, exist_ok=False)
    logger.add(target / "benchmark.log")
    variants = build_variants(baseline)
    instructions = _runtime(settings)._analysis_agent.instructions
    semaphore = asyncio.Semaphore(3)
    client = AsyncOpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url,
                         max_retries=0, timeout=300)
    def write(name, value):
        (target / name).write_text(json.dumps(value, ensure_ascii=False, indent=2))
    write("manifest.json", {"api": "responses.create", "model": settings.model_standard_id,
          "inputSha256": hashlib.sha256(json_text(baseline).encode()).hexdigest(),
          "reasoning": {"effort": "high"}, "repetitions": 3,
          "format": "json_object",
          "note": "端点拒绝json_schema；使用JSON模式并在本地校验Schema；无Chat回退，无模型评审"})

    async def call(variant, repetition, kind):
        payload = variants[variant]
        schema = AnalysisBundle if kind == "plan" else Comprehension
        label = f"{kind}-{repetition}-{variant}"
        prompt = "\n".join(instructions) if kind == "plan" else COMPREHENSION_PROMPT
        prompt += "\n只输出符合以下JSON Schema的JSON对象：\n" + json_text(to_strict_json_schema(schema))
        result = {"label": label, "variant": variant, "kind": kind,
                  "repetition": repetition, "output": None, "error": None}
        async with semaphore:
            started = perf_counter()
            logger.info("responses_started label={}", label)
            try:
                response = await client.responses.create(
                    model=settings.model_standard_id,
                    instructions=prompt,
                    input=json_text(payload),
                    reasoning={"effort": "high"},
                    temperature=1.0, top_p=1.0, max_output_tokens=16384,
                    text={"format": {"type": "json_object"}},
                )
                result.update(responseId=response.id, status=response.status,
                              usage=response.usage.model_dump() if response.usage else None,
                              incompleteDetails=response.incomplete_details.model_dump()
                              if response.incomplete_details else None,
                              rawText=response.output_text)
                output = schema.model_validate_json(response.output_text)
                result["output"] = output.model_dump(mode="json", by_alias=True)
                if kind == "plan":
                    result["validation"] = validate_plan(result["output"], baseline)
                else:
                    result["scopeRecognized"] = "开单收入" in output.incomeScope
            except Exception as error:
                result["error"] = {"type": type(error).__name__, "message": str(error)[:2000]}
            result["seconds"] = round(perf_counter() - started, 3)
            write(label + ".json", result)
            logger.info("responses_finished label={} seconds={} error={}",
                        label, result["seconds"], result["error"])
            return result

    runs = []
    try:
        # 先真实探针，失败时停止，不重复发送其余同协议请求。
        probe = await call("baseline", 1, "comprehension")
        runs.append(probe)
        if probe["error"]:
            write("results.json", {"runs": runs, "blocked": True})
            return
        for repetition in range(1, 4):
            names = ["baseline", "conservative_focus"]
            if repetition % 2 == 0:
                names.reverse()
            jobs = [(name, kind) for name in names for kind in ("plan", "comprehension")
                    if not (repetition == 1 and name == "baseline" and kind == "comprehension")]
            runs.extend(await asyncio.gather(*(call(name, repetition, kind) for name, kind in jobs)))
            write("results.json", {"runs": runs, "blocked": False})
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
