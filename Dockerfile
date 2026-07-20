ARG PYTHON_IMAGE=docker.m.daocloud.io/library/python:3.12-slim
FROM ${PYTHON_IMAGE} AS base

ARG APT_MIRROR_HOST=mirrors.aliyun.com

RUN sed -i \
        -e "s|deb.debian.org|${APT_MIRROR_HOST}|g" \
        -e "s|security.debian.org|${APT_MIRROR_HOST}|g" \
        /etc/apt/sources.list.d/debian.sources

FROM base AS env-init

WORKDIR /workspace

RUN apt-get update \
    && apt-get install -y --no-install-recommends apache2-utils bash coreutils mawk openssh-client openssl \
    && rm -rf /var/lib/apt/lists/*

FROM base AS runtime

ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

COPY agentos_dev/requirements.txt ./agentos_dev/requirements.txt
RUN pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" -r agentos_dev/requirements.txt

COPY agentos_dev ./agentos_dev

ENV AGENT_OS_HOST=0.0.0.0 \
    AGENT_OS_PORT=7777 \
    AGENT_OS_WORKERS=4 \
    AGENT_OS_RELOAD=false \
    AGENT_OS_ACCESS_LOG=true \
    AGENT_DEBUG=false

EXPOSE 7777

CMD ["python", "-m", "agentos_dev.app"]
