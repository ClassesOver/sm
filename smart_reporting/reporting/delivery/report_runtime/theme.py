"""报表视觉主题的唯一来源。

PDF/Word 版式、沙箱内 Matplotlib/Plotly 默认样式与编辑器交互图表共用这里的令牌，
保证正文、静态图与交互图的配色和字体属于同一套视觉语言。report_runtime 会被整体
打包进沙箱独立运行，因此本模块只含常量与纯函数，不依赖包外任何模块。
"""

from __future__ import annotations

from typing import Any

REPORT_VISUAL_THEME: dict[str, Any] = {
    "name": "enterprise-tech-blue",
    "primary": "#0B4F8A",
    "accent": "#007EA7",
    "highlight": "#F2B134",
    "ink": "#1B2A41",
    "muted": "#5B6B7A",
    "grid": "#C7D7E5",
    # 图表内网格线比表格边框更浅，避免压过数据。
    "gridline": "#E1E9EF",
    "surface": "#EDF5FC",
    "chartPalette": [
        "#0B4F8A",
        "#007EA7",
        "#2F80ED",
        "#56B4E9",
        "#F2B134",
        "#2E9F6B",
        "#7A5AF8",
        "#D66B3D",
    ],
}

REPORT_CHART_FONTS = ("Noto Sans CJK SC", "DejaVu Sans")


def _rc_color(value: str) -> str:
    # matplotlibrc 中 "#" 起始注释，十六进制颜色必须去掉前缀。
    return value.removeprefix("#")


def matplotlib_theme_rc() -> str:
    """报表主题对应的 matplotlibrc 片段；脚本显式设置的样式仍然优先。"""

    theme = REPORT_VISUAL_THEME
    palette = ", ".join(f"'{_rc_color(color)}'" for color in theme["chartPalette"])
    return (
        f"axes.prop_cycle: cycler('color', [{palette}])\n"
        f"text.color: {_rc_color(theme['ink'])}\n"
        f"axes.titlecolor: {_rc_color(theme['ink'])}\n"
        f"axes.labelcolor: {_rc_color(theme['ink'])}\n"
        f"axes.edgecolor: {_rc_color(theme['grid'])}\n"
        "axes.spines.top: False\n"
        "axes.spines.right: False\n"
        "axes.grid: True\n"
        "axes.grid.axis: y\n"
        "axes.axisbelow: True\n"
        f"grid.color: {_rc_color(theme['gridline'])}\n"
        f"xtick.color: {_rc_color(theme['muted'])}\n"
        f"ytick.color: {_rc_color(theme['muted'])}\n"
        "legend.frameon: False\n"
        "figure.facecolor: white\n"
        "axes.facecolor: white\n"
        "savefig.facecolor: white\n"
    )


def plotly_theme_layout() -> dict[str, Any]:
    """报表主题对应的 Plotly 模板 layout；figure 显式声明的值仍然优先。"""

    theme = REPORT_VISUAL_THEME
    axis = {
        "automargin": True,
        "linecolor": theme["grid"],
        "gridcolor": theme["gridline"],
        "zerolinecolor": theme["grid"],
        "tickfont": {"color": theme["muted"]},
        "title": {"font": {"color": theme["ink"]}},
    }
    return {
        "colorway": list(theme["chartPalette"]),
        "font": {"family": ", ".join((*REPORT_CHART_FONTS, "sans-serif")), "color": theme["ink"]},
        "title": {"font": {"color": theme["ink"]}},
        "paper_bgcolor": "#FFFFFF",
        "plot_bgcolor": "#FFFFFF",
        "xaxis": dict(axis),
        "yaxis": dict(axis),
        "legend": {"font": {"color": theme["ink"]}},
        "hoverlabel": {
            "bgcolor": theme["ink"],
            "bordercolor": theme["ink"],
            "font": {"color": "#FFFFFF"},
        },
    }


__all__ = [
    "REPORT_CHART_FONTS",
    "REPORT_VISUAL_THEME",
    "matplotlib_theme_rc",
    "plotly_theme_layout",
]
