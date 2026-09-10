import hashlib

import pytest
from agno.run import RunContext

from smart_reporting.reporting.contract import ReportFileInput
from smart_reporting.reporting.data_sources import (
    REPORT_DATASET_HANDLES_STATE_KEY,
    ReportDatasetStore,
)


class _Workspace:
    def __init__(self, content: bytes) -> None:
        self.content = content

    async def ahash_file(self, _thread_id: str, _path: str):
        return {"size": len(self.content), "sha256": hashlib.sha256(self.content).hexdigest()}

    async def afile_bytes(self, _thread_id: str, _path: str):
        return self.content, "text/csv"


@pytest.mark.anyio
async def test_url_csv_is_registered_as_supplemental_dataset() -> None:
    content = b"department,amount\nA,10\nB,20\n"
    digest = hashlib.sha256(content).hexdigest()
    state: dict[str, object] = {}
    context = RunContext(run_id="run-1", session_id="thread-1", session_state=state)
    store = ReportDatasetStore(_Workspace(content))  # type: ignore[arg-type]

    handles, lineage = await store.register_external_csv(
        (
            ReportFileInput(
                path="reporting-inputs/op/0-input.csv",
                filename="input.csv",
                size=len(content),
                sha256=digest,
                mediaType="text/csv",
            ),
        ),
        run_context=context,
    )

    assert handles[0].source_type == "url_csv"
    assert handles[0].row_count == 2
    assert lineage[0].source_type == "url_csv"
    assert handles[0].dataset_id in state[REPORT_DATASET_HANDLES_STATE_KEY]  # type: ignore[operator]
