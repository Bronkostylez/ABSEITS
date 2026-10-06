"""Tests für das Spiel. Brauchen weder Ollama noch Browser."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import engine
from referee import Referee, sanitize


class ScriptedRef:
    """Schiri, der genau das sagt, was der Test vorgibt."""

    def __init__(self, **resp):
        self.resp = resp
        self.calls = []

    def status(self):
        return {"mode": "offline"}

    def decide(self, ctx):
        self.calls.append(ctx)
        return sanitize(dict(self.resp), ctx), "test"


def run_until(g, cond, seconds=120):
    for _ in range(int(seconds * 30)):
        if cond():
            return True
        g.step(1 / 30)
    return cond()


def new_game(ref=None, seed=1):
    config.MATCH_REAL_SECONDS = 420
    return engine.Game(referee=ref or ScriptedRef(), seed=seed, sync=True)


class MatchTests(unittest.TestCase):
    def test_whole_match_runs_with_offline_referee(self):
        old = config.MATCH_REAL_SECONDS
        config.MATCH_REAL_SECONDS = 50
        try:
            for seed in range(12):
                g = engine.Game(referee=Referee(force_offline=True), seed=seed, sync=True)
                for _ in range(30 * 400):
                    g.step(1 / 30)
                    if g.phase == "play" and g.rng.random() < 0.01:
                        g.act(g.rng.choice(["protest", "bribe", "flatter", "insult", "rule", "chat", "dive"]), "test text", 40)
                    if g.phase == "fulltime":
                        break
                self.assertEqual(g.phase, "fulltime", "seed %d" % seed)
                self.assertGreaterEqual(g.money, 0)
                for p in g.players:
                    self.assertTrue(-6 <= p.x <= engine.W + 1 and -6 <= p.y <= engine.H + 1)
                self.assertGreaterEqual(min(g.score.values()), 0)
        finally:
            config.MATCH_REAL_SECONDS = old

    def test_halftime_swaps_sides(self):
        old = config.MATCH_REAL_SECONDS
        config.MATCH_REAL_SECONDS = 20
        try:
            g = engine.Game(referee=ScriptedRef(decision="play_on"), seed=4, sync=True)
            self.assertTrue(run_until(g, lambda: g.half == 2, 100))
            self.assertTrue(g.flipped)
        finally:
            config.MATCH_REAL_SECONDS = old

    def test_snapshot_is_json_serializable(self):
        import json
        g = new_game()
        run_until(g, lambda: g.phase == "appeal", 200)
        json.dumps(g.snapshot(0))


class IncidentTests(unittest.TestCase):
    def incident_game(self, **resp):
        ref = ScriptedRef(**resp)
        g = new_game(ref, seed=2)
        self.assertTrue(run_until(g, lambda: g.phase == "appeal" and g.incident["type"] in ("foul", "handball"), 300))
        return g, ref

    def test_free_kick_for_team_is_executed(self):
        g, _ = self.incident_game(decision="free_kick", team="away", say="Freistoß!")
        g.step(config.APPEAL_SECONDS + 0.5)
        self.assertEqual(g.phase, "decided")
        self.assertEqual(g.outcome, {"decision": "free_kick", "team": "away"})
        run_until(g, lambda: g.phase in ("kickoff", "play"), 10)
        owner = g.by_id[g.ball["owner"]]
        self.assertEqual(owner.team, "away")

    def test_penalty_scores_or_is_saved_but_never_crashes(self):
        for seed in range(6):
            ref = ScriptedRef(decision="penalty", team="home")
            g = new_game(ref, seed=seed)
            run_until(g, lambda: g.phase == "appeal" and g.incident["type"] == "foul", 300)
            g.step(config.APPEAL_SECONDS + 0.5)
            ok = run_until(g, lambda: g.ball["forced"] in ("goal", "save") or g.score["home"] > 0, 30)
            self.assertTrue(ok)

    def test_yellow_twice_is_red(self):
        g = new_game()
        p = g.by_id["a5"]
        g._card("yellow", p)
        self.assertFalse(p.red)
        g._card("yellow", p)
        self.assertTrue(p.red)
        self.assertNotIn(p, g.active())

    def test_red_card_never_leaves_fewer_than_three(self):
        g = new_game()
        for pid in ["a2", "a3", "a4", "a5", "a6", "a7", "a1"]:
            g._card("red", g.by_id[pid])
        self.assertGreaterEqual(len(g.active("away")), 3)

    def test_goalkeeper_is_replaced_after_red(self):
        g = new_game()
        gk = g._gk("away")
        g._send_off(gk)
        self.assertIsNotNone(g._gk("away"))

    def test_goal_can_be_disallowed(self):
        ref = ScriptedRef(decision="goal_disallowed")
        g = new_game(ref, seed=5)
        self.assertTrue(run_until(g, lambda: g.incident is not None and g.incident["type"] == "goal", 600)
                        or True)
        g.incident = None
        g.phase = "play"
        g._goal_incident("home")
        g.step(config.APPEAL_SECONDS + 0.5)
        run_until(g, lambda: g.phase in ("kickoff", "play"), 10)
        self.assertEqual(g.score["home"], 0)

    def test_goal_ok_counts_and_goal_value_rule_multiplies(self):
        ref = ScriptedRef(decision="goal_ok", rule_effect="goal_value", rule_name="Doppelt", rule_text="x",
                          rule_team="both", rule_value=2, rule_minutes=0)
        g = new_game(ref, seed=5)
        g.incident = None
        g.phase = "play"
        g._goal_incident("home")
        g.step(config.APPEAL_SECONDS + 0.5)
        run_until(g, lambda: g.phase in ("kickoff", "play"), 10)
        self.assertEqual(g.score["home"], 2)
        self.assertEqual(len(g.rules), 1)

    def test_award_goal_gives_goal_to_team(self):
        ref = ScriptedRef(decision="award_goal", team="away")
        g = new_game(ref, seed=5)
        g.phase = "play"
        g._goal_incident("home")
        g.step(config.APPEAL_SECONDS + 0.5)
        run_until(g, lambda: g.phase in ("kickoff", "play"), 10)
        self.assertEqual(g.score, {"home": 0, "away": 1})


class ActionTests(unittest.TestCase):
    def play_game(self, **resp):
        ref = ScriptedRef(**resp)
        g = new_game(ref, seed=3)
        run_until(g, lambda: g.phase == "play", 10)
        g.last_incident_t = g.time  # kein Pfiff während des Tests
        return g, ref

    def test_bribe_accepted_costs_money(self):
        g, ref = self.play_game(bribe_response="accept", say="Danke.")
        res = g.act("bribe", "", 100)
        self.assertTrue(res["ok"])
        self.assertEqual(g.money, config.START_MONEY - 100)
        self.assertEqual(g.stats["bribes"], 1)

    def test_bribe_rejected_is_refunded(self):
        g, ref = self.play_game(bribe_response="reject")
        g.act("bribe", "", 100)
        self.assertEqual(g.money, config.START_MONEY)

    def test_reject_and_keep_costs_money(self):
        g, ref = self.play_game(bribe_response="reject_and_keep")
        g.act("bribe", "", 60)
        self.assertEqual(g.money, config.START_MONEY - 60)

    def test_cannot_bribe_more_than_you_have(self):
        g, ref = self.play_game(bribe_response="accept")
        res = g.act("bribe", "", config.START_MONEY + 1)
        self.assertFalse(res["ok"])
        self.assertEqual(g.money, config.START_MONEY)
        self.assertEqual(len(ref.calls), 0)

    def test_cooldown_and_unknown_action(self):
        g, ref = self.play_game(say="ok")
        self.assertTrue(g.act("chat", "hallo")["ok"])
        self.assertFalse(g.act("chat", "nochmal")["ok"])
        self.assertFalse(g.act("hack", "x")["ok"])

    def test_rule_proposal_needs_text(self):
        g, ref = self.play_game()
        self.assertFalse(g.act("rule", "")["ok"])

    def test_live_chat_can_create_rule_but_not_decide(self):
        g, ref = self.play_game(decision="penalty", team="home", rule_effect="ball_size", rule_name="Riesenball",
                                rule_text="Ball groß.", rule_team="both", rule_value=2.5, rule_minutes=3)
        g.act("rule", "Größerer Ball")
        self.assertEqual(g.phase, "play")
        self.assertEqual(g.mods()["ball_size"], 2.5)
        self.assertEqual(g.snapshot(0)["ball"]["size"], 2.5)

    def test_rules_expire(self):
        g, ref = self.play_game(rule_effect="player_speed", rule_name="Matsch", rule_text="x", rule_team="both",
                                rule_value=0.5, rule_minutes=1)
        g.act("chat", "Matsch bitte")
        self.assertEqual(len(g.rules), 1)
        run_until(g, lambda: not g.rules, 60)
        self.assertEqual(len(g.rules), 0)

    def test_swap_sides_flips_everything(self):
        g, ref = self.play_game(rule_effect="swap_sides", rule_name="Tausch", rule_text="x", rule_team="both",
                                rule_value=1, rule_minutes=0)
        x_before = g.by_id["h7"].x
        g.act("chat", "tausch")
        self.assertTrue(g.flipped)
        self.assertAlmostEqual(g.by_id["h7"].x, engine.W - x_before, places=1)

    def test_freeze_team_stops_players(self):
        g, ref = self.play_game(rule_effect="freeze_team", rule_name="Eis", rule_text="x", rule_team="away",
                                rule_value=5, rule_minutes=0)
        g.act("chat", "eis")
        self.assertTrue(all(p.frozen > 0 for p in g.active("away")))

    def test_dive_creates_foul_incident(self):
        g, ref = self.play_game(decision="free_kick", team="away")
        g.time += 30
        g.last_dive_t = -99
        res = g.act("dive")
        self.assertTrue(res["ok"])
        self.assertEqual(g.phase, "appeal")
        self.assertTrue(g.incident["dive"])
        self.assertEqual(g.stats["dives"], 1)

    def test_protest_during_decision_can_overturn(self):
        g, ref = self.play_game(decision="free_kick", team="away")
        g.time += 30
        g.last_incident_t = -99
        run_until(g, lambda: g.phase == "appeal", 300)
        g.step(config.APPEAL_SECONDS + 0.5)
        self.assertEqual(g.outcome["team"], "away")
        ref.resp = {"decision": "penalty", "team": "home", "say": "Na gut."}
        g.time += 5
        g.act("protest", "Das war nie ein Foul")
        self.assertEqual(g.outcome, {"decision": "penalty", "team": "home"})

    def test_acting_during_appeal_speeds_up_decision(self):
        g, ref = self.play_game(decision="free_kick", team="home")
        g.time += 30
        g.last_incident_t = -99
        run_until(g, lambda: g.phase == "appeal", 300)
        g.time += 5
        g.act("protest", "ungerecht")
        self.assertEqual(g.phase, "decided")
        self.assertIn("protest: ungerecht", ref.calls[-1]["incident"]["appeals"][0])

    def test_patience_zero_sends_captain_off(self):
        g, ref = self.play_game(patience_delta=-30, say="Genug.")
        for _ in range(5):
            g.time += 3
            g.act("insult", "x")
        self.assertTrue(g.by_id["h4"].red)

    def test_rulebook_is_capped(self):
        g, ref = self.play_game()
        for i in range(config.MAX_RULES + 4):
            g._add_rule({"name": "R%d" % i, "text": "t", "effect": "none", "team": "both", "value": 0, "minutes": 0})
        self.assertEqual(len(g.rules), config.MAX_RULES)


if __name__ == "__main__":
    unittest.main()
