#!/bin/sh
# InfinityRoleplay launcher: loads .env (secrets, never committed) then starts the app.
cd "$(dirname "$0")"
if [ -f .env ]; then set -a; . ./.env; set +a; fi
exec python3 ollama_chat.py
