"""Reporting Runtime 的 Daytona CLI 入口。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .runtime import ReportRuntime
from .validation import ReportFailure

MAX_RESULT_BYTES = 64 * 1024


def main(arguments: list[str] | None = None) -> int:
    values = arguments if arguments is not None else sys.argv[1:]
    try:
        if len(values) != 2:
            raise ReportFailure("报表渲染参数无效")
        action, payload_text = values
        payload = json.loads(payload_text)
        runtime = ReportRuntime(Path.cwd())
        if action == "render_markdown":
            result = runtime.render_markdown(
                payload["job"],
                payload["markdown_path"],
                payload["output_path"],
                payload["temporary_path"],
                payload.get("page_layout"),
                payload.get("word_output_path"),
                payload.get("html_output_path"),
            )
        elif action == "validate_pdf":
            result = runtime.validate_pdf(
                payload["job"],
                payload["pdf_path"],
                payload["temporary_directory"],
                payload.get("artifact_manifest"),
                payload.get("word_path"),
            )
        else:
            raise ReportFailure("未知报表操作")
        encoded = json.dumps(result, ensure_ascii=False)
        if len(encoded.encode()) + 1 > MAX_RESULT_BYTES:
            raise ReportFailure("报表结果超过返回边界")
        print(encoded)
        return 0
    except (KeyError, TypeError, json.JSONDecodeError, ReportFailure) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        return 1
    except Exception:
        print(json.dumps({"error": "报表运行时执行失败"}, ensure_ascii=False))
        return 1


__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main())
