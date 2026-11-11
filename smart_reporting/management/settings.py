from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class ManagementSettings:
    public_origin: str | None = None
    static_dir: Path | None = None
    allow_local_http: bool = False

    def __post_init__(self):
        if self.public_origin is None:
            return
        url = urlsplit(self.public_origin)
        local_http = (
            self.allow_local_http
            and url.scheme == "http"
            and url.hostname
            in {
                "localhost",
                "127.0.0.1",
                "::1",
            }
        )
        if (
            not url.netloc
            or (url.scheme != "https" and not local_http)
            or url.username
            or url.password
            or url.path
            or url.query
            or url.fragment
        ):
            raise ValueError("管理公开地址须为 HTTPS Origin；本机 HTTP 须显式启用。")

    @property
    def cookie_secure(self) -> bool:
        return not self.allow_local_http or not (self.public_origin or "").startswith("http:")

    @classmethod
    def from_environment(cls):
        directory = os.getenv("AGENT_MANAGEMENT_STATIC_DIR")
        editor_directory = Path(
            os.getenv("AGENT_REPORT_EDITOR_STATIC_DIR")
            or Path(__file__).resolve().parents[1] / "report_editor/static"
        )
        return cls(
            public_origin=os.getenv("AGENT_MANAGEMENT_PUBLIC_ORIGIN") or None,
            static_dir=Path(directory) if directory else editor_directory / "management",
            allow_local_http=os.getenv("AGENT_MANAGEMENT_LOCAL_HTTP", "").lower() == "true",
        )
