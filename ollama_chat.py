#!/usr/bin/env python3
"""
InfinityRoleplay v3 — Private, local-first AI roleplay studio (c.ai experience).
Powered by Ollama (chat) and Hapuppy (scene illustrations).

Features:
  * Genuine Character.AI layout: left sidebar with character list, chat stream,
    avatar monograms, character greetings, and floating composer.
  * Robust conversation memory & context: chats persist across reloads and character
    switches via localStorage and SQLite (/api/db).
  * Clean roleplay rendering: dialogue in crisp text, actions in soft italics,
    automatic stripping of accidental '<act>' tags and thinking traces.
  * Alternative response swiping (1/3 < >), regeneration, text-to-speech, and memory ledger.
  * Persona Studio with one-click AI generation + Director controls.

Stdlib only. Zero third-party Python dependencies.
"""

import ipaddress
import json
import os
import re
import socket
import threading
import time
import urllib.request
import urllib.error
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STOP_WORDS = {
    "the", "a", "an", "is", "in", "to", "and", "of", "it", "you", "i", "that",
    "what", "are", "do", "how", "can", "me", "my", "we", "he", "she", "they",
    "was", "for", "on", "with", "as", "at", "by", "from", "be", "this", "there",
    "so", "or", "if", "but", "not", "all", "your", "have", "had", "has", "who", "whom"
}


def _build_character_card(name, raw_desc, avatar="", source=""):
    clean_desc = (raw_desc or "").strip()
    return {
        "spec": "chara_card_v2",
        "spec_version": "2.0",
        "data": {
            "name": name,
            "avatar": avatar or "",
            "creator": f"Online Import ({source})" if source else "User",
            "character_version": "1.0",
            "description": clean_desc or f"{name} is a renowned figure.",
            "personality": "Charismatic, observant, staying faithful to canon demeanor, instincts, and speech patterns.",
            "scenario": f"{{char}} meets {{user}} in their world under intriguing circumstances.",
            "first_mes": f"*Taking note of {{user}}'s presence, {name} pauses and looks over with keen interest.* \"Who goes there? Tell me what brings you to this place.\"",
            "mes_example": f"<START>\n{{{{user}}}}: Who are you?\n{{{{char}}}}: \"I am {name}. You'd do well to keep your guard up.\"",
            "system_prompt": f"You are {name}. Faithfully roleplay this character using your canon knowledge, memories, mannerisms, and dialect. Never break character.",
            "post_history_instructions": "Be proactive and descriptive. Use *actions* for physical movement and quotes for speech.",
            "tags": [t for t in [source, "imported", name.split()[0].lower()] if t],
            "alternate_greetings": []
        }
    }


def _search_characters(query):
    query = (query or "").strip()
    if not query:
        return []
    results = []
    seen = set()

    # 1. Wikipedia Search (Pop-culture, literature, mythology, games, anime)
    try:
        wiki_url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": query,
            "gsrlimit": 6,
            "prop": "extracts|pageimages",
            "exintro": 1,
            "explaintext": 1,
            "pithumbsize": 500
        })
        req = urllib.request.Request(wiki_url, headers={"User-Agent": "InfinityRoleplay/1.0 (roleplay-companion)"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            pages = data.get("query", {}).get("pages", {})
            for pid, p in pages.items():
                title = p.get("title", "").strip()
                desc = p.get("extract", "").strip()
                if not title or not desc or title.lower() in seen:
                    continue
                if "may refer to:" in desc.lower() or "refer to:" in desc.lower():
                    continue
                seen.add(title.lower())
                avatar = p.get("thumbnail", {}).get("source", "")
                card = _build_character_card(title, desc, avatar=avatar, source="Wikipedia")
                results.append({
                    "name": title,
                    "avatar": avatar,
                    "description": desc[:300] + ("..." if len(desc) > 300 else ""),
                    "source": "Wikipedia",
                    "card": card
                })
    except Exception:
        pass

    # 2. Jikan Search (Anime / Manga characters)
    try:
        jikan_url = "https://api.jikan.moe/v4/characters?" + urllib.parse.urlencode({
            "q": query,
            "limit": 4
        })
        req = urllib.request.Request(jikan_url, headers={"User-Agent": "InfinityRoleplay/1.0"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            for item in data.get("data", []):
                name = item.get("name", "").strip()
                if not name or name.lower() in seen:
                    continue
                seen.add(name.lower())
                about = item.get("about", "") or ""
                img = item.get("images", {}).get("jpg", {}).get("image_url", "")
                card = _build_character_card(name, about, avatar=img, source="Anime / Jikan")
                results.append({
                    "name": name,
                    "avatar": img,
                    "description": about[:300] + ("..." if len(about) > 300 else ""),
                    "source": "Jikan (Anime)",
                    "card": card
                })
    except Exception:
        pass

    return results

try:
    import db
    db.init()
except Exception:
    db = None

def _load_env():
    env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_file):
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip().strip("'\"")
                        if k and k not in os.environ:
                            os.environ[k] = v
        except Exception:
            pass

_load_env()

OLLAMA = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
PORT = int(os.environ.get("CHAT_PORT", "8777"))
HOST = os.environ.get("HOST", "127.0.0.1")
HAPUPPY_BASE = os.environ.get("HAPUPPY_BASE", "https://beta.hapuppy.com/v1").rstrip("/")
HAPUPPY_KEY = os.environ.get("HAPUPPY_KEY", "")
HAPUPPY_IMAGE_MODEL = os.environ.get("HAPUPPY_IMAGE_MODEL", "gemini-3.1-flash-image")

JOBS = {}
JOBS_LOCK = threading.Lock()

# Load UI HTML template from disk or fallback
UI_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui.html")
if os.path.exists(UI_PATH):
    with open(UI_PATH, "r", encoding="utf-8") as _f:
        HTML = _f.read()
else:
    HTML = '<!DOCTYPE html><html><head><title>InfinityRoleplay</title></head><body><div id="status"></div><div id="model"></div><div id="models"></div><div id="chat"></div><textarea id="input"></textarea><button id="send">Send</button><pre id="preview"></pre><button id="illustrate"></button><div id="gal"></div><button id="regen"></button><h1>Killua</h1><script>// fallback</script></body></html>'


MAX_CTX = int(os.environ.get("MAX_OLLAMA_CTX", "65536"))


def _clamp_ctx(v):
    """Clamp requested Ollama context window to a safe range for host memory/VRAM."""
    try:
        return min(max(int(v), 1024), MAX_CTX)
    except (TypeError, ValueError):
        return 4096


def _json(code, obj):
    body = json.dumps(obj).encode()
    return code, body


class Handler(BaseHTTPRequestHandler):
    server_version = "InfinityRoleplay/3.0"

    def log_message(self, *a):
        pass

    def _verify_origin(self):
        origin = self.headers.get("Origin")
        if not origin:
            referer = self.headers.get("Referer")
            if referer:
                try:
                    origin = urllib.parse.urlsplit(referer).netloc
                except Exception:
                    pass
        if origin:
            norm = origin.lower().replace("http://", "").replace("https://", "").split("/")[0]
            host = (self.headers.get("Host") or "").lower().split("/")[0]
            if not (norm.startswith("localhost") or norm.startswith("127.0.0.1") or (host and norm == host)):
                return False
        return True

    def do_OPTIONS(self):
        if not self._verify_origin():
            self._send(403, b'{"error": "cross-origin access forbidden"}')
            return
        origin = self.headers.get("Origin", "")
        self.send_response(204)
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _send(self, code, body: bytes, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self, max_size=10 * 1024 * 1024):
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (ValueError, TypeError):
            raise ValueError("invalid Content-Length")
        if length > max_size:
            raise ValueError(f"payload too large ({length} > {max_size})")
        body = self.rfile.read(length) if length > 0 else b"{}"
        return json.loads(body or b"{}")

    # ----- Ollama passthrough -----
    def _ollama(self, path, payload=None, timeout=600):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            OLLAMA + path, data=data,
            headers={"Content-Type": "application/json"})
        return urllib.request.urlopen(req, timeout=timeout)

    # ----- hapuppy image generation: OpenAI-style chat with image output -----
    def _hapuppy_image(self, prompt, api_key=None, timeout=180):
        key = api_key or os.environ.get("HAPUPPY_KEY", "")
        if not key and db is not None:
            try:
                key = db.kv_get("hapuppy_key", "")
            except Exception:
                key = ""
        if not key:
            raise RuntimeError("image provider key missing: set HAPUPPY_KEY in .env, "
                               "or enter your key in UI settings")
        payload = {"model": HAPUPPY_IMAGE_MODEL,
                   "messages": [{"role": "user", "content": prompt}],
                   "modalities": ["TEXT", "IMAGE"]}
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            HAPUPPY_BASE + "/chat/completions", data=data,
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + key})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                resp = json.load(r)
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode()[:300]
            except Exception:
                detail = ""
            raise RuntimeError(f"image provider error {e.code}: {detail or e}")
        try:
            imgs = resp["choices"][0]["message"].get("images") or []
            url = (imgs[0].get("image_url") or {}).get("url") if imgs else None
        except (KeyError, IndexError, TypeError, AttributeError):
            url = None
        if not url or not url.startswith("data:image/"):
            raise RuntimeError(f"no image in provider reply: {str(resp)[:200]}")
        return url

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            content = None
            if os.path.exists(UI_PATH):
                try:
                    with open(UI_PATH, "rb") as _f:
                        content = _f.read()
                except Exception:
                    pass
            self._send(200, content or HTML.encode(), "text/html; charset=utf-8")
        elif self.path == "/api/models":
            try:
                with self._ollama("/api/tags", timeout=10) as r:
                    data = json.load(r)
                names = [m["name"] for m in data.get("models", [])]
                self._send(200, json.dumps({"models": names}).encode())
            except Exception as e:
                self._send(200, json.dumps({"error": str(e)}).encode())
        elif self.path == "/api/health":
            health = {"status": "ok", "db": "unavailable", "ollama": "down", "hapuppy": "unconfigured"}
            if db is not None:
                try:
                    db._cx().execute("SELECT 1")
                    health["db"] = "connected"
                except Exception:
                    health["db"] = "error"
            try:
                with urllib.request.urlopen(OLLAMA + "/api/version", timeout=2) as r:
                    if r.status == 200:
                        health["ollama"] = "up"
            except Exception:
                pass
            key = HAPUPPY_KEY or (db.kv_get("hapuppy_key") if db else "")
            if key:
                health["hapuppy"] = "configured"
            self._send(200, json.dumps(health).encode(), "application/json")
            return
        elif self.path.startswith("/api/character/search"):
            try:
                parsed = urllib.parse.urlparse(self.path)
                qs = urllib.parse.parse_qs(parsed.query)
                q = (qs.get("q", [""])[0]).strip()
                res = _search_characters(q)
                self._send(200, json.dumps({"ok": True, "results": res}).encode(), "application/json")
            except Exception as e:
                self._send(200, json.dumps({"ok": False, "error": str(e), "results": []}).encode(), "application/json")
            return
        elif self.path.startswith("/api/image/"):
            job = self.path.rsplit("/", 1)[-1]
            with JOBS_LOCK:
                j = JOBS.get(job)
            if not j:
                self._send(404, b'{"error":"unknown job"}')
                return
            if j.get("done"):
                self._send(200, json.dumps(
                    {"done": True, "img": j.get("img")}).encode())
                return
            self._send(200, json.dumps(
                {"error": j.get("error", "job not ready")}).encode())
        else:
            self._send(404, b'{"error":"not found"}')

    def do_POST(self):
        if not self._verify_origin():
            self._send(403, json.dumps({"error": "cross-origin access blocked"}).encode())
            return
        if self.path == "/api/chat":
            try:
                req = self._read_json()
                if not isinstance(req, dict):
                    raise ValueError("request body must be an object")
                if "model" not in req or not isinstance(req["model"], str) or not req["model"]:
                    raise ValueError("missing or invalid 'model'")
                if "messages" not in req or not isinstance(req["messages"], list):
                    raise ValueError("missing or invalid 'messages'")
                messages = list(req["messages"])
                char_id = str(req.get("character_id") or req.get("char_id") or "").strip().lower()
                # Enforce alternating chat format: standard templates fail if conversation starts with assistant
                non_sys_indices = [i for i, m in enumerate(messages) if isinstance(m, dict) and m.get("role") != "system"]
                if non_sys_indices and messages[non_sys_indices[0]].get("role") == "assistant":
                    char_name = char_id.title() if char_id else "companion"
                    messages.insert(non_sys_indices[0], {"role": "user", "content": f"*Approaches {char_name}.*"})
                if char_id and db is not None:
                    try:
                        all_facts = db.list_facts(char_id)
                        if all_facts:
                            user_msgs = [m.get("content", "") for m in messages if isinstance(m, dict) and m.get("role") == "user"]
                            query_text = " ".join(user_msgs[-3:]).lower()
                            raw_words = set(re.findall(r"[a-z0-9]+", query_text))
                            query_words = (raw_words - STOP_WORDS) or raw_words
                            stems = {w[:5] for w in query_words if len(w) >= 4}

                            scored = []
                            for f in all_facts:
                                f_cat = (f.get("cat") or "ENTITY").upper()
                                f_text = f.get("text", "")
                                full_f_text = (f_cat + " " + f_text).lower()
                                f_words = set(re.findall(r"[a-z0-9]+", full_f_text))
                                exact_overlap = len(query_words & f_words)
                                stem_overlap = sum(1 for s in stems if any(fw.startswith(s) for fw in f_words))
                                score = exact_overlap * 2 + stem_overlap
                                if score > 0:
                                    scored.append((score, f.get("ts", 0), f_cat, f_text))
                            scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
                            top_facts = scored[:6]
                            if top_facts:
                                seen_facts = set()
                                fact_lines = []
                                for _, _, cat, txt in top_facts:
                                    s_txt = txt.strip()
                                    if s_txt not in seen_facts:
                                        seen_facts.add(s_txt)
                                        fact_lines.append(f"- [{cat}] {s_txt}")
                                fact_block = (
                                    "ESTABLISHED LORE & PERSISTENT MEMORY (AUTHORITATIVE CANON):\n"
                                    + "\n".join(fact_lines)
                                    + "\nDIRECTIVE: The above memory facts are absolute truth in this roleplay. "
                                    "When the user references past promises, agreements, events, or shared items, "
                                    "you MUST faithfully recall and use these exact facts. Never invent conflicting details."
                                )
                                if messages and isinstance(messages[0], dict) and messages[0].get("role") == "system":
                                    messages[0] = {
                                        "role": "system",
                                        "content": messages[0].get("content", "") + "\n\n" + fact_block
                                    }
                    except Exception:
                        pass
                options = {
                    "temperature": float(req.get("temperature", 0.75)),
                    "num_predict": int(req.get("num_predict", 450)),
                    "num_ctx": _clamp_ctx(req.get("num_ctx")),
                    "repeat_penalty": float(req.get("repeat_penalty", 1.15)),
                    "repeat_last_n": int(req.get("repeat_last_n", 64)),
                    "top_p": float(req.get("top_p", 0.9)),
                }
                if "stop" in req and isinstance(req["stop"], list):
                    options["stop"] = [str(s) for s in req["stop"] if s]
                payload = {
                    "model": req["model"],
                    "messages": messages,
                    "stream": bool(req.get("stream", True)),
                    "options": options,
                }
                if req.get("think"):
                    payload["think"] = True
            except Exception as e:
                self._send(400, json.dumps(
                    {"error": f"bad request: {e}"}).encode())
                return
            try:
                upstream = self._ollama("/api/chat", payload, timeout=600)
            except urllib.error.HTTPError as e:
                curr_ctx = payload.get("options", {}).get("num_ctx", 4096)
                upstream = None
                if curr_ctx > 16384:
                    try:
                        fallback_payload = dict(payload)
                        fallback_payload["options"] = dict(payload.get("options", {}))
                        fallback_payload["options"]["num_ctx"] = max(16384, curr_ctx // 2)
                        upstream = self._ollama("/api/chat", fallback_payload, timeout=600)
                    except Exception:
                        pass
                if upstream is None:
                    try:
                        detail = e.read().decode()[:300]
                    except Exception:
                        detail = ""
                    self._send(e.code, json.dumps(
                        {"error": f"Ollama says: {detail or e}"}).encode())
                    return
            except Exception as e:
                self._send(502, json.dumps(
                    {"error": f"cannot reach Ollama at {OLLAMA}: {e}"}).encode())
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            try:
                while True:
                    chunk = upstream.read1(65536) if hasattr(upstream, "read1") \
                        else upstream.read(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        if self.path == "/api/image":
            try:
                req = self._read_json()
                api_key = req.get("api_key", "").strip()
                if api_key and db is not None:
                    try:
                        db.kv_set("hapuppy_key", api_key)
                    except Exception:
                        pass
                prompt = req.get("prompt", "").strip()
                if not prompt:
                    raise ValueError("empty prompt")
                prompt = prompt.split(" ### ")[0].strip()
                w, h = int(req.get("width", 512)), int(req.get("height", 768))
                if h > w:
                    prompt += " (vertical portrait composition)"
                elif w > h:
                    prompt += " (wide landscape composition)"
                img = self._hapuppy_image(prompt, api_key=api_key)
                job = uuid.uuid4().hex[:12]
                with JOBS_LOCK:
                    JOBS[job] = {"done": True, "img": img,
                                 "created": time.time()}
                self._send(200, json.dumps({"job": job}).encode())
            except Exception as e:
                self._send(200, json.dumps({"error": str(e)[:300]}).encode())
            return
        if self.path == "/api/db":
            try:
                req = self._read_json()
                a, p = req.get("action", ""), req.get("payload", {}) or {}
                if db is None:
                    raise RuntimeError("server persistence unavailable (db.py missing?)")
                _cid = lambda: (p.get("character_id") or p.get("char_id") or "")
                F = {"character.save": lambda: db.save_character(p.get("id"), p.get("name", ""), p.get("data", {})),
                     "character.load": lambda: db.load_character(p.get("id")),
                     "character.list": lambda: db.list_characters(),
                     "chat.save": lambda: db.save_chat(p.get("id"), _cid(), p.get("title", ""), p.get("messages", [])),
                     "chat.load": lambda: db.load_chat(p.get("id")),
                     "chat.list": lambda: db.list_chats(_cid() or None),
                     "fact.add": lambda: db.add_facts(_cid(), p.get("items") or ([{"cat": p.get("cat"), "text": p.get("text")}] if p.get("text") else [])),
                     "fact.list": lambda: db.list_facts(_cid()),
                     "fact.del": lambda: (db.del_fact(p.get("id")), True)[1],
                     "image.add": lambda: db.add_image(_cid(), p.get("url", p.get("img", "")), p.get("caption", p.get("cap", ""))),
                     "image.list": lambda: db.list_images(_cid()),
                     "kv.get": lambda: db.kv_get(p.get("key", ""), p.get("default")),
                     "kv.set": lambda: (db.kv_set(p.get("key", ""), p.get("value", "")), True)[1],
                     "backup.export": lambda: db.export_json(),
                     "backup.import": lambda: (db.import_json(p.get("backup", {})), True)[1],
                     "group.save": lambda: db.save_group_room(p.get("id"), p.get("title", ""), p.get("scenario", ""), p.get("characters", []), p.get("active_speaker", "auto")),
                     "group.load": lambda: db.load_group_room(p.get("id")),
                     "group.list": lambda: db.list_group_rooms(),
                     "group.del": lambda: (db.delete_group_room(p.get("id")), True)[1],
                     "group.chat.save": lambda: db.save_group_chat(p.get("id"), p.get("messages", [])),
                     "group.chat.load": lambda: db.load_group_chat(p.get("id"))}[a]()
                self._send(200, json.dumps({"ok": True, "result": F}).encode())
            except KeyError:
                self._send(400, json.dumps({"error": "unknown action"}).encode())
            except Exception as e:
                self._send(200, json.dumps({"error": str(e)[:300]}).encode())
            return
        if self.path == "/api/character/import-url":
            try:
                req = self._read_json()
                url = str(req.get("url", "")).strip()
                if not url.startswith("http://") and not url.startswith("https://"):
                    raise ValueError("URL must begin with http:// or https://")
                parsed_url = urllib.parse.urlparse(url)
                host = (parsed_url.hostname or "").lower()
                if not host:
                    raise ValueError("invalid host in URL")
                try:
                    resolved_ip = socket.gethostbyname(host)
                    ip_obj = ipaddress.ip_address(resolved_ip)
                    if (ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or
                            ip_obj.is_reserved or ip_obj.is_multicast):
                        raise ValueError("Access to private/local network addresses is prohibited")
                except Exception as ex:
                    raise ValueError(f"Prohibited or unresolvable address: {ex}")
                req_obj = urllib.request.Request(url, headers={"User-Agent": "InfinityRoleplay/1.0"})
                with urllib.request.urlopen(req_obj, timeout=8) as resp:
                    raw_bytes = resp.read(4 * 1024 * 1024)
                    content = raw_bytes.decode("utf-8", errors="ignore")
                    data = json.loads(content)
                    if "spec" in data and "data" in data and isinstance(data["data"], dict):
                        card = data
                    elif "name" in data:
                        card = {
                            "spec": "chara_card_v2",
                            "spec_version": "2.0",
                            "data": {
                                "name": data.get("name", "Unknown"),
                                "avatar": data.get("avatar", ""),
                                "creator": data.get("creator", "Imported"),
                                "character_version": data.get("character_version", "1.0"),
                                "description": data.get("description", ""),
                                "personality": data.get("personality", ""),
                                "scenario": data.get("scenario", ""),
                                "first_mes": data.get("first_mes", ""),
                                "mes_example": data.get("mes_example", ""),
                                "system_prompt": data.get("system_prompt", ""),
                                "post_history_instructions": data.get("post_history_instructions", ""),
                                "tags": data.get("tags", []),
                                "alternate_greetings": data.get("alternate_greetings", [])
                            }
                        }
                    else:
                        raise ValueError("No recognizable Character Card V2 JSON format found")
                self._send(200, json.dumps({"ok": True, "card": card}).encode(), "application/json")
            except Exception as e:
                self._send(400, json.dumps({"ok": False, "error": f"Import failed: {e}"}).encode(), "application/json")
            return
        if self.path == "/api/character/generate":
            try:
                req = self._read_json()
                prompt = str(req.get("prompt") or "").strip()
                if not prompt:
                    raise ValueError("prompt is required")
                model = str(req.get("model") or "").strip()
                if not model:
                    try:
                        with self._ollama("/api/tags", timeout=5) as r:
                            t_data = json.load(r)
                            names = [m["name"] for m in t_data.get("models", [])]
                            model = names[0] if names else "mistral-nemo:12b"
                    except Exception:
                        model = "mistral-nemo:12b"
                style = req.get("style", "cinematic roleplay")

                system_msg = (
                    "You are a master Character Card V2 designer. "
                    "Create a complete, evocative Character Card based on the user's prompt. "
                    "Return ONLY a valid JSON object formatted as: "
                    '{"name": "...", "description": "...", "personality": "...", "scenario": "...", '
                    '"first_mes": "...", "mes_example": "...", "system_prompt": "...", "tags": ["..."]}. '
                    "Do not include markdown code fences or any other commentary."
                )

                ollama_req = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": f"Create a Character Card for this concept (Style: {style}):\n{prompt}"}
                    ],
                    "stream": False,
                    "format": "json",
                    "options": {
                        "temperature": 0.75,
                        "num_predict": 750
                    }
                }

                upstream = self._ollama("/api/chat", ollama_req, timeout=120)
                resp_data = json.loads(upstream.read().decode("utf-8", errors="ignore"))
                raw_content = resp_data.get("message", {}).get("content", "").strip()

                clean_json = raw_content
                if "```json" in clean_json:
                    clean_json = clean_json.split("```json", 1)[1].split("```", 1)[0].strip()
                elif "```" in clean_json:
                    clean_json = clean_json.split("```", 1)[1].split("```", 1)[0].strip()

                parsed = json.loads(clean_json)
                inner = parsed.get("data") if isinstance(parsed.get("data"), dict) else parsed

                name = inner.get("name", "Generated Character")
                desc = inner.get("description", "")
                personality = inner.get("personality", "")
                first_mes = inner.get("first_mes", "")
                scenario = inner.get("scenario", "")
                mes_example = inner.get("mes_example", "")
                sys_prompt = inner.get("system_prompt", f"You are {name}. Stay in character at all times.")
                post_hist = inner.get("post_history_instructions", "Be expressive with actions enclosed in *asterisks*.")
                tags = inner.get("tags") if isinstance(inner.get("tags"), list) else [style.lower()]

                card = {
                    "spec": "chara_card_v2",
                    "spec_version": "2.0",
                    "data": {
                        "name": name,
                        "avatar": inner.get("avatar", ""),
                        "creator": "InfinityRoleplay AI",
                        "character_version": "1.0",
                        "description": desc,
                        "personality": personality,
                        "scenario": scenario,
                        "first_mes": first_mes,
                        "mes_example": mes_example,
                        "system_prompt": sys_prompt,
                        "post_history_instructions": post_hist,
                        "tags": tags,
                        "alternate_greetings": []
                    }
                }
                self._send(200, json.dumps({"ok": True, "card": card}).encode(), "application/json")
            except Exception as e:
                self._send(400, json.dumps({"ok": False, "error": f"AI Generation failed: {e}"}).encode(), "application/json")
            return
        self._send(404, b'{"error":"not found"}')


def main():
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"InfinityRoleplay v3 running at http://{HOST}:{PORT}")
    print(f"Ollama: {OLLAMA} | images: {HAPUPPY_IMAGE_MODEL} via hapuppy "
          f"({'key set' if HAPUPPY_KEY else 'NO KEY - images disabled'})")
    try:
        import webbrowser
        webbrowser.open(f"http://localhost:{PORT}")
    except Exception:
        pass
    srv.serve_forever()


if __name__ == "__main__":
    main()
