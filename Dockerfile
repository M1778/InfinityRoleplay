# InfinityRoleplay — stdlib-only server, no pip install needed.
FROM python:3.12-slim

# Create unprivileged user
RUN useradd -m -u 1000 appuser && \
    mkdir -p /data && chown -R appuser:appuser /data
WORKDIR /app

# Only the runtime files. No secrets, no build tools, no caches in layers.
COPY ollama_chat.py db.py ui.html ./
RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8777
VOLUME /data

ENV OLLAMA_HOST=http://host.docker.internal:11434 \
    DB_PATH=/data/infinity.db \
    HOST=0.0.0.0 \
    CHAT_PORT=8777 \
    PYTHONUNBUFFERED=1

# Native Docker healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8777/api/health', timeout=3)" || exit 1

CMD ["python3", "ollama_chat.py"]
