from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from smart_reporting.sandbox.matplotlib_defaults import matplotlib_bootstrap


def test_matplotlib_bootstrap_renders_chinese_and_allows_script_override(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    chart_path = tmp_path / "chart.png"
    script = matplotlib_bootstrap(str(runtime_root)) + (
        "from matplotlib import font_manager, rcParams\n"
        "import matplotlib.pyplot as plt\n"
        "print(rcParams['font.sans-serif'][0])\n"
        "print(font_manager.findfont('Noto Sans CJK SC', fallback_to_default=False))\n"
        "figure, axes = plt.subplots()\n"
        "axes.set_title('收入规模与结构分析')\n"
        f"figure.savefig({str(chart_path)!r})\n"
        "rcParams['font.sans-serif'] = ['DejaVu Sans']\n"
        "print(rcParams['font.sans-serif'][0])\n"
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
    assert output[1].endswith("NotoSansCJKSC-Regular.otf")
    assert output[2] == "DejaVu Sans"
    assert "Glyph" not in result.stderr
    assert chart_path.stat().st_size > 0
