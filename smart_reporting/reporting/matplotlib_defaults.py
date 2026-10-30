import importlib.abc
import importlib.machinery
import re
import runpy
import sys
from collections.abc import Callable
from typing import Any

from .delivery.report_runtime.theme import (
    REPORT_CHART_FONTS,
    REPORT_VISUAL_THEME,
    matplotlib_theme_rc,
)

# 字体与报表主题配色一并作为默认样式；脚本显式设置的颜色、网格等仍然优先。
MATPLOTLIBRC_CONTENT = (
    "backend: Agg\n"
    "font.family: sans-serif\n"
    f"font.sans-serif: {', '.join(REPORT_CHART_FONTS)}\n"
    "axes.unicode_minus: False\n"
) + matplotlib_theme_rc()

def matplotlib_bootstrap(runtime_root: str) -> str:
    config_path = f"{runtime_root}/matplotlibrc"
    fonts = (
        (
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            f"{runtime_root}/NotoSansCJKSC-Regular.otf",
        ),
        (
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
            f"{runtime_root}/NotoSansCJKSC-Bold.otf",
        ),
    )
    return (
        "import os as _reporting_os\n"
        "import warnings as _reporting_warnings\n"
        f"_reporting_matplotlib_root = {runtime_root!r}\n"
        "_reporting_os.makedirs(_reporting_matplotlib_root, exist_ok=True)\n"
        f"_reporting_matplotlibrc = {config_path!r}\n"
        f"_reporting_matplotlibrc_content = {MATPLOTLIBRC_CONTENT!r}\n"
        "try:\n"
        "    with open(_reporting_matplotlibrc, encoding='ascii') as _reporting_file:\n"
        "        _reporting_matplotlibrc_current = _reporting_file.read()\n"
        "except OSError:\n"
        "    _reporting_matplotlibrc_current = None\n"
        "# 运行根目录可能跨版本持久保留；内容变化（如主题更新）时必须重写。\n"
        "if _reporting_matplotlibrc_current != _reporting_matplotlibrc_content:\n"
        "    _reporting_matplotlibrc_temporary = (\n"
        "        f'{_reporting_matplotlibrc}.{_reporting_os.getpid()}.tmp'\n"
        "    )\n"
        "    try:\n"
        "        with open(\n"
        "            _reporting_matplotlibrc_temporary, 'w', encoding='ascii'\n"
        "        ) as _reporting_file:\n"
        "            _reporting_file.write(_reporting_matplotlibrc_content)\n"
        "        _reporting_os.replace("
        "_reporting_matplotlibrc_temporary, _reporting_matplotlibrc)\n"
        "    finally:\n"
        "        if _reporting_os.path.exists(_reporting_matplotlibrc_temporary):\n"
        "            _reporting_os.unlink(_reporting_matplotlibrc_temporary)\n"
        "_reporting_os.environ.setdefault('MATPLOTLIBRC', _reporting_matplotlibrc)\n"
        "try:\n"
        "    from fontTools.ttLib import TTFont as _ReportingTTFont\n"
        "    from matplotlib import font_manager as _reporting_font_manager\n"
        "    from matplotlib import rcParams as _reporting_rc_params\n"
        f"    for _reporting_source, _reporting_font in {fonts!r}:\n"
        "        if not _reporting_os.path.exists(_reporting_font):\n"
        "            _reporting_temporary = f'{_reporting_font}.{_reporting_os.getpid()}.tmp'\n"
        "            try:\n"
        "                with _ReportingTTFont(_reporting_source, fontNumber=2, lazy=True) as _reporting_face:\n"
        "                    _reporting_face.save(_reporting_temporary)\n"
        "                _reporting_os.replace(_reporting_temporary, _reporting_font)\n"
        "            finally:\n"
        "                if _reporting_os.path.exists(_reporting_temporary):\n"
        "                    _reporting_os.unlink(_reporting_temporary)\n"
        "        _reporting_font_manager.fontManager.addfont(_reporting_font)\n"
        "    _reporting_rc_params['font.family'] = ['sans-serif']\n"
        "    _reporting_fallbacks = list(_reporting_rc_params['font.sans-serif'])\n"
        "    _reporting_rc_params['font.sans-serif'] = [\n"
        "        'Noto Sans CJK SC',\n"
        "        *(_font for _font in _reporting_fallbacks if _font != 'Noto Sans CJK SC'),\n"
        "    ]\n"
        "    def _reporting_protected_font_validator(_reporting_original):\n"
        "        def _reporting_validate_font(_reporting_value):\n"
        "            _reporting_validated = _reporting_original(_reporting_value)\n"
        "            try:\n"
        "                _reporting_values = list(_reporting_validated)\n"
        "            except TypeError:\n"
        "                return _reporting_validated\n"
        "            return [\n"
        "                'Noto Sans CJK SC',\n"
        "                *(\n"
        "                    _reporting_value\n"
        "                    for _reporting_value in _reporting_values\n"
        "                    if _reporting_value != 'Noto Sans CJK SC'\n"
        "                ),\n"
        "            ]\n"
        "        return _reporting_validate_font\n"
        "    for _reporting_key in ('font.family', 'font.sans-serif'):\n"
        "        _reporting_rc_params.validate[_reporting_key] = (\n"
        "            _reporting_protected_font_validator(\n"
        "                _reporting_rc_params.validate[_reporting_key]\n"
        "            )\n"
        "        )\n"
        "        _reporting_rc_params[_reporting_key] = _reporting_rc_params[_reporting_key]\n"
        "    _reporting_rc_params['axes.unicode_minus'] = False\n"
        "except Exception as _reporting_font_error:\n"
        "    _reporting_warnings.warn(\n"
        "        f'Could not prepare Noto Sans CJK SC: {_reporting_font_error}',\n"
        "        RuntimeWarning,\n"
        "    )\n"
    )


class _PostImportHooks(importlib.abc.MetaPathFinder):
    """模块被脚本首次导入后执行宿主默认值；不预先导入重量级依赖。"""

    def __init__(self, hooks: dict[str, Callable[[Any], None]]) -> None:
        self.hooks = hooks
        self.active: set[str] = set()

    def find_spec(self, fullname: str, path: Any, target: Any = None) -> Any:
        hook = self.hooks.get(fullname)
        if hook is None or fullname in self.active:
            return None
        self.active.add(fullname)
        try:
            spec = importlib.machinery.PathFinder.find_spec(fullname, path)
            if spec is None:
                for finder in sys.meta_path:
                    if finder is self or not hasattr(finder, "find_spec"):
                        continue
                    spec = finder.find_spec(fullname, path, target)
                    if spec is not None:
                        break
        finally:
            self.active.discard(fullname)
        loader: Any = getattr(spec, "loader", None) if spec is not None else None
        exec_module = getattr(loader, "exec_module", None)
        if not callable(exec_module):
            return spec

        def exec_with_hook(module: Any) -> None:
            exec_module(module)
            try:
                hook(module)
            except Exception:
                pass

        try:
            loader.exec_module = exec_with_hook
        except Exception:
            return spec
        return spec


def _compact_tick(value: float) -> str:
    magnitude = abs(value)
    for scale, suffix in ((1e8, "亿"), (1e4, "万")):
        if magnitude >= scale:
            return f"{value / scale:,.2f}".rstrip("0").rstrip(".") + suffix
    return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}".rstrip("0").rstrip(".")


def _apply_ticker_defaults(module: Any) -> None:
    """默认刻度把大数写成“5亿”“60万”，不出现“1e9”或挤在一起的长串数字；脚本自设格式器不受影响。"""

    formatter = module.ScalarFormatter
    if getattr(formatter.__call__, "_reporting_compact", False):
        return
    original = formatter.__call__

    def call(self: Any, value: float, pos: Any = None) -> str:
        text = original(self, value, pos)
        if type(self) is not formatter or not text or abs(value) < 1e4:
            return text
        return _compact_tick(value)

    call._reporting_compact = True  # type: ignore[attr-defined]
    formatter.__call__ = call


_NUMBER_CHARS = "0123456789.,"
_UNIT_STARTS = "亿万元%‰个人床次"


def _repair_number_breaks(text: str) -> str:
    """把落在数字中间（“9月11.6\n8亿元”）或数字与单位之间的换行移到该数字之前。

    脚本常用 textwrap.fill 按字符数折行，中文无空格时会把数字拆到两行。
    """
    if "\n" not in text:
        return text
    position = text.find("\n")
    while position != -1:
        before = text[position - 1] if position else ""
        after = text[position + 1] if position + 1 < len(text) else ""
        if before and before in _NUMBER_CHARS and after and (after in _NUMBER_CHARS or after in _UNIT_STARTS):
            start = position
            while start > 0 and text[start - 1] in _NUMBER_CHARS + "+-":
                start -= 1
            joined = text[:position] + text[position + 1:]
            text = joined if start == 0 or text[start - 1] == "\n" else joined[:start] + "\n" + joined[start:]
        position = text.find("\n", position + 1)
    return text


# 图内“2025-01”与正文统一写作“2025年1月”；带日的日期、编号与版本号不动。
_ISO_MONTH = re.compile(r"(?<![A-Za-z0-9_.\-/])(\d{4})-(0[1-9]|1[0-2])(?![A-Za-z0-9_.\-/])")


def _chart_text(text: str) -> str:
    text = _ISO_MONTH.sub(lambda match: f"{match[1]}年{int(match[2])}月", text)
    return _repair_number_breaks(text)


def _apply_text_defaults(module: Any) -> None:
    """图题、标注与刻度：换行不拆开数字，年月写作中文；只调整断行与年月写法。"""

    text_class = module.Text
    if getattr(text_class.set_text, "_reporting_number_breaks", False):
        return
    original = text_class.set_text

    def set_text(self: Any, s: Any) -> Any:
        return original(self, _chart_text(s) if isinstance(s, str) else s)

    set_text._reporting_number_breaks = True  # type: ignore[attr-defined]
    text_class.set_text = set_text


_LEGEND_LOCATIONS = (
    "upper left", "upper right", "lower left", "lower right",
    "upper center", "lower center", "center left", "center right",
)


def _legend_overlap(legend: Any, axes: list[Any], renderer: Any) -> float:
    """图例框压住的折线采样点、柱形与数据标签数；同位置的双轴一并计入。"""

    box = legend.get_window_extent(renderer)
    score = 0.0
    for ax in axes:
        for line in ax.get_lines():
            if not line.get_visible():
                continue
            points = line.get_transform().transform(line.get_xydata())
            for (x0, y0), (x1, y1) in zip(points, points[1:], strict=False):
                score += sum(box.contains(x0 + (x1 - x0) * step / 12, y0 + (y1 - y0) * step / 12)
                             for step in range(13))
            if len(points) == 1:
                score += box.contains(*points[0])
        for artist in (*ax.patches, *ax.texts):
            if artist.get_visible() and box.overlaps(artist.get_window_extent(renderer)):
                score += 12
    return score


def _place_legends(figure: Any) -> None:
    """保存前把压住数据的轴内图例移到重叠最少的轴内位置；脚本用 bbox_to_anchor 自定位置的不动。"""

    # 自动缩放与布局在绘制时才落定；不先布局时双轴折线仍按旧坐标计算重叠。
    figure.draw_without_rendering()
    renderer = figure.canvas.get_renderer()
    for ax in figure.axes:
        legend = ax.get_legend()
        if legend is None or not legend.get_visible() or getattr(legend, "_bbox_to_anchor", None) is not None:
            continue
        twins = [other for other in figure.axes
                 if other.get_position().bounds == ax.get_position().bounds]
        original = legend._loc
        overlap = _legend_overlap(legend, twins, renderer)
        if overlap == 0:
            continue
        scores = []
        for location in _LEGEND_LOCATIONS:
            legend.set_loc(location)
            scores.append((_legend_overlap(legend, twins, renderer), location))
        best, location = min(scores, key=lambda item: item[0])
        if best > 0 and all(item.get_yscale() == "linear" for item in twins):
            # 轴内各处都压数据（多条折线铺满全幅）：抬高纵轴上限，在数据上方留出图例高度的空白带。
            share = legend.get_window_extent(renderer).height / ax.get_window_extent(renderer).height
            if share < 0.4:
                limits = [item.get_ylim() for item in twins]
                for item, (bottom, top) in zip(twins, limits, strict=True):
                    item.set_ylim(bottom, bottom + (top - bottom) / (1 - share - 0.04))
                legend.set_loc("upper center")
                headroom = _legend_overlap(legend, twins, renderer)
                if headroom < best:
                    best, location = headroom, "upper center"
                else:
                    for item, limit in zip(twins, limits, strict=True):
                        item.set_ylim(*limit)
        if best < overlap:
            legend.set_loc(location)
        else:
            legend._loc = original


def _apply_figure_defaults(module: Any) -> None:
    """图例压住折线、柱形或数据标签时自动换到空白处；任何异常都按原图保存。"""

    figure_class = module.Figure
    if getattr(figure_class.savefig, "_reporting_legend", False):
        return
    original = figure_class.savefig

    def savefig(self: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            _place_legends(self)
        except Exception:
            pass
        return original(self, *args, **kwargs)

    savefig._reporting_legend = True  # type: ignore[attr-defined]
    figure_class.savefig = savefig


# 脚本常照抄 Matplotlib 默认 tab10 色值（“#1f77b4”“#d62728”），整份报告配色因此与主题不一。
# 按语义（蓝、橙、绿、红、紫、青）换成主题色，保留“门诊蓝、出院红”之类的区分；棕、粉、灰、
# 橄榄色无对应主题色不改，脚本的其他自定义颜色不受影响。
def _theme_color_aliases() -> dict[str, str]:
    palette = REPORT_VISUAL_THEME["chartPalette"]
    pairs = (("blue", "#1f77b4", palette[0]), ("orange", "#ff7f0e", palette[4]),
             ("green", "#2ca02c", palette[5]), ("red", "#d62728", palette[7]),
             ("purple", "#9467bd", palette[6]), ("cyan", "#17becf", palette[3]))
    return {key: theme for name, code, theme in pairs for key in (code, f"tab:{name}")}


def _apply_color_defaults(module: Any) -> None:
    original = module._to_rgba_no_colorcycle
    if getattr(original, "_reporting_theme", False):
        return
    aliases = _theme_color_aliases()

    def to_rgba(c: Any, alpha: Any = None) -> Any:
        if isinstance(c, str):
            c = aliases.get(c.lower(), c)
        return original(c, alpha)

    to_rgba._reporting_theme = True  # type: ignore[attr-defined]
    module._to_rgba_no_colorcycle = to_rgba
    module._colors_full_map.cache.clear()


def _install_import_hooks() -> _PostImportHooks:
    hooks = _PostImportHooks({
        "matplotlib.ticker": _apply_ticker_defaults, "matplotlib.text": _apply_text_defaults,
        "matplotlib.figure": _apply_figure_defaults, "matplotlib.colors": _apply_color_defaults,
    })
    sys.meta_path.insert(0, hooks)
    # 包装器之前已导入的模块直接应用默认值。
    if "matplotlib.ticker" in sys.modules:
        _apply_ticker_defaults(sys.modules["matplotlib.ticker"])
    if "matplotlib.text" in sys.modules:
        _apply_text_defaults(sys.modules["matplotlib.text"])
    if "matplotlib.figure" in sys.modules:
        _apply_figure_defaults(sys.modules["matplotlib.figure"])
    if "matplotlib.colors" in sys.modules:
        _apply_color_defaults(sys.modules["matplotlib.colors"])
    return hooks


def run_reporting_script(script_path: str, runtime_root: str) -> None:
    """在正式脚本进程内应用 Matplotlib 默认值后执行签发脚本。"""

    namespace: dict[str, object] = {}
    bootstrap = matplotlib_bootstrap(runtime_root)
    exec(compile(bootstrap, "<matplotlib-bootstrap>", "exec"), namespace)
    hooks = _install_import_hooks()
    previous_argv = sys.argv
    sys.argv = [script_path]
    try:
        runpy.run_path(script_path, run_name="__main__")
    finally:
        sys.argv = previous_argv
        try:
            sys.meta_path.remove(hooks)
        except ValueError:
            pass
