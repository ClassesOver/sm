FROM python:3.12-slim

WORKDIR /app

COPY agentos_dev/requirements.txt ./agentos_dev/requirements.txt
RUN pip install --no-cache-dir -r agentos_dev/requirements.txt

COPY agentos_dev ./agentos_dev

ENV AGENT_OS_HOST=0.0.0.0 \
    AGENT_OS_PORT=7777 \
    AGENT_OS_RELOAD=false \
    AGENT_DB_FILE=/data/agui_agentos.db

EXPOSE 7777

CMD ["python", "-m", "agentos_dev.app"]
