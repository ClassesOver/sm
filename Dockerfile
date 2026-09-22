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
    && apt-get install -y --no-install-recommends \
        fontconfig fonts-liberation fonts-noto-cjk git \
        libcairo2 libmagic1 libpango-1.0-0 libpangoft2-1.0-0 shared-mime-info \
        graphviz librsvg2-bin pandoc poppler-utils qpdf \
        libreoffice-calc libreoffice-impress libreoffice-writer \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
RUN UV_DEFAULT_INDEX="${UV_DEFAULT_INDEX}" UV_PROJECT_ENVIRONMENT=/app/.venv \
    uv sync --frozen --no-dev --no-install-project

RUN for tool in pandoc soffice pdftoppm pdfinfo dot rsvg-convert qpdf; do command -v "$tool" || exit 1; done \
    && /app/.venv/bin/python -c "import docx, matplotlib, pypandoc, pypdf, scipy, seaborn, statsmodels, sympy, tabulate, adjustText, altair, bokeh, plotnine, pygal, graphviz, PIL, xlsxwriter, odf, pptx, reportlab, pdfplumber, pymupdf, pikepdf, cairosvg, bs4, jinja2, pyarrow, duckdb; from weasyprint import HTML"

COPY smart_reporting ./smart_reporting
COPY docker/sandbox-tools/matplotlibrc /etc/reporting/matplotlibrc
COPY --from=report-editor-frontend /build/static ./smart_reporting/report_editor/static

ENV AGENT_OS_HOST=0.0.0.0 \
    MPLCONFIGDIR=/tmp/reporting-matplotlib \
    MPLBACKEND=Agg \
    MATPLOTLIBRC=/etc/reporting/matplotlibrc \
    REPORTING_HOST_WORKSPACE_ROOT=/tmp/smart-reporting-workspaces \
    SAL_USE_VCLPLUGIN=svp \
    AGENT_OS_PORT=7777 \
    AGENT_OS_WORKERS=1 \
    AGENT_OS_RELOAD=false \
    AGENT_OS_ACCESS_LOG=true \
    AGENT_DEBUG=false

EXPOSE 7777

CMD ["/app/.venv/bin/python", "-m", "smart_reporting.app"]
