"""产物文件身份：路径、媒体类型、大小与 SHA-256。"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from .contract import SHA256_PATTERN, StrictModel, safe_relative_posix_path


class ArtifactFile(StrictModel):
    path: str = Field(min_length=1, max_length=512)
    # mediaType 自 B1 起新增 json/csv：仅用于追溯 sidecar（traceIndex 等），
    # 渲染/图表产物仍走原有六类。
    media_type: Literal[
        "text/markdown",
        "image/png",
        "image/jpeg",
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/json",
        "text/csv",
    ] = Field(alias="mediaType")
    size: int = Field(ge=1, le=200 * 1024 * 1024)
    sha256: str = Field(pattern=SHA256_PATTERN)

    @field_validator("path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        safe_relative_posix_path(
            value, "产物路径必须位于工作区内", backslash_message="产物路径必须使用 POSIX 相对路径"
        )
        return value


__all__ = ["ArtifactFile"]
