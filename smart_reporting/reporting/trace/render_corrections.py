"""最终渲染对模型正文的语义改写记录。

方向词、极值月份、“各月均为<全年合计>”、百分数与百分点、末位差一的手算数和“万人”写法，
最终渲染会按冻结事实确定性改写。改写只在模式匹配正确时成立，且模型不知道正文被改成了什么。
写作关口试渲染时开启记录，把每处改写连同所在语句交回模型自行改写；正式渲染不开启记录，
行为不变，模型纠错轮次仍未改的才由自动改写兜底。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class RenderCorrection:
    kind: str
    original: str
    corrected: str
    text: str
    position: int


_RECORDER: ContextVar[list[RenderCorrection] | None] = ContextVar("render_corrections", default=None)


@contextmanager
def recording_render_corrections() -> Iterator[list[RenderCorrection]]:
    """在当前上下文内收集最终渲染将做的语义改写。"""
    sink: list[RenderCorrection] = []
    token = _RECORDER.set(sink)
    try:
        yield sink
    finally:
        _RECORDER.reset(token)


def record_render_correction(kind: str, original: str, corrected: str, text: str, position: int) -> None:
    """登记一处改写；text/position 指向改写前的正文，用于取所在语句。未开启记录时不做任何事。"""
    sink = _RECORDER.get()
    if sink is not None and original != corrected:
        sink.append(RenderCorrection(kind, original, corrected, text, position))


# 改变语义、常需连带改写上下文的改写单独触发退回；单位换写与末位修正服务端可确定完成，
# 只在本轮已有其他问题时顺带告知，不为它多开一轮模型调用。
MEANING_CHANGING = frozenset({"direction", "monthly_total", "extrema"})

_MESSAGES = {
    "direction": "方向与登记变化相反：“{original}”中的变化已登记为增加，最终渲染会改为“{corrected}”。"
                 "请自行改写方向词，并同步修正前后文的判断。",
    "monthly_total": "“{original}”把期间合计写成了每月数值，最终渲染会改为“{corrected}”。"
                     "请改写为每月数值，或明确写成合计。",
    "extrema": "极值月份与登记的月度序列不符，最终渲染会把“{original}”改写为“{corrected}”。请按登记序列自行改写。",
    "last_digit": "“{original}”与按登记值计算的结果末位不同（多为用已舍入的显示值手算），最终渲染会改为“{corrected}”。"
                  "请改用计算引用由服务端计算，或写成“{corrected}”。",
    "percent_point": "“{original}”是两项百分数之差，应写作“{corrected}”；写成百分数会被读成相对变化率。",
    "rate_unit": "“{original}”是相对变化率，应写作“{corrected}”，不是百分点。",
    "visit_unit": "“{original}”对应登记的人次（就诊次数），不是人数，应写作“{corrected}”。",
}


def correction_message(correction: RenderCorrection) -> str:
    """面向模型的纠错说明：最终渲染会把哪里改成什么，附所在语句（去掉协议标记）。"""
    import re

    from .numeric_text import text_after_last_break, text_before_next_break

    def plain(text: str) -> str:
        return re.sub(r"\[\[[^\]\r\n]+\]\]", "", text)

    statement = plain(text_after_last_break(correction.text, correction.position)
                      + text_before_next_break(correction.text, correction.position))
    message = _MESSAGES[correction.kind].format(original=plain(correction.original),
                                                corrected=plain(correction.corrected))
    return f"{message}所在语句：{statement.strip()[:240]}"


__all__ = [
    "MEANING_CHANGING",
    "RenderCorrection",
    "correction_message",
    "record_render_correction",
    "recording_render_corrections",
]
