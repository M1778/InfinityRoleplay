# ♾️ InfinityRoleplay

Private, local-first AI roleplay studio. Your characters, your machine, your rules.

> 🔞 **18+ DISCLAIMER — READ FIRST**
>
> InfinityRoleplay is intended **strictly for adults aged 18 and over**.
> It includes an optional **18+ mode** that unlocks mature character dynamics,
> which can be enabled per character via the persona settings and/or the
> system prompt. By using this software you confirm that you are of legal
> adult age in your jurisdiction.
>
> Even in 18+ mode, hard boundaries always apply: **all characters must be
> adults (18+)** — the app validates a minimum age of 18 and refuses younger
> ages; no sexual content involving minors, no non-consensual content, no
> graphic sexual content involving real people. Image generation runs with
> `nsfw:false` + censoring enabled. If you fork or redistribute this project,
> keep this disclaimer intact.

## What it is

- 💬 Chat UI served locally, powered by **your own Ollama models** — no accounts, no keys, no rate limits, no cloud.
- 🎭 Persona studio (appearance, dynamics, scene) + 🎬 Director controls (reply length, dialogue balance, pacing, hooks) compiled into the system prompt.
- 🖼️ Scene illustration via a hapuppy-hosted image model (default
  `gemini-3.1-flash-image`). Needs `HAPUPPY_KEY` — put it in `.env`
  (see below). Never commit keys.
- 🧠 Fact-ledger memory, recall search, reply regeneration with variants, on-device TTS.

## Quick start

```bash
ollama serve                      # separate terminal, if not running
ollama pull mistral-nemo:12b      # or any chat model you like
cp .env.example .env 2>/dev/null; ${EDITOR:-nano} .env   # add HAPUPPY_KEY for images
./start.sh                        # loads .env, runs the app (stdlib only)
# open http://localhost:8777
```

Docker:

```bash
docker compose up --build
```

## Project layout

| File | Purpose |
| ---- | ------- |
| `ollama_chat.py` | The whole app (stdlib server + UI). Current integration target. |
| `glm_roleplay_chat.py` / `rp_chat.py` | Legacy terminal clients (Puter / Pollinations). |
| `glm_roleplay_chat.html` | Legacy browser client. |

## Contributing

Open an issue or PR. Keep the 18+ disclaimer intact in any redistribution.
Adult-only: do not submit characters coded as minors, and do not attempt to
weaken the age validation or the hard content boundaries.

## License

MIT — see `LICENSE`.
