from __future__ import annotations

import hashlib
import json
import os
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence"
OUT.mkdir(exist_ok=True)

DATA = {
    "periods": ["2025-01", "2025-02", "2025-03", "2025-04"],
    "current_yuan": [Decimal("120000"), Decimal("-30000"), None, Decimal("250000")],
    "prior_yuan": [Decimal("100000"), Decimal("-20000"), Decimal("40000"), Decimal("200000")],
    "ratio": Fraction(1, 8),
    "ratio_prior": Fraction(1, 10),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    expected_yoy = [
        (Decimal("120000") - Decimal("100000")) / Decimal("100000"),
        (Decimal("-30000") - Decimal("-20000")) / Decimal("-20000"),
        None,
        (Decimal("250000") - Decimal("200000")) / Decimal("200000"),
    ]
    ratio_percent = DATA["ratio"] * 100
    ratio_change_pp = (DATA["ratio"] - DATA["ratio_prior"]) * 100
    assert ratio_percent == Fraction(25, 2)
    assert ratio_change_pp == Fraction(5, 2)
    assert expected_yoy == [Decimal("0.2"), Decimal("0.5"), None, Decimal("0.25")]
    assert Decimal("250000") / Decimal("10000") == Decimal("25")
    assert expected_yoy[2] is None

    font_path = Path(font_manager.findfont("Noto Sans CJK SC", fallback_to_default=True))
    plt.rcParams.update({"font.family": font_manager.FontProperties(fname=str(font_path)).get_name()})
    fig, ax = plt.subplots(figsize=(10, 5), dpi=150)
    x = list(range(len(DATA["periods"])))
    values = [float(value) if value is not None else float("nan") for value in DATA["current_yuan"]]
    bars = ax.bar(x, values, color=["#2878B5", "#E07A35", "#9A9A9A", "#2878B5"], width=0.62)
    ax.axhline(0, color="#333333", linewidth=0.8)
    ax.set_xticks(x, ["2025年1月", "2025年2月（负值）", "2025年3月（缺失）", "2025年4月"])
    ax.set_ylabel("金额（元）")
    ax.set_title("合成案例：收入金额与缺失期间")
    ax.set_ylim(-60000, 300000)
    ax.grid(axis="y", alpha=0.2)
    ax.set_axisbelow(True)
    for bar, amount in zip(bars, DATA["current_yuan"]):
        if amount is not None:
            y = float(amount)
            if y < 0:
                ax.text(bar.get_x() + bar.get_width() / 2, y / 2, f"{amount / 10000} 万元",
                        ha="center", va="center", color="white", fontsize=8)
            else:
                ax.annotate(f"{amount / 10000} 万元", (bar.get_x() + bar.get_width() / 2, y),
                            xytext=(0, 5), textcoords="offset points", ha="center", va="bottom", fontsize=8)
    fig.tight_layout()
    fig.subplots_adjust(bottom=0.28, left=0.12)
    image_path = OUT / "synthetic-chinese-chart.png"
    fig.savefig(image_path, dpi=150)

    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    figure_box = fig.bbox
    text_boxes = []
    outside = []
    for artist in fig.findobj(match=lambda obj: hasattr(obj, "get_window_extent") and hasattr(obj, "get_text")):
        if not artist.get_text():
            continue
        bbox = artist.get_window_extent(renderer)
        if not bbox.width or not bbox.height:
            continue
        record = {"text": artist.get_text(), "bounds": [round(v, 2) for v in bbox.bounds]}
        text_boxes.append(record)
        if bbox.x0 < figure_box.x0 or bbox.y0 < figure_box.y0 or bbox.x1 > figure_box.x1 or bbox.y1 > figure_box.y1:
            outside.append(record)
    assert not outside, f"Text outside canvas: {outside}"

    fixture_path = Path(__file__)
    record = {
        "case_id": "synthetic-units-periods-chinese-layout-v1",
        "flint_commit": "a794557384adcc3293a77043f6b9aff1c33d152c",
        "smart_reporting_commit": "28649e9c56b1aa7e96f0c363e8eec8accd0175b7",
        "input_identity": [{"path": fixture_path.name, "size": fixture_path.stat().st_size, "sha256": sha256(fixture_path)}],
        "business_intent": "Synthetic-only: preserve amount units and signs, distinguish ratio change from percentage-point change, retain missing period as missing, fit Chinese labels on static output.",
        "variant": "independent_oracle_and_static_layout_probe",
        "mechanism_changed": "none; this is a baseline invariant probe, not a Flint adapter comparison",
        "command": "python docs/superpowers/reports/2026-11-09-flint-standard-visualization/fixtures/run_synthetic_checks.py",
        "expected_values": {"yuan_to_wan": "250000 yuan = 25 万元", "ratio_percent": "25/2%", "ratio_delta_pp": "5/2 percentage points", "yoy": ["0.2", "0.5", None, "0.25"]},
        "actual_values": {"yuan_to_wan": str(Decimal("250000") / Decimal("10000")), "ratio_percent": str(ratio_percent), "ratio_delta_pp": str(ratio_change_pp), "yoy": [str(v) if v is not None else None for v in expected_yoy]},
        "geometry": {"canvas_px": [int(figure_box.width), int(figure_box.height)], "text_artist_count": len(text_boxes), "outside_canvas_count": len(outside), "text_bounds": text_boxes},
        "visual_review": "not_run; geometry assertions are not independent visual review",
        "duration_ms": None,
        "model_calls": None,
        "redraws": 0,
        "font": {"family": "Noto Sans CJK SC", "path_basename": font_path.name, "sha256": sha256(font_path)},
        "render": {"matplotlib": matplotlib.__version__, "backend": matplotlib.get_backend(), "png": image_path.name, "png_sha256": sha256(image_path)},
        "limitations": ["Negative-base arithmetic is not asserted as a universal business definition of同比", "No external business reviewer", "No independent visual reviewers", "No production transformation or routing code was called", "Canvas-bound checks do not detect overlaps or misleading visual encoding"],
    }
    evidence_path = OUT / "synthetic-check.json"
    evidence_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"evidence": evidence_path.name, "png": image_path.name, "sha256": record["render"]["png_sha256"], "outside_canvas_count": len(outside)}, ensure_ascii=False))
    plt.close(fig)


if __name__ == "__main__":
    main()
