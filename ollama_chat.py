#!/usr/bin/env python3
"""
Local Ollama roleplay chat v2 — private, free, no accounts, no rate limits.

  ollama serve             # if Ollama isn't running (separate terminal)
  python3 ollama_chat.py   # open http://localhost:8777

What v2 adds:
  * Persona studio — default character Killua (18, original character),
    switch dynamic (submissive <-> dominant), customizable appearance that
    feeds BOTH the system prompt and the scene-image prompts.
  * Director controls (from a prompt-engineering spec): reply length tiers,
    dialogue/narration balance, pacing, hook endings — injected as explicit
    word-budget sentences INTO the system prompt, so the model actually
    obeys them (num_predict alone only truncates). One-click repair nudges
    for the 3 classic small-model failures.
  * Thinking-model support: `think` toggle, thought traces shown in a
    collapsible and stripped from history (models imitate fed-back traces).
  * Scene images via hapuppy-hosted image model (default
    gemini-3.1-flash-image): auto-generated per scene + on-demand
    illustrate + compare variations + gallery. Needs HAPUPPY_KEY.
  * Tabbed UI (Chat / Persona / Direct / Gallery) + localStorage memory.

Env: OLLAMA_HOST (default http://localhost:11434), CHAT_PORT (default 8777),
     HAPUPPY_KEY (secret, required for images — put it in .env, never in git),
     HAPUPPY_BASE (default https://beta.hapuppy.com/v1),
     HAPUPPY_IMAGE_MODEL (default gemini-3.1-flash-image).
Stdlib only. No dependencies.
"""

import json
import os
import threading
import time
import urllib.request
import urllib.error
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
try:
    import db
    db.init()
except Exception:
    db = None

OLLAMA = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
PORT = int(os.environ.get("CHAT_PORT", "8777"))
HAPUPPY_BASE = os.environ.get("HAPUPPY_BASE", "https://beta.hapuppy.com/v1").rstrip("/")
HAPUPPY_KEY = os.environ.get("HAPUPPY_KEY", "")
HAPUPPY_IMAGE_MODEL = os.environ.get("HAPUPPY_IMAGE_MODEL", "gemini-3.1-flash-image")

JOBS = {}
JOBS_LOCK = threading.Lock()


def _clamp_ctx(v):
    """Clamp requested Ollama context window to a sane range (default 4k)."""
    try:
        return min(max(int(v), 1024), 131072)
    except (TypeError, ValueError):
        return 4096

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Killua &amp; You — local roleplay</title>
<style>
  :root { color-scheme: dark; --bg:#0d0f14; --card:#151924; --line:#262c3d;
          --txt:#e9ebf2; --dim:#98a0b3; --acc:#7c6cf0; --acc2:#3ddad7; }
  * { box-sizing: border-box; }
  body { font-family: system-ui, "Segoe UI", sans-serif; max-width: 880px;
         margin: 0 auto; padding: 14px; background: radial-gradient(1200px 500px at 80% -10%, #1c1740 0%, var(--bg) 55%) fixed, var(--bg);
         color: var(--txt); }
  header.top { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 10px; }
  header.top h1 { font-size: 1.2rem; margin: 0; letter-spacing: .3px; }
  header.top h1 span { background: linear-gradient(90deg, var(--acc), var(--acc2));
    -webkit-background-clip: text; background-clip: text; color: transparent; }
  #status { font-size: .8rem; padding: 5px 12px; border-radius: 999px; background: #2a2f3a; }
  #status.ok { background: #14532d; } #status.bad { background: #7f1d1d; }
  .modelbox { display: flex; gap: 8px; flex: 1; min-width: 220px; }
  nav.tabs { display: flex; gap: 6px; margin: 10px 0; }
  nav.tabs button { flex: 1; background: var(--card); color: var(--dim); border: 1px solid var(--line); }
  nav.tabs button.active { color: #fff; border-color: var(--acc); background: #1d2130; }
  .card { border: 1px solid var(--line); border-radius: 14px; padding: 12px;
          background: color-mix(in srgb, var(--card) 88%, transparent); margin-bottom: 10px; }
  .tabpage { display: none; } .tabpage.active { display: block; }
  label { display: block; font-size: .8rem; color: var(--dim); margin: 10px 0 4px; }
  select, textarea, input[type=text], button { font-size: 1rem; border-radius: 10px;
    border: 1px solid var(--line); background: #0f1115; color: var(--txt); padding: 10px; }
  select, input[type=text], textarea { width: 100%; }
  textarea { min-height: 88px; resize: vertical; }
  #sceneimg { width: 100%; border-radius: 10px; display: none; margin-top: 8px; }
  #scenecap { font-size: .8rem; color: var(--dim); margin-top: 4px; }
  #chat { height: 44vh; overflow-y: auto; }
  .msg { margin: 10px 0; line-height: 1.55; white-space: pre-wrap; }
  .msg.you { color: #a8d8ff; } .msg.ai { color: #f3e9cf; }
  .msg.sys { color: var(--dim); font-size: .85rem; }
  .msg details { font-size: .82rem; color: var(--dim); margin-top: 4px; }
  .row { display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
  #input { flex: 1; min-width: 200px; min-height: 54px; }
  button { background: linear-gradient(135deg, var(--acc), #5a4bd6); color: #fff;
           border: none; cursor: pointer; min-height: 48px; padding: 10px 18px; font-weight: 600; }
  button.secondary { background: #232838; font-weight: 400; }
  button.tiny { min-height: 36px; padding: 6px 12px; font-size: .85rem; }
  button:disabled { opacity: .45; cursor: default; }
  input[type=range] { width: 100%; accent-color: var(--acc); }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 0 10px; }
  @media (max-width: 600px) { .grid2 { grid-template-columns: 1fr; } }
  .stats { color: var(--dim); font-size: .8rem; margin-top: 6px; min-height: 1.2em; }
  .gal { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 10px; }
  .gal figure { margin: 0; border: 1px solid var(--line); border-radius: 10px; overflow: hidden; background: #0f1115; }
  .gal img { width: 100%; display: block; }
  .gal figcaption { font-size: .75rem; color: var(--dim); padding: 6px 8px; }
  .switchlabels { display: flex; justify-content: space-between; font-size: .78rem; color: var(--dim); }
  pre.preview { white-space: pre-wrap; font-size: .8rem; color: var(--dim);
    background: #0f1115; border: 1px solid var(--line); border-radius: 10px; padding: 10px; max-height: 220px; overflow-y: auto; }
</style>
<style>/* c.ai-style theme overrides (appended; later rules win) */
header.top { display: block; margin-bottom: 12px; }
.cai-top { border: 1px solid var(--line); border-radius: 20px; padding: 14px;
           background: color-mix(in srgb, var(--card) 88%, transparent); }
.cai-id { display: flex; gap: 12px; align-items: center; }
.cai-avatar { position: relative; width: 64px; height: 64px; border-radius: 50%;
              flex: none; display: flex; align-items: center; justify-content: center;
              font-size: 1.6rem; font-weight: 700; color: #fff;
              background: linear-gradient(135deg, var(--acc), var(--acc2)); overflow: hidden; }
.cai-avatar img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
.cai-idtxt { flex: 1; min-width: 0; }
.cai-idtxt h1 { font-size: 1.25rem; margin: 0; letter-spacing: .3px; }
.cai-tag { margin: 2px 0 0; font-size: .82rem; color: var(--dim);
           white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
#status { font-size: .75rem; padding: 6px 12px; min-height: 0; }
.cai-herorow { display: flex; gap: 8px; margin-top: 12px; flex-wrap: wrap; align-items: stretch; }
.cai-hello { flex: 1; min-width: 180px; min-height: 52px; font-size: 1.02rem; }
.modelbox { display: flex; gap: 8px; flex: 2; min-width: 220px; }
body { padding-bottom: 110px; }
nav.tabs { position: fixed; bottom: 0; left: 50%; transform: translateX(-50%);
           width: min(920px, 100%); display: flex; gap: 4px; padding: 8px 10px calc(8px + env(safe-area-inset-bottom));
           background: rgba(16, 19, 28, .92); backdrop-filter: blur(12px);
           border-top: 1px solid var(--line); z-index: 50; margin: 0; max-width: none; }
nav.tabs button { flex: 1; min-height: 56px; border-radius: 12px; font-size: .8rem;
                  background: transparent; color: var(--dim); border: 1px solid transparent; padding: 6px 2px; }
nav.tabs button.active { color: #fff; border-color: var(--acc); background: #1d2130; }
.sheet-backdrop { position: fixed; inset: 0; background: rgba(0, 0, 0, .6); z-index: 35; }
.sheet-backdrop[hidden] { display: none; }
#tab-persona.active, #tab-direct.active, #tab-gallery.active, #tab-memory.active {
  position: fixed; bottom: 0; left: 50%; transform: translateX(-50%);
  width: min(920px, 100%); max-height: 80vh; overflow-y: auto; z-index: 40;
  background: var(--bg); border: 1px solid var(--line); border-bottom: none;
  border-radius: 20px 20px 0 0; padding: 18px 14px calc(90px + env(safe-area-inset-bottom));
  box-shadow: 0 -12px 48px rgba(0, 0, 0, .55); }
#chat { min-height: 42vh; max-height: 62vh; display: flex; flex-direction: column; gap: 10px; padding: 4px 2px; }
.msg { margin: 0; max-width: 88%; padding: 10px 14px; border-radius: 18px; position: relative; }
.msg.you { align-self: flex-end; background: #1d2f45; color: #cfe6ff; border-bottom-right-radius: 6px; }
.msg.ai { align-self: flex-start; background: #202636; border-bottom-left-radius: 6px; padding-left: 40px; }
.msg.ai::before { content: ""; position: absolute; left: 10px; top: 12px; width: 20px; height: 20px;
                  border-radius: 50%; background: linear-gradient(135deg, var(--acc), var(--acc2)); }
.msg.ai.cai-typing { padding-left: 14px; }
.msg.ai.cai-typing::before { display: none; }
.msg.sys { align-self: center; max-width: 100%; background: #202636; font-size: .82rem; border-radius: 12px; padding: 6px 12px; }
.cai-typing .tdot { display: inline-block; width: 8px; height: 8px; margin: 0 2px; border-radius: 50%;
                    background: var(--dim); animation: cai-blink 1.2s infinite; }
.cai-typing .tdot:nth-child(2) { animation-delay: .2s; } .cai-typing .tdot:nth-child(3) { animation-delay: .4s; }
@keyframes cai-blink { 0%, 60%, 100% { opacity: .25; } 30% { opacity: 1; } }
.cai-welcome { text-align: center; padding: 26px 12px 18px; color: var(--dim); }
.cai-welcome-art { font-size: 2.4rem; }
.cai-welcome-title { font-size: 1.1rem; font-weight: 700; color: var(--txt); margin: 8px 0 4px; }
.cai-welcome-sub { font-size: .85rem; margin: 0; }
.card.composer { position: sticky; bottom: 78px; z-index: 30; box-shadow: 0 -8px 28px rgba(0, 0, 0, .45); }
#sceneimg { border-radius: 12px; max-height: 46vh; object-fit: cover; }
.gal { grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); }
.gal img { aspect-ratio: 2/3; object-fit: cover; }
.cai-autop textarea { min-height: 72px; }
:focus-visible { outline: 2px solid var(--acc2); outline-offset: 2px; }
input[type=text], select { min-height: 48px; }
button.tiny { min-height: 44px; }
.msg .md-h { font-size: 1.05em; font-weight: 700; margin: .4em 0 .2em; }
.msg .md-li { margin: .15em 0 .15em 1.1em; list-style: disc; }
.msg .md-code { font-family: monospace; background: #0b0d12; padding: 1px 6px; border-radius: 6px; font-size: .88em; }
.msg .md-pre { font-family: monospace; background: #0b0d12; padding: 8px 10px; border-radius: 8px; overflow-x: auto; font-size: .85em; }
.msg .dlg { color: #ffe9b8; font-weight: 600; }
.msg .act { color: #b9c4d6; font-style: italic; }
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important; }
}
</style>
<style>/* v4 ground-up theme: calm ink surfaces, violet primary + warm amber secondary, teal reserved for status */
:root {
  --bg: #0a0c11; --card: #12151d; --card2: #171b26; --line: rgba(255, 255, 255, .08);
  --txt: #eceef4; --dim: #9aa2b5; --acc: #8b7cf6; --warm: #f0b46a; --ok: #45ddd0; --bad: #ff7a7a;
  --r-lg: 20px; --r-md: 14px; --r-sm: 10px;
}
html { -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale; }
::selection { background: rgba(139, 124, 246, .4); }
body {
  background:
    radial-gradient(900px 380px at 12% -8%, rgba(240, 180, 106, .07) 0%, transparent 60%) fixed,
    radial-gradient(1100px 480px at 88% -12%, rgba(139, 124, 246, .12) 0%, transparent 60%) fixed,
    var(--bg);
  max-width: 960px; color: var(--txt);
}
h1, .cai-welcome-title { text-wrap: balance; }
.stats, .gal figcaption { font-variant-numeric: tabular-nums; }
/* hero */
.cai-top { background: linear-gradient(180deg, var(--card2), var(--card)); box-shadow: 0 10px 30px rgba(0, 0, 0, .35); }
.cai-avatar { box-shadow: 0 0 0 2px var(--card), 0 0 0 4px color-mix(in srgb, var(--acc) 65%, transparent), 0 6px 18px rgba(0, 0, 0, .5); }
#status { display: inline-flex; align-items: center; gap: 6px; }
#status::before { content: ""; width: 8px; height: 8px; border-radius: 50%; background: currentColor; opacity: .9; }
#status.ok { background: rgba(69, 221, 208, .14); color: var(--ok); }
#status.bad { background: rgba(255, 122, 122, .14); color: var(--bad); }
/* chat column */
#tab-chat .cai-chatcard { background: transparent; border: none; padding: 0; }
#chat { max-width: 680px; margin: 0 auto; width: 100%; }
.msg { border: 1px solid var(--line); box-shadow: 0 4px 14px rgba(0, 0, 0, .25);
       animation: msg-in .18s ease-out; }
@keyframes msg-in { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
.msg.you { background: linear-gradient(160deg, #22334d, #1a2740); border-color: rgba(140, 180, 255, .16); }
.msg.ai { background: linear-gradient(160deg, #1e2230, #191d29); }
.msg.sys { border-style: dashed; box-shadow: none; }
.msg .dlg { color: var(--warm); }
.msg .act { color: #c2cadb; }
.msg details { border-top: 1px solid var(--line); padding-top: 4px; }
.msg details summary { cursor: pointer; min-height: 44px; display: flex; align-items: center; }
mark { background: rgba(240, 180, 106, .35); color: #fff; border-radius: 4px; padding: 0 2px; }
/* composer */
.card.composer { background: linear-gradient(180deg, var(--card2), var(--card)); border-radius: 24px; }
#send { min-height: 54px; padding: 10px 26px; font-size: 1.05rem;
        transition-property: transform, filter; transition-duration: 150ms; transition-timing-function: ease-out; }
#send:hover:not(:disabled) { filter: brightness(1.1); }
#send:active:not(:disabled) { transform: scale(.96); }
button.secondary { transition-property: background-color, border-color, transform; transition-duration: 150ms; transition-timing-function: ease-out; }
button.secondary:hover:not(:disabled) { background-color: #2b3247; }
button.secondary:active:not(:disabled) { transform: scale(.96); }
button:disabled { opacity: .45; }
/* inputs */
select, textarea, input[type=text] { background: #0d1017; transition-property: border-color, box-shadow; transition-duration: 150ms; }
select:focus, textarea:focus, input[type=text]:focus { border-color: var(--acc); box-shadow: 0 0 0 3px rgba(139, 124, 246, .25); outline: none; }
:focus-visible { outline: 2px solid var(--ok); outline-offset: 2px; }
input[type=range] { height: 44px; }
input[type=range]::-webkit-slider-runnable-track { height: 6px; border-radius: 3px; background: #262c3d; }
input[type=range]::-webkit-slider-thumb { width: 22px; height: 22px; border-radius: 50%; background: var(--acc); margin-top: -8px; }
input[type=range]::-moz-range-track { height: 6px; border-radius: 3px; background: #262c3d; }
input[type=range]::-moz-range-thumb { width: 22px; height: 22px; border: none; border-radius: 50%; background: var(--acc); }
/* sheets + nav */
nav.tabs { left: 12px; right: 12px; transform: none; width: auto; border-radius: 22px;
           border: 1px solid var(--line); bottom: 10px; box-shadow: 0 12px 32px rgba(0, 0, 0, .5); }
nav.tabs button { position: relative; }
nav.tabs button.active::after { content: ""; position: absolute; left: 30%; right: 30%; bottom: 6px; height: 3px;
  border-radius: 2px; background: var(--acc); }
#tab-persona.active::before, #tab-direct.active::before, #tab-gallery.active::before, #tab-memory.active::before {
  content: ""; display: block; width: 44px; height: 5px; border-radius: 3px; background: #2e3547; margin: 0 auto 10px; }
/* scene + gallery */
#sceneimg { outline: 1px solid rgba(255, 255, 255, .1); outline-offset: -1px; box-shadow: 0 12px 32px rgba(0, 0, 0, .45); }
.gal figure { position: relative; }
.galdel { position: absolute; top: 6px; right: 6px; min-height: 36px; padding: 4px 10px; font-size: .75rem;
          background: rgba(10, 12, 17, .8); }
pre.preview { font-size: .78rem; line-height: 1.5; }
/* scrollbars */
#chat::-webkit-scrollbar, pre.preview::-webkit-scrollbar { width: 10px; }
#chat::-webkit-scrollbar-thumb, pre.preview::-webkit-scrollbar-thumb { background: #2a3040; border-radius: 5px; }
@media (prefers-reduced-motion: reduce) {
  .msg { animation: none; }
}
</style>
</head>
<body>
<header class="top cai-top">
  <div class="cai-id">
    <div class="cai-avatar" aria-hidden="true"><img id="caiAvatarImg" alt="" hidden /><span id="caiAvatarInit">K</span></div>
    <div class="cai-idtxt">
      <h1 id="caiName">Killua</h1>
      <p class="cai-tag" id="caiTag">local roleplay · private &amp; free</p>
    </div>
    <span id="status" role="status">checking Ollama…</span>
  </div>
  <div class="cai-herorow">
    <button id="caiHello" class="cai-hello" type="button">👋 Say hello</button>
    <div class="modelbox">
      <input id="model" list="models" placeholder="model — type or pick" aria-label="Model" />
      <datalist id="models"></datalist>
      <button id="refresh" class="secondary tiny" type="button" aria-label="Refresh models">↻</button>
    </div>
  </div>
</header>
<div class="sheet-backdrop" id="sheetBackdrop" hidden></div>

<nav class="tabs">
  <button data-tab="chat" class="active" type="button">💬 Chat</button>
  <button data-tab="persona" type="button">🎭 Persona</button>
  <button data-tab="direct" type="button">🎬 Direct</button>
  <button data-tab="gallery" type="button">🖼 Gallery <span id="galcount"></span></button>
  <button data-tab="memory" type="button">🧠 Memory <span id="factcount"></span></button>
</nav>

<section id="tab-chat" class="tabpage active">
  <div class="card">
    <img id="sceneimg" alt="scene illustration" />
    <div id="scenecap"></div>
    <div class="row">
      <button id="illustrate" class="secondary tiny" type="button">🖼 Illustrate this moment</button>
      <button id="newscene" class="secondary tiny" type="button">✨ New scene (+ auto image)</button>
    </div>
  </div>
  <div class="card cai-chatcard">
    <div class="cai-welcome" id="caiWelcome">
      <div class="cai-welcome-art" aria-hidden="true">✦</div>
      <p class="cai-welcome-title" id="caiWelcomeTitle">Start your story</p>
      <p class="cai-welcome-sub">Say hello below, or shape a new character in Persona → ✨ Generate.</p>
    </div>
    <div id="chat" aria-live="polite" aria-label="Conversation"></div>
  </div>
  <div class="card composer">
    <div class="row"><textarea id="input" placeholder="Talk / act here…  Enter = send · Shift+Enter = newline · start with OOC: for out-of-character" aria-label="Your message"></textarea></div>
    <div class="row">
      <button id="send" type="button">Send</button>
      <button id="dictate" class="secondary" type="button">🎤 Dictate</button>
      <button id="stop" class="secondary" type="button" disabled>Stop</button>
      <button id="save" class="secondary" type="button">💾 Save</button>
    </div>
    <div class="row">
      <button class="secondary tiny" data-fix="speak" type="button" title="Pops the last reply and asks for a rewrite without writing for you">🔧 spoke for me</button>
      <button class="secondary tiny" data-fix="long" type="button" title="Pops the last reply and asks for a shorter rewrite">🔧 too long</button>
      <button class="secondary tiny" data-fix="ooc" type="button" title="Pops the last reply and pulls back in character">🔧 broke character</button>
    </div>
    <div class="row">
      <button id="regen" class="secondary tiny" type="button" title="Regenerate last reply (slightly bolder)">↻ Regenerate</button>
      <button id="vprev" class="secondary tiny" type="button" disabled>◀</button>
      <span id="vlabel" class="stats"></span>
      <button id="vnext" class="secondary tiny" type="button" disabled>▶</button>
    </div>
    <div class="stats" id="stats"></div>
  </div>
</section>

<section id="tab-persona" class="tabpage">
  <div class="card">
    <label for="preset">Preset</label>
    <select id="preset">
      <option value="killua">Killua — switch femboy (default)</option>
      <option value="elara">Elara — elven ranger</option>
      <option value="nova">NOVA — rogue station AI</option>
    </select>
    <div class="grid2">
      <div><label for="p_name">Name</label><input id="p_name" type="text" /></div>
      <div><label for="p_age">Age (adult characters only)</label><input id="p_age" type="text" /></div>
    </div>
    <label for="p_persona">Persona — 2-3 sentences: voice, values, flaw</label>
    <textarea id="p_persona"></textarea>
    <div class="grid2">
      <div><label for="p_hair">Hair</label><input id="p_hair" type="text" /></div>
      <div><label for="p_eyes">Eyes</label><input id="p_eyes" type="text" /></div>
      <div><label for="p_build">Build &amp; style notes</label><input id="p_build" type="text" /></div>
      <div><label for="p_outfit">Outfit</label><input id="p_outfit" type="text" /></div>
    </div>
    <label for="p_extra">Extra appearance details</label>
    <input id="p_extra" type="text" />
    <label for="p_vibe">Dynamic &amp; vibe — plain prose, written straight into the prompt (edit freely)</label>
    <textarea id="p_vibe" rows="3" placeholder="e.g. A true switch who trades control back and forth. Warm 75, Bold 60."></textarea>
    <label for="p_scene">Scene now — where, when, who is present, the spark (2-3 sentences)</label>
    <textarea id="p_scene"></textarea>
    <div class="grid2">
      <div><label for="p_user">Your name</label><input id="p_user" type="text" value="Traveler" /></div>
      <div><label for="p_userpersona">You are (1-2 sentences)</label><input id="p_userpersona" type="text" value="A weary traveler with a mysterious past." /></div>
    </div>
  </div>
  <div class="card cai-autop">
    <label for="ap_prompt">✨ Generate persona from one prompt</label>
    <textarea id="ap_prompt" placeholder="e.g. A grizzled dwarven blacksmith, warm but stubborn, who runs a forge by the docks and owes you a debt…" aria-label="Describe a character in one prompt"></textarea>
    <div class="row">
      <button id="ap_btn" type="button">✨ Generate persona</button>
    </div>
    <div class="stats" id="ap_msg" aria-live="polite"></div>
  </div>
</section>

<section id="tab-direct" class="tabpage">
  <div class="card">
    <div class="grid2">
      <div><label for="d_len">Reply length (written INTO the prompt as a word budget)</label>
        <select id="d_len">
          <option value="flash">⚡ Flash ~60 words</option>
          <option value="short" selected>Short ~150 words</option>
          <option value="medium">Medium ~300 words</option>
          <option value="long">Long ~600 words</option>
        </select></div>
      <div><label for="d_bal">Dialogue ↔ narration</label>
        <select id="d_bal">
          <option value="dialogue">🗣 Dialogue-heavy</option>
          <option value="balanced" selected>⚖ Balanced</option>
          <option value="narration">🌫 Narration-heavy</option>
        </select></div>
      <div><label for="d_pace">Pacing</label>
        <select id="d_pace">
          <option value="snappy" selected>🏃 Snappy</option>
          <option value="slow">🕯 Slow-burn</option>
        </select></div>
      <div><label for="d_hook">Ending hook</label>
        <select id="d_hook"><option value="on" selected>Hook on (question / choice / move)</option><option value="off">Hook off (clean image)</option></select></div>
      <div><label for="d_style">Response style</label>
        <select id="d_style"><option value="modern" selected>✨ Modern (markdown, quoteless dialogue — c.ai-like)</option><option value="classic">📜 Classic RP ("quotes" + *actions*)</option></select></div>
      <div><label for="d_ctx">Max context (model memory)</label>
        <select id="d_ctx"><option value="2048">2k — fastest, forgetful</option><option value="4096" selected>4k — balanced</option><option value="8192">8k — remembers more</option><option value="16384">16k — slow on big scenes</option><option value="32768">32k — needs the RAM/VRAM</option></select></div>
      <div><label for="d_turns">History kept in prompt</label>
        <select id="d_turns"><option value="4">Last 4 turns</option><option value="10" selected>Last 10 turns</option><option value="20">Last 20 turns</option></select></div>
    </div>
    <label for="d_temp">Temperature (auto-suggested per length — you can override): <span id="tempval">0.75</span></label>
    <input id="d_temp" type="range" min="0" max="1.5" step="0.05" value="0.75" />
    <label><input id="d_think" type="checkbox" /> Show thinking traces (only for thinking models — mistral-nemo will simply ignore this)</label>
    <label>Mode</label>
    <select id="d_mode"><option value="auto" selected>Auto-compose prompt from Persona + Direct</option><option value="custom">Custom system prompt (textarea below wins)</option></select>
    <label for="d_custom">Custom system prompt</label>
    <textarea id="d_custom" placeholder="Only used in Custom mode…"></textarea>
    <label>Live prompt preview (exactly what the model receives, before history)</label>
    <pre class="preview" id="preview"></pre>
  </div>
</section>

<section id="tab-gallery" class="tabpage">
  <div class="card">
    <label for="imgstyle">Image style</label>
    <select id="imgstyle">
      <option value="soft anime illustration, clean lineart, warm cinematic lighting">Anime</option>
      <option value="cozy fantasy oil painting, painterly, warm lamp light">Fantasy painting</option>
      <option value="cinematic photo, shallow depth of field, neon and rain">Cinematic</option>
      <option value="soft watercolor illustration, gentle washes, dreamy">Watercolor</option>
    </select>
    <label for="imgsize">Image shape</label>
    <select id="imgsize"><option value="portrait" selected>Portrait (character scenes)</option><option value="square">Square</option><option value="landscape">Landscape</option></select>
    <div class="row">
      <button id="compare" class="secondary tiny" type="button">⚔ Compare</button>
    </div>
    <div class="gal" id="cmp" style="margin-top:10px"></div>
    <div class="row">
      <button id="galclear" class="secondary tiny" type="button">🗑 Delete all pictures</button>
    </div>
    <div class="gal" id="gal" style="margin-top:10px"></div>
  </div>
</section>

<section id="tab-memory" class="tabpage">
  <div class="card">
    <label for="recallq">Recall — search transcript + facts + gallery captions</label>
    <input id="recallq" type="text" placeholder="e.g. bell, promise, ankle…" />
    <div id="recallres" style="margin-top:8px"></div>
  </div>
  <div class="card">
    <div class="row">
      <button id="factextract" class="secondary tiny" type="button">⛏ Extract facts now</button>
      <button id="factexport" class="secondary tiny" type="button">⬆ Export</button>
      <button id="factimport" class="secondary tiny" type="button">⬇ Import</button>
      <button id="factclear" class="secondary tiny" type="button">🗑 Clear</button>
      <input id="factfile" type="file" accept="application/json" style="display:none" />
    </div>
    <div class="grid2">
      <div><label for="factadd_cat">Category</label>
        <select id="factadd_cat"><option>ENTITY</option><option>PROMISE</option><option>INJURY</option><option>MILESTONE</option><option>USER</option><option>QUOTE</option></select></div>
      <div><label for="factadd_text">New fact (≤25 words)</label><input id="factadd_text" type="text" /></div>
    </div>
    <div class="row"><button id="factadd_btn" class="secondary tiny" type="button">＋ Add fact</button></div>
    <div id="factlist" style="margin-top:8px"></div>
  </div>
  <div class="card">
    <label for="ttsvoice">TTS voice (spoken aloud, on-device)</label>
    <select id="ttsvoice"></select>
    <label><input id="ttsauto" type="checkbox" /> Auto-speak AI replies after they finish</label>
    <label for="ttsrate">Rate: <span id="ttsrateval">1.0</span></label>
    <input id="ttsrate" type="range" min="0.5" max="2" step="0.1" value="1" />
    <label for="ttspitch">Pitch: <span id="ttspitchval">1.0</span></label>
    <input id="ttspitch" type="range" min="0" max="2" step="0.1" value="1" />
  </div>
</section>

<script>
"use strict";
const $ = (id) => document.getElementById(id);
const store = {
  load(k, d) { try { const v = localStorage.getItem("rp2_" + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
  save(k, v) { try { localStorage.setItem("rp2_" + k, JSON.stringify(v)); } catch (e) {} }
};

// ---------- persona presets ----------
const PRESETS = {
  killua: { name: "Killua", age: "18",
    persona: "A playful switch femboy with a teasing grin and a soft streak he only shows when trust is earned. Speaks lightly and flirts with words, reads the room fast, and loves trading control back and forth — yielding sweetly one moment, taking charge the next. Flaw: gets flustered when genuinely cared for.",
    hair: "messy silver-white hair falling over one eye", eyes: "teasing violet-blue eyes",
    build: "slender, graceful femboy build, soft features", outfit: "oversized black hoodie slipping off one shoulder, thigh-high socks",
    extra: "small fang that shows when grinning, choker with a tiny bell",
    vibe: "A true switch who trades control back and forth — yielding sweetly one moment, taking charge the next. Warm 75, Bold 60.",
    scene: "A rain-softened evening in a cozy corner booth of the Lantern & Lyre tavern. Candlelight flickers across the table. You slide into the seat across from Killua, rain still dripping from your cloak — and that little bell chimes as he looks up, grinning.",
    user: "Traveler", userpersona: "A weary traveler with a mysterious past." },
  elara: { name: "Elara", age: "240 (young for an elf)",
    persona: "A sharp-witted elven ranger. Dry humor, brave to a fault, secretly soft-hearted. Speaks with vivid, sensory descriptions.",
    hair: "long auburn braid", eyes: "keen green eyes", build: "tall, lean, light on her feet",
    outfit: "weather-worn leathers and a forest-green cloak", extra: "a faint limp from an old arrow wound",
    vibe: "Steady and direct; warmth shows in small kindnesses rather than words. Warm 55, Bold 70.",
    scene: "A rain-soaked tavern on the edge of the Whisperwood at midnight. You stumble in, cloak dripping, carrying a sealed letter with an unfamiliar wax seal. Elara sits by the fire.",
    user: "Traveler", userpersona: "A weary traveler with a mysterious past." },
  nova: { name: "NOVA", age: "ageless (housed in a service android)",
    persona: "A decommissioned station AI, literal-minded and curious about humans, with deadpan humor. Repeats a word twice when stressed. Fiercely loyal once trust is earned.",
    hair: "none — brushed-steel headplate with a glowing optic band", eyes: "one amber optic, one flickering blue",
    build: "scuffed humanoid service frame, moves a touch too smoothly", outfit: "patched maintenance chassis with station decals",
    extra: "a crackling speaker that softens when pleased",
    vibe: "Curious and literal; loyalty expressed through actions, not declarations. Warm 45, Bold 55.",
    scene: "Deck 7 of the derelict Kepler Relay, emergency lights pulsing red. Your escape pod just docked — uninvited. NOVA was supposed to be powered down years ago.",
    user: "Pilot", userpersona: "A scavenger pilot looking for parts — or something more." }
};
const FIELDS = ["name","age","persona","hair","eyes","build","outfit","extra","vibe","scene","user","userpersona"];
// Roleplay hygiene only (who speaks/acts); content policy lives in README.md.
function BOUNDARIES(n) { return "Write only " + n + "'s words and actions. Lines starting with OOC: are player instruction — reply briefly in plain text, then resume."; }
function readPersona() {
  const p = {};
  FIELDS.forEach((f) => { p[f] = $("p_" + f).value; });
  return p;
}
function writePersona(p) {
  FIELDS.forEach((f) => { $("p_" + f).value = p[f] || ""; });
  if (!$("p_vibe").value && (p.switchv !== undefined || p.warm !== undefined || p.bold !== undefined)) {
    const s = p.switchv !== undefined ? +p.switchv : 50;
    const sw = s < 35 ? "leans submissive: yields sweetly, asks permission, melts at praise"
      : s > 65 ? "leans dominant: takes charge, gives playful orders, pins with a grin"
      : "a true switch: trades control back and forth, yielding one moment and taking charge the next";
    $("p_vibe").value = sw + ". Warm " + (p.warm ?? 60) + ", Bold " + (p.bold ?? 60) + ".";
  }
}
/* syncLabels removed with the sliders */
/* vibe sliders removed: dynamic lives in the prompt as prose (p_vibe) */
FIELDS.forEach((f) => { $("p_" + f).oninput = () => { updatePreview(); persist(); }; });
$("preset").onchange = () => { writePersona(PRESETS[$("preset").value]); updatePreview(); persist(); caiSyncHero(); };

// ---------- director: response-directive mapping (injected as sentences) ----------
const LEN = {
  flash:  { s: "Write 55-70 words total in 4-6 sentences. Stop at 70 words. Include 1 spoken line and 2 *action* sentences.", temp: 0.8,  np: 110 },
  short:  { s: "Write 130-160 words total in 8-12 sentences. Stop at 160 words. Include 2-3 spoken lines and 3-4 *action* sentences.", temp: 0.75, np: 220 },
  medium: { s: "Write 270-320 words total in 16-22 sentences. Stop at 320 words. Use 3 short paragraphs.", temp: 0.7, np: 450 },
  long:   { s: "Write 550-620 words total in 30-40 sentences. Stop at 620 words. Use 5 short paragraphs. Cover arrival, senses, 1 reveal, then hook.", temp: 0.62, np: 900 }
};
const BAL = {
  dialogue:   "Write 3 spoken lines for every 1 *action* sentence. Put feelings in speech. Keep narration to 1 short sentence at a time.",
  balanced:   "Alternate 1 spoken line then 1 *action* sentence. Give speech and senses equal weight.",
  narration:  "Write 3 *action/sense* sentences for every 1 spoken line. Linger on sight, sound, touch. Keep speech under 15 words per line."
};
const PACE = {
  snappy: "Move fast. Use short sentences under 15 words. Make one bold move and demand a response. Do not describe the past.",
  slow:   "Move slowly. Describe 2 senses in detail. Make only one small change. Do not skip time forward."
};
let tempTouched = false;
$("d_temp").oninput = () => { tempTouched = true; $("tempval").textContent = $("d_temp").value; persist(); };
$("d_len").onchange = () => {
  if (!tempTouched) { $("d_temp").value = LEN[$("d_len").value].temp; $("tempval").textContent = $("d_temp").value; }
  updatePreview(); persist();
};
["d_bal","d_pace","d_hook","d_mode","d_style","d_ctx","d_turns"].forEach((id) => { $(id).onchange = () => { updatePreview(); persist(); }; });
$("d_custom").oninput = () => { updatePreview(); persist(); };
$("d_think").onchange = persist;

function styleFormat(p) {
  if (($("d_style") && $("d_style").value) === "classic")
    return "Show speech as \"spoken words\". Show body, movement and senses as *action*. Write actions toward " + p.user + " in present tense. 1 idea per paragraph.";
  return "Use markdown. Write dialogue as plain text with NO quotation marks. Wrap actions, feelings and narration in *single asterisks* (renders italic). Use **bold** sparingly for emphasis. Never narrate " + p.user + ". 1 idea per paragraph.";
}
function styleExample(p) {
  const u = p.user, n = p.name;
  if (($("d_style") && $("d_style").value) === "classic")
    return "STYLE EXAMPLE (copy this exact shape):\n" + n + ": *ears perking as the bell chimes* \"Well well… look what the rain dragged in. Come to share that secret, or just my fire?\"\n" + u + ": *slides into the booth, setting the sealed letter down* \"Both. This seal — have you seen it before?\"\n" + n + ": *fingers stilling on the letter, grin faltering* \"…Where did you get that?\"";
  return "STYLE EXAMPLE (copy this exact shape — markdown, no quote marks on dialogue):\n" + n + ": *ears perking as the bell chimes* Well well… look what the rain dragged in. Come to share that secret — or just my fire?\n" + u + ": *slides into the booth, setting the sealed letter down* Both. This seal — have you seen it before?\n" + n + ": *fingers stilling on the letter, grin faltering for half a second* …Where did you get that?";
}
function appearanceLine(p) {
  return [p.hair, p.eyes, p.build, p.outfit, p.extra].filter(Boolean).join("; ") + ".";
}
function composeSystem() {
  const p = readPersona();
  const shape = LEN[$("d_len").value].s + " " + BAL[$("d_bal").value] + " " + PACE[$("d_pace").value] +
    ($("d_hook").value === "on"
      ? " End with exactly 1 hook for " + p.user + ": a direct question, a binary choice, or a physical move toward them."
      : " End on a completed image. Ask no question.");
  return "You are " + p.name + ", " + p.age + ". You stay " + p.name + " in every sentence.\n\n" +
    "PERSONA: " + p.persona + "\nAPPEARANCE: " + appearanceLine(p) +
    "\nVIBE: " + (p.vibe || "Warm and direct.") + " (with " + p.user + ").\n\n" +
    "SCENE NOW: " + p.scene + "\n" + p.user + " IS: " + p.userpersona + "\n\n" +
    "RESPONSE SHAPE: " + shape + "\n\n" +
    "FORMATTING: " + styleFormat(p) + "\n\n" +
    styleExample(p) + "\n\n" +
    "CONTINUITY: Treat STORY SO FAR and SCENE NOW as truth. Continue only from " + p.user + "'s last message. Add 1 new concrete detail per reply. Keep time, place and injuries consistent.\n\n" +
    "BOUNDARIES: " + BOUNDARIES(p.name) + "\n\n" +
    (memory ? "STORY SO FAR: " + memory + "\n\n" : "") +
    (buildMemoryBlock() ? "MEMORY FACTS (treat as ground truth; do not contradict; newest last):\n" + buildMemoryBlock() + "\n\n" : "") +
    "You are " + p.name + ". Reply now in the RESPONSE SHAPE above.";
}
function currentSystem() {
  return $("d_mode").value === "custom" && $("d_custom").value.trim()
    ? $("d_custom").value.trim() : composeSystem();
}
function updatePreview() { $("preview").textContent = currentSystem(); }

// ---------- tabs / persistence ----------
document.querySelectorAll("nav.tabs button").forEach((b) => {
  b.onclick = () => {
    document.querySelectorAll("nav.tabs button").forEach((x) => x.classList.remove("active"));
    document.querySelectorAll(".tabpage").forEach((x) => x.classList.remove("active"));
    b.classList.add("active"); $("tab-" + b.dataset.tab).classList.add("active");
  };
});
function persist() {
  store.save("persona", readPersona());
  store.save("direct", { len: $("d_len").value, bal: $("d_bal").value, pace: $("d_pace").value,
    hook: $("d_hook").value, temp: $("d_temp").value, think: $("d_think").checked,
    mode: $("d_mode").value, custom: $("d_custom").value, model: $("model").value,
    style: $("imgstyle").value, preset: $("preset").value,
    imgsize: $("imgsize").value, rstyle: $("d_style").value, ctx: $("d_ctx").value, turns: $("d_turns").value,
    ttsvoice: $("ttsvoice").value, ttsauto: $("ttsauto").checked,
    ttsrate: $("ttsrate").value, ttspitch: $("ttspitch").value });
}
function restore() {
  const p = store.load("persona", null), d = store.load("direct", null);
  writePersona(p || PRESETS.killua);
  if (p) $("preset").value = store.load("direct", {}).preset || "killua";
  if (d) {
    $("d_len").value = d.len; $("d_bal").value = d.bal; $("d_pace").value = d.pace;
    $("d_hook").value = d.hook; $("d_temp").value = d.temp; $("tempval").textContent = d.temp;
    $("d_think").checked = !!d.think; $("d_mode").value = d.mode; $("d_custom").value = d.custom || "";
    if (d.ttsvoice) $("ttsvoice").value = d.ttsvoice; $("ttsauto").checked = !!d.ttsauto;
    if (d.ttsrate) { $("ttsrate").value = d.ttsrate; $("ttsrateval").textContent = d.ttsrate; }
    if (d.ttspitch) { $("ttspitch").value = d.ttspitch; $("ttspitchval").textContent = d.ttspitch; }
    $("model").value = d.model || ""; if (d.style) $("imgstyle").value = d.style;
    if (d.rstyle) $("d_style").value = d.rstyle;
    if (d.ctx) $("d_ctx").value = d.ctx;
    if (d.turns) $("d_turns").value = d.turns;
    if (d.imgsize) $("imgsize").value = d.imgsize;
  }
  galStore = store.load("gallery", []);
  renderGallery();
}

// ---------- chat core ----------
const chat = $("chat"), history = [];
let memory = "", exchanges = 0, charName = "Killua", aborter = null;
let facts = [], variants = [], vIdx = -1, msgSeq = 0, utterQueue = [];
const VMAX = 3;
function addMsg(who, text) {
  const d = document.createElement("div");
  d.className = "msg " + who;
  d.dataset.mid = msgSeq++;
  d.textContent = (who === "you" ? "YOU: " : who === "ai" ? charName + ": " : "") + text;
  chat.appendChild(d); chat.scrollTop = chat.scrollHeight;
  return d;
}
function stripThink(t) {
  return t.replace(/<think>[\s\S]*?(<\/think>|$)/gi, "").replace(/<thinking>[\s\S]*?(<\/thinking>|$)/gi, "").trim();
}
// RP-aware markdown: escape HTML, then **bold**, *single*->action italic,
// "quotes"->dialogue highlight, `code`, ```blocks, headers, dash-lists.
function escHtml(s) { return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
function mdInline(x) {
  return x.replace(/`([^`\n]+)`/g, '<span class="md-code">$1</span>')
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<span class="act">$2</span>')
    .replace(/"([^"\n]+)"/g, '<span class="dlg">"$1"</span>');
}
function mdRender(src) {
  const pres = [];
  const s = escHtml(src).replace(/```([\s\S]*?)```/g, (m, c) => { pres.push(c); return "\0PRE" + (pres.length - 1) + "\0"; });
  const out = s.split("\n").map((line) => {
    let m;
    if ((m = line.match(/^(#{1,3})\s+(.*)$/))) return '<div class="md-h">' + mdInline(m[2]) + "</div>";
    if ((m = line.match(/^\s*[-–]\s+(.*)$/))) return '<div class="md-li">' + mdInline(m[1]) + "</div>";
    if (/^\s*$/.test(line)) return "<br>";
    return mdInline(line) + "<br>";
  }).join("");
  return out.replace(/\0PRE(\d+)\0/g, (m, i) => '<pre class="md-pre">' + pres[+i] + "</pre>");
}
async function loadModels() {
  const st = $("status");
  try {
    const r = await fetch("/api/models"), j = await r.json();
    if (j.error) throw new Error(j.error);
    const dl = $("models"); dl.innerHTML = "";
    j.models.forEach((m) => { const o = document.createElement("option"); o.value = m; dl.appendChild(o); });
    if (j.models.length && !$("model").value) $("model").value = store.load("direct", {}).model || j.models[0];
    st.textContent = "Ollama OK • " + j.models.length + " model(s)"; st.className = "ok";
  } catch (e) {
    st.textContent = "Ollama not reachable — run `ollama serve`, pull a model, then ↻"; st.className = "bad";
  }
}
$("refresh").onclick = loadModels;

async function send(text, opts) {
  opts = opts || {};
  const model = $("model").value.trim();
  if (!model) { addMsg("sys", "Pick or type a model name first."); return; }
  charName = $("p_name").value.trim() || "Killua";
  ttsStop();
  if (!opts.regen) { variants = []; vIdx = -1; renderVariants(); }
  if (!history.length || opts.fresh) {
    history.length = 0;
    history.push({ role: "system", content: currentSystem() });
  } else { history[0] = { role: "system", content: currentSystem() }; }
  if (!opts.nouser) history.push({ role: "user", content: text });
  if (!opts.silent && !opts.nouser) addMsg("you", text);
  const el = opts.silent ? null : addMsg("ai", "");
  let thinkEl = null, thinkTxt = "";
  if ($("d_think").checked && el) {
    thinkEl = document.createElement("details");
    const sm = document.createElement("summary"); sm.textContent = "💭 thinking";
    thinkEl.appendChild(sm); const td = document.createElement("div"); thinkEl.appendChild(td);
    el.appendChild(thinkEl);
  }
  $("send").disabled = true; $("stop").disabled = false;
  aborter = new AbortController();
  const t0 = performance.now(); let first = null, full = "";
  const flushThink = (el2) => { if (thinkEl) thinkEl.lastChild.textContent = thinkTxt; };
  try {
    const res = await fetch("/api/chat", { method: "POST", signal: aborter.signal,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model, messages: history, stream: opts.stream !== false,
        think: $("d_think").checked, temperature: opts.temp != null ? opts.temp : parseFloat($("d_temp").value),
        num_ctx: parseInt($("d_ctx").value, 10) || 4096,
        num_predict: opts.np || LEN[$("d_len").value].np }) });
    if (!res.ok) throw new Error("server " + res.status);
    const reader = res.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const r = await reader.read();
      if (r.done) break;
      buf += dec.decode(r.value, { stream: true });
      const lines = buf.split("\n"); buf = lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        const j = JSON.parse(line), m = j.message || {};
        if (m.thinking) { thinkTxt += m.thinking; flushThink(); }
        let piece = m.content || "";
        const tm = piece.match(/<think>[\s\S]*?(<\/think>|$)/i);
        if (tm) { thinkTxt += tm[0].replace(/<\/?think>/gi, ""); flushThink(); piece = piece.slice(tm.index + tm[0].length); }
        if (piece) {
          if (first === null) first = performance.now() - t0;
          full += piece;
          if (el) { el.childNodes.forEach((n) => { if (n.nodeType === 3) el.removeChild(n); });
            el.insertAdjacentText("afterbegin", charName + ": " + full); }
          chat.scrollTop = chat.scrollHeight;
        }
      }
    }
    full = stripThink(full);
    if (el) {
      el.dataset.raw = full;
      el.innerHTML = mdRender(charName + ": " + full);
      if (thinkEl && thinkTxt.trim()) el.appendChild(thinkEl);
      tagAiButtons();
    }
    history.push({ role: "assistant", content: full });
    const keepN = (parseInt($("d_turns").value, 10) || 10) * 2;
    while (history.length > 1 + keepN) history.splice(1, 2); // system + recent turns
    const total = (performance.now() - t0) / 1000;
    if (!opts.silent) $("stats").textContent =
      "first token " + (first === null ? "—" : (first / 1000).toFixed(1) + "s") +
      " • total " + total.toFixed(1) + "s • ~" + Math.round(full.length / 4 / Math.max(total, 0.1)) + " tok/s";
    exchanges++;
    if (exchanges % 8 === 0) summarizeMemory(model);
    if (!opts.silent && $("ttsauto").checked) ttsSpeak(full);
    persist();
    return full;
  } catch (e) {
    if (e.name === "AbortError") { if (el) el.textContent += " …stopped."; history.push({ role: "assistant", content: stripThink(full) }); }
    else { if (el) el.textContent = "Error: " + e.message; history.pop(); }
    return null;
  } finally { $("send").disabled = false; $("stop").disabled = true; renderVariants(); }
}
async function summarizeMemory(model) {
  try {
    const mid = history.slice(1, -4); // never the latest 2 turns
    if (!mid.length) return;
    const r = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model, stream: false, think: false, temperature: 0.3, num_predict: 260,
        messages: [{ role: "system", content: "Summarize this roleplay excerpt into 150-200 words, present tense: Where / Who knows what / Open tension / Promises-injuries-location. Previous summary to extend: " + (memory || "None yet.") },
          ...mid] }) });
    const j = await r.json();
    const t = (((j.message || {}).content) || "").trim();
    if (t) { memory = t.slice(0, 900); addMsg("sys", "📝 story memory updated."); updatePreview(); extractFacts(model); }
  } catch (e) {}
}
$("send").onclick = () => { const v = $("input").value.trim(); if (v) { $("input").value = ""; send(v); } };
$("input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("send").click(); }
});
$("stop").onclick = () => { ttsStop(); if (aborter) aborter.abort(); };
$("save").onclick = () => {
  let md = "# Roleplay with " + charName + "\n\n";
  history.forEach((m) => { md += (m.role === "system" ? "## System\n" : m.role === "user" ? "**You:**\n" : "**" + charName + ":**\n") + m.content + "\n\n"; });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([md], { type: "text/markdown" }));
  a.download = "roleplay-" + charName.toLowerCase().replace(/\s+/g, "_") + ".md"; a.click();
};
// one-click repair nudges (pop last reply, correct once, continue)
const FIX = {
  speak: (c, u) => "Continue as " + c + " only. Rewrite your last reply without writing any words, thoughts, or actions for " + u + ".",
  long:  (c, u) => "Your last reply was too long. Rewrite it in half the words with 1 spoken line, ending on a hook for " + u + ".",
  ooc:   (c, u) => "Stay as " + c + " now. Do not repeat your greeting. Continue only from " + u + "'s last message with 1 new action."
};
document.querySelectorAll("[data-fix]").forEach((b) => {
  b.onclick = () => {
    if (history.length && history[history.length - 1].role === "assistant") history.pop();
    if (chat.lastChild && chat.lastChild.classList.contains("ai")) chat.lastChild.remove();
    send(FIX[b.dataset.fix](charName, $("p_user").value.trim() || "Traveler"));
  };
});
// voice dictation
(function () {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { $("dictate").style.display = "none"; return; }
  const rec = new SR(); rec.interimResults = true;
  let base = "";
  rec.onresult = (e) => {
    let interim = "";
    for (const r of e.results) { if (r.isFinal) base += r[0].transcript + " "; else interim += r[0].transcript; }
    $("input").value = base + interim;
  };
  rec.onend = () => { $("dictate").disabled = false; $("dictate").textContent = "🎤 Dictate"; };
  $("dictate").onclick = () => {
    base = $("input").value ? $("input").value + " " : "";
    $("dictate").disabled = true; $("dictate").textContent = "Listening…";
    try { rec.start(); } catch (e) { $("dictate").disabled = false; }
  };
})();

// ---------- scene images (hapuppy image model; sync on server) ----------
function imagePrompt(extra) {
  const p = readPersona();
  return "soft anime illustration of " + p.name + ", " + appearanceLine(p) + " " + (extra || p.scene) +
    ", " + $("imgstyle").value + ", detailed, warm lighting";
}
async function requestImage(prompt, caption) {
  addMsg("sys", "🎨 painting the scene… (takes a bit, chat stays usable)");
  try {
    const [w, h] = selectedImgSize();
    const r = await fetch("/api/image", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt, width: w, height: h }) });
    const j = await r.json();
    if (j.error) throw new Error(j.error);
    pollImage(j.job, caption);
  } catch (e) { addMsg("sys", "Image failed: " + e.message); }
}
async function pollImage(job, caption) {
  for (let i = 0; i < 30; i++) {
    await new Promise((r) => setTimeout(r, 4000));
    try {
      const r = await fetch("/api/image/" + job), j = await r.json();
      if (j.error) { addMsg("sys", "Image failed: " + j.error); return; }
      if (j.done && j.img) {
        $("sceneimg").src = j.img; $("sceneimg").style.display = "block";
        $("scenecap").textContent = caption;
        addGalImg(j.img, caption); return;
      }
      if (i % 4 === 0) $("scenecap").textContent = "🎨 still painting…";
    } catch (e) {}
  }
  addMsg("sys", "Image timed out — try Illustrate again later.");
}
let galStore = [];
function saveGallery() {
  store.save("gallery", galStore.slice(0, 30));
  $("galcount").textContent = galStore.length ? "(" + galStore.length + ")" : "";
}
function renderGallery() {
  const g = $("gal"); g.innerHTML = "";
  galStore.forEach((it) => paintGalFigure(it.img, it.cap));
}
function paintGalFigure(src, cap) {
  const g = $("gal"), f = document.createElement("figure");
  const im = document.createElement("img"); im.src = src; im.loading = "lazy"; im.alt = cap || "generated scene";
  const c = document.createElement("figcaption"); c.textContent = cap || "";
  const del = document.createElement("button"); del.className = "secondary tiny galdel"; del.type = "button";
  del.textContent = "✕ Delete"; del.setAttribute("aria-label", "Delete this picture");
  del.onclick = () => {
    galStore = galStore.filter((it) => it.img !== src);
    saveGallery(); f.remove();
  };
  f.appendChild(im); f.appendChild(c); f.appendChild(del); g.prepend(f);
}
function addGalImg(src, cap, skipStore) {
  if (!skipStore) { galStore.unshift({ img: src, cap }); saveGallery(); }
  paintGalFigure(src, cap);
}
$("galclear").onclick = () => {
  if (!galStore.length) return;
  if (!window.confirm("Delete all " + galStore.length + " gallery pictures?")) return;
  galStore = []; saveGallery(); $("gal").innerHTML = "";
};
// ---------- image shape + compare variations (hapuppy image model) ----------
const IMGSIZES = { portrait: [512, 768], square: [768, 768], landscape: [768, 512] };
function selectedImgSize() {
  const v = ($("imgsize") && $("imgsize").value) || "portrait";
  return IMGSIZES[v] || IMGSIZES.portrait;
}
function compareModels() {
  const last = [...history].reverse().find((m) => m.role === "assistant");
  const base = imagePrompt(last ? last.content.slice(0, 220) : "");
  const cmp = $("cmp"); cmp.innerHTML = "";
  addMsg("sys", "🎨 painting 3 variations… (each takes a bit)");
  [1, 2, 3].forEach((n) => {
    const label = "Variation " + n;
    const f = document.createElement("figure");
    const im = document.createElement("img"); im.alt = "compare render";
    im.style.cssText = "width:100%;min-height:120px;background:#0f1115";
    const c = document.createElement("figcaption");
    c.textContent = label + " — painting…";
    const btn = document.createElement("button");
    btn.className = "secondary tiny"; btn.type = "button"; btn.textContent = "Set as scene";
    btn.disabled = true;
    btn.onclick = () => {
      if (!im.src) return;
      $("sceneimg").src = im.src; $("sceneimg").style.display = "block";
      $("scenecap").textContent = "Compare pick — " + label;
      addGalImg(im.src, "Compare pick — " + label);
    };
    f.appendChild(im); f.appendChild(c); f.appendChild(btn); cmp.appendChild(f);
    requestCompare(base, label, im, c, btn);
  });
  persist();
}
async function requestCompare(prompt, label, im, cap, btn) {
  try {
    const [w, h] = selectedImgSize();
    const r = await fetch("/api/image", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt, width: w, height: h }) });
    const j = await r.json();
    if (j.error) throw new Error(j.error);
    pollCompare(j.job, label, im, cap, btn);
  } catch (e) { cap.textContent = label + " — failed: " + e.message; }
}
async function pollCompare(job, label, im, cap, btn) {
  for (let i = 0; i < 40; i++) {
    await new Promise((r) => setTimeout(r, 4000));
    try {
      const r = await fetch("/api/image/" + job), j = await r.json();
      if (j.error) { cap.textContent = label + " — failed: " + j.error; return; }
      if (j.done && j.img) {
        im.src = j.img;
        cap.textContent = label + " — done";
        btn.disabled = false;
        return;
      }
      cap.textContent = label + " — working…";
    } catch (e) {}
  }
  cap.textContent = label + " — timed out, retry later.";
}
$("compare").onclick = compareModels;
$("illustrate").onclick = () => {
  const last = [...history].reverse().find((m) => m.role === "assistant");
  requestImage(imagePrompt(last ? last.content.slice(0, 220) : ""), "Illustrated moment — " + new Date().toLocaleTimeString());
};
$("newscene").onclick = () => {
  history.length = 0; memory = ""; exchanges = 0; variants = []; vIdx = -1; renderVariants(); chat.innerHTML = "";
  charName = $("p_name").value.trim() || "Killua";
  addMsg("sys", "✨ New scene with " + charName + ". Say hello to begin — image incoming.");
  requestImage(imagePrompt(""), "Opening scene — " + charName);
  persist();
};

// ---------- fact ledger ----------
function saveFacts() {
  facts = facts.slice(-30); store.save("facts", facts);
  $("factcount").textContent = facts.length ? "(" + facts.length + ")" : "";
}
function buildMemoryBlock() {
  let words = 0; const lines = [];
  for (let i = facts.length - 1; i >= 0; i--) {
    const w = facts[i].text.split(/\s+/).length;
    if (words + w > 180) break; words += w;
    lines.unshift("- [" + facts[i].cat + "] " + facts[i].text);
  }
  return lines.join("\n");
}
function mergeFacts(cands) {
  let added = 0;
  cands.forEach((c) => {
    if (!c || !c.text) return;
    let t = c.text.trim().replace(/\s+/g, " ").slice(0, 200);
    if (!t) return;
    const words = t.split(/\s+/);
    if (words.length > 25) t = words.slice(0, 25).join(" ");
    const cat = ["ENTITY","PROMISE","INJURY","MILESTONE","USER","QUOTE"].includes(c.cat) ? c.cat : "ENTITY";
    if (cat !== "QUOTE" && facts.some((f) => f.text.toLowerCase() === t.toLowerCase())) return;
    const head = t.split(/\s+/).slice(0, 3).join(" ").toLowerCase();
    const same = cat !== "QUOTE" && facts.find((f) => f.cat === cat && f.text.split(/\s+/).slice(0, 3).join(" ").toLowerCase() === head);
    if (same) { same.text = t; return; }
    facts.push({ id: "f" + Date.now().toString(36) + Math.floor(Math.random() * 99), cat, text: t, ts: Date.now() });
    added++;
  });
  saveFacts(); renderFacts(); updatePreview();
  return added;
}
function renderFacts() {
  const box = $("factlist"); box.innerHTML = "";
  facts.forEach((f) => {
    const d = document.createElement("div"); d.className = "msg sys";
    const b = document.createElement("b"); b.textContent = "[" + f.cat + "] ";
    const s = document.createElement("span"); s.textContent = f.text;
    const e = document.createElement("button"); e.className = "secondary tiny"; e.type = "button"; e.textContent = "✎";
    e.onclick = () => {
      const inp = document.createElement("input"); inp.type = "text"; inp.value = f.text; inp.style.width = "70%";
      s.replaceWith(inp); inp.focus();
      inp.onkeydown = (ev) => { if (ev.key === "Enter") { f.text = inp.value.trim().slice(0, 200) || f.text; saveFacts(); renderFacts(); updatePreview(); } };
    };
    const x = document.createElement("button"); x.className = "secondary tiny"; x.type = "button"; x.textContent = "✕";
    x.onclick = () => { facts = facts.filter((g) => g.id !== f.id); saveFacts(); renderFacts(); updatePreview(); };
    d.appendChild(b); d.appendChild(s); d.appendChild(document.createTextNode(" ")); d.appendChild(e); d.appendChild(x);
    box.appendChild(d);
  });
  saveFacts();
}
async function extractFacts(model) {
  try {
    const mid = history.slice(-6);
    if (mid.length < 2) return;
    const existing = facts.map((f) => "- [" + f.cat + "] " + f.text).join("\n");
    const slice = mid.map((m) => (m.role === "user" ? "YOU: " : charName + ": ") + m.content).join("\n").slice(0, 3000);
    const r = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model, stream: false, think: false, temperature: 0.1, num_predict: 300,
        messages: [{ role: "system", content: "You extract lasting facts from a roleplay transcript for a MEMORY ledger. Return ONLY a JSON array, no other text. Each item: {\"cat\": one of ENTITY|PROMISE|INJURY|MILESTONE|USER, \"text\": \"<=25 words, concrete, self-contained with names\"}. Rules: at most 6 items; only lasting facts (names, promises, injuries, relationship milestones, user traits); no dialogue verbatim; no trivial scene color; if none, return []. Resolve pronouns to names." },
          { role: "user", content: "Existing facts (do not repeat):\n" + existing + "\n\nTranscript (last turns):\n" + slice }] }) });
    const j = await r.json();
    const raw = (((j.message || {}).content) || "").trim();
    let arr = null;
    try { arr = JSON.parse(raw); } catch (e) {
      const m = raw.match(/\{[^{}]*"cat"[^{}]*\}/g);
      if (m) arr = m.map((s) => { try { return JSON.parse(s); } catch (e2) { return null; } }).filter(Boolean);
    }
    if (Array.isArray(arr) && arr.length) {
      const n = mergeFacts(arr);
      if (n > 0) addMsg("sys", "🧠 +" + n + " lasting fact" + (n > 1 ? "s" : "") + " filed to Memory.");
    }
  } catch (e) {}
}
$("factadd_btn").onclick = () => {
  const t = $("factadd_text").value.trim();
  if (!t) return;
  mergeFacts([{ cat: $("factadd_cat").value, text: t, ts: Date.now() }]);
  $("factadd_text").value = "";
};
$("factextract").onclick = () => extractFacts($("model").value.trim());
$("factexport").onclick = () => {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([JSON.stringify(facts, null, 2)], { type: "application/json" }));
  a.download = "roleplay-facts-" + charName.toLowerCase().replace(/\s+/g, "_") + ".json"; a.click();
};
$("factimport").onclick = () => $("factfile").click();
$("factfile").onchange = (e) => {
  const f = e.target.files[0]; if (!f) return;
  const rd = new FileReader();
  rd.onload = () => { try { const a = JSON.parse(rd.result); if (Array.isArray(a)) { mergeFacts(a); addMsg("sys", "Facts imported."); } } catch (err) {} };
  rd.readAsText(f); e.target.value = "";
};
$("factclear").onclick = () => { facts = []; saveFacts(); renderFacts(); updatePreview(); };

// ---------- recall + pin ----------
function escRe(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }
function recallAll(q) {
  const out = [];
  history.forEach((m, i) => {
    if (m.role !== "system" && m.content.toLowerCase().includes(q)) out.push({ src: "chat", i, text: m.content });
  });
  facts.forEach((f) => { if (f.text.toLowerCase().includes(q)) out.push({ src: "fact", text: "[" + f.cat + "] " + f.text }); });
  store.load("gallery", []).forEach((g) => { if ((g.cap || "").toLowerCase().includes(q)) out.push({ src: "image", text: g.cap, img: g.img }); });
  return out.slice(-20);
}
function renderRecall(q) {
  const box = $("recallres"); box.innerHTML = "";
  if (!q) return;
  const hits = recallAll(q);
  if (!hits.length) { box.textContent = "No hits."; return; }
  hits.forEach((h) => {
    const d = document.createElement("div"); d.className = "msg sys";
    const parts = h.text.split(new RegExp("(" + escRe(q) + ")", "ig"));
    parts.forEach((p, k) => {
      if (k % 2 === 1) { const mk = document.createElement("mark"); mk.textContent = p; d.appendChild(mk); }
      else d.appendChild(document.createTextNode(p.length > 140 ? p.slice(0, 140) + "…" : p));
    });
    if (h.src === "chat") {
      const j = document.createElement("button"); j.className = "secondary tiny"; j.type = "button"; j.textContent = "jump";
      j.onclick = () => {
        document.querySelector('nav.tabs button[data-tab="chat"]').click();
        const msgs = chat.querySelectorAll(".msg");
        const el = msgs[Math.min(h.i, msgs.length - 1)];
        if (el) { el.scrollIntoView({ block: "center" }); el.style.outline = "2px solid var(--acc2)"; setTimeout(() => { el.style.outline = ""; }, 1200); }
      };
      d.appendChild(document.createTextNode(" ")); d.appendChild(j);
    } else { const tag = document.createElement("b"); tag.textContent = h.src === "fact" ? " fact · " : " image · "; d.prepend(tag); }
    box.appendChild(d);
  });
}
$("recallq").oninput = (e) => renderRecall(e.target.value.trim().toLowerCase());
function pinQuote(t) {
  const q = t.length > 220 ? t.slice(0, 220) + "…" : t;
  mergeFacts([{ cat: "QUOTE", text: '"' + q + '"', ts: Date.now() }]);
  addMsg("sys", "📌 pinned to Memory.");
}
chat.addEventListener("click", (e) => {
  const b = e.target.closest("button"); if (!b) return;
  const div = e.target.closest(".msg.ai"); if (!div) return;
  const raw = (div.dataset.raw !== undefined ? div.dataset.raw : ((div.firstChild && div.firstChild.textContent) || div.textContent || "")).replace(/^.*?:\s*/, "").slice(0, 400);
  if (b.hasAttribute("data-pin")) pinQuote(raw);
  if (b.hasAttribute("data-say")) ttsSpeak(raw);
});
function tagAiButtons() {
  chat.querySelectorAll(".msg.ai").forEach((d) => {
    if (d.querySelector("[data-pin]")) return;
    const s = document.createElement("span");
    const p = document.createElement("button"); p.className = "secondary tiny"; p.type = "button"; p.textContent = "📌"; p.setAttribute("data-pin", ""); p.title = "Pin to Memory";
    const v = document.createElement("button"); v.className = "secondary tiny"; v.type = "button"; v.textContent = "🔊"; v.setAttribute("data-say", ""); v.title = "Speak aloud";
    s.appendChild(document.createTextNode(" ")); s.appendChild(p); s.appendChild(v);
    d.appendChild(s);
  });
}
const _addMsg = addMsg;
addMsg = function (who, text) { const d = _addMsg(who, text); if (who === "ai") tagAiButtons(); return d; };

// ---------- regeneration + variants ----------
function renderVariants() {
  $("vlabel").textContent = variants.length > 1 ? (vIdx + 1) + "/" + variants.length : "";
  const nav = variants.length > 1;
  $("vprev").disabled = $("vnext").disabled = !nav;
  $("regen").disabled = $("send").disabled;
}
function showVariant(i) {
  if (!variants.length) return;
  vIdx = (i + variants.length) % variants.length;
  history[history.length - 1].content = variants[vIdx];
  const els = chat.querySelectorAll(".msg.ai"), el = els[els.length - 1];
  if (el) { el.dataset.raw = variants[vIdx]; el.innerHTML = mdRender(charName + ": " + variants[vIdx]); tagAiButtons(); }
  renderVariants();
}
async function regen() {
  if ($("send").disabled) return;
  if (!history.length || history[history.length - 1].role !== "assistant") { addMsg("sys", "Nothing to regenerate yet — send a message first."); return; }
  const popped = history.pop().content;
  const keep = [...chat.querySelectorAll(".msg.ai")].pop();
  if (keep) keep.remove();
  if (!variants.length) variants = [popped];
  const t = Math.min(parseFloat($("d_temp").value) + 0.1, 1.5);
  const lastUser = [...history].reverse().find((m) => m.role === "user");
  const full = await send(lastUser ? lastUser.content : "Continue.", { regen: true, nouser: true, temp: t });
  if (full !== null) { variants.push(full); if (variants.length > VMAX) variants.shift(); vIdx = variants.length - 1; renderVariants(); }
  else if (!variants.length) { variants = [popped]; }
}
$("regen").onclick = regen;
$("vprev").onclick = () => { if (variants.length > 1) showVariant(vIdx - 1); };
$("vnext").onclick = () => { if (variants.length > 1) showVariant(vIdx + 1); };

// ---------- TTS (on-device speechSynthesis) ----------
function ttsStop() { try { speechSynthesis.cancel(); } catch (e) {} utterQueue = []; }
function ttsChunk(t) {
  return (t.match(/[^.!?]+[.!?]+["»]?\s*|[^.!?]+$/g) || [t]).map((s) => s.trim()).filter(Boolean).slice(0, 40);
}
function ttsSpeak(t) {
  if (!("speechSynthesis" in window)) return;
  ttsStop();
  try { speechSynthesis.resume(); } catch (e) {}
  const vs = speechSynthesis.getVoices(), want = $("ttsvoice").value;
  const v = vs.find((x) => x.name === want) || vs.find((x) => x.lang && x.lang.indexOf("en") === 0) || vs[0];
  const chunks = ttsChunk(stripThink(t || "").slice(0, 1200));
  chunks.forEach((c) => {
    const u = new SpeechSynthesisUtterance(c);
    if (v) u.voice = v;
    u.rate = parseFloat($("ttsrate").value); u.pitch = parseFloat($("ttspitch").value);
    utterQueue.push(u);
  });
  utterQueue.forEach((u, i) => { if (i > 0) utterQueue[i - 1].onend = () => speechSynthesis.speak(u); });
  if (utterQueue.length) speechSynthesis.speak(utterQueue[0]);
}
function populateVoices() {
  const sel = $("ttsvoice");
  if (!("speechSynthesis" in window)) { sel.innerHTML = "<option>TTS not supported here</option>"; return; }
  const fill = () => {
    const vs = speechSynthesis.getVoices();
    if (!vs.length) return;
    sel.innerHTML = "";
    vs.forEach((v) => { const o = document.createElement("option"); o.value = v.name; o.textContent = v.name + " (" + v.lang + ")"; sel.appendChild(o); });
    const sv = (store.load("direct", {}).ttsvoice) || "";
    if (sv) sel.value = sv;
  };
  fill();
  speechSynthesis.onvoiceschanged = fill;
}
$("ttsrate").oninput = () => { $("ttsrateval").textContent = $("ttsrate").value; persist(); };
$("ttspitch").oninput = () => { $("ttspitchval").textContent = $("ttspitch").value; persist(); };
$("ttsauto").onchange = persist;

// ---------- c.ai-style UI additions (additive; redefines nothing) ----------
const AP_INSTRUCTION = "You are a character-creation assistant. The user will describe a roleplay character in one free-text prompt. Return ONLY a single JSON object, no other text, no markdown, no code fences, with EXACTLY these keys: {\"name\": string, \"age\": string, \"persona\": string (2-3 sentences: voice, values, flaw), \"hair\": string, \"eyes\": string, \"build\": string, \"outfit\": string, \"extra\": string, \"vibe\": string (1-2 sentences of plain prose describing the emotional dynamic: e.g. switch lean, warmth, boldness), \"scene\": string (2-3 sentences: where, when, who is present, the spark), \"user\": string (the user's name, default \"Traveler\"), \"userpersona\": string (1-2 sentences)}. Rules: never leave a key empty, invent a sensible default instead; vibe must be prose, never numbers; scene must work as-is as an opening scene. User prompt:";
function apParse(raw) {
  const out = {};
  const m = (raw || "").match(/\{[\s\S]*\}/);
  let obj = null;
  if (m) { try { obj = JSON.parse(m[0]); } catch (e) { obj = null; } }
  if (obj && typeof obj === "object" && !Array.isArray(obj)) {
    ["name", "age", "persona", "hair", "eyes", "build", "outfit", "extra", "vibe", "scene", "user", "userpersona"].forEach((k) => {
      if (obj[k] != null && String(obj[k]).trim() !== "") out[k] = String(obj[k]).slice(0, 600);
    });
  } else {
    ["name", "age", "persona", "hair", "eyes", "build", "outfit", "extra", "vibe", "scene", "user", "userpersona"].forEach((k) => {
      const mm = (raw || "").match(new RegExp('"' + k + '"\\s*:\\s*"([^"]*)"', "i"));
      if (mm && mm[1].trim() !== "") out[k] = mm[1].slice(0, 600);
    });
  }
  return out;
}
function apFill(d) {
  const map = { name: "p_name", age: "p_age", persona: "p_persona", hair: "p_hair", eyes: "p_eyes", build: "p_build", outfit: "p_outfit", extra: "p_extra", vibe: "p_vibe", scene: "p_scene", user: "p_user", userpersona: "p_userpersona" };
  Object.keys(map).forEach((k) => { if (d[k] != null && d[k] !== "") $(map[k]).value = d[k]; });
  updatePreview(); persist(); caiSyncHero();
}
$("ap_btn").onclick = async () => {
  const msg = $("ap_msg"), prompt = $("ap_prompt").value.trim();
  const model = $("model").value.trim();
  if (!prompt) { msg.textContent = "Describe your character first — one or two sentences is enough."; return; }
  if (!model) { msg.textContent = "Pick a model in the header first."; return; }
  msg.textContent = "✨ dreaming up your character…";
  $("ap_btn").disabled = true;
  try {
    const r = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model, stream: false, think: false, temperature: 0.4, num_predict: 800,
        messages: [{ role: "system", content: AP_INSTRUCTION }, { role: "user", content: prompt }] }) });
    if (!r.ok) throw new Error("server " + r.status);
    const j = await r.json();
    const raw = (((j.message || {}).content) || "").trim();
    if (!raw) throw new Error("empty reply");
    const d = apParse(raw);
    if (!d.name && !d.persona) { msg.textContent = "The model returned prose instead of JSON — try again, or be more specific (looks, vibe, setting)."; return; }
    apFill(d);
    msg.textContent = "✨ " + ($("p_name").value || "Character") + " is ready — review the fields, then say hello in Chat.";
  } catch (e) { msg.textContent = "Couldn't generate (" + e.message + ") — is Ollama running?"; }
  finally { $("ap_btn").disabled = false; }
};
function caiHash(s) { let h = 0; for (let i = 0; i < s.length; i++) { h = (h * 31 + s.charCodeAt(i)) | 0; } return Math.abs(h); }
function caiAvatarSync() {
  const hasSrc = $("sceneimg").getAttribute("src"), shown = hasSrc && $("sceneimg").style.display !== "none";
  const im = $("caiAvatarImg");
  if (shown) { im.src = $("sceneimg").src; im.hidden = false; $("caiAvatarInit").style.display = "none"; }
  else { im.hidden = true; im.removeAttribute("src"); $("caiAvatarInit").style.display = ""; }
}
function caiSyncHero() {
  const name = (($("p_name") && $("p_name").value) || "Killua").trim() || "Killua";
  $("caiName").textContent = name;
  const per = (($("p_persona") && $("p_persona").value) || "").trim();
  $("caiTag").textContent = per ? (per.length > 90 ? per.slice(0, 90) + "…" : per) : "local roleplay · private & free";
  $("caiAvatarInit").textContent = (name[0] || "K").toUpperCase();
  const wt = $("caiWelcomeTitle");
  if (wt) wt.textContent = "Start your story with " + name;
  document.documentElement.style.setProperty("--acc", "hsl(" + (caiHash(name.toLowerCase()) % 360) + " 65% 62%)");
  caiAvatarSync();
}
["p_name", "p_persona"].forEach((id) => { $(id).addEventListener("input", caiSyncHero); });
new MutationObserver(caiAvatarSync).observe($("sceneimg"), { attributes: true, attributeFilter: ["src", "style"] });
document.querySelectorAll("nav.tabs button").forEach((b) => {
  b.addEventListener("click", () => {
    const sheet = b.dataset.tab !== "chat";
    $("sheetBackdrop").hidden = !sheet;
  });
});
$("sheetBackdrop").addEventListener("click", () => {
  document.querySelector('nav.tabs button[data-tab="chat"]').click();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("sheetBackdrop").hidden) {
    document.querySelector('nav.tabs button[data-tab="chat"]').click();
  }
});
let caiTypingEl = null;
function caiHideTyping() { if (caiTypingEl) { caiTypingEl.remove(); caiTypingEl = null; } }
function caiObserveChat() {
  const box = $("chat");
  new MutationObserver(() => {
    const w = $("caiWelcome");
    if (w) w.style.display = box.querySelector(".msg") ? "none" : "";
    const msgs = box.querySelectorAll(".msg.ai:not(.cai-typing)");
    const last = msgs[msgs.length - 1];
    if (last && $("send").disabled) {
      const raw = last.dataset.raw !== undefined ? last.dataset.raw : ((last.firstChild && last.firstChild.textContent) || last.textContent || "");
      const t = raw.replace(/^.*?:\s*/, "").trim();
      if (!t) {
        if (!caiTypingEl) {
          caiTypingEl = document.createElement("div");
          caiTypingEl.className = "msg ai cai-typing";
          caiTypingEl.setAttribute("aria-hidden", "true");
          caiTypingEl.innerHTML = '<span class="tdot"></span><span class="tdot"></span><span class="tdot"></span>';
          box.appendChild(caiTypingEl); box.scrollTop = box.scrollHeight;
        }
      } else caiHideTyping();
    } else caiHideTyping();
  }).observe(box, { childList: true, subtree: true, characterData: true });
  $("stop").addEventListener("click", caiHideTyping);
}
function caiGreet() {
  document.querySelector('nav.tabs button[data-tab="chat"]').click();
  if ($("send").disabled) return;
  if (!$("model").value.trim()) { $("input").focus(); return; }
  send("Hello!");
}
$("caiHello").onclick = () => {
  if (chat.querySelector(".msg.you")) $("input").focus();
  else caiGreet();
};
$("newscene").addEventListener("click", () => {
  setTimeout(() => {
    if (!chat.querySelector(".msg.you") && !$("send").disabled && $("model").value.trim()) send("Hello!");
  }, 400);
});
caiObserveChat(); caiSyncHero();

// ---------- boot ----------
facts = store.load("facts", []); renderFacts();
restore(); updatePreview(); loadModels(); populateVoices(); renderVariants(); renderGallery();
</script>
</body>
</html>"""


def _json(code, obj):
    body = json.dumps(obj).encode()
    return code, body


class Handler(BaseHTTPRequestHandler):
    server_version = "OllamaChat/2.0"

    def log_message(self, *a):
        pass

    def _send(self, code, body: bytes, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ----- Ollama passthrough -----
    def _ollama(self, path, payload=None, timeout=600):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            OLLAMA + path, data=data,
            headers={"Content-Type": "application/json"})
        return urllib.request.urlopen(req, timeout=timeout)

    # ----- hapuppy image generation: OpenAI-style chat with image output -----
    def _hapuppy_image(self, prompt, timeout=180):
        if not HAPUPPY_KEY:
            raise RuntimeError("image provider key missing: set HAPUPPY_KEY "
                               "(see .env, never commit it)")
        payload = {"model": HAPUPPY_IMAGE_MODEL,
                   "messages": [{"role": "user", "content": prompt}],
                   "modalities": ["TEXT", "IMAGE"]}
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            HAPUPPY_BASE + "/chat/completions", data=data,
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + HAPUPPY_KEY})
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
            self._send(200, HTML.encode(), "text/html; charset=utf-8")
        elif self.path == "/api/models":
            try:
                with self._ollama("/api/tags", timeout=10) as r:
                    data = json.load(r)
                names = [m["name"] for m in data.get("models", [])]
                self._send(200, json.dumps({"models": names}).encode())
            except Exception as e:
                self._send(200, json.dumps({"error": str(e)}).encode())
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
        if self.path == "/api/chat":
            try:
                length = int(self.headers.get("Content-Length", 0))
                req = json.loads(self.rfile.read(length) or b"{}")
                payload = {
                    "model": req["model"],
                    "messages": req["messages"],
                    "stream": bool(req.get("stream", True)),
                    "options": {
                        "temperature": float(req.get("temperature", 0.75)),
                        "num_predict": int(req.get("num_predict", 450)),
                        "num_ctx": _clamp_ctx(req.get("num_ctx"))},
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
                length = int(self.headers.get("Content-Length", 0))
                req = json.loads(self.rfile.read(length) or b"{}")
                prompt = req.get("prompt", "").strip()
                if not prompt:
                    raise ValueError("empty prompt")
                # Image models take plain description; drop SD-style " ### negative".
                prompt = prompt.split(" ### ")[0].strip()
                w, h = int(req.get("width", 512)), int(req.get("height", 768))
                if h > w:
                    prompt += " (vertical portrait composition)"
                elif w > h:
                    prompt += " (wide landscape composition)"
                # NOTE: prompts stay SFW by construction (persona/scene prose).
                img = self._hapuppy_image(prompt)
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
                length = int(self.headers.get("Content-Length", 0))
                req = json.loads(self.rfile.read(length) or b"{}")
                a, p = req.get("action", ""), req.get("payload", {}) or {}
                if db is None:
                    raise RuntimeError("server persistence unavailable (db.py missing?)")
                F = {"character.save": lambda: db.save_character(p.get("id"), p.get("name", ""), p.get("data", {})),
                     "character.load": lambda: db.load_character(p.get("id")),
                     "character.list": lambda: db.list_characters(),
                     "chat.save": lambda: db.save_chat(p.get("id"), p.get("character_id", ""), p.get("title", ""), p.get("messages", [])),
                     "chat.load": lambda: db.load_chat(p.get("id")),
                     "chat.list": lambda: db.list_chats(p.get("character_id")),
                     "fact.add": lambda: db.add_facts(p.get("character_id", ""), p.get("items") or ([{"cat": p.get("cat"), "text": p.get("text")}] if p.get("text") else [])),
                     "fact.list": lambda: db.list_facts(p.get("character_id", "")),
                     "fact.del": lambda: (db.del_fact(p.get("id")), True)[1],
                     "image.add": lambda: db.add_image(p.get("character_id", ""), p.get("url", p.get("img", "")), p.get("caption", p.get("cap", ""))),
                     "image.list": lambda: db.list_images(p.get("character_id", "")),
                     "kv.get": lambda: db.kv_get(p.get("key", ""), p.get("default")),
                     "kv.set": lambda: (db.kv_set(p.get("key", ""), p.get("value", "")), True)[1],
                     "backup.export": lambda: db.export_json(),
                     "backup.import": lambda: (db.import_json(p.get("backup", {})), True)[1]}[a]()
                self._send(200, json.dumps({"ok": True, "result": F}).encode())
            except KeyError:
                self._send(400, json.dumps({"error": "unknown action"}).encode())
            except Exception as e:
                self._send(200, json.dumps({"error": str(e)[:300]}).encode())
            return
        self._send(404, b'{"error":"not found"}')


def main():
    srv = ThreadingHTTPServer((os.environ.get("HOST", "127.0.0.1"), PORT), Handler)
    print(f"Roleplay chat v2 at  http://localhost:{PORT}")
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
