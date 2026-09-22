from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from smart_reporting.sandbox.matplotlib_defaults import matplotlib_bootstrap


def test_matplotlib_bootstrap_keeps_chinese_font_after_script_overrides(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    chart_path = tmp_path / "chart.png"
    script = matplotlib_bootstrap(str(runtime_root)) + (
        "from matplotlib import font_manager, rcParams, style\n"
        "import matplotlib.pyplot as plt\n"
        "print(rcParams['font.sans-serif'][0])\n"
        "print(font_manager.findfont('Noto Sans CJK SC', fallback_to_default=False))\n"
        "rcParams['font.sans-serif'] = "
        "['SimHei', 'Microsoft YaHei', 'PingFang SC', 'Arial Unicode MS', 'DejaVu Sans']\n"
        "print(rcParams['font.sans-serif'][0])\n"
        "rcParams.update({'font.family': ['DejaVu Sans']})\n"
        "print(rcParams['font.family'][0])\n"
        "with style.context({'font.sans-serif': ['DejaVu Sans']}):\n"
        "    print(rcParams['font.sans-serif'][0])\n"
        "    figure, axes = plt.subplots()\n"
        "    axes.set_title('收入规模与结构分析')\n"
        f"    figure.savefig({str(chart_path)!r})\n"
    )

    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    output = result.stdout.splitlines()
    assert output[0] == "Noto Sans CJK SC"
    assert output[1].endswith(("NotoSansCJKSC-Regular.otf", "NotoSansCJK-Regular.ttc"))
    assert output[2:] == ["Noto Sans CJK SC"] * 3
    assert "Glyph" not in result.stderr
    assert chart_path.stat().st_size > 0


def test_matplotlib_bootstrap_preserves_native_invalid_font_error(tmp_path: Path) -> None:
    script = matplotlib_bootstrap(str(tmp_path / "runtime")) + (
        "from matplotlib import rcParams\n"
        "rcParams['font.family'] = object()\n"
    )

    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "Expected str or other non-set iterable" in result.stderr


def test_reporting_script_runner_bootstraps_font_inside_child_process(tmp_path: Path) -> None:
    script_path = tmp_path / "chart.py"
    output_path = tmp_path / "font.txt"
    script_path.write_text(
        "from pathlib import Path\n"
        "from matplotlib import font_manager, rcParams\n"
        "font = font_manager.findfont('Noto Sans CJK SC', fallback_to_default=False)\n"
        f"Path({str(output_path)!r}).write_text("
        "rcParams['font.sans-serif'][0] + '\\n' + font, encoding='utf-8')\n",
        encoding="utf-8",
    )
    command = (
        "from smart_reporting.sandbox.matplotlib_defaults import run_reporting_script;"
        f"run_reporting_script({str(script_path)!r}, {str(tmp_path / 'runtime')!r})"
    )

    result = subprocess.run(
        [sys.executable, "-B", "-c", command],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    family, font_path = output_path.read_text(encoding="utf-8").splitlines()
    assert family == "Noto Sans CJK SC"
    assert font_path.endswith(("NotoSansCJKSC-Regular.otf", "NotoSansCJK-Regular.ttc"))
