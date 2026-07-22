import io
import json
import os
import shlex
import uuid
from pathlib import Path

import pytest
from daytona import CreateSandboxFromSnapshotParams, Daytona
from pypdf import PdfReader

from agentos_dev import report_runtime
from agentos_dev.workspace import (
    MAX_DOWNLOAD_BYTES,
    WORKSPACE_ROOT,
    WORKSPACE_SNAPSHOT,
    WorkspaceService,
)


@pytest.mark.integration
def test_sandbox_tools_多轮分析后将_markdown_渲染为_pdf():
    if not os.getenv("DAYTONA_API_KEY"):
        pytest.skip("需要 Daytona API Key")
    client = Daytona()
    sandbox = None
    try:
        sandbox = client.create(
            CreateSandboxFromSnapshotParams(
                name=f"agui-report-integration-{uuid.uuid4().hex[:8]}",
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
        sandbox.fs.upload_file(
            b"region,amount\nEast,10\nSouth,30\n",
            f"{WORKSPACE_ROOT}/data.csv",
        )

        def run(action, payload):
            command = (
                f"python /tmp/report_runtime.py {shlex.quote(action)} "
                f"{shlex.quote(json.dumps(payload, ensure_ascii=False))}"
            )
            result = sandbox.process.exec(command, cwd=WORKSPACE_ROOT, timeout=120)
            assert result.exit_code == 0, result.result
            output = next(line for line in reversed(result.result.splitlines()) if line.strip())
            return json.loads(output)

        capabilities = run("capabilities", {})
        assert capabilities["packages"]["pandas"]

        prepared = run("prepare", {"paths": ["data.csv"]})
        failed = run(
            "analyze",
            {"job_id": prepared["jobId"], "command": "false"},
        )
        assert failed["ok"] is False

        directory = f"报表/生成结果/{prepared['jobId']}"
        markdown = (
            "# 中文智能报表\n\n"
            "|地区|金额|\n|---|---:|\n|East|10|\n|South|30|\n\n"
            "![金额](chart.png)\n"
        )
        command = (
            f"mkdir -p {shlex.quote(directory)} && "
            "python - <<'PY'\n"
            "from pathlib import Path\n"
            "import matplotlib.pyplot as plt\n"
            f"root = Path({directory!r})\n"
            "plt.bar(['East', 'South'], [10, 30])\n"
            "plt.savefig(root / 'chart.png')\n"
            "plt.close()\n"
            f"(root / 'report.md').write_text({markdown!r}, encoding='utf-8')\n"
            "print('analysis complete')\n"
            "PY"
        )
        analyzed = run(
            "analyze",
            {"job_id": prepared["jobId"], "command": command, "timeout": 60},
        )
        assert analyzed["ok"] is True
        assert analyzed["roundCount"] == 2

        rendered = run(
            "render_markdown",
            {
                "job_id": prepared["jobId"],
                "markdown_path": f"{directory}/report.md",
                "output_path": f"{directory}/report.pdf",
            },
        )
        content = WorkspaceService._download_file(
            sandbox,
            f"{WORKSPACE_ROOT}/{rendered['pdfPath']}",
            MAX_DOWNLOAD_BYTES,
        )
        reader = PdfReader(io.BytesIO(content))
        text = "".join(page.extract_text() or "" for page in reader.pages)
        assert reader.pages and "中文智能报表" in text and rendered["imageCount"] == 1
    finally:
        if sandbox is not None:
            client.delete(sandbox)
