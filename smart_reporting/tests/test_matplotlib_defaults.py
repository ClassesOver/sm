from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from smart_reporting.reporting.matplotlib_defaults import matplotlib_bootstrap


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
        "from matplotlib import rcParams\nrcParams['font.family'] = object()\n"
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
        "from smart_reporting.reporting.matplotlib_defaults import run_reporting_script;"
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


def test_reporting_script_runner_writes_large_ticks_in_chinese_units(tmp_path: Path) -> None:
    script_path = tmp_path / "chart.py"
    output_path = tmp_path / "ticks.txt"
    script_path.write_text(
        "from pathlib import Path\n"
        "import matplotlib.pyplot as plt\n"
        "from matplotlib.ticker import FuncFormatter\n"
        "fig, (ax, custom) = plt.subplots(1, 2)\n"
        "ax.bar(['a', 'b'], [3046407434, 600000]); custom.bar(['a'], [3046407434])\n"
        "custom.yaxis.set_major_formatter(FuncFormatter(lambda value, _pos: f'{value:.0f}'))\n"
        f"fig.savefig({str(tmp_path / 'chart.png')!r}); fig.canvas.draw()\n"
        "labels = [tick.get_text() for tick in ax.get_yticklabels()]\n"
        "custom_labels = [tick.get_text() for tick in custom.get_yticklabels()]\n"
        f"Path({str(output_path)!r}).write_text('|'.join(labels) + '\\n' + ax.yaxis.get_offset_text().get_text()"
        " + '\\n' + '|'.join(custom_labels), encoding='utf-8')\n",
        encoding="utf-8",
    )
    command = (
        "from smart_reporting.reporting.matplotlib_defaults import run_reporting_script;"
        f"run_reporting_script({str(script_path)!r}, {str(tmp_path / 'runtime')!r})"
    )

    result = subprocess.run([sys.executable, "-B", "-c", command], check=False, capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    labels, offset, custom = output_path.read_text(encoding="utf-8").split("\n")
    assert "5亿" in labels.split("|") and "0" in labels.split("|")
    assert offset == "" and "e" not in labels
    assert "500000000" in custom.split("|")


def test_reporting_script_runner_keeps_numbers_whole_across_title_breaks(tmp_path: Path) -> None:
    # 回放：textwrap.fill 把图题“9月11.68亿元”拆成“9月11.6\n8亿元”。
    script_path = tmp_path / "chart.py"
    output_path = tmp_path / "titles.txt"
    script_path.write_text(
        "from pathlib import Path\n"
        "import matplotlib.pyplot as plt\n"
        "fig, ax = plt.subplots()\n"
        "title = fig.suptitle('3—10月均超10亿元，9月11.6\\n8亿元为年内最高')\n"
        "label = ax.annotate('合计93.0\\n5%', (0, 0))\n"
        "plain = ax.set_title('收入构成\\n总部院区')\n"
        "ax.bar(['2025-01', '2025-02'], [1, 2]); fig.canvas.draw()\n"
        "note = fig.text(0, 0, '数据期间：2025-01至2025-11；文件 2025-01-01.csv')\n"
        "ticks = [tick.get_text() for tick in ax.get_xticklabels()]\n"
        f"Path({str(output_path)!r}).write_text('|'.join([*(item.get_text() for item in (title, label, plain, note)),"
        " *ticks]), encoding='utf-8')\n",
        encoding="utf-8",
    )
    command = (
        "from smart_reporting.reporting.matplotlib_defaults import run_reporting_script;"
        f"run_reporting_script({str(script_path)!r}, {str(tmp_path / 'runtime')!r})"
    )

    result = subprocess.run([sys.executable, "-B", "-c", command], check=False, capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    assert output_path.read_text(encoding="utf-8").split("|") == [
        "3—10月均超10亿元，9月\n11.68亿元为年内最高", "合计\n93.05%", "收入构成\n总部院区",
        # 图内年月与正文一致写作中文；带日的日期与文件名不动。
        "数据期间：2025年1月至2025年11月；文件 2025-01-01.csv", "2025年1月", "2025年2月",
    ]


def test_reporting_script_runner_moves_legends_off_plotted_data(tmp_path: Path) -> None:
    # 回放：双轴工作量图把图例放在上方居中，压住7月出院人次的峰值点。
    script_path = tmp_path / "chart.py"
    output_path = tmp_path / "legend.txt"
    script_path.write_text(
        "from pathlib import Path\n"
        "import matplotlib.pyplot as plt\n"
        "fig, (ax, kept, anchored) = plt.subplots(1, 3, figsize=(12, 4))\n"
        "months = list(range(1, 11))\n"
        "ax.plot(months, [55, 53, 64, 63, 57, 59, 61, 59, 61, 42], label='门诊人次')\n"
        "right = ax.twinx()\n"
        "right.plot(months, [1.75, 1.5, 2.04, 2.0, 1.94, 1.96, 2.12, 2.09, 2.1, 1.45], label='出院人次')\n"
        "lines = ax.get_lines() + right.get_lines()\n"
        "ax.legend(lines, [line.get_label() for line in lines], loc='upper center')\n"
        "kept.plot([0, 1], [0, 0.1], label='平稳'); kept.legend(loc='upper right')\n"
        "anchored.plot([0, 1], [1, 1], label='固定'); anchored.legend(loc='upper center', bbox_to_anchor=(0.5, 1))\n"
        f"fig.savefig({str(tmp_path / 'chart.png')!r})\n"
        f"Path({str(output_path)!r}).write_text('|'.join(str(item.get_legend()._loc) for item in (ax, kept, anchored)),"
        " encoding='utf-8')\n",
        encoding="utf-8",
    )
    command = (
        "from smart_reporting.reporting.matplotlib_defaults import run_reporting_script;"
        f"run_reporting_script({str(script_path)!r}, {str(tmp_path / 'runtime')!r})"
    )

    result = subprocess.run([sys.executable, "-B", "-c", command], check=False, capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    moved, kept, anchored = output_path.read_text(encoding="utf-8").split("|")
    # 9 = upper center；移到不压数据的位置，原本不重叠与脚本自定锚点的不动。
    assert moved not in {"9", "0"} and kept == "1" and anchored == "9"
