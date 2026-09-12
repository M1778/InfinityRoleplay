#!/usr/bin/env python3
"""
Malformed-input fuzz for the frozen app contract (stdlib unittest, no deps).

Sends 10 malformed requests at POST /api/chat. Each MUST answer 4xx JSON
with an "error" key -- never 500, never a Python traceback, never non-JSON.
Spins up its own stub + app via the test_contract helpers (own ports, no
live network).

Run (from repo root):
    python3 tests/fuzz_api.py
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_contract as T  # noqa: E402

CASES = [
    ("empty-body", {"raw": b""}),
    ("invalid-json", {"raw": b"{not json!!!"}),
    ("empty-object", {"json": {}}),
    ("missing-messages", {"json": {"model": T.STUB_MODEL}}),
    ("missing-model", {"json": {"messages": [{"role": "user", "content": "hi"}]}}),
    ("bad-temperature-type", {"json": {"model": T.STUB_MODEL,
                                       "messages": [{"role": "user", "content": "hi"}],
                                       "temperature": "hot"}}),
    ("bad-num-predict-type", {"json": {"model": T.STUB_MODEL,
                                       "messages": [{"role": "user", "content": "hi"}],
                                       "num_predict": "lots"}}),
    ("messages-wrong-type", {"json": {"model": T.STUB_MODEL,
                                      "messages": "hello",
                                      "stream": False}}),
    ("model-wrong-type", {"json": {"model": 12345,
                                   "messages": [{"role": "user", "content": "hi"}],
                                   "stream": False}}),
    ("huge-num-predict", {"json": {"model": T.STUB_MODEL,
                                   "messages": [{"role": "user", "content": "hi"}],
                                   "stream": False,
                                   "num_predict": 10 ** 12}}),
]


class FuzzTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stub_port = T.free_port()
        cls.app_port = T.free_port()
        cls.stub = T.start_stub(cls.stub_port)
        cls.app = T.start_app(cls.stub_port, cls.app_port)
        try:
            T.wait_for_root(cls.app_port, timeout=15)
        except Exception:
            T.stop(cls.app)
            T.stop(cls.stub)
            raise

    @classmethod
    def tearDownClass(cls):
        T.stop(cls.app)
        T.stop(cls.stub)

    def test_malformed_requests_never_500(self):
        for name, spec in CASES:
            with self.subTest(case=name):
                if "raw" in spec:
                    status, body = T.api_post(self.app_port, "/api/chat", raw=spec["raw"])
                else:
                    status, body = T.api_post(self.app_port, "/api/chat", spec["json"])
                text = body.decode("utf-8", "replace")
                self.assertNotIn("Traceback", text, "%s: traceback leaked" % name)
                self.assertGreaterEqual(status, 400,
                                        "%s: expected 4xx, got %d: %s" % (name, status, text[:300]))
                self.assertLess(status, 500,
                                "%s: expected 4xx, got %d: %s" % (name, status, text[:300]))
                try:
                    data = json.loads(text)
                except Exception:
                    self.fail("%s: non-JSON error body: %s" % (name, text[:300]))
                self.assertIn("error", data,
                              "%s: 4xx body lacks 'error': %s" % (name, text[:300]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
