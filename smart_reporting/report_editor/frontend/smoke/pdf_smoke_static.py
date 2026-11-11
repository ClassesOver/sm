"""PDF 浏览器验收可固定到单次构建的静态资源快照。"""
import os
from pathlib import Path


def pdf_smoke_static_directory() -> Path:
    snapshot = os.environ.get('PDF_SMOKE_STATIC_DIRECTORY')
    return Path(snapshot).resolve() if snapshot else Path(__file__).resolve().parents[2] / 'static'
