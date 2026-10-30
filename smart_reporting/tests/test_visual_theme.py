from __future__ import annotations

import warnings
from pathlib import Path

from smart_reporting.reporting.delivery.report_runtime import REPORT_VISUAL_THEME as REPORT_THEME
from smart_reporting.reporting.delivery.report_runtime.theme import (
    REPORT_VISUAL_THEME,
)
from smart_reporting.reporting.matplotlib_defaults import (
    MATPLOTLIBRC_CONTENT,
    matplotlib_bootstrap,
)


def test_report_renderer_and_chart_defaults_share_one_theme() -> None:
    assert REPORT_THEME is REPORT_VISUAL_THEME


def test_matplotlibrc_applies_report_palette_and_neutral_tokens(tmp_path: Path) -> None:
    from matplotlib import rc_params_from_file

    rc_path = tmp_path / "matplotlibrc"
    rc_path.write_text(MATPLOTLIBRC_CONTENT, encoding="ascii")
    params = rc_params_from_file(str(rc_path), use_default_template=False)

    colors = [color.upper() for color in params["axes.prop_cycle"].by_key()["color"]]
    assert colors == REPORT_VISUAL_THEME["chartPalette"]
    assert params["grid.color"].upper() == REPORT_VISUAL_THEME["gridline"]
    assert params["xtick.color"].upper() == REPORT_VISUAL_THEME["muted"]
    assert params["axes.spines.top"] is False


def test_matplotlib_bootstrap_rewrites_stale_rc_file(tmp_path: Path) -> None:
    (tmp_path / "matplotlibrc").write_text("backend: Agg\n", encoding="ascii")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        exec(compile(matplotlib_bootstrap(str(tmp_path)), "<bootstrap>", "exec"), {})

    assert (tmp_path / "matplotlibrc").read_text(encoding="ascii") == MATPLOTLIBRC_CONTENT
