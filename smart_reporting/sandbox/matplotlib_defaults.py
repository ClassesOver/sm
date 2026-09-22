import runpy
import sys

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


def run_reporting_script(script_path: str, runtime_root: str) -> None:
    """在正式脚本进程内应用 Matplotlib 默认值后执行签发脚本。"""

    namespace: dict[str, object] = {}
    bootstrap = matplotlib_bootstrap(runtime_root)
    exec(compile(bootstrap, "<matplotlib-bootstrap>", "exec"), namespace)
    previous_argv = sys.argv
    sys.argv = [script_path]
    try:
        runpy.run_path(script_path, run_name="__main__")
    finally:
        sys.argv = previous_argv
