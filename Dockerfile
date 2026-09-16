ARG PYTHON_IMAGE=docker.m.daocloud.io/library/python:3.12-slim
ARG UV_IMAGE=ghcr.m.daocloud.io/astral-sh/uv:0.11.26
ARG NODE_IMAGE=docker.m.daocloud.io/library/node:22-slim
FROM ${PYTHON_IMAGE} AS base

ARG APT_MIRROR_HOST=mirrors.aliyun.com

RUN sed -i \
        -e "s|deb.debian.org|${APT_MIRROR_HOST}|g" \
        -e "s|security.debian.org|${APT_MIRROR_HOST}|g" \
        /etc/apt/sources.list.d/debian.sources

FROM ${UV_IMAGE} AS uv-source

FROM ${NODE_IMAGE} AS report-editor-frontend

ARG NPM_REGISTRY=https://registry.npmmirror.com

WORKDIR /build/frontend

COPY smart_reporting/report_editor/frontend/package.json \
    smart_reporting/report_editor/frontend/package-lock.json ./
RUN npm ci --registry="${NPM_REGISTRY}"

COPY smart_reporting/report_editor/frontend ./
RUN npm run build

FROM base AS env-init

WORKDIR /workspace

RUN apt-get update \
    && apt-get install -y --no-install-recommends apache2-utils bash coreutils mawk openssl \
    && rm -rf /var/lib/apt/lists/*

FROM base AS runtime

ARG UV_DEFAULT_INDEX=https://mirrors.aliyun.com/pypi/simple/

COPY --from=uv-source /uv /uvx /bin/

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
RUN UV_DEFAULT_INDEX="${UV_DEFAULT_INDEX}" UV_PROJECT_ENVIRONMENT=/app/.venv \
    uv sync --frozen --no-dev --no-install-project

COPY smart_reporting ./smart_reporting
COPY --from=report-editor-frontend /build/static ./smart_reporting/report_editor/static

ENV AGENT_OS_HOST=0.0.0.0 \
    AGENT_OS_PORT=7777 \
    AGENT_OS_WORKERS=1 \
    AGENT_OS_RELOAD=false \
    AGENT_OS_ACCESS_LOG=true \
    AGENT_DEBUG=false

EXPOSE 7777

CMD ["/app/.venv/bin/python", "-m", "smart_reporting.app"]
