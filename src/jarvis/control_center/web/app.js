"use strict";
// Control Center (cc-shell): zeigt den UI-Vertrag v1. Ereignisse per SSE, Befehle per POST. Kein Fremdcode, keine externen Adressen.
const params = new URLSearchParams(location.search);
const token = params.get("t") || "";
const STATE_TEXT = { ready: "bereit", listening: "hoert zu", processing: "arbeitet", speaking: "spricht", awaiting_confirmation: "wartet auf Rueckfrage", error: "Fehler", emergency: "NOTAUS" };
const STATE_COLOR = { ready: "#4fb3ff", listening: "#5dffb0", processing: "#ffd24f", speaking: "#c58bff", awaiting_confirmation: "#ff9f4f", error: "#ff6b6b", emergency: "#ff2a2a" };
const MAX_LIST = 200;
let lastSeq = 0;
let source = null;
let counter = 0;
let level = 0;
let currentState = "ready";
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
}

function addItem(list, text, cls) {
  const li = document.createElement("li");
  li.textContent = text;
  if (cls) li.className = cls;
  list.appendChild(li);
  while (list.children.length > MAX_LIST) list.removeChild(list.firstChild);
  list.scrollTop = list.scrollHeight;
}

function setState(state, detail) {
  currentState = STATE_TEXT[state] ? state : "error";
  document.body.dataset.state = currentState;
  el("state-label").textContent = STATE_TEXT[currentState] + (detail ? ": " + detail : "");
  el("orb-caption").textContent = detail || "";
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
    case "voice_level": level = Math.max(0, Math.min(1, d.level)); break;
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

function drawOrb(t, c) {
  const g = c.getContext("2d");
  const w = c.width, h = c.height, cx = w / 2, cy = h / 2;
  g.clearRect(0, 0, w, h);
  const color = STATE_COLOR[currentState] || STATE_COLOR.ready;
  const pulse = reduceMotion ? 0 : Math.sin(t / 600) * 0.04 + level * 0.12;
  const r = w * (0.28 + pulse);
  const grad = g.createRadialGradient(cx, cy, r * 0.1, cx, cy, r * 1.6);
  grad.addColorStop(0, color);
  grad.addColorStop(0.5, color + "88");
  grad.addColorStop(1, "#00000000");
  g.fillStyle = grad;
  g.beginPath(); g.arc(cx, cy, r * 1.6, 0, Math.PI * 2); g.fill();
  g.fillStyle = color;
  g.beginPath(); g.arc(cx, cy, r, 0, Math.PI * 2); g.fill();
}

function loop(t) {
  drawOrb(t, el(document.body.dataset.mode === "orb" ? "orb" : "orb-mini"));
  if (!reduceMotion) requestAnimationFrame(loop);
}

el("mode-toggle").addEventListener("click", () => { manualMode = true; setMode(document.body.dataset.mode === "orb" ? "dashboard" : "orb"); });
el("emergency").addEventListener("click", () => send("emergency_stop", {}));
el("input-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const text = el("input").value.trim();
  if (text) { send("submit_text", { text: text }); el("input").value = ""; }
});

setMode("orb");
requestAnimationFrame(loop);
connect();
