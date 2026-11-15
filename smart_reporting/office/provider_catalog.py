"""GenOffice BYOK capability catalog; pinned source and adaptations in PROVIDERS-SOURCE.md."""

from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

Capability = Literal["imageAnalysis", "videoAnalysis", "webSearch"]
CAPABILITIES = ("imageAnalysis", "videoAnalysis", "webSearch")
# id, label, endpoint, default analysis model, protocol, video support.
_MEDIA = [
    ("openai", "OpenAI", "https://api.openai.com/v1", "gpt-5.6-luna", "openai", False),
    (
        "gemini",
        "Gemini",
        "https://generativelanguage.googleapis.com/v1beta",
        "gemini-3.8-flash",
        "gemini",
        True,
    ),
    (
        "doubao",
        "Doubao / 火山引擎",
        "https://ark.cn-beijing.volces.com/api/v3",
        "doubao-seed-2-1-pro-260915",
        "openai",
        True,
    ),
    ("glm", "GLM / 智谱", "https://open.bigmodel.cn/api/paas/v4", "glm-4.6v", "openai", True),
    ("xai", "Grok / xAI", "https://api.x.ai/v1", "grok-4.6", "openai", False),
    (
        "qwen",
        "Qwen / 阿里云",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "qwen3-vl-plus",
        "openai",
        True,
    ),
    ("minimax", "MiniMax", "https://api.minimax.io/v1", "MiniMax-M3", "openai", True),
    ("deepseek", "DeepSeek", "https://api.deepseek.com/v1", "deepseek-flash", "openai", False),
    ("custom", "OpenAI 兼容服务", "", "", "openai", False),
]
_SEARCH = [
    ("serper", "Serper", "https://google.serper.dev"),
    ("serply", "Serply", "https://api.serply.io"),
    ("searchapi", "SearchAPI", "https://www.searchapi.io"),
    ("tavily", "Tavily", "https://api.tavily.com"),
    ("parallel", "Parallel", "https://api.parallel.ai"),
    ("exa", "Exa", "https://api.exa.ai"),
    ("firecrawl", "Firecrawl", "https://api.firecrawl.dev"),
    ("keenable", "Keenable", "https://api.keenable.ai"),
]
MEDIA = {
    p[0]: dict(id=p[0], label=p[1], baseUrl=p[2], model=p[3], protocol=p[4], video=p[5])
    for p in _MEDIA
}
SEARCH = {p[0]: dict(id=p[0], label=p[1], baseUrl=p[2], model="") for p in _SEARCH}


def catalog_for(capability):
    if capability == "webSearch":
        return list(SEARCH.values())
    return [p for p in MEDIA.values() if capability == "imageAnalysis" or p["video"]]


def defaults(capability):
    provider = {"imageAnalysis": "openai", "videoAnalysis": "gemini", "webSearch": "tavily"}[
        capability
    ]
    meta = (SEARCH if capability == "webSearch" else MEDIA)[provider]
    return dict(enabled=False, provider=provider, baseUrl=meta["baseUrl"], model=meta["model"])


class ProviderInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    provider: str = Field(min_length=1, max_length=40)
    model: str = Field(default="", max_length=200, pattern=r"^[a-zA-Z0-9_.:/-]*$")
    baseUrl: str = Field(max_length=2048)
    apiKey: str | None = Field(default=None, max_length=4096)
    expectedVersion: int = Field(ge=0, strict=True)

    @field_validator("baseUrl")
    @classmethod
    def https_endpoint(cls, value):
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.port not in (None, 443)
            or any(ord(c) <= 32 for c in value)
        ):
            raise ValueError("服务地址须为无凭据的 HTTPS 地址（443 端口）。")
        return value.rstrip("/")

    @field_validator("apiKey")
    @classmethod
    def clean_key(cls, value):
        if value is not None and any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("API Key 包含无效字符。")
        return value.strip() if value is not None else None


class ProviderTestInput(ProviderInput):
    media: list[str] = Field(default_factory=list, max_length=4)
