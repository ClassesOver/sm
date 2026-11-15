"""Office 共用的基础契约：严格模型、摘要格式与工作区相对路径校验。"""

from __future__ import annotations

from pathlib import PurePosixPath

from pydantic import BaseModel, ConfigDict

SHA256_PATTERN = r"^[0-9a-f]{64}$"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


def safe_relative_posix_path(
    value: str, message: str, *, backslash_message: str | None = None
) -> PurePosixPath:
    """校验工作区相对 POSIX 路径：拒绝反斜杠、绝对路径、工作区根（"."）、“..”与目录形式。"""

    if backslash_message is not None and "\\" in value:
        raise ValueError(backslash_message)
    path = PurePosixPath(value)
    if (
        "\\" in value
        or path.is_absolute()
        or not path.parts
        or ".." in path.parts
        or value.endswith("/")
    ):
        raise ValueError(message)
    return path


__all__ = ["SHA256_PATTERN", "StrictModel", "safe_relative_posix_path"]
