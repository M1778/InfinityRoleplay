#!/usr/bin/env python3
"""AI Horde image-model catalog for InfinityRoleplay (Agent-1).

Stdlib only (urllib, json, time, os). Fetches GET /status/models with a
10-minute on-disk cache, and exposes helpers for the app server / UI:

  list_image_models() -> [{name, workers, queued, styles, nsfw}]
  best_model(style)   -> highest-worker SFW model name for
                         anime | realistic | fantasy | general
  search_models(q)    -> case-insensitive substring matches

NSFW-tagged models (name contains "nsfw", case-insensitive) are flagged
and NEVER returned by best_model(). Anonymous jobs always send
nsfw:false, so NSFW workers can never serve them anyway.
"""

import json
import os
import time
import urllib.request

HORDE_BASE = os.environ.get("HORDE_BASE", "https://stablehorde.net/api/v2").rstrip("/")
CLIENT_AGENT = "ollama-rp-chat/2.0"
CACHE_PATH = "/tmp/horde_models.json"
CACHE_TTL = 600  # 10 minutes

STYLE_KEYWORDS = {
    "anime": ("anime", "illustrious", "pony", "manga", "waifu", "cartoon", "nova"),
    "realistic": ("realistic", "vision", "photo", "absolute", "deliberate", "icbinp"),
    "fantasy": ("fantasy", "deliberate", "diffusion", "dream", "epic", "mix", "art"),
    "general": (),
}


def _is_nsfw(name, entry):
    if "nsfw" in (name or "").lower():
        return True
    return bool(entry.get("nsfw"))


def _styles_for(name):
    low = (name or "").lower()
    hit = [s for s, kws in STYLE_KEYWORDS.items()
           if s != "general" and any(k in low for k in kws)]
    return hit or ["general"]


def _fetch_live(timeout=10):
    req = urllib.request.Request(
        HORDE_BASE + "/status/models",
        headers={"Client-Agent": CLIENT_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.load(r)
    return data if isinstance(data, list) else []


def _load_cache():
    try:
        with open(CACHE_PATH) as f:
            blob = json.load(f)
        return blob.get("ts", 0), blob.get("models", [])
    except (OSError, ValueError):
        return 0, []


def get_models(force=False, timeout=10):
    """Raw model list; fresh cache (<10 min) wins, stale cache on failure."""
    ts, cached = _load_cache()
    if not force and cached and time.time() - ts < CACHE_TTL:
        return cached
    try:
        models = _fetch_live(timeout)
        if models:
            try:
                with open(CACHE_PATH, "w") as f:
                    json.dump({"ts": time.time(), "models": models}, f)
            except OSError:
                pass
            return models
    except Exception:
        pass
    return cached  # stale cache or [] — never raises


def list_image_models():
    """Normalized [{name, workers, queued, styles, nsfw}], workers desc."""
    out = []
    for m in get_models():
        if m.get("type", "image") != "image":
            continue
        name = m.get("name", "")
        if not name:
            continue
        out.append({"name": name,
                    "workers": int(m.get("count", 0) or 0),
                    "queued": m.get("queued", 0),
                    "styles": _styles_for(name),
                    "nsfw": _is_nsfw(name, m)})
    out.sort(key=lambda e: e["workers"], reverse=True)
    return out


def best_model(style="general"):
    """Highest-worker SFW model suiting style; None if catalog unreachable."""
    kws = STYLE_KEYWORDS.get((style or "general").lower(), ())
    cands = [m for m in list_image_models() if not m["nsfw"]]
    if kws:
        hit = [m for m in cands if any(k in m["name"].lower() for k in kws)]
        if hit:
            cands = hit
    if not cands:
        return None
    return min(cands, key=lambda m: (-m["workers"], m["queued"]))["name"]


def search_models(q):
    """Case-insensitive substring search over the normalized catalog."""
    q = (q or "").strip().lower()
    if not q:
        return []
    return [m for m in list_image_models() if q in m["name"].lower()]


if __name__ == "__main__":
    for i, m in enumerate(list_image_models()[:10], 1):
        flag = " [NSFW-excluded]" if m["nsfw"] else ""
        print(f"{i:2}. {m['name']} — {m['workers']} workers{flag}")
    print("best anime:", best_model("anime"))
    print("best realistic:", best_model("realistic"))
    print("best fantasy:", best_model("fantasy"))
    print("best general:", best_model("general"))
