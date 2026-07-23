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
        bash \
        coreutils \
        file \
        findutils \
        fontconfig \
        fonts-liberation \
        fonts-noto-cjk \
        git \
        graphviz \
        libcairo2 \
        libmagic1 \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        librsvg2-bin \
        libreoffice-calc \
        libreoffice-impress \
        libreoffice-writer \
        pandoc \
        poppler-utils \
        qpdf \
        ripgrep \
        sed \
        shared-mime-info \
        unzip \
        util-linux \
        zip \
    && rm -rf /var/lib/apt/lists/*

COPY docker/sandbox-tools/requirements.txt /tmp/requirements-tools.txt
COPY docker/sandbox-tools/matplotlibrc /tmp/matplotlibrc

RUN python -m pip install \
        --no-cache-dir \
        --disable-pip-version-check \
        --index-url "${PIP_INDEX_URL}" \
        --require-hashes \
        -r /tmp/requirements-tools.txt \
    && python -m pip check \
    && python -c "from importlib.metadata import distributions; normalize=lambda name: name.lower().replace('_', '-').replace('.', '-'); installed={normalize(dist.metadata['Name']) for dist in distributions()}; forbidden={'adlfs', 'azure-storage-blob', 'boto3', 'catboost', 'contextily', 'distributed', 'gcsfs', 'geopy', 'google-cloud-storage', 'huggingface-hub', 'jax', 'jaxlib', 'kaleido', 'keras', 'lightgbm', 'magika', 'markitdown', 'mlflow', 'newspaper3k', 'nltk', 'onnxruntime', 'osmnx', 'pandas-datareader', 'playwright', 'pyppeteer', 's3fs', 'scikit-learn', 'selenium', 'sentence-transformers', 'spacy', 'tensorflow', 'torch', 'trafilatura', 'transformers', 'webdriver-manager', 'xgboost', 'yfinance'}; found=installed & forbidden; assert not found, f'forbidden packages: {sorted(found)}'" \
    && python -c "import IPython, adjustText, altair, babel, bokeh, bs4, build, cairosvg, coverage, cssselect, cssutils, cv2, dask, dateparser, deepdiff, defusedxml, docutils, docx, docx2python, docxcompose, docxtpl, ebooklib, faker, fitz, formulas, fpdf, freezegun, frontmatter, geopandas, graphviz, great_tables, h5py, holidays, html2text, html5lib, httpx, hypothesis, ipykernel, jieba, jinja2, jmespath, json_repair, jsonlines, jsonschema, libcst, lxml, magic, mammoth, markdown, matplotlib, mdit_py_plugins, msoffcrypto, msgpack, mypy, nbclient, nbconvert, nbformat, networkx, numpy, odf, openpyxl, orjson, pandas, pdfplumber, picosvg, pikepdf, PIL, plotly, plotnine, polars, pptx, premailer, pulp, py7zr, pyarrow, pydantic, pygal, pypandoc, pypdf, pypinyin, pyproj, pyreadstat, pytest, pytest_asyncio, pytest_cov, pytest_mock, python_calamine, qrcode, radon, rapidfuzz, readability, reportlab, requests, responses, respx, rich, roman, rst2pdf, scipy, scour, seaborn, selectolax, shapely, skimage, sqlalchemy, sqlglot, statsmodels, svglib, svgpathtools, svgwrite, sympy, tenacity, tomli_w, tomlkit, tqdm, typer, vl_convert, weasyprint, wordcloud, xarray, xdist, xlsx2csv, xlsxwriter, xlrd, xmldiff, xmlschema, xmltodict, yaml, zarr" \
    && command -v bash cairosvg coverage dot file find git head ipython jupyter-nbconvert libreoffice mypy pandoc pdfinfo pdftoppm pdftotext pyproject-build pytest qpdf radon rg rst2pdf rsvg-convert ruff scour script sed sha256sum sort stat stty tail timeout wc xlsx2csv \
    && install -d -o daytona -g daytona \
        /home/daytona/.cache/matplotlib \
        /home/daytona/.config/libreoffice \
    && install -o daytona -g daytona /tmp/matplotlibrc /home/daytona/.cache/matplotlib/matplotlibrc \
    && rm /tmp/matplotlibrc \
    && rm /tmp/requirements-tools.txt

ENV HOME=/home/daytona \
    XDG_CACHE_HOME=/home/daytona/.cache \
    XDG_CONFIG_HOME=/home/daytona/.config \
    MPLCONFIGDIR=/home/daytona/.cache/matplotlib \
    MPLBACKEND=Agg \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    SAL_USE_VCLPLUGIN=svp

USER daytona
