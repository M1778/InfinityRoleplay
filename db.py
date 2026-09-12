#!/usr/bin/env python3
"""InfinityRoleplay persistence — stdlib sqlite3 only, thread-safe.

Mirrors ollama_chat.py @ ade335f shapes: history[] {role,content},
facts[] {id,cat,text,ts}, gallery[] {img,cap}, persona dict, direct dict.
Images stored as TEXT (remote URL or base64). Env DB_PATH default
/data/infinity.db if /data exists else ./infinity.db.
"""

import json
import os
import sqlite3
import threading
import time
import uuid

SCHEMA_VERSION = 1
DB_PATH = os.environ.get("DB_PATH", "/data/infinity.db" if os.path.isdir("/data") else "./infinity.db")

_LOCK = threading.Lock()
_CONN = None
_PATH = None

_now = lambda: int(time.time() * 1000)
_nid = lambda n=12: uuid.uuid4().hex[:n]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (v INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS characters (id TEXT PRIMARY KEY, name TEXT NOT NULL,
  data TEXT NOT NULL DEFAULT '{}', updated INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS chats (id TEXT PRIMARY KEY, character_id TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL DEFAULT '', created INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT NOT NULL,
  role TEXT NOT NULL, content TEXT NOT NULL DEFAULT '', idx INTEGER NOT NULL,
  FOREIGN KEY(chat_id) REFERENCES chats(id) ON DELETE CASCADE);
CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, idx);
CREATE TABLE IF NOT EXISTS facts (id TEXT PRIMARY KEY, character_id TEXT NOT NULL DEFAULT '',
  cat TEXT NOT NULL DEFAULT 'ENTITY', text TEXT NOT NULL, ts INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS idx_facts_char ON facts(character_id, ts);
CREATE TABLE IF NOT EXISTS images (id TEXT PRIMARY KEY, character_id TEXT NOT NULL DEFAULT '',
  url TEXT NOT NULL, caption TEXT NOT NULL DEFAULT '', created INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS idx_images_char ON images(character_id, created);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS group_rooms (id TEXT PRIMARY KEY, title TEXT NOT NULL DEFAULT '',
  scenario TEXT NOT NULL DEFAULT '', characters TEXT NOT NULL DEFAULT '[]',
  active_speaker TEXT NOT NULL DEFAULT 'auto', updated INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS group_messages (id INTEGER PRIMARY KEY AUTOINCREMENT,
  room_id TEXT NOT NULL, role TEXT NOT NULL, speaker TEXT NOT NULL DEFAULT '',
  speaker_name TEXT NOT NULL DEFAULT '', content TEXT NOT NULL DEFAULT '', idx INTEGER NOT NULL,
  FOREIGN KEY(room_id) REFERENCES group_rooms(id) ON DELETE CASCADE);
CREATE INDEX IF NOT EXISTS idx_group_messages ON group_messages(room_id, idx);
"""


def init(db_path=None):
    """Open (mkdir -p as needed) + create schema. Returns resolved path."""
    global _CONN, _PATH
    path = db_path or DB_PATH
    with _LOCK:
        if _CONN is not None and _PATH == path:
            return path
        if _CONN is not None:
            try:
                _CONN.close()
            except Exception:
                pass
            _CONN = None
        d = os.path.dirname(os.path.abspath(path))
        if d:
            os.makedirs(d, exist_ok=True)
        _CONN = sqlite3.connect(path, check_same_thread=False)
        _CONN.row_factory = sqlite3.Row
        _CONN.execute("PRAGMA journal_mode=WAL;")
        _CONN.execute("PRAGMA foreign_keys=ON;")
        _CONN.executescript(_SCHEMA)
        row = _CONN.execute("SELECT v FROM schema_version LIMIT 1").fetchone()
        if row is None:
            _CONN.execute("INSERT INTO schema_version (v) VALUES (?)", (SCHEMA_VERSION,))
        elif row["v"] != SCHEMA_VERSION:
            _CONN.execute("UPDATE schema_version SET v=?", (SCHEMA_VERSION,))
        _CONN.commit()
        _PATH = path
        return path


def _cx():
    if _CONN is None:
        init()
    return _CONN


def save_character(cid, name, data):
    """Upsert character; falsy cid -> generated id. data: persona dict."""
    cid = cid or ("c" + _nid())
    with _LOCK:
        _cx().execute(
            "INSERT INTO characters (id,name,data,updated) VALUES (?,?,?,?)"
            " ON CONFLICT(id) DO UPDATE SET name=excluded.name, data=excluded.data,"
            " updated=excluded.updated", (cid, name, json.dumps(data or {}), _now()))
        _cx().commit()
    return cid


def load_character(cid):
    with _LOCK:
        r = _cx().execute("SELECT * FROM characters WHERE id=?", (cid,)).fetchone()
    return None if not r else {"id": r["id"], "name": r["name"],
                               "data": json.loads(r["data"] or "{}"), "updated": r["updated"]}


def list_characters():
    with _LOCK:
        rows = _cx().execute("SELECT id,name,updated FROM characters ORDER BY updated DESC").fetchall()
    return [dict(r) for r in rows]


def save_chat(chat_id, character_id, title, messages):
    """Upsert chat + REPLACE messages ([{role, content}]). Falsy id -> generated."""
    chat_id = chat_id or ("h" + _nid())
    messages = list(messages or [])
    with _LOCK:
        cx = _cx()
        try:
            cx.execute(
                "INSERT INTO chats (id,character_id,title,created) VALUES (?,?,?,?)"
                " ON CONFLICT(id) DO UPDATE SET character_id=excluded.character_id,"
                " title=excluded.title", (chat_id, character_id or "", title or "", _now()))
            cx.execute("DELETE FROM messages WHERE chat_id=?", (chat_id,))
            cx.executemany("INSERT INTO messages (chat_id,role,content,idx) VALUES (?,?,?,?)",
                           [(chat_id, m.get("role", "user"), m.get("content", ""), i)
                            for i, m in enumerate(messages)])
            cx.commit()
        except Exception:
            cx.rollback()
            raise
    return chat_id


def load_chat(chat_id):
    with _LOCK:
        cx = _cx()
        c = cx.execute("SELECT * FROM chats WHERE id=?", (chat_id,)).fetchone()
        if not c:
            return None
        msgs = cx.execute("SELECT role,content FROM messages WHERE chat_id=? ORDER BY idx",
                          (chat_id,)).fetchall()
    return {"id": c["id"], "character_id": c["character_id"], "title": c["title"],
            "created": c["created"], "messages": [dict(m) for m in msgs]}


def list_chats(character_id=None):
    q = ("SELECT c.*, COUNT(m.id) AS count FROM chats c LEFT JOIN messages m ON m.chat_id=c.id")
    args = []
    if character_id:
        q += " WHERE c.character_id=?"
        args.append(character_id)
    q += " GROUP BY c.id ORDER BY c.created DESC"
    with _LOCK:
        rows = _cx().execute(q, args).fetchall()
    return [dict(r) for r in rows]


def add_fact(character_id, cat, text, ts=None, fid=None):
    fid = fid or ("f" + _nid())
    cid = (character_id or "").strip().lower()
    with _LOCK:
        _cx().execute(
            "INSERT INTO facts (id,character_id,cat,text,ts) VALUES (?,?,?,?,?)"
            " ON CONFLICT(id) DO UPDATE SET cat=excluded.cat, text=excluded.text, ts=excluded.ts",
            (fid, cid, cat or "ENTITY", (text or "")[:500], ts or _now()))
        _cx().commit()
    return fid


def add_facts(character_id, items):
    cid = (character_id or "").strip().lower()
    return [add_fact(cid, (i or {}).get("cat", "ENTITY"), (i or {}).get("text", ""),
                     (i or {}).get("ts"), (i or {}).get("id")) for i in (items or [])]


def list_facts(character_id):
    cid = (character_id or "").strip().lower()
    with _LOCK:
        if cid:
            rows = _cx().execute("SELECT id,cat,text,ts FROM facts WHERE LOWER(character_id)=? OR character_id=''"
                                 " ORDER BY ts ASC LIMIT 500", (cid,)).fetchall()
        else:
            rows = _cx().execute("SELECT id,cat,text,ts FROM facts ORDER BY ts ASC LIMIT 500").fetchall()
    return [dict(r) for r in rows]


def del_fact(fid):
    with _LOCK:
        _cx().execute("DELETE FROM facts WHERE id=?", (fid,))
        _cx().commit()


def add_image(character_id, url, caption="", created=None, iid=None):
    iid = iid or ("g" + _nid())
    cid = (character_id or "").strip().lower()
    with _LOCK:
        _cx().execute(
            "INSERT INTO images (id,character_id,url,caption,created) VALUES (?,?,?,?,?)"
            " ON CONFLICT(id) DO UPDATE SET url=excluded.url, caption=excluded.caption",
            (iid, cid, url or "", caption or "", created or _now()))
        _cx().commit()
    return iid


def list_images(character_id):
    cid = (character_id or "").strip().lower()
    with _LOCK:
        if cid:
            rows = _cx().execute("SELECT id,url,caption,created FROM images WHERE LOWER(character_id)=? OR character_id=''"
                                 " ORDER BY created DESC LIMIT 200", (cid,)).fetchall()
        else:
            rows = _cx().execute("SELECT id,url,caption,created FROM images ORDER BY created DESC LIMIT 200").fetchall()
    return [{"id": r["id"], "img": r["url"], "cap": r["caption"], "created": r["created"]}
            for r in rows]


def kv_set(key, value):
    with _LOCK:
        _cx().execute("INSERT INTO kv (key,value) VALUES (?,?)"
                      " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                      (key, value if isinstance(value, str) else json.dumps(value)))
        _cx().commit()


def kv_get(key, default=None):
    with _LOCK:
        r = _cx().execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    if not r:
        return default
    try:
        return json.loads(r["value"])
    except Exception:
        return r["value"]


def save_group_room(room_id, title, scenario, characters, active_speaker="auto"):
    room_id = room_id or ("gr_" + _nid())
    chars_json = json.dumps(characters if isinstance(characters, list) else [])
    with _LOCK:
        _cx().execute(
            "INSERT INTO group_rooms (id,title,scenario,characters,active_speaker,updated) VALUES (?,?,?,?,?,?)"
            " ON CONFLICT(id) DO UPDATE SET title=excluded.title, scenario=excluded.scenario,"
            " characters=excluded.characters, active_speaker=excluded.active_speaker, updated=excluded.updated",
            (room_id, title or "Group Chat", scenario or "", chars_json, active_speaker or "auto", _now()))
        _cx().commit()
    return room_id


def load_group_room(room_id):
    with _LOCK:
        r = _cx().execute("SELECT * FROM group_rooms WHERE id=?", (room_id,)).fetchone()
    if not r:
        return None
    try:
        chars = json.loads(r["characters"])
    except Exception:
        chars = []
    return {
        "id": r["id"],
        "title": r["title"],
        "scenario": r["scenario"],
        "characters": chars,
        "activeSpeaker": r["active_speaker"],
        "updated": r["updated"]
    }


def list_group_rooms():
    with _LOCK:
        rows = _cx().execute("SELECT id,title,scenario,characters,active_speaker,updated FROM group_rooms ORDER BY updated DESC").fetchall()
    res = []
    for r in rows:
        try:
            chars = json.loads(r["characters"])
        except Exception:
            chars = []
        res.append({
            "id": r["id"],
            "title": r["title"],
            "scenario": r["scenario"],
            "characters": chars,
            "activeSpeaker": r["active_speaker"],
            "updated": r["updated"]
        })
    return res


def delete_group_room(room_id):
    with _LOCK:
        _cx().execute("DELETE FROM group_rooms WHERE id=?", (room_id,))
        _cx().execute("DELETE FROM group_messages WHERE room_id=?", (room_id,))
        _cx().commit()


def save_group_chat(room_id, messages):
    messages = list(messages or [])
    with _LOCK:
        cx = _cx()
        try:
            cx.execute("DELETE FROM group_messages WHERE room_id=?", (room_id,))
            cx.executemany(
                "INSERT INTO group_messages (room_id,role,speaker,speaker_name,content,idx) VALUES (?,?,?,?,?,?)",
                [(room_id, m.get("role", "assistant"), m.get("speaker", ""), m.get("speakerName", ""), m.get("content", ""), i)
                 for i, m in enumerate(messages)])
            cx.execute("UPDATE group_rooms SET updated=? WHERE id=?", (_now(), room_id))
            cx.commit()
        except Exception:
            cx.rollback()
            raise
    return room_id


def load_group_chat(room_id):
    with _LOCK:
        cx = _cx()
        msgs = cx.execute("SELECT role,speaker,speaker_name,content FROM group_messages WHERE room_id=? ORDER BY idx", (room_id,)).fetchall()
    return [{"role": m["role"], "speaker": m["speaker"], "speakerName": m["speaker_name"], "content": m["content"]} for m in msgs]


def export_json():
    with _LOCK:
        cx = _cx()
        ver = cx.execute("SELECT v FROM schema_version LIMIT 1").fetchone()["v"]
        out = {"schema_version": ver,
               "characters": [dict(r) for r in cx.execute("SELECT * FROM characters").fetchall()],
               "chats": [dict(r) for r in cx.execute("SELECT * FROM chats").fetchall()],
               "messages": [dict(r) for r in
                            cx.execute("SELECT * FROM messages ORDER BY chat_id, idx").fetchall()],
               "facts": [dict(r) for r in cx.execute("SELECT * FROM facts").fetchall()],
               "images": [dict(r) for r in cx.execute("SELECT * FROM images").fetchall()],
               "kv": {r["key"]: r["value"] for r in cx.execute("SELECT * FROM kv").fetchall()},
               "group_rooms": [dict(r) for r in cx.execute("SELECT * FROM group_rooms").fetchall()],
               "group_messages": [dict(r) for r in cx.execute("SELECT * FROM group_messages ORDER BY room_id, idx").fetchall()]}
    return out


def import_json(b):
    """Full restore: wipes tables, re-inserts export_json() shape (incl. schema version)."""
    with _LOCK:
        cx = _cx()
        try:
            for t in ("messages", "chats", "facts", "images", "characters", "kv", "group_messages", "group_rooms"):
                try:
                    cx.execute(f"DELETE FROM {t}")
                except Exception:
                    pass
            for c in b.get("characters", []):
                cx.execute("INSERT INTO characters (id,name,data,updated) VALUES (?,?,?,?)",
                           (c["id"], c["name"], c["data"] if isinstance(c["data"], str)
                            else json.dumps(c.get("data", {})), c.get("updated", _now())))
            for c in b.get("chats", []):
                cx.execute("INSERT INTO chats (id,character_id,title,created) VALUES (?,?,?,?)",
                           (c["id"], c.get("character_id", ""), c.get("title", ""), c.get("created", _now())))
            for m in b.get("messages", []):
                cx.execute("INSERT INTO messages (chat_id,role,content,idx) VALUES (?,?,?,?)",
                           (m["chat_id"], m["role"], m.get("content", ""), m.get("idx", 0)))
            for f in b.get("facts", []):
                cx.execute("INSERT INTO facts (id,character_id,cat,text,ts) VALUES (?,?,?,?,?)",
                           (f["id"], f.get("character_id", ""), f.get("cat", "ENTITY"),
                            f.get("text", ""), f.get("ts", _now())))
            for g in b.get("images", []):
                cx.execute("INSERT INTO images (id,character_id,url,caption,created) VALUES (?,?,?,?,?)",
                           (g["id"], g.get("character_id", ""), g.get("url", g.get("img", "")),
                            g.get("caption", g.get("cap", "")), g.get("created", _now())))
            for k, v in (b.get("kv", {}) or {}).items():
                cx.execute("INSERT INTO kv (key,value) VALUES (?,?)",
                           (k, v if isinstance(v, str) else json.dumps(v)))
            for gr in b.get("group_rooms", []):
                cx.execute("INSERT INTO group_rooms (id,title,scenario,characters,active_speaker,updated) VALUES (?,?,?,?,?,?)",
                           (gr["id"], gr.get("title", ""), gr.get("scenario", ""),
                            gr["characters"] if isinstance(gr["characters"], str) else json.dumps(gr.get("characters", [])),
                            gr.get("active_speaker", "auto"), gr.get("updated", _now())))
            for gm in b.get("group_messages", []):
                cx.execute("INSERT INTO group_messages (room_id,role,speaker,speaker_name,content,idx) VALUES (?,?,?,?,?,?)",
                           (gm["room_id"], gm.get("role", "assistant"), gm.get("speaker", ""), gm.get("speaker_name", ""),
                            gm.get("content", ""), gm.get("idx", 0)))
            cx.execute("UPDATE schema_version SET v=?", (b.get("schema_version", SCHEMA_VERSION),))
            cx.commit()
        except Exception:
            cx.rollback()
            raise
