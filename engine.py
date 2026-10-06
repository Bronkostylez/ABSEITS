"""Das Spiel selbst: Platz, Spieler, Ball, Pfiffe, Regeln.

Der Schiri ist nicht hier drin. Die Engine meldet "Das ist passiert" und
bekommt vom Schiri (referee.py) eine Entscheidung zurueck. Alles, was der
Schiri liefert, wird geprueft, bevor es das Spiel veraendert.
"""

import math
import random
import threading

import config

W, H = 105.0, 68.0
GOAL_HALF = 3.66
CAPTAIN = {"home": "h4", "away": "a4"}

DECISIONS = ("play_on", "free_kick", "penalty", "goal_ok", "goal_disallowed", "award_goal", "drop_ball")
CARDS = ("none", "yellow", "red")
CARD_TARGETS = ("none", "offender", "victim", "home_captain", "away_captain", "random")
EFFECTS = ("none", "goal_value", "ball_size", "ball_speed", "player_speed", "goal_size",
           "player_size", "hands_allowed", "no_fouls", "swap_sides", "freeze_team", "add_goal")
INSTANT = ("swap_sides", "freeze_team", "add_goal")

# Formation, immer fuer "Angriff nach rechts": (x-Anteil, y-Anteil, Rolle)
FORMATION = [
    (0.04, 0.50, "GK"),
    (0.20, 0.30, "DEF"),
    (0.20, 0.70, "DEF"),
    (0.44, 0.50, "MID"),
    (0.50, 0.16, "MID"),
    (0.50, 0.84, "MID"),
    (0.70, 0.50, "ST"),
]
NAMES_HOME = ["Kowalski", "Brinkmann", "Yilmaz", "Dein Kapitaen", "Schmitz", "Lukic", "Haase"]
NAMES_AWAY = ["Betonski", "Mueller-Wuerstchen", "Sokolov", "Kaiser", "Dragovic", "Pfeiffer", "Zimmermann"]
NUMBERS_HOME = [1, 4, 5, 10, 7, 8, 9]
NUMBERS_AWAY = [1, 3, 6, 10, 11, 14, 99]

FOUL_TEXTS = [
    "Rempler im Mittelfeld", "Grätsche von hinten", "Trikot gezogen",
    "Ellbogen im Zweikampf", "Bein gestellt", "Schubser an der Seitenlinie",
]


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def other(team):
    return "away" if team == "home" else "home"


class Player:
    def __init__(self, pid, team, idx, name, number):
        self.id = pid
        self.team = team
        fx, fy, role = FORMATION[idx]
        self.fx, self.fy, self.role = fx, fy, role
        self.name = name
        self.number = number
        self.x = self.y = 0.0
        self.vx = self.vy = 0.0
        self.yellow = 0
        self.red = False
        self.fallen = 0.0
        self.frozen = 0.0
        self.think = 0.5
        self.tackle_cd = 0.0
        self.kick_cd = 0.0
        self.face = 1.0

    def view(self):
        return {"id": self.id, "team": self.team, "n": self.number, "name": self.name,
                "x": round(self.x, 2), "y": round(self.y, 2), "yc": self.yellow, "red": self.red,
                "down": self.fallen > 0, "frozen": self.frozen > 0, "role": self.role,
                "face": self.face}


class Game:
    def __init__(self, referee=None, seed=None, sync=False):
        self.rng = random.Random(seed)
        self.referee = referee
        self.sync = sync
        self.lock = threading.RLock()
        self.new_match()

    # ------------------------------------------------------------------
    # Aufbau
    # ------------------------------------------------------------------
    def new_match(self):
        with self.lock:
            self.players = []
            for i in range(7):
                self.players.append(Player("h%d" % (i + 1), "home", i, NAMES_HOME[i], NUMBERS_HOME[i]))
                self.players.append(Player("a%d" % (i + 1), "away", i, NAMES_AWAY[i], NUMBERS_AWAY[i]))
            self.by_id = {p.id: p for p in self.players}
            self.score = {"home": 0, "away": 0}
            self.minute = 0.0
            self.half = 1
            self.flipped = False
            self.time = 0.0
            self.rules = []
            self.rule_counter = 0
            self.events = []
            self.event_counter = 0
            self.money = config.START_MONEY
            self.meters = {"patience": 100.0, "mood": 70.0, "suspicion": 0.0, "crowd": 40.0}
            self.persona = self._make_persona()
            self.stats = {"bribes": 0, "rules": 0, "cards": 0, "dives": 0, "money_spent": 0}
            self.ball = {"x": W / 2, "y": H / 2, "vx": 0.0, "vy": 0.0, "owner": None, "kind": "free",
                         "last_team": "home", "target": None, "forced": None, "kicker": None}
            self.phase = "kickoff"
            self.phase_t = 2.5
            self.incident = None
            self.outcome = None
            self.pending_penalty = None
            self.last_incident_t = -99.0
            self.last_act_t = -99.0
            self.last_dive_t = -99.0
            self.ref_busy = False
            self.ref_say = ""
            self.ref_say_t = 0.0
            self.protest_changes = 0
            self.ref = {"x": W / 2, "y": H * 0.25}
            self.streaker = None
            self.crowd_line = ""
            self.kickoff_team = "home"
            self.reset_positions(self.kickoff_team)
            self.log("info", "Anpfiff gleich: %s gegen %s. Schiri: %s." % (
                config.HOME_NAME, config.AWAY_NAME, self.persona["name"]))

    def _make_persona(self):
        r = self.rng
        names = ["Herr Kowalczyk", "Frau Dr. Brandt", "Herr Hasenclever", "Herr Pfeiffer-Lamm",
                 "Frau Obermeier", "Herr Szymanski", "Herr Tannenbaum"]
        quirks = [
            "liebt Regeln mit Zahlen und kann Dreier nicht leiden",
            "hat Angst vor Hunden und zuckt bei Lärm",
            "will unbedingt, dass man ihn für gerecht hält",
            "isst in jeder Halbzeit heimlich eine Banane und lässt sich nicht gern dabei erwischen",
            "ist überzeugt, er hätte eigentlich Richter werden sollen",
            "hasst Stirnbänder und Diskussionen, aber liebt Komplimente",
            "kann sich Rückennummern nicht merken und nennt alle 'Der Mit Dem Trikot'",
        ]
        return {"name": r.choice(names), "quirk": r.choice(quirks),
                "greed": round(r.uniform(0.25, 0.9), 2), "ego": round(r.uniform(0.3, 0.95), 2)}

    # ------------------------------------------------------------------
    # Hilfen
    # ------------------------------------------------------------------
    def log(self, kind, text, **extra):
        self.event_counter += 1
        ev = {"id": self.event_counter, "kind": kind, "text": text, "min": int(self.minute)}
        ev.update(extra)
        self.events.append(ev)
        if len(self.events) > 300:
            self.events = self.events[-200:]
        return ev

    def attack_dir(self, team):
        d = 1 if team == "home" else -1
        return -d if self.flipped else d

    def goal_x(self, attacking_team):
        return W if self.attack_dir(attacking_team) > 0 else 0.0

    def own_goal_x(self, team):
        return 0.0 if self.attack_dir(team) > 0 else W

    def home_pos(self, p, kickoff=False):
        d = self.attack_dir(p.team)
        fx = p.fx
        if kickoff:
            fx = min(fx, 0.46)
        x = fx * W if d > 0 else (1 - fx) * W
        return x, p.fy * H

    def active(self, team=None):
        return [p for p in self.players if not p.red and (team is None or p.team == team)]

    def mods(self):
        m = {"goal_value": {"home": 1, "away": 1}, "ball_size": 1.0, "ball_speed": 1.0,
             "speed": {"home": 1.0, "away": 1.0}, "goal_size": {"home": 1.0, "away": 1.0},
             "player_size": {"home": 1.0, "away": 1.0}, "hands_allowed": False, "no_fouls": False}
        for r in self.rules:
            e, t, v = r["effect"], r["team"], r["value"]
            teams = ("home", "away") if t == "both" else (t,)
            if e == "goal_value":
                for x in teams:
                    m["goal_value"][x] = int(v)
            elif e == "ball_size":
                m["ball_size"] *= v
            elif e == "ball_speed":
                m["ball_speed"] *= v
            elif e == "player_speed":
                for x in teams:
                    m["speed"][x] *= v
            elif e == "goal_size":
                for x in teams:
                    m["goal_size"][x] *= v
            elif e == "player_size":
                for x in teams:
                    m["player_size"][x] *= v
            elif e == "hands_allowed":
                m["hands_allowed"] = True
            elif e == "no_fouls":
                m["no_fouls"] = True
        m["ball_size"] = clamp(m["ball_size"], 0.4, 4.0)
        m["ball_speed"] = clamp(m["ball_speed"], 0.4, 2.5)
        for x in ("home", "away"):
            m["speed"][x] = clamp(m["speed"][x], 0.3, 2.2)
            m["goal_size"][x] = clamp(m["goal_size"][x], 0.3, 3.0)
            m["player_size"][x] = clamp(m["player_size"][x], 0.5, 2.5)
        return m

    def goal_half(self, defending_team):
        return GOAL_HALF * self.mods()["goal_size"][defending_team]

    def reset_positions(self, kickoff_team):
        for p in self.players:
            if p.red:
                p.x, p.y = (-5.0, -5.0)
                continue
            p.x, p.y = self.home_pos(p, kickoff=True)
            p.vx = p.vy = 0.0
            p.fallen = 0.0
            p.face = self.attack_dir(p.team)
        st = self._striker(kickoff_team)
        if st:
            st.x, st.y = W / 2 - 0.8 * self.attack_dir(st.team), H / 2
            self._give_ball(st)
        else:
            self.ball.update({"x": W / 2, "y": H / 2, "vx": 0.0, "vy": 0.0, "owner": None, "kind": "free"})

    def _striker(self, team):
        act = self.active(team)
        for role in ("ST", "MID", "DEF"):
            for p in act:
                if p.role == role:
                    return p
        return act[0] if act else None

    def _gk(self, team):
        for p in self.active(team):
            if p.role == "GK":
                return p
        return None

    def ensure_gk(self, team):
        if self._gk(team) or not self.active(team):
            return
        defs = [p for p in self.active(team) if p.role == "DEF"] or self.active(team)
        defs[0].role = "GK"
        defs[0].fx, defs[0].fy = FORMATION[0][0], FORMATION[0][1]
        self.log("info", "%s geht ins Tor, weil niemand sonst da ist." % defs[0].name)

    def _give_ball(self, p):
        b = self.ball
        b["owner"] = p.id
        b["kind"] = "carried"
        b["last_team"] = p.team
        b["vx"] = b["vy"] = 0.0
        b["target"] = None
        b["forced"] = None
        b["x"], b["y"] = p.x + p.face * 0.8, p.y
        p.think = self.rng.uniform(0.5, 1.2)

    def _nearest(self, team, x, y, exclude_gk=True):
        best, bd = None, 1e9
        for p in self.active(team):
            if exclude_gk and p.role == "GK" and len(self.active(team)) > 1:
                continue
            d = math.hypot(p.x - x, p.y - y)
            if d < bd:
                best, bd = p, d
        return best

    # ------------------------------------------------------------------
    # Hauptschleife
    # ------------------------------------------------------------------
    def step(self, dt):
        with self.lock:
            self.time += dt
            if self.ref_say_t > 0:
                self.ref_say_t -= dt
            self._ref_move(dt)
            self._decay_meters(dt)
            ph = self.phase
            if ph == "fulltime":
                return
            if ph in ("kickoff", "halftime"):
                self.phase_t -= dt
                if self.phase_t <= 0:
                    if ph == "halftime":
                        self._start_second_half()
                    else:
                        self.phase = "play"
                        self._after_ready()
                return
            if ph == "appeal":
                if not self.ref_busy:
                    self.phase_t -= dt
                    if self.phase_t <= 0:
                        self._ask_ref_incident(None)
                return
            if ph == "deciding":
                return
            if ph == "decided":
                if not self.ref_busy:
                    self.phase_t -= dt
                    if self.phase_t <= 0:
                        self._execute_outcome()
                return
            self._step_play(dt)

    def _after_ready(self):
        if self.pending_penalty:
            pen, self.pending_penalty = self.pending_penalty, None
            self._take_penalty(pen)

    def _decay_meters(self, dt):
        m = self.meters
        m["crowd"] = clamp(m["crowd"] + (35 - m["crowd"]) * 0.01 * dt, 0, 100)
        m["suspicion"] = clamp(m["suspicion"] - 0.15 * dt, 0, 100)
        m["patience"] = clamp(m["patience"] + 0.1 * dt, 0, 100)

    def _ref_move(self, dt):
        tx, ty = self.ref["x"], self.ref["y"]
        if self.incident and self.phase in ("appeal", "deciding", "decided"):
            tx, ty = self.incident["pos"]
            ty = clamp(ty - 3.0, 2, H - 2)
            tx = clamp(tx - 2.5, 2, W - 2)
        else:
            b = self.ball
            tx = clamp(b["x"] * 0.8 + W * 0.1, 8, W - 8)
            ty = clamp(b["y"] * 0.4 + H * 0.3, 6, H - 6)
        k = min(1.0, 2.2 * dt)
        self.ref["x"] += (tx - self.ref["x"]) * k
        self.ref["y"] += (ty - self.ref["y"]) * k

    def _step_play(self, dt):
        mods = self.mods()
        self.minute += dt * 90.0 / config.MATCH_REAL_SECONDS
        if self.half == 1 and self.minute >= 45:
            self.minute = 45.0
            self._halftime()
            return
        if self.minute >= 90:
            self._fulltime()
            return
        self._expire_rules()
        self._update_players(dt, mods)
        self._update_ball(dt, mods)
        if self.phase != "play":
            return
        self._check_tackles(mods)
        if self.phase != "play":
            return
        self._random_incidents(dt)
        if self.streaker:
            self.streaker["t"] += dt
            if self.streaker["t"] > 6:
                self.streaker = None

    # ------------------------------------------------------------------
    # Spieler
    # ------------------------------------------------------------------
    def _update_players(self, dt, mods):
        b = self.ball
        owner = self.by_id.get(b["owner"]) if b["owner"] else None
        chasers = set()
        for team in ("home", "away"):
            cand = [p for p in self.active(team) if p.role != "GK"]
            if owner and owner.team != team:
                tgt = (owner.x, owner.y)
            elif not owner:
                tgt = (b["x"], b["y"])
            else:
                tgt = None
            if tgt:
                cand.sort(key=lambda p: math.hypot(p.x - tgt[0], p.y - tgt[1]))
                for p in cand[:2]:
                    chasers.add(p.id)
        for p in self.active():
            p.tackle_cd = max(0.0, p.tackle_cd - dt)
            p.kick_cd = max(0.0, p.kick_cd - dt)
            if p.frozen > 0:
                p.frozen -= dt
                p.vx = p.vy = 0.0
                continue
            if p.fallen > 0:
                p.fallen -= dt
                p.vx = p.vy = 0.0
                continue
            d = self.attack_dir(p.team)
            hx, hy = self.home_pos(p)
            speed = 6.8 * mods["speed"][p.team]
            if p.role == "GK":
                gx = self.own_goal_x(p.team) + d * 2.2
                ty = clamp(b["y"], H / 2 - 8, H / 2 + 8)
                tx = gx
                if not owner and math.hypot(b["x"] - gx, b["y"] - ty) < 9 and b["kind"] == "free":
                    tx, ty = b["x"], b["y"]
                speed *= 0.8
            elif owner and owner.id == p.id:
                gx = self.goal_x(p.team)
                tx = gx
                ty = H / 2 + math.sin(self.time * 0.8 + p.fy * 9) * 12
                speed *= 0.92
            elif p.id in chasers:
                tgt = owner if (owner and owner.team != p.team) else None
                tx, ty = (tgt.x, tgt.y) if tgt else (b["x"], b["y"])
                speed *= 1.05
            elif owner and owner.team == p.team:
                if p.role == "DEF":
                    tx = hx + (owner.x - hx) * 0.25
                else:
                    tx = owner.x + d * (5 + 14 * p.fx)
                ty = hy + (owner.y - hy) * 0.25
            else:
                tx = hx + (b["x"] - hx) * 0.35
                ty = hy + (b["y"] - hy) * 0.25
            tx = clamp(tx, 1.0, W - 1.0)
            ty = clamp(ty, 1.0, H - 1.0)
            dx, dy = tx - p.x, ty - p.y
            dist = math.hypot(dx, dy)
            if dist > 0.4:
                dvx, dvy = dx / dist * speed, dy / dist * speed
            else:
                dvx = dvy = 0.0
            k = min(1.0, 6.0 * dt)
            p.vx += (dvx - p.vx) * k
            p.vy += (dvy - p.vy) * k
            p.x += p.vx * dt
            p.y += p.vy * dt
            p.x, p.y = clamp(p.x, 0.5, W - 0.5), clamp(p.y, 0.5, H - 0.5)
            if abs(p.vx) > 0.5:
                p.face = 1.0 if p.vx > 0 else -1.0
            if owner and owner.id == p.id:
                p.think -= dt
                if p.think <= 0:
                    self._owner_decides(p, mods)
                    if self.phase != "play":
                        return

    def _owner_decides(self, p, mods):
        gx = self.goal_x(p.team)
        dist = abs(gx - p.x)
        r = self.rng.random()
        if p.role == "GK":
            tm = [q for q in self.active(p.team) if q.id != p.id]
            if tm:
                self._pass(p, self.rng.choice(tm), mods)
            return
        if dist < 30 and r < 0.5:
            self._shoot(p, mods)
        elif r < 0.62:
            tm = [q for q in self.active(p.team) if q.id != p.id and q.role != "GK"]
            if tm:
                tm.sort(key=lambda q: -self.attack_dir(p.team) * q.x + self.rng.uniform(-12, 12))
                self._pass(p, tm[0], mods)
        else:
            p.think = self.rng.uniform(0.4, 1.0)

    def _shoot(self, p, mods, forced=None, aim=None):
        gx = self.goal_x(p.team)
        defending = other(p.team)
        gh = self.goal_half(defending)
        ty = aim if aim is not None else H / 2 + self.rng.uniform(-gh * 1.7, gh * 1.7)
        self._kick(p, gx, ty, 31.0 * mods["ball_speed"], "shot")
        self.ball["forced"] = forced
        self.log("shot", "%s schießt!" % p.name, team=p.team)

    def _pass(self, p, q, mods):
        lead = 0.25
        tx = q.x + q.vx * lead
        ty = q.y + q.vy * lead
        self._kick(p, tx, ty, 21.0 * mods["ball_speed"], "pass")
        self.ball["target"] = q.id

    def _kick(self, p, tx, ty, speed, kind):
        b = self.ball
        dx, dy = tx - b["x"], ty - b["y"]
        d = math.hypot(dx, dy) or 1.0
        b["vx"], b["vy"] = dx / d * speed, dy / d * speed
        b["owner"] = None
        b["kind"] = kind
        b["last_team"] = p.team
        b["kicker"] = p.id
        b["target"] = None
        b["forced"] = None
        p.kick_cd = 0.5
        p.think = self.rng.uniform(0.5, 1.1)

    # ------------------------------------------------------------------
    # Ball
    # ------------------------------------------------------------------
    def _update_ball(self, dt, mods):
        b = self.ball
        if b["owner"]:
            o = self.by_id[b["owner"]]
            if o.red:
                b["owner"], b["kind"] = None, "free"
                return
            b["x"] = o.x + o.face * 0.9
            b["y"] = o.y
            return
        b["x"] += b["vx"] * dt
        b["y"] += b["vy"] * dt
        fr = 0.5 if b["kind"] == "shot" else 1.1
        k = max(0.0, 1.0 - fr * dt)
        b["vx"] *= k
        b["vy"] *= k
        sp = math.hypot(b["vx"], b["vy"])
        if sp < 2.5 and b["kind"] != "free":
            b["kind"] = "free"
            b["target"] = None
        if self._check_goal_line(mods):
            return
        if b["y"] < 0 or b["y"] > H:
            team = other(b["last_team"])
            x = clamp(b["x"], 3, W - 3)
            y = 0.8 if b["y"] < 0 else H - 0.8
            self._quick_restart(team, x, y, "Einwurf")
            return
        self._ball_pickups(mods)

    def _check_goal_line(self, mods):
        b = self.ball
        if 0 <= b["x"] <= W:
            return False
        side_right = b["x"] > W
        attacker = None
        for t in ("home", "away"):
            if (self.goal_x(t) == W) == side_right:
                attacker = t
        defender = other(attacker)
        in_goal = abs(b["y"] - H / 2) <= self.goal_half(defender)
        if in_goal:
            gk = self._gk(defender)
            saved = b["forced"] == "save" or (
                b["forced"] != "goal" and b["kind"] == "shot" and gk and self.rng.random() < 0.45)
            if saved and gk:
                self.log("save", "Parade von %s!" % gk.name, team=defender)
                self.meters["crowd"] = clamp(self.meters["crowd"] + 5, 0, 100)
                gk.x, gk.y = self.own_goal_x(defender) + self.attack_dir(defender) * 2.2, clamp(b["y"], 20, 48)
                self._give_ball(gk)
                return True
            if b["forced"] == "goal":
                self._score(attacker, b["kicker"], auto=True)
                return True
            self._goal_incident(attacker)
            return True
        gk = self._gk(defender)
        if gk:
            gk.x, gk.y = self.own_goal_x(defender) + self.attack_dir(defender) * 2.2, H / 2
            self._give_ball(gk)
            self.log("info", "Ball ins Aus. Abstoß für %s." % self._team_name(defender))
        else:
            b["x"], b["y"], b["vx"], b["vy"], b["kind"] = W / 2, H / 2, 0, 0, "free"
        return True

    def _quick_restart(self, team, x, y, label):
        p = self._nearest(team, x, y)
        if not p:
            return
        p.x, p.y = x, clamp(y, 1, H - 1)
        p.vx = p.vy = 0
        self._give_ball(p)
        self.log("info", "%s für %s." % (label, self._team_name(team)))

    def _ball_pickups(self, mods):
        b = self.ball
        sp = math.hypot(b["vx"], b["vy"])
        radius = 1.3 + 0.55 * (mods["ball_size"] - 1.0)
        for p in self.active():
            if p.kick_cd > 0 or p.fallen > 0:
                continue
            d = math.hypot(p.x - b["x"], p.y - b["y"])
            r = radius + (1.0 if p.role == "GK" else 0.0)
            if d > r:
                continue
            is_target = b["target"] == p.id
            if sp > 24 and not is_target and p.role != "GK":
                continue
            if sp > 12 and not is_target and self.rng.random() > 0.35:
                continue
            intercept = p.team != b["last_team"] and b["kind"] in ("pass", "shot")
            if intercept and not mods["hands_allowed"] and p.role != "GK" and self.rng.random() < 0.05:
                self._handball_incident(p)
                return
            self._give_ball(p)
            return

    # ------------------------------------------------------------------
    # Zweikaempfe und Vorfaelle
    # ------------------------------------------------------------------
    def _gap_ok(self):
        return self.time - self.last_incident_t >= config.MIN_INCIDENT_GAP and not self.ref_busy

    def _check_tackles(self, mods):
        b = self.ball
        if not b["owner"]:
            return
        o = self.by_id[b["owner"]]
        for p in self.active(other(o.team)):
            if p.tackle_cd > 0 or p.fallen > 0 or p.frozen > 0 or o.fallen > 0:
                continue
            if math.hypot(p.x - o.x, p.y - o.y) < 1.9:
                p.tackle_cd = 1.4
                r = self.rng.random()
                foul_p = 0.22 if (self._gap_ok() and not mods["no_fouls"]) else 0.0
                if r < foul_p:
                    self._foul_incident(p, o)
                    return
                if r < foul_p + 0.38:
                    self._give_ball(p)
                    return
                return

    def _random_incidents(self, dt):
        if not self._gap_ok() or self.minute < 2:
            return
        if self.rng.random() < 0.006 * dt and not self.streaker:
            r = self.rng.random()
            if r < 0.5:
                self._tumult_incident()
            else:
                self._streaker_incident()

    def _make_incident(self, kind, text, pos, **kw):
        inc = {"id": self.event_counter + 1, "type": kind, "text": text, "pos": (round(pos[0], 1), round(pos[1], 1)),
               "minute": int(self.minute), "appeals": []}
        inc.update(kw)
        return inc

    def _foul_incident(self, off, victim, dive=False):
        text = "%s: #%d %s gegen #%d %s" % (self.rng.choice(FOUL_TEXTS), off.number, off.name, victim.number, victim.name)
        victim.fallen = 2.5
        pos = (victim.x, victim.y)
        noticed = None
        if dive:
            noticed = self.rng.random() < 0.25 + self.meters["suspicion"] / 200.0
        inc = self._make_incident("foul", text, pos, offender=off.id, victim=victim.id,
                                  beneficiary=victim.team, dive=dive, dive_noticed=noticed)
        self._begin_incident(inc)

    def _handball_incident(self, p):
        text = "Hand! #%d %s hat den Ball mit der Hand gestoppt" % (p.number, p.name)
        inc = self._make_incident("handball", text, (p.x, p.y), offender=p.id, victim=None, beneficiary=other(p.team))
        self._begin_incident(inc)

    def _goal_incident(self, scoring):
        b = self.ball
        shooter = self.by_id.get(b.get("kicker")) if b.get("kicker") else None
        who = "#%d %s" % (shooter.number, shooter.name) if shooter else "jemand"
        text = "TOR?! %s trifft für %s" % (who, self._team_name(scoring))
        inc = self._make_incident("goal", text, (clamp(b["x"], 5, W - 5), clamp(b["y"], 5, H - 5)),
                                  offender=None, victim=b.get("kicker"), beneficiary=scoring, scoring=scoring)
        b["vx"] = b["vy"] = 0.0
        b["x"] = clamp(b["x"], 0.5, W - 0.5)
        b["kind"] = "free"
        self._begin_incident(inc)

    def _tumult_incident(self):
        a = self.rng.choice(self.active("home"))
        c = self.rng.choice(self.active("away"))
        text = "Tumult: #%d %s und #%d %s gehen aufeinander los" % (a.number, a.name, c.number, c.name)
        a.fallen = c.fallen = 1.5
        inc = self._make_incident("tumult", text, ((a.x + c.x) / 2, (a.y + c.y) / 2), offender=c.id, victim=a.id,
                                  beneficiary=None)
        self._begin_incident(inc)

    def _streaker_incident(self):
        y = self.rng.uniform(15, 55)
        self.streaker = {"t": 0.0, "y": y, "dir": self.rng.choice([-1, 1])}
        inc = self._make_incident("streaker", "Ein Flitzer rennt über den Platz", (W / 2, y), offender=None,
                                  victim=None, beneficiary=None)
        self._begin_incident(inc)

    def _begin_incident(self, inc):
        self.incident = inc
        self.outcome = None
        self.protest_changes = 0
        self.last_incident_t = self.time
        self.phase = "appeal"
        self.phase_t = config.APPEAL_SECONDS
        for p in self.players:
            p.vx = p.vy = 0.0
        b = self.ball
        if inc["type"] != "goal" and b["owner"]:
            b["hold_owner"] = b["owner"]
        self.log("whistle", "PFIFF! " + inc["text"], itype=inc["type"], x=inc["pos"][0], y=inc["pos"][1])
        self.meters["crowd"] = clamp(self.meters["crowd"] + 6, 0, 100)

    # ------------------------------------------------------------------
    # Schiri fragen
    # ------------------------------------------------------------------
    def context(self, kind, action=None):
        inc = self.incident
        ctx = {
            "kind": kind,
            "persona": self.persona,
            "teams": {"home": config.HOME_NAME, "away": config.AWAY_NAME},
            "minute": int(self.minute),
            "score": dict(self.score),
            "meters": {k: int(v) for k, v in self.meters.items()},
            "rules": [{"name": r["name"], "text": r["text"], "effect": r["effect"], "team": r["team"],
                       "value": r["value"]} for r in self.rules],
            "recent": [e["text"] for e in self.events[-6:] if e["kind"] in ("whistle", "speech", "goal", "card", "rule", "bribe")],
            "captain": "#%d %s" % (self.by_id["h4"].number, self.by_id["h4"].name),
            "captain_on_pitch": not self.by_id["h4"].red,
            "action": action,
        }
        if inc:
            ctx["incident"] = {k: inc.get(k) for k in ("type", "text", "beneficiary", "scoring", "dive", "dive_noticed")}
            ctx["incident"]["appeals"] = list(inc["appeals"])
            ctx["incident"]["offender"] = self._pname(inc.get("offender"))
            ctx["incident"]["victim"] = self._pname(inc.get("victim"))
        if self.outcome and kind == "protest_window":
            ctx["current_outcome"] = {"decision": self.outcome["decision"], "team": self.outcome["team"]}
        return ctx

    def _pname(self, pid):
        p = self.by_id.get(pid) if pid else None
        return ("#%d %s (%s)" % (p.number, p.name, self._team_name(p.team))) if p else None

    def _team_name(self, team):
        return config.HOME_NAME if team == "home" else config.AWAY_NAME

    def _call_ref(self, ctx, handler):
        self.ref_busy = True

        def work():
            try:
                resp, source = self.referee.decide(ctx)
            except Exception as exc:  # der Notbetrieb darf nie ausfallen
                from referee import offline_decide
                resp, source = offline_decide(ctx, self.rng), "offline"
                resp["_error"] = str(exc)
            with self.lock:
                self.ref_busy = False
                self.source = source
                handler(resp)

        if self.sync:
            work()
        else:
            threading.Thread(target=work, daemon=True).start()

    def _ask_ref_incident(self, action):
        self.phase = "deciding"
        ctx = self.context("incident", action)
        self._call_ref(ctx, self._on_incident_decision)

    def _on_incident_decision(self, resp):
        inc = self.incident
        self._apply_common(resp, inc)
        dec = self._normalize_decision(resp, inc)
        self.outcome = dec
        self.phase = "decided"
        self.phase_t = config.PROTEST_SECONDS
        self.log("decision", self._describe(dec), decision=dec["decision"])

    def _normalize_decision(self, resp, inc):
        d = resp.get("decision", "play_on")
        t = resp.get("team", "none")
        typ = inc["type"]
        if typ == "goal":
            if d not in ("goal_ok", "award_goal"):
                d = "goal_disallowed"
        else:
            if d in ("goal_ok", "goal_disallowed"):
                d = "play_on"
        if d in ("free_kick", "penalty", "award_goal") and t not in ("home", "away"):
            t = inc.get("beneficiary") or self.rng.choice(["home", "away"])
        if d == "penalty" and typ == "streaker":
            d = "drop_ball"
        return {"decision": d, "team": t}

    def _describe(self, dec):
        d, t = dec["decision"], dec["team"]
        name = self._team_name(t) if t in ("home", "away") else ""
        return {"play_on": "Weiterspielen", "free_kick": "Freistoß für " + name,
                "penalty": "ELFMETER für " + name, "goal_ok": "Tor gilt",
                "goal_disallowed": "Tor zählt NICHT", "award_goal": "Tor für %s (einfach so)" % name,
                "drop_ball": "Schiedsrichterball"}[d]

    def _apply_common(self, resp, inc):
        """Alles, was bei jeder Antwort des Schiris gilt: Spruch, Karten, Regel, Werte."""
        say = resp.get("say", "")
        if say:
            self.ref_say, self.ref_say_t = say, 6.0
            self.log("speech", say)
        if resp.get("away_says"):
            self.log("away", resp["away_says"])
        if resp.get("crowd"):
            self.crowd_line = resp["crowd"]
            self.log("crowd", resp["crowd"])
        m = self.meters
        m["patience"] = clamp(m["patience"] + resp.get("patience_delta", 0), 0, 100)
        m["mood"] = clamp(m["mood"] + resp.get("mood_delta", 0), 0, 100)
        m["suspicion"] = clamp(m["suspicion"] + resp.get("suspicion_delta", 0), 0, 100)
        m["crowd"] = clamp(m["crowd"] + resp.get("crowd_delta", 0), 0, 100)
        br = resp.get("bribe_response", "none")
        amt = resp.get("_bribe_amount", 0)
        if amt and br in ("accept", "reject_and_keep"):
            amt = min(amt, self.money)
            self.money -= amt
            self.stats["bribes"] += 1
            self.stats["money_spent"] += amt
            self.log("bribe", "%d € wandern in die Schiri-Tasche%s" % (amt, "" if br == "accept" else " (ohne Gegenleistung)"), amount=amt)
        elif amt and br == "reject":
            self.log("bribe", "Schiri lehnt die %d € ab." % amt, amount=0)
        card = resp.get("card", "none")
        if card != "none":
            self._card(card, self._resolve_target(resp.get("card_target", "none"), inc), resp)
        rule = resp.get("rule")
        if rule:
            self._add_rule(rule)
        if m["patience"] <= 0 and not self.by_id["h4"].red:
            self.log("info", "Der Schiri hat genug von deinem Kapitän.")
            m["patience"] = 40
            self._card("red", self.by_id["h4"], resp)

    def _resolve_target(self, tg, inc):
        if tg == "none":
            return None
        if tg == "offender" and inc and inc.get("offender"):
            return self.by_id.get(inc["offender"])
        if tg == "victim" and inc and inc.get("victim"):
            return self.by_id.get(inc["victim"])
        if tg == "home_captain":
            return self.by_id["h4"]
        if tg == "away_captain":
            return self.by_id["a4"]
        if tg == "random":
            return self.rng.choice(self.active())
        return None

    def _card(self, kind, p, resp=None):
        if not p or p.red:
            return
        self.stats["cards"] += 1
        if kind == "red" and len(self.active(p.team)) <= 3:
            kind = "yellow"
        if kind == "yellow":
            p.yellow += 1
            if p.yellow >= 2:
                self.log("card", "GELB-ROT für #%d %s!" % (p.number, p.name), card="red", pid=p.id)
                self._send_off(p)
            else:
                self.log("card", "GELB für #%d %s." % (p.number, p.name), card="yellow", pid=p.id)
        else:
            self.log("card", "ROT für #%d %s!" % (p.number, p.name), card="red", pid=p.id)
            self._send_off(p)

    def _send_off(self, p):
        p.red = True
        if self.ball["owner"] == p.id:
            self.ball["owner"], self.ball["kind"] = None, "free"
        p.x, p.y = -5.0, -5.0
        self.ensure_gk(p.team)
        self.meters["crowd"] = clamp(self.meters["crowd"] + 10, 0, 100)

    # ------------------------------------------------------------------
    # Regeln
    # ------------------------------------------------------------------
    def _add_rule(self, rule):
        self.rule_counter += 1
        r = {"id": self.rule_counter, "name": rule["name"], "text": rule["text"], "effect": rule["effect"],
             "team": rule["team"], "value": rule["value"], "created": self.minute,
             "expires": (self.minute + rule["minutes"]) if rule["minutes"] else None}
        self.stats["rules"] += 1
        if rule["effect"] in INSTANT:
            self._instant_effect(r)
            r["expires"] = self.minute + 0.01
        self.rules.append(r)
        if len(self.rules) > config.MAX_RULES:
            old = self.rules.pop(0)
            self.log("info", "Regel '%s' ist im Regelbuch verloren gegangen." % old["name"])
        self.log("rule", "NEUE REGEL: %s - %s" % (r["name"], r["text"]), rule=r)

    def _instant_effect(self, r):
        e = r["effect"]
        teams = ["home", "away"] if r["team"] == "both" else [r["team"]]
        if e == "swap_sides":
            self.flipped = not self.flipped
            for p in self.players:
                if not p.red:
                    p.x = W - p.x
                    p.face = -p.face
            self.ball["x"] = W - self.ball["x"]
            self.ball["vx"] = -self.ball["vx"]
        elif e == "freeze_team":
            for t in teams:
                for p in self.active(t):
                    p.frozen = clamp(r["value"], 2, 10)
        elif e == "add_goal":
            for t in teams:
                self.score[t] = max(0, self.score[t] + int(r["value"]))
            self.log("goal", "Der Schiri ändert den Spielstand: %d:%d" % (self.score["home"], self.score["away"]),
                     team=None, silent=True)

    def _expire_rules(self):
        keep = []
        for r in self.rules:
            if r["expires"] is not None and self.minute >= r["expires"]:
                if r["effect"] not in INSTANT:
                    self.log("info", "Regel '%s' ist abgelaufen." % r["name"])
                continue
            keep.append(r)
        self.rules = keep

    # ------------------------------------------------------------------
    # Entscheidung ausfuehren
    # ------------------------------------------------------------------
    def _execute_outcome(self):
        inc, out = self.incident, self.outcome
        d, t = out["decision"], out["team"]
        b = self.ball
        mods = self.mods()
        self.incident = None
        self.outcome = None
        self.protest_changes = 0
        self.last_incident_t = self.time
        b.pop("hold_owner", None)
        for p in self.players:
            p.fallen = 0.0
        if d == "goal_ok":
            self._score(inc["scoring"], inc.get("victim"))
            return
        if d == "award_goal":
            self._score(t if t in ("home", "away") else inc["beneficiary"], inc.get("victim"), awarded=True)
            return
        if inc["type"] == "goal" or d == "goal_disallowed":
            defender = other(inc["scoring"])
            gk = self._gk(defender)
            if gk:
                gk.x, gk.y = self.own_goal_x(defender) + self.attack_dir(defender) * 2.2, H / 2
                self._give_ball(gk)
            self._go_ready(1.5)
            return
        if d == "penalty":
            self._setup_penalty(t)
            return
        if d == "free_kick":
            p = self._nearest(t, *inc["pos"])
            if p:
                p.x, p.y = inc["pos"]
                self._give_ball(p)
        elif d == "drop_ball":
            team = self.rng.choice(["home", "away"])
            p = self._nearest(team, *inc["pos"])
            if p:
                p.x, p.y = inc["pos"]
                self._give_ball(p)
        else:  # play_on
            vic = self.by_id.get(inc.get("victim")) if inc.get("victim") else None
            if vic and not vic.red and inc["type"] in ("foul",):
                self._give_ball(vic)
            else:
                p = self._nearest(self.rng.choice(["home", "away"]), *inc["pos"])
                if p:
                    self._give_ball(p)
        self._go_ready(1.2)

    def _go_ready(self, secs):
        self.phase = "kickoff"
        self.phase_t = secs

    def _score(self, team, shooter_id, awarded=False, auto=False):
        v = self.mods()["goal_value"][team]
        self.score[team] += v
        sh = self.by_id.get(shooter_id) if shooter_id else None
        txt = "TOOOR für %s%s! Stand: %d:%d" % (
            self._team_name(team), (" durch #%d %s" % (sh.number, sh.name)) if sh and not awarded else "",
            self.score["home"], self.score["away"])
        if v != 1:
            txt += " (Tor zählt %d)" % v
        self.log("goal", txt, team=team, value=v)
        self.meters["crowd"] = clamp(self.meters["crowd"] + 25, 0, 100)
        self.kickoff_team = other(team)
        self.incident = None
        self.reset_positions(self.kickoff_team)
        self._go_ready(3.0)

    def _setup_penalty(self, team):
        gx = self.goal_x(team)
        d = self.attack_dir(team)
        spot_x = gx - d * 11.0
        taker = self._striker(team)
        if not taker:
            self._go_ready(1.0)
            return
        for p in self.active():
            hx, hy = self.home_pos(p)
            p.x, p.y = (hx, hy)
            if p.team == team:
                p.x = clamp(gx - d * 22 + (p.fx - 0.4) * 10 * d, 1, W - 1)
            else:
                p.x = clamp(gx - d * 20, 1, W - 1) if p.role != "GK" else p.x
        taker.x, taker.y = spot_x - d * 1.2, H / 2
        gk = self._gk(other(team))
        if gk:
            gk.x, gk.y = gx - d * 1.5, H / 2
        self._give_ball(taker)
        self.ball["x"], self.ball["y"] = spot_x, H / 2
        self.pending_penalty = {"team": team, "taker": taker.id}
        self._go_ready(2.0)

    def _take_penalty(self, pen):
        taker = self.by_id[pen["taker"]]
        goal = self.rng.random() < 0.72
        gh = self.goal_half(other(pen["team"]))
        aim = H / 2 + self.rng.choice([-1, 1]) * gh * 0.8
        self.ball["x"], self.ball["y"] = taker.x + taker.face * 0.9, taker.y
        self.ball["owner"] = taker.id
        self._shoot(taker, self.mods(), forced="goal" if goal else "save", aim=aim)

    # ------------------------------------------------------------------
    # Halbzeit, Abpfiff
    # ------------------------------------------------------------------
    def _halftime(self):
        self.phase = "halftime"
        self.phase_t = 5.0
        self.log("info", "Halbzeit: %d:%d" % (self.score["home"], self.score["away"]), banner="Halbzeit")

    def _start_second_half(self):
        self.half = 2
        self.flipped = not self.flipped
        self.kickoff_team = "away"
        self.reset_positions("away")
        self.phase = "kickoff"
        self.phase_t = 2.5
        self.log("info", "Zweite Halbzeit. Die Seiten sind getauscht.")

    def _fulltime(self):
        self.phase = "fulltime"
        self.minute = 90.0
        h, a = self.score["home"], self.score["away"]
        res = "Sieg für %s" % config.HOME_NAME if h > a else ("Niederlage" if h < a else "Unentschieden")
        self.log("info", "ABPFIFF: %d:%d. %s." % (h, a, res), banner="Abpfiff")

    # ------------------------------------------------------------------
    # Aktionen des Spielers
    # ------------------------------------------------------------------
    ACTIONS = ("protest", "bribe", "flatter", "insult", "rule", "chat", "dive")

    def act(self, kind, text="", amount=0):
        with self.lock:
            if kind not in self.ACTIONS:
                return {"ok": False, "error": "Unbekannte Aktion."}
            if self.phase in ("halftime", "fulltime"):
                return {"ok": False, "error": "Gerade keine Spielphase."}
            if self.ref_busy or self.phase == "deciding":
                return {"ok": False, "error": "Der Schiri denkt noch."}
            if self.time - self.last_act_t < config.ACT_COOLDOWN:
                return {"ok": False, "error": "Nicht so schnell."}
            if kind == "dive":
                return self._dive()
            text = " ".join(str(text or "").split())[:160]
            try:
                amount = int(amount)
            except (TypeError, ValueError):
                amount = 0
            if kind == "bribe":
                if amount < 1:
                    return {"ok": False, "error": "Wie viel denn?"}
                if amount > self.money:
                    return {"ok": False, "error": "So viel Geld hast du nicht."}
            else:
                amount = 0
            if kind == "rule" and not text:
                return {"ok": False, "error": "Schreib deinen Regelvorschlag auf."}
            return self._act_speak(kind, text, amount)

    def _act_speak(self, kind, text, amount):
        self.last_act_t = self.time
        cap = self.by_id["h4"]
        label = {"protest": "protestiert", "bribe": "steckt dem Schiri %d € zu" % amount,
                 "flatter": "schmeichelt dem Schiri", "insult": "pöbelt den Schiri an",
                 "rule": "schlägt eine Regel vor", "chat": "sagt"}[kind]
        shown = ('"%s"' % text) if text else ""
        self.log("player", ("Du %s %s" % (label, shown)).strip(), akind=kind)
        action = {"type": kind, "text": text, "amount": amount}
        if self.phase == "appeal":
            self.incident["appeals"].append("%s: %s%s" % (kind, text, (" (%d €)" % amount) if amount else ""))
            self._ask_with_amount("incident", action, self._on_incident_decision_a(amount))
        elif self.phase == "decided":
            self._ask_with_amount("protest_window", action, self._on_protest(amount))
        else:
            self._ask_with_amount("live", action, self._on_live(amount))
        return {"ok": True}

    def _ask_with_amount(self, kind, action, handler):
        if kind == "incident":
            self.phase = "deciding"
        ctx = self.context(kind, action)
        self._call_ref(ctx, handler)

    def _on_incident_decision_a(self, amount):
        def h(resp):
            resp["_bribe_amount"] = amount
            self._on_incident_decision(resp)
        return h

    def _on_protest(self, amount):
        def h(resp):
            resp["_bribe_amount"] = amount
            inc = self.incident
            self._apply_common(resp, inc)
            if inc and self.outcome is not None and self.protest_changes < 3 and resp.get("decision") != "play_on":
                new = self._normalize_decision(resp, inc)
                if new != self.outcome:
                    self.protest_changes += 1
                    self.outcome = new
                    self.log("decision", "Der Schiri überlegt es sich anders: " + self._describe(new), decision=new["decision"], changed=True)
            self.phase_t = max(self.phase_t, 2.5)
        return h

    def _on_live(self, amount):
        def h(resp):
            resp["_bribe_amount"] = amount
            self._apply_common(resp, None)
        return h

    def _dive(self):
        if self.phase != "play":
            return {"ok": False, "error": "Eine Schwalbe geht nur im laufenden Spiel."}
        if self.time - self.last_dive_t < 20:
            return {"ok": False, "error": "Der Schiri guckt noch skeptisch von der letzten Schwalbe."}
        b = self.ball
        near = None
        if b["owner"] and self.by_id[b["owner"]].team == "home":
            near = self.by_id[b["owner"]]
        if not near:
            cands = [p for p in self.active("home") if p.role != "GK"]
            near = min(cands, key=lambda p: math.hypot(p.x - b["x"], p.y - b["y"])) if cands else None
        opp = self._nearest("away", near.x, near.y) if near else None
        if not near or not opp:
            return {"ok": False, "error": "Gerade nicht möglich."}
        self.last_dive_t = self.time
        self.last_act_t = self.time
        self.stats["dives"] += 1
        self.log("player", "Dein Spieler #%d wirft sich theatralisch hin..." % near.number, akind="dive")
        self._foul_incident(opp, near, dive=True)
        return {"ok": True}

    # ------------------------------------------------------------------
    # Daten fuer die Oberflaeche
    # ------------------------------------------------------------------
    def snapshot(self, since=0):
        with self.lock:
            m = self.mods()
            inc = self.incident
            return {
                "title": config.TITLE,
                "time": round(self.time, 2),
                "minute": round(self.minute, 1),
                "half": self.half,
                "phase": self.phase,
                "phase_t": round(max(0.0, self.phase_t), 1),
                "appeal_total": config.APPEAL_SECONDS,
                "protest_total": config.PROTEST_SECONDS,
                "score": self.score,
                "teams": {"home": config.HOME_NAME, "away": config.AWAY_NAME},
                "flipped": self.flipped,
                "players": [p.view() for p in self.players],
                "ball": {"x": round(self.ball["x"], 2), "y": round(self.ball["y"], 2),
                         "owner": self.ball["owner"], "size": round(m["ball_size"], 2)},
                "mods": {"goal_size": m["goal_size"], "player_size": m["player_size"]},
                "ref": {"x": round(self.ref["x"], 2), "y": round(self.ref["y"], 2),
                        "name": self.persona["name"], "quirk": self.persona["quirk"],
                        "say": self.ref_say if self.ref_say_t > 0 else "", "busy": self.ref_busy},
                "streaker": self.streaker,
                "meters": {k: round(v, 1) for k, v in self.meters.items()},
                "money": self.money,
                "rules": self.rules,
                "stats": self.stats,
                "incident": ({"type": inc["type"], "text": inc["text"], "x": inc["pos"][0], "y": inc["pos"][1]} if inc else None),
                "outcome": self.outcome,
                "source": getattr(self, "source", None),
                "ref_status": self.referee.status() if self.referee else {"mode": "offline"},
                "events": [e for e in self.events if e["id"] > since],
                "last_event": self.event_counter,
                "captain_off": self.by_id["h4"].red,
          }
