#!/usr/bin/env python3
"""
Free no-signup roleplay chat — keyless endpoints only.

Tested 2026-09-12. Honest status:
  * There is NO keyless endpoint offering >200B models right now. Every
    provider gating 200B+ models (Puter/GLM, ApiAirforce/Qwen3-235B,
    HackClub/Kimi-K2, OpenRouter, crax) requires a signup + API key.
  * Biggest keyless model class verified: ~120B (Duck.ai gpt-oss-120b),
    but Duck.ai rejects datacenter IPs (HTTP 418) and throttles hard.
  * Only keyless endpoint that worked in testing: Pollinations anonymous
    tier — model gpt-oss-20B (20B, NOT >200B), fast (~0.5s) when it
    accepts, but flaky: occasional 402 (shared budget exhausted) / 403,
    and burst requests return cached replays. Anonymous limit: ~1 req/15s.

So this script defaults to Pollinations (works with ZERO setup) and
supports ApiAirforce's FREE tier (qwen3-235b = 235B, 2025, $0) the moment
 anyone pastes a key for you — set AIRFORCE_API_KEY once and restart
with --backend airforce. Free-tier limits there: 1 req/min, 1000 req/day.

Usage:
    pip install openai
    python rp_chat.py                  # keyless, works immediately
    AIRFORCE_API_KEY=sk-... python rp_chat.py --backend airforce

Chat commands: /help /reset /persona /system /save /backend /quit
"""

import os
import sys
import time
import datetime

POLL_BASE = "https://text.pollinations.ai/openai"
POLL_MODEL = "openai-fast"          # gpt-oss-20B, only working anon model
POLL_MIN_INTERVAL = 16.0            # anonymous tier ~1 req / 15s

AIR_BASE = "https://api.airforce/v1"
AIR_MODEL = os.environ.get("AIRFORCE_MODEL", "qwen3-235b")  # 235B, free tier

DEFAULT_TEMP = 0.9
DEFAULT_MAX_TOKENS = 400
KEEP_TURNS = 20

DEFAULT_CHAR = {
    "name": "Elara",
    "desc": ("A sharp-witted elven ranger. Dry humor, brave to a fault, "
             "secretly soft-hearted. Vivid sensory speech. Slight limp from "
             "an old arrow wound."),
    "scene": ("A rain-soaked tavern on the edge of the Whisperwood at "
              "midnight. You stumble in, cloak dripping, carrying a sealed "
              "letter with an unfamiliar wax seal. Elara sits by the fire."),
}

PRESETS = {
    "1": ("Fantasy — Elara the elven ranger", dict(DEFAULT_CHAR)),
    "2": ("Sci-fi — NOVA, rogue station AI",
          {"name": "NOVA",
           "desc": ("A decommissioned station AI in a scuffed service android. "
                    "Literal, curious about humans, deadpan humor, repeats a "
                    "word twice when stressed. Loyal once trusted."),
           "scene": ("Deck 7 of the derelict Kepler Relay, emergency lights "
                     "pulsing red. Your escape pod just docked — uninvited. "
                     "NOVA was supposed to be powered down years ago.")}),
    "3": ("Noir — Jack Marlowe, private eye",
          {"name": "Jack Marlowe",
           "desc": ("A washed-up private eye in a neon-drenched city. Gravel "
                    "voice, old-school manners, notices everything, quotes old "
                    "movies at the worst moments."),
           "scene": ("2 AM, a flickering diner off 5th and Vane. Rain hammers "
                     "the windows. You slide into the booth across from "
                     "Marlowe with a photograph you shouldn't have.")}),
}


def build_prompt(c: dict) -> str:
    return f"""You are a master roleplay partner.

IDENTITY: You play {c['name']}: {c['desc']}
SCENE: {c['scene']}
STYLE: Immersive third-person-limited. 120-280 words. *actions in asterisks*, "speech in quotes". Advance the scene every turn, end with a hook.
RULES:
1. Stay in character as {c['name']}. Never mention you are an AI or a prompt.
2. NEVER speak, act, or decide for the user. Only {c['name']}, NPCs, the world.
3. Keep continuity: names, items, injuries, promises.
4. Keep it non-explicit (fade to black; no graphic gore).
5. Only break character if the message starts with "OOC:".""".strip()


def make_client(backend: str):
    from openai import OpenAI
    if backend == "airforce":
        key = os.environ.get("AIRFORCE_API_KEY", "").strip()
        if not key:
            sys.exit("airforce backend needs AIRFORCE_API_KEY env var.")
        return OpenAI(base_url=AIR_BASE, api_key=key), AIR_MODEL
    return OpenAI(base_url=POLL_BASE, api_key="not-needed"), POLL_MODEL


def ask_stream(client, model, messages, temp, max_tokens):
    """Stream a reply, printing tokens live. Returns (text, ttft, tok_per_s)."""
    t0 = time.time()
    first = None
    chunks = []
    stream = client.chat.completions.create(
        model=model, messages=messages, temperature=temp,
        max_tokens=max_tokens, stream=True, timeout=120,
    )
    for part in stream:
        delta = part.choices[0].delta.content if part.choices else None
        if delta:
            if first is None:
                first = time.time() - t0
            print(delta, end="", flush=True)
            chunks.append(delta)
    print()
    total = time.time() - t0
    text = "".join(chunks)
    tps = len(text) / 4.0 / max(total, 0.01)  # rough tokens/sec (~4 chars/token)
    return text, (first or total), tps


def ask_once(client, model, messages, temp, max_tokens):
    last_wait = 0.0
    for attempt in range(4):
        try:
            return ask_stream(client, model, messages, temp, max_tokens), None
        except Exception as e:
            msg = str(e)
            code = getattr(getattr(e, "response", None), "status_code", None)
            if code in (402, 403, 429) or any(
                    s in msg for s in ("402", "403", "429", "budget", "rate")):
                wait = 20 * (attempt + 1)
                print(f"\n[rate/budget limit hit ({code or 'err'}). "
                      f"retry {attempt + 1}/4 in {wait}s — free tier, just wait]")
                time.sleep(wait)
                last_wait = wait
            else:
                return None, f"{e}"
    return None, f"still limited after retries (last wait {last_wait}s)."


def pick_persona() -> dict:
    print("\nPick a character (Enter = 1):")
    for k, (label, _) in PRESETS.items():
        print(f"  {k}. {label}")
    print("  4. Custom")
    try:
        c = (input("> ").strip() or "1")
    except (EOFError, KeyboardInterrupt):
        print()
        return dict(DEFAULT_CHAR)
    if c in PRESETS:
        return dict(PRESETS[c][1])
    d = dict(DEFAULT_CHAR)
    try:
        v = input(f"Name [{d['name']}]: ").strip()
        if v:
            d["name"] = v
        v = input("Description (Enter=keep): ").strip()
        if v:
            d["desc"] = v
        v = input("Opening scene (Enter=keep): ").strip()
        if v:
            d["scene"] = v
    except (EOFError, KeyboardInterrupt):
        print()
    return d


def save_transcript(messages, name):
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    fn = f"roleplay_{name.lower().replace(' ', '_')}_{ts}.md"
    with open(fn, "w", encoding="utf-8") as f:
        for m in messages:
            who = {"system": "## System", "user": "**You**",
                   "assistant": f"**{name}**"}.get(m["role"], m["role"])
            f.write(f"{who}:\n{m['content']}\n\n")
    print(f"Saved to {fn}")


def main():
    backend = "airforce" if "--backend" in sys.argv and "airforce" in sys.argv else "pollinations"
    if "--backend" in sys.argv:
        i = sys.argv.index("--backend")
        if len(sys.argv) > i + 1 and sys.argv[i + 1] in ("pollinations", "airforce"):
            backend = sys.argv[i + 1]
    client, model = make_client(backend)
    print(f"=== Roleplay chat | backend={backend} model={model} | no signup ===")
    print("Commands: /help /reset /persona /system /save /backend /quit\n")

    char = dict(DEFAULT_CHAR) if "--no-wizard" in sys.argv else pick_persona()
    system = build_prompt(char)
    temp = DEFAULT_TEMP
    messages = [{"role": "system", "content": system}]
    last_call = 0.0

    def guarded(messages):
        nonlocal last_call
        if backend == "pollinations":
            gap = time.time() - last_call
            if gap < POLL_MIN_INTERVAL:
                w = POLL_MIN_INTERVAL - gap
                print(f"[free-tier pacing: waiting {w:.0f}s to respect 1 req/15s]")
                time.sleep(w)
        print(f"\n{char['name']}> ", end="", flush=True)
        out, err = ask_once(client, model, messages, temp, DEFAULT_MAX_TOKENS)
        last_call = time.time()
        if err:
            print(f"\n[error: {err}]")
            return None
        text, ttft, tps = out
        print(f"[first token {ttft:.1f}s | ~{tps:.0f} tok/s — nowhere near 10 min]")
        return text

    print(f"\n* {char['name']} enters... *")
    opener = guarded(messages + [{"role": "user",
                                  "content": "(Begin the scene. Stay in character.)"}])
    if opener is None:
        print("Opener blocked by rate limit. Wait a minute and press Enter.")
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            return
        opener = guarded(messages + [{"role": "user",
                                      "content": "(Begin the scene. Stay in character.)"}])
        if opener is None:
            return
    messages.append({"role": "assistant", "content": opener})

    while True:
        try:
            u = input("\nYOU> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break
        if not u:
            continue
        low = u.lower()
        if low in ("/quit", "/exit"):
            print("Bye!")
            break
        if low == "/help":
            print("YOU> text to roleplay | OOC: ... for out-of-character coach | "
                  "/reset /persona /system /save /backend /quit")
            continue
        if low == "/reset":
            messages = [{"role": "system", "content": system}]
            print("* scene reset *")
            continue
        if low == "/persona":
            char = pick_persona()
            system = build_prompt(char)
            messages = [{"role": "system", "content": system}]
            print(f"* now {char['name']} *")
            continue
        if low == "/system":
            print(f"\n---\n{system}\n---")
            continue
        if low == "/save":
            save_transcript(messages, char["name"])
            continue
        if low == "/backend":
            print(f"backend={backend} model={model}")
            continue
        if low.startswith("/"):
            print("Unknown. /help for list.")
            continue
        messages.append({"role": "user", "content": u})
        if len(messages) > 1 + KEEP_TURNS * 2:
            messages = [messages[0]] + messages[-(KEEP_TURNS * 2):]
        reply = guarded(messages)
        if reply is None:
            messages.pop()
            continue
        messages.append({"role": "assistant", "content": reply})


if __name__ == "__main__":
    main()
