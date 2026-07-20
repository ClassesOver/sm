ARG BASE_IMAGE=docker.m.daocloud.io/daytonaio/sandbox:0.5.0-slim
FROM ${BASE_IMAGE}

ARG APT_MIRROR_HOST=mirrors.aliyun.com
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

USER root

RUN sed -i \
        -e "s|deb.debian.org|${APT_MIRROR_HOST}|g" \
        -e "s|security.debian.org|${APT_MIRROR_HOST}|g" \
        /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        file \
        fontconfig \
        fonts-liberation \
        fonts-noto-cjk \
        libcairo2 \
        libmagic1 \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libreoffice-calc \
        libreoffice-impress \
        libreoffice-writer \
        pandoc \
        poppler-utils \
        qpdf \
        shared-mime-info \
        unzip \
        zip \
    && rm -rf /var/lib/apt/lists/*

COPY docker/sandbox-tools/requirements.txt /tmp/requirements-tools.txt

RUN python -m pip install \
        --no-cache-dir \
        --disable-pip-version-check \
        --index-url "${PIP_INDEX_URL}" \
        --require-hashes \
        -r /tmp/requirements-tools.txt \
    && python -m pip check \
    && python -c "import babel, bs4, cairosvg, dateparser, deepdiff, docx, fitz, frontmatter, html5lib, httpx, jinja2, jmespath, json_repair, jsonschema, lxml, magic, magika, mammoth, markdown, markitdown, matplotlib, networkx, numpy, odf, openpyxl, orjson, pandas, pdfplumber, pikepdf, PIL, plotly, polars, pptx, py7zr, pyarrow, pypandoc, pypdf, rapidfuzz, reportlab, requests, rich, scipy, seaborn, sklearn, statsmodels, sympy, tomli_w, tqdm, weasyprint, xlsxwriter, xlrd, yaml" \
    && command -v cairosvg libreoffice magika markitdown pandoc pdfinfo pdftotext qpdf \
    && install -d -o daytona -g daytona \
        /home/daytona/.cache/matplotlib \
        /home/daytona/.config/libreoffice \
    && rm /tmp/requirements-tools.txt

ENV HOME=/home/daytona \
    XDG_CACHE_HOME=/home/daytona/.cache \
    XDG_CONFIG_HOME=/home/daytona/.config \
    MPLCONFIGDIR=/home/daytona/.cache/matplotlib \
    LANG=en_US.UTF-8 \
    LC_ALL=en_US.UTF-8 \
    SAL_USE_VCLPLUGIN=svp

USER daytona
