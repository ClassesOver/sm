import importlib.abc
import importlib.machinery
import runpy
import sys
import warnings
from collections.abc import Callable
from typing import Any

MATPLOTLIBRC_CONTENT = """backend: Agg
font.family: sans-serif
font.sans-serif: Noto Sans CJK SC, DejaVu Sans
axes.unicode_minus: False
"""

LOCAL_MATPLOTLIB_ROOT = "/workspace/.sandbox-matplotlib"
LOCAL_MATPLOTLIBRC_PATH = f"{LOCAL_MATPLOTLIB_ROOT}/matplotlibrc"


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
        "if not _reporting_os.path.exists(_reporting_matplotlibrc):\n"
        "    _reporting_matplotlibrc_temporary = (\n"
        "        f'{_reporting_matplotlibrc}.{_reporting_os.getpid()}.tmp'\n"
        "    )\n"
        "    try:\n"
        "        with open(\n"
        "            _reporting_matplotlibrc_temporary, 'w', encoding='ascii'\n"
        "        ) as _reporting_file:\n"
        f"            _reporting_file.write({MATPLOTLIBRC_CONTENT!r})\n"
        "        _reporting_os.replace("
        "_reporting_matplotlibrc_temporary, _reporting_matplotlibrc)\n"
        "    finally:\n"
        "        if _reporting_os.path.exists(_reporting_matplotlibrc_temporary):\n"
        "            _reporting_os.unlink(_reporting_matplotlibrc_temporary)\n"
        "_reporting_os.environ.setdefault('MATPLOTLIBRC', _reporting_matplotlibrc)\n"
        "try:\n"
        "    from fontTools.ttLib import TTCollection as _ReportingTTCollection\n"
        "    from matplotlib import font_manager as _reporting_font_manager\n"
        "    from matplotlib import rcParams as _reporting_rc_params\n"
        f"    for _reporting_source, _reporting_font in {fonts!r}:\n"
        "        if not _reporting_os.path.exists(_reporting_font):\n"
        "            _reporting_temporary = f'{_reporting_font}.{_reporting_os.getpid()}.tmp'\n"
        "            try:\n"
        "                _reporting_collection = _ReportingTTCollection(_reporting_source)\n"
        "                _reporting_collection.fonts[2].save(_reporting_temporary)\n"
        "                _reporting_collection.close()\n"
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


_KALEIDO_SYNC_FUNCTIONS = ("calc_fig_sync", "write_fig_sync", "write_fig_from_object_sync")
_PLOTLY_AUTOMARGIN_TEMPLATE = "reporting_automargin"


class _KaleidoSession:
    """首个同步渲染请求时启动常驻 Chrome，脚本结束时关闭。

    Kaleido 1.x 未启动 sync server 时每次 write_image 都冷启动并关闭一个
    Chrome；复用单实例只改变渲染进程生命周期，不改变脚本语义。任何失败都
    静默退回逐次启动。
    """

    def __init__(self) -> None:
        self.module: Any = None
        self.started = False
        self.attempted = False

    def ensure_started(self) -> None:
        if self.attempted or self.module is None:
            return
        self.attempted = True
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                self.module.start_sync_server(silence_warnings=True)
            self.started = True
        except Exception:
            self.started = False

    def patch(self, module: Any) -> None:
        self.module = module
        if not callable(getattr(module, "start_sync_server", None)):
            return
        for name in _KALEIDO_SYNC_FUNCTIONS:
            original = getattr(module, name, None)
            if callable(original):
                setattr(module, name, self._wrap(original))

    def _wrap(self, original: Callable[..., Any]) -> Callable[..., Any]:
        def call(*args: Any, **kwargs: Any) -> Any:
            self.ensure_started()
            return original(*args, **kwargs)

        call.__wrapped__ = original  # type: ignore[attr-defined]
        return call

    def close(self) -> None:
        if not self.started or self.module is None:
            return
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                self.module.stop_sync_server(silence_warnings=True)
        except Exception:
            pass
        self.started = False


def _apply_plotly_layout_defaults(module: Any) -> None:
    """为 Plotly 默认模板叠加 automargin，避免长刻度标签被裁切或重叠。"""

    try:
        base = module.templates.default or "plotly"
        if _PLOTLY_AUTOMARGIN_TEMPLATE in str(base).split("+"):
            return
        module.templates[_PLOTLY_AUTOMARGIN_TEMPLATE] = {
            "layout": {
                "xaxis": {"automargin": True},
                "yaxis": {"automargin": True},
            }
        }
        module.templates.default = f"{base}+{_PLOTLY_AUTOMARGIN_TEMPLATE}"
    except Exception:
        pass


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
        loader = getattr(spec, "loader", None) if spec is not None else None
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


def _install_import_hooks(kaleido: _KaleidoSession) -> _PostImportHooks:
    hooks = _PostImportHooks(
        {"kaleido": kaleido.patch, "plotly.io": _apply_plotly_layout_defaults}
    )
    sys.meta_path.insert(0, hooks)
    # 包装器之前已导入的模块直接应用默认值。
    if "kaleido" in sys.modules:
        kaleido.patch(sys.modules["kaleido"])
    if "plotly.io" in sys.modules:
        _apply_plotly_layout_defaults(sys.modules["plotly.io"])
    return hooks


def run_reporting_script(script_path: str, runtime_root: str) -> None:
    """在正式脚本进程内应用 Matplotlib/Plotly 默认值后执行签发脚本。"""

    namespace: dict[str, object] = {}
    bootstrap = matplotlib_bootstrap(runtime_root)
    exec(compile(bootstrap, "<matplotlib-bootstrap>", "exec"), namespace)
    kaleido = _KaleidoSession()
    hooks = _install_import_hooks(kaleido)
    previous_argv = sys.argv
    sys.argv = [script_path]
    try:
        runpy.run_path(script_path, run_name="__main__")
    finally:
        sys.argv = previous_argv
        kaleido.close()
        try:
            sys.meta_path.remove(hooks)
        except ValueError:
            pass
