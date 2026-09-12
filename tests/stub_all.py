#!/usr/bin/env python3
"""
InfinityRoleplay QA stub: ONE combined fake backend (stdlib only).

Emulates Ollama AND AI Horde on a single port so tests/test_contract.py can
point OLLAMA_HOST and HORDE_BASE at the same stub with zero live-network use.

  Ollama emulation
    GET  /api/tags        -> {"models": [{"name": "test-model"}, ...]}
    POST /api/chat        -> stream:true  => NDJSON relay with a thinking
                             chunk AND think-tagged content chunk + done line
                             stream:false => single JSON
                             {message:{content}, done:true}
                           unknown model  => 404 (exercises the app's
                             upstream-error passthrough path)
                           malformed      => 400
                           absurd num_predict (>100M) => 400 (lets the fuzz
                             suite assert the app never 500s on forwardable
                             garbage; real Ollama limits may differ)
  Horde emulation
    POST /generate/async  -> validates the frozen contract:
                             nsfw is False, censor_nsfw is True, r2 is True,
                             `apikey` header present, `Client-Agent` present.
                             Violations => 400/401. OK => {"id": ...}
    GET  /generate/check/<id>  -> {"done": true, ...} immediately
    GET  /generate/status/<id> -> {"generations": [{"img": <data URI>}]}
  Test introspection (stub-only, not part of the app contract)
    GET  /__stub/horde-last    -> last validated async request actually
                                  received from the app (headers + payload)

Usage:
    python3 tests/stub_all.py [PORT]      # default 18080
"""

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

IMG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
       "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
KNOWN_MODELS = ["test-model", "test-model-2"]
HORDE_ID = "stub-horde-id-1"
MAX_NUM_PREDICT = 100_000_000
LAST_HORDE = {"calls": 0, "headers": {}, "payload": {}}


class Stub(BaseHTTPRequestHandler):
    server_version = "QAStub/1.0"

    def log_message(self, *a):
        pass

    def _send(self, code, obj, ctype="application/json"):
        body = obj if isinstance(obj, (bytes, bytearray)) else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            length = 0
        raw = self.rfile.read(length) if length > 0 else b""
        if not raw:
            return None, "empty body"
        try:
            return json.loads(raw), None
        except Exception:
            return None, "invalid json"

    def do_GET(self):
        if self.path == "/api/tags":
            self._send(200, {"models": [{"name": m, "model": m} for m in KNOWN_MODELS]})
        elif self.path.startswith("/generate/check/"):
            self._send(200, {"done": True, "faulted": False,
                             "queue_position": 0, "wait_time": 0})
        elif self.path.startswith("/generate/status/"):
            self._send(200, {"done": True, "generations": [
                {"img": IMG, "model": "stub", "worker_name": "qa-stub"}]})
        elif self.path == "/__stub/horde-last":
            self._send(200, LAST_HORDE)
        else:
            self._send(404, {"error": "stub: not found: " + self.path})

    def do_POST(self):
        if self.path == "/api/chat":
            self._chat()
        elif self.path == "/generate/async":
            self._horde_async()
        else:
            self._send(404, {"error": "stub: not found: " + self.path})

    def _chat(self):
        payload, err = self._read_json()
        if err or not isinstance(payload, dict):
            self._send(400, {"error": "stub: bad request: " + (err or "not an object")})
            return
        model = payload.get("model")
        messages = payload.get("messages")
        if not isinstance(model, str) or not model:
            self._send(400, {"error": "stub: 'model' must be a non-empty string"})
            return
        if model not in KNOWN_MODELS:
            self._send(404, {"error": "stub: model '%s' not found" % model})
            return
        if not isinstance(messages, list) or not messages:
            self._send(400, {"error": "stub: 'messages' must be a non-empty list"})
            return
        opts = payload.get("options", {}) or {}
        num_predict = opts.get("num_predict")
        if num_predict is not None and (
                not isinstance(num_predict, int) or isinstance(num_predict, bool)
                or not (1 <= num_predict <= MAX_NUM_PREDICT)):
            self._send(400, {"error": "stub: 'options.num_predict' out of range"})
            return
        last_user = ""
        for m in reversed(messages):
            if isinstance(m, dict) and m.get("role") == "user" \
                    and isinstance(m.get("content"), str):
                last_user = m["content"][:120]
                break
        if payload.get("stream", True):
            lines = [
                {"model": model, "message": {
                    "role": "assistant",
                    "thinking": "stub thought trace: weighing the tavern scene before replying"},
                 "done": False},
                {"model": model, "message": {
                    "role": "assistant",
                    "content": "<think>inner deliberation: stay warm, stay in character</think>"
                               "Hello, Traveler! *grins, the little bell chiming* "
                               "You made it through the rain"
                               + (" - noted: " + last_user if last_user else "") + "."},
                 "done": False},
                {"model": model, "done": True},
            ]
            body = ("\n".join(json.dumps(line) for line in lines) + "\n").encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self._send(200, {
                "model": model,
                "message": {"role": "assistant",
                            "content": "Stub reply (non-stream)"
                                       + (" to: " + last_user if last_user else "") + "."},
                "done": True,
                "done_reason": "stop",
            })

    def _horde_async(self):
        payload, err = self._read_json()
        if err or not isinstance(payload, dict):
            self._send(400, {"error": "stub: bad request: " + (err or "not an object")})
            return
        apikey = self.headers.get("apikey")
        agent = self.headers.get("Client-Agent")
        if not apikey:
            self._send(401, {"error": "stub: missing apikey header"})
            return
        if not agent:
            self._send(400, {"error": "stub: missing Client-Agent header"})
            return
        for key, want in (("nsfw", False), ("censor_nsfw", True), ("r2", True)):
            if payload.get(key) is not want:
                self._send(400, {"error": "stub: horde contract violation: %r must be %r"
                                          % (key, want)})
                return
        LAST_HORDE["calls"] += 1
        LAST_HORDE["headers"] = {"apikey": apikey, "client-agent": agent}
        LAST_HORDE["payload"] = {
            "nsfw": payload.get("nsfw"),
            "censor_nsfw": payload.get("censor_nsfw"),
            "r2": payload.get("r2"),
            "prompt_len": len(str(payload.get("prompt", ""))),
            "params": payload.get("params", {}),
        }
        self._send(202, {"id": HORDE_ID, "message": "stub accepted"})


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 18080
    srv = ThreadingHTTPServer(("127.0.0.1", port), Stub)
    print("QA stub on http://127.0.0.1:%d" % port, flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
