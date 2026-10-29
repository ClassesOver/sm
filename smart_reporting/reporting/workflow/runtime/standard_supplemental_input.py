"""标准补证批次内复用原始 CSV；不承担授权、范围过滤或聚合。"""

import polars as pl

from ...hospital_operation.deterministic_analysis import read_analysis_csv

MAX_BATCH_INPUT_CACHE_BYTES = 32 * 1024 * 1024
MAX_BATCH_INPUT_CACHE_ENTRIES = 40


class BatchAnalysisInputCache:
    """仅由当前批次持有；完整输入内容绑定，返回可独立修改的 frame。"""

    def __init__(self) -> None:
        self._frames: dict[bytes, pl.DataFrame] = {}
        self._cached_bytes = 0

    def read(self, content: bytes) -> pl.DataFrame:
        cached = self._frames.get(content)
        if cached is not None:
            return cached.clone()

        frame = read_analysis_csv(content)
        size = len(content) + int(frame.estimated_size())
        if (
            len(self._frames) < MAX_BATCH_INPUT_CACHE_ENTRIES
            and self._cached_bytes + size <= MAX_BATCH_INPUT_CACHE_BYTES
        ):
            self._frames[content] = frame
            self._cached_bytes += size
        return frame.clone()
