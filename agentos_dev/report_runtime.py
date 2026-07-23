"""受限 Markdown 报表运行时；由 WorkspaceReportToolkit 在 Daytona 中执行。"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit

MAX_MARKDOWN_BYTES = 1024 * 1024
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_COUNT = 50
MAX_TOTAL_IMAGE_BYTES = 50 * 1024 * 1024
MAX_RESULT_BYTES = 64 * 1024
MAX_DATASET_PATHS = 20
MAX_PDF_BYTES = 25 * 1024 * 1024
MAX_PDF_PAGES = 200
PDF_VALIDATION_TIMEOUT_SECONDS = 240
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
    if not parent.is_dir():
        raise ReportFailure("PDF 输出目录不存在")
    if path.exists() or path.is_symlink():
        raise ReportFailure("PDF 输出文件已经存在")
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


class ReportRuntime:
    def __init__(self, workspace: str | Path):
        self.workspace = Path(workspace).resolve()

    def _validate_datasets(self, state: dict[str, Any]) -> None:
        sources = state.get("sources")
        if not isinstance(sources, list) or not 1 <= len(sources) <= MAX_DATASET_PATHS:
            raise ReportFailure("分析任务缺少源文件校验信息")
        for source in sources:
            if not isinstance(source, dict):
                raise ReportFailure("分析任务缺少源文件校验信息")
            value = source.get("path")
            if not isinstance(value, str):
                raise ReportFailure("分析任务缺少源文件校验信息")
            relative = _relative_path(value)
            path = self.workspace.joinpath(*relative.parts)
            _reject_symlinks(self.workspace, path)
            if (
                not path.is_file()
                or path.stat().st_size != source.get("size")
                or _sha256(path) != source.get("sha256")
            ):
                raise ReportFailure("源文件发生变化，分析任务已失效")

    def _artifact(self, path: Path) -> dict[str, Any]:
        _reject_symlinks(self.workspace, path)
        if not path.is_file():
            raise ReportFailure("报表产物不存在或不是普通文件")
        return {
            "path": str(path.relative_to(self.workspace)),
            "size": path.stat().st_size,
            "sha256": _sha256(path),
        }

    def _images(self, markdown_path: Path, tokens: list[Any]) -> set[Path]:
        images: list[Path] = []
        for token in tokens:
            for child in token.children or []:
                if child.type != "image":
                    continue
                source = child.attrGet("src") or ""
                parsed = urlsplit(source)
                if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
                    raise ReportFailure("Markdown 图片只能引用工作区内的相对路径")
                decoded = unquote(parsed.path)
                if not decoded or "\\" in decoded:
                    raise ReportFailure("Markdown 图片路径无效")
                relative = PurePosixPath(decoded)
                if relative.is_absolute() or ".." in relative.parts:
                    raise ReportFailure("Markdown 图片只能引用工作区内的相对路径")
                image = markdown_path.parent.joinpath(*relative.parts)
                _reject_symlinks(self.workspace, image)
                try:
                    image.relative_to(self.workspace)
                except ValueError as error:
                    raise ReportFailure("Markdown 图片路径越界") from error
                if image.suffix.lower() not in IMAGE_SUFFIXES or not image.is_file():
                    raise ReportFailure("Markdown 图片不存在或格式不受支持")
                if image.stat().st_size > MAX_IMAGE_BYTES:
                    raise ReportFailure("单张 Markdown 图片超过 10 MiB")
                _check_image_signature(image)
                images.append(image.resolve())
        unique = set(images)
        if len(images) > MAX_IMAGE_COUNT:
            raise ReportFailure("Markdown 图片数量超过 50 张")
        if sum(path.stat().st_size for path in unique) > MAX_TOTAL_IMAGE_BYTES:
            raise ReportFailure("Markdown 图片合计超过 50 MiB")
        return unique

    def render_markdown(
        self,
        state: dict[str, Any],
        markdown_path: str,
        output_path: str,
        temporary_path: str,
    ) -> dict[str, Any]:
        try:
            import pypdf
            from markdown_it import MarkdownIt
            from weasyprint import HTML, URLFetcher
        except ImportError as error:
            raise ReportFailure("PDF 运行时依赖不可用") from error

        self._validate_datasets(state)
        temporary: Path | None = None
        succeeded = False
        try:
            source = _input_path(self.workspace, markdown_path, ".md")
            if source.stat().st_size > MAX_MARKDOWN_BYTES:
                raise ReportFailure("Markdown 文件超过 1 MiB")
            try:
                markdown = source.read_text(encoding="utf-8")
            except UnicodeDecodeError as error:
                raise ReportFailure("Markdown 文件必须使用 UTF-8 编码") from error

            parser = MarkdownIt("commonmark", {"html": False}).enable("table")
            tokens = parser.parse(markdown)
            allowed_images = self._images(source, tokens)
            source_artifact = self._artifact(source)
            image_artifacts = [self._artifact(path) for path in sorted(allowed_images)]
            body = parser.renderer.render(tokens, parser.options, {})
            output = _output_path(self.workspace, output_path)
            temporary = _temporary_pdf_path(temporary_path)
            file_fetcher = URLFetcher(allowed_protocols={"file"}, fail_on_errors=True)

            def fetch_resource(url: str) -> dict[str, Any]:
                parsed = urlsplit(url)
                if parsed.scheme != "file" or parsed.netloc not in ("", "localhost"):
                    raise ReportFailure("PDF 渲染禁止访问外部资源")
                path = Path(unquote(parsed.path)).resolve()
                if path not in allowed_images:
                    raise ReportFailure("PDF 渲染引用了未校验资源")
                return file_fetcher(url)

            document = (
                "<meta charset='utf-8'>"
                "<style>"
                "@page{size:A4;margin:18mm}"
                "body{font-family:'Noto Sans CJK SC','Noto Sans CJK JP',sans-serif;"
                "font-size:10.5pt;line-height:1.65;color:#202124}"
                "h1{font-size:24pt}h2{font-size:17pt}h3{font-size:13pt}"
                "h1,h2,h3{page-break-after:avoid}"
                "table{width:100%;border-collapse:collapse;margin:10px 0}"
                "th,td{border:1px solid #c7c9cc;padding:5px 7px;text-align:left}"
                "th{background:#f1f3f4}"
                "img{display:block;max-width:100%;height:auto;margin:12px auto}"
                "pre,code{white-space:pre-wrap;overflow-wrap:anywhere}"
                "blockquote{border-left:3px solid #9aa0a6;margin-left:0;padding-left:12px}"
                "</style>"
                f"{body}"
            )
            HTML(
                string=document,
                base_url=str(source.parent),
                url_fetcher=fetch_resource,
            ).write_pdf(str(temporary))
            pdf_size = temporary.stat().st_size
            if pdf_size > MAX_PDF_BYTES:
                raise ReportFailure("PDF 文件不能超过 25 MiB")
            reader = pypdf.PdfReader(str(temporary))
            page_count = len(reader.pages)
            if not page_count:
                raise ReportFailure("PDF 校验失败")
            if page_count > MAX_PDF_PAGES:
                raise ReportFailure("PDF 页数不能超过 200 页")
            if self._artifact(source)["sha256"] != source_artifact["sha256"] or any(
                self._artifact(path)["sha256"] != artifact["sha256"]
                for path, artifact in zip(sorted(allowed_images), image_artifacts, strict=True)
            ):
                raise ReportFailure("Markdown 或图片在渲染期间发生变化，请重新生成报表")
            pdf_artifact = {
                "path": str(output.relative_to(self.workspace)),
                "size": pdf_size,
                "sha256": _sha256(temporary),
            }
            render = {
                "markdown": source_artifact,
                "pdf": pdf_artifact,
                "images": image_artifacts,
                "pageCount": page_count,
                "imageCount": len(allowed_images),
            }
            result = {
                "status": "rendered",
                "jobId": state["jobId"],
                "markdownPath": str(source.relative_to(self.workspace)),
                "pdfPath": str(output.relative_to(self.workspace)),
                "pageCount": page_count,
                "imageCount": len(allowed_images),
                "size": pdf_size,
                "render": render,
            }
            succeeded = True
            return result
        finally:
            if temporary is not None and not succeeded:
                shutil.rmtree(temporary.parent, ignore_errors=True)

    def validate_pdf(
        self,
        state: dict[str, Any],
        pdf_path: str,
        temporary_directory: str,
    ) -> dict[str, Any]:
        try:
            import pypdf
            from PIL import Image
        except ImportError as error:
            raise ReportFailure("PDF 视觉验收依赖不可用") from error
        if not shutil.which("pdftoppm"):
            raise ReportFailure("PDF 视觉验收命令不可用")

        self._validate_datasets(state)
        temp_path: Path | None = None
        try:
            render = state.get("render")
            if not isinstance(render, dict) or render.get("pdf", {}).get("path") != pdf_path:
                raise ReportFailure("PDF 未登记为当前分析任务的渲染产物")
            supporting_artifacts = [render["markdown"], *render.get("images", [])]
            for artifact in supporting_artifacts:
                supporting = self.workspace.joinpath(*_relative_path(artifact["path"]).parts)
                if self._artifact(supporting)["sha256"] != artifact["sha256"]:
                    raise ReportFailure("Markdown 或图片产物发生变化，请重新渲染后验收")
            relative = _relative_path(pdf_path, ".pdf")
            path = self.workspace.joinpath(*relative.parts)
            current = self._artifact(path)
            self._check_pdf_bounds(path)
            if current["sha256"] != render["pdf"]["sha256"]:
                raise ReportFailure("PDF 产物发生变化，请重新渲染后验收")
            pages = []
            blank_pages = []
            rendered_image_count = 0
            temp_path = _validation_directory(temporary_directory)
            with _cleanup_directory(temp_path):
                prefix = temp_path / "page"
                try:
                    process = subprocess.run(
                        [
                            "pdftoppm",
                            "-gray",
                            "-r",
                            "72",
                            "-png",
                            str(path),
                            str(prefix),
                        ],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=PDF_VALIDATION_TIMEOUT_SECONDS,
                        check=False,
                    )
                    reader = pypdf.PdfReader(str(path))
                except (OSError, subprocess.TimeoutExpired, pypdf.errors.PdfReadError) as error:
                    raise ReportFailure("PDF 视觉验收无法打开产物") from error
                rendered_pages = sorted(
                    temp_path.glob("page-*.png"),
                    key=lambda item: int(item.stem.rsplit("-", 1)[-1]),
                )
                if process.returncode != 0 or len(rendered_pages) != len(reader.pages):
                    raise ReportFailure("PDF 视觉验收栅格化失败")
                for index, (page, rendered_page) in enumerate(
                    zip(reader.pages, rendered_pages, strict=True), start=1
                ):
                    with Image.open(rendered_page) as image:
                        grayscale = image.convert("L")
                        samples = grayscale.tobytes()
                        width, height = grayscale.size
                    non_white = sum(value < 250 for value in samples)
                    ratio = round(non_white / len(samples), 6) if samples else 0.0
                    text_char_count = len("".join((page.extract_text() or "").split()))
                    image_count = len(page.images)
                    rendered_image_count += image_count
                    blank = ratio < 0.0005 and text_char_count == 0 and image_count == 0
                    if blank:
                        blank_pages.append(index)
                    pages.append(
                        {
                            "page": index,
                            "width": width,
                            "height": height,
                            "nonWhiteRatio": ratio,
                            "textCharCount": text_char_count,
                            "imageCount": image_count,
                            "blank": blank,
                        }
                    )
            markdown_image_count = int(render.get("imageCount") or 0)
            missing_images = max(0, markdown_image_count - rendered_image_count)
            ok = bool(pages) and not blank_pages and missing_images == 0
            validation = {
                "ok": ok,
                "status": "validated" if ok else "validation_failed",
                "pdfPath": pdf_path,
                "pdfSha256": current["sha256"],
                "pageCount": len(pages),
                "markdownImageCount": markdown_image_count,
                "renderedImageCount": rendered_image_count,
                "missingImageCount": missing_images,
                "blankPages": blank_pages,
                "pages": pages,
            }
            if _sha256(path) != current["sha256"] or path.stat().st_size != current["size"]:
                raise ReportFailure("PDF 产物在验收期间发生变化，请重新验收")
            return validation
        finally:
            if temp_path is not None:
                shutil.rmtree(temp_path, ignore_errors=True)

    @staticmethod
    def _check_pdf_bounds(path: Path) -> None:
        try:
            import pypdf
        except ImportError as error:
            raise ReportFailure("PDF 视觉验收依赖不可用") from error
        if not path.is_file() or path.stat().st_size > MAX_PDF_BYTES:
            raise ReportFailure("PDF 文件不能超过 25 MiB")
        try:
            page_count = len(pypdf.PdfReader(str(path)).pages)
        except pypdf.errors.PdfReadError as error:
            raise ReportFailure("PDF 视觉验收无法打开产物") from error
        if not 1 <= page_count <= MAX_PDF_PAGES:
            raise ReportFailure("PDF 页数必须在 1 至 200 页之间")


def main(arguments: list[str] | None = None) -> int:
    values = arguments if arguments is not None else sys.argv[1:]
    try:
        if len(values) != 2:
            raise ReportFailure("报表渲染参数无效")
        action, payload_text = values
        payload = json.loads(payload_text)
        runtime = ReportRuntime(Path.cwd())
        if action == "render_markdown":
            result = runtime.render_markdown(
                payload["job"],
                payload["markdown_path"],
                payload["output_path"],
                payload["temporary_path"],
            )
        elif action == "validate_pdf":
            result = runtime.validate_pdf(
                payload["job"], payload["pdf_path"], payload["temporary_directory"]
            )
        else:
            raise ReportFailure("未知报表操作")
        encoded = json.dumps(result, ensure_ascii=False)
        if len(encoded.encode()) + 1 > MAX_RESULT_BYTES:
            raise ReportFailure("报表结果超过返回边界")
        print(encoded)
        return 0
    except (KeyError, TypeError, json.JSONDecodeError, ReportFailure) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        return 1
    except Exception:
        print(json.dumps({"error": "报表运行时执行失败"}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
