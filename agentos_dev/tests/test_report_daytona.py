import io
import json
import os
import shlex
from pathlib import Path

import pytest
from daytona import CreateSandboxFromSnapshotParams, Daytona
from pypdf import PdfReader

from agentos_dev import report_runtime
from agentos_dev.workspace import WORKSPACE_ROOT, WORKSPACE_SNAPSHOT


@pytest.mark.integration
def test_sandbox_tools_生成三套中文_pdf():
    if not os.getenv("DAYTONA_API_KEY"):
        pytest.skip("需要 Daytona API Key")
    client = Daytona()
    sandbox = None
    try:
        sandbox = client.create(
            CreateSandboxFromSnapshotParams(
                name="agui-report-integration",
                snapshot=WORKSPACE_SNAPSHOT,
                public=False,
                ephemeral=True,
                auto_stop_interval=60,
                auto_archive_interval=0,
                network_block_all=True,
            ),
            timeout=180,
        )
        sandbox.fs.upload_file(Path(report_runtime.__file__).read_bytes(), "/tmp/report_runtime.py")
        sandbox.fs.upload_file(b"region,amount\nEast,10\nSouth,30\n", f"{WORKSPACE_ROOT}/data.csv")

        def run(action, payload):
            command = (
                f"python /tmp/report_runtime.py {shlex.quote(action)} "
                f"{shlex.quote(json.dumps(payload, ensure_ascii=False))}"
            )
            result = sandbox.process.exec(command, cwd=WORKSPACE_ROOT, timeout=120)
            assert result.exit_code == 0, result.result
            return json.loads(result.result)

        for template in ("经营", "财务", "项目"):
            prepared = run("prepare", {"paths": ["data.csv"]})
            analyzed = run(
                "analyze",
                {"job_id": prepared["jobId"], "operations": [{"type": "summary"}]},
            )
            run(
                "compile",
                {
                    "job_id": prepared["jobId"],
                    "title": f"{template}验收",
                    "template": template,
                    "blocks": [
                        {
                            "type": "table",
                            "analysis_id": analyzed["analyses"][0]["analysisId"],
                        },
                        {"type": "appendix"},
                    ],
                },
            )
            rendered = run("render", {"job_id": prepared["jobId"]})
            content = sandbox.fs.download_file(f"{WORKSPACE_ROOT}/{rendered['path']}")
            reader = PdfReader(io.BytesIO(content))
            text = "".join(page.extract_text() or "" for page in reader.pages)
            assert reader.pages and template in text and "截断" in text
    finally:
        if sandbox is not None:
            client.delete(sandbox)
