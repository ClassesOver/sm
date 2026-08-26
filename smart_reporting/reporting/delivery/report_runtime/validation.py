"""Reporting 运行时路径、图片和产物边界校验。"""

import hashlib
import shutil
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

MAX_MARKDOWN_BYTES = 1024 * 1024
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 50 * 1024 * 1024
MAX_PDF_BYTES = 200 * 1024 * 1024
MAX_DOCX_BYTES = 200 * 1024 * 1024
IMAGE_SUFFIXES = {".gif", ".jpeg", ".jpg", ".png", ".webp"}


class ReportFailure(ValueError):
    pass


def _relative_path(value: str, suffix: str | None = None) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ReportFailure("路径必须是当前工作区的相对路径")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or any(part in ("", ".") for part in path.parts)
        or (suffix is not None and path.suffix.lower() != suffix)
    ):
        expected = f" {suffix}" if suffix is not None else ""
        raise ReportFailure(f"路径必须是当前工作区内的{expected}相对路径")
    return path


def _reject_symlinks(workspace: Path, path: Path) -> None:
    relative = path.relative_to(workspace)
    current = workspace
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ReportFailure("报表路径不能包含符号链接")


def _input_path(workspace: Path, value: str, suffix: str) -> Path:
    relative = _relative_path(value, suffix)
    path = workspace.joinpath(*relative.parts)
    _reject_symlinks(workspace, path)
    if not path.is_file():
        raise ReportFailure("报表源文件不存在或不是普通文件")
    return path


def _output_path(workspace: Path, value: str) -> Path:
    relative = _relative_path(value, ".pdf")
    path = workspace.joinpath(*relative.parts)
    parent = path.parent
    _reject_symlinks(workspace, parent)
    if not parent.is_dir() and not parent.parent.is_dir():
        raise ReportFailure("PDF revision 父目录不存在")
    if path.exists() or path.is_symlink():
        raise ReportFailure("PDF 输出文件已经存在")
    return path


def _word_output_path(workspace: Path, value: str) -> Path:
    relative = _relative_path(value, ".docx")
    path = workspace.joinpath(*relative.parts)
    _reject_symlinks(workspace, path.parent)
    if not path.parent.is_dir() and not path.parent.parent.is_dir():
        raise ReportFailure("Word revision 父目录不存在")
    if path.exists() or path.is_symlink():
        raise ReportFailure("Word 输出文件已经存在")
    return path


def _temporary_pdf_path(value: str) -> Path:
    if not isinstance(value, str) or not value.startswith("/tmp/workspace-report-"):
        raise ReportFailure("PDF 临时路径无效")
    path = Path(value)
    if path.name != "render.pdf" or path.parent.parent != Path("/tmp"):
        raise ReportFailure("PDF 临时路径无效")
    if path.parent.is_symlink() or path.exists() or path.is_symlink():
        raise ReportFailure("PDF 临时路径已经存在")
    try:
        path.parent.mkdir(mode=0o700)
    except FileExistsError as error:
        raise ReportFailure("PDF 临时路径已经存在") from error
    return path


def _temporary_docx_path(pdf_path: Path) -> Path:
    path = pdf_path.with_name("render.docx")
    if path.exists() or path.is_symlink():
        raise ReportFailure("Word 临时路径已经存在")
    return path


def _validation_directory(value: str) -> Path:
    if not isinstance(value, str) or not value.startswith("/tmp/workspace-report-"):
        raise ReportFailure("PDF 验收临时路径无效")
    path = Path(value)
    if path.parent != Path("/tmp") or not path.name.endswith("-validate"):
        raise ReportFailure("PDF 验收临时路径无效")
    if path.exists() or path.is_symlink():
        raise ReportFailure("PDF 验收临时路径已经存在")
    try:
        path.mkdir(mode=0o700)
    except FileExistsError as error:
        raise ReportFailure("PDF 验收临时路径已经存在") from error
    return path


@contextmanager
def _cleanup_directory(path: Path):
    try:
        yield
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_image_signature(path: Path) -> None:
    header = path.read_bytes()[:12]
    suffix = path.suffix.lower()
    valid = {
        ".png": header.startswith(b"\x89PNG\r\n\x1a\n"),
        ".jpg": header.startswith(b"\xff\xd8\xff"),
        ".jpeg": header.startswith(b"\xff\xd8\xff"),
        ".gif": header.startswith((b"GIF87a", b"GIF89a")),
        ".webp": header.startswith(b"RIFF") and header[8:12] == b"WEBP",
    }.get(suffix, False)
    if not valid:
        raise ReportFailure("Markdown 图片格式或文件签名无效")


__all__ = [
    "IMAGE_SUFFIXES",
    "MAX_DOCX_BYTES",
    "MAX_IMAGE_BYTES",
    "MAX_MARKDOWN_BYTES",
    "MAX_PDF_BYTES",
    "MAX_TOTAL_IMAGE_BYTES",
    "ReportFailure",
    "_check_image_signature",
    "_cleanup_directory",
    "_input_path",
    "_output_path",
    "_relative_path",
    "_reject_symlinks",
    "_sha256",
    "_temporary_docx_path",
    "_temporary_pdf_path",
    "_validation_directory",
    "_word_output_path",
]
