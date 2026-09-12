# InfinityRoleplay — stdlib-only server, no pip install needed.
FROM python:3.12-slim

WORKDIR /app

# Only the two runtime files. No secrets, no build tools, no caches in layers.
COPY ollama_chat.py db.py ./

# Server patch required: db import must be lazy/optional so a bare
# `python3 ollama_chat.py` (no db.py present) still runs. Use exactly:
#   try:
#       import db
#       db.init()
#   except Exception:
#       db = None
# and guard every db use with `if db is None: ...`.
# Also read bind host from env (default keeps local behavior):
#   HOST = os.environ.get("HOST", "127.0.0.1")

EXPOSE 8777
VOLUME /data

ENV OLLAMA_HOST=http://host.docker.internal:11434 \
    DB_PATH=/data/infinity.db \
    HOST=0.0.0.0 \
    CHAT_PORT=8777 \
    PYTHONUNBUFFERED=1

CMD ["python3", "ollama_chat.py"]
