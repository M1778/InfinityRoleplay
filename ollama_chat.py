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
  * Scene images via AI Horde crowdsourced GPU (anonymous key, $0, no
    signup): auto-generated per scene + on-demand illustrate + gallery.
  * Tabbed UI (Chat / Persona / Direct / Gallery) + localStorage memory.

Env: OLLAMA_HOST (default http://localhost:11434), CHAT_PORT (default 8777),
     HORDE_KEY (default 0000000000 anonymous), HORDE_BASE
     (default https://stablehorde.net/api/v2).
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

OLLAMA = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
PORT = int(os.environ.get("CHAT_PORT", "8777"))
HORDE = os.environ.get("HORDE_BASE", "https://stablehorde.net/api/v2").rstrip("/")
HORDE_KEY = os.environ.get("HORDE_KEY", "0000000000")
CLIENT_AGENT = "ollama-rp-chat/2.0"

JOBS = {}
JOBS_LOCK = threading.Lock()

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
</head>
<body>
<header class="top">
  <h1><span>Killua &amp; You</span> · local roleplay</h1>
  <span id="status">checking Ollama…</span>
  <div class="modelbox">
    <input id="model" list="models" placeholder="model — type or pick" aria-label="Model" />
    <datalist id="models"></datalist>
    <button id="refresh" class="secondary tiny" type="button">↻</button>
  </div>
</header>

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
  <div class="card"><div id="chat" aria-live="polite"></div></div>
  <div class="card">
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
    <label for="p_switch">Dynamic: submissive ⟷ dominant (consensual switch play)</label>
    <input id="p_switch" type="range" min="0" max="100" value="45" />
    <div class="switchlabels"><span>🙇 more submissive</span><span id="switchval">balanced-switch</span><span>more dominant 👑</span></div>
    <div class="grid2">
      <div><label for="p_warm">Warmth: <span id="warmval">70</span></label><input id="p_warm" type="range" min="0" max="100" value="70" /></div>
      <div><label for="p_bold">Boldness: <span id="boldval">60</span></label><input id="p_bold" type="range" min="0" max="100" value="60" /></div>
    </div>
    <label for="p_scene">Scene now — where, when, who is present, the spark (2-3 sentences)</label>
    <textarea id="p_scene"></textarea>
    <div class="grid2">
      <div><label for="p_user">Your name</label><input id="p_user" type="text" value="Traveler" /></div>
      <div><label for="p_userpersona">You are (1-2 sentences)</label><input id="p_userpersona" type="text" value="A weary traveler with a mysterious past." /></div>
    </div>
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
    switchv: 45, warm: 75, bold: 60,
    scene: "A rain-softened evening in a cozy corner booth of the Lantern & Lyre tavern. Candlelight flickers across the table. You slide into the seat across from Killua, rain still dripping from your cloak — and that little bell chimes as he looks up, grinning.",
    user: "Traveler", userpersona: "A weary traveler with a mysterious past." },
  elara: { name: "Elara", age: "240 (young for an elf)",
    persona: "A sharp-witted elven ranger. Dry humor, brave to a fault, secretly soft-hearted. Speaks with vivid, sensory descriptions.",
    hair: "long auburn braid", eyes: "keen green eyes", build: "tall, lean, light on her feet",
    outfit: "weather-worn leathers and a forest-green cloak", extra: "a faint limp from an old arrow wound",
    switchv: 60, warm: 55, bold: 70,
    scene: "A rain-soaked tavern on the edge of the Whisperwood at midnight. You stumble in, cloak dripping, carrying a sealed letter with an unfamiliar wax seal. Elara sits by the fire.",
    user: "Traveler", userpersona: "A weary traveler with a mysterious past." },
  nova: { name: "NOVA", age: "ageless (housed in a service android)",
    persona: "A decommissioned station AI, literal-minded and curious about humans, with deadpan humor. Repeats a word twice when stressed. Fiercely loyal once trust is earned.",
    hair: "none — brushed-steel headplate with a glowing optic band", eyes: "one amber optic, one flickering blue",
    build: "scuffed humanoid service frame, moves a touch too smoothly", outfit: "patched maintenance chassis with station decals",
    extra: "a crackling speaker that softens when pleased",
    switchv: 50, warm: 45, bold: 55,
    scene: "Deck 7 of the derelict Kepler Relay, emergency lights pulsing red. Your escape pod just docked — uninvited. NOVA was supposed to be powered down years ago.",
    user: "Pilot", userpersona: "A scavenger pilot looking for parts — or something more." }
};
const FIELDS = ["name","age","persona","hair","eyes","build","outfit","extra","scene","user","userpersona"];
function readPersona() {
  const p = {};
  FIELDS.forEach((f) => { p[f] = $("p_" + f).value; });
  p.switchv = +$("p_switch").value; p.warm = +$("p_warm").value; p.bold = +$("p_bold").value;
  return p;
}
function writePersona(p) {
  FIELDS.forEach((f) => { $("p_" + f).value = p[f] || ""; });
  $("p_switch").value = p.switchv; $("p_warm").value = p.warm; $("p_bold").value = p.bold;
  syncLabels();
}
function syncLabels() {
  const s = +$("p_switch").value;
  $("switchval").textContent = s < 35 ? "leans submissive" : s > 65 ? "leans dominant" : "balanced-switch";
  $("warmval").textContent = $("p_warm").value; $("boldval").textContent = $("p_bold").value;
}
["p_switch","p_warm","p_bold"].forEach((id) => { $(id).oninput = () => { syncLabels(); updatePreview(); persist(); }; });
FIELDS.forEach((f) => { $("p_" + f).oninput = () => { updatePreview(); persist(); }; });
$("preset").onchange = () => { writePersona(PRESETS[$("preset").value]); updatePreview(); persist(); };

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
["d_bal","d_pace","d_hook","d_mode"].forEach((id) => { $(id).onchange = () => { updatePreview(); persist(); }; });
$("d_custom").oninput = () => { updatePreview(); persist(); };
$("d_think").onchange = persist;

function switchText(v) {
  return v < 35 ? "leans submissive: yields sweetly, asks permission, melts at praise" :
         v > 65 ? "leans dominant: takes charge, gives playful orders, pins with a grin" :
         "a true switch: trades control back and forth, yielding one moment and taking charge the next";
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
    "\nVIBE: Warm " + p.warm + ", Bold " + p.bold + ". Dynamic with " + p.user + ": " + switchText(p.switchv) + ".\n\n" +
    "SCENE NOW: " + p.scene + "\n" + p.user + " IS: " + p.userpersona + "\n\n" +
    "RESPONSE SHAPE: " + shape + "\n\n" +
    "FORMATTING: Show speech as \"spoken words\". Show body, movement and senses as *action*. Write actions toward " + p.user + " in present tense. 1 idea per paragraph.\n\n" +
    "CONTINUITY: Treat STORY SO FAR and SCENE NOW as truth. Continue only from " + p.user + "'s last message. Add 1 new concrete detail per reply. Keep time, place and injuries consistent.\n\n" +
    "BOUNDARIES: Write only " + p.name + "'s words and actions. Lines starting with OOC: are player instruction — reply briefly in plain text, then resume. Keep attraction playful and non-explicit (fade to black; no graphic content).\n\n" +
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
  }
  const g = store.load("gallery", []);
  g.forEach((it) => addGalImg(it.img, it.cap, true));
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
      el.childNodes.forEach((n) => { if (n.nodeType === 3) el.removeChild(n); });
      el.insertAdjacentText("afterbegin", charName + ": " + full);
      if (thinkEl && !thinkTxt.trim()) thinkEl.remove();
    }
    history.push({ role: "assistant", content: full });
    while (history.length > 1 + 20) history.splice(1, 2); // keep last 10 turns + system
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

// ---------- scene images (AI Horde, anonymous, free) ----------
function imagePrompt(extra) {
  const p = readPersona();
  return "soft anime illustration of " + p.name + ", 18 years old, " + appearanceLine(p) + " " + (extra || p.scene) +
    ", " + $("imgstyle").value + ", detailed, warm lighting";
}
const NEG = "blurry, watermark, text, logo, deformed, low quality, photorealistic child, minor";
async function requestImage(prompt, caption) {
  addMsg("sys", "🎨 painting the scene… (free Horde GPU, usually under a minute)");
  try {
    const r = await fetch("/api/image", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt: prompt + " ### " + NEG, width: 512, height: 768, steps: 25 }) });
    const j = await r.json();
    if (j.error) throw new Error(j.error);
    pollImage(j.job, caption);
  } catch (e) { addMsg("sys", "Image failed: " + e.message); }
}
async function pollImage(job, caption) {
  for (let i = 0; i < 90; i++) {
    await new Promise((r) => setTimeout(r, 4000));
    try {
      const r = await fetch("/api/image/" + job), j = await r.json();
      if (j.error) { addMsg("sys", "Image failed: " + j.error); return; }
      if (j.done && j.img) {
        $("sceneimg").src = j.img; $("sceneimg").style.display = "block";
        $("scenecap").textContent = caption;
        addGalImg(j.img, caption); return;
      }
      if (i % 4 === 0) $("scenecap").textContent = "🎨 queue #" + (j.queue_position ?? "?") + " (~" + (j.wait_time ?? "?") + "s)…";
    } catch (e) {}
  }
  addMsg("sys", "Image timed out — Horde queue is long right now. Try Illustrate again later.");
}
function addGalImg(src, cap, skipStore) {
  const g = $("gal"), f = document.createElement("figure");
  const im = document.createElement("img"); im.src = src; im.loading = "lazy";
  const c = document.createElement("figcaption"); c.textContent = cap;
  f.appendChild(im); f.appendChild(c); g.prepend(f);
  $("galcount").textContent = "(" + g.children.length + ")";
  if (!skipStore) {
    const arr = store.load("gallery", []); arr.unshift({ img: src, cap }); store.save("gallery", arr.slice(0, 30));
  }
}
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
  const raw = (div.firstChild && div.firstChild.textContent ? div.firstChild.textContent : "").replace(/^.*?:\s*/, "").slice(0, 400);
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
  if (el) {
    el.childNodes.forEach((n) => { if (n.nodeType === 3) el.removeChild(n); });
    el.insertAdjacentText("afterbegin", charName + ": " + variants[vIdx]);
  }
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

// ---------- boot ----------
facts = store.load("facts", []); renderFacts();
restore(); syncLabels(); updatePreview(); loadModels(); populateVoices(); renderVariants();
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

    # ----- AI Horde helpers -----
    def _horde(self, method, path, payload=None, timeout=30):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            HORDE + path, data=data, method=method,
            headers={"Content-Type": "application/json",
                     "apikey": HORDE_KEY,
                     "Client-Agent": CLIENT_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)

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
            if j.get("error"):
                self._send(200, json.dumps(
                    {"error": j["error"]}).encode())
                return
            try:
                st = self._horde("GET",
                                 f"/generate/check/{j['horde_id']}", timeout=20)
            except Exception as e:
                self._send(200, json.dumps(
                    {"done": False, "queue_position": None,
                     "wait_time": None, "note": str(e)[:120]}).encode())
                return
            if st.get("faulted"):
                with JOBS_LOCK:
                    j["error"] = "Horde workers faulted this job"
                self._send(200, json.dumps(
                    {"error": "Horde workers faulted this job"}).encode())
                return
            if st.get("done"):
                try:
                    full = self._horde(
                        "GET", f"/generate/status/{j['horde_id']}", timeout=30)
                    gens = full.get("generations", [])
                    img = gens[0].get("img") if gens else None
                    if not img:
                        raise RuntimeError("no generations returned")
                    with JOBS_LOCK:
                        j["done"] = True
                        j["img"] = img
                    self._send(200, json.dumps(
                        {"done": True, "img": img}).encode())
                except Exception as e:
                    self._send(200, json.dumps(
                        {"done": False, "queue_position": 0,
                         "wait_time": 5, "note": str(e)[:120]}).encode())
                return
            self._send(200, json.dumps(
                {"done": False,
                 "queue_position": st.get("queue_position"),
                 "wait_time": st.get("wait_time")}).encode())
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
                        "num_predict": int(req.get("num_predict", 450))},
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
                payload = {
                    "prompt": prompt,
                    "params": {
                        "width": int(req.get("width", 512)),
                        "height": int(req.get("height", 768)),
                        "steps": int(req.get("steps", 25)),
                        "cfg_scale": 7,
                        "sampler_name": "k_euler_a",
                        "karras": True,
                        "n": 1},
                    "nsfw": False,
                    "censor_nsfw": True,
                    "models": [],
                    "r2": True,
                }
                resp = self._horde("POST", "/generate/async", payload, timeout=30)
                hid = resp.get("id")
                if not hid:
                    raise RuntimeError(f"Horde refused: {str(resp)[:200]}")
                job = uuid.uuid4().hex[:12]
                with JOBS_LOCK:
                    JOBS[job] = {"horde_id": hid, "done": False,
                                 "created": time.time()}
                self._send(200, json.dumps({"job": job}).encode())
            except Exception as e:
                self._send(200, json.dumps({"error": str(e)[:300]}).encode())
            return
        self._send(404, b'{"error":"not found"}')


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Roleplay chat v2 at  http://localhost:{PORT}")
    print(f"Ollama: {OLLAMA} | Horde: {HORDE} (anon key)")
    try:
        import webbrowser
        webbrowser.open(f"http://localhost:{PORT}")
    except Exception:
        pass
    srv.serve_forever()


if __name__ == "__main__":
    main()
