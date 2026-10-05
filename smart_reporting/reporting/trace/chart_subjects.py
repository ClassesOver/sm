"""图题与紧邻图注的规范化指纹；格式变化不改变生成时展示身份。"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt

from .contracts_v1 import canonical_sha256


def chart_presentations(markdown: str) -> dict[str, list[str]]:
    tokens = MarkdownIt("commonmark").parse(markdown)
    presentations: dict[str, list[str]] = {}

    def text(children: Any) -> str:
        return " ".join("".join(
            child.content if child.type in {"text", "code_inline"} else
            " " if child.type in {"softbreak", "hardbreak"} else ""
            for child in children or ()
        ).split())

    for position, token in enumerate(tokens):
        for image in (child for child in token.children or () if child.type == "image"):
            source = urlsplit(str(image.attrGet("src") or ""))
            if source.scheme or source.netloc or source.query or source.fragment:
                continue
            path = unquote(source.path)
            if not path or "\\" in path or PurePosixPath(path).is_absolute():
                continue
            caption = ""
            following = tokens[position + 2:position + 4]
            if len(following) == 2 and following[0].type == "paragraph_open" and following[1].type == "inline":
                candidate = text(following[1].children)
                if candidate.startswith(("图表：", "图表:", "图注：", "图注:")):
                    caption = candidate
            fingerprint = canonical_sha256({
                "alt": text(image.children),
                "title": str(image.attrGet("title") or ""),
                "caption": caption,
            })
            presentations.setdefault(PurePosixPath(path).as_posix(), []).append(fingerprint)
    return presentations


def chart_fingerprints(
    presentations: dict[str, list[str]], image_path: str, *, allow_filename: bool = True,
) -> list[str]:
    # 编辑器草稿经 manifest 定位裸文件名；其他目录的同名图片不能冒充。
    filename = PurePosixPath(image_path).name
    paths = {image_path, filename} if allow_filename else {image_path}
    return [fingerprint for path, fingerprints in presentations.items()
            if path in paths for fingerprint in fingerprints]


def freeze_chart_presentations(index: Any, markdown: str) -> Any:
    presentations = chart_presentations(markdown)
    files = {file.resource_id: file for file in index.files}
    charts = []
    for chart in index.chart_traces:
        if chart.presentation_sha256 is None:
            image_path = files[chart.image_file_resource_id].path
            unique_name = sum(
                PurePosixPath(files[item.image_file_resource_id].path).name == PurePosixPath(image_path).name
                for item in index.chart_traces
            ) == 1
            fingerprints = chart_fingerprints(presentations, image_path, allow_filename=unique_name)
            chart = chart.model_copy(update={
                "presentation_sha256": fingerprints[0] if len(fingerprints) == 1 else canonical_sha256(None),
            })
        charts.append(chart)
    return index.model_copy(update={"chart_traces": tuple(charts)})
