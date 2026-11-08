"""Office 引擎子进程（Node 桥接、LibreOffice）的进程内并发上限。

每次调用都会启动一个 CPU 密集的子进程。默认线程池按 CPU 数放大并发，多人同时编辑
或预览时会把 CPU 占满。这里用固定大小的独立线程池串起所有引擎调用：超出上限的调用
排队等待；协程取消时尚未开始的任务直接放弃，不再启动子进程。
"""

from __future__ import annotations

import asyncio
import contextvars
import functools
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Literal

from loguru import logger

_CONCURRENCY_ENV = "AGENT_REPORTING_OFFICE_ENGINE_CONCURRENCY"
_QUEUE_WAIT_WARNING_SECONDS = 5.0

_executor: ThreadPoolExecutor | None = None
_executor_lock = threading.Lock()


def office_engine_concurrency() -> int:
    """读取并发上限；未配置或无效时取 CPU 数的一半（1–4）。"""
    raw = os.environ.get(_CONCURRENCY_ENV, "").strip()
    if raw:
        try:
            value = int(raw)
        except ValueError:
            value = 0
        if value >= 1:
            return value
        logger.warning("office_engine_concurrency_invalid value={!r}", raw)
    return max(1, min(4, (os.cpu_count() or 2) // 2))


def _engine_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        with _executor_lock:
            if _executor is None:
                _executor = ThreadPoolExecutor(
                    max_workers=office_engine_concurrency(),
                    thread_name_prefix="office-engine",
                )
    return _executor


async def run_office_engine[T](func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """在受限线程池中执行同步引擎调用，保留调用方上下文变量（含 loguru 上下文）。"""
    submitted = time.monotonic()
    name = getattr(func, "__qualname__", repr(func))

    def call() -> T:
        waited = time.monotonic() - submitted
        if waited >= _QUEUE_WAIT_WARNING_SECONDS:
            logger.warning("office_engine_queue_wait name={} waited_s={:.1f}", name, waited)
        return func(*args, **kwargs)

    context = contextvars.copy_context()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_engine_executor(), functools.partial(context.run, call))


class OfficeConversionError(RuntimeError):
    """LibreOffice 转换失败；消息可直接作为软告警展示。"""


def libreoffice_to_pdf(content: bytes, *, suffix: str, timeout: float) -> bytes:
    """用独立配置目录把 Office 文件转换为 PDF。

    LibreOffice 的默认用户配置目录不能被多个进程同时使用：并发转换时后启动的进程会直接
    退出且不产出文件。每次调用都使用临时配置目录，结束后随临时目录一起删除。
    """
    converter = shutil.which("libreoffice") or shutil.which("soffice")
    if converter is None:
        raise OfficeConversionError("未安装 Office 页面渲染器")
    with tempfile.TemporaryDirectory(prefix="report-libreoffice-") as directory:
        root = Path(directory)
        source = root / f"source{suffix}"
        source.write_bytes(content)
        output = root / "output"
        output.mkdir()
        result = subprocess.run(
            [
                converter,
                "--headless",
                f"-env:UserInstallation={(root / 'profile').as_uri()}",
                "--convert-to",
                "pdf",
                "--outdir",
                str(output),
                str(source),
            ],
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        target = output / "source.pdf"
        if result.returncode != 0 or not target.is_file():
            logger.warning(
                "libreoffice_pdf_conversion_failed suffix={} returncode={}", suffix, result.returncode
            )
            raise OfficeConversionError("Office 页面转换失败")
        return target.read_bytes()


_ENGINES = {
    "slides": ("AGENT_REPORTING_SLIDES_ENGINE_DIR", "slides_engine"),
    "workbook": ("AGENT_REPORTING_WORKBOOK_ENGINE_DIR", "workbook_engine"),
    "pdf": ("AGENT_REPORTING_PDF_ENGINE_DIR", "pdf_engine"),
}


def engine_dir(engine: Literal["slides", "workbook", "pdf"]) -> Path:
    """固定版本 Node 引擎目录；部署时可用环境变量指向镜像内副本。"""
    variable, folder = _ENGINES[engine]
    return Path(os.environ.get(variable) or Path(__file__).resolve().parents[1] / folder)


def run_bridge(
    engine: Literal["slides", "workbook", "pdf"], script: str, request_path: Path, *, timeout: float = 120,
) -> subprocess.CompletedProcess[str]:
    """执行引擎桥接脚本，返回进程结果，由调用方按各自契约解释。

    镜像构建时会把桥接脚本预先打包为 dist/<script>.mjs，省去每次调用的 TypeScript 转译
    （单次约 0.7–1.2 秒降到约 0.3 秒）；源码检出没有 dist 时直接用 tsx 运行源文件。
    """
    root = engine_dir(engine)
    bundled = root / "dist" / f"{script}.mjs"
    if bundled.is_file():
        command = ["node", str(bundled)]
    else:
        command = [str(root / "node_modules" / ".bin" / "tsx"), str(root / "bridge" / f"{script}.ts")]
    return subprocess.run(
        [*command, str(request_path)],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def last_json_line(stdout: str) -> Any:
    """桥接脚本把 JSON 回执写在最后一行；回执缺失或无效时抛出 ValueError。"""
    lines = stdout.strip().splitlines()
    if not lines:
        raise ValueError("bridge_receipt_missing")
    return json.loads(lines[-1])
