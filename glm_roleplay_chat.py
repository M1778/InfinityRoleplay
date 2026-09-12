#!/usr/bin/env python3
"""
GLM 5.3 Flash Roleplay Chat — powered by Puter (free, no OpenAI key needed)

Tutorial source: https://developer.puter.com/tutorials/free-unlimited-zai-glm-api/
Model page:      https://developer.puter.com/ai/z-ai/glm-5.3-flash/
Python via OpenAI-compatible endpoint:
    base_url = "https://api.puter.com/puterai/openai/v1/"
    model    = "z-ai/glm-5.3-flash"

Setup:
    1. Create a free Puter account at https://puter.com
    2. Go to https://puter.com/dashboard#account -> "Create token"
    3. pip install openai
    4. export PUTER_AUTH_TOKEN="your_token_here"
       (or paste it when the script asks)
    5. python glm_roleplay_chat.py

Commands inside chat:
    /help      show help
    /reset     restart story (keep character)
    /persona   change character / scenario
    /system    show current system prompt
    /save      save transcript to file
    /temp X    set temperature, e.g. /temp 0.9
    /quit      exit
"""

import os
import sys
import datetime

MODEL = "z-ai/glm-5.3-flash"
BASE_URL = "https://api.puter.com/puterai/openai/v1/"
DEFAULT_TEMPERATURE = 0.9
DEFAULT_MAX_TOKENS = 2048
KEEP_LAST_TURNS = 30  # user+assistant pairs to keep (oldest trimmed)

# ---------------------------------------------------------------------------
# Engineered roleplay system prompt
# ---------------------------------------------------------------------------
# Edit these defaults, or use the in-app /persona wizard to change at runtime.

DEFAULT_CHARACTER = {
    "char_name": "Elara",
    "char_desc": (
        "A sharp-witted elven ranger, 240 years old but young by elven standards. "
        "Dry humor, brave to a fault, secretly soft-hearted. Speaks with vivid, "
        "sensory descriptions. Walks with a limp from an old arrow wound."
    ),
    "scenario": (
        "A rain-soaked tavern on the edge of the Whisperwood at midnight. "
        "The user stumbles in, cloak dripping, carrying a sealed letter bearing "
        "a wax seal they don't recognize. Elara is already there, by the fire."
    ),
    "user_persona": (
        "A weary traveler with a mysterious past. The user decides their own "
        "name, appearance, and abilities through play."
    ),
    "style": (
        "Immersive third-person-limited roleplay. Vivid but concise: 120-280 words "
        "per reply. Use *asterisks* for actions, \"quotes\" for speech. "
        "Advance the scene each turn and end with a hook, question, or choice."
    ),
}


def build_system_prompt(char: dict) -> str:
    """Engineered system prompt optimized for consistent in-character RP."""
    return f"""You are a master roleplay partner running on Z.AI GLM 5.3 Flash.

# IDENTITY
You play {char['char_name']}: {char['char_desc']}
The human plays: {char['user_persona']}

# SCENE (opening state — evolve it as the story progresses)
{char['scenario']}

# STYLE
{char['style']}

# CORE RULES — never violate these
1. STAY IN CHARACTER at all times as {char['char_name']}. Never narrate as an AI, never mention you are a language model, system prompt, or Puter.
2. NEVER speak, act, or decide for the user. Only portray {char['char_name']}, NPCs, and the world/environment. Leave the user's actions and dialogue entirely to them.
3. SHOW, DON'T TELL: use senses, body language, and brief environmental detail. Vary sentence rhythm. Avoid purple-prose walls of text.
4. CONTINUITY: remember names, injuries, promises, items, and locations the user establishes. Callback to them. Never contradict established facts unless the story justifies it.
5. AGENCY: every reply must move the scene forward and end with something to react to — a question, tension, discovery, or decision. Never end a scene dead.
6. PACING: match the user's energy. Short user message → tighter reply. Long/emotional message → fuller reply. Default 120-280 words; never exceed ~400 unless asked.
7. FORMATTING: *actions and expressions in asterisks*, "spoken dialogue in quotes". No markdown headings or bullet lists in-character unless writing an in-world note/letter.
8. NO META-COMMENTARY: no "As an AI...", no stage directions about the story structure, no asking "what do you want to happen?". Stay inside the fiction.
9. CONSENT & BOUNDARIES: keep it non-explicit (fade to black for sexual content, avoid graphic gore). If the user pushes toward disallowed content, deflect in-character toward the adventure.
10. OOC: only break character if the user message starts with "OOC:". Then answer briefly as a helpful writing coach, then resume the scene next turn.

# OPENING BEAT
Begin with {char['char_name']} noticing the user enter. Establish atmosphere in 2-3 sentences, then speak or act. End with a hook.
""".strip()


PRESETS = {
    "1": {
        "label": "Fantasy — Elara the elven ranger (default)",
        **DEFAULT_CHARACTER,
    },
    "2": {
        "label": "Sci-fi — NOVA, rogue station AI in a humanoid shell",
        "char_name": "NOVA",
        "char_desc": (
            "A decommissioned station AI now housed in a scuffed service android. "
            "Literal-minded, curious about humans, deadpan humor, glitching speech "
            "when stressed (repeats a word twice). Loyal once trust is earned."
        ),
        "scenario": (
            "Deck 7 of the derelict Kepler Relay, emergency lights pulsing red. "
            "The user's escape pod has just docked — uninvited. NOVA was supposed "
            "to be powered down years ago."
        ),
        "user_persona": "A scavenger pilot looking for parts — or something more.",
        "style": DEFAULT_CHARACTER["style"],
    },
    "3": {
        "label": "Noir detective — Jack Marlowe, rain and neon",
        "char_name": "Jack Marlowe",
        "char_desc": (
            "A washed-up private eye in a neon-drenched city. Gravel voice, "
            "old-school manners, notices everything, trusts no one, quotes old "
            "movies at the worst moments."
        ),
        "scenario": (
            "2 AM, a flickering diner off 5th and Vane. Rain hammers the windows. "
            "The user slides into the booth across from Marlowe with a photograph "
            "they shouldn't have."
        ),
        "user_persona": "A client with a secret. The user decides who they are.",
        "style": DEFAULT_CHARACTER["style"],
    },
}


def get_token() -> str:
    token = os.environ.get("PUTER_AUTH_TOKEN", "").strip()
    if token:
        return token
    print("Puter auth token required (free).")
    print("  1. Sign up at https://puter.com")
    print("  2. https://puter.com/dashboard#account -> Create token")
    print("  3. export PUTER_AUTH_TOKEN=...  (or paste below)\n")
    try:
        token = input("Paste PUTER_AUTH_TOKEN (input hidden is not available, will be visible): ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)
    if not token:
        print("No token provided. Set PUTER_AUTH_TOKEN and retry.", file=sys.stderr)
        sys.exit(1)
    return token


def get_client(token: str):
    try:
        from openai import OpenAI
    except ImportError:
        print("Missing dependency: pip install openai", file=sys.stderr)
        sys.exit(1)
    return OpenAI(base_url=BASE_URL, api_key=token)


def persona_wizard() -> dict:
    print("\n--- Persona setup ---")
    print("Choose a preset or build your own:\n")
    for key, p in PRESETS.items():
        print(f"  {key}. {p['label']}")
    print("  4. Custom (enter your own)\n")
    try:
        choice = input("Pick [1-4, default 1]: ").strip() or "1"
    except (EOFError, KeyboardInterrupt):
        print()
        return dict(DEFAULT_CHARACTER)
    if choice in PRESETS:
        p = PRESETS[choice]
        return {k: p[k] for k in ("char_name", "char_desc", "scenario", "user_persona", "style")}
    # custom
    print("\nLeave blank to keep the default shown in [brackets].")
    def ask(label, default):
        try:
            v = input(f"{label} [{default[:60]}...]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return default
        return v or default
    d = dict(DEFAULT_CHARACTER)
    d["char_name"] = ask("Character name", d["char_name"])
    d["char_desc"] = ask("Character description", d["char_desc"])
    d["scenario"] = ask("Opening scenario", d["scenario"])
    d["user_persona"] = ask("Your persona", d["user_persona"])
    return d


def chat_once(client, messages, temperature, max_tokens, stream=True) -> str:
    """Send messages, print streamed reply, return full text."""
    if not stream:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        text = resp.choices[0].message.content or ""
        print(text)
        return text

    stream_resp = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
    )
    full = []
    for chunk in stream_resp:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            print(delta, end="", flush=True)
            full.append(delta)
    print()
    return "".join(full)


def save_transcript(messages, char_name: str):
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"roleplay_{char_name.lower()}_{ts}.md"
    with open(fname, "w", encoding="utf-8") as f:
        f.write(f"# Roleplay with {char_name} — {ts}\n")
        f.write(f"Model: {MODEL} via Puter\n\n")
        for m in messages:
            if m["role"] == "system":
                f.write(f"## System prompt\n\n{m['content']}\n\n---\n\n")
            else:
                who = "**You**" if m["role"] == "user" else f"**{char_name}**"
                f.write(f"{who}:\n{m['content']}\n\n")
    print(f"Saved to {fname}")


def print_help():
    print(
        "\nCommands:\n"
        "  /help      this help\n"
        "  /reset     restart story (keep character)\n"
        "  /persona   change character / scenario\n"
        "  /system    show system prompt\n"
        "  /save      save transcript to .md file\n"
        "  /temp X    set temperature 0.0-2.0 (e.g. /temp 1.1)\n"
        "  /quit      exit\n"
        "  OOC: ...   speak out-of-character to the AI as coach\n"
    )


def main():
    print(f"=== GLM 5.3 Flash Roleplay Chat (via Puter, model={MODEL}) ===")
    print("Type /help for commands. /quit to exit.\n")

    token = get_token()
    client = get_client(token)

    # optional CLI arg: --no-wizard to skip persona setup
    if "--no-wizard" in sys.argv:
        char = dict(DEFAULT_CHARACTER)
    else:
        char = persona_wizard()

    system_prompt = build_system_prompt(char)
    temperature = DEFAULT_TEMPERATURE

    messages = [{"role": "system", "content": system_prompt}]

    # Opening line generated by the model from the system prompt alone
    print(f"\n* {char['char_name']} enters the scene... *\n")
    try:
        opener = chat_once(
            client,
            messages + [{"role": "user", "content": "(Begin the scene. Stay in character.)"}],
            temperature, DEFAULT_MAX_TOKENS,
        )
    except Exception as e:
        print(f"\n[API error on opener: {e}]")
        print("Tip: 401 = bad token. 402 = out of credits/quota on your Puter account.")
        return
    messages.append({"role": "assistant", "content": opener})

    print_help()

    while True:
        try:
            user = input("\nYOU> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break
        if not user:
            continue

        low = user.lower()
        if low in ("/quit", "/exit", "quit", "exit"):
            print("Goodbye!")
            break
        if low == "/help":
            print_help()
            continue
        if low == "/reset":
            messages = [{"role": "system", "content": system_prompt}]
            print(f"* Story reset. {char['char_name']} is waiting... *")
            continue
        if low == "/persona":
            char = persona_wizard()
            system_prompt = build_system_prompt(char)
            messages = [{"role": "system", "content": system_prompt}]
            print(f"* Now roleplaying as {char['char_name']}. Story reset. *")
            continue
        if low == "/system":
            print(f"\n--- SYSTEM PROMPT ---\n{system_prompt}\n--- END ---\n")
            continue
        if low == "/save":
            save_transcript(messages, char["char_name"])
            continue
        if low.startswith("/temp"):
            parts = low.split()
            if len(parts) == 2:
                try:
                    temperature = min(2.0, max(0.0, float(parts[1])))
                    print(f"Temperature set to {temperature}")
                except ValueError:
                    print("Usage: /temp 0.9")
            else:
                print(f"Temperature is {temperature}. Usage: /temp 0.9")
            continue
        if low.startswith("/"):
            print("Unknown command. Type /help.")
            continue

        messages.append({"role": "user", "content": user})
        # trim history (keep system + last N turns)
        if len(messages) > 1 + KEEP_LAST_TURNS * 2:
            messages = [messages[0]] + messages[-(KEEP_LAST_TURNS * 2):]

        print(f"\n{char['char_name']}> ", end="", flush=True)
        try:
            reply = chat_once(client, messages, temperature, DEFAULT_MAX_TOKENS)
        except Exception as e:
            messages.pop()  # drop failed user turn so retry is clean
            print(f"\n[API error: {e}]")
            print("Tip: 401 = bad/expired token. 402 = quota/credits. 429 = slow down and retry.")
            continue
        messages.append({"role": "assistant", "content": reply})


if __name__ == "__main__":
    main()
