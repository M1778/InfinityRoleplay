#!/usr/bin/env python3
"""
Contract tests for the InfinityRoleplay frozen baseline (ollama_chat.py).

Stdlib unittest only -- no third-party deps. Spins up tests/stub_all.py plus
the REAL repo app as subprocesses, with OLLAMA_HOST / HORDE_BASE / CHAT_PORT
pointed at the stub so nothing touches the live network. Must finish in <60s.

Run (from repo root):
    python3 tests/test_contract.py
"""

import json
import os
import socket
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "ollama_chat.py")
STUB = os.path.join(ROOT, "tests", "stub_all.py")

STUB_MODEL = "test-model"

# 10 most critical UI element IDs, spot-checked against the frozen baseline
# (ollama_chat.py @ ade335f): status/model/models (header+model picker),
# chat/input/send (core loop), preview (prompt transparency), illustrate
# (image entry point), gal (gallery), regen (variants).
CRITICAL_IDS = ["status", "model", "models", "chat", "input", "send",
                "preview", "illustrate", "gal", "regen"]


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def api_get(port, path, timeout=10):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        body = e.read()
        e.close()
        return e.code, body


def api_post(port, path, payload=None, raw=None, timeout=15):
    data = raw if raw is not None else json.dumps(payload).encode()
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=data,
                                 method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        body = e.read()
        e.close()
        return e.code, body


def wait_for_root(port, timeout=15):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            status, _ = api_get(port, "/", timeout=2)
            if status == 200:
                return True
        except Exception as e:  # noqa: BLE001 - polling until deadline
            last = e
        time.sleep(0.05)
    raise AssertionError("app on port %d not up in %ss (last=%r)" % (port, timeout, last))


def start_stub(port):
    return subprocess.Popen([sys.executable, STUB, str(port)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


def start_app(stub_port, app_port):
    env = dict(os.environ)
    env["OLLAMA_HOST"] = "http://127.0.0.1:%d" % stub_port
    env["HORDE_BASE"] = "http://127.0.0.1:%d" % stub_port
    env["HORDE_KEY"] = "0000000000"
    env["CHAT_PORT"] = str(app_port)
    env["BROWSER"] = "true"  # keep webbrowser.open() a no-op in CI/headless
    return subprocess.Popen([sys.executable, APP], env=env, cwd=ROOT,
                            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


def stop(proc):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


class ContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stub_port = free_port()
        cls.app_port = free_port()
        cls.stub = start_stub(cls.stub_port)
        cls.app = start_app(cls.stub_port, cls.app_port)
        try:
            wait_for_root(cls.app_port, timeout=15)
        except Exception:
            stop(cls.app)
            stop(cls.stub)
            raise

    @classmethod
    def tearDownClass(cls):
        stop(cls.app)
        stop(cls.stub)

    def get(self, path):
        return api_get(self.app_port, path)

    def post(self, path, payload=None, raw=None):
        return api_post(self.app_port, path, payload, raw)

    def chat(self, **kw):
        body = {"model": STUB_MODEL,
                "messages": [{"role": "user", "content": "Hello from QA"}],
                "stream": True, "think": False,
                "temperature": 0.5, "num_predict": 64}
        body.update(kw)
        return self.post("/api/chat", body)

    def test_ui_serves_html_with_default_character(self):
        status, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn("Killua", body.decode("utf-8", "replace"))

    def test_ui_preserves_critical_ids(self):
        _, body = self.get("/")
        html = body.decode("utf-8", "replace")
        for eid in CRITICAL_IDS:
            with self.subTest(id=eid):
                self.assertIn('id="%s"' % eid, html)

    def test_models_lists_stub_models(self):
        status, body = self.get("/api/models")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertIn("models", data)
        self.assertIn(STUB_MODEL, data["models"])

    def test_chat_stream_relays_thinking_and_think_tags(self):
        status, body = self.chat(stream=True, think=True)
        self.assertEqual(status, 200)
        self.assertIn(b"thinking", body)
        self.assertIn(b"<think>", body)

    def test_chat_nonstream_json_shape(self):
        status, body = self.chat(stream=False)
        self.assertEqual(status, 200)
        data = json.loads(body)
        content = (data.get("message") or {}).get("content")
        self.assertIsInstance(content, str)
        self.assertTrue(content.strip())

    def test_image_submit_and_poll(self):
        status, body = self.post("/api/image", {"prompt": "a cozy tavern booth at dusk",
                                                "width": 512, "height": 768, "steps": 25})
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertIn("job", data)
        done = None
        last = body
        for _ in range(25):
            st2, body2 = self.get("/api/image/" + data["job"])
            self.assertEqual(st2, 200)
            last = body2
            d2 = json.loads(body2)
            if d2.get("done") and d2.get("img"):
                done = d2
                break
            time.sleep(0.2)
        self.assertIsNotNone(done, "image job never completed: %s" % last[:200])
        self.assertTrue(done["img"])

    def test_horde_payload_contract(self):
        self.post("/api/image", {"prompt": "contract probe",
                                 "width": 512, "height": 768, "steps": 25})
        status, body = api_get(self.stub_port, "/__stub/horde-last")
        self.assertEqual(status, 200)
        seen = json.loads(body)
        self.assertGreaterEqual(seen.get("calls", 0), 1)
        self.assertEqual(seen["headers"].get("apikey"), "0000000000")
        self.assertTrue(seen["headers"].get("client-agent"))
        self.assertIs(seen["payload"].get("nsfw"), False)
        self.assertIs(seen["payload"].get("censor_nsfw"), True)
        self.assertIs(seen["payload"].get("r2"), True)

    def test_image_empty_prompt_error(self):
        _, body = self.post("/api/image", {"prompt": "   "})
        # Frozen contract: validation failures answer 200 + {error}, not 4xx.
        self.assertIn("error", json.loads(body))

    def test_image_unknown_job_404(self):
        status, body = self.get("/api/image/no-such-job-qa")
        self.assertEqual(status, 404)
        self.assertIn("error", json.loads(body))

    def test_chat_missing_model_passthrough(self):
        status, body = self.chat(model="no-such-model-qa", stream=False)
        self.assertIn(status, (400, 404))
        self.assertIn("error", json.loads(body))


if __name__ == "__main__":
    unittest.main(verbosity=2)
