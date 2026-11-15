from fastapi import FastAPI
from fastapi.testclient import TestClient

from smart_reporting.office_entry import create_office_entry_router


def test_office_entry_keeps_assets_and_retires_report_editor(tmp_path):
    (tmp_path / "office.html").write_text("Office workspace", encoding="utf-8")
    (tmp_path / "native.html").write_text("Native editor", encoding="utf-8")
    app = FastAPI()
    app.include_router(create_office_entry_router(static_dir=tmp_path))
    with TestClient(app) as client:
        assert client.get("/office").text == "Office workspace"
        assert client.get("/reports/v1/editor/assets/native.html").text == "Native editor"
        for method, path in (
            ("GET", "/reports/v1/editor/open/retired-grant"),
            ("GET", "/reports/v1/editor/report/2"),
            ("GET", "/reports/v1/editor/report/2/api/document"),
            ("GET", "/reports/v1/editor/report/2/export"),
            ("PUT", "/reports/v1/editor/report/2/api/document"),
            ("POST", "/reports/v1/editor/report/2/api/export"),
            ("POST", "/reports/v1/editor/report/2/api/native/open"),
        ):
            response = client.request(method, path)
            assert response.status_code == 410
            assert response.json()["detail"]["code"] == "report_editor_retired"
            assert response.headers["cache-control"] == "no-store"
        assert client.get("/reports/v1/editor/assets/missing.js").status_code == 404
