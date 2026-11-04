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

function renderActivity(d) {
  const ul = el("activity");
  ul.replaceChildren();
  for (const it of d.items) addItem(ul, it.title + " [" + it.status + "]" + (it.note ? " - " + it.note : ""));
  el("problems").textContent = d.problems.length ? "Probleme: " + d.problems.map((p) => (typeof p === "string" ? p : JSON.stringify(p))).join("; ") : "";
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
    if (ack && ack.data && ack.data.ok === false) handle(ack);
  } catch (e) {
    addItem(el("chat"), "Befehl nicht gesendet (getrennt)", "system");
  }
}

function drawOrb(t) {
  const c = el("orb");
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
  if (document.body.dataset.mode === "orb") drawOrb(t);
  if (!reduceMotion) requestAnimationFrame(loop);
}

el("mode-toggle").addEventListener("click", () => setMode(document.body.dataset.mode === "orb" ? "dashboard" : "orb"));
el("emergency").addEventListener("click", () => send("emergency_stop", {}));
el("input-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const text = el("input").value.trim();
  if (text) { send("submit_text", { text: text }); el("input").value = ""; }
});

setMode("orb");
requestAnimationFrame(loop);
connect();
