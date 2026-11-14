"""配置导入命令无需登记或提供组织。"""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from smart_reporting.management import cli


def test_import_cli_accepts_only_directory_and_dry_run(monkeypatch):
    run = AsyncMock(return_value={"dryRun": True})
    monkeypatch.setattr(cli, "run", run)
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    monkeypatch.setattr("sys.argv", ["management", "import-config", "--directory", "/tmp/config", "--dry-run"])
    cli.main()
    run.assert_awaited_once_with("import-config", directory=Path("/tmp/config"), dry_run=True)


def test_import_cli_does_not_offer_organization_switching(monkeypatch):
    monkeypatch.setattr("sys.argv", ["management", "import-config", "--directory", "/tmp/config", "--company-id", "foreign"])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
