#!/usr/bin/env python3
"""
InfinityRoleplay QA stub: ONE combined fake backend (stdlib only).

Emulates Ollama AND the hapuppy image endpoint on a single port so
tests/test_contract.py can point OLLAMA_HOST and HAPUPPY_BASE at the same
stub with zero live-network use.

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
  hapuppy image emulation (OpenAI-style chat with image output)
    POST /v1/chat/completions -> validates: Authorization Bearer present,
                             model non-empty, messages non-empty list,
                             modalities includes "IMAGE".
                             Violations => 400/401. OK => {"choices":
                             [{"message": {"images": [{"image_url":
                             {"url": <data URI>}}]}}]}
  Test introspection (stub-only, not part of the app contract)
    GET  /__stub/image-last    -> last validated image request actually
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
STUB_IMAGE_MODEL = "stub-image-model"
MAX_NUM_PREDICT = 100_000_000
LAST_IMAGE = {"calls": 0, "headers": {}, "payload": {}}


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
        elif self.path == "/__stub/image-last":
            self._send(200, LAST_IMAGE)
        else:
            self._send(404, {"error": "stub: not found: " + self.path})

    def do_POST(self):
        if self.path == "/api/chat":
            self._chat()
        elif self.path in ("/v1/chat/completions", "/chat/completions"):
            self._hapuppy_image()
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

    def _hapuppy_image(self):
        payload, err = self._read_json()
        if err or not isinstance(payload, dict):
            self._send(400, {"error": "stub: bad request: " + (err or "not an object")})
            return
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or len(auth) <= 7:
            self._send(401, {"error": "stub: missing/invalid Bearer auth"})
            return
        if not isinstance(payload.get("model"), str) or not payload["model"]:
            self._send(400, {"error": "stub: 'model' must be a non-empty string"})
            return
        if not isinstance(payload.get("messages"), list) or not payload["messages"]:
            self._send(400, {"error": "stub: 'messages' must be a non-empty list"})
            return
        if "IMAGE" not in (payload.get("modalities") or []):
            self._send(400, {"error": "stub: modalities must include IMAGE"})
            return
        LAST_IMAGE["calls"] += 1
        LAST_IMAGE["headers"] = {"authorization": "Bearer <redacted>",
                                 "model": payload.get("model")}
        LAST_IMAGE["payload"] = {
            "model": payload.get("model"),
            "modalities": payload.get("modalities"),
            "prompt_len": len(str((payload.get("messages") or [{}])[-1].get("content", ""))),
        }
        self._send(200, {"choices": [{"message": {"role": "assistant", "content": None,
                                                  "images": [{"type": "image_url",
                                                              "image_url": {"url": IMG}}]}}]})


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 18080
    srv = ThreadingHTTPServer(("127.0.0.1", port), Stub)
    print("QA stub on http://127.0.0.1:%d" % port, flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
