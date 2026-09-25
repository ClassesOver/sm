"""edit_script 原生兼容 Codex apply_patch 与混合信封，并统计输入格式分布。"""

import hashlib

import pytest
from lark import Lark, UnexpectedInput

from smart_reporting.reporting.code_agent.edit_patch import (
    EDIT_PATCH_GRAMMAR,
    apply_edit_blocks,
    parse_script_patch,
)
from smart_reporting.reporting.code_agent.metrics import build_coding_metric_sample
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_reporting_code_draft import (
    REJECTED_SOURCE,
    _rejected,
    _toolkit,
)
from smart_reporting.reporting.tests.test_reporting_code_edit import (
    script,  # noqa: F401
)
from smart_reporting.reporting.tests.test_reporting_code_input import (
    anyio_backend,  # noqa: F401
    binding,  # noqa: F401
    toolkit,  # noqa: F401
    workspace,  # noqa: F401
)
from smart_reporting.reporting.tests.test_reporting_interactive_code_agent import (
    runtime,  # noqa: F401
)

SHA = "a" * 64


def _apply_patch(path: str, hunks: str, *, sha: str | None = None) -> str:
    sha_line = f"*** SHA256: {sha}\n" if sha else ""
    return f"*** Begin Patch\n{sha_line}*** Update File: {path}\n{hunks}*** End Patch\n"


@pytest.mark.parametrize(
    "patch",
    [
        _apply_patch("analysis/a.py", "@@ def main():\n     value = 1\n-    print(value)\n+    print(2)\n"),
        _apply_patch("a.py", "@@\n x\n-y\n+z\n", sha=SHA),
        f"*** Begin Edit\n*** SHA256: {SHA}\n- value = 1\n+ value = 2\n*** End Edit\n",
    ],
    ids=["apply-patch", "apply-patch-sha", "mixed-envelope"],
)
def test_wire_grammar_accepts_apply_patch_forms(patch: str) -> None:
    Lark(EDIT_PATCH_GRAMMAR).parse(patch)


@pytest.mark.parametrize(
    "patch",
    [
        "*** Begin Patch\n*** Add File: b.py\n+x\n*** End Patch\n",
        _apply_patch("a.py", " x\n-y\n") + "解释",
    ],
    ids=["add-file", "trailing-text"],
)
def test_wire_grammar_rejects_unsupported_apply_patch(patch: str) -> None:
    with pytest.raises(UnexpectedInput):
        Lark(EDIT_PATCH_GRAMMAR).parse(patch)


def test_apply_patch_hunks_convert_to_search_replace() -> None:
    source = "import json\n\ndef main():\n    value = 1\n    print(value)\n\nmain()\n"
    parsed = parse_script_patch(
        _apply_patch(
            "analysis/a.py",
            "@@ def main():\n     value = 1\n-    print(value)\n+    print(value * 2)\n"
            "@@\n \n-main()\n+if __name__ == '__main__':\n+    main()\n",
        ),
        64 * 1024,
    )

    assert parsed.patch_format == "apply_patch"
    assert parsed.sha256 is None
    assert parsed.path == "analysis/a.py"
    updated, _ = apply_edit_blocks(source, parsed.edits)
    assert updated == (
        "import json\n\ndef main():\n    value = 1\n    print(value * 2)\n\n"
        "if __name__ == '__main__':\n    main()\n"
    )


def test_mixed_envelope_with_update_file_hunks_is_parsed() -> None:
    # candidate-19/27/28 观测形态：Begin Edit 信封内写 apply_patch 差异，- / + 后多一个空格。
    parsed = parse_script_patch(
        f"*** Begin Edit\n*** SHA256: {SHA}\n*** Update File: charts.py\n"
        "- value = 1\n+ value = 2\n*** End Edit\n",
        64 * 1024,
    )

    assert parsed.patch_format == "edit_envelope_hunks"
    assert parsed.sha256 == SHA
    updated, fuzzy = apply_edit_blocks("import os\nvalue = 1\nprint(value)\n", parsed.edits)
    assert updated == "import os\nvalue = 2\nprint(value)\n"
    assert fuzzy == [{"blockIndex": 1, "matchMode": "indentation"}]


@pytest.mark.parametrize(
    ("hunks", "reason"),
    [
        ("+only_added\n", "apply_patch_hunk_without_context"),
        (" context\n", "apply_patch_hunk_without_change"),
        (" x\nmissing_prefix\n-y\n", "apply_patch_line_prefix_missing"),
        (" x\n-y\n*** Update File: b.py\n x\n-y\n", "apply_patch_operation_unsupported"),
    ],
)
def test_apply_patch_invalid_hunks_report_reason(hunks: str, reason: str) -> None:
    with pytest.raises(ReportingError) as caught:
        parse_script_patch(_apply_patch("a.py", hunks), 64 * 1024)

    assert caught.value.code == "report_code_script_edit_invalid"
    assert caught.value.details["reason"] == reason
    assert caught.value.details["patchFormat"] == "apply_patch"


@pytest.mark.anyio
async def test_edit_script_applies_sha_less_apply_patch_and_counts_format(toolkit, script):  # noqa: F811
    patch = _apply_patch(toolkit.context.script_path, " value = 1\n-print(value)\n+print(value + 1)\n")

    result = await toolkit.edit_script(patch)

    assert result["ok"] is True
    assert script["source"] == "# 保留中文\nvalue = 1\nprint(value + 1)\n"
    assert toolkit.patch_format_counts == {"apply_patch": 1}


@pytest.mark.anyio
async def test_edit_script_apply_patch_with_stale_sha_still_conflicts(toolkit, script):  # noqa: F811
    patch = _apply_patch("x.py", " value = 1\n-print(value)\n+print(0)\n", sha="b" * 64)

    result = await toolkit.edit_script(patch)

    assert result["code"] == "report_code_script_edit_conflict"
    assert script["writes"] == 0


@pytest.mark.anyio
async def test_edit_script_sha_less_patch_requires_bound_path(toolkit, script):  # noqa: F811
    result = await toolkit.edit_script(_apply_patch("other.py", " value = 1\n-print(value)\n+print(0)\n"))

    assert result["code"] == "report_code_script_edit_invalid"
    assert result["details"]["reason"] == "apply_patch_path_mismatch"
    assert script["writes"] == 0

    await toolkit.edit_script("*** Begin Patch\n*** Add File: b.py\n+x\n*** End Patch\n")
    # 路径不符时格式本身已解析成功，仍计入 apply_patch，便于评估格式偏好。
    assert toolkit.patch_format_counts == {
        "apply_patch": 1,
        "invalid:apply_patch_operation_unsupported": 1,
    }


@pytest.mark.anyio
async def test_sha_less_apply_patch_targets_rejected_draft(binding, runtime):  # noqa: F811
    draft_toolkit = _toolkit(binding, runtime)
    await _rejected(draft_toolkit)

    result = await draft_toolkit.edit_script(
        _apply_patch(
            draft_toolkit.context.script_path,
            '-json.dump({}, open("data/x.json", "w"))\n'
            '+json.dump({}, open("analysis/out.json", "w"))\n',
        )
    )

    assert result["ok"] is True, result
    assert result["status"] == "draft_promoted"
    assert draft_toolkit.rejected_draft_sha256 is None
    assert '"analysis/out.json"' in (await draft_toolkit.read_script())["source"]
    assert hashlib.sha256(REJECTED_SOURCE.encode()).hexdigest() != result["sha256"]


def test_metric_sample_reports_patch_formats() -> None:
    sample = build_coding_metric_sample(
        task_id="task-1",
        task_kind="analysis",
        duration_ms=1,
        patch_format_counts={"apply_patch": 2, "invalid:no_valid_blocks": 1},
    )

    assert sample["patchFormats"] == {"apply_patch": 2, "invalid:no_valid_blocks": 1}


_TWO_FUNCTIONS = (
    "def load():\n    value = 1\n    return value\n\n\n"
    "def plot():\n    value = 1\n    return value\n"
)


def _apply(patch: str) -> tuple[str, list[dict[str, object]]]:
    parsed = parse_script_patch(patch, 64 * 1024)
    return apply_edit_blocks(
        _TWO_FUNCTIONS, parsed.edits, anchors=parsed.anchors, ordered=parsed.ordered
    )


def test_anchor_disambiguates_repeated_hunk() -> None:
    updated, matches = _apply(
        _apply_patch("a.py", "@@ def plot():\n     value = 1\n-    return value\n+    return value * 2\n")
    )

    assert updated.endswith("def plot():\n    value = 1\n    return value * 2\n")
    assert updated.startswith("def load():\n    value = 1\n    return value\n")
    assert matches == [{"blockIndex": 1, "matchMode": "anchor"}]


def test_later_hunks_are_located_after_previous_hunk() -> None:
    updated, _ = _apply(
        _apply_patch(
            "a.py",
            "@@ def load():\n     value = 1\n-    return value\n+    return value + 1\n"
            "@@\n     value = 1\n-    return value\n+    return value + 2\n",
        )
    )

    assert "return value + 1\n\n\ndef plot():" in updated
    assert updated.endswith("return value + 2\n")


@pytest.mark.parametrize(
    ("hunks", "anchor_detail"),
    [
        ("@@\n     value = 1\n-    return value\n+    return 0\n", None),
        ("@@ def missing():\n     value = 1\n-    return value\n+    return 0\n", "def missing():"),
    ],
    ids=["first-hunk-without-anchor", "anchor-not-found"],
)
def test_ambiguous_hunk_without_usable_anchor_is_rejected(hunks, anchor_detail) -> None:
    with pytest.raises(ReportingError) as caught:
        _apply(_apply_patch("a.py", hunks))

    assert caught.value.code == "report_code_script_edit_ambiguous"
    assert caught.value.details.get("anchor") == anchor_detail


def test_search_replace_ambiguity_ignores_anchor_semantics() -> None:
    with pytest.raises(ReportingError) as caught:
        apply_edit_blocks(_TWO_FUNCTIONS, [("    value = 1\n    return value", "    return 0")])

    assert caught.value.code == "report_code_script_edit_ambiguous"
    assert "hint" not in caught.value.details


def test_codex_style_double_at_header_is_parsed_as_anchor() -> None:
    parsed = parse_script_patch(
        _apply_patch("a.py", "@@ def plot(): @@\n     value = 1\n-    return value\n+    return 0\n"),
        64 * 1024,
    )

    assert parsed.anchors == ("def plot():",)
