"use strict";
// Control Center (cc-shell): zeigt den UI-Vertrag v1. Ereignisse per SSE, Befehle per POST. Kein Fremdcode, keine externen Adressen.
const params = new URLSearchParams(location.search);
const token = params.get("t") || "";
// Zustaende des UI-Vertrags (schema.STATES). Das Aussehen steht in core_states.json (Tabelle); ein Zustand wird nur gezeigt, wenn das Backend ihn meldet.
const KNOWN_STATES = ["ready", "listening", "processing", "speaking", "awaiting_confirmation", "error", "emergency"];
// Grenzen der Tabellenwerte (die Tests pruefen die Datei gegen dieselben Werte; hier wird zusaetzlich geklemmt).
const LIMITS = { glow: [0, 1], pulse_hz: [0, 2], pulse_amp: [0, 0.08], spin: [0, 2], rings: [0, 3], particles: [0, 24], level_gain: [0, 0.2], flash_hz: [0, 3] };
const NEUTRAL = { label: "kein Zustand gemeldet", color: "#6b7686", glow: 0.12, pulse_hz: 0, pulse_amp: 0, spin: 0, rings: 0, particles: 0, level_gain: 0, flash_hz: 0 };
const MAX_LIST = 200;
let lastSeq = 0;
let source = null;
let counter = 0;
let level = 0;
let currentState = null;  // null = das Backend hat (noch) keinen Zustand gemeldet
let coreTable = null;
const reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const el = (id) => document.getElementById(id);

function url(path, since) {
  const q = new URLSearchParams({ t: token });
  if (since) q.set("since", String(since));
  return path + "?" + q.toString();
}

// Der Anzeigemodus (Orb/Dashboard) ist rein lokal: er aendert nur ein Attribut und sendet nichts.
function setMode(mode) {
  document.body.dataset.mode = mode === "dashboard" ? "dashboard" : "orb";
  el("mode-toggle").textContent = document.body.dataset.mode === "orb" ? "Dashboard" : "Orb";
  redraw();
}

function addItem(list, text, cls) {
  const li = document.createElement("li");
  li.textContent = text;
  if (cls) li.className = cls;
  list.appendChild(li);
  while (list.children.length > MAX_LIST) list.removeChild(list.firstChild);
  list.scrollTop = list.scrollHeight;
}

// state: Zustand aus einem Backend-Ereignis oder null (unbekannt, z. B. nach Verbindungsverlust). Unbekannte Werte werden nicht gezeigt und nicht durch einen anderen ersetzt.
function setState(state, detail) {
  currentState = KNOWN_STATES.includes(state) ? state : null;
  document.body.dataset.state = currentState || "none";
  el("state-label").textContent = look(currentState).label + (currentState && detail ? ": " + detail : "");
  el("orb-caption").textContent = currentState && detail ? detail : "";
  renderVoice();
  drawWave();
  redraw();
}

// ---- Dashboard (cc-dashboard): Aufgaben, Agenten, Ergebnisse. Nur Vertragsdaten; jeder Text wird mit textContent gesetzt, nie als HTML/Link. -----------------
const FINAL = new Set(["SUCCEEDED", "FAILED", "CANCELLED", "BLOCKED"]);
const MIN_PLANNED_STEPS = 3;  // automatischer Wechsel nur bei mindestens drei belegbaren geplanten Schritten (activity kind=plan, noch aktiv) ...
const MIN_AGENTS = 2;         // ... oder mindestens zwei belegbar beteiligten Agenten (routing zu noch aktiven Aufgaben). Der Vertrag liefert keine weiteren Komplexitaetsdaten.
const tasks = new Map();       // "kind:id" -> Aufgabe
const routes = new Map();      // task_id -> {agent, source, reason}
const results = new Map();     // task_id -> {summary, artifacts}
const cancelNotes = new Map(); // "kind:id" -> Text der echten Backend-Antwort
let selected = null;
let manualMode = false;        // wer selbst umgeschaltet hat, wird nie automatisch umgeschaltet

function taskKey(kind, id) { return kind + ":" + id; }
function isFinal(t) { return FINAL.has(String(t.status).toUpperCase()); }

function upsertTask(kind, id, patch) {
  const key = taskKey(kind, id);
  const t = tasks.get(key) || { kind: kind, id: id, title: id, status: "", note: "", detail: "", cancellable: false, listed: false };
  Object.assign(t, patch);
  tasks.set(key, t);
  if (!selected) selected = key;
  return t;
}

function renderActivity(d) {
  const listed = new Set();
  for (const it of d.items) {
    listed.add(taskKey(it.kind, it.id));
    upsertTask(it.kind, it.id, { title: it.title, status: it.status, note: it.note, cancellable: it.cancellable, listed: true });
  }
  for (const [key, t] of tasks) if (!listed.has(key)) { t.listed = false; t.cancellable = false; }  // nicht mehr in der Arbeitsliste: nicht abbrechbar
  el("problems").textContent = d.problems.length ? "Probleme: " + d.problems.map((p) => (typeof p === "string" ? p : JSON.stringify(p))).join("; ") : "";
  renderDashboard();
  maybeAutoSwitch();
}

function onTaskUpdate(d) {
  const t = upsertTask(d.kind, d.id, { status: d.status, detail: d.detail || "" });
  if (isFinal(t)) t.cancellable = false;
  renderDashboard();
}

function onRouting(d) { routes.set(d.task_id, { agent: d.agent, source: d.source, reason: d.reason }); renderDashboard(); maybeAutoSwitch(); }
function onResult(d) { results.set(d.task_id, { summary: d.summary, artifacts: d.artifacts }); renderDashboard(); }

function taskById(id) { for (const t of tasks.values()) if (t.id === id) return t; return null; }

function line(parent, label, value) {
  const p = document.createElement("div");
  p.textContent = label + ": " + value;
  parent.appendChild(p);
}

function renderTasks() {
  const ul = el("task-list");
  ul.replaceChildren();
  for (const [key, t] of tasks) {
    const li = document.createElement("li");
    li.className = (key === selected ? "sel " : "") + (isFinal(t) || !t.listed ? "final" : "");
    const pick = document.createElement("button");
    pick.type = "button";
    pick.textContent = t.title + " [" + t.status + "]";
    pick.addEventListener("click", () => { selected = key; renderDashboard(); });
    li.appendChild(pick);
    if (t.cancellable) {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = "Abbrechen";
      b.addEventListener("click", () => cancelTask(t.kind, t.id));
      li.appendChild(b);
    }
    if (cancelNotes.has(key)) {
      const n = document.createElement("div");
      n.className = "cancel-note";
      n.textContent = cancelNotes.get(key);
      li.appendChild(n);
    }
    ul.appendChild(li);
  }
}

function renderDetail() {
  const box = el("task-detail");
  box.replaceChildren();
  const t = tasks.get(selected);
  if (!t) { box.textContent = "keine Aufgabe gewaehlt"; return; }
  line(box, "Titel", t.title);
  line(box, "Art", t.kind);
  line(box, "Kennung", t.id);
  line(box, "Status", t.status);
  if (t.note) line(box, "Hinweis", t.note);
  if (t.detail) line(box, "Detail", t.detail);
  const r = routes.get(t.id);
  if (r) { line(box, "Agent", r.agent); line(box, "Zuordnung", r.source); line(box, "Grund", r.reason); }
  if (cancelNotes.has(selected)) line(box, "Abbruch", cancelNotes.get(selected));
}

function renderAgents() {
  const ul = el("agent-list");
  ul.replaceChildren();
  const byAgent = new Map();
  for (const [taskId, r] of routes) {
    const t = taskById(taskId);
    const e = byAgent.get(r.agent) || { total: 0, active: 0 };
    e.total += 1;
    if (t && !isFinal(t) && t.listed) e.active += 1;
    byAgent.set(r.agent, e);
  }
  for (const [agent, e] of byAgent) addItem(ul, agent + " - " + e.active + " aktiv, " + e.total + " zugeordnet");
  if (!byAgent.size) addItem(ul, "keine Agenten beteiligt");
}

function renderResults() {
  const ul = el("results-list");
  ul.replaceChildren();
  for (const [taskId, r] of results) {
    const li = document.createElement("li");
    const t = taskById(taskId);
    line(li, "Aufgabe", t ? t.title : taskId);
    line(li, "Zusammenfassung", r.summary);
    for (const a of r.artifacts) line(li, "Beleg (" + a.kind + ")", a.name + " - " + a.ref);  // Verweise sind reiner Text, nie ein Link
    ul.appendChild(li);
  }
  if (!results.size) addItem(ul, "noch keine Ergebnisse");
}

function renderDashboard() { renderTasks(); renderDetail(); renderAgents(); renderResults(); }

// Abbrechen: sendet nur `cancel` (kind, id) und zeigt die echte Antwort: abgebrochen, Abbruch angefordert oder abgelehnt (mit Code und Meldung des Backends).
function cancelText(ack) {
  if (!ack) return "abgelehnt: keine Antwort (getrennt)";
  if (!ack.ok) return "abgelehnt (" + ack.code + "): " + ack.message;
  return ack.code === "cancel_requested" ? "Abbruch angefordert" : "abgebrochen";
}

async function cancelTask(kind, id) {
  const ack = await send("cancel", { kind: kind, id: id });
  cancelNotes.set(taskKey(kind, id), cancelText(ack));
  renderDashboard();
}

// Automatischer Wechsel in das Dashboard: nur mit belegbaren Vertragsdaten (siehe MIN_*), nie nach manueller Wahl, nie zurueck zum Orb. Rein lokal.
function maybeAutoSwitch() {
  if (manualMode || document.body.dataset.mode === "dashboard") return;
  let planned = 0;
  const agents = new Set();
  for (const t of tasks.values()) {
    if (!t.listed || isFinal(t)) continue;
    if (t.kind === "plan") planned += 1;
    const r = routes.get(t.id);
    if (r) agents.add(r.agent);
  }
  if (planned >= MIN_PLANNED_STEPS || agents.size >= MIN_AGENTS) setMode("dashboard");
}

// ---- Rueckfragen (cc-confirmation) ------------------------------------------------------------------------------------------------------
// Standard ist Ablehnen: "deny" steht zuerst und hat den Fokus; Escape lehnt ab, Enter bestaetigt nie. Angeboten und sendbar ist nur, was die Anfrage selbst
// anbietet. Zeitablauf, Schliessen des Fensters und Verbindungsverlust gelten als abgelehnt (der Server schliesst dann die Anfrage).
const CHOICE_TEXT = { deny: "Ablehnen", allow_once: "Einmal erlauben", allow_session: "Fuer die Sitzung erlauben" };
const DENY_FIRST = ["deny", "allow_once", "allow_session"];
const pending = new Map();
let remainTimer = null;

function currentRequest() {
  const first = pending.values().next();
  return first.done ? null : first.value;
}

function answer(id, choice) {
  const q = pending.get(id);
  if (!q || !q.choices.includes(choice) || q.answered) return;  // nur Angebotenes ist sendbar
  q.answered = true;
  for (const b of el("dlg-choices").querySelectorAll("button")) b.disabled = true;
  send("confirm", { request_id: id, choice: choice });
}

function renderConfirmation() {
  const q = currentRequest();
  const dlg = el("confirm-dialog");
  el("confirmation").textContent = q ? q.tool + " / " + q.action + " (" + q.level + "): " + q.reason + (pending.size > 1 ? " [+" + (pending.size - 1) + " weitere]" : "") : "keine";
  if (!q) {
    dlg.hidden = true;
    if (remainTimer) { clearInterval(remainTimer); remainTimer = null; }
    return;
  }
  el("dlg-count").textContent = pending.size > 1 ? "Offene Rueckfragen: " + pending.size + " (diese zuerst)" : "";
  el("dlg-tool").textContent = q.tool;
  el("dlg-action").textContent = q.action;
  el("dlg-resource").textContent = q.resource;
  el("dlg-level").textContent = q.level;
  el("dlg-reason").textContent = q.reason;
  const ctx = el("dlg-context");
  ctx.replaceChildren();
  for (const c of q.context) addItem(ctx, c.key + ": " + c.value);
  const box = el("dlg-choices");
  box.replaceChildren();
  const offered = DENY_FIRST.filter((c) => q.choices.includes(c));
  for (const choice of offered) {
    const b = document.createElement("button");
    b.type = "button";
    b.dataset.choice = choice;
    b.textContent = CHOICE_TEXT[choice];
    b.addEventListener("click", () => answer(q.request_id, choice));
    box.appendChild(b);
  }
  dlg.hidden = false;
  updateRemaining();
  if (!remainTimer) remainTimer = setInterval(updateRemaining, 250);
  const first = box.querySelector("button");
  if (first && !q.answered) first.focus();  // der Fokus liegt auf Ablehnen
}

function updateRemaining() {
  const q = currentRequest();
  if (!q) return;
  const left = Math.max(0, Math.ceil((q.deadline - Date.now()) / 1000));
  el("dlg-remaining").textContent = left > 0 ? left + " s (danach abgelehnt)" : "abgelaufen - gilt als abgelehnt";
  if (left === 0) for (const b of el("dlg-choices").querySelectorAll("button")) b.disabled = true;
}

function openConfirmation(d) {
  pending.set(d.request_id, { request_id: d.request_id, tool: d.tool, action: d.action, resource: d.resource, level: d.level, reason: d.reason,
    context: d.context, choices: d.choices, deadline: Date.now() + d.timeout_s * 1000, answered: false });
  renderConfirmation();
}

function closeConfirmation(d) {
  pending.delete(d.request_id);
  renderConfirmation();
}

// Verbindungsverlust: der Server lehnt ab (detach); die Oberflaeche zeigt nichts Beantwortbares mehr an.
function clearConfirmations() {
  pending.clear();
  renderConfirmation();
}

document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  const q = currentRequest();
  if (q && q.choices.includes("deny")) answer(q.request_id, "deny");  // Escape lehnt ab, bestaetigt nie
});

function setEmergency(engaged) {
  el("emergency-banner").hidden = !engaged;
  emergencyOn = engaged === true;
  if (emergencyOn) { voiceActive = false; level = 0; waveHistory.length = 0; }  // der Notaus beendet den Sprachmodus: kein "Mikrofon an" anzeigen
  renderVoice();
  drawWave();
}

// ---- Sprache (cc-voice-viz): Pegel, Welle und Zustand nur aus voice_level- und state-Ereignissen des Backends. -------------------------------------------
// Das Mikrofon gehoert dem Backend; diese Seite sendet nur auf Knopfdruck start_voice/stop_voice und verarbeitet nie Audiodaten (kein Zugriff auf Mikrofon oder Audio-APIs).
// Die Statusanzeige (Text, Pegelbalken) bleibt auch bei ausgeschalteten Effekten lesbar; die Welle wird nur bei einem Ereignis neu gezeichnet, nie durch Zeitablauf.
const WAVE_POINTS = 48;
const VOICE_WORDS = { listening: "hoert zu", processing: "verarbeitet", speaking: "spricht" };
const waveHistory = [];
let voiceActive = null;  // null = das Backend hat (noch) nichts gemeldet
let emergencyOn = false;

function clamp01(v) { return Number.isFinite(v) ? Math.min(1, Math.max(0, v)) : 0; }

function renderVoice() {
  const mic = voiceActive === null ? "unbekannt" : voiceActive ? "an" : "aus";
  el("voice-mic").textContent = "Mikrofon: " + mic;
  document.body.dataset.voice = voiceActive === null ? "none" : voiceActive ? "on" : "off";
  el("voice-state").textContent = "Sprachzustand: " + (VOICE_WORDS[currentState] || "-");
  el("voice-meter").value = level;
  el("voice-level-text").textContent = voiceActive === true ? "Pegel " + Math.round(level * 100) + " %" : voiceActive === false ? "kein Pegel (Mikrofon aus)" : "kein Pegel gemeldet";
  el("voice-start").disabled = voiceActive === true || emergencyOn;
  el("voice-stop").disabled = voiceActive !== true;
}

function drawWave() {
  const c = el("voice-wave");
  const g = c.getContext("2d");
  const w = c.width || 240, h = c.height || 40, mid = h / 2;
  g.clearRect(0, 0, w, h);
  const color = look(currentState).color;
  g.strokeStyle = rgba(color, 0.9);
  g.fillStyle = rgba(color, 0.9);
  g.lineWidth = 2;
  if (effective() === "off") {  // ohne Effekte nur der aktuelle Pegel als ruhige Mittellinie, keine Verlaufswelle
    g.fillRect(0, mid - 1, w * level, 2);
    return;
  }
  g.beginPath();
  waveHistory.forEach((v, i) => {
    const x = (i / (WAVE_POINTS - 1)) * w;
    if (i === 0) g.moveTo(x, mid - v * mid); else g.lineTo(x, mid - v * mid);
  });
  for (let i = waveHistory.length - 1; i >= 0; i--) g.lineTo((i / (WAVE_POINTS - 1)) * w, mid + waveHistory[i] * mid);
  g.stroke();
}

function onVoiceLevel(d) {
  voiceActive = d.active === true;
  level = voiceActive ? clamp01(d.level) : 0;
  if (voiceActive) { waveHistory.push(level); while (waveHistory.length > WAVE_POINTS) waveHistory.shift(); } else { waveHistory.length = 0; }
  renderVoice();
  drawWave();
}

function resetVoice() {  // Verbindung verloren: der Mikrofonzustand ist unbekannt
  voiceActive = null;
  level = 0;
  waveHistory.length = 0;
  renderVoice();
  drawWave();
}

function handle(ev) {
  if (typeof ev.seq === "number") lastSeq = Math.max(lastSeq, ev.seq);
  addItem(el("log"), "#" + ev.seq + " " + ev.type);
  const d = ev.data;
  switch (ev.type) {
    case "state": setState(d.state, d.detail); break;
    case "chat": addItem(el("chat"), d.sender + ": " + d.text, d.sender); break;
    case "activity": renderActivity(d); break;
    case "task_update": onTaskUpdate(d); break;
    case "routing": onRouting(d); break;
    case "result": onResult(d); break;
    case "confirmation_request": openConfirmation(d); break;
    case "confirmation_closed": closeConfirmation(d); break;
    case "emergency": setEmergency(d.engaged); if (d.engaged) setState("emergency", d.reason); break;
    case "voice_level": onVoiceLevel(d); break;
    case "error": addItem(el("chat"), "Fehler " + d.code + ": " + d.message, "system"); break;
    case "ack": if (!d.ok) addItem(el("chat"), "Abgelehnt (" + d.code + "): " + d.message, "system"); break;
    default: break;
  }
}

function connect() {
  source = new EventSource(url("events", lastSeq));
  source.onopen = () => { document.body.dataset.conn = "open"; el("conn").textContent = "verbunden"; };
  source.onmessage = (m) => { try { handle(JSON.parse(m.data)); } catch (e) { /* ungueltiges Ereignis ignorieren */ } };
  source.onerror = () => {
    document.body.dataset.conn = "closed";
    setState(null);  // der letzte Zustand ist unbekannt, solange die Verbindung fehlt
    resetVoice();
    clearConfirmations();
    el("conn").textContent = "GETRENNT";
    if (source.readyState === EventSource.CLOSED) { source.close(); setTimeout(connect, 2000); }
  };
}

async function send(type, data) {
  counter += 1;
  const body = JSON.stringify({ v: "1.0", id: "ui" + Date.now().toString(36) + counter, type: type, data: data });
  try {
    const r = await fetch(url("command"), { method: "POST", headers: { "Content-Type": "application/json" }, body: body });
    const ack = await r.json();
    if (ack && ack.data && ack.data.ok === false && type !== "cancel") handle(ack);  // Abbruch-Antworten zeigt die Aufgabenliste selbst
    return ack && ack.data ? ack.data : null;
  } catch (e) {
    addItem(el("chat"), "Befehl nicht gesendet (getrennt)", "system");
    return null;
  }
}

// ---- Kern (cc-ai-core): Canvas 2D, Pseudo-3D-Kugel mit Meridianen, Ringen und Teilchen. Reine lokale Anzeige: sendet nichts. -----------------------------
// Effektstufen: full (alles, bewegt) > reduced (Kugel und Ringe, ca. 20 Bilder/s) > off (ein stehendes Bild). prefers-reduced-motion erzwingt off.
// Bei geringer Leistung (Bildzeit dauerhaft zu hoch) wird automatisch eine Stufe reduziert, nie wieder erhoeht; der Mensch kann jederzeit zuruecksetzen.
const RANK = { off: 0, reduced: 1, full: 2 };
let userEffects = "full";
let autoEffects = "full";
let rafId = 0;
let lastT = 0;
let ema = 16;
let slowFrames = 0;
const SLOW_FULL_MS = 45;      // Mittel ueber die Bildzeit; darueber (unter ca. 22 Bilder/s) zaehlt ein Bild als langsam
const SLOW_REDUCED_MS = 120;
const SLOW_LIMIT = 30;

function effective() {
  if (reduceMotion) return "off";
  return RANK[userEffects] <= RANK[autoEffects] ? userEffects : autoEffects;
}

function clamp(v, lo, hi) { return Math.min(hi, Math.max(lo, Number.isFinite(v) ? v : lo)); }

function sanitize(row) {
  if (!row || typeof row !== "object" || !/^#[0-9a-fA-F]{6}$/.test(row.color)) return null;
  const out = { label: typeof row.label === "string" ? row.label.slice(0, 40) : "", color: row.color };
  for (const k of Object.keys(LIMITS)) out[k] = clamp(Number(row[k]), LIMITS[k][0], LIMITS[k][1]);
  out.rings = Math.round(out.rings);
  out.particles = Math.round(out.particles);
  return out;
}

// Aussehen eines gemeldeten Zustands; ohne Zustand oder ohne (gueltige) Tabelle: neutral. Der Name des Zustands bleibt in der Beschriftung erhalten.
function look(state) {
  if (!state) return NEUTRAL;
  const row = coreTable && coreTable.states ? sanitize(coreTable.states[state]) : null;
  if (row) return row;
  return Object.assign({}, NEUTRAL, { label: state });
}

function rgba(hex, a) {
  return "rgba(" + parseInt(hex.slice(1, 3), 16) + "," + parseInt(hex.slice(3, 5), 16) + "," + parseInt(hex.slice(5, 7), 16) + "," + clamp(a, 0, 1).toFixed(3) + ")";
}

function ring(g, c, r, k, time, s, half) {
  const rx = r * (1.45 + 0.2 * k), ry = rx * 0.32;
  g.save();
  g.translate(c.x, c.y);
  g.rotate((k % 2 ? -1 : 1) * s.spin * time * 0.5 + k * 0.9);
  g.strokeStyle = rgba(s.color, half === "back" ? 0.25 : 0.7);
  g.lineWidth = 2;
  g.beginPath();
  if (half === "back") g.ellipse(0, 0, rx, ry, 0, Math.PI, 2 * Math.PI); else g.ellipse(0, 0, rx, ry, 0, 0, Math.PI);
  g.stroke();
  return { rx: rx, ry: ry };
}

function drawCore(t, c, quality) {
  const g = c.getContext("2d");
  const w = c.width || 480, h = c.height || 480, cx = w / 2, cy = h / 2;
  g.clearRect(0, 0, w, h);
  const s = look(currentState);
  const animated = quality !== "off";
  const time = animated ? t / 1000 : 0;
  const pulse = animated ? Math.sin(2 * Math.PI * s.pulse_hz * time) * s.pulse_amp + level * s.level_gain : 0;
  const r = w * (0.24 + pulse);
  const flash = quality === "full" && s.flash_hz > 0 ? 0.7 + 0.3 * Math.sin(2 * Math.PI * s.flash_hz * time) : 1;  // Blinken nur im vollen Modus
  const glow = g.createRadialGradient(cx, cy, r * 0.2, cx, cy, r * 2.1);
  glow.addColorStop(0, rgba(s.color, s.glow * flash));
  glow.addColorStop(1, rgba(s.color, 0));
  g.fillStyle = glow;
  g.beginPath(); g.arc(cx, cy, r * 2.1, 0, Math.PI * 2); g.fill();
  const rings = quality === "off" ? Math.min(s.rings, 1) : s.rings;
  const centre = { x: cx, y: cy };
  for (let k = 0; k < rings; k++) { ring(g, centre, r, k, time, s, "back"); g.restore(); }  // Hinterseite der Ringe liegt hinter der Kugel
  const body = g.createRadialGradient(cx - r * 0.35, cy - r * 0.4, r * 0.1, cx, cy, r);
  body.addColorStop(0, rgba("#ffffff", 0.55));
  body.addColorStop(0.25, rgba(s.color, 1));
  body.addColorStop(1, rgba("#000000", 0.7));
  g.fillStyle = body;
  g.beginPath(); g.arc(cx, cy, r, 0, Math.PI * 2); g.fill();
  if (quality === "full") {  // Meridiane drehen sich: erzeugt den 3D-Eindruck
    g.strokeStyle = rgba("#ffffff", 0.18);
    g.lineWidth = 1;
    for (let i = 0; i < 4; i++) {
      g.beginPath(); g.ellipse(cx, cy, Math.abs(r * Math.cos(s.spin * time + i * Math.PI / 4)), r, 0, 0, Math.PI * 2); g.stroke();
    }
    g.beginPath(); g.ellipse(cx, cy, r, r * 0.28, 0, 0, Math.PI * 2); g.stroke();
  }
  for (let k = 0; k < rings; k++) {
    const dims = ring(g, centre, r, k, time, s, "front");
    if (quality === "full") {  // Energieteilchen laufen auf dem Ring
      const n = Math.floor(s.particles / Math.max(1, rings));
      g.fillStyle = rgba(s.color, 0.95);
      for (let j = 0; j < n; j++) {
        const a = s.spin * time * 2 * (k % 2 ? -1 : 1) + j * 2 * Math.PI / n;
        g.beginPath(); g.arc(dims.rx * Math.cos(a), dims.ry * Math.sin(a), 2.5, 0, Math.PI * 2); g.fill();
      }
    }
    g.restore();
  }
}

function canvasNow() { return el(document.body.dataset.mode === "orb" ? "orb" : "orb-mini"); }

function redraw(t) {
  drawCore(t || lastT, canvasNow(), effective());
  document.body.dataset.effects = effective();
  schedule();
}

function schedule() {
  if (!rafId && effective() !== "off") rafId = requestAnimationFrame(frame);
}

// Leistungsueberwachung: nur lokal; verzichtet auf Effekte, aendert sonst nichts.
function monitorFrame(dt) {
  const q = effective();
  if (q === "off" || dt <= 0 || dt > 1000) return;  // Pausen (Tab im Hintergrund) zaehlen nicht
  ema = ema * 0.9 + dt * 0.1;
  slowFrames = ema > (q === "full" ? SLOW_FULL_MS : SLOW_REDUCED_MS) ? slowFrames + 1 : Math.max(0, slowFrames - 1);
  if (slowFrames < SLOW_LIMIT) return;
  autoEffects = q === "full" ? "reduced" : "off";
  slowFrames = 0;
  ema = 16;
  el("effects-note").textContent = "Effekte wegen geringer Leistung automatisch reduziert";
}

function frame(t) {
  rafId = 0;
  const q = effective();
  if (q === "off") { redraw(t); return; }
  if (q === "reduced" && lastT && t - lastT < 50) { schedule(); return; }  // ca. 20 Bilder/s
  monitorFrame(lastT ? t - lastT : 0);
  lastT = t;
  redraw(t);
}

function setEffects(value) {
  userEffects = RANK[value] === undefined ? "full" : value;
  autoEffects = "full";  // eine bewusste Wahl setzt die automatische Reduktion zurueck
  slowFrames = 0;
  ema = 16;
  el("effects-note").textContent = reduceMotion ? "Bewegung vom System reduziert (prefers-reduced-motion)" : "";
  drawWave();
  redraw();
}

async function loadCoreTable() {
  try {
    const r = await fetch(url("core_states.json"), { method: "GET" });
    if (r.ok) coreTable = await r.json();
  } catch (e) { coreTable = null; /* ohne Tabelle bleibt der Kern neutral; gezeigt wird weiterhin nur der gemeldete Zustand */ }
  setState(currentState);
}

el("effects").addEventListener("change", (e) => setEffects(el("effects").value));
el("mode-toggle").addEventListener("click", () => { manualMode = true; setMode(document.body.dataset.mode === "orb" ? "dashboard" : "orb"); });
el("voice-start").addEventListener("click", () => send("start_voice", {}));  // einzige Stelle, die das Mikrofon anfordert: ausdruecklicher Knopfdruck
el("voice-stop").addEventListener("click", () => send("stop_voice", {}));
el("emergency").addEventListener("click", () => send("emergency_stop", {}));
el("input-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const text = el("input").value.trim();
  if (text) { send("submit_text", { text: text }); el("input").value = ""; }
});

setMode("orb");
setEffects("full");
renderVoice();
loadCoreTable();
connect();
