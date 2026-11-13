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

function url(path, since, params) {
  const q = new URLSearchParams({ t: token });
  if (since) q.set("since", String(since));
  for (const k of Object.keys(params || {})) q.set(k, params[k]);
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
  el("orb-state").textContent = look(currentState).label;
  renderStatus();
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
const STATUS_DE = { PENDING: "wartet", QUEUED: "wartet", RUNNING: "laeuft", SUCCEEDED: "erfolgreich", FAILED: "fehlgeschlagen", CANCELLED: "abgebrochen", BLOCKED: "blockiert" };
function statusDe(status) { const k = String(status).toUpperCase(); return STATUS_DE[k] ? status + " (" + STATUS_DE[k] + ")" : String(status); }
function isFinal(t) { return FINAL.has(String(t.status).toUpperCase()); }

function upsertTask(kind, id, patch) {
  const key = taskKey(kind, id);
  const t = tasks.get(key) || { kind: kind, id: id, title: id, status: "", note: "", detail: "", cancellable: false, listed: false, history: [] };
  Object.assign(t, patch);
  const st = String(t.status || "");
  if (st && t.history[t.history.length - 1] !== st) { t.history.push(st); if (t.history.length > 12) t.history.shift(); }   // Statusfolge nur aus echten Meldungen
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
  line(box, "Status", statusDe(t.status));
  if (t.history.length > 1) line(box, "Verlauf", t.history.join(" -> "));
  const bad = ["FAILED", "BLOCKED"].includes(String(t.status).toUpperCase());
  if (bad) line(box, "Fehler", t.detail || t.note || "das Backend nannte keinen Grund");
  const res = results.get(t.id);
  if (res) line(box, "Ergebnis", res.summary);
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
    if (t) {
      const go = document.createElement("button");
      go.type = "button";
      go.textContent = "Zur Aufgabe";
      go.addEventListener("click", () => { selected = taskKey(t.kind, t.id); renderDashboard(); });
      li.appendChild(go);
    }
    line(li, "Zusammenfassung", r.summary);
    for (const a of r.artifacts) line(li, "Beleg (" + a.kind + ")", a.name + " - " + a.ref);  // Verweise sind reiner Text, nie ein Link
    ul.appendChild(li);
  }
  if (!results.size) addItem(ul, "noch keine Ergebnisse");
}

// ---- Zeitleiste (WP07b): Aufgaben je Agent in zeitlicher Reihenfolge (aelteste oben), nur lesend aus /view/agents. Texte per textContent; Aktualisierung hoechstens 1x/s. ----
const TIMELINE_MAX = 100;     // sichtbare Eintraege; der Rest wird als "+N weitere" gemeldet
const TIMELINE_STATES = ["pending", "running", "succeeded", "failed", "blocked", "cancelled"];
let timelineLast = 0;
let timelineTimer = null;

function clockOf(iso) {
  const m = /T(\d\d:\d\d:\d\d)/.exec(String(iso || ""));
  return m ? m[1] : "";
}

function renderTimeline(data) {
  const ul = el("timeline-list");
  const note = el("timeline-note");
  ul.replaceChildren();
  if (!data || typeof data !== "object") { note.textContent = "nicht abrufbar"; return; }
  if (!data.available) { note.textContent = data.reason || "nicht verfuegbar"; return; }
  const all = Array.isArray(data.items) ? data.items.slice().reverse() : [];  // die Ansicht liefert neueste zuerst; die Zeitleiste zeigt die aeltesten oben
  const hidden = Math.max(0, all.length - TIMELINE_MAX);
  for (const it of all.slice(hidden)) {
    if (!it || typeof it !== "object") continue;
    const li = document.createElement("li");
    const status = String(it.status || "").toLowerCase();
    li.dataset.status = TIMELINE_STATES.includes(status) ? status : "unknown";
    const head = document.createElement("div");
    head.className = "tl-head";
    head.textContent = (clockOf(it.started_at) || "-") + (it.finished_at ? " - " + clockOf(it.finished_at) : "") + "  " + String(it.agent_id || "-") + "  [" + String(it.status || "?") + "]";
    li.appendChild(head);
    const body = document.createElement("div");
    body.className = "tl-body";
    body.textContent = String(it.task_id || "") + " " + String(it.objective || "");
    li.appendChild(body);
    const deps = Array.isArray(it.dependencies) ? it.dependencies.filter((d) => typeof d === "string" && d) : [];
    if (deps.length) { const d = document.createElement("div"); d.className = "tl-dep"; d.textContent = "abhaengig von " + deps.join(", "); li.appendChild(d); }
    if (it.error_code) { const e = document.createElement("div"); e.className = "tl-err"; e.textContent = "Fehlercode: " + String(it.error_code); li.appendChild(e); }
    ul.appendChild(li);
  }
  note.textContent = all.length ? all.length + " Aufgaben" + (hidden ? " (+" + hidden + " weitere, aeltere ausgeblendet)" : "") : "keine Aufgaben";
}

async function loadTimeline() {
  timelineLast = Date.now();
  try {
    const r = await fetch(url("view/agents", 0, { limit: String(TIMELINE_MAX) }), { method: "GET" });
    const data = await r.json();
    if (!r.ok) { renderTimeline(null); el("timeline-note").textContent = "Abgelehnt: " + (data && data.error ? data.error : r.status); return; }
    renderTimeline(data);
  } catch (e) {
    renderTimeline(null);
  }
}

// ---- Mission Control (V2.1 M6): eine nur lesende Uebersicht aus /view/mission (GET). Texte per textContent; kein Befehl, keine Freigabe, kein Abbrechen. ----
const MISSION_STATES = ["pending", "running", "succeeded", "failed", "blocked", "cancelled"];

function missionLine(parent, text, status) {
  const li = document.createElement("li");
  if (status !== undefined) li.dataset.status = MISSION_STATES.includes(String(status).toLowerCase()) ? String(status).toLowerCase() : "unknown";
  li.textContent = text;
  parent.appendChild(li);
  return li;
}

function missionSection(id, data, rows) {
  const ul = el(id);
  ul.replaceChildren();
  if (!data || typeof data !== "object") { missionLine(ul, "nicht abrufbar"); return; }
  if (!data.available) { missionLine(ul, String(data.reason || "nicht verfuegbar")); return; }
  const list = rows(data);
  if (!list.length) missionLine(ul, "keine Eintraege");
  for (const t of list) missionLine(ul, t);
}

function renderMission(data) {
  const note = el("mission-note");
  const graph = el("mission-graph");
  graph.replaceChildren();
  for (const id of ["mission-agents", "mission-errors", "mission-quality", "mission-business", "mission-memory"]) el(id).replaceChildren();
  el("mission-budget").textContent = "";
  el("mission-progress").value = 0;
  el("mission-progress-note").textContent = "";
  if (!data || typeof data !== "object") { note.textContent = "nicht abrufbar"; return; }
  if (!data.available) { note.textContent = String(data.reason || "nicht verfuegbar"); return; }
  const g = data.graph && typeof data.graph === "object" ? data.graph : {};
  const nodes = Array.isArray(g.nodes) ? g.nodes.filter((n) => n && typeof n === "object") : [];
  const byId = new Map(nodes.map((n) => [String(n.id), n]));
  (Array.isArray(g.waves) ? g.waves : []).forEach((wave, i) => {
    const li = document.createElement("li");
    li.className = "mission-wave";
    const head = document.createElement("div");
    head.className = "tl-head";
    head.textContent = "Welle " + (i + 1) + (i === 0 ? " (ohne Voraussetzung)" : "");
    li.appendChild(head);
    const ul = document.createElement("ul");
    for (const id of Array.isArray(wave) ? wave : []) {
      const n = byId.get(String(id)) || { id };
      const deps = Array.isArray(n.deps) && n.deps.length ? "  <- " + n.deps.join(", ") : "";
      missionLine(ul, String(n.id) + "  " + String(n.agent || "-") + "  [" + String(n.status || "?") + "]  " + String(n.objective || "") + deps, n.status);
    }
    li.appendChild(ul);
    graph.appendChild(li);
  });
  if (Array.isArray(g.blocked_by_failure) && g.blocked_by_failure.length) { const li = document.createElement("li"); li.className = "tl-err"; li.textContent = "Blockiert durch einen Fehlschlag: " + g.blocked_by_failure.join(", "); graph.appendChild(li); }
  if (Array.isArray(g.cycle) && g.cycle.length) { const li = document.createElement("li"); li.className = "tl-err"; li.textContent = "Zyklus in den Abhaengigkeiten: " + g.cycle.join(", "); graph.appendChild(li); }
  if (Array.isArray(g.external_deps) && g.external_deps.length) { const li = document.createElement("li"); li.className = "tl-dep"; li.textContent = "Voraussetzung ausserhalb des Fensters: " + g.external_deps.join(", "); graph.appendChild(li); }
  const agents = data.agents && typeof data.agents === "object" ? data.agents : null;
  missionSection("mission-agents", agents, (a) => (Array.isArray(a.items) ? a.items : []).map((x) => String(x.id) + "  [" + String(x.status) + "]  laeuft " + (x.running | 0) + ", wartet " + (x.pending | 0) + (x.reason ? "  - " + String(x.reason) : "")));
  const b = data.budget && typeof data.budget === "object" ? data.budget : null;
  if (!b) el("mission-budget").textContent = "nicht abrufbar";
  else if (!b.available || !b.session) el("mission-budget").textContent = String(b.reason || "nicht verfuegbar");
  else {
    const s = b.session;
    el("mission-budget").textContent = "Aufrufe " + (s.calls | 0) + "/" + (s.max_calls | 0) + ", Laufzeit " + Number(s.elapsed || 0).toFixed(0) + "/" + Number(s.max_seconds || 0).toFixed(0) + " s" + (s.exhausted ? "  ERSCHOEPFT: " + String(s.exhausted) : "");
  }
  const p = data.progress && typeof data.progress === "object" ? data.progress : null;
  if (p && p.available) {
    el("mission-progress").value = Math.max(0, Math.min(100, p.percent | 0));
    const by = p.by_status && typeof p.by_status === "object" ? Object.entries(p.by_status).map(([k, v]) => k + " " + v).join(", ") : "";
    el("mission-progress-note").textContent = (p.finished | 0) + " von " + (p.total | 0) + " Aufgaben abgeschlossen (" + (p.percent | 0) + " %)" + (by ? "  - " + by : "");
  }
  missionSection("mission-errors", data.errors && typeof data.errors === "object" ? data.errors : null, (d) => (Array.isArray(d.items) ? d.items : []).map((x) => String(x.task_id) + "  " + String(x.agent || "-") + "  " + String(x.code)));
  const q = data.quality && typeof data.quality === "object" ? data.quality : null;
  missionSection("mission-quality", q, (d) => (Array.isArray(d.items) ? d.items : []).map((x) => String(x.task_id) + "  " + (x.accepted ? "angenommen" : "NICHT angenommen") + "  (Agent meldet: " + String(x.self_reported || "?") + ")"
    + (Array.isArray(x.failed) && x.failed.length ? "  fehlgeschlagen: " + x.failed.join(", ") : "") + (Array.isArray(x.unknown) && x.unknown.length ? "  ungeprueft: " + x.unknown.join(", ") : "")));
  const biz = data.business && typeof data.business === "object" ? data.business : null;
  missionSection("mission-business", biz, (d) => (Array.isArray(d.items) ? d.items : []).map((x) => String(x.task_id) + "  " + String(x.agent_id) + "/" + String(x.kind || "-") + "  Sicherheit " + String(x.confidence || "UNKNOWN")
    + ", " + (x.unknowns | 0) + " unbekannt, " + (x.sources | 0) + " Quellen  - " + String(x.summary || "")));
  const m = data.memory && typeof data.memory === "object" ? data.memory : null;
  missionSection("mission-memory", m, (d) => (Array.isArray(d.projects) ? d.projects : []).map((x) => String(x.project) + "  " + Object.entries(x.counts && typeof x.counts === "object" ? x.counts : {}).map(([k, v]) => k + " " + v).join(", ")
    + "  Widersprueche " + (x.conflicts | 0) + ", veraltet " + (x.stale | 0) + ", Vorschlaege " + (x.suggestions | 0)));
  note.textContent = nodes.length ? nodes.length + " Aufgaben" + (g.truncated ? " (aeltere ausgeblendet)" : "") : "keine Aufgaben";
}

async function loadMission() {
  try {
    const r = await fetch(url("view/mission", 0, { limit: String(TIMELINE_MAX) }), { method: "GET" });
    const data = await r.json();
    if (!r.ok) { renderMission(null); el("mission-note").textContent = "Abgelehnt: " + (data && data.error ? data.error : r.status); return; }
    renderMission(data);
  } catch (e) {
    renderMission(null);
  }
}

// Aufgabenereignisse laden die Zeitleiste neu, aber hoechstens einmal pro Sekunde (ein wartender Abruf genuegt).
function scheduleTimeline() {
  if (timelineTimer !== null) return;
  const wait = timelineLast + 1000 - Date.now();
  if (wait <= 0) { loadTimeline(); return; }
  timelineTimer = setTimeout(() => { timelineTimer = null; loadTimeline(); }, wait);
}

function renderDashboard() { renderTasks(); renderDetail(); renderAgents(); renderResults(); renderStatus(); }

// Systemstatus (Premium V2): nur Werte, die diese Seite aus echten Backend-Ereignissen kennt; ohne Meldung steht dort "unbekannt", nie ein erfundener Wert.
function renderStatus() {
  const conn = document.body.dataset.conn;
  const active = [...tasks.values()].filter((t) => t.listed && !isFinal(t)).length;
  const agents = new Set();
  for (const [taskId, r] of routes) { const t = taskById(taskId); if (t && !isFinal(t) && t.listed) agents.add(r.agent); }
  el("st-conn").textContent = conn === "open" ? "verbunden" : conn === "closed" ? "GETRENNT" : "verbinde ...";
  el("st-state").textContent = look(currentState).label;
  el("st-emergency").textContent = emergencyOn ? "AKTIV" : "nicht aktiv";
  el("st-voice").textContent = voiceActive === null ? "unbekannt" : voiceActive ? "an" : "aus";
  el("st-tasks").textContent = active + " aktiv, " + tasks.size + " bekannt";
  el("st-agents").textContent = agents.size + " aktiv";
  el("st-results").textContent = String(results.size);
  el("st-confirm").textContent = pending.size ? pending.size + " offen" : "keine";
  el("st-effects").textContent = effective();
  el("st-seq").textContent = String(lastSeq);
  document.body.dataset.pending = pending.size ? "yes" : "no";
}

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
  renderApprovals();
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
  updateApprovalRemaining();
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
  scheduleApprovalHistory();
}

// Verbindungsverlust: der Server lehnt ab (detach); die Oberflaeche zeigt nichts Beantwortbares mehr an.
function clearConfirmations() {
  pending.clear();
  renderConfirmation();
}

// ---- Freigaben (WP07c): ALLE offenen Rueckfragen (aelteste zuerst) mit Frist und der angebotenen Auswahl, dazu der Verlauf aus dem Audit (nur Zeit, Art, Werkzeug, Aktion, Stufe, Status, Regel).
// Reine Anzeige, KEIN Schreibweg und keine Knoepfe: beantwortet wird allein im Rueckfrage-Dialog (answer() -> `confirm`, nur Angebotenes, "Ablehnen" zuerst); nichts wird je automatisch gesendet.
const APPROVAL_HISTORY_MAX = 100;
const APPROVAL_KINDS = { confirmation_requested: "angefragt", confirmation_accepted: "erlaubt", confirmation_rejected: "abgelehnt" };
const approvalRows = new Map();   // request_id -> { rem, li }
let approvalsHistLast = 0;
let approvalsHistTimer = null;

function remainingText(q) {
  const left = Math.max(0, Math.ceil((q.deadline - Date.now()) / 1000));
  return { left: left, text: "Frist: " + (left > 0 ? left + " s (danach abgelehnt)" : "abgelaufen - gilt als abgelehnt") };
}

function renderApprovals() {
  const ul = el("approvals-list");
  ul.replaceChildren();
  approvalRows.clear();
  for (const q of pending.values()) {  // die Map haelt die Reihenfolge des Eintreffens: aelteste zuerst
    const li = document.createElement("li");
    li.dataset.kind = "open";
    const head = document.createElement("div");
    head.className = "ap-head";
    head.textContent = q.tool + " / " + q.action + " (" + q.level + ")";
    li.appendChild(head);
    for (const [cls, value] of [["ap-reason", q.reason], ["ap-resource", q.resource]]) {
      const d = document.createElement("div");
      d.className = cls;
      d.textContent = String(value == null ? "" : value);
      li.appendChild(d);
    }
    const rem = document.createElement("div");
    rem.className = "ap-rem";
    li.appendChild(rem);
    const offered = document.createElement("div");           // reine Anzeige: beantwortet wird allein im Rueckfrage-Dialog (modal, "Ablehnen" zuerst), hier gibt es keine Knoepfe
    offered.className = "ap-choices";
    offered.textContent = "angeboten: " + DENY_FIRST.filter((c) => q.choices.includes(c)).map((c) => CHOICE_TEXT[c]).join(", ");
    li.appendChild(offered);
    ul.appendChild(li);
    approvalRows.set(q.request_id, { rem: rem, li: li });
  }
  el("approvals-note").textContent = pending.size ? pending.size + " offen (aelteste zuerst)" : "keine offenen Freigaben";
  updateApprovalRemaining();
}

function updateApprovalRemaining() {
  for (const [id, row] of approvalRows) {
    const q = pending.get(id);
    if (!q) continue;
    row.rem.textContent = remainingText(q).text;
  }
}

function renderApprovalHistory(items, note, hidden) {
  const ul = el("approvals-history");
  ul.replaceChildren();
  for (const it of items) {
    const li = document.createElement("li");
    li.dataset.kind = APPROVAL_KINDS[it.type] ? it.type : "unknown";
    const clock = /T(\d\d:\d\d:\d\d)/.exec(String(it.timestamp || ""));
    li.textContent = (clock ? clock[1] : "-") + "  " + (APPROVAL_KINDS[it.type] || "?") + "  " + String(it.tool || "-") + " / " + String(it.action || "-") + " (" + String(it.level || "-") + ")"
      + (it.status ? "  [" + String(it.status) + "]" : "") + (it.rule ? "  Regel " + String(it.rule) : "");
    ul.appendChild(li);
  }
  el("approvals-history-note").textContent = note + (hidden ? " (+" + hidden + " weitere, aeltere ausgeblendet)" : "");
}

async function loadApprovalHistory() {
  approvalsHistLast = Date.now();
  try {
    const replies = await Promise.all(Object.keys(APPROVAL_KINDS).map(async (k) => {
      const r = await fetch(url("view/audit", 0, { type: k, limit: String(APPROVAL_HISTORY_MAX) }), { method: "GET" });
      return { ok: r.ok, data: await r.json() };
    }));
    const seen = new Set();
    let all = [];
    let reason = "";
    for (const r of replies) {
      if (!r.ok || !r.data || !r.data.available) { reason = reason || (r.data && (r.data.reason || r.data.error)) || "nicht verfuegbar"; continue; }
      for (const it of Array.isArray(r.data.items) ? r.data.items : []) {
        const key = it && it.id ? String(it.id) : null;
        if (!it || typeof it !== "object" || (key && seen.has(key))) continue;
        if (key) seen.add(key);
        all.push(it);
      }
    }
    if (!all.length && reason) { renderApprovalHistory([], reason, 0); return; }
    all.sort((a, b) => String(b.timestamp || "").localeCompare(String(a.timestamp || "")));  // neueste zuerst
    const hidden = Math.max(0, all.length - APPROVAL_HISTORY_MAX);
    renderApprovalHistory(all.slice(0, APPROVAL_HISTORY_MAX), all.length ? all.length + " Ereignisse" : "keine Ereignisse", hidden);
  } catch (e) {
    renderApprovalHistory([], "nicht abrufbar (getrennt)", 0);
  }
}

// Geschlossene Rueckfragen laden den Verlauf neu, hoechstens einmal pro Sekunde (ein wartender Abruf genuegt).
function scheduleApprovalHistory() {
  if (approvalsHistTimer !== null) return;
  const wait = approvalsHistLast + 1000 - Date.now();
  if (wait <= 0) { loadApprovalHistory(); return; }
  approvalsHistTimer = setTimeout(() => { approvalsHistTimer = null; loadApprovalHistory(); }, wait);
}

// ---- Tastatur ----------------------------------------------------------------------------------------------------------------------------
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
  renderStatus();
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
    case "task_update": onTaskUpdate(d); scheduleTimeline(); break;
    case "routing": onRouting(d); break;
    case "result": onResult(d); scheduleTimeline(); break;
    case "confirmation_request": openConfirmation(d); break;
    case "confirmation_closed": closeConfirmation(d); break;
    case "emergency": setEmergency(d.engaged); if (d.engaged) setState("emergency", d.reason); break;
    case "voice_level": onVoiceLevel(d); break;
    case "error": addItem(el("chat"), "Fehler " + d.code + ": " + d.message, "system"); break;
    case "ack": if (!d.ok) addItem(el("chat"), "Abgelehnt (" + d.code + "): " + d.message, "system"); break;
    default: break;
  }
  renderStatus();
}

function connect() {
  source = new EventSource(url("events", lastSeq));
  source.onopen = () => { document.body.dataset.conn = "open"; el("conn").textContent = "verbunden"; renderStatus(); };
  source.onmessage = (m) => { try { handle(JSON.parse(m.data)); } catch (e) { /* ungueltiges Ereignis ignorieren */ } };
  source.onerror = () => {
    document.body.dataset.conn = "closed";
    setState(null);  // der letzte Zustand ist unbekannt, solange die Verbindung fehlt
    resetVoice();
    clearConfirmations();
    el("conn").textContent = "GETRENNT";
    renderStatus();
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

// ---- Verlauf und Audit (cc-results-audit): nur lesend. Abruf nur auf Knopfdruck (GET), ohne Zeitgeber; gezeigt wird nur, was das Backend liefert. ------------
function viewItem(list, text, cls) {
  const li = document.createElement("li");
  li.textContent = text;
  if (cls) li.className = cls;
  list.appendChild(li);
  return li;
}

function renderHistory(list, items) {
  for (const it of items) {
    const li = viewItem(list, it.status + " | " + it.kind + " " + it.id + " | " + it.text + (it.recorded_at ? " | " + it.recorded_at : ""));
    const sub = document.createElement("ul");
    if (it.result) viewItem(sub, "Ergebnis: " + it.result);
    if (it.error) viewItem(sub, "Fehler: " + it.error, "error");
    for (const ev of it.evidence || []) viewItem(sub, "Beleg: " + ev);
    for (const st of it.steps || []) {
      viewItem(sub, "Schritt " + st.no + " [" + st.status + (st.side_effect ? ", mit Wirkung" : "") + "]: " + st.text + (st.result ? " -> " + st.result : "") + (st.error ? " (Fehler: " + st.error + ")" : ""));
    }
    li.appendChild(sub);
  }
}

function renderAudit(list, items) {
  for (const it of items) {
    const parts = [it.timestamp, it.type, it.tool, it.action, it.resource, it.level ? "Stufe " + it.level : "", it.status].filter((p) => p);
    const li = viewItem(list, parts.join(" | "));
    const sub = document.createElement("ul");
    if (it.detail) viewItem(sub, "Detail: " + it.detail);
    if (it.rule) viewItem(sub, "Regel: " + it.rule);
    if (it.request_id) viewItem(sub, "Anfrage: " + it.request_id);
    for (const k of Object.keys(it.extra || {})) viewItem(sub, k + ": " + it.extra[k]);
    li.appendChild(sub);
  }
}

const DOCTOR_STATE = { ok: "bereit", hint: "Hinweis", off: "aus" };

function renderDoctor(list, items, data) {
  el("doctor-summary").textContent = "Python " + data.python + " (" + data.platform + "), JARVIS " + data.jarvis + " | " + data.errors + " Fehler, " + data.hints + " Hinweis(e)"
    + " | Sicherheitsmodus " + (data.security && data.security.mode) + ", Rückfragen: " + (data.security && data.security.confirmation);
  for (const c of data.components || []) viewItem(list, (DOCTOR_STATE[c.state] || c.state) + " | " + c.name + ": " + c.text, "doctor-" + c.state);
  for (const a of data.agents || []) viewItem(list, "Agent " + a.id + ": " + a.status + (a.reason ? " (" + a.reason + ")" : ""), a.status === "AVAILABLE" ? "doctor-ok" : "doctor-off");
  const keys = Object.keys(data.keys || {}).map((k) => k + ": " + (data.keys[k] ? "gesetzt" : "nicht gesetzt"));
  if (keys.length) viewItem(list, "Schlüssel (nur gesetzt/nicht gesetzt): " + keys.join("; "));
  for (const it of items) viewItem(list, it.level + ": " + it.text, it.level === "FEHLER" ? "error" : "");
  if (data.note) viewItem(list, data.note);
}

async function loadView(which, params) {
  const note = el(which + "-note");
  const list = el(which + "-list");
  note.textContent = "lade ...";
  try {
    const r = await fetch(url("view/" + which, 0, params), { method: "GET" });
    const data = await r.json();
    list.replaceChildren();
    if (!r.ok) { note.textContent = "Abgelehnt: " + (data && data.error ? data.error : r.status); return; }
    const items = Array.isArray(data.items) ? data.items : [];
    if (!data.available) { note.textContent = data.reason || "nicht verfuegbar"; return; }
    note.textContent = which === "doctor" ? "Stand: jetzt geprüft (nur lesend, es wird nichts eingeschaltet)" : (items.length ? items.length + " Eintraege (hoechstens " + data.limit + ")" : "keine Eintraege");
    if (which === "doctor") renderDoctor(list, items, data); else (which === "history" ? renderHistory : renderAudit)(list, items);
  } catch (e) {
    list.replaceChildren();
    note.textContent = "nicht abrufbar (getrennt)";
  }
}

function viewParams(which, fields) {
  const p = { limit: el(which + "-limit").value || "50" };
  for (const f of fields) {
    const v = String(el(which + "-" + f).value || "").trim();
    if (v) p[f] = f === "status" && which === "history" ? v.toUpperCase() : v;
  }
  return p;
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

// ---- Kern (Premium V2): Kugel mit Tiefe (Nebel, Gitter, Randlicht, Glanz), Ringe, Energieteilchen, Staub. Reine Anzeige: die Farbe des Zustands kommt aus der Tabelle, ----------
// die Grundfarben der Kugel (Violett/Blau) aendern nie, welcher Zustand gemeldet wird. Stufen: full (voll animiert), reduced (ruhig, ca. 20 Bilder/s), off (flacher 2D-Fallback, einmal gezeichnet).
const VIOLET = "#7b4dff", BLUE = "#3b6bff", INDIGO = "#2a2a9a", DEEP = "#0a0626", WHITE = "#ffffff";
const DUST = [];
for (let i = 0; i < 36; i++) DUST.push({ a: (i * 2.399963) % (2 * Math.PI), d: 1.4 + ((i * 37) % 100) / 100 * 0.85, sz: 0.8 + ((i * 53) % 10) / 10 * 1.6, sp: 0.04 + ((i * 17) % 10) / 100, ph: i * 0.7 });

function ring(g, c, r, k, time, s, half, quality) {
  const rx = r * (1.45 + 0.2 * k), ry = rx * 0.32;
  g.save();
  g.translate(c.x, c.y);
  g.rotate((k % 2 ? -1 : 1) * s.spin * time * 0.5 + k * 0.9);
  g.strokeStyle = rgba(s.color, half === "back" ? 0.22 : 0.85);
  g.lineWidth = half === "back" ? 1.5 : 2.2;
  if (quality === "full" && half !== "back") { g.shadowColor = rgba(s.color, 0.9); g.shadowBlur = 14; }
  g.beginPath();
  if (half === "back") g.ellipse(0, 0, rx, ry, 0, Math.PI, 2 * Math.PI); else g.ellipse(0, 0, rx, ry, 0, 0, Math.PI);
  g.stroke();
  return { rx: rx, ry: ry };
}

function disc(g, x, y, r) { g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); }

function drawNebula(g, cx, cy, r, s, time) {
  g.globalCompositeOperation = "lighter";
  for (let i = 0; i < 4; i++) {
    const ang = time * (0.18 + 0.05 * i) * (i % 2 ? -1 : 1) * (0.4 + s.spin) + i * 1.7;
    const bx = cx + Math.cos(ang) * r * 0.5, by = cy + Math.sin(ang * 1.3) * r * 0.42;
    const blob = g.createRadialGradient(bx, by, 0, bx, by, r * 0.75);
    blob.addColorStop(0, rgba(i % 2 ? BLUE : VIOLET, 0.55));
    blob.addColorStop(1, rgba(i % 2 ? BLUE : VIOLET, 0));
    g.fillStyle = blob;
    g.fillRect(cx - r, cy - r, 2 * r, 2 * r);
  }
  g.globalCompositeOperation = "source-over";
}

function drawGrid(g, cx, cy, r, s, time) {
  g.lineWidth = 1;
  for (let i = 0; i < 6; i++) {  // Laengenkreise drehen sich: Vorderseite hell, Rueckseite blass (Tiefe)
    const ph = s.spin * time * 0.5 + i * Math.PI / 6;
    const rx = Math.abs(r * Math.cos(ph));
    g.strokeStyle = rgba(WHITE, 0.07 + 0.14 * Math.abs(Math.sin(ph)));
    g.beginPath(); g.ellipse(cx, cy, Math.max(0.5, rx), r, 0, 0, Math.PI * 2); g.stroke();
  }
  for (const lat of [-0.62, -0.32, 0, 0.32, 0.62]) {  // Breitenkreise: vordere Haelfte kraeftiger
    const y = cy + r * lat, hw = r * Math.sqrt(1 - lat * lat), hh = hw * 0.2;
    g.strokeStyle = rgba(WHITE, 0.08);
    g.beginPath(); g.ellipse(cx, y, hw, hh, 0, Math.PI, 2 * Math.PI); g.stroke();
    g.strokeStyle = rgba(WHITE, 0.2);
    g.beginPath(); g.ellipse(cx, y, hw, hh, 0, 0, Math.PI); g.stroke();
  }
}

function drawSphere(g, cx, cy, r, s, time, quality, flash) {
  const body = g.createRadialGradient(cx - r * 0.35, cy - r * 0.4, r * 0.05, cx, cy, r);
  if (quality === "off") {  // flacher 2D-Fallback: zwei Farben, Randlinie in der Zustandsfarbe
    body.addColorStop(0, rgba(VIOLET, 1));
    body.addColorStop(1, rgba(DEEP, 1));
    g.fillStyle = body; disc(g, cx, cy, r); g.fill();
    g.strokeStyle = rgba(s.color, 0.95); g.lineWidth = 3; disc(g, cx, cy, r); g.stroke();
    return;
  }
  body.addColorStop(0, rgba("#c9bbff", 1));
  body.addColorStop(0.16, rgba(VIOLET, 1));
  body.addColorStop(0.55, rgba(INDIGO, 1));
  body.addColorStop(1, rgba(DEEP, 1));
  g.fillStyle = body; disc(g, cx, cy, r); g.fill();
  g.save();
  disc(g, cx, cy, r); g.clip();
  drawNebula(g, cx, cy, r, s, quality === "full" ? time : 0);
  const tint = g.createRadialGradient(cx, cy, 0, cx, cy, r);  // Zustandsfarbe als Kernlicht
  tint.addColorStop(0, rgba(s.color, 0.55 * s.glow * flash));
  tint.addColorStop(0.7, rgba(s.color, 0.12 * s.glow));
  tint.addColorStop(1, rgba(s.color, 0));
  g.fillStyle = tint; g.fillRect(cx - r, cy - r, 2 * r, 2 * r);
  drawGrid(g, cx, cy, r, s, quality === "full" ? time : 0);
  const rim = g.createRadialGradient(cx, cy, r * 0.62, cx, cy, r);  // Fresnel: Randlicht in der Zustandsfarbe
  rim.addColorStop(0, rgba(s.color, 0));
  rim.addColorStop(1, rgba(s.color, 0.75 * flash));
  g.fillStyle = rim; g.fillRect(cx - r, cy - r, 2 * r, 2 * r);
  const spec = g.createRadialGradient(cx - r * 0.38, cy - r * 0.44, 0, cx - r * 0.38, cy - r * 0.44, r * 0.3);
  spec.addColorStop(0, rgba(WHITE, 0.6));
  spec.addColorStop(1, rgba(WHITE, 0));
  g.fillStyle = spec; g.fillRect(cx - r, cy - r, 2 * r, 2 * r);
  g.restore();
  g.strokeStyle = rgba(s.color, 0.9 * flash); g.lineWidth = 1.6; disc(g, cx, cy, r); g.stroke();
}

function drawDust(g, cx, cy, r, s, time) {
  g.fillStyle = rgba(s.color, 0.55);
  for (const d of DUST) {
    const a = d.a + time * d.sp, rad = r * d.d, tw = 0.5 + 0.5 * Math.sin(time * 1.5 + d.ph);
    g.globalAlpha = 0.25 + 0.6 * tw;
    disc(g, cx + Math.cos(a) * rad, cy + Math.sin(a) * rad * 0.8, d.sz); g.fill();
  }
  g.globalAlpha = 1;
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
  const halo = g.createRadialGradient(cx, cy, r * 0.5, cx, cy, r * 1.95);  // violett-blauer Hof hinter dem Zustandsglimmen
  halo.addColorStop(0, rgba(VIOLET, 0.2));
  halo.addColorStop(0.55, rgba(BLUE, 0.06));
  halo.addColorStop(1, rgba(BLUE, 0));
  g.fillStyle = halo; disc(g, cx, cy, r * 1.95); g.fill();
  const glow = g.createRadialGradient(cx, cy, r * 0.2, cx, cy, r * 1.9);
  glow.addColorStop(0, rgba(s.color, s.glow * flash));
  glow.addColorStop(1, rgba(s.color, 0));
  g.fillStyle = glow; disc(g, cx, cy, r * 1.9); g.fill();
  if (quality === "full") drawDust(g, cx, cy, r, s, time);
  const rings = quality === "off" ? Math.min(s.rings, 1) : s.rings;
  const centre = { x: cx, y: cy };
  for (let k = 0; k < rings; k++) { ring(g, centre, r, k, time, s, "back", quality); g.restore(); }  // Hinterseite der Ringe liegt hinter der Kugel
  drawSphere(g, cx, cy, r, s, time, quality, flash);
  for (let k = 0; k < rings; k++) {
    const dims = ring(g, centre, r, k, time, s, "front", quality);
    if (quality === "full") {  // Energieteilchen laufen auf dem Ring
      const n = Math.floor(s.particles / Math.max(1, rings));
      g.fillStyle = rgba(s.color, 0.95);
      for (let j = 0; j < n; j++) {
        const a = s.spin * time * 2 * (k % 2 ? -1 : 1) + j * 2 * Math.PI / n;
        disc(g, dims.rx * Math.cos(a), dims.ry * Math.sin(a), 3); g.fill();
      }
    }
    g.restore();
  }
}

function canvasNow() { return el(document.body.dataset.mode === "dashboard" ? "orb-mini" : "orb"); }

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
  renderStatus();
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

el("timeline-refresh").addEventListener("click", () => loadTimeline());
el("mission-refresh").addEventListener("click", () => loadMission());
el("approvals-refresh").addEventListener("click", () => loadApprovalHistory());
el("doctor-refresh").addEventListener("click", () => loadView("doctor", {}));
el("history-refresh").addEventListener("click", () => loadView("history", viewParams("history", ["kind", "status"])));
el("audit-refresh").addEventListener("click", () => loadView("audit", viewParams("audit", ["type", "tool", "status", "level"])));
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

// Mini-Overlay (?view=overlay, nur durch `jarvis-cc --overlay`): zeigt Kern, Zustand und den Notaus-Knopf; Klick auf den Kern oeffnet das Hauptfenster.
// Rueckfragen beantwortet allein das Hauptfenster (ohne Antwort gilt: abgelehnt). Keine JS-Python-Bruecke: nur derselbe Vertrag per POST.
function enterOverlay() {
  manualMode = true;                                            // nie automatisch ins Dashboard wechseln
  document.body.dataset.mode = "overlay";
  el("overlay-open").hidden = false;
  const open = () => fetch(url("/overlay/open"), { method: "POST", headers: { "Content-Type": "application/json", "X-JARVIS-Token": token }, body: "{}" }).catch(() => {});
  el("overlay-open").addEventListener("click", open);
  el("orb").addEventListener("click", open);
  redraw();
}

setMode("orb");
if (params.get("view") === "overlay") enterOverlay();
setEffects("full");
renderApprovals();
renderVoice();
loadCoreTable();
connect();
