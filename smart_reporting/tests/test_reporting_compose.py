from pathlib import Path

import yaml


def test_reporting_compose_uses_package_entrypoint():
    compose_path = Path(__file__).parents[2] / "docker-compose-reporting.yml"
    compose = yaml.load(compose_path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

    assert compose["services"]["reporting-os"]["command"] == [
        "python",
        "-m",
        "smart_reporting.app",
    ]
    assert compose["services"]["reporting-os"]["environment"]["AGENT_OS_WORKERS"] == "1"
