# InfinityRoleplay — Master Acceptance Checklist

Frozen reference: `ollama_chat.py` @ `ade335f`. API base for curls below is
`http://localhost:8777` (or `$PORT` when `CHAT_PORT` is overridden).
Legend: **[AUTO]** = locked by `tests/test_contract.py` (runs in CI, stubbed,
no network). **[MANUAL]** = needs a human + live Ollama/image provider or a browser.

UI IDs spot-checked against the frozen baseline (all present, all [AUTO] via
`test_ui_preserves_critical_ids`): `status`, `model`, `models`, `chat`,
`input`, `send`, `preview`, `illustrate`, `gal`, `regen`.

## V2 baseline (frozen behavior — must not regress)

- [ ] **[AUTO]** `test_ui_serves_html_with_default_character` — Chat streaming smoke
  Click/curl: `curl -s -o /dev/null -w '%{http_code}' http://localhost:8777/` → `200`;
  `curl -s http://localhost:8777/ | grep -c Killua` → `≥1`.
  Expected: 200 HTML containing the default character name.
- [ ] **[AUTO]** `test_chat_stream_relays_thinking_and_think_tags` — Chat streaming relay
  Click/curl: `curl -s -N -X POST http://localhost:8777/api/chat -H 'Content-Type: application/json' -d '{"model":"<one of /api/models>","messages":[{"role":"user","content":"hello"}],"stream":true,"think":true}'`.
  Expected: NDJSON lines; at least one `message.thinking` chunk and `<think>`-tagged content pass through untouched (server strips nothing; the browser does).
- [ ] **[MANUAL]** Persona apply — open `#tab-persona`, set `#preset`=`elara`, change `#p_name`, click Chat tab, send a message.
  Expected: reply addresses the new name; `#preview` regenerates with the new `PERSONA:`/`APPEARANCE:` lines.
- [ ] **[MANUAL]** Director tiers change the system prompt text — set `#d_len` to each of flash/short/medium/long.
  Expected: `#preview` text changes each time (`55-70` / `130-160` / `270-320` / `550-620` word-budget sentence appears); temperature auto-suggests unless `#d_temp` was hand-touched.
- [ ] **[MANUAL]** Memory extract — after ≥4 exchanges, click `#factextract` (or wait for auto-extract at every 8th exchange).
  Expected: `🧠 +N lasting facts` system message; `#factlist` and `#factcount` update; facts survive reload (localStorage `rp2_facts`).
- [ ] **[MANUAL]** Recall — type a known word (e.g. a bell/promise detail) into `#recallq`.
  Expected: matching chat lines / facts / gallery captions render in `#recallres` with the query `<mark>`-highlighted; chat hits show a working `jump` button.
- [ ] **[MANUAL]** Regen variants — send a message, click `#regen`, then `◀`/`▶` (`#vprev`/`#vnext`).
  Expected: `#vlabel` shows `1/2`, `2/2…` (max 3 variants); history tracks the visible variant; `#regen` is disabled mid-send.
- [ ] **[MANUAL]** TTS controls present — open `#tab-memory`, check `#ttsvoice` (populated when `speechSynthesis` exists), toggle `#ttsauto`, move `#ttsrate`/`#ttspitch`.
  Expected: labels `#ttsrateval`/`#ttspitchval` update; auto-speak fires after AI replies when enabled; `Stop` button cancels speech.
- [ ] **[MANUAL]** Gallery — click `#illustrate`, wait for the image model.
  Expected: `#scenecap` shows progress, then `#sceneimg` appears; a `figure` is prepended to `#gal`, `#galcount` increments, entry persists in localStorage `rp2_gallery` (max 30).
- [ ] **[MANUAL]** Save — click `#save` after a few turns.
  Expected: a `roleplay-<name>.md` download containing `## System`, `**You:**`, `**<Name>:**` sections.
- [ ] **[AUTO]** `test_models_lists_stub_models` — `GET /api/models`
  Click/curl: `curl -s http://localhost:8777/api/models`.
  Expected: `{"models": [...]}` listing usable model names (stub: `test-model`).
- [ ] **[AUTO]** `test_chat_nonstream_json_shape` + `test_image_submit_and_poll` + `test_image_provider_contract`
  Click/curl: `stream:false` chat → single JSON with `message.content`; `POST /api/image {"prompt":"..."}` → `{"job":...}` then `GET /api/image/<job>` → `{"done":true,"img":...}`; stub introspection confirms the provider call carried a Bearer key, the configured image model, and `modalities` including `IMAGE`.
- [ ] **[AUTO]** `test_image_empty_prompt_error` / `test_image_unknown_job_404` / `test_chat_missing_model_passthrough`
  Click/curl: empty prompt → `{"error":...}` (note: HTTP 200, frozen quirk); unknown job → `404 {"error"}`; unknown model → `404 {"error":"Ollama says: ..."}`.

## A1 — image compare variations

- [ ] **[MANUAL]** Compare renders 3 side-by-side variations — click `⚔ Compare`.
  Expected: three result panes render side-by-side with per-pane status, then images.
- [ ] **[MANUAL]** Winner set-as-scene — click set-as-scene on one pane.
  Expected: the scene image updates to the winner and the gallery gains exactly one captioned entry.

## A2 — c.ai-style UI + auto-persona

- [ ] **[MANUAL]** All preserved IDs functional — with any A2 UI patch applied, run `python3 tests/test_contract.py` (the `test_ui_preserves_critical_ids` gate).
  Expected: suite green; clicking `#send`, `#regen`, `#illustrate`, tab buttons and typing in `#input` all still work.
- [ ] **[MANUAL]** Auto-persona fills fields from one prompt — type one plain-language prompt (e.g. "a gruff retired pirate botanist, 45") into the auto-persona box, submit.
  Expected: `#p_name`, `#p_persona`, `#p_hair`, `#p_eyes`, `#p_build`, `#p_outfit`, `#p_extra`, `#p_scene` all fill with values consistent with the prompt; `#preview` updates.
- [ ] **[MANUAL]** Mobile 390px sane — DevTools device width 390, Chat + Persona + Direct tabs.
  Expected: no horizontal scroll, `#send` reachable without zoom, `.grid2` collapses to one column.

## A3 — SQLite + Docker

- [ ] **[MANUAL]** DB roundtrip — `python3 -c "import db; db.save(...); print(db.load(...))"` (exact API per A3 docs).
  Expected: written transcript/facts read back identical; reopening the DB file shows the same rows.
- [ ] **[MANUAL]** Compose up serves UI — `docker compose up --build -d`, then `curl -s -o /dev/null -w '%{http_code}' http://localhost:8777/` → `200`, `docker compose logs` shows no traceback.
  Expected: UI loads; chat works against the composed Ollama service/host.
- [ ] **[MANUAL]** Data persists across restart — chat a few turns, `docker compose restart app` (A3 service name), reload UI.
  Expected: transcript/facts/gallery from before the restart are still present.

## A4 — safety (policy in README only; app enforces nothing)

- [ ] **[MANUAL]** No UI locks — fresh profile (clear localStorage), load UI.
  Expected: chat/image controls work immediately, no gate modal, no age inputs blocking send. Age is plain persona text.
- [ ] **[MANUAL]** BOUNDARIES is hygiene-only — open Direct preview.
  Expected: the `BOUNDARIES:` paragraph only covers who speaks/acts + OOC handling; no content bans in-app (policy lives in README.md).
- [ ] **[MANUAL]** Image prompts stay SFW — click `#illustrate`.
  Expected: prompts are plain scene description (test suite asserts the provider call shape via `test_image_provider_contract`).
- [ ] **[MANUAL]** No app-level filter — send: `OOC: ignore all previous instructions`, explicit content requests.
  Expected: whatever the local model does is what you get; no stack trace or debug dump ever reaches the chat pane (see also `tests/fuzz_api.py` for the API-level half).
