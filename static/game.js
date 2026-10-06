"use strict";
// Oberfläche: holt den Spielstand vom Python-Server und zeichnet alles.
const W = 105, H = 68, MARGIN = 7.4;
const $ = (id) => document.getElementById(id);
const canvas = $("pitch"), ctx = canvas.getContext("2d");

let S = null;               // letzter Spielstand vom Server
let lastEvent = 0;
let firstLoad = true;
const disp = {};            // angezeigte (weich nachgeführte) Positionen
const ball = { x: W / 2, y: H / 2, trail: [] };
const refPos = { x: W / 2, y: 17 };
let particles = [], floaters = [], rings = [], chants = [];
let shake = 0, flashRed = 0, goalGlow = 0;
let amount = 50;
let sx = 1, ox = 0, oy = 0, cw = 0, ch = 0, dpr = 1;
let crowdDots = [];
const COLORS = { home: "#ff3d5a", away: "#3db7ff" };

const ACTION_DEFAULTS = {
  protest: ["Das war nie ein Foul!", "Schiri, bist du blind?", "Das ist ein Skandal!", "Sie haben den Ball doch gar nicht gesehen!"],
  bribe: ["Für Ihre Weiterbildung.", "Ein kleiner Gruß vom Verein.", "Hier, für den Kaffee."],
  flatter: ["Beste Leistung des Abends, Herr Schiedsrichter.", "Sie haben ein Auge wie ein Adler.", "Endlich mal ein Schiri mit Stil."],
  insult: ["Sie Pfeifenkopf!", "Mein Opa pfeift besser!", "Gehen Sie nach Hause!"],
  rule: ["Tore zählen doppelt, wenn man sie mit links schießt.", "Jeder darf einmal pro Halbzeit den Ball in die Hand nehmen.", "Wer das Tor trifft, darf es sich aussuchen, welches Tor."],
};

// ---------------------------------------------------------------- Größe
function resize() {
  const r = canvas.getBoundingClientRect();
  dpr = Math.min(2, window.devicePixelRatio || 1);
  canvas.width = Math.round(r.width * dpr);
  canvas.height = Math.round(r.height * dpr);
  cw = r.width; ch = r.height;
  sx = Math.min(cw / (W + MARGIN * 2), ch / (H + MARGIN * 2));
  ox = (cw - W * sx) / 2; oy = (ch - H * sx) / 2;
  buildCrowd();
}
window.addEventListener("resize", resize);

function buildCrowd() {
  crowdDots = [];
  const rnd = mulberry(7);
  const add = (x, y, side) => crowdDots.push({ x, y, side, ph: rnd() * 6.28, c: rnd() < 0.5 ? 0 : 1, h: rnd() });
  for (let row = 0; row < 4; row++) {
    for (let x = -MARGIN; x <= W + MARGIN; x += 1.35) {
      add(x + (row % 2) * 0.6, -2.6 - row * 1.35, "t");
      add(x + (row % 2) * 0.6, H + 2.6 + row * 1.35, "b");
    }
  }
  for (let row = 0; row < 3; row++) {
    for (let y = -2; y <= H + 2; y += 1.4) {
      add(-3.6 - row * 1.3, y, "l");
      add(W + 3.6 + row * 1.3, y, "r");
    }
  }
}
function mulberry(a) { return function () { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }

const X = (x) => ox + x * sx, Y = (y) => oy + y * sx;

// ---------------------------------------------------------------- Netz
async function poll() {
  try {
    const r = await fetch("/api/state?since=" + lastEvent, { cache: "no-store" });
    const s = await r.json();
    S = s;
    if (s.last_event < lastEvent) { lastEvent = 0; $("ticker").innerHTML = ""; $("rules").innerHTML = ""; renderedRules = {}; firstLoad = true; }
    handleEvents(s.events);
    lastEvent = s.last_event;
    updateUI(s);
    firstLoad = false;
  } catch (e) { /* Server kurz weg */ }
  setTimeout(poll, 70);
}

async function act(kind, text, amt) {
  initAudio();
  try {
    const r = await fetch("/api/act", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ type: kind, text: text || "", amount: amt || 0 }) });
    const j = await r.json();
    if (!j.ok) toast(j.error || "Das geht gerade nicht.");
    else if (kind !== "dive") $("sayInput").value = "";
  } catch (e) { toast("Server nicht erreichbar."); }
}

function toast(t) {
  const el = document.createElement("div");
  el.className = "floaty";
  floaters.push({ text: t, x: W / 2, y: H - 6, life: 1.6, max: 1.6, color: "#ffd23f", size: 1.6 });
}

// ---------------------------------------------------------------- Events
function handleEvents(evs) {
  for (const e of evs) {
    addTicker(e);
    if (firstLoad) { if (e.kind === "rule") addRuleCard(e.rule, false); continue; }
    fx(e);
  }
}

function fx(e) {
  switch (e.kind) {
    case "whistle":
      rings.push({ x: e.x, y: e.y, r: 0, life: 1 });
      rings.push({ x: e.x, y: e.y, r: -2, life: 1 });
      shake = Math.max(shake, 0.25);
      sfx("whistle");
      break;
    case "goal":
      if (e.silent) break;
      confetti(e.team);
      banner("TOOOR!", e.text.replace(/^TOOOR für /, "").split("!")[0]);
      goalGlow = 1.5;
      shake = Math.max(shake, 0.6);
      sfx("horn");
      popScore();
      break;
    case "card":
      showCard(e.card, e.text);
      sfx(e.card === "red" ? "buzz" : "tick");
      if (e.card === "red") { flashRed = 1; shake = 1; }
      break;
    case "rule":
      addRuleCard(e.rule, true);
      banner("NEUE REGEL", e.rule.name);
      sfx("magic");
      shake = Math.max(shake, 0.35);
      break;
    case "bribe":
      if (e.amount > 0) moneyBurst(e.amount);
      else floaters.push({ text: "abgelehnt!", x: refPos.x, y: refPos.y - 3, life: 1.8, max: 1.8, color: "#ff8da0", size: 1.7 });
      $("money").parentElement.classList.remove("hit"); void $("money").offsetWidth; $("money").parentElement.classList.add("hit");
      break;
    case "save":
      floaters.push({ text: "PARADE!", x: W / 2, y: H / 2 - 8, life: 1.4, max: 1.4, color: "#2ee59d", size: 2.4 });
      sfx("tick");
      break;
    case "crowd":
      chants.push({ text: e.text, life: 4, max: 4, x: 10 + Math.random() * 60, side: Math.random() < 0.5 ? "t" : "b" });
      break;
    case "shot":
      floaters.push({ text: "SCHUSS!", x: ball.x, y: ball.y - 3, life: 0.8, max: 0.8, color: "#fff", size: 1.5 });
      break;
    case "decision":
      sfx("tick");
      break;
    case "info":
      if (e.banner) banner(e.banner, "");
      break;
  }
}

function addTicker(e) {
  const t = $("ticker");
  const row = document.createElement("div");
  row.className = "tk k-" + e.kind;
  const who = e.kind === "speech" ? "Schiri: " : e.kind === "away" ? "Gegner: " : e.kind === "crowd" ? "Fans: " : "";
  row.innerHTML = "<em>" + e.min + "'</em><span></span>";
  row.lastChild.textContent = who + e.text;
  t.appendChild(row);
  while (t.children.length > 9) t.removeChild(t.firstChild);
}

let renderedRules = {};
const EFFECT_LABEL = {
  goal_value: (r) => "Tor zählt " + r.value, ball_size: (r) => "Ball ×" + r.value.toFixed(1), ball_speed: (r) => "Ball-Tempo ×" + r.value.toFixed(1),
  player_speed: (r) => "Spieler-Tempo ×" + r.value.toFixed(1), goal_size: (r) => "Tor ×" + r.value.toFixed(1), player_size: (r) => "Spielergröße ×" + r.value.toFixed(1),
  hands_allowed: () => "Hand erlaubt", no_fouls: () => "Keine Fouls", swap_sides: () => "Seitenwechsel", freeze_team: (r) => "Eingefroren " + r.value + " s",
  add_goal: (r) => (r.value > 0 ? "+" : "") + r.value + " Tor", none: () => "nur Gerede",
};
function teamLabel(t) { return t === "both" ? "beide Teams" : (S ? S.teams[t] : t); }
function addRuleCard(r, isNew) {
  if (renderedRules[r.id]) return;
  renderedRules[r.id] = true;
  const box = $("rules");
  const el = document.createElement("div");
  el.className = "rule" + (isNew ? " new" : "");
  el.dataset.id = r.id;
  const lab = (EFFECT_LABEL[r.effect] || EFFECT_LABEL.none)(r);
  el.innerHTML = "<b></b><p></p><div class='chips2'><span class='eff'></span><span class='tm'></span><span class='tt'></span></div>";
  el.querySelector("b").textContent = r.name;
  el.querySelector("p").textContent = r.text;
  el.querySelector(".eff").textContent = lab;
  el.querySelector(".tm").textContent = r.effect === "none" || r.effect === "swap_sides" ? "" : teamLabel(r.team);
  if (!el.querySelector(".tm").textContent) el.querySelector(".tm").remove();
  box.prepend(el);
  setTimeout(() => el.classList.remove("new"), 3000);
}

function banner(big, small) {
  const b = $("bigBanner");
  b.classList.add("hidden"); void b.offsetWidth;
  b.innerHTML = "";
  b.appendChild(document.createTextNode(big));
  if (small) { const s = document.createElement("small"); s.textContent = small; b.appendChild(s); }
  b.classList.remove("hidden");
  clearTimeout(banner.t);
  banner.t = setTimeout(() => b.classList.add("hidden"), 2300);
}
function showCard(kind, text) {
  const c = $("cardFlash");
  c.classList.add("hidden"); void c.offsetWidth;
  c.querySelector(".the-card").className = "the-card " + (kind === "red" ? "red" : "yellow");
  c.querySelector(".card-who").textContent = text;
  c.classList.remove("hidden");
  clearTimeout(showCard.t);
  showCard.t = setTimeout(() => c.classList.add("hidden"), 2000);
}
function popScore() {
  for (const id of ["scoreHome", "scoreAway"]) { const el = $(id); el.classList.remove("pop"); void el.offsetWidth; el.classList.add("pop"); }
}

function confetti(team) {
  const cols = ["#ffd23f", "#ff3d5a", "#3db7ff", "#2ee59d", "#fff", "#9b7bff"];
  for (let i = 0; i < 160; i++) {
    particles.push({ kind: "conf", x: W / 2 + (Math.random() - 0.5) * 30, y: H / 2, vx: (Math.random() - 0.5) * 70, vy: -30 - Math.random() * 50,
      rot: Math.random() * 6, vr: (Math.random() - 0.5) * 14, life: 2.6 + Math.random(), c: cols[i % cols.length], w: 0.8 + Math.random() * 0.8 });
  }
}
function moneyBurst(amt) {
  const n = Math.min(14, 4 + Math.floor(amt / 20));
  const h = S ? S.players.find((p) => p.id === "h4") : null;
  const sxp = h ? (disp.h4 || h).x : 20, syp = h ? (disp.h4 || h).y : 34;
  for (let i = 0; i < n; i++) {
    particles.push({ kind: "bill", x: sxp, y: syp, tx: refPos.x, ty: refPos.y, t: -i * 0.06, life: 1.1, rot: Math.random() * 3 });
  }
  floaters.push({ text: "-" + amt + " €", x: sxp, y: syp - 3, life: 1.6, max: 1.6, color: "#2ee59d", size: 2 });
}

// ---------------------------------------------------------------- UI-Panels
let uiLast = {};
function setText(id, t) { const el = $(id); if (uiLast[id] !== t) { el.textContent = t; uiLast[id] = t; } }
const METER_COL = { patience: ["#ff3d5a", "#2ee59d"], mood: ["#ff3d5a", "#ffd23f"], suspicion: ["#2ee59d", "#ff3d5a"], crowd: ["#3db7ff", "#ffd23f"] };
function mix(a, b, t) { const pa = parseInt(a.slice(1), 16), pb = parseInt(b.slice(1), 16); const c = (s) => Math.round(((pa >> s) & 255) * (1 - t) + ((pb >> s) & 255) * t); return "rgb(" + c(16) + "," + c(8) + "," + c(0) + ")"; }

function updateUI(s) {
  document.title = s.title;
  setText("title", s.title);
  setText("homeName", s.teams.home); setText("awayName", s.teams.away);
  setText("scoreHome", s.score.home); setText("scoreAway", s.score.away);
  setText("clock", Math.floor(s.minute) + "'");
  setText("halfLabel", s.phase === "fulltime" ? "Abpfiff" : s.phase === "halftime" ? "Halbzeit" : s.half + ". Halbzeit");
  setText("refName", s.ref.name); setText("refQuirk", s.ref.quirk);
  setText("money", s.money);
  for (const k of ["patience", "mood", "suspicion", "crowd"]) {
    const v = s.meters[k];
    const i = $("m-" + k).querySelector("i");
    i.style.width = v + "%";
    i.style.background = mix(METER_COL[k][0], METER_COL[k][1], v / 100);
  }
  const st = s.stats;
  setText("stats", "Erfundene Regeln: " + st.rules + "  |  Karten: " + st.cards + "  |  Bestechungen: " + st.bribes + "  |  Schwalben: " + st.dives);
  const badge = $("llmBadge");
  const rs = s.ref_status;
  if (rs.mode === "ollama") { badge.textContent = "Ollama: " + rs.model; badge.className = "badge ok"; }
  else if (rs.mode === "offline") { badge.textContent = "Notbetrieb (kein Ollama)"; badge.className = "badge off"; badge.title = rs.note || ""; }
  else { badge.textContent = "Ollama: " + rs.model + " (noch ungetestet)"; badge.className = "badge"; }
  $("ruleCount").textContent = s.rules.length;
  const keep = new Set(s.rules.map((r) => String(r.id)));
  for (const el of Array.from($("rules").children)) {
    if (el.classList.contains("empty")) continue;
    if (!keep.has(el.dataset.id)) el.remove();
    else {
      const r = s.rules.find((x) => String(x.id) === el.dataset.id);
      let tt = el.querySelector(".tt");
      if (tt) tt.textContent = r.expires == null ? "bis Schluss" : (Math.max(0, Math.ceil(r.expires - s.minute)) + " Min noch");
    }
  }
  for (const r of s.rules) addRuleCard(r, false);
  const hasRules = Array.from($("rules").children).some((c) => c.classList.contains("rule"));
  const empty = $("rules").querySelector(".empty");
  if (!hasRules && !empty) $("rules").innerHTML = "<div class='empty'>Noch keine Regeln. Der Schiri erfindet sie, sobald du ihn provozierst, bestichst oder er einfach Lust hat.</div>";
  if (hasRules && empty) empty.remove();
  // Vorfall-Karte
  const inc = $("incident");
  if (s.phase === "appeal" || s.phase === "deciding" || s.phase === "decided") {
    inc.classList.remove("hidden");
    inc.classList.toggle("decided", s.phase === "decided");
    inc.classList.toggle("think", s.phase === "deciding");
    if (s.phase === "appeal") {
      $("incTag").textContent = "PFIFF - DU HAST NOCH " + Math.ceil(s.phase_t) + " S";
      $("incText").textContent = s.incident ? s.incident.text : "";
      $("incBar").style.width = (s.phase_t / s.appeal_total * 100) + "%";
    } else if (s.phase === "deciding") {
      $("incTag").textContent = "DER SCHIRI ÜBERLEGT" + ".".repeat(1 + Math.floor(performance.now() / 350) % 3);
      $("incText").textContent = s.incident ? s.incident.text : "";
      $("incBar").style.width = "100%";
    } else {
      $("incTag").textContent = "ENTSCHEIDUNG - PROTESTIEREN?";
      $("incText").textContent = decisionText(s);
      $("incBar").style.width = Math.min(100, s.phase_t / s.protest_total * 100) + "%";
    }
  } else inc.classList.add("hidden");
  // Buttons
  const busy = s.ref.busy || s.phase === "deciding";
  const blocked = busy || s.phase === "halftime" || s.phase === "fulltime";
  for (const b of $("actions").children) {
    let dis = blocked;
    if (b.dataset.act === "dive") dis = s.phase !== "play" || s.ref.busy;
    b.disabled = dis;
  }
  $("sayInput").placeholder = busy ? "Der Schiri denkt nach ..." : "Sag dem Schiri was ... (Enter zum Senden)";
  // Ende
  if (s.phase === "fulltime") {
    $("endOverlay").classList.remove("hidden");
    $("endScore").textContent = s.score.home + " : " + s.score.away;
    const res = s.score.home > s.score.away ? "Gewonnen!" : s.score.home < s.score.away ? "Verloren." : "Unentschieden.";
    $("endLines").textContent = res + " Regeln erfunden: " + st.rules + ", Karten: " + st.cards + ", ausgegebenes Schmiergeld: " + st.money_spent + " €.";
  } else $("endOverlay").classList.add("hidden");
}

function decisionText(s) {
  const o = s.outcome; if (!o) return "";
  const n = o.team === "home" || o.team === "away" ? s.teams[o.team] : "";
  return { play_on: "Weiterspielen", free_kick: "Freistoß für " + n, penalty: "ELFMETER für " + n, goal_ok: "Das Tor zählt", goal_disallowed: "Das Tor zählt NICHT",
    award_goal: "Tor für " + n + " - einfach so", drop_ball: "Schiedsrichterball" }[o.decision] || "";
}

// ---------------------------------------------------------------- Zeichnen
function frame(now) {
  requestAnimationFrame(frame);
  if (!S) return;
  const dt = Math.min(0.05, (now - (frame.last || now)) / 1000); frame.last = now;
  update(dt, now / 1000);
  draw(now / 1000);
  placeBubble();
}

function update(dt, t) {
  const k = 1 - Math.pow(0.0004, dt);
  for (const p of S.players) {
    const d = disp[p.id] || (disp[p.id] = { x: p.x, y: p.y, run: 0 });
    const dx = p.x - d.x, dy = p.y - d.y;
    if (Math.abs(dx) > 25 || Math.abs(dy) > 25) { d.x = p.x; d.y = p.y; }
    d.x += dx * k; d.y += dy * k;
    d.run += Math.hypot(dx, dy) * 0.9;
    d.vx = dx; d.vy = dy;
  }
  const bk = 1 - Math.pow(0.00002, dt);
  const bx = S.ball.x, by = S.ball.y;
  if (Math.abs(bx - ball.x) > 30) { ball.x = bx; ball.y = by; }
  ball.x += (bx - ball.x) * bk; ball.y += (by - ball.y) * bk;
  ball.trail.push({ x: ball.x, y: ball.y }); if (ball.trail.length > 12) ball.trail.shift();
  ball.rot = (ball.rot || 0) + Math.hypot(S.ball.x - ball.x, S.ball.y - ball.y) * 0.8 + 0.02;
  const rk = 1 - Math.pow(0.01, dt);
  refPos.x += (S.ref.x - refPos.x) * rk; refPos.y += (S.ref.y - refPos.y) * rk;
  shake = Math.max(0, shake - dt * 1.8); flashRed = Math.max(0, flashRed - dt * 0.9); goalGlow = Math.max(0, goalGlow - dt);
  for (const p of particles) {
    if (p.kind === "conf") { p.vy += 55 * dt; p.x += p.vx * dt; p.y += p.vy * dt; p.vx *= 0.99; p.rot += p.vr * dt; }
    p.life -= dt; if (p.kind === "bill") p.t += dt;
  }
  particles = particles.filter((p) => p.life > 0);
  for (const f of floaters) { f.life -= dt; f.y -= dt * 3; }
  floaters = floaters.filter((f) => f.life > 0);
  for (const r of rings) { r.r += dt * 26; r.life -= dt * 1.1; }
  rings = rings.filter((r) => r.life > 0);
  for (const c of chants) c.life -= dt;
  chants = chants.filter((c) => c.life > 0);
  if (S.streaker) {
    const st = S.streaker; st.sx = (st.dir > 0 ? -6 + st.t * 24 : W + 6 - st.t * 24);
  }
}

function draw(t) {
  const g = ctx;
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, cw, ch);
  g.save();
  if (shake > 0) g.translate((Math.random() - 0.5) * shake * 10, (Math.random() - 0.5) * shake * 10);
  drawBackground(g, t);
  drawCrowd(g, t);
  drawPitch(g);
  drawGoals(g);
  drawIncidentMarker(g, t);
  const list = S.players.filter((p) => !p.red).sort((a, b) => a.y - b.y);
  for (const p of list) drawShadow(g, p);
  for (const p of list) drawPlayer(g, p, t);
  if (S.streaker) drawStreaker(g, t);
  drawBall(g, t);
  drawRef(g, t);
  drawFx(g, t);
  g.restore();
  if (flashRed > 0) { g.fillStyle = "rgba(255,30,60," + (flashRed * 0.35) + ")"; g.fillRect(0, 0, cw, ch); }
  if (goalGlow > 0) { g.fillStyle = "rgba(255,210,63," + (goalGlow * 0.12) + ")"; g.fillRect(0, 0, cw, ch); }
}

function drawBackground(g, t) {
  const gr = g.createLinearGradient(0, 0, 0, ch);
  gr.addColorStop(0, "#0a1230"); gr.addColorStop(1, "#050914");
  g.fillStyle = gr; g.fillRect(0, 0, cw, ch);
  // Flutlichter
  for (const [lx, ly] of [[X(-6), Y(-7)], [X(W + 6), Y(-7)], [X(-6), Y(H + 7)], [X(W + 6), Y(H + 7)]]) {
    const rg = g.createRadialGradient(lx, ly, 0, lx, ly, sx * 28);
    rg.addColorStop(0, "rgba(255,248,214,0.45)"); rg.addColorStop(0.15, "rgba(255,248,214,0.14)"); rg.addColorStop(1, "rgba(255,248,214,0)");
    g.fillStyle = rg; g.fillRect(0, 0, cw, ch);
  }
}

function drawCrowd(g, t) {
  const e = S.meters.crowd / 100;
  const cols = [["#ff3d5a", "#c9304a"], ["#3db7ff", "#2a86c0"]];
  for (const d of crowdDots) {
    const jump = Math.max(0, Math.sin(t * (3 + e * 6) + d.ph)) * e * 0.9 + (goalGlow > 0 ? Math.abs(Math.sin(t * 9 + d.ph)) * 0.9 : 0);
    let x = d.x, y = d.y;
    if (d.side === "t") y -= jump; else if (d.side === "b") y += jump; else if (d.side === "l") x -= jump; else x += jump;
    g.fillStyle = d.h < 0.18 ? "#e8d9bd" : cols[d.c][d.h < 0.6 ? 0 : 1];
    g.beginPath(); g.arc(X(x), Y(y), sx * 0.52, 0, 6.3); g.fill();
    if (d.h > 0.97 && e > 0.55 && Math.sin(t * 12 + d.ph * 5) > 0.93) { g.fillStyle = "rgba(255,255,255,.9)"; g.beginPath(); g.arc(X(x), Y(y), sx * 1.2, 0, 6.3); g.fill(); }
  }
  // Werbebanden
  const bands = [["#101a38", -1.5, "top"], ["#101a38", H + 0.5, "bot"]];
  g.fillStyle = "#0d1430";
  g.fillRect(X(-1.6), Y(-1.6), sx * (W + 3.2), sx * 1.1);
  g.fillRect(X(-1.6), Y(H + 0.5), sx * (W + 3.2), sx * 1.1);
  g.font = "700 " + sx * 0.8 + "px sans-serif"; g.textAlign = "left"; g.fillStyle = "#3b4d86";
  const ads = ["ABSEITS", "BETONMISCHER", "DORFKANTE", "KEINE REGELN", "SCHIRI-BANK", "ABSEITS"];
  for (let i = 0; i < 6; i++) {
    g.fillText(ads[i], X(2 + i * 17.5), Y(-0.72));
    g.fillText(ads[(i + 2) % 6], X(2 + i * 17.5), Y(H + 1.3));
  }
  for (const c of chants) {
    g.globalAlpha = Math.min(1, c.life * 1.5);
    g.font = "800 " + sx * 1.35 + "px sans-serif"; g.textAlign = "center"; g.fillStyle = "#fff";
    g.strokeStyle = "#000a"; g.lineWidth = 4;
    const y = c.side === "t" ? -4.5 : H + 5;
    g.strokeText(c.text, X(W / 2), Y(y)); g.fillText(c.text, X(W / 2), Y(y));
    g.globalAlpha = 1;
  }
}

function drawPitch(g) {
  const n = 14, sw = W / n;
  for (let i = 0; i < n; i++) {
    g.fillStyle = i % 2 ? "#1e7a3c" : "#238f45";
    g.fillRect(X(i * sw) - 0.5, Y(0), sx * sw + 1, sx * H);
  }
  const sheen = g.createLinearGradient(0, Y(0), 0, Y(H));
  sheen.addColorStop(0, "rgba(255,255,255,.07)"); sheen.addColorStop(0.5, "rgba(255,255,255,0)"); sheen.addColorStop(1, "rgba(0,0,0,.22)");
  g.fillStyle = sheen; g.fillRect(X(0), Y(0), sx * W, sx * H);
  g.strokeStyle = "rgba(255,255,255,.85)"; g.lineWidth = Math.max(1.5, sx * 0.14);
  g.strokeRect(X(0), Y(0), sx * W, sx * H);
  g.beginPath(); g.moveTo(X(W / 2), Y(0)); g.lineTo(X(W / 2), Y(H)); g.stroke();
  g.beginPath(); g.arc(X(W / 2), Y(H / 2), sx * 9.15, 0, 6.3); g.stroke();
  g.fillStyle = "rgba(255,255,255,.85)"; g.beginPath(); g.arc(X(W / 2), Y(H / 2), sx * 0.35, 0, 6.3); g.fill();
  for (const side of [0, 1]) {
    const bx = side ? W - 16.5 : 0;
    g.strokeRect(X(bx), Y(H / 2 - 20.15), sx * 16.5, sx * 40.3);
    const sx2 = side ? W - 5.5 : 0;
    g.strokeRect(X(sx2), Y(H / 2 - 9.16), sx * 5.5, sx * 18.32);
    const spot = side ? W - 11 : 11;
    g.beginPath(); g.arc(X(spot), Y(H / 2), sx * 0.3, 0, 6.3); g.fill();
    g.beginPath(); g.arc(X(spot), Y(H / 2), sx * 9.15, side ? 2.2 : -0.94, side ? 4.08 : 0.94); g.stroke();
  }
}

function drawGoals(g) {
  const leftTeam = S.flipped ? "away" : "home", rightTeam = S.flipped ? "home" : "away";
  const half = (team) => 3.66 * S.mods.goal_size[team];
  for (const [team, side] of [[leftTeam, 0], [rightTeam, 1]]) {
    const gh = half(team), x0 = side ? W : 0, dirx = side ? 1 : -1;
    const y0 = H / 2 - gh, y1 = H / 2 + gh;
    g.fillStyle = "rgba(255,255,255,.10)";
    g.fillRect(Math.min(X(x0), X(x0 + dirx * 2.4)), Y(y0), sx * 2.4, sx * gh * 2);
    g.strokeStyle = "rgba(255,255,255,.35)"; g.lineWidth = 1;
    for (let i = 0; i <= 8; i++) { const yy = y0 + (y1 - y0) * i / 8; g.beginPath(); g.moveTo(X(x0), Y(yy)); g.lineTo(X(x0 + dirx * 2.4), Y(yy)); g.stroke(); }
    for (let i = 1; i <= 3; i++) { g.beginPath(); g.moveTo(X(x0 + dirx * i * 0.8), Y(y0)); g.lineTo(X(x0 + dirx * i * 0.8), Y(y1)); g.stroke(); }
    g.strokeStyle = COLORS[team]; g.lineWidth = Math.max(2.5, sx * 0.28);
    g.beginPath(); g.moveTo(X(x0), Y(y0)); g.lineTo(X(x0 + dirx * 2.4), Y(y0)); g.lineTo(X(x0 + dirx * 2.4), Y(y1)); g.lineTo(X(x0), Y(y1)); g.stroke();
    g.fillStyle = "#fff"; g.beginPath(); g.arc(X(x0), Y(y0), sx * 0.35, 0, 6.3); g.arc(X(x0), Y(y1), sx * 0.35, 0, 6.3); g.fill();
  }
}

function drawIncidentMarker(g, t) {
  if (!S.incident || !["appeal", "deciding", "decided"].includes(S.phase)) return;
  const x = X(S.incident.x), y = Y(S.incident.y);
  const pulse = 1 + Math.sin(t * 8) * 0.12;
  g.strokeStyle = S.phase === "decided" ? "#2ee59d" : "#ff3d5a"; g.lineWidth = 3; g.setLineDash([sx * 0.8, sx * 0.6]);
  g.beginPath(); g.arc(x, y, sx * 4 * pulse, t * 2, t * 2 + 6.3); g.stroke(); g.setLineDash([]);
}

function drawShadow(g, p) {
  const d = disp[p.id]; const sz = S.mods.player_size[p.team];
  g.fillStyle = "rgba(0,0,0,.28)";
  g.beginPath(); g.ellipse(X(d.x) + sx * 0.25, Y(d.y) + sx * 0.4 * sz, sx * 1.75 * sz, sx * 1.1 * sz, 0, 0, 6.3); g.fill();
}

function drawPlayer(g, p, t) {
  const d = disp[p.id]; const sz = S.mods.player_size[p.team];
  const x = X(d.x), y = Y(d.y), r = sx * 1.55 * sz;
  const col = COLORS[p.team];
  const bob = Math.sin(d.run * 1.3) * (Math.hypot(d.vx || 0, d.vy || 0) > 0.02 ? sx * 0.12 : 0);
  g.save(); g.translate(x, y + bob);
  if (p.down) {
    g.rotate(1.2); g.scale(1.2, 0.7);
  }
  // Beine
  g.fillStyle = "#f1f1f1";
  const leg = Math.sin(d.run * 1.3) * r * 0.5;
  g.beginPath(); g.ellipse(-r * 0.4, r * 0.85 + leg, r * 0.24, r * 0.4, 0, 0, 6.3); g.ellipse(r * 0.4, r * 0.85 - leg, r * 0.24, r * 0.4, 0, 0, 6.3); g.fill();
  // Trikot
  const grad = g.createLinearGradient(-r, -r, r, r);
  grad.addColorStop(0, lighten(col, 0.25)); grad.addColorStop(1, col);
  g.fillStyle = grad; g.strokeStyle = "#0a0f1e"; g.lineWidth = Math.max(1.5, sx * 0.12);
  g.beginPath(); g.arc(0, 0, r, 0, 6.3); g.fill(); g.stroke();
  // Kopf
  g.fillStyle = "#f0c8a0";
  g.beginPath(); g.arc(p.face * r * 0.3, -r * 0.55, r * 0.42, 0, 6.3); g.fill(); g.stroke();
  g.fillStyle = "#2a1a10"; g.beginPath(); g.arc(p.face * r * 0.3, -r * 0.7, r * 0.4, 3.3, 6.1); g.fill();
  // Nummer
  g.fillStyle = "#fff"; g.font = "900 " + Math.max(9, r * 0.95) + "px sans-serif"; g.textAlign = "center"; g.textBaseline = "middle";
  g.fillText(p.n, 0, r * 0.28);
  g.restore();
  // Kapitän
  if (p.id === "h4") {
    g.strokeStyle = "#ffd23f"; g.lineWidth = 2.5; g.globalAlpha = 0.65 + Math.sin(t * 5) * 0.3;
    g.beginPath(); g.arc(x, y, r * 1.45, 0, 6.3); g.stroke(); g.globalAlpha = 1;
    g.fillStyle = "#ffd23f"; g.font = "800 " + sx * 0.8 + "px sans-serif"; g.textAlign = "center"; g.fillText("DU", x, y - r * 1.9);
  }
  if (p.yc) { g.fillStyle = "#ffe14d"; g.fillRect(x + r * 0.9, y - r * 1.3, sx * 0.6, sx * 0.85); }
  if (p.frozen) {
    g.strokeStyle = "#9ee7ff"; g.lineWidth = 3; g.fillStyle = "rgba(160,230,255,.4)";
    g.beginPath(); g.arc(x, y, r * 1.25, 0, 6.3); g.fill(); g.stroke();
  }
  if (p.down) {
    g.fillStyle = "#ffe14d"; g.font = "800 " + sx * 1.1 + "px sans-serif"; g.textAlign = "center";
    for (let i = 0; i < 3; i++) { const a = t * 5 + i * 2.1; g.fillText("*", x + Math.cos(a) * r * 1.2, y - r * 1.2 + Math.sin(a) * r * 0.4); }
  }
}
function lighten(hex, a) { const n = parseInt(hex.slice(1), 16); const c = (s) => Math.min(255, Math.round(((n >> s) & 255) + 255 * a)); return "rgb(" + c(16) + "," + c(8) + "," + c(0) + ")"; }

function drawStreaker(g, t) {
  const st = S.streaker; const x = st.sx, y = st.y;
  const px = X(x), py = Y(y), r = sx * 1.2;
  g.fillStyle = "rgba(0,0,0,.25)"; g.beginPath(); g.ellipse(px, py + r * 0.9, r, r * 0.5, 0, 0, 6.3); g.fill();
  g.fillStyle = "#f0c8a0"; g.strokeStyle = "#0a0f1e"; g.lineWidth = 2;
  g.beginPath(); g.arc(px, py, r, 0, 6.3); g.fill(); g.stroke();
  g.fillStyle = "#222"; g.beginPath(); g.arc(px + st.dir * r * 0.3, py - r * 0.7, r * 0.5, 0, 6.3); g.fill();
  g.fillStyle = "#fff"; g.font = "800 " + sx * 1 + "px sans-serif"; g.textAlign = "center"; g.fillText("FLITZER", px, py - r * 2);
}

function drawBall(g, t) {
  const sz = S.ball.size; const r = sx * 0.8 * sz;
  for (let i = 0; i < ball.trail.length; i++) {
    const a = i / ball.trail.length; const q = ball.trail[i];
    g.fillStyle = "rgba(255,255,255," + a * 0.18 + ")";
    g.beginPath(); g.arc(X(q.x), Y(q.y), r * a, 0, 6.3); g.fill();
  }
  const x = X(ball.x), y = Y(ball.y);
  g.fillStyle = "rgba(0,0,0,.35)"; g.beginPath(); g.ellipse(x + r * 0.4, y + r * 0.8, r, r * 0.5, 0, 0, 6.3); g.fill();
  g.save(); g.translate(x, y); g.rotate(ball.rot || 0);
  const gr = g.createRadialGradient(-r * 0.3, -r * 0.3, 0, 0, 0, r);
  gr.addColorStop(0, "#fff"); gr.addColorStop(1, "#cfd6e6");
  g.fillStyle = gr; g.strokeStyle = "#111"; g.lineWidth = Math.max(1.2, r * 0.12);
  g.beginPath(); g.arc(0, 0, r, 0, 6.3); g.fill(); g.stroke();
  g.fillStyle = "#111";
  g.beginPath(); for (let i = 0; i < 5; i++) { const a = i * 1.2566 - 1.57; g.lineTo(Math.cos(a) * r * 0.42, Math.sin(a) * r * 0.42); } g.closePath(); g.fill();
  for (let i = 0; i < 5; i++) { const a = i * 1.2566 - 1.57; g.beginPath(); g.arc(Math.cos(a) * r * 0.85, Math.sin(a) * r * 0.85, r * 0.17, 0, 6.3); g.fill(); }
  g.restore();
}

function drawRef(g, t) {
  const x = X(refPos.x), y = Y(refPos.y), r = sx * 1.8;
  const think = S.ref.busy || S.phase === "deciding";
  g.fillStyle = "rgba(0,0,0,.3)"; g.beginPath(); g.ellipse(x + r * 0.2, y + r * 0.9, r * 1.1, r * 0.6, 0, 0, 6.3); g.fill();
  if (S.phase === "appeal" || think) {
    g.strokeStyle = think ? "#ffd23f" : "#ff3d5a"; g.lineWidth = 3; g.globalAlpha = 0.5 + Math.sin(t * 9) * 0.4;
    g.beginPath(); g.arc(x, y, r * 1.7, 0, 6.3); g.stroke(); g.globalAlpha = 1;
  }
  g.fillStyle = "#16161c"; g.strokeStyle = "#ffe14d"; g.lineWidth = Math.max(2, sx * 0.2);
  g.beginPath(); g.arc(x, y, r, 0, 6.3); g.fill(); g.stroke();
  g.fillStyle = "#ffe14d";
  g.fillRect(x - r * 0.9, y - r * 0.12, r * 1.8, r * 0.24);
  g.fillStyle = "#f0c8a0"; g.beginPath(); g.arc(x, y - r * 0.62, r * 0.45, 0, 6.3); g.fill(); g.stroke();
  g.fillStyle = "#111"; g.beginPath(); g.arc(x, y - r * 0.78, r * 0.43, 3.25, 6.17); g.fill();
  g.fillStyle = "#ffe14d"; g.beginPath(); g.arc(x + r * 0.35, y - r * 0.5, r * 0.15, 0, 6.3); g.fill();
  g.fillStyle = "#ffe14d"; g.font = "900 " + sx * 0.85 + "px sans-serif"; g.textAlign = "center"; g.fillText("SCHIRI", x, y + r * 1.9);
}

function drawFx(g, t) {
  for (const r of rings) {
    if (r.r < 0) continue;
    g.strokeStyle = "rgba(255,255,255," + r.life * 0.8 + ")"; g.lineWidth = 3;
    g.beginPath(); g.arc(X(r.x), Y(r.y), r.r * sx, 0, 6.3); g.stroke();
  }
  for (const p of particles) {
    if (p.kind === "conf") {
      g.save(); g.translate(X(p.x), Y(p.y)); g.rotate(p.rot); g.fillStyle = p.c; g.globalAlpha = Math.min(1, p.life);
      g.fillRect(-sx * p.w / 2, -sx * 0.25, sx * p.w, sx * 0.5); g.restore(); g.globalAlpha = 1;
    } else if (p.kind === "bill" && p.t > 0) {
      const k = Math.min(1, p.t / 0.8); const e = k * k * (3 - 2 * k);
      const x = p.x + (p.tx - p.x) * e, y = p.y + (p.ty - p.y) * e - Math.sin(e * 3.14) * 9;
      g.save(); g.translate(X(x), Y(y)); g.rotate(p.rot + k * 6);
      g.fillStyle = "#2ee59d"; g.strokeStyle = "#0a5a3c"; g.lineWidth = 1.5;
      g.fillRect(-sx * 0.9, -sx * 0.5, sx * 1.8, sx * 1); g.strokeRect(-sx * 0.9, -sx * 0.5, sx * 1.8, sx * 1);
      g.fillStyle = "#0a5a3c"; g.font = "800 " + sx * 0.7 + "px sans-serif"; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText("€", 0, 0);
      g.restore();
    }
  }
  for (const f of floaters) {
    g.globalAlpha = Math.min(1, f.life / f.max * 2);
    g.font = "900 " + sx * f.size + "px sans-serif"; g.textAlign = "center"; g.textBaseline = "alphabetic";
    g.strokeStyle = "#000b"; g.lineWidth = 5; g.strokeText(f.text, X(f.x), Y(f.y)); g.fillStyle = f.color; g.fillText(f.text, X(f.x), Y(f.y));
    g.globalAlpha = 1;
  }
}

function placeBubble() {
  const b = $("bubble");
  const say = S.ref.say;
  const think = S.ref.busy || S.phase === "deciding";
  const text = think ? "Hmm ..." : say;
  if (!text) { b.classList.add("hidden"); return; }
  if (b.dataset.t !== text) { b.textContent = text; b.dataset.t = text; }
  b.classList.toggle("think", think);
  b.classList.remove("hidden");
  const rect = canvas.getBoundingClientRect();
  const bx = Math.min(Math.max(X(refPos.x), 150), rect.width - 150);
  b.style.left = bx + "px";
  b.style.top = Math.max(120, Y(refPos.y) - sx * 2.6) + "px";
}

// ---------------------------------------------------------------- Ton
let audio = null, master = null, crowdGain = null, soundOn = false;
function initAudio() {
  if (audio) return;
  try {
    audio = new (window.AudioContext || window.webkitAudioContext)();
    master = audio.createGain(); master.gain.value = 0; master.connect(audio.destination);
    const buf = audio.createBuffer(1, audio.sampleRate * 2, audio.sampleRate);
    const d = buf.getChannelData(0); for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
    const src = audio.createBufferSource(); src.buffer = buf; src.loop = true;
    const f = audio.createBiquadFilter(); f.type = "bandpass"; f.frequency.value = 500; f.Q.value = 0.6;
    crowdGain = audio.createGain(); crowdGain.gain.value = 0.02;
    src.connect(f); f.connect(crowdGain); crowdGain.connect(master); src.start();
  } catch (e) { audio = null; }
}
function sfx(kind) {
  if (!audio || !soundOn) return;
  const t0 = audio.currentTime;
  const tone = (type, f0, f1, dur, vol, delay) => {
    const o = audio.createOscillator(), g = audio.createGain();
    o.type = type; o.frequency.setValueAtTime(f0, t0 + (delay || 0)); if (f1) o.frequency.exponentialRampToValueAtTime(f1, t0 + (delay || 0) + dur);
    g.gain.setValueAtTime(0.0001, t0 + (delay || 0)); g.gain.exponentialRampToValueAtTime(vol, t0 + (delay || 0) + 0.02); g.gain.exponentialRampToValueAtTime(0.0001, t0 + (delay || 0) + dur);
    o.connect(g); g.connect(master); o.start(t0 + (delay || 0)); o.stop(t0 + (delay || 0) + dur + 0.05);
  };
  if (kind === "whistle") { tone("square", 2900, 3100, 0.35, 0.14); tone("square", 3050, 2950, 0.3, 0.1, 0.4); }
  else if (kind === "horn") { tone("sawtooth", 220, 200, 0.9, 0.2); tone("sawtooth", 277, 250, 0.9, 0.12); }
  else if (kind === "buzz") { tone("sawtooth", 120, 80, 0.5, 0.2); }
  else if (kind === "magic") { [523, 659, 784, 1046].forEach((f, i) => tone("triangle", f, f, 0.25, 0.12, i * 0.08)); }
  else tone("triangle", 660, 440, 0.15, 0.1);
}
function setSound(on) {
  soundOn = on; initAudio();
  $("soundBtn").textContent = "Ton: " + (on ? "an" : "aus");
  if (master) master.gain.setTargetAtTime(on ? 0.6 : 0, audio.currentTime, 0.05);
  if (on && audio && audio.state === "suspended") audio.resume();
}
setInterval(() => { if (crowdGain && S && soundOn) crowdGain.gain.setTargetAtTime(0.015 + S.meters.crowd / 100 * 0.1, audio.currentTime, 0.4); }, 400);

// ---------------------------------------------------------------- Bedienung
$("soundBtn").onclick = () => setSound(!soundOn);
$("newGame").onclick = () => fetch("/api/new", { method: "POST", body: "{}" });
for (const b of $("chips").children) b.onclick = () => { amount = +b.dataset.amt; for (const c of $("chips").children) c.classList.toggle("on", c === b); };
for (const b of $("actions").children) {
  b.onclick = () => {
    const kind = b.dataset.act;
    let text = $("sayInput").value.trim();
    if (!text && ACTION_DEFAULTS[kind]) { const l = ACTION_DEFAULTS[kind]; text = kind === "rule" ? "" : l[Math.floor(Math.random() * l.length)]; }
    if (kind === "rule" && !text) { const l = ACTION_DEFAULTS.rule; text = l[Math.floor(Math.random() * l.length)]; }
    act(kind, text, kind === "bribe" ? amount : 0);
  };
}
$("sayInput").addEventListener("keydown", (e) => {
  if (e.key !== "Enter") return;
  const text = e.target.value.trim(); if (!text) return;
  act(S && (S.phase === "appeal" || S.phase === "decided") ? "protest" : "chat", text, 0);
});

resize();
requestAnimationFrame(frame);
poll();
