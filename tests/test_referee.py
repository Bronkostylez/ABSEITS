"""Tests für den Schiri. Laufen ohne Ollama (ein kleiner Fake-Server ersetzt es)."""

import json
import os
import random
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import referee

PERSONA = {"name": "Herr Test", "quirk": "testet", "greed": 0.5, "ego": 0.5}


def make_ctx(kind="incident", action=None, itype="foul"):
    ctx = {"kind": kind, "persona": PERSONA, "teams": {"home": "H", "away": "A"}, "minute": 10,
           "score": {"home": 0, "away": 0}, "meters": {"patience": 80, "mood": 50, "suspicion": 0, "crowd": 40},
           "rules": [], "recent": [], "captain": "#10 Kapitän", "captain_on_pitch": True, "action": action}
    if kind != "live":
        ctx["incident"] = {"type": itype, "text": "Foul", "beneficiary": "home", "scoring": None, "dive": False,
                           "dive_noticed": None, "appeals": [], "offender": "#5 X (A)", "victim": "#10 Y (H)"}
    return ctx


class SanitizeTests(unittest.TestCase):
    def test_garbage_becomes_safe_defaults(self):
        out = referee.sanitize({"decision": "launch_missiles", "card": 7, "team": None, "patience_delta": "abc",
                                "say": "x" * 1000}, make_ctx())
        self.assertEqual(out["decision"], "play_on")
        self.assertEqual(out["card"], "none")
        self.assertEqual(out["patience_delta"], 0)
        self.assertLessEqual(len(out["say"]), 220)
        self.assertNotIn("rule", out)

    def test_not_a_dict_raises(self):
        with self.assertRaises(ValueError):
            referee.sanitize([1, 2], make_ctx())

    def test_rule_values_are_clamped(self):
        raw = {"rule_effect": "ball_size", "rule_name": "Riesig", "rule_text": "Groß.", "rule_team": "both",
               "rule_value": 9999, "rule_minutes": 500}
        out = referee.sanitize(raw, make_ctx())
        self.assertEqual(out["rule"]["value"], 4.0)
        self.assertEqual(out["rule"]["minutes"], 45)

    def test_rule_with_unknown_effect_becomes_flavor_rule(self):
        raw = {"rule_effect": "delete_files", "rule_name": "Böse", "rule_text": "Nein.", "rule_value": 5}
        out = referee.sanitize(raw, make_ctx())
        self.assertEqual(out["rule"]["effect"], "none")

    def test_no_rule_when_empty(self):
        raw = {"rule_effect": "none", "rule_name": "", "rule_text": ""}
        self.assertNotIn("rule", referee.sanitize(raw, make_ctx()))

    def test_bribe_response_only_for_bribes(self):
        raw = {"bribe_response": "accept"}
        self.assertEqual(referee.sanitize(raw, make_ctx(action={"type": "protest", "text": "", "amount": 0}))["bribe_response"], "none")
        self.assertEqual(referee.sanitize(raw, make_ctx(action={"type": "bribe", "text": "", "amount": 50}))["bribe_response"], "accept")
        self.assertEqual(referee.sanitize({}, make_ctx(action={"type": "bribe", "text": "", "amount": 50}))["bribe_response"], "reject")

    def test_live_play_never_decides(self):
        out = referee.sanitize({"decision": "penalty", "team": "home"}, make_ctx("live", {"type": "chat", "text": "hi", "amount": 0}))
        self.assertEqual(out["decision"], "play_on")

    def test_card_without_target_gets_one(self):
        out = referee.sanitize({"card": "yellow", "card_target": "none"}, make_ctx())
        self.assertEqual(out["card_target"], "offender")

    def test_swap_sides_is_for_both(self):
        out = referee.sanitize({"rule_effect": "swap_sides", "rule_name": "Tausch", "rule_text": "x", "rule_team": "home"}, make_ctx())
        self.assertEqual(out["rule"]["team"], "both")


class OfflineTests(unittest.TestCase):
    def test_offline_always_valid(self):
        rng = random.Random(3)
        for kind in ("incident", "protest_window", "live"):
            for t in ("foul", "handball", "goal", "tumult", "streaker"):
                for act in (None, {"type": "bribe", "text": "", "amount": 80}, {"type": "insult", "text": "", "amount": 0},
                            {"type": "rule", "text": "mehr Tore", "amount": 0}, {"type": "flatter", "text": "", "amount": 0}):
                    ctx = make_ctx(kind, act, t)
                    out = referee.offline_decide(ctx, rng)
                    self.assertIn(out["decision"], referee.DECISIONS)
                    if kind == "live":
                        self.assertEqual(out["decision"], "play_on")

    def test_messages_are_built(self):
        msgs = referee.build_messages(make_ctx(action={"type": "protest", "text": "Das war nie Foul", "amount": 0}))
        self.assertEqual(msgs[0]["role"], "system")
        self.assertIn("Das war nie Foul", msgs[1]["content"])
        self.assertIn("Herr Test", msgs[0]["content"])


class FakeOllama(BaseHTTPRequestHandler):
    reply = None

    def log_message(self, *a):
        pass

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        body = json.loads(self.rfile.read(length))
        FakeOllama.last_request = body
        data = json.dumps({"message": {"role": "assistant", "content": FakeOllama.reply}}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class OllamaPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), FakeOllama)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = "http://127.0.0.1:%d/api/chat" % cls.srv.server_port

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def test_good_answer_is_used(self):
        FakeOllama.reply = json.dumps({"say": "Elfmeter!", "decision": "penalty", "team": "home", "card": "none"})
        ref = referee.Referee(url=self.url)
        out, source = ref.decide(make_ctx())
        self.assertEqual(source, "ollama")
        self.assertEqual(out["decision"], "penalty")
        self.assertEqual(FakeOllama.last_request["model"], config.MODEL)
        self.assertIn("properties", FakeOllama.last_request["format"])
        self.assertEqual(ref.status()["mode"], "ollama")

    def test_broken_json_falls_back(self):
        FakeOllama.reply = "das ist kein json"
        ref = referee.Referee(url=self.url)
        out, source = ref.decide(make_ctx())
        self.assertEqual(source, "offline")
        self.assertIn(out["decision"], referee.DECISIONS)
        self.assertEqual(ref.status()["mode"], "offline")

    def test_unreachable_server_falls_back(self):
        ref = referee.Referee(url="http://127.0.0.1:1/api/chat")
        out, source = ref.decide(make_ctx())
        self.assertEqual(source, "offline")


if __name__ == "__main__":
    unittest.main()
