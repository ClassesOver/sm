"""受限 Markdown 报表运行时；由 WorkspaceReportToolkit 在 Daytona 中执行。"""

from __future__ import annotations

import base64
import ctypes
import fcntl
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit

MAX_MARKDOWN_BYTES = 1024 * 1024
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_COUNT = 50
MAX_TOTAL_IMAGE_BYTES = 50 * 1024 * 1024
MAX_RESULT_BYTES = 64 * 1024
MAX_COMMAND_BYTES = 32 * 1024
MAX_ANALYSIS_OUTPUT_BYTES = 8 * 1024
MAX_DATASET_PATHS = 20
MAX_ANALYSIS_TIMEOUT = 60
IMAGE_SUFFIXES = {".gif", ".jpeg", ".jpg", ".png", ".webp"}
FAILURE_TTL_SECONDS = 24 * 60 * 60


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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _enable_child_subreaper() -> None:
    if sys.platform != "linux":
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
        raise ReportFailure("无法启用分析进程隔离")


def _process_parents() -> dict[int, int]:
    result = {}
    for status in Path("/proc").glob("[0-9]*/status"):
        try:
            values = {
                key: value.strip()
                for key, value in (
                    line.split(":", 1) for line in status.read_text().splitlines() if ":" in line
                )
            }
            result[int(status.parent.name)] = int(values["PPid"])
        except (FileNotFoundError, KeyError, PermissionError, ValueError):
            continue
    return result


def _descendants(parent_pid: int, parents: dict[int, int]) -> set[int]:
    result: set[int] = set()
    changed = True
    while changed:
        changed = False
        for pid, parent in parents.items():
            if pid not in result and (parent == parent_pid or parent in result):
                result.add(pid)
                changed = True
    return result


def _terminate_descendants() -> None:
    if sys.platform != "linux":
        return
    parent_pid = os.getpid()
    for _attempt in range(8):
        parents = _process_parents()
        descendants = _descendants(parent_pid, parents)
        if not descendants:
            return
        for pid in descendants:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        for pid, process_parent in parents.items():
            if process_parent != parent_pid or pid not in descendants:
                continue
            try:
                os.waitpid(pid, 0)
            except (ChildProcessError, ProcessLookupError):
                pass


def _execute_command(command: str, timeout: int) -> dict[str, Any]:
    _enable_child_subreaper()
    process = subprocess.Popen(
        ["/bin/bash", "--noprofile", "--norc", "-c", command],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        output_bytes, _stderr = process.communicate(timeout=timeout)
        exit_code = process.returncode
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        _terminate_descendants()
        output_bytes, _stderr = process.communicate()
        exit_code = 124
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        _terminate_descendants()
    truncated = len(output_bytes) > MAX_ANALYSIS_OUTPUT_BYTES
    return {
        "exitCode": exit_code,
        "output": base64.b64encode(output_bytes[:MAX_ANALYSIS_OUTPUT_BYTES]).decode("ascii"),
        "truncated": truncated,
    }


def _run_supervised_command(command: str, cwd: Path, timeout: int) -> tuple[bytes, int, bool]:
    payload = json.dumps({"command": command, "timeout": timeout}, ensure_ascii=False)
    supervisor = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "_execute", payload],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        output_bytes, _stderr = supervisor.communicate(timeout=timeout + 5)
    except subprocess.TimeoutExpired as error:
        os.killpg(supervisor.pid, signal.SIGKILL)
        supervisor.wait()
        raise ReportFailure("分析 supervisor 未能按时退出") from error
    output = output_bytes.decode("utf-8", errors="replace")
    if supervisor.returncode != 0:
        raise ReportFailure(output or "分析 supervisor 执行失败")
    try:
        line = next(line for line in reversed(output.splitlines()) if line.strip())
        result = json.loads(line)
        command_output = base64.b64decode(result["output"], validate=True)
        exit_code = result["exitCode"]
        truncated = result["truncated"]
    except (StopIteration, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ReportFailure(output or "分析 supervisor 返回无效结果") from error
    if not isinstance(exit_code, int) or not isinstance(truncated, bool):
        raise ReportFailure("分析 supervisor 返回无效结果")
    return command_output, exit_code, truncated


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
    def __init__(self, workspace: str | Path, state_root: str | Path | None = None):
        self.workspace = Path(workspace).resolve()
        self.state_root = Path(state_root or "/tmp/workspace-report").resolve()
        self.state_root.mkdir(parents=True, exist_ok=True)
        now = time.time()
        for path in self.state_root.iterdir():
            if path.is_dir() and now - path.stat().st_mtime > FAILURE_TTL_SECONDS:
                shutil.rmtree(path, ignore_errors=True)

    def _load(self, job_id: str) -> dict[str, Any]:
        state_path = self._job_path(job_id) / "state.json"
        return json.loads(state_path.read_text(encoding="utf-8"))

    def _job_path(self, job_id: str) -> Path:
        try:
            value = uuid.UUID(job_id)
        except (TypeError, ValueError) as error:
            raise ReportFailure("job_id 无效") from error
        job = self.state_root / str(value)
        if not (job / "state.json").is_file():
            raise ReportFailure("分析任务不存在")
        return job

    @contextmanager
    def _locked_state(self, job_id: str):
        job = self._job_path(job_id)
        with (job / "state.lock").open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield self._load(job_id)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _save(self, state: dict[str, Any]) -> None:
        job = self.state_root / state["jobId"]
        job.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix="state-", suffix=".tmp", dir=job)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(state, stream, ensure_ascii=False)
            temporary.replace(job / "state.json")
        finally:
            temporary.unlink(missing_ok=True)

    def _validate_datasets(self, state: dict[str, Any]) -> None:
        hashes = state.get("hashes")
        if not isinstance(hashes, dict):
            raise ReportFailure("分析任务缺少源文件校验信息")
        for value in state["paths"]:
            relative = _relative_path(value)
            path = self.workspace.joinpath(*relative.parts)
            _reject_symlinks(self.workspace, path)
            if not path.is_file() or _sha256(path) != hashes.get(value):
                raise ReportFailure("源文件发生变化，分析任务已失效")

    def prepare_dataset(self, paths: list[str]) -> dict[str, Any]:
        if not isinstance(paths, list) or not 1 <= len(paths) <= MAX_DATASET_PATHS:
            raise ReportFailure("paths 数量必须在 1 至 20 个之间")
        if len(set(paths)) != len(paths):
            raise ReportFailure("paths 不能重复")
        normalized = []
        hashes = {}
        for value in paths:
            relative = _relative_path(value)
            path = self.workspace.joinpath(*relative.parts)
            _reject_symlinks(self.workspace, path)
            if not path.is_file():
                raise ReportFailure("分析输入不存在或不是普通文件")
            normalized_path = str(relative)
            normalized.append(normalized_path)
            hashes[normalized_path] = _sha256(path)
        state = {
            "jobId": str(uuid.uuid4()),
            "paths": normalized,
            "hashes": hashes,
            "roundCount": 0,
            "successfulRoundCount": 0,
        }
        self._save(state)
        return {"status": "prepared", **state}

    @staticmethod
    def analysis_capabilities() -> dict[str, Any]:
        from importlib.metadata import PackageNotFoundError, version

        packages = {
            "numpy": "numpy",
            "pandas": "pandas",
            "polars": "polars",
            "pyarrow": "pyarrow",
            "scipy": "scipy",
            "statsmodels": "statsmodels",
            "scikit-learn": "scikit-learn",
            "matplotlib": "matplotlib",
            "seaborn": "seaborn",
            "plotly": "plotly",
            "openpyxl": "openpyxl",
            "xlrd": "xlrd",
            "xlsxwriter": "xlsxwriter",
            "pypdf": "pypdf",
            "pdfplumber": "pdfplumber",
            "reportlab": "reportlab",
            "weasyprint": "weasyprint",
            "markitdown": "markitdown",
            "networkx": "networkx",
            "sympy": "sympy",
        }
        available = {}
        for name, distribution in packages.items():
            try:
                available[name] = version(distribution)
            except PackageNotFoundError:
                continue
        commands = [
            name
            for name in ("python", "pandoc", "libreoffice", "pdfinfo", "pdftotext", "qpdf")
            if shutil.which(name)
        ]
        return {
            "python": sys.version.split()[0],
            "packages": available,
            "commands": commands,
            "sql": ["sqlite3"],
        }

    def analyze_dataset(
        self,
        job_id: str,
        command: str,
        cwd: str | None = None,
        timeout: int = 30,
    ) -> dict[str, Any]:
        if not isinstance(command, str) or not command.strip():
            raise ReportFailure("分析命令不能为空")
        if len(command.encode("utf-8")) > MAX_COMMAND_BYTES:
            raise ReportFailure("分析命令超过 32 KiB")
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, int)
            or not 1 <= timeout <= MAX_ANALYSIS_TIMEOUT
        ):
            raise ReportFailure("分析超时必须在 1 至 60 秒之间")
        working_directory = self.workspace
        if cwd is not None:
            relative = _relative_path(cwd)
            working_directory = self.workspace.joinpath(*relative.parts)
            _reject_symlinks(self.workspace, working_directory)
            if not working_directory.is_dir():
                raise ReportFailure("分析工作目录不存在")
        with self._locked_state(job_id) as state:
            self._validate_datasets(state)
            output_bytes, exit_code, truncated = _run_supervised_command(
                command, working_directory, timeout
            )
            self._validate_datasets(state)
            output = output_bytes.decode("utf-8", errors="replace")
            succeeded = exit_code == 0 and bool(output.strip())
            if exit_code == 0 and not succeeded:
                output = "分析命令退出码为 0，但没有返回分析结果；请输出本轮结果后重试。"
            state["roundCount"] += 1
            if succeeded:
                state["successfulRoundCount"] += 1
            self._save(state)
            return {
                "ok": succeeded,
                "jobId": state["jobId"],
                "status": "analyzed" if succeeded else "analysis_failed",
                "roundCount": state["roundCount"],
                "successfulRoundCount": state["successfulRoundCount"],
                "paths": state["paths"],
                "exitCode": exit_code,
                "output": output,
                "truncated": truncated,
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

    def render_markdown(self, job_id: str, markdown_path: str, output_path: str) -> dict[str, Any]:
        try:
            import pypdf
            from markdown_it import MarkdownIt
            from weasyprint import HTML, URLFetcher
        except ImportError as error:
            raise ReportFailure("PDF 运行时依赖不可用") from error

        with self._locked_state(job_id) as state:
            self._validate_datasets(state)
            if state["successfulRoundCount"] < 1:
                raise ReportFailure("至少成功完成一轮分析后才能渲染 PDF")
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
            body = parser.renderer.render(tokens, parser.options, {})
            output = _output_path(self.workspace, output_path)
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
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{output.name}-", suffix=".tmp.pdf", dir=output.parent
            )
            os.close(descriptor)
            temporary = Path(temporary_name)
            try:
                HTML(
                    string=document,
                    base_url=str(source.parent),
                    url_fetcher=fetch_resource,
                ).write_pdf(str(temporary))
                reader = pypdf.PdfReader(str(temporary))
                if not reader.pages:
                    raise ReportFailure("PDF 校验失败")
                page_count = len(reader.pages)
                try:
                    os.link(temporary, output)
                except FileExistsError as error:
                    raise ReportFailure("PDF 输出文件已经存在") from error
            finally:
                temporary.unlink(missing_ok=True)
            return {
                "status": "rendered",
                "jobId": state["jobId"],
                "roundCount": state["roundCount"],
                "successfulRoundCount": state["successfulRoundCount"],
                "markdownPath": str(source.relative_to(self.workspace)),
                "pdfPath": str(output.relative_to(self.workspace)),
                "pageCount": page_count,
                "imageCount": len(allowed_images),
                "size": output.stat().st_size,
            }


def main(arguments: list[str] | None = None) -> int:
    values = arguments if arguments is not None else sys.argv[1:]
    try:
        if len(values) != 2:
            raise ReportFailure("报表渲染参数无效")
        action, payload_text = values
        payload = json.loads(payload_text)
        if action == "_execute":
            result = _execute_command(payload["command"], payload["timeout"])
        else:
            runtime = ReportRuntime(Path.cwd())
            if action == "capabilities":
                result = runtime.analysis_capabilities()
            elif action == "prepare":
                result = runtime.prepare_dataset(payload["paths"])
            elif action == "analyze":
                result = runtime.analyze_dataset(
                    payload["job_id"],
                    payload["command"],
                    payload.get("cwd"),
                    payload.get("timeout", 30),
                )
            elif action == "render_markdown":
                result = runtime.render_markdown(
                    payload["job_id"], payload["markdown_path"], payload["output_path"]
                )
            else:
                raise ReportFailure("未知报表操作")
        encoded = json.dumps(result, ensure_ascii=False)
        if len(encoded.encode()) > MAX_RESULT_BYTES:
            raise ReportFailure("报表结果超过返回边界")
        print(encoded)
        return 0
    except (KeyError, TypeError, json.JSONDecodeError, ReportFailure) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
