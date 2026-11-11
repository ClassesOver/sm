"""从.env读取StarRocks连接，使用显式指定的独立管理测试库执行真实验收。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy.engine import make_url


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    management_url = os.environ.get("REPORTING_MANAGEMENT_TEST_DB_URL")
    # pytest fixture会重建管理schema，必须显式指定专用测试库。
    if not management_url or make_url(management_url).database != "management_test":
        print("请通过 REPORTING_MANAGEMENT_TEST_DB_URL 指定独立的 management_test 数据库。")
        return 2
    dsn = dotenv_values(root / ".env").get("REPORT_STARROCKS_DSN")
    if not dsn:
        print(".env 缺少 REPORT_STARROCKS_DSN。")
        return 2
    evidence = root / "output/management-upgrade/real-starrocks"
    evidence.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "REPORTING_STARROCKS_INTEGRATION_DSN": dsn,
        "REPORTING_STARROCKS_EVIDENCE_DIR": str(evidence),
    }
    return subprocess.call(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-o",
            "addopts=",
            "--tb=short",
            "smart_reporting/tests/test_management_starrocks_integration.py",
            f"--junitxml={evidence / 'junit.xml'}",
        ],
        cwd=root,
        env=env,
    )


if __name__ == "__main__":
    raise SystemExit(main())
