"""读取编辑器文件时共用的字节身份校验。"""

import hashlib
from typing import Any

from ..reporting.models import ReportingError


async def read_verified_file(
    workspace: Any, scope: dict[str, Any], path: str, *, size: int | None,
    sha256: str | None, error_code: str, format_name: str,
) -> bytes:
    try:
        content, _ = await workspace.afile_bytes(scope["threadId"], path)
    except Exception as error:
        raise ReportingError(error_code, f"{format_name} 文件无法读取。") from error
    if len(content) != size or hashlib.sha256(content).hexdigest() != sha256:
        raise ReportingError(error_code, f"{format_name} 文件身份已变化。")
    return content
