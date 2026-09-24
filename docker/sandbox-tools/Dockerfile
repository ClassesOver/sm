ARG BASE_IMAGE=docker.m.daocloud.io/daytonaio/sandbox:0.5.0-slim
FROM ${BASE_IMAGE}

ARG APT_MIRROR_HOST=mirrors.aliyun.com
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

USER root

RUN sed -i \
        -e "s|deb.debian.org|${APT_MIRROR_HOST}|g" \
        -e "s|security.debian.org|${APT_MIRROR_HOST}|g" \
        /etc/apt/sources.list.d/debian.sources

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        coreutils \
        curl \
        file \
        findutils \
        git \
        ripgrep \
        sed \
        unzip \
        util-linux \
        wget \
        zip \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        diffutils \
        git-lfs \
        gzip \
        jq \
        less \
        openssh-client \
        patch \
        procps \
        psmisc \
        tar \
        xz-utils \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        fontconfig \
        fonts-liberation \
        fonts-noto-cjk \
        libcairo2 \
        libmagic1 \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        graphviz \
        librsvg2-bin \
        pandoc \
        poppler-utils \
        qpdf \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libreoffice-calc \
        libreoffice-impress \
        libreoffice-writer \
    && rm -rf /var/lib/apt/lists/*

COPY docker/sandbox-tools/requirements-docs.txt /tmp/requirements-docs.txt
COPY docker/sandbox-tools/requirements-report.txt /tmp/requirements-report.txt
COPY docker/sandbox-tools/requirements-data.txt /tmp/requirements-data.txt
COPY docker/sandbox-tools/requirements-dev.txt /tmp/requirements-dev.txt
COPY docker/sandbox-tools/requirements-db.txt /tmp/requirements-db.txt
COPY docker/sandbox-tools/matplotlibrc /tmp/matplotlibrc

RUN python -m pip install \
        --no-cache-dir \
        --disable-pip-version-check \
        --index-url "${PIP_INDEX_URL}" \
        --require-hashes \
        -r /tmp/requirements-docs.txt

RUN python -m pip install \
        --no-cache-dir \
        --disable-pip-version-check \
        --index-url "${PIP_INDEX_URL}" \
        --require-hashes \
        -r /tmp/requirements-report.txt

RUN python -m pip install \
        --no-cache-dir \
        --disable-pip-version-check \
        --index-url "${PIP_INDEX_URL}" \
        --require-hashes \
        -r /tmp/requirements-data.txt

RUN python -m pip install \
        --no-cache-dir \
        --disable-pip-version-check \
        --index-url "${PIP_INDEX_URL}" \
        --require-hashes \
        -r /tmp/requirements-dev.txt

RUN python -m pip install \
        --no-cache-dir \
        --disable-pip-version-check \
        --index-url "${PIP_INDEX_URL}" \
        --require-hashes \
        -r /tmp/requirements-db.txt

RUN python -m pip check

# forbidden 列表中的 kaleido 是本镜像（不可信代码沙箱）的刻意排除；
# 报表宿主镜像（根 Dockerfile）自 2026-09-24 起相反地 provision kaleido+Chrome，
# 供 visualization Coding 的 fig.write_image() 使用。两侧口径相反是有意的。
RUN python -c "from importlib.metadata import distributions; normalize=lambda name: name.lower().replace('_', '-').replace('.', '-'); installed={normalize(dist.metadata['Name']) for dist in distributions()}; forbidden={'adlfs', 'azure-storage-blob', 'boto3', 'catboost', 'contextily', 'distributed', 'gcsfs', 'geopy', 'google-cloud-storage', 'huggingface-hub', 'jax', 'jaxlib', 'kaleido', 'keras', 'lightgbm', 'magika', 'markitdown', 'mlflow', 'newspaper3k', 'nltk', 'onnxruntime', 'osmnx', 'pandas-datareader', 'playwright', 'pyppeteer', 's3fs', 'scikit-learn', 'selenium', 'sentence-transformers', 'spacy', 'tensorflow', 'torch', 'trafilatura', 'transformers', 'webdriver-manager', 'xgboost', 'yfinance'}; found=installed & forbidden; assert not found, f'forbidden packages: {sorted(found)}'"

RUN python -c "import IPython, adjustText, altair, babel, bokeh, bs4, build, cairosvg, clickhouse_connect, coverage, cssselect, cssutils, cv2, dask, dateparser, deepdiff, defusedxml, docutils, docx, docx2python, docxcompose, docxtpl, ebooklib, faker, fitz, formulas, fpdf, freezegun, frontmatter, geopandas, graphviz, great_tables, h5py, holidays, html2text, html5lib, httpx, hypothesis, ipykernel, jieba, jinja2, jmespath, json_repair, jsonlines, jsonschema, libcst, lxml, magic, mammoth, markdown, matplotlib, mdit_py_plugins, msoffcrypto, msgpack, mypy, mysql.connector, nbclient, nbconvert, nbformat, neo4j, networkx, numpy, odf, openpyxl, orjson, pandas, pdfplumber, picosvg, pikepdf, PIL, plotly, plotnine, polars, psycopg, pptx, premailer, pulp, py7zr, pyarrow, pydantic, pygal, pymongo, pymysql, pypandoc, pypdf, pypinyin, pyproj, pyreadstat, pytest, pytest_asyncio, pytest_cov, pytest_mock, python_calamine, qrcode, radon, rapidfuzz, readability, redis, reportlab, requests, responses, respx, rich, roman, rst2pdf, scipy, scour, seaborn, selectolax, shapely, skimage, sqlalchemy, sqlglot, starrocks, statsmodels, svglib, svgpathtools, svgwrite, sympy, tenacity, tomli_w, tomlkit, tqdm, trino, typer, vl_convert, weasyprint, wordcloud, xarray, xdist, xlsx2csv, xlsxwriter, xlrd, xmldiff, xmlschema, xmltodict, yaml, zarr"

RUN command -v bash cairosvg cmp coverage curl diff dot file find git git-lfs gzip head ipython jq jupyter-nbconvert less libreoffice mypy pandoc patch pdfinfo pdftoppm pdftotext ps pstree pyproject-build pytest qpdf radon rg rst2pdf rsvg-convert ruff scour script sed sha256sum soffice sort ssh ssh-keyscan stat stty tail tar timeout wc wget xlsx2csv xz

RUN install -d -o daytona -g daytona \
        /home/daytona/.cache/matplotlib \
        /home/daytona/.config/libreoffice \
    && install -o daytona -g daytona /tmp/matplotlibrc /home/daytona/.cache/matplotlib/matplotlibrc \
    && rm /tmp/matplotlibrc \
    && rm /tmp/requirements-docs.txt \
    && rm /tmp/requirements-report.txt \
    && rm /tmp/requirements-data.txt \
    && rm /tmp/requirements-dev.txt \
    && rm /tmp/requirements-db.txt

ENV HOME=/home/daytona \
    XDG_CACHE_HOME=/home/daytona/.cache \
    XDG_CONFIG_HOME=/home/daytona/.config \
    MPLCONFIGDIR=/home/daytona/.cache/matplotlib \
    MPLBACKEND=Agg \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    SAL_USE_VCLPLUGIN=svp

USER daytona
