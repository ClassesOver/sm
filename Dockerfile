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

# 保持与源码相同的相对层级，让浏览器和 Node 桥接使用同一固定版本引擎。
WORKDIR /build/smart_reporting/reporting/workbook_engine
COPY smart_reporting/reporting/workbook_engine ./
COPY docker/package-office-engine.mjs /build/package-office-engine.mjs
# 桥接脚本预先打包，运行时不再逐次转译 TypeScript。
RUN npm ci --registry="${NPM_REGISTRY}" \
    && npm run bundle:bridges -- --metafile=dist/metafile.json \
    && node /build/package-office-engine.mjs . /runtime/reporting-workbook-engine

WORKDIR /build/smart_reporting/reporting/slides_engine
COPY smart_reporting/reporting/slides_engine/package.json \
    smart_reporting/reporting/slides_engine/package-lock.json \
    smart_reporting/reporting/slides_engine/tsconfig.base.json ./
COPY smart_reporting/reporting/slides_engine/LICENSE \
    smart_reporting/reporting/slides_engine/NOTICE \
    smart_reporting/reporting/slides_engine/SOURCE.md ./
COPY smart_reporting/reporting/slides_engine/packages ./packages
COPY smart_reporting/reporting/slides_engine/bridge ./bridge
RUN npm ci --registry="${NPM_REGISTRY}" \
    && npm run test --workspace @genoffice/pipelines \
    && npm run typecheck --workspace @genoffice/pipelines \
    && npm run bundle:bridges -- --metafile=dist/metafile.json \
    && node /build/package-office-engine.mjs . /runtime/reporting-slides-engine

# 前端按源码相对路径复用冻结的 GenOffice 类型和浏览器渲染模块。
WORKDIR /build/smart_reporting/report_editor/frontend
COPY smart_reporting/report_editor/frontend/package.json \
    smart_reporting/report_editor/frontend/package-lock.json ./
RUN npm ci --registry="${NPM_REGISTRY}"
COPY smart_reporting/report_editor/frontend ./
RUN npm run build && npm run build:slides

# COPY smart_reporting 会再次带入引擎源码；在独立构建层裁剪，避免镜像层仍保存副本。
FROM base AS app-source
COPY smart_reporting /app/smart_reporting
RUN find /app/smart_reporting/reporting/slides_engine /app/smart_reporting/reporting/workbook_engine \
        -type f ! -iname '*license*' ! -iname '*notice*' ! -iname '*copying*' ! -iname '*copyright*' \
        ! -name 'SOURCE*' ! -name 'UPSTREAM*' -delete \
    && find /app/smart_reporting/reporting/slides_engine /app/smart_reporting/reporting/workbook_engine \
        -depth -type d -empty -delete

FROM base AS env-init

WORKDIR /workspace

RUN apt-get update \
    && apt-get install -y --no-install-recommends apache2-utils bash coreutils mawk openssl \
    && rm -rf /var/lib/apt/lists/*

FROM base AS runtime

ARG UV_DEFAULT_INDEX=https://mirrors.aliyun.com/pypi/simple/
ARG PYPI_FILES_MIRROR=https://mirrors.aliyun.com/pypi

COPY --from=uv-source /uv /uvx /bin/
COPY --from=report-editor-frontend /usr/local /usr/local
COPY --from=report-editor-frontend /runtime/reporting-slides-engine /opt/reporting-slides-engine
COPY --from=report-editor-frontend /runtime/reporting-workbook-engine /opt/reporting-workbook-engine

WORKDIR /app

# libharfbuzz-subset0：WeasyPrint 用 HarfBuzz 做 PDF 字体子集化；缺失时回退纯 Python 的
# fontTools，Noto CJK 每个字重约 3 秒，整份报告 PDF 由约 27 秒变约 8 秒。
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        fontconfig fonts-liberation fonts-noto-cjk git \
        libcairo2 libmagic1 libpango-1.0-0 libpangoft2-1.0-0 shared-mime-info \
        libharfbuzz-subset0 \
        graphviz librsvg2-bin pandoc poppler-utils qpdf \
        libreoffice-calc libreoffice-impress libreoffice-writer \
        chromium \
        libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
        libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
RUN sed -i "s|https://files.pythonhosted.org|${PYPI_FILES_MIRROR}|g" uv.lock
RUN UV_DEFAULT_INDEX="${UV_DEFAULT_INDEX}" UV_PROJECT_ENVIRONMENT=/app/.venv \
    uv sync --frozen --no-dev --no-install-project

RUN for tool in pandoc soffice pdftoppm pdfinfo dot rsvg-convert qpdf; do command -v "$tool" || exit 1; done \
    && /app/.venv/bin/python -c "import docx, matplotlib, pypandoc, pypdf, scipy, seaborn, statsmodels, sympy, tabulate, adjustText, altair, bokeh, plotnine, pygal, graphviz, PIL, xlsxwriter, odf, pptx, reportlab, pdfplumber, pymupdf, pikepdf, cairosvg, bs4, jinja2, pyarrow, duckdb; from weasyprint import HTML" \
    && /app/.venv/bin/python -c "import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt; figure = plt.figure(); figure.add_subplot(111).plot([1], [1]); figure.savefig('/tmp/matplotlib-smoke.png'); plt.close(figure)"

COPY --from=app-source /app/smart_reporting ./smart_reporting
COPY docker/matplotlibrc /etc/reporting/matplotlibrc
# 前端产物放在源码目录之外：Compose 以只读 bind mount 覆盖 /app/smart_reporting，
# 若放在源码树内会被宿主空目录遮蔽；命名卷又只在首次创建时播种，升级镜像后仍是旧前端。
COPY --from=report-editor-frontend /build/smart_reporting/report_editor/static /opt/report-editor-static

ENV AGENT_OS_HOST=0.0.0.0 \
    AGENT_REPORTING_SLIDES_ENGINE_DIR=/opt/reporting-slides-engine \
    AGENT_REPORTING_WORKBOOK_ENGINE_DIR=/opt/reporting-workbook-engine \
    AGENT_REPORT_EDITOR_STATIC_DIR=/opt/report-editor-static \
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
